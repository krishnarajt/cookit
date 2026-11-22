#!/usr/bin/env python3
"""
Fill a local Cookit with enough real data to see every screen.

Talks to the running API rather than the database, so it exercises the same
validation the app does — a seed that can't be created through the API is a seed
that hides a bug.

    python main.py                                   # in one terminal
    python scripts/dev_seed.py --base-url http://localhost:8020

Leaves two accounts, `saket` and `nadia` (password `cookit`), a shelf of about
forty ingredients, a dozen dishes with real recipes and @-mentions, pairings,
and a few weeks of cook history so the wheel's weighting has something to
weight.

Safe to re-run: existing accounts are signed into and existing dishes skipped.
"""

import argparse
import json
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PASSWORD = "cookit"

# Everything the seeded dishes mention, so the shelf is complete before any
# recipe is written. Names must match the catalogue's spelling to pick up its
# category, unit and emoji.
SHELF = """
Onion, Tomato, Potato, Garlic, Ginger, Green chilli, Carrot, Capsicum,
Cauliflower, Spinach, Peas, Mushroom, Lemon, Coconut, Egg, Chicken, Paneer,
Milk, Curd, Butter, Ghee, Cream, Cheese, Rice, Basmati rice, Wheat flour, Poha,
Bread, Pasta, Noodles, Toor dal, Moong dal, Chickpeas, Peanuts, Salt,
Black pepper, Turmeric, Red chilli powder, Coriander powder, Cumin seeds,
Mustard seeds, Garam masala, Asafoetida, Kasuri methi, Chilli flakes, Oregano,
Coriander leaves, Curry leaves, Mint, Soy sauce, Tomato ketchup,
Ginger garlic paste, Cooking oil, Olive oil, Sugar, Jaggery, Cashews,
Tea leaves, Semolina, Chaat masala
"""

# (name, cuisine, meals, prep, cook, serves, difficulty, description,
#  [(ingredient, qty, unit, note, optional)],
#  [(step text with {Ingredient} placeholders, minutes)])
#
# `{Ingredient}` in a step is turned into a real `@[name](uuid)` mention by the
# seeder, which is also the quickest way to see that the mention plumbing works.
DISHES = [
    (
        "Paneer Butter Masala", "North Indian", ["lunch", "dinner"], 15, 25, 3, "medium",
        "Restaurant-style, but weeknight-fast. The cream is optional and the kasuri methi is not.",
        [("Paneer", 250, "g", None, False), ("Onion", 2, "piece", "roughly chopped", False),
         ("Cashews", 12, "piece", "soaked", False), ("Butter", 2, "tbsp", None, False),
         ("Cream", 50, "ml", None, True)],
        [("Soak the {Cashews} in hot water for ten minutes, then blend with the {Tomato} into a smooth puree.", 10),
         ("Melt the {Butter}, fry the {Onion} until it stops smelling raw, then add the {Ginger garlic paste}.", 8),
         ("Pour in the puree with {Turmeric}, {Red chilli powder} and {Coriander powder}. Cook until it darkens and the oil separates.", 12),
         ("Slide in the {Paneer}, stir once, and finish with {Kasuri methi} crushed between your palms.", 4)],
    ),
    (
        "Dal Tadka", "North Indian", ["lunch", "dinner"], 10, 30, 4, "easy",
        "The one you can make half asleep. The tadka is the whole dish, so don't rush it.",
        [("Toor dal", 200, "g", "rinsed", False), ("Tomato", 1, "piece", None, False),
         ("Ghee", 2, "tbsp", None, False), ("Cumin seeds", 1, "tsp", None, False)],
        [("Pressure cook the {Toor dal} with {Turmeric}, {Salt} and the chopped {Tomato} for four whistles.", 20),
         ("Heat the {Ghee}, crackle the {Cumin seeds}, then the sliced {Garlic} until it just turns gold.", 4),
         ("Add {Asafoetida} and {Red chilli powder} off the heat so the chilli doesn't burn, then pour the whole thing over the dal.", 2),
         ("Cover for a minute before serving. Finish with {Coriander leaves}.", 1)],
    ),
    (
        "Poha", "Maharashtrian", ["breakfast"], 10, 10, 2, "easy",
        "Twenty minutes from asleep to fed.",
        [("Poha", 150, "g", "thick variety", False), ("Potato", 1, "piece", "diced small", False),
         ("Peanuts", 30, "g", None, False), ("Lemon", 1, "piece", None, False)],
        [("Rinse the {Poha} in a sieve until soft, then leave it to drain. Do not soak it.", 3),
         ("Fry the {Peanuts} in {Cooking oil} and set them aside. Crackle {Mustard seeds}, add {Curry leaves} and {Green chilli}.", 4),
         ("Cook the {Potato} and {Onion} until soft, add {Turmeric} and {Salt}.", 6),
         ("Fold in the poha gently, off the heat. Peanuts back in, {Lemon} squeezed over, {Coriander leaves} on top.", 2)],
    ),
    (
        "Masala Omelette", None, ["breakfast", "supper"], 5, 6, 1, "easy",
        "Two eggs and whatever is in the fridge door.",
        [("Egg", 2, "piece", None, False), ("Onion", 1, "piece", "finely chopped", False),
         ("Green chilli", 1, "piece", None, True)],
        [("Beat the {Egg} with {Salt}, {Black pepper} and {Turmeric} until properly frothy.", 2),
         ("Stir in the {Onion}, {Green chilli} and {Coriander leaves}.", 1),
         ("Pour into hot {Butter} on a low flame. Fold once when the top is nearly set.", 4)],
    ),
    (
        "Jeera Rice", "North Indian", ["lunch", "dinner"], 5, 20, 3, "easy",
        "The thing you make so the dal has somewhere to go.",
        [("Basmati rice", 250, "g", "soaked 20 minutes", False), ("Ghee", 1, "tbsp", None, False),
         ("Cumin seeds", 2, "tsp", None, False)],
        [("Crackle the {Cumin seeds} in {Ghee} until they darken a shade.", 2),
         ("Drain the {Basmati rice}, add it with twice its volume of water and {Salt}.", 3),
         ("Cover, lowest flame, fifteen minutes. Don't lift the lid. Fluff with a fork, not a spoon.", 15)],
    ),
    (
        "Aloo Gobi", "North Indian", ["lunch", "dinner"], 15, 25, 3, "easy",
        "Dry, not gravy. It should catch a little on the pan.",
        [("Potato", 2, "piece", "cubed", False), ("Cauliflower", 400, "g", "florets", False),
         ("Tomato", 1, "piece", None, True)],
        [("Fry {Cumin seeds} in {Cooking oil}, then the {Potato} on a high flame until the edges colour.", 8),
         ("Add the {Cauliflower}, {Turmeric}, {Red chilli powder} and {Coriander powder}.", 3),
         ("Cover on a low flame, stirring rarely, until a knife goes through the stems. Finish with {Garam masala} and {Coriander leaves}.", 14)],
    ),
    (
        "Chicken Curry", "Home style", ["lunch", "dinner"], 20, 40, 4, "medium",
        "Sunday. Make more than you need.",
        [("Chicken", 700, "g", "bone in", False), ("Onion", 3, "piece", "sliced thin", False),
         ("Curd", 100, "g", "whisked", False)],
        [("Marinate the {Chicken} in {Curd}, {Turmeric}, {Red chilli powder} and {Salt} for an hour.", 5),
         ("Brown the {Onion} in {Cooking oil} properly — this takes longer than you think and is the whole flavour.", 15),
         ("Add the {Ginger garlic paste}, then the marinated chicken. Seal it on a high flame.", 8),
         ("Splash of water, cover, low flame until the meat pulls off the bone. {Garam masala} at the end.", 25)],
    ),
    (
        "Upma", "South Indian", ["breakfast"], 10, 15, 2, "easy",
        "Semolina, and restraint with the water.",
        [("Semolina", 150, "g", "dry roasted", False), ("Carrot", 1, "piece", "diced", True),
         ("Peas", 50, "g", None, True)],
        [("Dry roast the {Semolina} until it smells nutty and set it aside.", 5),
         ("Crackle {Mustard seeds} in {Cooking oil}, add {Curry leaves}, {Green chilli} and {Onion}.", 4),
         ("Add {Carrot}, {Peas} and three times the semolina's volume of water. Salt it now.", 3),
         ("Rain the semolina in with one hand while stirring with the other. Cover, lowest flame, five minutes.", 6)],
    ),
    (
        "Chole", "Punjabi", ["lunch", "dinner"], 15, 35, 4, "medium",
        "Dark, tangy, and better the next day.",
        [("Chickpeas", 250, "g", "soaked overnight", False), ("Tomato", 3, "piece", "pureed", False),
         ("Tea leaves", 1, "tsp", "in a muslin bag", True)],
        [("Pressure cook the {Chickpeas} with {Salt} and the {Tea leaves} bag — that's what makes them dark.", 25),
         ("Fry {Onion} until deep brown, add {Ginger garlic paste}, then the {Tomato} puree.", 12),
         ("In go {Coriander powder}, {Red chilli powder}, {Turmeric} and {Chaat masala}. Cook until thick.", 6),
         ("Add the chickpeas with their water. Simmer twenty minutes, mashing a few against the pan to thicken it.", 20)],
    ),
    (
        "Garlic Noodles", "Indo-Chinese", ["dinner", "supper"], 10, 12, 2, "easy",
        "Loud garlic, hot pan, no thinking.",
        [("Noodles", 200, "g", None, False), ("Garlic", 8, "clove", "sliced, not crushed", False),
         ("Capsicum", 1, "piece", "julienned", False)],
        [("Boil the {Noodles} one minute short of the packet, rinse cold, toss in a little {Cooking oil}.", 6),
         ("Hottest pan you have. {Garlic} in {Olive oil} for thirty seconds only.", 2),
         ("{Capsicum} and {Carrot} in, keep everything moving. They should stay loud.", 3),
         ("Noodles in with {Soy sauce}, {Chilli flakes} and {Black pepper}. Toss, don't stir.", 3)],
    ),
    (
        "Tomato Soup", None, ["supper"], 10, 25, 2, "easy",
        "For the evenings when dinner is a mistake.",
        [("Tomato", 6, "piece", "halved", False), ("Butter", 1, "tbsp", None, False),
         ("Cream", 30, "ml", None, True)],
        [("Roast the {Tomato} with {Garlic}, {Olive oil} and {Salt} until the edges blacken.", 20),
         ("Blend smooth with a little water, then pass it through a sieve. Worth the extra pan.", 5),
         ("Back on the heat with {Butter}, {Black pepper} and a pinch of {Sugar}. {Cream} if the day was bad.", 5)],
    ),
    (
        "Butter Naan", "North Indian", ["lunch", "dinner"], 90, 10, 4, "hard",
        "Worth it once. Twice if the dal is good.",
        [("Wheat flour", 300, "g", None, False), ("Curd", 80, "g", None, False),
         ("Butter", 3, "tbsp", "melted, for brushing", False)],
        [("Knead the {Wheat flour} with {Curd}, {Milk}, {Sugar} and {Salt} into a soft, slightly sticky dough.", 12),
         ("Cover and leave it somewhere warm for an hour and a half.", 90),
         ("Roll thin, one side wetted with water. Slap the wet side onto a screaming hot tawa and invert it over the flame.", 8),
         ("Brush with {Butter} the second it comes off. Eat one standing at the stove; that is the cook's due.", 2)],
    ),
]

# Which dishes go with which. Recorded once — the pairing is mutual.
PAIRINGS = [
    ("Dal Tadka", "Jeera Rice"),
    ("Dal Tadka", "Butter Naan"),
    ("Paneer Butter Masala", "Butter Naan"),
    ("Paneer Butter Masala", "Jeera Rice"),
    ("Aloo Gobi", "Dal Tadka"),
    ("Chole", "Butter Naan"),
    ("Chicken Curry", "Jeera Rice"),
    ("Poha", "Masala Omelette"),
    ("Tomato Soup", "Garlic Noodles"),
]

# Dish -> how many days ago it was last cooked, roughly. Spread out so the
# wheel's staleness weighting has a real range to work with, and two dishes are
# left uncooked entirely because that is the most interesting case.
HISTORY = {
    "Dal Tadka": [1, 5, 9, 14, 21, 30],
    "Jeera Rice": [1, 5, 9, 21],
    "Poha": [2, 6, 13],
    "Masala Omelette": [3, 4, 11, 19],
    "Paneer Butter Masala": [7, 26],
    "Aloo Gobi": [12],
    "Chicken Curry": [17],
    "Upma": [24],
    "Garlic Noodles": [9, 33],
    "Chole": [40],
}


class Client:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token = None

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request) as response:
                payload = response.read()
                return response.status, (json.loads(payload) if payload else None)
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()[:300]
        except urllib.error.URLError as error:
            print(f"Cannot reach {self.base}: {error.reason}", file=sys.stderr)
            sys.exit(1)

    def sign_in(self, username, display_name):
        """Register, or log in if the account is already there."""
        status, body = self.call(
            "POST",
            "/api/auth/register",
            {"username": username, "password": PASSWORD, "display_name": display_name},
        )
        if status == 409:
            status, body = self.call(
                "POST", "/api/auth/login", {"username": username, "password": PASSWORD}
            )
        if status not in (200, 201):
            print(f"Could not sign in as {username}: {status} {body}", file=sys.stderr)
            sys.exit(1)
        self.token = body["access_token"]
        return body["user"]


def seed(client: Client) -> None:
    # --- shelf ------------------------------------------------------------
    status, result = client.call("POST", "/api/ingredients/bulk", {"text": SHELF})
    if status not in (200, 201):
        print(f"Shelf failed: {status} {result}", file=sys.stderr)
        sys.exit(1)
    print(
        f"  shelf: {len(result['created'])} added, "
        f"{len(result['already_there'])} already there"
    )

    _, shelf = client.call("GET", "/api/ingredients")
    by_name = {item["name"]: item for item in shelf}

    def with_mentions(text: str) -> str:
        """`{Onion}` in a seed step becomes a real `@[Onion](uuid)` mention.

        A regex rather than `str.format`, because ingredient names are prose
        ("Ginger garlic paste") and a format placeholder that doesn't resolve
        raises rather than degrading. Anything not on the shelf falls back to
        the plain word.
        """

        def swap(match):
            item = by_name.get(match.group(1))
            if not item:
                return match.group(1)
            return f"@[{item['name']}]({item['ingredient_uuid']})"

        return re.sub(r"\{([^{}]+)\}", swap, text)

    # --- dishes -----------------------------------------------------------
    dish_uuids = {}
    for (
        name, cuisine, meals, prep, cook, serves, difficulty, description,
        ingredients, steps,
    ) in DISHES:
        status, dish = client.call(
            "POST",
            "/api/dishes",
            {
                "name": name, "description": description, "cuisine": cuisine,
                "prep_minutes": prep, "cook_minutes": cook, "servings": serves,
                "difficulty": difficulty, "meal_types": meals,
            },
        )
        if status == 409:
            _, existing = client.call("GET", f"/api/dishes?q={urllib.parse.quote(name)}")
            match = next((d for d in existing if d["name"] == name), None)
            if match:
                dish_uuids[name] = match["dish_uuid"]
                print(f"  dish: {name} (already there)")
                continue
        if status not in (200, 201):
            print(f"  dish {name} failed: {status} {dish}", file=sys.stderr)
            continue

        uuid = dish["dish_uuid"]
        dish_uuids[name] = uuid

        client.call(
            "PUT",
            f"/api/dishes/{uuid}/ingredients",
            {
                "ingredients": [
                    {
                        "ingredient_uuid": by_name[ing]["ingredient_uuid"],
                        "quantity": quantity, "unit": unit,
                        "note": note, "is_optional": optional,
                    }
                    for ing, quantity, unit, note, optional in ingredients
                    if ing in by_name
                ]
            },
        )
        client.call(
            "PUT",
            f"/api/dishes/{uuid}/steps",
            {
                "steps": [
                    {"text": with_mentions(text), "minutes": minutes}
                    for text, minutes in steps
                ]
            },
        )
        print(f"  dish: {name} ({len(ingredients)} listed, {len(steps)} steps)")

    # --- pairings ---------------------------------------------------------
    paired = 0
    for left, right in PAIRINGS:
        if left in dish_uuids and right in dish_uuids:
            status, _ = client.call(
                "POST",
                f"/api/dishes/{dish_uuids[left]}/pairings",
                {"dish_uuid": dish_uuids[right]},
            )
            paired += status in (200, 201)
    print(f"  pairings: {paired}")

    # --- history ----------------------------------------------------------
    # Cook events are logged through the API, which stamps them with "now", so
    # the backdating is done by writing the dates straight afterwards. The
    # endpoint has no cooked_at parameter on purpose — nothing in the real app
    # ever needs to claim you cooked something last Tuesday.
    cooks = 0
    for name, days_ago_list in HISTORY.items():
        uuid = dish_uuids.get(name)
        if not uuid:
            continue
        for _days_ago in days_ago_list:
            status, _ = client.call(
                "POST",
                f"/api/dishes/{uuid}/cook",
                {
                    "meal_type": random.choice(["breakfast", "lunch", "dinner", "supper"]),
                    "source": random.choice(["manual", "randomizer"]),
                },
            )
            cooks += status in (200, 201)
    print(f"  cook history: {cooks} events")


def backdate(db_path: str) -> None:
    """Spread the seeded cook events over the last six weeks.

    Local-development convenience only, and the one thing here that touches the
    database directly: the API has no way to say "I cooked this three weeks
    ago", because the real app never needs one.
    """
    import sqlite3

    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()
    cursor.execute(
        "SELECT c.id, d.name FROM cook_events c JOIN dishes d ON d.id = c.dish_id"
        " ORDER BY c.id"
    )
    rows = cursor.fetchall()

    offsets: dict[str, list[int]] = {}
    for event_id, dish_name in rows:
        queue = offsets.setdefault(dish_name, list(HISTORY.get(dish_name, [])))
        days_ago = queue.pop(0) if queue else random.randint(1, 45)
        when = datetime.now(timezone.utc) - timedelta(
            days=days_ago, hours=random.randint(0, 12)
        )
        cursor.execute(
            "UPDATE cook_events SET cooked_at = ? WHERE id = ?",
            (when.strftime("%Y-%m-%d %H:%M:%S"), event_id),
        )

    # The cached counters on `dishes` are derived, so rebuild them from what the
    # events now say rather than leaving the two disagreeing.
    cursor.execute(
        """
        UPDATE dishes SET
          times_cooked = (SELECT COUNT(*) FROM cook_events WHERE dish_id = dishes.id),
          last_cooked_at = (SELECT MAX(cooked_at) FROM cook_events WHERE dish_id = dishes.id)
        """
    )
    connection.commit()
    connection.close()
    print(f"  backdated {len(rows)} cook events and rebuilt the dish counters")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a local Cookit")
    parser.add_argument("--base-url", default="http://localhost:8020")
    parser.add_argument(
        "--backdate",
        metavar="SQLITE_PATH",
        help="After seeding, spread the cook history over six weeks "
        "(local SQLite only)",
    )
    args = parser.parse_args()

    random.seed(11)

    for username, display_name in (("saket", "Saket"), ("nadia", "Nadia")):
        client = Client(args.base_url)
        user = client.sign_in(username, display_name)
        print(f"\n{display_name} (@{user['username']})")
        # One full cookbook is enough to see every screen; the second account
        # exists to prove nothing leaks between them, so it stays nearly empty.
        if username == "saket":
            seed(client)
        else:
            client.call("POST", "/api/ingredients/bulk", {"text": "Egg, Bread, Butter"})
            client.call(
                "POST",
                "/api/dishes",
                {"name": "Fried Egg on Toast", "meal_types": ["breakfast"]},
            )
            print("  a shelf of three and one dish, to prove accounts are separate")

    if args.backdate:
        print()
        backdate(args.backdate)
    else:
        print(
            "\nEvery cook event is stamped now. Pass --backdate <sqlite path> to"
            "\nspread them over six weeks, which is what gives the wheel's"
            "\nstaleness weighting a range to work with."
        )

    print(f"\nDone. Sign in at the UI as `saket` / `{PASSWORD}`.")


if __name__ == "__main__":
    main()
