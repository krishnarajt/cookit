"""Import a recipe from ordinary Markdown.

The importer deliberately understands a small, useful part of Markdown rather
than trying to render it. A recipe is made of list items, so headings decide
what a list means and the list markers decide where one row ends and the next
begins:

* a list below an ``Ingredients`` heading becomes the dish's ingredients;
* lists below ``Method``, ``Steps``, ``Recipe``, ``Instructions`` and similar
  headings become recipe steps;
* if there is no recipe heading, every list outside Ingredients is a step.

That last rule is what makes a bare checklist or numbered note import cleanly.
Cookit's own export additionally contributes its YAML metadata, amounts, notes,
optional flags, and per-step timers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Ingredient, User, name_key
from app.enums import Difficulty, MealType
from app.services import dish_service, ingredient_service


MAX_INGREDIENTS = 100
MAX_STEPS = 100


class MarkdownImportError(ValueError):
    """The document is readable text, but not an importable recipe."""


@dataclass(frozen=True)
class ImportedIngredient:
    name: str
    quantity: float | None = None
    unit: str | None = None
    note: str | None = None
    is_optional: bool = False


@dataclass(frozen=True)
class ImportedStep:
    text: str
    minutes: int | None = None


@dataclass(frozen=True)
class ParsedRecipe:
    name: str
    description: str | None = None
    cuisine: str | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    servings: int | None = None
    difficulty: str = Difficulty.EASY
    source_url: str | None = None
    notes: str | None = None
    meal_types: list[str] = field(default_factory=list)
    ingredients: list[ImportedIngredient] = field(default_factory=list)
    steps: list[ImportedStep] = field(default_factory=list)


@dataclass
class _ListItem:
    kind: str | None
    text: str


_ATX_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_SETEXT_RE = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_LIST_RE = re.compile(
    r"^\s*(?:(?:[-+*•])|(?:\d{1,3}[.)])|(?:[A-Za-z][.)]))\s+(.*?)\s*$"
)
_TASK_RE = re.compile(r"^\[[ xX~-]\]\s*")
_IMAGE_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")
_AUTOLINK_RE = re.compile(r"<((?:https?://|mailto:)[^>]+)>")
_MINUTES_RE = re.compile(
    r"\s*(?:[_*]{1,2})?\(\s*(\d{1,4})\s*(?:min|mins|minute|minutes)\s*\)"
    r"(?:[_*]{1,2})?\s*$",
    re.IGNORECASE,
)

_INGREDIENT_HEADINGS = {"ingredient", "ingredients"}
_METHOD_HEADINGS = {
    "direction",
    "directions",
    "instruction",
    "instructions",
    "method",
    "methods",
    "preparation",
    "procedure",
    "recipe",
    "steps",
    "step by step",
    "what to do",
}
_NOTE_HEADINGS = {"note", "notes"}
_KNOWN_LABELS = _INGREDIENT_HEADINGS | _METHOD_HEADINGS | _NOTE_HEADINGS

# Only known measurement words are split from an arbitrary ingredient. Thus
# "2 large eggs" becomes quantity 2 + "large eggs", while "2 tbsp oil"
# becomes quantity 2 + unit tbsp + "oil".
_UNITS = {
    "bag",
    "bags",
    "bottle",
    "bottles",
    "bunch",
    "bunches",
    "can",
    "cans",
    "clove",
    "cloves",
    "cup",
    "cups",
    "dash",
    "dashes",
    "g",
    "gram",
    "grams",
    "handful",
    "handfuls",
    "head",
    "heads",
    "kg",
    "kilogram",
    "kilograms",
    "l",
    "liter",
    "liters",
    "litre",
    "litres",
    "mg",
    "milligram",
    "milligrams",
    "milliliter",
    "milliliters",
    "millilitre",
    "millilitres",
    "ml",
    "ounce",
    "ounces",
    "oz",
    "pack",
    "package",
    "packages",
    "packet",
    "packets",
    "piece",
    "pieces",
    "pinch",
    "pinches",
    "pint",
    "pints",
    "pound",
    "pounds",
    "slice",
    "slices",
    "sprig",
    "sprigs",
    "stalk",
    "stalks",
    "tablespoon",
    "tablespoons",
    "tbsp",
    "teaspoon",
    "teaspoons",
    "tin",
    "tins",
    "tsp",
}
_QUANTITY_RE = re.compile(
    r"^(?P<quantity>(?:\d+\s+\d+/\d+)|(?:\d+/\d+)|(?:\d+(?:\.\d+)?)|[¼½¾⅓⅔⅛⅜⅝⅞])"
    r"(?:\s+|(?=[A-Za-z]))(?P<rest>.+)$"
)
_UNICODE_FRACTIONS = {
    "¼": 0.25,
    "½": 0.5,
    "¾": 0.75,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
}


def parse_markdown(markdown: str, filename: str | None = None) -> ParsedRecipe:
    """Parse one Markdown document into Cookit's structured recipe shape."""
    if not (markdown or "").strip():
        raise MarkdownImportError("That Markdown file is empty.")

    metadata, body = _front_matter(markdown.lstrip("\ufeff"))
    lines = body.splitlines()
    headings = _headings(lines)
    items, method_heading_seen = _list_items(lines, headings)

    ingredients = _ingredients(
        item.text for item in items if item.kind == "ingredients"
    )
    step_items = (
        [item.text for item in items if item.kind == "steps"]
        if method_heading_seen
        else [item.text for item in items if item.kind != "ingredients"]
    )
    steps = [_step(item) for item in step_items]
    steps = [step for step in steps if step.text]

    if not steps:
        raise MarkdownImportError(
            "No recipe steps found. Put them in a Markdown list, optionally under "
            "a Method, Steps, Recipe, Instructions, or Directions heading."
        )
    if len(steps) > MAX_STEPS:
        raise MarkdownImportError(f"A recipe can have at most {MAX_STEPS} steps.")
    if len(ingredients) > MAX_INGREDIENTS:
        raise MarkdownImportError(
            f"A recipe can have at most {MAX_INGREDIENTS} ingredients."
        )

    name = _recipe_name(metadata, headings, lines, filename)
    if len(name) > 300:
        raise MarkdownImportError("The recipe title is longer than 300 characters.")
    for ingredient in ingredients:
        if len(ingredient.name) > 200:
            raise MarkdownImportError(
                f"The ingredient “{ingredient.name[:40]}…” is longer than 200 characters."
            )

    return ParsedRecipe(
        name=name,
        description=_description(lines, headings),
        cuisine=_scalar(metadata.get("cuisine"), 80),
        prep_minutes=_bounded_int(metadata.get("prep_minutes"), 0, 6000),
        cook_minutes=_bounded_int(metadata.get("cook_minutes"), 0, 6000),
        servings=_bounded_int(metadata.get("servings"), 1, 99),
        difficulty=_difficulty(metadata.get("difficulty")),
        source_url=_scalar(metadata.get("source") or metadata.get("source_url"), 2000),
        notes=_section_text(lines, headings, "notes"),
        meal_types=_meals(metadata.get("meals") or metadata.get("meal_types")),
        ingredients=ingredients,
        steps=steps,
    )


def import_markdown(
    db: Session, user: User, markdown: str, filename: str | None = None
):
    """Create a dish and any missing shelf ingredients in one transaction."""
    recipe = parse_markdown(markdown, filename)
    if dish_service.get_by_name(db, user.id, recipe.name):
        raise dish_service.AlreadyExists(recipe.name)

    try:
        dish = dish_service.create(
            db,
            user,
            name=recipe.name,
            description=recipe.description,
            cuisine=recipe.cuisine,
            prep_minutes=recipe.prep_minutes,
            cook_minutes=recipe.cook_minutes,
            servings=recipe.servings,
            difficulty=recipe.difficulty,
            source_url=recipe.source_url,
            notes=recipe.notes,
            meal_types=recipe.meal_types,
            commit=False,
        )

        keys = [name_key(item.name) for item in recipe.ingredients]
        shelf = {
            item.name_key: item
            for item in db.query(Ingredient)
            .filter(Ingredient.user_id == user.id, Ingredient.name_key.in_(keys))
            .all()
        }
        for item in recipe.ingredients:
            key = name_key(item.name)
            if key not in shelf:
                shelf[key] = ingredient_service.create(
                    db, user, name=item.name, commit=False
                )
        db.flush()

        dish_service.set_ingredients(
            db,
            dish,
            [
                {
                    "ingredient_id": shelf[name_key(item.name)].id,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "note": item.note,
                    "is_optional": item.is_optional,
                }
                for item in recipe.ingredients
            ],
            commit=False,
        )
        dish_service.set_steps(
            db,
            dish,
            [{"text": step.text, "minutes": step.minutes} for step in recipe.steps],
            commit=False,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise dish_service.AlreadyExists(recipe.name) from exc
    except Exception:
        db.rollback()
        raise

    return dish_service.get(db, user.id, dish.dish_uuid)


def _front_matter(markdown: str) -> tuple[dict[str, str], str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, markdown

    values: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        if key:
            values[key] = value.strip()
    return values, "\n".join(lines[end + 1 :])


def _headings(lines: list[str]) -> dict[int, tuple[int, str]]:
    headings: dict[int, tuple[int, str]] = {}
    fenced = False
    fence_char = ""
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fenced:
                fenced, fence_char = True, marker
            elif marker == fence_char:
                fenced = False
            continue
        if fenced:
            continue

        match = _ATX_HEADING_RE.match(line)
        if match:
            headings[index] = (len(match.group(1)), _inline_text(match.group(2)))
            continue

        if (
            index + 1 < len(lines)
            and line.strip()
            and not _LIST_RE.match(line)
            and (underline := _SETEXT_RE.match(lines[index + 1]))
        ):
            headings[index] = (
                1 if underline.group(1).startswith("=") else 2,
                _inline_text(line),
            )
            continue

        label = _heading_label(line)
        if label in _KNOWN_LABELS:
            headings[index] = (2, _inline_text(line).rstrip(":"))
            continue
        # Notes copied from editors often use ``Shopping:`` rather than a real
        # Markdown heading. Treat a short colon label as a sibling section so
        # its list does not accidentally inherit Ingredients.
        if line.strip().endswith(":") and len(line.strip()) <= 120:
            headings[index] = (2, _inline_text(line).rstrip(":"))
    return headings


def _list_items(
    lines: list[str], headings: dict[int, tuple[int, str]]
) -> tuple[list[_ListItem], bool]:
    items: list[_ListItem] = []
    stack: list[tuple[int, str | None]] = []
    current: _ListItem | None = None
    method_heading_seen = False
    fenced = False
    fence_char = ""
    setext_underlines = {
        index + 1
        for index in headings
        if index + 1 < len(lines) and _SETEXT_RE.match(lines[index + 1])
    }

    def finish() -> None:
        nonlocal current
        if current and current.text.strip():
            items.append(current)
        current = None

    for index, original in enumerate(lines):
        stripped = original.lstrip()
        if stripped.startswith(("```", "~~~")):
            finish()
            marker = stripped[:3]
            if not fenced:
                fenced, fence_char = True, marker
            elif marker == fence_char:
                fenced = False
            continue
        if fenced:
            continue

        if index in headings:
            finish()
            level, title = headings[index]
            while stack and stack[-1][0] >= level:
                stack.pop()
            explicit = _heading_kind(title)
            inherited = stack[-1][1] if stack else None
            kind = explicit if explicit is not None else inherited
            stack.append((level, kind))
            method_heading_seen = method_heading_seen or explicit == "steps"
            continue
        if index in setext_underlines:
            continue

        # A quoted list is still a list. Removing only the quote prefix keeps
        # ordinary indentation available for continuation detection.
        candidate = re.sub(r"^\s*(?:>\s*)+", "", original)
        match = _LIST_RE.match(candidate)
        if match:
            finish()
            text = _TASK_RE.sub("", match.group(1)).strip()
            current = _ListItem(stack[-1][1] if stack else None, text)
            continue

        if current and original[:1].isspace() and stripped:
            if not _IMAGE_RE.match(stripped) and not stripped.startswith("<!--"):
                current.text += " " + stripped
        elif stripped:
            finish()

    finish()
    return items, method_heading_seen


def _heading_label(value: str) -> str:
    value = value.strip().rstrip(":").strip()
    value = re.sub(r"^(?:\*\*|__)(.*)(?:\*\*|__)$", r"\1", value)
    return _normal_heading(value)


def _normal_heading(value: str) -> str:
    value = _inline_text(value).lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _heading_kind(title: str) -> str | None:
    label = _normal_heading(title)
    if label in _INGREDIENT_HEADINGS:
        return "ingredients"
    words = set(label.split())
    if (
        label in _METHOD_HEADINGS
        or words
        & {
            "direction",
            "directions",
            "instruction",
            "instructions",
            "method",
            "methods",
            "procedure",
            "recipe",
            "step",
            "steps",
        }
        or label.startswith("how to ")
    ):
        return "steps"
    if label in _NOTE_HEADINGS:
        return "notes"
    return None


def _ingredients(values) -> list[ImportedIngredient]:
    result: list[ImportedIngredient] = []
    seen: set[str] = set()
    for value in values:
        ingredient = _ingredient(value)
        key = name_key(ingredient.name)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(ingredient)
    return result


def _ingredient(value: str) -> ImportedIngredient:
    text = _inline_text(value).strip()
    note = None
    optional = False
    note_match = re.search(r"\s*\(([^()]*)\)\s*$", text)
    if note_match:
        parts = [part.strip() for part in note_match.group(1).split(",")]
        optional = any(part.lower() == "optional" for part in parts)
        notes = [part for part in parts if part and part.lower() != "optional"]
        note = ", ".join(notes) or None
        text = text[: note_match.start()].strip()

    # Common prose amounts without a numeric quantity.
    unit = None
    for prefix in ("to taste", "as needed"):
        if text.lower().startswith(prefix + " "):
            unit, text = text[: len(prefix)], text[len(prefix) :].strip()
            break

    quantity = None
    match = _QUANTITY_RE.match(text)
    if match:
        quantity = _number(match.group("quantity"))
        text = match.group("rest").strip()
        first, separator, rest = text.partition(" ")
        if first.lower().rstrip(".,") in _UNITS and rest:
            unit = first.rstrip(".,")
            text = rest.strip()
            if text.lower().startswith("of "):
                text = text[3:].strip()

    name = _inline_text(text).strip(" ,;:-")
    if not name:
        raise MarkdownImportError(f"Could not find an ingredient name in “{value}”.")
    return ImportedIngredient(name, quantity, unit, note, optional)


def _number(value: str) -> float:
    if value in _UNICODE_FRACTIONS:
        return _UNICODE_FRACTIONS[value]
    if " " in value:
        whole, fraction = value.split(None, 1)
        return float(whole) + _number(fraction)
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        if float(denominator) == 0:
            raise MarkdownImportError("An ingredient quantity cannot divide by zero.")
        return float(numerator) / float(denominator)
    return float(value)


def _step(value: str) -> ImportedStep:
    minutes = None
    match = _MINUTES_RE.search(value)
    if match:
        minutes = int(match.group(1))
        value = value[: match.start()]
    return ImportedStep(_inline_text(value).strip(), minutes)


def _inline_text(value: str) -> str:
    """Flatten inline Markdown into the plain prose stored by the editor."""
    text = _HTML_COMMENT_RE.sub("", value or "")
    text = _LINK_RE.sub(lambda match: match.group(1), text)
    text = _AUTOLINK_RE.sub(lambda match: match.group(1), text)
    text = re.sub(r"(`{1,3}|\*{1,3}|_{1,3}|~~)", "", text)
    text = re.sub(r"\\([\\`*{}\[\]()#+.!_>-])", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def _recipe_name(
    metadata: dict[str, str],
    headings: dict[int, tuple[int, str]],
    lines: list[str],
    filename: str | None,
) -> str:
    title = _scalar(metadata.get("title"), 300)
    if title:
        return title
    for index, (level, value) in headings.items():
        if level == 1 and _heading_kind(value) is None:
            return value[:300]

    stem = Path(filename or "").name
    stem = re.sub(r"\.(?:markdown|md)$", "", stem, flags=re.IGNORECASE)
    stem = " ".join(re.sub(r"[-_]+", " ", stem).split())
    if stem:
        return stem[:300]
    raise MarkdownImportError(
        "Give the recipe a level-one heading (# Recipe name) or a filename."
    )


def _description(
    lines: list[str], headings: dict[int, tuple[int, str]]
) -> str | None:
    title_index = next(
        (
            index
            for index, (level, title) in headings.items()
            if level == 1 and _heading_kind(title) is None
        ),
        None,
    )
    if title_index is None:
        return None
    collected: list[str] = []
    fenced = False
    fence_char = ""
    for index in range(title_index + 1, len(lines)):
        if index in headings:
            break
        text = lines[index].strip()
        if text.startswith(("```", "~~~")):
            marker = text[:3]
            if not fenced:
                fenced, fence_char = True, marker
            elif marker == fence_char:
                fenced = False
            continue
        if fenced:
            continue
        if not text:
            if collected:
                break
            continue
        if (
            _IMAGE_RE.match(text)
            or text == "---"
            or text.startswith("**Good for**")
            or _LIST_RE.match(text)
        ):
            if collected:
                break
            continue
        collected.append(_inline_text(text))
    value = " ".join(part for part in collected if part).strip()
    return value or None


def _section_text(
    lines: list[str], headings: dict[int, tuple[int, str]], kind: str
) -> str | None:
    start = next(
        (index for index, heading in headings.items() if _heading_kind(heading[1]) == kind),
        None,
    )
    if start is None:
        return None
    level = headings[start][0]
    values: list[str] = []
    for index in range(start + 1, len(lines)):
        if index in headings and headings[index][0] <= level:
            break
        text = lines[index].strip()
        if text in {"---", "***", "___"}:
            break
        if text and not _IMAGE_RE.match(text):
            values.append(_inline_text(text))
    value = "\n".join(part for part in values if part).strip()
    return value or None


def _scalar(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = value[1:-1]
    elif len(value) >= 2 and value[0] == value[-1] == "'":
        value = value[1:-1].replace("''", "'")
    value = " ".join(str(value).split())
    return value[:limit] or None


def _bounded_int(value: str | None, minimum: int, maximum: int) -> int | None:
    clean = _scalar(value, 20)
    if clean is None:
        return None
    try:
        number = int(clean)
    except ValueError:
        return None
    return number if minimum <= number <= maximum else None


def _difficulty(value: str | None) -> str:
    clean = (_scalar(value, 20) or "").lower()
    return clean if Difficulty.has(clean) else Difficulty.EASY


def _meals(value: str | None) -> list[str]:
    clean = _scalar(value, 200)
    if not clean:
        return []
    if clean.startswith("[") and clean.endswith("]"):
        clean = clean[1:-1]
    values = [part.strip().strip("'\"").lower() for part in clean.split(",")]
    return list(dict.fromkeys(part for part in values if MealType.has(part)))
