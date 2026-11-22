"""
The shelf: reading, adding and merging ingredients.

The one rule everything here exists to protect: a person's shelf holds each
ingredient exactly once. Every write goes through `name_key()`, so "Onion",
"onion" and "  onion " are the same row, and the unique index on
(user_id, name_key) is the arbiter rather than a check-then-insert that two
simultaneous requests could both pass.
"""

import logging
import re
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data import catalogue
from app.db.models import DishIngredient, Ingredient, User, name_key
from app.enums import IngredientCategory

logger = logging.getLogger(__name__)

# What one paste can add at once. The bulk box exists so a shelf can be typed
# in one go; the cap is only here so a pasted document can't become 40,000 rows.
MAX_BULK = 200

# How a pasted blob becomes names: newlines and commas separate, and so does a
# leading list bullet or number, because the text people paste came from a
# recipe or a notes app.
_SPLIT_RE = re.compile(r"[\n,;]+")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def split_names(blob: str) -> list[str]:
    """Turn a pasted blob into a deduped list of names, order preserved."""
    names: list[str] = []
    seen: set[str] = set()
    for chunk in _SPLIT_RE.split(blob or ""):
        cleaned = _BULLET_RE.sub("", chunk).strip()
        if not cleaned:
            continue
        key = name_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(cleaned)
    return names


def get(db: Session, user_id: int, ingredient_uuid: str) -> Optional[Ingredient]:
    return (
        db.query(Ingredient)
        .filter(
            Ingredient.user_id == user_id,
            Ingredient.ingredient_uuid == ingredient_uuid,
        )
        .first()
    )


def get_many(db: Session, user_id: int, uuids: list[str]) -> list[Ingredient]:
    """The caller's ingredients for these UUIDs. Unknown ones are dropped."""
    if not uuids:
        return []
    return (
        db.query(Ingredient)
        .filter(
            Ingredient.user_id == user_id,
            Ingredient.ingredient_uuid.in_(uuids),
        )
        .all()
    )


def get_by_name(db: Session, user_id: int, name: str) -> Optional[Ingredient]:
    key = name_key(name)
    if not key:
        return None
    return (
        db.query(Ingredient)
        .filter(Ingredient.user_id == user_id, Ingredient.name_key == key)
        .first()
    )


def list_ingredients(
    db: Session,
    user_id: int,
    *,
    q: str | None = None,
    category: str | None = None,
    staples_only: bool = False,
) -> list[Ingredient]:
    query = db.query(Ingredient).filter(Ingredient.user_id == user_id)
    if q:
        # Match on the normalised key so a search for "OLIVE" finds "Olive oil".
        query = query.filter(Ingredient.name_key.contains(name_key(q)))
    if category:
        query = query.filter(Ingredient.category == category)
    if staples_only:
        query = query.filter(Ingredient.is_staple.is_(True))
    return query.order_by(Ingredient.category, Ingredient.name_key).all()


def usage_counts(db: Session, user_id: int) -> dict[int, int]:
    """ingredient id -> how many dishes use it.

    One grouped query for the whole shelf rather than a count per row: the
    ingredients tab shows this on every chip, and 150 chips would otherwise be
    150 queries.
    """
    rows = (
        db.query(DishIngredient.ingredient_id, func.count(DishIngredient.id))
        .join(Ingredient, Ingredient.id == DishIngredient.ingredient_id)
        .filter(Ingredient.user_id == user_id)
        .group_by(DishIngredient.ingredient_id)
        .all()
    )
    return {ingredient_id: count for ingredient_id, count in rows}


def create(
    db: Session,
    user: User,
    *,
    name: str,
    category: str | None = None,
    default_unit: str | None = None,
    emoji: str | None = None,
    notes: str | None = None,
    is_staple: bool | None = None,
    commit: bool = True,
) -> Ingredient:
    """Add one ingredient, filling in whatever the catalogue knows about it.

    Raises `ValueError` on a blank name and `AlreadyExists` if the shelf already
    holds it — callers turn those into a 400 and a 409.
    """
    key = name_key(name)
    if not key:
        raise ValueError("Ingredient name cannot be blank")

    known = catalogue.BY_KEY.get(key, {})
    ingredient = Ingredient(
        user_id=user.id,
        name=" ".join((name or "").strip().split()),
        name_key=key,
        category=category or known.get("category") or IngredientCategory.OTHER,
        default_unit=default_unit or known.get("default_unit"),
        emoji=emoji or known.get("emoji"),
        notes=notes,
        is_staple=(
            known.get("is_staple", False) if is_staple is None else bool(is_staple)
        ),
    )
    db.add(ingredient)
    if commit:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise AlreadyExists(name)
        db.refresh(ingredient)
    return ingredient


class AlreadyExists(Exception):
    """The shelf already holds an ingredient with this name."""

    def __init__(self, name: str):
        super().__init__(f"“{name}” is already on your shelf")
        self.name = name


def bulk_add(
    db: Session, user: User, names: list[str]
) -> tuple[list[Ingredient], list[Ingredient]]:
    """Add every name that isn't on the shelf yet.

    Returns (created, already_there). Never an error for a duplicate: the whole
    point of the bulk box is pasting a list without first working out which half
    of it you already have.
    """
    names = names[:MAX_BULK]
    if not names:
        return [], []

    keys = [name_key(n) for n in names]
    existing = {
        ingredient.name_key: ingredient
        for ingredient in db.query(Ingredient)
        .filter(Ingredient.user_id == user.id, Ingredient.name_key.in_(keys))
        .all()
    }

    created: list[Ingredient] = []
    skipped: list[Ingredient] = []
    for name in names:
        key = name_key(name)
        if key in existing:
            skipped.append(existing[key])
            continue
        ingredient = create(db, user, name=name, commit=False)
        existing[key] = ingredient
        created.append(ingredient)

    try:
        db.commit()
    except IntegrityError:
        # Another request added one of these between the read and the write.
        # Re-read and report what is actually on the shelf now, rather than
        # failing a paste of thirty names because one of them raced.
        db.rollback()
        logger.info("Bulk add raced; re-reading the shelf")
        found = {
            ingredient.name_key: ingredient
            for ingredient in db.query(Ingredient)
            .filter(Ingredient.user_id == user.id, Ingredient.name_key.in_(keys))
            .all()
        }
        return [], [found[k] for k in keys if k in found]

    for ingredient in created:
        db.refresh(ingredient)
    logger.info(
        f"{user.username} bulk-added {len(created)} ingredient(s), "
        f"{len(skipped)} already there"
    )
    return created, skipped


def update(db: Session, ingredient: Ingredient, payload: dict) -> Ingredient:
    """Apply a partial update. A rename re-derives `name_key`."""
    if "name" in payload and payload["name"] is not None:
        key = name_key(payload["name"])
        if not key:
            raise ValueError("Ingredient name cannot be blank")
        if key != ingredient.name_key:
            clash = (
                db.query(Ingredient)
                .filter(
                    Ingredient.user_id == ingredient.user_id,
                    Ingredient.name_key == key,
                    Ingredient.id != ingredient.id,
                )
                .first()
            )
            if clash:
                raise AlreadyExists(payload["name"])
        ingredient.name = " ".join(payload["name"].strip().split())
        ingredient.name_key = key

    for field in ("category", "default_unit", "emoji", "notes", "is_staple"):
        if field in payload and payload[field] is not None:
            setattr(ingredient, field, payload[field])

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AlreadyExists(ingredient.name)
    db.refresh(ingredient)
    return ingredient


def delete(db: Session, ingredient: Ingredient) -> None:
    """Remove an ingredient from the shelf, and from every dish using it.

    The cascade is deliberate and the API warns with the usage count first: an
    ingredient that no longer exists cannot stay in a recipe's list. Mentions
    already written into step text survive as plain words, because
    `strip_mentions` falls back to the name in the markup.
    """
    db.delete(ingredient)
    db.commit()
