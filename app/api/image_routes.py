"""
Photos, of a dish and of its steps.

Uploads go straight to MinIO and the row keeps only the key; reads hand back a
presigned URL rather than proxying the bytes, so the image traffic never touches
this process.

Two places a photo can land, same table and same storage either way:

  POST /dishes/{uuid}/images  — the gallery. The first becomes the cover.
  POST /steps/{uuid}/images   — beside one instruction. A step takes any number.

The split matters at read time, not write time: a step photo is mid-process and
must never drift into the gallery or become the dish's cover, which is what
`dish_service.gallery_images()` enforces.
"""

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.schemas import DishImageOut, DishImageUpdate, PresignedUrlOut
from app.api.serializers import image_out
from app.db.database import get_db
from app.db.models import Dish, DishImage, RecipeStep, User, generate_uuid
from app.services import dish_service, minio_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["images"])

# A phone photo is 3-6MB; 12 leaves room for a DSLR shot without letting an
# upload become a denial of service.
MAX_IMAGE_BYTES = 12 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/gif": "gif",
}
PRESIGNED_URL_TTL = 3600


async def _read_image(upload: UploadFile) -> tuple[bytes, str, str]:
    """Validate a multipart upload and return (bytes, mime type, extension)."""
    mime_type = (upload.content_type or "").lower()
    extension = ALLOWED_MIME_TYPES.get(mime_type)
    if extension is None:
        # Some browsers send application/octet-stream for a HEIC from the camera
        # roll, so fall back to the filename before giving up.
        name = (upload.filename or "").lower()
        for candidate in set(ALLOWED_MIME_TYPES.values()):
            if name.endswith(f".{candidate}"):
                extension = candidate
                break
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image type '{mime_type or 'unknown'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
        )

    data = await upload.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That file was empty"
        )
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Images have to be under {MAX_IMAGE_BYTES // (1024 * 1024)}MB",
        )
    return data, mime_type or f"image/{extension}", extension


def _load_dish(db: Session, user: User, dish_uuid: str) -> Dish:
    dish = dish_service.get(db, user.id, dish_uuid)
    if dish is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dish not found"
        )
    return dish


def _load_step(db: Session, user: User, step_uuid: str) -> RecipeStep:
    """A step of one of my dishes. Joined through `dishes` so a step uuid from
    somebody else's recipe is a 404, not a way in."""
    step = (
        db.query(RecipeStep)
        .join(Dish, RecipeStep.dish_id == Dish.id)
        .filter(RecipeStep.step_uuid == step_uuid, Dish.user_id == user.id)
        .first()
    )
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Step not found"
        )
    return step


def _load_image(db: Session, user: User, image_uuid: str) -> DishImage:
    image = (
        db.query(DishImage)
        .filter(DishImage.image_uuid == image_uuid, DishImage.user_id == user.id)
        .first()
    )
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image not found"
        )
    return image


@router.post(
    "/dishes/{dish_uuid}/images",
    response_model=DishImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_dish_image(
    dish_uuid: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a photo to a dish. The first one becomes the cover."""
    dish = _load_dish(db, current_user, dish_uuid)
    data, mime_type, extension = await _read_image(file)

    image_uuid = generate_uuid()
    object_key = minio_service.dish_image_key(
        current_user.id, dish.dish_uuid, image_uuid, extension
    )
    if not minio_service.get_minio_service().upload_bytes(data, object_key, mime_type):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not store the photo right now",
        )

    gallery = dish_service.gallery_images(dish)
    image = DishImage(
        image_uuid=image_uuid,
        dish_id=dish.id,
        user_id=current_user.id,
        image_name=file.filename,
        mime_type=mime_type,
        file_size=len(data),
        file_format=extension,
        minio_object_key=object_key,
        minio_bucket=minio_service.MINIO_BUCKET,
        # The first photo is the cover with no further ceremony; a dish whose
        # card shows nothing until you pick a cover looks broken. Counted over
        # the gallery, not every photo, so a dish whose only photos are on its
        # steps still gets a cover the moment one is added here.
        is_cover=not gallery,
        sort_order=len(gallery),
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    logger.info(f"{current_user.username} added a photo to {dish.name}")
    return image_out(image)


@router.get("/dishes/{dish_uuid}/images", response_model=list[DishImageOut])
def list_dish_images(
    dish_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The dish gallery. Step photos come back on the step."""
    dish = _load_dish(db, current_user, dish_uuid)
    return [image_out(image) for image in dish_service.gallery_images(dish)]


@router.post(
    "/steps/{step_uuid}/images",
    response_model=DishImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_step_image(
    step_uuid: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a photo to one step of a recipe. A step can hold any number."""
    step = _load_step(db, current_user, step_uuid)
    data, mime_type, extension = await _read_image(file)

    image_uuid = generate_uuid()
    object_key = minio_service.dish_image_key(
        current_user.id, step.dish.dish_uuid, image_uuid, extension
    )
    if not minio_service.get_minio_service().upload_bytes(data, object_key, mime_type):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not store the photo right now",
        )

    image = DishImage(
        image_uuid=image_uuid,
        dish_id=step.dish_id,
        step_id=step.id,
        user_id=current_user.id,
        image_name=file.filename,
        mime_type=mime_type,
        file_size=len(data),
        file_format=extension,
        minio_object_key=object_key,
        minio_bucket=minio_service.MINIO_BUCKET,
        # Never a cover: a photo of the onions half-fried is not what the dish
        # looks like.
        is_cover=False,
        sort_order=len(step.images),
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    logger.info(
        f"{current_user.username} added a photo to step {step.step_index + 1} "
        f"of {step.dish.name}"
    )
    return image_out(image, step_uuid=step.step_uuid)


@router.get("/steps/{step_uuid}/images", response_model=list[DishImageOut])
def list_step_images(
    step_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    step = _load_step(db, current_user, step_uuid)
    return [image_out(image, step_uuid=step.step_uuid) for image in step.images]


@router.patch("/images/{image_uuid}", response_model=DishImageOut)
def update_image(
    image_uuid: str,
    payload: DishImageUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Caption a photo, reorder it, or make it the cover."""
    image = _load_image(db, current_user, image_uuid)

    if payload.caption is not None:
        image.caption = payload.caption
    if payload.sort_order is not None:
        image.sort_order = payload.sort_order
    if payload.is_cover:
        if image.step_id is not None:
            # A step photo shows a stage, not the dish. Refusing here rather
            # than quietly detaching it from its step keeps "where does this
            # photo live" answerable from the row alone.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A step photo can't be the cover. Add it to the dish's "
                "photos instead.",
            )
        # Exactly one cover per dish, so promoting this one demotes the rest in
        # the same transaction.
        db.query(DishImage).filter(
            DishImage.dish_id == image.dish_id, DishImage.id != image.id
        ).update({DishImage.is_cover: False}, synchronize_session=False)
        image.is_cover = True
    elif payload.is_cover is False:
        image.is_cover = False

    db.commit()
    db.refresh(image)
    return image_out(
        image, step_uuid=image.step.step_uuid if image.step_id else None
    )


@router.get("/images/{image_uuid}/url", response_model=PresignedUrlOut)
def get_image_url(
    image_uuid: str,
    expires_in: int = Query(default=PRESIGNED_URL_TTL, ge=60, le=86400),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A temporary link to view a photo."""
    image = _load_image(db, current_user, image_uuid)
    url = minio_service.generate_presigned_url(image.minio_object_key, expires_in)
    if not url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate an image link right now",
        )
    return PresignedUrlOut(
        image_uuid=image.image_uuid, url=url, expires_in=expires_in
    )


@router.delete("/images/{image_uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    image_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a photo. If it was the cover, the next one takes over."""
    image = _load_image(db, current_user, image_uuid)
    object_key = image.minio_object_key
    dish_id, was_cover = image.dish_id, image.is_cover

    db.delete(image)
    db.flush()

    if was_cover:
        # The next *gallery* photo takes over. A step photo is never a cover, so
        # it is not a candidate to inherit one either.
        successor = (
            db.query(DishImage)
            .filter(DishImage.dish_id == dish_id, DishImage.step_id.is_(None))
            .order_by(DishImage.sort_order, DishImage.id)
            .first()
        )
        if successor:
            successor.is_cover = True

    db.commit()
    minio_service.delete_image(object_key)
