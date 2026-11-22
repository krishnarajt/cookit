"""
Database models for Cookit.

Everything time-related is stored in UTC (`DateTime(timezone=True)`). The UI
converts to local time for display only.

Everything a person creates — ingredients, dishes, photos — belongs to that
person. There is no sharing model, so every query in the API filters on
`user_id` and two people can both own "onion" without colliding.

Enumerated column values live in app/enums.py.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.db.database import Base
from app.enums import CookSource, Difficulty, IngredientCategory


def generate_uuid():
    """Generate a unique UUID string"""
    return str(uuid.uuid4())


def name_key(name: str) -> str:
    """The form an ingredient or dish name is compared by.

    Case and stray spacing are the two ways the same ingredient gets typed
    twice, so both are flattened out of the key while `name` keeps whatever the
    person actually wrote. "Extra  Virgin Olive Oil" and "extra virgin olive
    oil" are one shelf entry.
    """
    return " ".join((name or "").strip().lower().split())


class User(Base):
    """A person. `username` is the unique handle, `display_name` is what the UI shows."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_uuid = Column(String(36), default=generate_uuid, unique=True, index=True)

    username = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(Text, nullable=False)
    password_hash = Column(String(255), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    settings = relationship(
        "UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    external_identities = relationship(
        "ExternalIdentity", back_populates="user", cascade="all, delete-orphan"
    )
    ingredients = relationship(
        "Ingredient", back_populates="user", cascade="all, delete-orphan"
    )
    dishes = relationship("Dish", back_populates="user", cascade="all, delete-orphan")


class ExternalIdentity(Base):
    """An optional SSO identity; local password accounts remain authoritative."""

    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "subject", name="uq_external_identity_provider_subject"
        ),
        UniqueConstraint(
            "provider", "user_id", name="uq_external_identity_provider_user"
        ),
    )

    id = Column(Integer, primary_key=True)
    provider = Column(String(50), nullable=False, default="authentik")
    subject = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="external_identities")


class RefreshToken(Base):
    """Stores refresh tokens for JWT authentication"""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(500), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


class UserSettings(Base):
    """Per-user preferences. Display and default-value only."""

    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # IANA name, e.g. "Asia/Kolkata". Display only.
    timezone = Column(String(64), default="UTC")
    # Pre-filled on a new dish, so the common case is already right.
    default_servings = Column(Integer, default=2)
    # The wheel's default "don't offer me what I just ate" window, in days.
    # 0 means everything is always in play.
    avoid_recent_days = Column(Integer, default=2)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="settings")


class Ingredient(Base):
    """One thing on the shelf.

    `name_key` is the comparison form (see `name_key()` above) and carries the
    per-user unique index, so adding "Onion" when "onion" exists updates rather
    than duplicates. `name` keeps the spelling the person typed.
    """

    __tablename__ = "ingredients"
    __table_args__ = (
        UniqueConstraint("user_id", "name_key", name="uq_ingredient_per_user"),
        Index("ix_ingredients_user_category", "user_id", "category"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ingredient_uuid = Column(String(36), default=generate_uuid, unique=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name = Column(Text, nullable=False)
    name_key = Column(String(200), nullable=False)

    category = Column(String(30), default=IngredientCategory.OTHER, nullable=False)
    # A short unit hint for the amount picker ("g", "clove"). Not enforced.
    default_unit = Column(String(30), nullable=True)
    # One character of decoration, chosen by the person or the catalogue. The
    # ingredients tab is a wall of names otherwise.
    emoji = Column(String(16), nullable=True)
    notes = Column(Text, nullable=True)
    # A staple always in the house. The randomizer treats these as available
    # without being ticked, which is what stops "salt" ruining every filter.
    is_staple = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="ingredients")
    dish_links = relationship(
        "DishIngredient", back_populates="ingredient", cascade="all, delete-orphan"
    )
    step_links = relationship(
        "RecipeStepIngredient", back_populates="ingredient", cascade="all, delete-orphan"
    )


class Dish(Base):
    """Something you can cook, and everything known about it.

    The recipe itself is `steps`; the shopping side is `dish_ingredients`. Both
    are separate tables rather than a blob of markdown, which is what makes
    "filter by ingredient" and "read me one step at a time" possible at all.
    """

    __tablename__ = "dishes"
    __table_args__ = (
        UniqueConstraint("user_id", "name_key", name="uq_dish_per_user"),
        Index("ix_dishes_user_favorite", "user_id", "is_favorite"),
    )

    id = Column(Integer, primary_key=True, index=True)
    dish_uuid = Column(String(36), default=generate_uuid, unique=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name = Column(Text, nullable=False)
    name_key = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)

    cuisine = Column(String(80), nullable=True)
    prep_minutes = Column(Integer, nullable=True)
    cook_minutes = Column(Integer, nullable=True)
    servings = Column(Integer, nullable=True)
    difficulty = Column(String(20), default=Difficulty.EASY, nullable=False)

    source_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_favorite = Column(Boolean, default=False, nullable=False)

    # Denormalised from `cook_events` so a list of 200 dishes doesn't need a
    # correlated subquery per row. Both are recomputed whenever a cook is logged
    # or deleted — cook_events stays the record of truth.
    times_cooked = Column(Integer, default=0, nullable=False)
    last_cooked_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="dishes")
    meal_types = relationship(
        "DishMealType",
        back_populates="dish",
        cascade="all, delete-orphan",
        order_by="DishMealType.id",
    )
    ingredients = relationship(
        "DishIngredient",
        back_populates="dish",
        cascade="all, delete-orphan",
        order_by="DishIngredient.sort_order",
    )
    steps = relationship(
        "RecipeStep",
        back_populates="dish",
        cascade="all, delete-orphan",
        order_by="RecipeStep.step_index",
    )
    images = relationship(
        "DishImage",
        back_populates="dish",
        cascade="all, delete-orphan",
        order_by="DishImage.sort_order",
    )
    cook_events = relationship(
        "CookEvent", back_populates="dish", cascade="all, delete-orphan"
    )


class DishMealType(Base):
    """One row per meal a dish suits — the multi-select, normalised.

    A row per value rather than a JSON array because the whole point is
    filtering ("what's for breakfast?"), and that wants an index.
    """

    __tablename__ = "dish_meal_types"
    __table_args__ = (
        UniqueConstraint("dish_id", "meal_type", name="uq_dish_meal_type"),
        Index("ix_dish_meal_types_meal", "meal_type"),
    )

    id = Column(Integer, primary_key=True)
    dish_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meal_type = Column(String(20), nullable=False)

    dish = relationship("Dish", back_populates="meal_types")


class DishIngredient(Base):
    """An ingredient a dish needs, with how much of it.

    `quantity` and `unit` are both optional and `unit` is free text: "2 cloves",
    "a splash", and "salt" all have to fit. `sort_order` is the order the person
    arranged them in, which is usually the order they get used.
    """

    __tablename__ = "dish_ingredients"
    __table_args__ = (
        UniqueConstraint("dish_id", "ingredient_id", name="uq_dish_ingredient"),
        Index("ix_dish_ingredients_ingredient", "ingredient_id"),
    )

    id = Column(Integer, primary_key=True)
    dish_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_id = Column(
        Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )

    quantity = Column(Float, nullable=True)
    unit = Column(String(30), nullable=True)
    note = Column(Text, nullable=True)  # "finely chopped", "room temperature"
    is_optional = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    dish = relationship("Dish", back_populates="ingredients")
    ingredient = relationship("Ingredient", back_populates="dish_links")


class RecipeStep(Base):
    """One instruction.

    A row per step, not one markdown field, because a step is a thing the app
    has to be able to hand over on its own — read aloud, sent to a chat, ticked
    off in cook mode. `step_index` is 0-based and contiguous; the API rewrites
    the whole ladder rather than leaving gaps.

    `text` may contain ingredient mentions in the form `@[name](uuid)`. The
    canonical form is written by the editor and parsed by
    app/services/mention_service.py, which is also what keeps
    `recipe_step_ingredients` and the dish's ingredient list in step with what
    the recipe actually says.
    """

    __tablename__ = "recipe_steps"
    __table_args__ = (
        UniqueConstraint("dish_id", "step_index", name="uq_step_index_per_dish"),
    )

    id = Column(Integer, primary_key=True)
    step_uuid = Column(String(36), default=generate_uuid, unique=True, index=True)
    dish_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    step_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    # An optional timer for this step alone, e.g. "simmer 20 minutes".
    minutes = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    dish = relationship("Dish", back_populates="steps")
    ingredient_links = relationship(
        "RecipeStepIngredient", back_populates="step", cascade="all, delete-orphan"
    )
    images = relationship(
        "DishImage",
        back_populates="step",
        order_by="DishImage.sort_order",
        # No delete-orphan, and ON DELETE SET NULL on the column: deleting a
        # step releases its photos back to the dish gallery instead of
        # destroying them. Losing a photo taken at the stove because a step got
        # reworded is not a trade anyone would make.
        #
        # Deliberately not passive_deletes — SQLAlchemy nulls the children
        # itself, which is what makes this work on local SQLite, where foreign
        # keys (and so ON DELETE) are off unless a PRAGMA turns them on.
    )


class RecipeStepIngredient(Base):
    """Which ingredients a single step mentions.

    Derived from the step's text on every write, never edited directly. It
    exists so a step can be handed over complete — "now add the 2 cloves of
    garlic" — without re-parsing prose at read time.
    """

    __tablename__ = "recipe_step_ingredients"
    __table_args__ = (
        UniqueConstraint("step_id", "ingredient_id", name="uq_step_ingredient"),
    )

    id = Column(Integer, primary_key=True)
    step_id = Column(
        Integer,
        ForeignKey("recipe_steps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ingredient_id = Column(
        Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )

    step = relationship("RecipeStep", back_populates="ingredient_links")
    ingredient = relationship("Ingredient", back_populates="step_links")


def pairing_pair(dish_id_1: int, dish_id_2: int) -> tuple[int, int]:
    """Order two dish ids the way `dish_pairings` stores them (see below)."""
    return (min(dish_id_1, dish_id_2), max(dish_id_1, dish_id_2))


class DishPairing(Base):
    """"Often had with" — one row per pair, not two.

    Pairing is mutual: if rice goes with dal then dal goes with rice, and
    nobody wants to record that twice. The pair is stored canonically sorted
    (`dish_a_id < dish_b_id`, enforced by a CHECK) so a unique index prevents
    duplicates and the lookup is a single OR rather than a union.

    Partners of dish X:
        SELECT CASE WHEN dish_a_id = :x THEN dish_b_id ELSE dish_a_id END
        FROM dish_pairings WHERE :x IN (dish_a_id, dish_b_id)

    Use `pairing_pair()` before querying or inserting.
    """

    __tablename__ = "dish_pairings"
    __table_args__ = (
        UniqueConstraint("dish_a_id", "dish_b_id", name="uq_dish_pairing"),
        CheckConstraint("dish_a_id < dish_b_id", name="ck_dish_pairing_ordered"),
        Index("ix_dish_pairings_b", "dish_b_id"),
    )

    id = Column(Integer, primary_key=True)
    dish_a_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dish_b_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False
    )
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    dish_a = relationship("Dish", foreign_keys=[dish_a_id])
    dish_b = relationship("Dish", foreign_keys=[dish_b_id])


class DishImage(Base):
    """A photo, stored in MinIO. A dish can have any number.

    `step_id` is what makes a photo *of a step* rather than of the dish. Null
    means the dish gallery — the cover and the "more photos" page. Set means it
    belongs beside one instruction, and a step can carry several: "fold it like
    this, then like this" is two photos of one step, not two steps.

    One nullable column rather than a second table: a step photo and a gallery
    photo are the same thing in storage, differ only in where they are shown,
    and sharing the row means upload, presigning, deletion and the cleanup on
    dish delete all keep working untouched.
    """

    __tablename__ = "dish_images"

    id = Column(Integer, primary_key=True, index=True)
    image_uuid = Column(String(36), default=generate_uuid, unique=True, index=True)

    dish_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL, not CASCADE: see RecipeStep.images.
    step_id = Column(
        Integer,
        ForeignKey("recipe_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    image_name = Column(Text, nullable=True)  # Original filename
    mime_type = Column(String(100), nullable=True)  # e.g. "image/jpeg"
    file_size = Column(Integer, nullable=True)  # Size in bytes
    file_format = Column(String(10), nullable=True)  # jpg, png, etc.
    caption = Column(Text, nullable=True)

    minio_object_key = Column(String(500), nullable=False)
    minio_bucket = Column(String(100), nullable=True)

    # The one shown on cards and at the top of an export. Exactly one per dish;
    # setting a new cover clears the old one. Only a gallery photo is ever the
    # cover — a step photo is mid-process and rarely what the dish looks like.
    is_cover = Column(Boolean, default=False, nullable=False)
    # Position within whichever list this photo is in — the dish gallery, or
    # one step's strip.
    sort_order = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    dish = relationship("Dish", back_populates="images")
    step = relationship("RecipeStep", back_populates="images")
    user = relationship("User")


class CookEvent(Base):
    """A record that a dish actually got cooked.

    This is what makes the wheel smarter than a coin toss: a dish you had
    yesterday is a worse suggestion than one you haven't had in a month, and
    that only works if there is a history to read. `Dish.times_cooked` and
    `last_cooked_at` are caches over this table.
    """

    __tablename__ = "cook_events"
    __table_args__ = (Index("ix_cook_events_user_time", "user_id", "cooked_at"),)

    id = Column(Integer, primary_key=True, index=True)
    dish_id = Column(
        Integer, ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    cooked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    meal_type = Column(String(20), nullable=True)
    source = Column(String(20), default=CookSource.MANUAL, nullable=False)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    dish = relationship("Dish", back_populates="cook_events")
    user = relationship("User")
