"""
A starter shelf.

Typing out sixty ingredients before the app is any use is the thing most likely
to make someone close it, so the ingredients tab offers this catalogue as
one-tap chips: category, a sensible default unit, and an emoji so the list is
scannable rather than a wall of words.

It is only ever a *suggestion*. Nothing is inserted automatically, adding a
suggestion makes an ordinary editable row, and anything not here is typed in the
same box. Entries already on someone's shelf are filtered out of the
suggestions by name key, so the list shrinks as it gets used.

Biased towards an Indian kitchen with the global basics alongside, which is the
kitchen this was built for. Add to it freely — it is data, not schema.
"""

from app.enums import IngredientCategory as C

# (name, category, default unit, emoji, is_staple)
#
# `is_staple` marks the things that are simply always in the house. The
# randomizer treats staples as available whether or not they're ticked in a
# filter, which is what stops "salt" and "oil" quietly excluding every dish.
CATALOGUE: list[tuple[str, str, str | None, str, bool]] = [
    # --- produce ---------------------------------------------------------
    ("Onion", C.PRODUCE, "piece", "🧅", True),
    ("Tomato", C.PRODUCE, "piece", "🍅", True),
    ("Potato", C.PRODUCE, "piece", "🥔", True),
    ("Garlic", C.PRODUCE, "clove", "🧄", True),
    ("Ginger", C.PRODUCE, "g", "🫚", True),
    ("Green chilli", C.PRODUCE, "piece", "🌶️", True),
    ("Carrot", C.PRODUCE, "piece", "🥕", False),
    ("Capsicum", C.PRODUCE, "piece", "🫑", False),
    ("Cauliflower", C.PRODUCE, "g", "🥬", False),
    ("Cabbage", C.PRODUCE, "g", "🥬", False),
    ("Spinach", C.PRODUCE, "g", "🥬", False),
    ("Okra", C.PRODUCE, "g", "🥬", False),
    ("Brinjal", C.PRODUCE, "piece", "🍆", False),
    ("Peas", C.PRODUCE, "g", "🫛", False),
    ("Mushroom", C.PRODUCE, "g", "🍄", False),
    ("Corn", C.PRODUCE, "piece", "🌽", False),
    ("Cucumber", C.PRODUCE, "piece", "🥒", False),
    ("Lemon", C.PRODUCE, "piece", "🍋", True),
    ("Bottle gourd", C.PRODUCE, "g", "🥒", False),
    ("Pumpkin", C.PRODUCE, "g", "🎃", False),
    ("Beetroot", C.PRODUCE, "piece", "🥬", False),
    ("Sweet potato", C.PRODUCE, "piece", "🍠", False),
    ("Spring onion", C.PRODUCE, "piece", "🧅", False),
    ("Avocado", C.PRODUCE, "piece", "🥑", False),
    ("Banana", C.PRODUCE, "piece", "🍌", False),
    ("Apple", C.PRODUCE, "piece", "🍎", False),
    ("Mango", C.PRODUCE, "piece", "🥭", False),
    ("Coconut", C.PRODUCE, "g", "🥥", False),
    # --- protein ---------------------------------------------------------
    ("Egg", C.PROTEIN, "piece", "🥚", True),
    ("Chicken", C.PROTEIN, "g", "🍗", False),
    ("Mutton", C.PROTEIN, "g", "🍖", False),
    ("Fish", C.PROTEIN, "g", "🐟", False),
    ("Prawns", C.PROTEIN, "g", "🦐", False),
    ("Paneer", C.PROTEIN, "g", "🧈", False),
    ("Tofu", C.PROTEIN, "g", "🧈", False),
    ("Soya chunks", C.PROTEIN, "g", "🫘", False),
    # --- dairy -----------------------------------------------------------
    ("Milk", C.DAIRY, "ml", "🥛", True),
    ("Curd", C.DAIRY, "g", "🥣", True),
    ("Butter", C.DAIRY, "g", "🧈", True),
    ("Ghee", C.DAIRY, "tbsp", "🧈", True),
    ("Cream", C.DAIRY, "ml", "🥛", False),
    ("Cheese", C.DAIRY, "g", "🧀", False),
    ("Mozzarella", C.DAIRY, "g", "🧀", False),
    ("Buttermilk", C.DAIRY, "ml", "🥛", False),
    # --- grain -----------------------------------------------------------
    ("Rice", C.GRAIN, "g", "🍚", True),
    ("Basmati rice", C.GRAIN, "g", "🍚", False),
    ("Wheat flour", C.GRAIN, "g", "🌾", True),
    ("Maida", C.GRAIN, "g", "🌾", False),
    ("Semolina", C.GRAIN, "g", "🌾", False),
    ("Besan", C.GRAIN, "g", "🌾", False),
    ("Poha", C.GRAIN, "g", "🍚", False),
    ("Oats", C.GRAIN, "g", "🥣", False),
    ("Bread", C.GRAIN, "slice", "🍞", False),
    ("Pasta", C.GRAIN, "g", "🍝", False),
    ("Noodles", C.GRAIN, "g", "🍜", False),
    ("Vermicelli", C.GRAIN, "g", "🍜", False),
    ("Tortilla", C.GRAIN, "piece", "🫓", False),
    # --- legume ----------------------------------------------------------
    ("Toor dal", C.LEGUME, "g", "🫘", True),
    ("Moong dal", C.LEGUME, "g", "🫘", False),
    ("Chana dal", C.LEGUME, "g", "🫘", False),
    ("Masoor dal", C.LEGUME, "g", "🫘", False),
    ("Urad dal", C.LEGUME, "g", "🫘", False),
    ("Chickpeas", C.LEGUME, "g", "🫘", False),
    ("Rajma", C.LEGUME, "g", "🫘", False),
    ("Black beans", C.LEGUME, "g", "🫘", False),
    ("Peanuts", C.LEGUME, "g", "🥜", False),
    # --- spice -----------------------------------------------------------
    ("Salt", C.SPICE, "to taste", "🧂", True),
    ("Black pepper", C.SPICE, "tsp", "🧂", True),
    ("Turmeric", C.SPICE, "tsp", "🟡", True),
    ("Red chilli powder", C.SPICE, "tsp", "🌶️", True),
    ("Coriander powder", C.SPICE, "tsp", "🟤", True),
    ("Cumin seeds", C.SPICE, "tsp", "🟤", True),
    ("Mustard seeds", C.SPICE, "tsp", "🟤", True),
    ("Garam masala", C.SPICE, "tsp", "🟤", True),
    ("Asafoetida", C.SPICE, "pinch", "🟤", False),
    ("Fenugreek seeds", C.SPICE, "tsp", "🟤", False),
    ("Cardamom", C.SPICE, "piece", "🟢", False),
    ("Cinnamon", C.SPICE, "piece", "🪵", False),
    ("Cloves", C.SPICE, "piece", "🟤", False),
    ("Bay leaf", C.SPICE, "piece", "🍃", False),
    ("Star anise", C.SPICE, "piece", "⭐", False),
    ("Chaat masala", C.SPICE, "tsp", "🟤", False),
    ("Amchur", C.SPICE, "tsp", "🟤", False),
    ("Kasuri methi", C.SPICE, "tsp", "🍃", False),
    ("Paprika", C.SPICE, "tsp", "🌶️", False),
    ("Oregano", C.SPICE, "tsp", "🍃", False),
    ("Chilli flakes", C.SPICE, "tsp", "🌶️", False),
    # --- herb ------------------------------------------------------------
    ("Coriander leaves", C.HERB, "handful", "🌿", True),
    ("Mint", C.HERB, "handful", "🌿", False),
    ("Curry leaves", C.HERB, "handful", "🌿", True),
    ("Basil", C.HERB, "handful", "🌿", False),
    ("Parsley", C.HERB, "handful", "🌿", False),
    # --- sauce -----------------------------------------------------------
    ("Soy sauce", C.SAUCE, "tbsp", "🍶", False),
    ("Tomato ketchup", C.SAUCE, "tbsp", "🍅", False),
    ("Vinegar", C.SAUCE, "tbsp", "🍶", False),
    ("Chilli sauce", C.SAUCE, "tbsp", "🌶️", False),
    ("Mayonnaise", C.SAUCE, "tbsp", "🥣", False),
    ("Tamarind paste", C.SAUCE, "tbsp", "🟤", False),
    ("Coconut milk", C.SAUCE, "ml", "🥥", False),
    ("Tomato puree", C.SAUCE, "ml", "🍅", False),
    ("Ginger garlic paste", C.SAUCE, "tbsp", "🧄", True),
    # --- pantry ----------------------------------------------------------
    ("Cooking oil", C.PANTRY, "tbsp", "🫗", True),
    ("Olive oil", C.PANTRY, "tbsp", "🫗", False),
    ("Mustard oil", C.PANTRY, "tbsp", "🫗", False),
    ("Baking powder", C.PANTRY, "tsp", "🥄", False),
    ("Baking soda", C.PANTRY, "tsp", "🥄", False),
    ("Yeast", C.PANTRY, "tsp", "🥄", False),
    ("Cornflour", C.PANTRY, "tbsp", "🥄", False),
    ("Cashews", C.PANTRY, "g", "🥜", False),
    ("Almonds", C.PANTRY, "g", "🥜", False),
    ("Raisins", C.PANTRY, "g", "🍇", False),
    ("Stock cube", C.PANTRY, "piece", "🧊", False),
    # --- sweet -----------------------------------------------------------
    ("Sugar", C.SWEET, "tsp", "🍬", True),
    ("Jaggery", C.SWEET, "g", "🟤", False),
    ("Honey", C.SWEET, "tbsp", "🍯", False),
    ("Chocolate", C.SWEET, "g", "🍫", False),
    ("Condensed milk", C.SWEET, "ml", "🥛", False),
    ("Vanilla extract", C.SWEET, "tsp", "🍦", False),
    # --- drink -----------------------------------------------------------
    ("Tea leaves", C.DRINK, "tsp", "🍵", True),
    ("Coffee", C.DRINK, "tsp", "☕", False),
    ("Lime soda", C.DRINK, "ml", "🥤", False),
]


def suggestions(exclude_keys: set[str]) -> list[dict]:
    """The catalogue minus anything already on the shelf.

    `exclude_keys` is a set of `models.name_key()` values, so a shelf entry
    typed as "ONION" still hides the "Onion" chip.
    """
    out = []
    for name, category, unit, emoji, is_staple in CATALOGUE:
        if " ".join(name.lower().split()) in exclude_keys:
            continue
        out.append(
            {
                "name": name,
                "category": category,
                "default_unit": unit,
                "emoji": emoji,
                "is_staple": is_staple,
            }
        )
    return out


# Name key -> catalogue entry, so a hand-typed "turmeric" still picks up the
# category, unit and emoji instead of landing in "other" with no icon.
BY_KEY = {
    " ".join(name.lower().split()): {
        "category": category,
        "default_unit": unit,
        "emoji": emoji,
        "is_staple": is_staple,
    }
    for name, category, unit, emoji, is_staple in CATALOGUE
}
