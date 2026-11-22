"""
The wheel.

One endpoint, and it is the reason the app exists. POST rather than GET because
the filter set is a body (several multi-selects and an exclusion list), and
because a spin is not idempotent — it draws a new answer every time on purpose.
"""

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.schemas import SpinRequest, SpinResult
from app.api.serializers import dish_detail, dish_summary
from app.db.database import get_db
from app.db.models import User, UserSettings
from app.services import dish_service, ingredient_service, randomizer_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/randomizer", tags=["randomizer"])


@router.post("/spin", response_model=SpinResult, status_code=status.HTTP_200_OK)
def spin(
    payload: SpinRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Decide what to cook.

    An empty body is "anything" — the button most people press. Everything
    else narrows the pool: meal type, what's in the fridge, how long you have.

    The response carries the winner in full (so the reveal needs no second
    call), the slices the wheel should draw, and how big the real pool was.
    `dish` is null when nothing matched, which is the client's cue to say so
    rather than spin an empty wheel.
    """
    # No body at all means the same as an empty one. A bare POST is the most
    # natural way to say "anything", and answering it with a 422 would be
    # pedantry.
    payload = payload or SpinRequest()

    # The miss count matters: an ingredient uuid that resolves to nothing is in
    # no dish, and dropping it silently would widen the spin to the whole book
    # instead of narrowing it. `list_dishes` decides what that means.
    wanted = list(dict.fromkeys(payload.ingredient_uuids))
    found = ingredient_service.get_many(db, current_user.id, wanted)
    ingredient_ids = [i.id for i in found]
    unknown_ingredients = len(wanted) - len(found)

    # An unset avoid-window falls back to the user's own setting, so the
    # preference means something without every client having to send it. An
    # explicit 0 is not unset — it is "no window, everything is in play" — which
    # is why the field is nullable rather than defaulting to 0.
    avoid_days = payload.avoid_recent_days
    if avoid_days is None:
        settings = (
            db.query(UserSettings)
            .filter(UserSettings.user_id == current_user.id)
            .first()
        )
        avoid_days = (settings.avoid_recent_days if settings else 0) or 0

    result = randomizer_service.spin(
        db,
        current_user,
        meal_types=list(payload.meal_types),
        ingredient_ids=ingredient_ids,
        unknown_ingredients=unknown_ingredients,
        match=payload.match,
        favorites_only=payload.favorites_only,
        max_total_minutes=payload.max_total_minutes,
        difficulty=payload.difficulty,
        avoid_recent_days=avoid_days,
        weighted=payload.weighted,
        exclude_dish_uuids=list(payload.exclude_dish_uuids),
    )

    winner = result["dish"]
    if winner is None and avoid_days:
        # The avoid-window is a preference, not a rule. Rather than tell someone
        # with six dishes that nothing matches, retry without it and let the
        # weighting handle the repetition.
        logger.info(
            f"{current_user.username} had an empty pool at "
            f"avoid_recent_days={avoid_days}; retrying without it"
        )
        result = randomizer_service.spin(
            db,
            current_user,
            meal_types=list(payload.meal_types),
            ingredient_ids=ingredient_ids,
            unknown_ingredients=unknown_ingredients,
            match=payload.match,
            favorites_only=payload.favorites_only,
            max_total_minutes=payload.max_total_minutes,
            difficulty=payload.difficulty,
            avoid_recent_days=0,
            weighted=payload.weighted,
            exclude_dish_uuids=list(payload.exclude_dish_uuids),
        )
        winner = result["dish"]

    return SpinResult(
        dish=(
            dish_detail(winner, dish_service.partners(db, winner)) if winner else None
        ),
        slices=[dish_summary(dish) for dish in result["slices"]],
        pool_size=result["pool_size"],
        weighted=result["weighted"],
    )
