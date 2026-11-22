"""
Every enumerated value used by Cookit.

These are `StrEnum`s, so a member *is* a string: SQLAlchemy stores it in a plain
`String` column, `json.dumps` handles it, and Pydantic validates request bodies
against it for free. Reading a row back gives a plain `str`, and comparing that
to a member still works (`row.meal_type == MealType.DINNER`).

Deliberately not Postgres ENUM types — adding a meal or an ingredient category
should be a code change, not a migration.
"""

from enum import StrEnum


class _Enum(StrEnum):
    """StrEnum plus a couple of conveniences for validation."""

    @classmethod
    def values(cls) -> list[str]:
        return [member.value for member in cls]

    @classmethod
    def has(cls, value: str) -> bool:
        return value in cls._value2member_map_


class MealType(_Enum):
    """When a dish is eaten. A dish can carry any combination of these."""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SUPPER = "supper"


class IngredientCategory(_Enum):
    """How the ingredients tab groups the shelf.

    Purely organisational — nothing filters or cooks differently because of it,
    so a wrong guess costs a tap to fix.
    """

    PRODUCE = "produce"
    PROTEIN = "protein"
    DAIRY = "dairy"
    GRAIN = "grain"
    LEGUME = "legume"
    SPICE = "spice"
    HERB = "herb"
    SAUCE = "sauce"
    PANTRY = "pantry"
    SWEET = "sweet"
    DRINK = "drink"
    OTHER = "other"


class MeasureUnit(_Enum):
    """Suggested units for the amount pickers.

    `dish_ingredients.unit` is a free String, not this enum: half of cooking is
    "a splash" and refusing to store that would be worse than a tidy list. These
    are only what the UI offers first.
    """

    G = "g"
    KG = "kg"
    ML = "ml"
    L = "l"
    TSP = "tsp"
    TBSP = "tbsp"
    CUP = "cup"
    PIECE = "piece"
    CLOVE = "clove"
    SLICE = "slice"
    PINCH = "pinch"
    HANDFUL = "handful"
    TO_TASTE = "to taste"


class Difficulty(_Enum):
    """Roughly how much attention a dish wants."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class CookSource(_Enum):
    """How a dish came to be cooked — the randomizer, or a deliberate choice.

    Kept so the dashboard can honestly say "the wheel picked this" rather than
    implying you chose it.
    """

    RANDOMIZER = "randomizer"
    MANUAL = "manual"


class IngredientMatch(_Enum):
    """How a multi-ingredient filter combines.

    ANY is the useful default for "what can I make with these?" — one match is
    a reason to consider a dish. ALL is the strict reading, for when the fridge
    really does only hold those things.
    """

    ANY = "any"
    ALL = "all"
