"""
ORM rows into response shapes.

Kept out of the route modules because a dish is assembled in three places — the
dishes list, the detail screen, and the wheel — and three hand-rolled versions
would drift. Every function here is pure: it reads already-loaded relationships
and issues no queries, so a list of 200 dishes stays the one query
`dish_service._loaded` made.
"""

from app.api.schemas import (
    CookEventOut,
    DishDetail,
    DishImageOut,
    DishIngredientOut,
    DishSummary,
    IngredientOut,
    StepOut,
)
from app.db.models import CookEvent, Dish, DishImage, Ingredient
from app.services import dish_service, mention_service


def ingredient_out(ingredient: Ingredient, used_in: int = 0) -> IngredientOut:
    return IngredientOut(
        id=ingredient.id,
        ingredient_uuid=ingredient.ingredient_uuid,
        name=ingredient.name,
        category=ingredient.category,
        default_unit=ingredient.default_unit,
        emoji=ingredient.emoji,
        notes=ingredient.notes,
        is_staple=ingredient.is_staple,
        used_in=used_in,
        created_at=ingredient.created_at,
    )


def dish_ingredient_out(link) -> DishIngredientOut:
    return DishIngredientOut(
        ingredient_uuid=link.ingredient.ingredient_uuid,
        name=link.ingredient.name,
        category=link.ingredient.category,
        emoji=link.ingredient.emoji,
        quantity=link.quantity,
        unit=link.unit,
        note=link.note,
        is_optional=link.is_optional,
        sort_order=link.sort_order,
    )


def _step_ingredient_out(link) -> DishIngredientOut:
    """A step's mentioned ingredient. No amounts — those belong to the dish's
    list, and repeating them per step is how the two get out of agreement."""
    return DishIngredientOut(
        ingredient_uuid=link.ingredient.ingredient_uuid,
        name=link.ingredient.name,
        category=link.ingredient.category,
        emoji=link.ingredient.emoji,
    )


def step_out(step) -> StepOut:
    return StepOut(
        step_uuid=step.step_uuid,
        step_index=step.step_index,
        text=step.text,
        plain_text=mention_service.strip_mentions(step.text),
        minutes=step.minutes,
        ingredients=[_step_ingredient_out(link) for link in step.ingredient_links],
        images=[image_out(image, step_uuid=step.step_uuid) for image in step.images],
    )


def image_out(image: DishImage, *, step_uuid: str | None = None) -> DishImageOut:
    """A photo row.

    `step_uuid` is passed in rather than read from `image.step`: every caller
    already holds the step (or knows there isn't one), and touching the
    relationship here would lazy-load one row per photo — exactly the per-row
    query this module exists to avoid.
    """
    return DishImageOut(
        image_uuid=image.image_uuid,
        image_name=image.image_name,
        mime_type=image.mime_type,
        file_size=image.file_size,
        caption=image.caption,
        is_cover=image.is_cover,
        sort_order=image.sort_order,
        step_uuid=step_uuid,
        created_at=image.created_at,
    )


def _total_minutes(dish: Dish) -> int | None:
    if dish.prep_minutes is None and dish.cook_minutes is None:
        return None
    return (dish.prep_minutes or 0) + (dish.cook_minutes or 0)


def dish_summary(dish: Dish) -> DishSummary:
    cover = dish_service.cover_image(dish)
    gallery = dish_service.gallery_images(dish)
    return DishSummary(
        dish_uuid=dish.dish_uuid,
        name=dish.name,
        description=dish.description,
        cuisine=dish.cuisine,
        prep_minutes=dish.prep_minutes,
        cook_minutes=dish.cook_minutes,
        total_minutes=_total_minutes(dish),
        servings=dish.servings,
        difficulty=dish.difficulty,
        is_favorite=dish.is_favorite,
        meal_types=sorted(row.meal_type for row in dish.meal_types),
        ingredient_count=len(dish.ingredients),
        step_count=len(dish.steps),
        image_count=len(gallery),
        step_image_count=len(dish.images) - len(gallery),
        cover_image_uuid=cover.image_uuid if cover else None,
        times_cooked=dish.times_cooked,
        last_cooked_at=dish.last_cooked_at,
        created_at=dish.created_at,
    )


def dish_detail(dish: Dish, partners: list[Dish] | None = None) -> DishDetail:
    """The full dish. `partners` comes from `dish_service.partners()` — passed in
    rather than read here, because it is the one part that needs a query."""
    return DishDetail(
        **dish_summary(dish).model_dump(),
        source_url=dish.source_url,
        notes=dish.notes,
        ingredients=[dish_ingredient_out(link) for link in dish.ingredients],
        steps=[step_out(step) for step in dish.steps],
        images=[image_out(image) for image in dish_service.gallery_images(dish)],
        often_had_with=[dish_summary(other) for other in (partners or [])],
    )


def cook_event_out(event: CookEvent) -> CookEventOut:
    cover = dish_service.cover_image(event.dish) if event.dish else None
    return CookEventOut(
        id=event.id,
        dish_uuid=event.dish.dish_uuid if event.dish else "",
        dish_name=event.dish.name if event.dish else "",
        cover_image_uuid=cover.image_uuid if cover else None,
        cooked_at=event.cooked_at,
        meal_type=event.meal_type,
        source=event.source,
        note=event.note,
    )
