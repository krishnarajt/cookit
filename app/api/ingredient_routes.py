"""
The ingredients tab.

Adding things has to be frictionless or the app never gets off the ground, so
there are three ways in and none of them is a form:

  POST /ingredients          one name, everything else guessed from the catalogue
  POST /ingredients/bulk     a pasted blob or a list; duplicates are not errors
  GET  /ingredients/suggestions   catalogue chips, minus what's already there
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.schemas import (
    IngredientBulkCreate,
    IngredientBulkResult,
    IngredientCreate,
    IngredientOut,
    IngredientSuggestion,
    IngredientUpdate,
)
from app.api.serializers import ingredient_out
from app.data import catalogue
from app.db.database import get_db
from app.db.models import Ingredient, User
from app.enums import IngredientCategory
from app.services import ingredient_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ingredients", tags=["ingredients"])


def _load(db: Session, user: User, ingredient_uuid: str) -> Ingredient:
    ingredient = ingredient_service.get(db, user.id, ingredient_uuid)
    if ingredient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ingredient not found"
        )
    return ingredient


@router.get("", response_model=list[IngredientOut])
def list_ingredients(
    q: str | None = Query(default=None, max_length=200),
    category: IngredientCategory | None = None,
    staples_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """My shelf, with a usage count on each entry."""
    ingredients = ingredient_service.list_ingredients(
        db, current_user.id, q=q, category=category, staples_only=staples_only
    )
    counts = ingredient_service.usage_counts(db, current_user.id)
    return [
        ingredient_out(ingredient, counts.get(ingredient.id, 0))
        for ingredient in ingredients
    ]


@router.get("/categories", response_model=list[str])
def list_categories():
    """The category values, in the order the UI should group them."""
    return IngredientCategory.values()


@router.get("/suggestions", response_model=list[IngredientSuggestion])
def list_suggestions(
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Catalogue chips for one-tap adding, minus anything already on the shelf."""
    have = {
        key
        for (key,) in db.query(Ingredient.name_key)
        .filter(Ingredient.user_id == current_user.id)
        .all()
    }
    return catalogue.suggestions(have)[:limit]


@router.post("", response_model=IngredientOut, status_code=status.HTTP_201_CREATED)
def create_ingredient(
    payload: IngredientCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add one ingredient. Category, unit and emoji are guessed if not given."""
    try:
        ingredient = ingredient_service.create(
            db,
            current_user,
            name=payload.name,
            category=payload.category,
            default_unit=payload.default_unit,
            emoji=payload.emoji,
            notes=payload.notes,
            is_staple=payload.is_staple,
        )
    except ingredient_service.AlreadyExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return ingredient_out(ingredient)


@router.post(
    "/bulk", response_model=IngredientBulkResult, status_code=status.HTTP_201_CREATED
)
def bulk_create(
    payload: IngredientBulkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a whole list at once. Names already on the shelf come back untouched.

    Deliberately not a 409 on duplicates: the point of pasting a list is not
    having to work out first which half of it you already have.
    """
    names = list(payload.names or [])
    if payload.text:
        names += ingredient_service.split_names(payload.text)
    # Dedupe across both sources, keeping the order they arrived in.
    names = ingredient_service.split_names("\n".join(names))

    if not names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to add — no names found in that.",
        )

    created, existing = ingredient_service.bulk_add(db, current_user, names)
    counts = ingredient_service.usage_counts(db, current_user.id)
    return IngredientBulkResult(
        created=[ingredient_out(i, counts.get(i.id, 0)) for i in created],
        already_there=[ingredient_out(i, counts.get(i.id, 0)) for i in existing],
    )


@router.get("/{ingredient_uuid}", response_model=IngredientOut)
def get_ingredient(
    ingredient_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ingredient = _load(db, current_user, ingredient_uuid)
    counts = ingredient_service.usage_counts(db, current_user.id)
    return ingredient_out(ingredient, counts.get(ingredient.id, 0))


@router.patch("/{ingredient_uuid}", response_model=IngredientOut)
def update_ingredient(
    ingredient_uuid: str,
    payload: IngredientUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit an ingredient. A rename is safe — dishes reference it by id, and
    step mentions carry the UUID, so nothing breaks."""
    ingredient = _load(db, current_user, ingredient_uuid)
    try:
        ingredient = ingredient_service.update(
            db, ingredient, payload.model_dump(exclude_unset=True)
        )
    except ingredient_service.AlreadyExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    counts = ingredient_service.usage_counts(db, current_user.id)
    return ingredient_out(ingredient, counts.get(ingredient.id, 0))


@router.delete("/{ingredient_uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ingredient(
    ingredient_uuid: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove an ingredient, and with it every dish's reference to it.

    The client shows the usage count from the list before asking, so this is
    never a surprise. Mentions already written into step text survive as plain
    words, because the name is in the markup.
    """
    ingredient = _load(db, current_user, ingredient_uuid)
    name = ingredient.name
    ingredient_service.delete(db, ingredient)
    logger.info(f"{current_user.username} deleted ingredient {name}")
