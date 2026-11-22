import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import User
from app.services import export_service, import_service


COOKIT_STYLE = """---
title: "Tomato Pasta"
cuisine: "Italian"
meals: [lunch, dinner]
servings: 2
prep_minutes: 5
cook_minutes: 15
difficulty: "medium"
source: "https://example.test/pasta"
---

# Tomato Pasta

Fast and bright.

**Good for** lunch, dinner · **Serves** 2

## Ingredients

- 200 g tomatoes
- 2 cloves garlic (minced, optional)
- salt

## Method

1. Chop the **tomatoes**. _(5 min)_
2. [ ] Fry the garlic.

## Often had with

- Bread

## Notes

Best eaten immediately.
"""


class MarkdownParserTests(unittest.TestCase):
    def test_cookit_export_shape(self):
        recipe = import_service.parse_markdown(COOKIT_STYLE, "tomato-pasta.md")

        self.assertEqual(recipe.name, "Tomato Pasta")
        self.assertEqual(recipe.description, "Fast and bright.")
        self.assertEqual(recipe.meal_types, ["lunch", "dinner"])
        self.assertEqual(recipe.prep_minutes, 5)
        self.assertEqual(recipe.cook_minutes, 15)
        self.assertEqual(recipe.notes, "Best eaten immediately.")
        self.assertEqual(len(recipe.ingredients), 3)
        self.assertEqual(recipe.ingredients[0].quantity, 200)
        self.assertEqual(recipe.ingredients[0].unit, "g")
        self.assertEqual(recipe.ingredients[1].name, "garlic")
        self.assertEqual(recipe.ingredients[1].note, "minced")
        self.assertTrue(recipe.ingredients[1].is_optional)
        self.assertEqual(
            [step.text for step in recipe.steps],
            ["Chop the tomatoes.", "Fry the garlic."],
        )
        self.assertEqual(recipe.steps[0].minutes, 5)

    def test_bare_lists_are_steps(self):
        recipe = import_service.parse_markdown(
            """# Quick supper

- [ ] Chop the onion
* Fry until golden
3) Serve hot
a. Wash up
""",
            "quick-supper.md",
        )

        self.assertEqual(
            [step.text for step in recipe.steps],
            ["Chop the onion", "Fry until golden", "Serve hot", "Wash up"],
        )
        self.assertEqual(recipe.ingredients, [])

    def test_ingredient_list_is_not_used_as_fallback_steps(self):
        recipe = import_service.parse_markdown(
            """# Toast

Ingredients:
- Bread
- Butter

Things to do:
- Toast the bread
- Add butter
""",
            "toast.md",
        )

        self.assertEqual([item.name for item in recipe.ingredients], ["Bread", "Butter"])
        self.assertEqual(
            [step.text for step in recipe.steps], ["Toast the bread", "Add butter"]
        )

    def test_recipe_heading_ignores_lists_in_other_sections(self):
        recipe = import_service.parse_markdown(
            """Pancakes
========

## Ingredients
- 1 cup flour

## Cooking instructions
1. Mix the batter
   until smooth.
2. Cook

## Shopping reminders
- Maple syrup
""",
            "pancakes.md",
        )

        self.assertEqual(recipe.name, "Pancakes")
        self.assertEqual(
            [step.text for step in recipe.steps], ["Mix the batter until smooth.", "Cook"]
        )

    def test_document_without_list_is_rejected(self):
        with self.assertRaisesRegex(import_service.MarkdownImportError, "No recipe steps"):
            import_service.parse_markdown("# Soup\n\nSimmer it.", "soup.md")


class MarkdownPersistenceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(
            username="cook",
            display_name="Cook",
            password_hash="not-used",
        )
        self.other = User(
            username="other",
            display_name="Other",
            password_hash="not-used",
        )
        self.db.add_all([self.user, self.other])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_import_creates_dish_and_reuses_shelf_ingredients(self):
        dish = import_service.import_markdown(
            self.db, self.user, COOKIT_STYLE, "tomato-pasta.md"
        )

        self.assertEqual(dish.name, "Tomato Pasta")
        self.assertEqual(len(dish.ingredients), 3)
        self.assertEqual(len(dish.steps), 2)
        self.assertEqual(len(self.user.ingredients), 3)

        exported = export_service.dish_to_markdown(dish, image_url=lambda _image: None)
        restored = import_service.import_markdown(
            self.db, self.other, exported, "tomato-pasta.md"
        )
        self.assertEqual(
            [link.ingredient.name for link in restored.ingredients],
            ["tomatoes", "garlic", "salt"],
        )
        self.assertEqual([step.text for step in restored.steps], [step.text for step in dish.steps])
        self.assertEqual(restored.steps[0].minutes, 5)
        self.assertEqual(restored.notes, "Best eaten immediately.")

    def test_duplicate_title_does_not_add_more_ingredients(self):
        import_service.import_markdown(self.db, self.user, COOKIT_STYLE, "one.md")
        before = len(self.user.ingredients)

        with self.assertRaises(import_service.dish_service.AlreadyExists):
            import_service.import_markdown(self.db, self.user, COOKIT_STYLE, "two.md")

        self.assertEqual(len(self.user.ingredients), before)


if __name__ == "__main__":
    unittest.main()
