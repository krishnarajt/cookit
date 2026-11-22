"""
A dish as a markdown file, and as a zip of one.

The output is meant to be legible as text and to survive a paste into anything —
Obsidian, a GitHub gist, a message. So: YAML front matter for the metadata that
a notes app can index, then plain headings.

Ingredient mentions in a step become **bold names**, which is the closest a
markdown file gets to the app's chips and reads correctly with no renderer at
all. `mention_service` owns that transformation, so exports can never disagree
with what the editor wrote.

**Photos** are the one thing markdown cannot hold itself, and there are two
honest answers rather than one:

* `dish_to_markdown()` links them by presigned URL. One file, renders the
  instant it is pasted anywhere, and the links die when the signature expires
  (`MARKDOWN_URL_TTL`, a week — the S3 v4 maximum).
* `dish_to_zip()` writes the same document with relative `images/…` paths and
  the bytes alongside it. Nothing to expire, drops into an Obsidian vault as a
  folder, and is the form to keep.

Both go through the same renderer, differing only in the `image_url` resolver
they hand it, so the two exports can never drift into disagreeing about what a
recipe says.
"""

import io
import logging
import zipfile
from datetime import datetime, timezone

from app.db.models import Dish, DishImage
from app.services import dish_service, mention_service, minio_service

logger = logging.getLogger(__name__)

# A presigned GET is capped at seven days by SigV4, so that is what the linked
# markdown gets. Anything meant to outlive that wants dish_to_zip().
MARKDOWN_URL_TTL = 7 * 24 * 3600


def _yaml_list(values: list[str]) -> str:
    return "[" + ", ".join(values) + "]"


def _amount(link) -> str:
    """"200 g", "2 cloves", "to taste", or nothing at all."""
    parts = []
    if link.quantity is not None:
        # 2.0 is "2"; 0.5 stays "0.5". A recipe that says "2.0 onions" reads
        # like a spreadsheet.
        quantity = link.quantity
        parts.append(
            str(int(quantity)) if float(quantity).is_integer() else f"{quantity:g}"
        )
    if link.unit:
        parts.append(link.unit)
    return " ".join(parts)


def _presigned(image: DishImage) -> str | None:
    """A week-long link to a photo, or None if storage can't be reached.

    None rather than raising: a recipe with a missing photo is still a recipe,
    and an export that fails because MinIO hiccuped is not.
    """
    return minio_service.generate_presigned_url(
        image.minio_object_key, MARKDOWN_URL_TTL
    )


def _image_markdown(images, url_for, alt: str, indent: str = "") -> list[str]:
    """A row of `![alt](url)` lines for one set of photos.

    Consecutive lines with no blank between them are one paragraph in every
    markdown renderer, so several photos of a step lay themselves out as a strip
    side by side rather than a tall column. `indent` is what keeps them inside
    an ordered-list item, and so under the step's number.
    """
    lines = []
    for position, image in enumerate(images):
        url = url_for(image)
        if not url:
            continue
        caption = (image.caption or "").strip()
        label = caption or (alt if len(images) == 1 else f"{alt} ({position + 1})")
        # Alt text carries the caption when there is one — it is the only place
        # a markdown image can put words, and a screen reader reads it.
        lines.append(f"{indent}![{_escape_alt(label)}]({_link(url)})")
    return lines


def _link(url: str) -> str:
    """A URL safe to sit inside `(…)`.

    Signed MinIO URLs are uuids and hex and have never needed this, but a
    destination with a space or a bracket in it silently truncates the link
    rather than failing, and the angle-bracket form costs nothing.
    """
    return f"<{url}>" if any(char in url for char in " ()<>") else url


def _escape_alt(text: str) -> str:
    """Alt text can't hold a bracket without closing the link early."""
    return (text or "").replace("[", "(").replace("]", ")").replace("\n", " ")


def dish_to_markdown(
    dish: Dish,
    *,
    partners: list[Dish] | None = None,
    image_url=_presigned,
) -> str:
    """The whole dish as one markdown document.

    `image_url` maps a photo row to something an `![](…)` can point at. The
    default signs a MinIO URL; `dish_to_zip` passes a resolver that returns a
    relative path instead. Returning None for a photo drops it and keeps the
    rest of the document.
    """
    meals = sorted(row.meal_type for row in dish.meal_types)
    total = (dish.prep_minutes or 0) + (dish.cook_minutes or 0)

    lines: list[str] = ["---", f'title: "{dish.name}"']
    if dish.cuisine:
        lines.append(f'cuisine: "{dish.cuisine}"')
    if meals:
        lines.append(f"meals: {_yaml_list(meals)}")
    if dish.servings:
        lines.append(f"servings: {dish.servings}")
    if dish.prep_minutes:
        lines.append(f"prep_minutes: {dish.prep_minutes}")
    if dish.cook_minutes:
        lines.append(f"cook_minutes: {dish.cook_minutes}")
    lines.append(f'difficulty: "{dish.difficulty}"')
    if dish.source_url:
        lines.append(f'source: "{dish.source_url}"')
    lines.append(f"times_cooked: {dish.times_cooked}")
    lines.append(f'exported: "{datetime.now(timezone.utc).isoformat(timespec="seconds")}"')
    lines += ["---", "", f"# {dish.name}", ""]

    cover, extras = cover_and_extras(dish)
    if cover:
        lines += _image_markdown([cover], image_url, dish.name)
        if lines[-1].startswith("!["):
            lines.append("")

    if dish.description:
        lines += [dish.description.strip(), ""]

    facts = []
    if meals:
        facts.append("**Good for** " + ", ".join(meals))
    if dish.servings:
        facts.append(f"**Serves** {dish.servings}")
    if total:
        facts.append(f"**Time** {total} min")
    if dish.cuisine:
        facts.append(f"**Cuisine** {dish.cuisine}")
    if facts:
        lines += [" · ".join(facts), ""]

    if dish.ingredients:
        lines += ["## Ingredients", ""]
        for link in dish.ingredients:
            amount = _amount(link)
            bits = [f"- {amount} {link.ingredient.name}".replace("-  ", "- ")]
            extras = []
            if link.note:
                extras.append(link.note)
            if link.is_optional:
                extras.append("optional")
            if extras:
                bits.append(f" ({', '.join(extras)})")
            lines.append("".join(bits))
        lines.append("")

    if dish.steps:
        lines += ["## Method", ""]
        for step in dish.steps:
            text = mention_service.mentions_to_markdown(step.text).strip()
            suffix = f" _({step.minutes} min)_" if step.minutes else ""
            lines.append(f"{step.step_index + 1}. {text}{suffix}")
            # Three spaces is the continuation indent for a single-digit
            # ordered list item, which is what keeps the photos inside the step
            # instead of ending the list and restarting the numbering at 1.
            photos = _image_markdown(
                step.images, image_url, f"Step {step.step_index + 1}", indent="   "
            )
            if photos:
                lines += [""] + photos + [""]
        if lines[-1] != "":
            lines.append("")

    if partners:
        lines += ["## Often had with", ""]
        lines += [f"- {other.name}" for other in partners]
        lines.append("")

    if dish.notes:
        lines += ["## Notes", "", dish.notes.strip(), ""]

    gallery = _image_markdown(extras, image_url, dish.name)
    if gallery:
        lines += ["## Photos", ""] + gallery + [""]

    lines += ["---", "", "Exported from Cookit."]
    return "\n".join(lines) + "\n"


def filename_for(dish: Dish, extension: str) -> str:
    """A safe, readable download name: "palak-paneer.md"."""
    slug = "".join(
        char if char.isalnum() else "-" for char in dish.name.strip().lower()
    )
    slug = "-".join(part for part in slug.split("-") if part) or "dish"
    return f"{slug[:80]}.{extension}"


def cover_and_extras(dish: Dish, limit: int = 3):
    """(cover image, other gallery images) for an export, capped.

    Gallery only: a step's photos belong beside their step and are fetched
    there, so including them here would print each one twice.

    The exporters fetch each of these from MinIO, so the cap is what keeps an
    export of a dish with thirty photos from taking half a minute.
    """
    gallery = dish_service.gallery_images(dish)
    cover = dish_service.cover_image(dish)
    extras = [image for image in gallery if image is not cover][: max(0, limit)]
    return cover, extras


def _extension(image: DishImage) -> str:
    """The file extension to write a photo out under."""
    if image.file_format:
        return image.file_format
    mime = (image.mime_type or "").rsplit("/", 1)[-1]
    return mime or "jpg"


def _bundle_paths(dish: Dish) -> dict[int, str]:
    """Where each photo goes inside the zip, keyed by image id.

    Named for what they are rather than by uuid — `images/step-03-2.jpg` tells
    you what you are looking at from the filename alone, which is the whole
    reason to prefer a folder over a wall of signed URLs.
    """
    paths: dict[int, str] = {}
    cover, extras = cover_and_extras(dish)
    if cover:
        paths[cover.id] = f"images/cover.{_extension(cover)}"
    for position, image in enumerate(extras, start=1):
        paths[image.id] = f"images/photo-{position:02d}.{_extension(image)}"
    for step in dish.steps:
        for position, image in enumerate(step.images, start=1):
            suffix = "" if len(step.images) == 1 else f"-{position}"
            paths[image.id] = (
                f"images/step-{step.step_index + 1:02d}{suffix}.{_extension(image)}"
            )
    return paths


def dish_to_zip(dish: Dish, *, partners: list[Dish] | None = None) -> bytes:
    """The dish as `recipe.md` plus an `images/` folder, as zip bytes.

    Photos are downloaded first and only the ones that arrive get a path, so the
    markdown is written knowing exactly which images exist. A photo storage
    can't produce is left out of both the folder and the document rather than
    becoming a broken link.
    """
    wanted = _bundle_paths(dish)
    fetched: dict[int, tuple[str, bytes]] = {}
    for image_id, path in wanted.items():
        data = minio_service.download_image(
            _image_by_id(dish, image_id).minio_object_key
        )
        if data:
            fetched[image_id] = (path, data)
        else:
            logger.warning(f"Zip export could not fetch image {image_id}")

    body = dish_to_markdown(
        dish,
        partners=partners,
        image_url=lambda image: fetched.get(image.id, (None,))[0],
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("recipe.md", body)
        for path, data in fetched.values():
            # Already-compressed bytes; deflating a JPEG twice costs CPU and
            # saves nothing.
            archive.writestr(path, data, compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()


def _image_by_id(dish: Dish, image_id: int) -> DishImage:
    for image in dish.images:
        if image.id == image_id:
            return image
    raise KeyError(image_id)
