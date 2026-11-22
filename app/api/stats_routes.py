"""
The dashboard's numbers.

One endpoint, one round trip. The home screen is the wheel plus a handful of
counts, and shipping those as six separate requests would mean six spinners
above the fold.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.schemas import DashboardOut, MealTypeCount
from app.api.serializers import cook_event_out, dish_summary, ingredient_out
from app.db.database import get_db
from app.db.models import (
    CookEvent,
    Dish,
    DishIngredient,
    DishMealType,
    Ingredient,
    RecipeStep,
    User,
)
from app.services import dish_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Everything above the fold on the home screen."""
    user_id = current_user.id
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    dish_count = (
        db.query(func.count(Dish.id)).filter(Dish.user_id == user_id).scalar() or 0
    )
    favorite_count = (
        db.query(func.count(Dish.id))
        .filter(Dish.user_id == user_id, Dish.is_favorite.is_(True))
        .scalar()
        or 0
    )
    never_cooked = (
        db.query(func.count(Dish.id))
        .filter(Dish.user_id == user_id, Dish.times_cooked == 0)
        .scalar()
        or 0
    )
    ingredient_count = (
        db.query(func.count(Ingredient.id))
        .filter(Ingredient.user_id == user_id)
        .scalar()
        or 0
    )
    step_count = (
        db.query(func.count(RecipeStep.id))
        .join(Dish, Dish.id == RecipeStep.dish_id)
        .filter(Dish.user_id == user_id)
        .scalar()
        or 0
    )
    cooks_all_time = (
        db.query(func.count(CookEvent.id))
        .filter(CookEvent.user_id == user_id)
        .scalar()
        or 0
    )
    cooks_this_week = (
        db.query(func.count(CookEvent.id))
        .filter(CookEvent.user_id == user_id, CookEvent.cooked_at >= week_ago)
        .scalar()
        or 0
    )

    by_meal_type = [
        MealTypeCount(meal_type=meal_type, count=count)
        for meal_type, count in db.query(
            DishMealType.meal_type, func.count(DishMealType.id)
        )
        .join(Dish, Dish.id == DishMealType.dish_id)
        .filter(Dish.user_id == user_id)
        .group_by(DishMealType.meal_type)
        .all()
    ]

    # Longest unmade first, never-cooked ahead of everything — the "you haven't
    # had this in ages" shelf, and the most useful nudge the app has.
    overdue = dish_service.list_dishes(db, user_id, sort="stale")[:6]

    top_ingredient_rows = (
        db.query(Ingredient, func.count(DishIngredient.id).label("uses"))
        .join(DishIngredient, DishIngredient.ingredient_id == Ingredient.id)
        .filter(Ingredient.user_id == user_id)
        .group_by(Ingredient.id)
        .order_by(func.count(DishIngredient.id).desc(), Ingredient.name_key)
        .limit(12)
        .all()
    )

    return DashboardOut(
        dish_count=dish_count,
        ingredient_count=ingredient_count,
        step_count=step_count,
        cooks_this_week=cooks_this_week,
        cooks_all_time=cooks_all_time,
        favorite_count=favorite_count,
        never_cooked=never_cooked,
        by_meal_type=by_meal_type,
        overdue=[dish_summary(dish) for dish in overdue],
        recent_cooks=[
            cook_event_out(event) for event in dish_service.recent_cooks(db, user_id)
        ],
        top_ingredients=[
            ingredient_out(ingredient, uses)
            for ingredient, uses in top_ingredient_rows
        ],
    )
