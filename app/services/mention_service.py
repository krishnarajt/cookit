"""
Ingredient mentions inside a recipe step.

A step's text is prose with typed references in it:

    Fry the @[cumin seeds](8f1c…) until they pop, then add @[onion](2a4e…).

The markup is written by the editor's autocomplete, never by hand, and carries
the ingredient's UUID rather than only its name. That matters: "oil" and "olive
oil" are different shelf entries and a name alone could not tell them apart, so
renaming an ingredient later leaves every step that mentions it still correct.

Two things happen on every step write, both here:

  1. `recipe_step_ingredients` is rebuilt from the mentions, so a step can be
     handed over on its own — read aloud, sent to a chat — already knowing what
     it needs.
  2. Anything mentioned is added to the *dish's* ingredient list if it wasn't
     there. This is the whole point of typing "@" mid-sentence: writing the
     recipe is what builds the shopping list, instead of two lists to keep in
     agreement.

Nothing is ever removed by the parser. Deleting a mention from a step does not
un-shop the ingredient, because a dish routinely needs something no step spells
out (salt, the oil it's fried in) and silently dropping those would be worse
than an occasional stale row the person can delete.
"""

import logging
import re
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models import (
    Dish,
    DishIngredient,
    Ingredient,
    RecipeStep,
    RecipeStepIngredient,
)

logger = logging.getLogger(__name__)

# @[display name](uuid). The name is allowed anything but a closing bracket, so
# "@[chilli (dried)](…)" survives; the uuid shape is pinned so ordinary prose
# containing brackets can never be mistaken for a mention.
MENTION_RE = re.compile(
    r"@\[([^\]\n]{1,200})\]\(([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)"
)


def mention_uuids(text: str) -> list[str]:
    """Every ingredient UUID mentioned in a step, in reading order, deduped."""
    seen: list[str] = []
    for _name, ingredient_uuid in MENTION_RE.findall(text or ""):
        lowered = ingredient_uuid.lower()
        if lowered not in seen:
            seen.append(lowered)
    return seen


def strip_mentions(text: str) -> str:
    """The step as a human reads it: `@[onion](…)` becomes `onion`.

    Used by the exporters and by anything that has to speak a step out loud.
    """
    return MENTION_RE.sub(lambda match: match.group(1), text or "")


def mentions_to_markdown(text: str) -> str:
    """The step for a markdown file, with mentioned ingredients in bold."""
    return MENTION_RE.sub(lambda match: f"**{match.group(1)}**", text or "")


def resolve(db: Session, user_id: int, uuids: Iterable[str]) -> list[Ingredient]:
    """The caller's own ingredients for these UUIDs, in the order given.

    Scoped to `user_id` on purpose: a UUID in a request body is user input, and
    without this filter a crafted step could pull another person's shelf entry
    into a dish. Unknown or foreign UUIDs are dropped rather than raising —
    a mention whose ingredient has since been deleted should leave the step
    readable, not make it unsaveable.
    """
    wanted = [u.lower() for u in uuids]
    if not wanted:
        return []

    found = (
        db.query(Ingredient)
        .filter(
            Ingredient.user_id == user_id,
            Ingredient.ingredient_uuid.in_(wanted),
        )
        .all()
    )
    by_uuid = {ingredient.ingredient_uuid.lower(): ingredient for ingredient in found}
    return [by_uuid[u] for u in wanted if u in by_uuid]


def sync_step(db: Session, dish: Dish, step: RecipeStep) -> list[Ingredient]:
    """Rebuild one step's ingredient links and top up the dish's list.

    Returns the ingredients this step mentions. Does not commit — the caller
    owns the transaction, so saving a whole recipe stays one round trip.
    """
    mentioned = resolve(db, dish.user_id, mention_uuids(step.text))

    # Rebuild rather than diff: a step mentions a handful of things, and a
    # wholesale replace can't drift out of step with the text the way an
    # incremental update can.
    #
    # Through the collection, not a bulk DELETE. A step now survives a recipe
    # save (see dish_service.set_steps), so its old links are live objects in
    # the session; deleting the rows out from under them leaves the identity map
    # holding rows that no longer exist.
    step.ingredient_links.clear()
    # Flush the removals before the re-adds. `uq_step_ingredient` is checked per
    # statement, and the unit of work would otherwise insert the new row for an
    # ingredient still mentioned before deleting the old one.
    db.flush()
    for ingredient in mentioned:
        step.ingredient_links.append(
            RecipeStepIngredient(step_id=step.id, ingredient_id=ingredient.id)
        )

    _add_missing_to_dish(db, dish, mentioned)
    return mentioned


def sync_dish(db: Session, dish: Dish) -> None:
    """Rebuild every step's links for a dish, and top up its ingredient list.

    Used after a whole-recipe replace, where individual step ids have changed.
    """
    for step in dish.steps:
        sync_step(db, dish, step)


def _add_missing_to_dish(
    db: Session, dish: Dish, ingredients: list[Ingredient]
) -> None:
    """Add any of these ingredients the dish doesn't already list."""
    if not ingredients:
        return

    existing = {link.ingredient_id for link in dish.ingredients}
    # Rows added earlier in this same transaction are not on `dish.ingredients`
    # yet (no flush), so a second step mentioning the same ingredient would
    # insert a duplicate and trip the unique index. Track them here instead.
    pending = {
        obj.ingredient_id
        for obj in db.new
        if isinstance(obj, DishIngredient) and obj.dish_id == dish.id
    }
    next_order = max(
        [link.sort_order for link in dish.ingredients] + [len(pending) - 1, -1]
    ) + 1

    for ingredient in ingredients:
        if ingredient.id in existing or ingredient.id in pending:
            continue
        db.add(
            DishIngredient(
                dish_id=dish.id,
                ingredient_id=ingredient.id,
                sort_order=next_order,
            )
        )
        pending.add(ingredient.id)
        next_order += 1
        logger.debug(
            f"Mention added {ingredient.name} to dish {dish.dish_uuid}"
        )
