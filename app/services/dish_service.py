"""
Dishes: reading with filters, writing the recipe, and remembering what got cooked.

The two pieces worth reading before changing anything:

* **Filtering by ingredient** (`list_dishes`) is the query the whole app is
  built around — the wheel is the same filter with a random pick on the end.
  ANY and ALL are both done in SQL rather than in Python, so a shelf of 200
  ingredients doesn't drag every dish into memory to be thrown away.

* **Staples** are ingredients always in the house. They are excluded from an
  ALL-match requirement, because "I have onion and tomato" is a statement about
  what's interesting in the fridge, not a claim to have run out of salt.

The two matches ask different questions, and the difference is the point:

    ANY  "which dishes use any of these?"   — browsing
    ALL  "which of these can I cook now?"   — the fridge

ANY is a test on the ingredients you named. ALL is a test on the *dish*: it
matches when nothing the dish needs is missing, treating staples as always
present and optional ingredients as never required. So ticking onion and tomato
finds the dish that wants onion, tomato and salt, and rejects the one that also
wants paneer.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db.models import (
    CookEvent,
    Dish,
    DishIngredient,
    DishMealType,
    DishPairing,
    Ingredient,
    RecipeStep,
    User,
    name_key,
    pairing_pair,
)
from app.enums import CookSource, Difficulty, IngredientMatch
from app.services import mention_service

logger = logging.getLogger(__name__)

MAX_STEPS = 100


class AlreadyExists(Exception):
    """A dish with this name is already in the book."""

    def __init__(self, name: str):
        super().__init__(f"“{name}” is already in your dishes")
        self.name = name


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _loaded(query):
    """Eager-load everything a dish response needs.

    `selectinload` rather than `joinedload` for the collections: a dish with 12
    ingredients, 10 steps and 4 photos would otherwise fan out to 480 rows per
    dish through the join, and a list of 50 dishes turns that into a real
    problem.
    """
    return query.options(
        selectinload(Dish.meal_types),
        selectinload(Dish.ingredients).joinedload(DishIngredient.ingredient),
        selectinload(Dish.steps).selectinload(RecipeStep.ingredient_links),
        selectinload(Dish.steps).selectinload(RecipeStep.images),
        selectinload(Dish.images),
    )


def get(db: Session, user_id: int, dish_uuid: str) -> Optional[Dish]:
    return _loaded(
        db.query(Dish).filter(Dish.user_id == user_id, Dish.dish_uuid == dish_uuid)
    ).first()


def get_many(db: Session, user_id: int, uuids: list[str]) -> list[Dish]:
    if not uuids:
        return []
    return (
        db.query(Dish)
        .filter(Dish.user_id == user_id, Dish.dish_uuid.in_(uuids))
        .all()
    )


def get_by_name(db: Session, user_id: int, name: str) -> Optional[Dish]:
    key = name_key(name)
    if not key:
        return None
    return db.query(Dish).filter(Dish.user_id == user_id, Dish.name_key == key).first()


def list_dishes(
    db: Session,
    user_id: int,
    *,
    q: str | None = None,
    meal_types: Iterable[str] | None = None,
    ingredient_ids: Iterable[int] | None = None,
    match: str = IngredientMatch.ANY,
    favorites_only: bool = False,
    max_total_minutes: int | None = None,
    difficulty: str | None = None,
    avoid_recent_days: int = 0,
    unknown_ingredients: int = 0,
    sort: str = "name",
) -> list[Dish]:
    """Every dish matching the filters, eagerly loaded.

    `ingredient_ids` are internal ids, already resolved and confirmed to belong
    to this user by the caller. `unknown_ingredients` is how many of the ids the
    caller asked for could *not* be resolved — a filter chip left over from an
    ingredient since deleted, most often. They are counted rather than dropped
    silently, because an unresolvable ingredient is not the same as no
    ingredient: see the two guards below.
    """
    query = _loaded(db.query(Dish).filter(Dish.user_id == user_id))

    if q:
        needle = f"%{name_key(q)}%"
        # Name and description both, so "quick" in a description is findable.
        query = query.filter(
            or_(Dish.name_key.like(needle), func.lower(Dish.description).like(needle))
        )

    meal_types = [m for m in (meal_types or []) if m]
    if meal_types:
        # EXISTS rather than a join: a dish tagged both lunch and dinner would
        # otherwise come back twice for a [lunch, dinner] filter.
        query = query.filter(
            select(DishMealType.id)
            .where(
                DishMealType.dish_id == Dish.id,
                DishMealType.meal_type.in_(meal_types),
            )
            .exists()
        )

    ingredient_ids = list(dict.fromkeys(ingredient_ids or []))
    # Every ingredient asked for is unknown — a filter chip left over from an
    # ingredient since deleted, most often. Nothing can match it, which is not
    # the same as "no filter"; dropping it quietly is what used to widen the
    # results to the whole book.
    if unknown_ingredients and not ingredient_ids:
        return []
    if ingredient_ids:
        if match == IngredientMatch.ALL:
            # "What can I make with this?" — two conditions, both needed.
            #
            # Relevance: the dish actually uses something you ticked. Without
            # this, a dish with an empty ingredient list needs nothing and so
            # would match every fridge, burying the real answers.
            #
            # Sufficiency: nothing the dish needs is missing. Expressed as NOT
            # EXISTS over the ingredients *outside* your selection, which is the
            # only form that stays one query however long the list gets.
            # Staples are always in the house and optional ingredients are by
            # definition not needed, so neither can disqualify a dish.
            query = query.filter(
                select(DishIngredient.id)
                .where(
                    DishIngredient.dish_id == Dish.id,
                    DishIngredient.ingredient_id.in_(ingredient_ids),
                )
                .exists(),
                ~select(DishIngredient.id)
                .join(Ingredient, Ingredient.id == DishIngredient.ingredient_id)
                .where(
                    DishIngredient.dish_id == Dish.id,
                    DishIngredient.ingredient_id.notin_(ingredient_ids),
                    DishIngredient.is_optional.is_(False),
                    Ingredient.is_staple.is_(False),
                )
                .correlate(Dish)
                .exists(),
            )
        else:
            query = query.filter(
                select(DishIngredient.id)
                .where(
                    DishIngredient.dish_id == Dish.id,
                    DishIngredient.ingredient_id.in_(ingredient_ids),
                )
                .exists()
            )

    if favorites_only:
        query = query.filter(Dish.is_favorite.is_(True))
    if difficulty:
        query = query.filter(Dish.difficulty == difficulty)
    if max_total_minutes:
        # A dish with no times recorded is not excluded by a time filter —
        # unknown is not the same as slow, and hiding half the book because it
        # hasn't been annotated yet would make the filter useless.
        total = func.coalesce(Dish.prep_minutes, 0) + func.coalesce(Dish.cook_minutes, 0)
        query = query.filter(
            or_(
                total <= max_total_minutes,
                and_(Dish.prep_minutes.is_(None), Dish.cook_minutes.is_(None)),
            )
        )
    if avoid_recent_days and avoid_recent_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=avoid_recent_days)
        query = query.filter(
            or_(Dish.last_cooked_at.is_(None), Dish.last_cooked_at < cutoff)
        )

    orders = {
        "name": (Dish.name_key.asc(),),
        "recent": (Dish.created_at.desc(), Dish.id.desc()),
        "cooked": (Dish.times_cooked.desc(), Dish.name_key.asc()),
        # Nulls first: never-cooked dishes are the most overdue of all.
        "stale": (Dish.last_cooked_at.asc().nullsfirst(), Dish.name_key.asc()),
    }
    return query.order_by(*orders.get(sort, orders["name"])).all()


def partners(db: Session, dish: Dish) -> list[Dish]:
    """The dishes this one is often had with.

    Pairings are stored once as a sorted pair, so this reads both columns and
    keeps whichever id isn't the dish itself.
    """
    rows = (
        db.query(DishPairing)
        .filter(
            or_(DishPairing.dish_a_id == dish.id, DishPairing.dish_b_id == dish.id)
        )
        .all()
    )
    other_ids = [
        row.dish_b_id if row.dish_a_id == dish.id else row.dish_a_id for row in rows
    ]
    if not other_ids:
        return []
    return (
        db.query(Dish)
        .options(selectinload(Dish.images), selectinload(Dish.meal_types))
        .filter(Dish.id.in_(other_ids))
        .order_by(Dish.name_key)
        .all()
    )


def gallery_images(dish: Dish) -> list:
    """The dish's own photos — what the Photos tab shows.

    Step photos live in the same table and are filtered out here by `step_id`.
    A photo of the onions half-fried is a photo *of step two*; showing it in the
    gallery, or letting it become the cover, would misrepresent the dish.
    """
    return [image for image in dish.images if image.step_id is None]


def cover_image(dish: Dish):
    """The photo to show on a card: the chosen cover, else the first one.

    Gallery photos only — see `gallery_images()`.
    """
    gallery = gallery_images(dish)
    for image in gallery:
        if image.is_cover:
            return image
    return gallery[0] if gallery else None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def create(
    db: Session,
    user: User,
    *,
    name: str,
    description: str | None = None,
    cuisine: str | None = None,
    prep_minutes: int | None = None,
    cook_minutes: int | None = None,
    servings: int | None = None,
    difficulty: str = Difficulty.EASY,
    source_url: str | None = None,
    notes: str | None = None,
    meal_types: Iterable[str] | None = None,
    commit: bool = True,
) -> Dish:
    key = name_key(name)
    if not key:
        raise ValueError("Dish name cannot be blank")

    dish = Dish(
        user_id=user.id,
        name=" ".join((name or "").strip().split()),
        name_key=key,
        description=description,
        cuisine=cuisine,
        prep_minutes=prep_minutes,
        cook_minutes=cook_minutes,
        servings=servings,
        difficulty=difficulty or Difficulty.EASY,
        source_url=source_url,
        notes=notes,
    )
    db.add(dish)
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        raise AlreadyExists(name)
    if commit:
        db.refresh(dish)

    if meal_types:
        set_meal_types(db, dish, meal_types, commit=commit)
    logger.info(f"{user.username} added dish {dish.name} ({dish.dish_uuid})")
    return dish


def update(db: Session, dish: Dish, payload: dict) -> Dish:
    if "name" in payload and payload["name"] is not None:
        key = name_key(payload["name"])
        if not key:
            raise ValueError("Dish name cannot be blank")
        if key != dish.name_key:
            clash = (
                db.query(Dish)
                .filter(
                    Dish.user_id == dish.user_id,
                    Dish.name_key == key,
                    Dish.id != dish.id,
                )
                .first()
            )
            if clash:
                raise AlreadyExists(payload["name"])
        dish.name = " ".join(payload["name"].strip().split())
        dish.name_key = key

    # Nullable fields are set even when None, so a time or a serving count can
    # be cleared. `name` is handled above and can never be blanked.
    for field in (
        "description",
        "cuisine",
        "prep_minutes",
        "cook_minutes",
        "servings",
        "source_url",
        "notes",
    ):
        if field in payload:
            setattr(dish, field, payload[field])

    for field in ("difficulty", "is_favorite"):
        if field in payload and payload[field] is not None:
            setattr(dish, field, payload[field])

    if "meal_types" in payload and payload["meal_types"] is not None:
        set_meal_types(db, dish, payload["meal_types"], commit=False)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AlreadyExists(dish.name)
    db.refresh(dish)
    return dish


def set_meal_types(
    db: Session, dish: Dish, meal_types: Iterable[str], commit: bool = True
) -> None:
    """Replace the meal multi-select wholesale."""
    wanted = list(dict.fromkeys(m for m in meal_types if m))
    db.query(DishMealType).filter(DishMealType.dish_id == dish.id).delete(
        synchronize_session=False
    )
    for meal_type in wanted:
        db.add(DishMealType(dish_id=dish.id, meal_type=meal_type))
    if commit:
        db.commit()
        db.refresh(dish)


def set_ingredients(
    db: Session, dish: Dish, rows: list[dict], commit: bool = True
) -> None:
    """Replace the dish's ingredient list.

    `rows` carry an already-resolved `ingredient_id` plus the amounts. Replacing
    rather than diffing keeps the editor honest — what you see in the list is
    exactly what gets stored, including the order.
    """
    db.query(DishIngredient).filter(DishIngredient.dish_id == dish.id).delete(
        synchronize_session=False
    )
    seen: set[int] = set()
    for order, row in enumerate(rows):
        ingredient_id = row["ingredient_id"]
        if ingredient_id in seen:
            continue
        seen.add(ingredient_id)
        db.add(
            DishIngredient(
                dish_id=dish.id,
                ingredient_id=ingredient_id,
                quantity=row.get("quantity"),
                unit=row.get("unit"),
                note=row.get("note"),
                is_optional=bool(row.get("is_optional", False)),
                sort_order=order,
            )
        )
    if commit:
        db.commit()
        db.refresh(dish)
    else:
        db.flush()
        db.expire(dish, ["ingredients"])


def set_steps(db: Session, dish: Dish, rows: list[dict], commit: bool = True) -> None:
    """Replace the whole recipe.

    The request is still "here is the entire ladder" — `step_index` has to stay
    contiguous and 0-based for "step 3 of 8" to mean anything, and reordering in
    the editor is a drag rather than a set of index edits.

    What is *not* wholesale is the rows. A row carrying a `step_uuid` is matched
    to the existing step and edited in place; the rest are inserted and anything
    missing is deleted. Steps used to be dropped and recreated, which was
    cheaper to write — but a step now owns photos, and recreating the row would
    mean reordering a recipe silently detached every photo in it. Stable
    `step_uuid`s are also what let the editor upload a photo to step three and
    still have it there after a save.

    Mentions are re-synced afterwards, which is what pulls newly @-mentioned
    ingredients onto the dish's list.
    """
    rows = [row for row in rows if (row.get("text") or "").strip()][:MAX_STEPS]

    # Match by uuid, popping as we go: a payload that repeats a uuid must not
    # point two rows at one step object.
    unclaimed = {step.step_uuid: step for step in dish.steps}
    matched: list[Optional[RecipeStep]] = [
        unclaimed.pop(row.get("step_uuid"), None) for row in rows
    ]

    # Whatever is still unclaimed is a step the person deleted. ORM delete
    # rather than a bulk one, so its photos get handed back to the gallery and
    # its mention links go with it.
    for step in unclaimed.values():
        db.delete(step)
    db.flush()

    # Park the survivors on negative indices first. `uq_step_index_per_dish` is
    # checked per statement, so swapping steps 2 and 3 in place would collide
    # halfway through without somewhere empty to move through.
    for offset, step in enumerate(step for step in matched if step is not None):
        step.step_index = -(offset + 1)
    db.flush()

    for index, (row, step) in enumerate(zip(rows, matched)):
        text = row["text"].strip()
        if step is None:
            db.add(
                RecipeStep(
                    dish_id=dish.id,
                    step_index=index,
                    text=text,
                    minutes=row.get("minutes"),
                )
            )
        else:
            step.step_index = index
            step.text = text
            step.minutes = row.get("minutes")

    # Flush so new steps have ids for the mention links to point at, but stay in
    # one transaction so a bad mention can't leave half a recipe saved.
    db.flush()
    # The inserts and deletes above leave the loaded collection stale; without
    # expiring it the mention sync would iterate the wrong set of steps.
    db.expire(dish, ["steps"])
    mention_service.sync_dish(db, dish)
    if commit:
        db.commit()
        db.refresh(dish)
    else:
        db.flush()


def add_pairing(db: Session, dish: Dish, other: Dish, note: str | None = None) -> bool:
    """Record that two dishes go together. Returns False if already recorded."""
    if dish.id == other.id:
        raise ValueError("A dish cannot be paired with itself")

    a_id, b_id = pairing_pair(dish.id, other.id)
    existing = (
        db.query(DishPairing)
        .filter(DishPairing.dish_a_id == a_id, DishPairing.dish_b_id == b_id)
        .first()
    )
    if existing:
        return False
    db.add(DishPairing(dish_a_id=a_id, dish_b_id=b_id, note=note))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def remove_pairing(db: Session, dish: Dish, other: Dish) -> bool:
    a_id, b_id = pairing_pair(dish.id, other.id)
    deleted = (
        db.query(DishPairing)
        .filter(DishPairing.dish_a_id == a_id, DishPairing.dish_b_id == b_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return bool(deleted)


# ---------------------------------------------------------------------------
# Cook history
# ---------------------------------------------------------------------------

def log_cook(
    db: Session,
    dish: Dish,
    *,
    meal_type: str | None = None,
    source: str = CookSource.MANUAL,
    note: str | None = None,
    cooked_at: datetime | None = None,
) -> CookEvent:
    """Record that a dish got cooked, and refresh its cached counters."""
    event = CookEvent(
        dish_id=dish.id,
        user_id=dish.user_id,
        cooked_at=cooked_at or datetime.now(timezone.utc),
        meal_type=meal_type,
        source=source,
        note=note,
    )
    db.add(event)
    db.flush()
    _recount(db, dish)
    db.commit()
    db.refresh(event)
    return event


def unlog_cook(db: Session, dish: Dish, event: CookEvent) -> None:
    db.delete(event)
    db.flush()
    _recount(db, dish)
    db.commit()


def _recount(db: Session, dish: Dish) -> None:
    """Recompute `times_cooked` and `last_cooked_at` from `cook_events`.

    The cached columns exist so a dish list needs no per-row subquery; recounting
    from the events table rather than incrementing means a deleted event can
    never leave the cache overstated.
    """
    total, latest = (
        db.query(func.count(CookEvent.id), func.max(CookEvent.cooked_at))
        .filter(CookEvent.dish_id == dish.id)
        .one()
    )
    dish.times_cooked = total or 0
    dish.last_cooked_at = latest


def recent_cooks(db: Session, user_id: int, limit: int = 12) -> list[CookEvent]:
    return (
        db.query(CookEvent)
        .options(joinedload(CookEvent.dish).selectinload(Dish.images))
        .filter(CookEvent.user_id == user_id)
        .order_by(CookEvent.cooked_at.desc(), CookEvent.id.desc())
        .limit(limit)
        .all()
    )
