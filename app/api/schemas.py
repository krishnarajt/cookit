"""Request and response bodies. Enums come straight from app/enums.py."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.enums import (
    CookSource,
    Difficulty,
    IngredientCategory,
    IngredientMatch,
    MealType,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Auth / users
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    # No rules on the password itself, deliberately.
    password: str = Field(min_length=1)
    display_name: Optional[str] = Field(default=None, max_length=200)

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("Username cannot be blank")
        if any(char.isspace() for char in value):
            raise ValueError("Username cannot contain spaces")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1)


class UserOut(ORMModel):
    id: int
    user_uuid: str
    username: str
    display_name: str
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class ExternalIdentityOut(BaseModel):
    linked: bool
    email: Optional[str] = None
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsOut(ORMModel):
    timezone: str = "UTC"
    default_servings: Optional[int] = 2
    avoid_recent_days: Optional[int] = 2


class SettingsUpdate(BaseModel):
    timezone: Optional[str] = Field(default=None, max_length=64)
    default_servings: Optional[int] = Field(default=None, ge=1, le=99)
    avoid_recent_days: Optional[int] = Field(default=None, ge=0, le=90)


# ---------------------------------------------------------------------------
# Ingredients
# ---------------------------------------------------------------------------

class IngredientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: Optional[IngredientCategory] = None
    default_unit: Optional[str] = Field(default=None, max_length=30)
    emoji: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = None
    is_staple: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Ingredient name cannot be blank")
        return value


class IngredientUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    category: Optional[IngredientCategory] = None
    default_unit: Optional[str] = Field(default=None, max_length=30)
    emoji: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = None
    is_staple: Optional[bool] = None


class IngredientBulkCreate(BaseModel):
    """Either a pasted blob or an explicit list — the UI sends whichever it has.

    `text` is what the quick-add box posts: newline, comma or semicolon
    separated, list bullets and numbering tolerated, because the text people
    paste came out of a recipe or a notes app.
    """

    text: Optional[str] = None
    names: Optional[list[str]] = None

    @model_validator(mode="after")
    def need_something(self):
        if not (self.text or "").strip() and not self.names:
            raise ValueError("Give some ingredient names to add")
        return self


class IngredientOut(ORMModel):
    id: int
    ingredient_uuid: str
    name: str
    category: str
    default_unit: Optional[str] = None
    emoji: Optional[str] = None
    notes: Optional[str] = None
    is_staple: bool
    # How many dishes use it. Filled in by the route from one grouped query.
    used_in: int = 0
    created_at: Optional[datetime] = None


class IngredientBulkResult(BaseModel):
    created: list[IngredientOut]
    already_there: list[IngredientOut]


class IngredientSuggestion(BaseModel):
    """A catalogue chip — not a row yet. Tapping one POSTs it as a real create."""

    name: str
    category: str
    default_unit: Optional[str] = None
    emoji: Optional[str] = None
    is_staple: bool = False


# ---------------------------------------------------------------------------
# Dishes
# ---------------------------------------------------------------------------

class DishIngredientIn(BaseModel):
    ingredient_uuid: str
    quantity: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = Field(default=None, max_length=30)
    note: Optional[str] = None
    is_optional: bool = False


class DishIngredientOut(BaseModel):
    ingredient_uuid: str
    name: str
    category: str
    emoji: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    note: Optional[str] = None
    is_optional: bool = False
    sort_order: int = 0


class DishImageOut(ORMModel):
    image_uuid: str
    image_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    caption: Optional[str] = None
    is_cover: bool = False
    sort_order: int = 0
    # Set when this photo belongs beside one instruction rather than to the
    # dish gallery. The client never needs the internal step id.
    step_uuid: Optional[str] = None
    created_at: Optional[datetime] = None


class DishImageUpdate(BaseModel):
    caption: Optional[str] = None
    is_cover: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=0, le=999)


class PresignedUrlOut(BaseModel):
    image_uuid: Optional[str] = None
    url: str
    expires_in: int


class StepIn(BaseModel):
    """One instruction. `text` may carry `@[name](uuid)` ingredient mentions.

    `step_uuid` is how a save says "this is the same step, edited" rather than
    "delete everything and write it again". Sending it back is what keeps the
    step's photos attached across a reorder or a reword; omitting it — a row the
    editor just added — inserts a new step.
    """

    step_uuid: Optional[str] = None
    text: str = Field(min_length=1)
    minutes: Optional[int] = Field(default=None, ge=0, le=6000)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A step cannot be blank")
        return value


class StepsReplace(BaseModel):
    steps: list[StepIn] = Field(default_factory=list, max_length=100)


class StepOut(BaseModel):
    step_uuid: str
    step_index: int
    text: str
    # The same text with mentions flattened to plain names — what a step reads
    # like out loud, so the client never has to parse the markup to speak it.
    plain_text: str
    minutes: Optional[int] = None
    # Which ingredients this step mentions, resolved. Lets cook mode show
    # "you'll need…" beside a single step.
    ingredients: list[DishIngredientOut] = Field(default_factory=list)
    # Photos of this step, in order. Any number — "fold it like this, then like
    # this" is two photos of one instruction.
    images: list[DishImageOut] = Field(default_factory=list)


class DishCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: Optional[str] = None
    cuisine: Optional[str] = Field(default=None, max_length=80)
    prep_minutes: Optional[int] = Field(default=None, ge=0, le=6000)
    cook_minutes: Optional[int] = Field(default=None, ge=0, le=6000)
    servings: Optional[int] = Field(default=None, ge=1, le=99)
    difficulty: Difficulty = Difficulty.EASY
    source_url: Optional[str] = Field(default=None, max_length=2000)
    notes: Optional[str] = None
    meal_types: list[MealType] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Dish name cannot be blank")
        return value

    @field_validator("meal_types")
    @classmethod
    def dedupe_meals(cls, value: list[MealType]) -> list[MealType]:
        return list(dict.fromkeys(value))


class DishUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = None
    cuisine: Optional[str] = Field(default=None, max_length=80)
    prep_minutes: Optional[int] = Field(default=None, ge=0, le=6000)
    cook_minutes: Optional[int] = Field(default=None, ge=0, le=6000)
    servings: Optional[int] = Field(default=None, ge=1, le=99)
    difficulty: Optional[Difficulty] = None
    source_url: Optional[str] = Field(default=None, max_length=2000)
    notes: Optional[str] = None
    is_favorite: Optional[bool] = None
    meal_types: Optional[list[MealType]] = None


class DishSummary(BaseModel):
    """What a card needs. No steps, no full ingredient rows — a list of 200 of
    these is one page of JSON, and the detail endpoint is one tap away."""

    dish_uuid: str
    name: str
    description: Optional[str] = None
    cuisine: Optional[str] = None
    prep_minutes: Optional[int] = None
    cook_minutes: Optional[int] = None
    total_minutes: Optional[int] = None
    servings: Optional[int] = None
    difficulty: str = Difficulty.EASY
    is_favorite: bool = False
    meal_types: list[str] = Field(default_factory=list)
    ingredient_count: int = 0
    step_count: int = 0
    # Gallery photos only. Step photos are counted per step, and a card that
    # said "9 photos" for a dish whose Photos tab shows one would just be wrong.
    image_count: int = 0
    step_image_count: int = 0
    cover_image_uuid: Optional[str] = None
    times_cooked: int = 0
    last_cooked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DishDetail(DishSummary):
    source_url: Optional[str] = None
    notes: Optional[str] = None
    ingredients: list[DishIngredientOut] = Field(default_factory=list)
    steps: list[StepOut] = Field(default_factory=list)
    # The dish gallery. A step's photos travel on the step, not here.
    images: list[DishImageOut] = Field(default_factory=list)
    often_had_with: list[DishSummary] = Field(default_factory=list)


class DishIngredientsReplace(BaseModel):
    ingredients: list[DishIngredientIn] = Field(default_factory=list, max_length=100)


class PairingRequest(BaseModel):
    """Pair by UUID, or by name — the UI's "add a dish" box accepts both.

    A name that doesn't exist yet is created, because the natural way to record
    "rice goes with this" is to type "rice" whether or not it is already a dish.
    """

    dish_uuid: Optional[str] = None
    name: Optional[str] = Field(default=None, max_length=300)
    note: Optional[str] = None

    @model_validator(mode="after")
    def need_one(self):
        if not self.dish_uuid and not (self.name or "").strip():
            raise ValueError("Give a dish to pair with")
        return self


# ---------------------------------------------------------------------------
# Cook log
# ---------------------------------------------------------------------------

class CookRequest(BaseModel):
    meal_type: Optional[MealType] = None
    source: CookSource = CookSource.MANUAL
    note: Optional[str] = None


class CookEventOut(BaseModel):
    id: int
    dish_uuid: str
    dish_name: str
    cover_image_uuid: Optional[str] = None
    cooked_at: datetime
    meal_type: Optional[str] = None
    source: str
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Randomizer
# ---------------------------------------------------------------------------

class SpinRequest(BaseModel):
    """Everything the wheel is allowed to be told.

    All optional: an empty body is "surprise me from the whole book", which is
    the button most people press.
    """

    meal_types: list[MealType] = Field(default_factory=list)
    ingredient_uuids: list[str] = Field(default_factory=list, max_length=100)
    match: IngredientMatch = IngredientMatch.ANY
    favorites_only: bool = False
    max_total_minutes: Optional[int] = Field(default=None, ge=1, le=6000)
    difficulty: Optional[Difficulty] = None
    # Unset means "use my saved preference"; 0 means "no window, everything is
    # in play". Those are different answers, so this cannot default to 0.
    avoid_recent_days: Optional[int] = Field(default=None, ge=0, le=90)
    # Off means a flat draw. On, staleness decides — see randomizer_service.
    weighted: bool = True
    # What "spin again" sends so the wheel can't hand back the same answer.
    exclude_dish_uuids: list[str] = Field(default_factory=list, max_length=50)


class SpinResult(BaseModel):
    dish: Optional[DishDetail] = None
    # The dishes the wheel draws, winner always among them.
    slices: list[DishSummary] = Field(default_factory=list)
    pool_size: int = 0
    weighted: bool = True


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class MealTypeCount(BaseModel):
    meal_type: str
    count: int


class DashboardOut(BaseModel):
    dish_count: int
    ingredient_count: int
    step_count: int
    cooks_this_week: int
    cooks_all_time: int
    favorite_count: int
    never_cooked: int
    by_meal_type: list[MealTypeCount] = Field(default_factory=list)
    # Longest-unmade dishes — the "you haven't had this in a while" shelf.
    overdue: list[DishSummary] = Field(default_factory=list)
    recent_cooks: list[CookEventOut] = Field(default_factory=list)
    # The ingredients in most dishes, for the filter bar's first row.
    top_ingredients: list[IngredientOut] = Field(default_factory=list)
