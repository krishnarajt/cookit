"""
Dishes: the book, one dish, its recipe, and getting it back out again.

Two shapes on purpose. The list returns `DishSummary` — what a card needs and
nothing more, so browsing 200 dishes is one small response. `GET
/dishes/{uuid}` returns everything: ingredients with amounts, steps with their
mentions resolved, photos, and what it's often had with.

Writes are replace-whole-collection rather than per-row patching
(`PUT .../ingredients`, `PUT .../steps`). An editor that can reorder by drag has
no stable per-row identity to patch against, and "what you see is what gets
stored" is the only version of that which can't half-save.
"""

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.schemas import (
    CookEventOut,
    CookRequest,
    DishCreate,
    DishDetail,
    DishIngredientsReplace,
    DishSummary,
    DishUpdate,
    PairingRequest,
    StepOut,
    StepsReplace,
)
from app.api.serializers import cook_event_out, dish_detail, dish_summary, step_out
from app.db.database import get_db
from app.db.models import Dish, User
from app.enums import Difficulty, IngredientMatch, MealType
from app.services import (
    dish_service,
    export_service,
    import_service,
    ingredient_service,
    pdf_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dishes", tags=["dishes"])

# Large enough for a very long recipe, small enough that an upload can safely
# be decoded and parsed in memory.
MAX_MARKDOWN_BYTES = 1024 * 1024


def _load(db: Session, user: User, dish_uuid: str) -> Dish:
    dish = dish_service.get(db, user.id, dish_uuid)
    if dish is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dish not found"
        )
    return dish


def _resolve_ingredient_ids(
    db: Session, user: User, uuids: list[str]
) -> tuple[list[int], int]:
    """UUIDs from a query string into internal ids, plus how many didn't resolve.

    Scoped to the caller: a UUID in a request is user input, and an unfiltered
    lookup would let a crafted filter reach across accounts.

    The count of misses is returned rather than thrown away. A UUID that names
    no ingredient of mine matches no dish, and `list_dishes` needs to tell that
    apart from "no ingredient filter at all" — otherwise a stale filter chip
    quietly widens the results to everything.
    """
    wanted = list(dict.fromkeys(uuids or []))
    if not wanted:
        return [], 0
    found = ingredient_service.get_many(db, user.id, wanted)
    return [i.id for i in found], len(wanted) - len(found)


# ---------------------------------------------------------------------------
# The book
# ---------------------------------------------------------------------------

@router.get("", response_model=list[DishSummary])
def list_dishes(
    q: str | None = Query(default=None, max_length=200),
    meal_type: list[MealType] = Query(default=[]),
    ingredient: list[str] = Query(
        default=[], description="Ingredient UUIDs to filter by"
    ),
    match: IngredientMatch = IngredientMatch.ANY,
    favorites_only: bool = False,
    max_total_minutes: int | None = Query(default=None, ge=1, le=6000),
    difficulty: Difficulty | None = None,
    avoid_recent_days: int = Query(default=0, ge=0, le=90),
    sort: str = Query(default="name", pattern="^(name|recent|cooked|stale)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My dishes, filtered. This is the same query the wheel spins over."""
    ingredient_ids, unknown = _resolve_ingredient_ids(db, current_user, ingredient)
    dishes = dish_service.list_dishes(
        db,
        current_user.id,
        q=q,
        meal_types=meal_type,
        ingredient_ids=ingredient_ids,
        unknown_ingredients=unknown,
        match=match,
        favorites_only=favorites_only,
        max_total_minutes=max_total_minutes,
        difficulty=difficulty,
        avoid_recent_days=avoid_recent_days,
        sort=sort,
    )
    return [dish_summary(dish) for dish in dishes]


@router.post("", response_model=DishDetail, status_code=status.HTTP_201_CREATED)
def create_dish(
    payload: DishCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a dish. Name only is fine — the recipe can come later."""
    try:
        dish = dish_service.create(
            db,
            current_user,
            name=payload.name,
            description=payload.description,
            cuisine=payload.cuisine,
            prep_minutes=payload.prep_minutes,
            cook_minutes=payload.cook_minutes,
            servings=payload.servings,
            difficulty=payload.difficulty,
            source_url=payload.source_url,
            notes=payload.notes,
            meal_types=payload.meal_types,
        )
    except dish_service.AlreadyExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return dish_detail(_load(db, current_user, dish.dish_uuid))


@router.post(
    "/import.md", response_model=DishDetail, status_code=status.HTTP_201_CREATED
)
async def import_markdown(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import a Markdown file as a new dish.

    Lists under Ingredients become shelf/dish ingredients. Lists under a
    recipe-like heading become steps; without such a heading, every list
    outside Ingredients is treated as steps. Missing shelf ingredients are
    created and the entire import commits atomically.
    """
    body = await file.read(MAX_MARKDOWN_BYTES + 1)
    if len(body) > MAX_MARKDOWN_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="That Markdown file is larger than 1 MB.",
        )
    try:
        markdown = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That file is not UTF-8 text.",
        )

    try:
        dish = import_service.import_markdown(
            db, current_user, markdown, filename=file.filename
        )
    except import_service.MarkdownImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except dish_service.AlreadyExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    logger.info(
        f"{current_user.username} imported {dish.name} from Markdown "
        f"({len(dish.ingredients)} ingredients, {len(dish.steps)} steps)"
    )
    return dish_detail(dish)


@router.get("/{dish_uuid}", response_model=DishDetail)
def get_dish(
    dish_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Everything about one dish."""
    dish = _load(db, current_user, dish_uuid)
    return dish_detail(dish, dish_service.partners(db, dish))


@router.patch("/{dish_uuid}", response_model=DishDetail)
def update_dish(
    dish_uuid: str,
    payload: DishUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dish = _load(db, current_user, dish_uuid)
    try:
        dish = dish_service.update(db, dish, payload.model_dump(exclude_unset=True))
    except dish_service.AlreadyExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    dish = _load(db, current_user, dish_uuid)
    return dish_detail(dish, dish_service.partners(db, dish))


@router.delete("/{dish_uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dish(
    dish_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a dish, its recipe, its photos and its cook history.

    The photo objects are removed from storage too — the rows go with the
    cascade, and without this their bytes would linger unreachable forever.
    """
    from app.services import minio_service

    dish = _load(db, current_user, dish_uuid)
    object_keys = [image.minio_object_key for image in dish.images]
    name = dish.name
    db.delete(dish)
    db.commit()
    if object_keys:
        minio_service.delete_images(object_keys)
    logger.info(f"{current_user.username} deleted dish {name}")


# ---------------------------------------------------------------------------
# Ingredients on a dish
# ---------------------------------------------------------------------------

@router.put("/{dish_uuid}/ingredients", response_model=DishDetail)
def replace_ingredients(
    dish_uuid: str,
    payload: DishIngredientsReplace,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set the dish's ingredient list, in order, with amounts.

    Unknown UUIDs are rejected rather than skipped: an ingredient quietly
    vanishing from a list you just saved is worse than being told which one
    didn't resolve.
    """
    dish = _load(db, current_user, dish_uuid)

    wanted = [row.ingredient_uuid for row in payload.ingredients]
    found = {
        i.ingredient_uuid: i
        for i in ingredient_service.get_many(db, current_user.id, wanted)
    }
    missing = [u for u in wanted if u not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{len(missing)} ingredient(s) are not on your shelf",
        )

    dish_service.set_ingredients(
        db,
        dish,
        [
            {
                "ingredient_id": found[row.ingredient_uuid].id,
                "quantity": row.quantity,
                "unit": row.unit,
                "note": row.note,
                "is_optional": row.is_optional,
            }
            for row in payload.ingredients
        ],
    )
    dish = _load(db, current_user, dish_uuid)
    return dish_detail(dish, dish_service.partners(db, dish))


# ---------------------------------------------------------------------------
# The recipe
# ---------------------------------------------------------------------------

@router.get("/{dish_uuid}/steps", response_model=list[StepOut])
def list_steps(
    dish_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The recipe, in order. Each step carries the ingredients it mentions, so a
    client can hand over one step at a time without re-reading the dish."""
    dish = _load(db, current_user, dish_uuid)
    return [step_out(step) for step in dish.steps]


@router.put("/{dish_uuid}/steps", response_model=DishDetail)
def replace_steps(
    dish_uuid: str,
    payload: StepsReplace,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save the whole recipe.

    Anything `@[mentioned](uuid)` in a step is linked to that step and, if it
    wasn't already there, added to the dish's ingredient list. Writing the
    recipe is what builds the shopping list.

    Send each step's `step_uuid` back and that step is edited in place, keeping
    its photos through a reword or a reorder. Omit it and the step is new.
    """
    dish = _load(db, current_user, dish_uuid)
    dish_service.set_steps(
        db,
        dish,
        [
            {
                "step_uuid": step.step_uuid,
                "text": step.text,
                "minutes": step.minutes,
            }
            for step in payload.steps
        ],
    )
    dish = _load(db, current_user, dish_uuid)
    return dish_detail(dish, dish_service.partners(db, dish))


# ---------------------------------------------------------------------------
# Often had with
# ---------------------------------------------------------------------------

@router.post(
    "/{dish_uuid}/pairings",
    response_model=DishDetail,
    status_code=status.HTTP_201_CREATED,
)
def add_pairing(
    dish_uuid: str,
    payload: PairingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record that this dish is often had with another.

    Mutual by construction — the pair is stored once, so the other dish shows
    this one too without a second call. A name that isn't a dish yet becomes
    one, because typing "rice" is the natural way to say it.
    """
    dish = _load(db, current_user, dish_uuid)

    if payload.dish_uuid:
        other = dish_service.get(db, current_user.id, payload.dish_uuid)
        if other is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That dish doesn't exist",
            )
    else:
        other = dish_service.get_by_name(db, current_user.id, payload.name)
        if other is None:
            try:
                other = dish_service.create(db, current_user, name=payload.name)
            except (dish_service.AlreadyExists, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                )

    try:
        dish_service.add_pairing(db, dish, other, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    dish = _load(db, current_user, dish_uuid)
    return dish_detail(dish, dish_service.partners(db, dish))


@router.delete("/{dish_uuid}/pairings/{other_uuid}", response_model=DishDetail)
def remove_pairing(
    dish_uuid: str,
    other_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dish = _load(db, current_user, dish_uuid)
    other = dish_service.get(db, current_user.id, other_uuid)
    if other is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That dish doesn't exist"
        )
    dish_service.remove_pairing(db, dish, other)
    dish = _load(db, current_user, dish_uuid)
    return dish_detail(dish, dish_service.partners(db, dish))


# ---------------------------------------------------------------------------
# Cook log
# ---------------------------------------------------------------------------

@router.post(
    "/{dish_uuid}/cook",
    response_model=CookEventOut,
    status_code=status.HTTP_201_CREATED,
)
def log_cook(
    dish_uuid: str,
    payload: CookRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Say you actually cooked it.

    This is what teaches the wheel. A dish with no history is the most
    interesting suggestion the app can make, and one cooked yesterday is the
    least — neither is knowable without this call.
    """
    dish = _load(db, current_user, dish_uuid)
    event = dish_service.log_cook(
        db,
        dish,
        meal_type=payload.meal_type,
        source=payload.source,
        note=payload.note,
    )
    return cook_event_out(event)


@router.get("/{dish_uuid}/cooks", response_model=list[CookEventOut])
def list_cooks(
    dish_uuid: str,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """When this dish has been cooked."""
    from app.db.models import CookEvent

    dish = _load(db, current_user, dish_uuid)
    events = (
        db.query(CookEvent)
        .filter(CookEvent.dish_id == dish.id)
        .order_by(CookEvent.cooked_at.desc())
        .limit(limit)
        .all()
    )
    return [cook_event_out(event) for event in events]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/{dish_uuid}/export.md", response_class=Response)
def export_markdown(
    dish_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The dish as a markdown file."""
    dish = _load(db, current_user, dish_uuid)
    body = export_service.dish_to_markdown(
        dish, partners=dish_service.partners(db, dish)
    )
    filename = export_service.filename_for(dish, "md")
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # The UI fetches this with an Authorization header and saves the
            # blob itself, so the name has to survive on a header the browser
            # can read cross-origin.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/{dish_uuid}/export.zip", response_class=Response)
def export_bundle(
    dish_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The dish as a folder: `recipe.md` plus an `images/` directory.

    The plain markdown export links photos by presigned URL, which is right for
    pasting into a message and wrong for keeping. This is the archival form —
    relative paths, no expiry, and it drops straight into an Obsidian vault.
    """
    dish = _load(db, current_user, dish_uuid)
    try:
        body = export_service.dish_to_zip(
            dish, partners=dish_service.partners(db, dish)
        )
    except Exception as exc:
        logger.error(f"Zip export failed for {dish_uuid}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not build that bundle. The markdown export still works.",
        )
    filename = export_service.filename_for(dish, "zip")
    return Response(
        content=body,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/{dish_uuid}/export.pdf", response_class=Response)
def export_pdf(
    dish_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The dish as a printable PDF, photos included."""
    dish = _load(db, current_user, dish_uuid)
    try:
        body = pdf_service.dish_to_pdf(dish, partners=dish_service.partners(db, dish))
    except Exception as exc:
        logger.error(f"PDF export failed for {dish_uuid}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not build that PDF. The markdown export still works.",
        )
    filename = export_service.filename_for(dish, "pdf")
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
