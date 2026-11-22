"""
The wheel.

Deciding what to cook is the app's actual job, so this is deliberately more
than `random.choice`. Two things shape a spin:

* **The filters** — meal type and what's in the fridge — narrow the pool. That
  part is `dish_service.list_dishes`, unchanged, because the wheel and the
  dishes tab must never disagree about what matches.

* **The weighting** — how long since you last had it. A dish eaten yesterday
  and one you haven't made since March are not equally good suggestions, and a
  uniform draw over a book of forty dishes serves you the same six by chance.
  Weight rises with staleness and never reaches zero, so nothing is ever
  permanently off the wheel.

The pool is returned alongside the winner. The UI needs it to draw the wheel's
slices, and showing what *could* have come up is most of what makes a spin feel
fair rather than arbitrary.
"""

import logging
import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Dish, User
from app.enums import IngredientMatch
from app.services import dish_service

logger = logging.getLogger(__name__)

# How many dishes the wheel will draw. Past this the slices are unreadable, so
# the wheel shows a weighted sample and says how big the real pool was.
WHEEL_SLOTS = 12

# Staleness is capped here. Beyond about a month "ages ago" is "ages ago", and
# without a cap a dish last cooked two years back would outweigh everything else
# combined and the wheel would stop being a wheel.
MAX_STALENESS_DAYS = 45

# What a never-cooked dish is worth. Above the cap on purpose: something you
# have written down but never made is the most interesting suggestion the app
# can offer.
UNCOOKED_WEIGHT = MAX_STALENESS_DAYS + 15

# The floor. A dish cooked an hour ago is still possible, just unlikely.
MIN_WEIGHT = 1.0


def weight_for(dish: Dish, now: datetime | None = None) -> float:
    """How strongly a dish should be favoured, from staleness alone."""
    if dish.last_cooked_at is None:
        return float(UNCOOKED_WEIGHT)

    now = now or datetime.now(timezone.utc)
    last = dish.last_cooked_at
    # SQLite hands back naive datetimes; treat them as the UTC they are, rather
    # than letting the subtraction raise.
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    days = (now - last).total_seconds() / 86_400
    return max(MIN_WEIGHT, min(float(MAX_STALENESS_DAYS), days))


def spin(
    db: Session,
    user: User,
    *,
    meal_types: list[str] | None = None,
    ingredient_ids: list[int] | None = None,
    match: str = IngredientMatch.ANY,
    favorites_only: bool = False,
    max_total_minutes: int | None = None,
    difficulty: str | None = None,
    avoid_recent_days: int = 0,
    unknown_ingredients: int = 0,
    weighted: bool = True,
    exclude_dish_uuids: list[str] | None = None,
) -> dict:
    """Pick a dish. Returns the winner, the wheel's slices, and the pool size.

    `exclude_dish_uuids` is what "spin again" sends: the dish just rejected is
    kept out of the next draw, so pressing the button twice can't hand back the
    same answer and look broken.
    """
    pool = dish_service.list_dishes(
        db,
        user.id,
        meal_types=meal_types,
        ingredient_ids=ingredient_ids,
        match=match,
        favorites_only=favorites_only,
        max_total_minutes=max_total_minutes,
        difficulty=difficulty,
        avoid_recent_days=avoid_recent_days,
        unknown_ingredients=unknown_ingredients,
        sort="stale",
    )

    excluded = set(exclude_dish_uuids or [])
    narrowed = [dish for dish in pool if dish.dish_uuid not in excluded]
    # Refusing to repeat matters less than answering at all: with one matching
    # dish left, giving it again beats "nothing matches".
    candidates = narrowed or pool

    if not candidates:
        return {
            "dish": None,
            "slices": [],
            "pool_size": 0,
            "weighted": weighted,
        }

    now = datetime.now(timezone.utc)
    weights = (
        [weight_for(dish, now) for dish in candidates]
        if weighted
        else [1.0] * len(candidates)
    )

    winner = random.choices(candidates, weights=weights, k=1)[0]

    logger.info(
        f"{user.username} spun the wheel: {winner.name} "
        f"out of {len(candidates)} candidate(s)"
    )
    return {
        "dish": winner,
        "slices": _slices(candidates, weights, winner),
        "pool_size": len(candidates),
        "weighted": weighted,
    }


def _slices(dishes: list[Dish], weights: list[float], winner: Dish) -> list[Dish]:
    """The dishes the wheel draws, winner always included.

    A wheel with forty slices is a grey disc, so it shows at most WHEEL_SLOTS.
    They are the heaviest candidates — the ones most overdue, which is also the
    most interesting thing to look at while it spins — and the winner is spliced
    in if the weighting didn't already put it there. A wheel that doesn't
    contain the answer would be a lie.
    """
    if len(dishes) <= WHEEL_SLOTS:
        return list(dishes)

    ranked = [dish for dish, _ in sorted(
        zip(dishes, weights, strict=True), key=lambda pair: pair[1], reverse=True
    )]
    shown = ranked[:WHEEL_SLOTS]
    if winner not in shown:
        shown[-1] = winner
    return shown
