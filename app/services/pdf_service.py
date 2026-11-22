"""
A dish as a PDF.

reportlab's platypus rather than raw canvas calls: a recipe is flowing content —
a description of unknown length, an ingredient table, numbered steps that wrap —
and platypus does the pagination. Nothing here places a coordinate by hand.

The result is meant to be printed and stuck on a fridge, so it is deliberately
plain: one accent colour, generous leading, ingredients in a two-column table,
steps numbered large enough to find your place again after looking away.

Photos are fetched from MinIO and embedded. Storage being unreachable drops the
images and keeps the recipe — a PDF without the photo is useful, a 502 is not.

A step's own photos sit in a fixed column to the right of its text, so the
number and the first word of every instruction stay on one left edge all the way
down the page. That is the column you follow with a finger while cooking, and
alternating the photos left and right would move it on every step.
"""

import io
import logging
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.db.models import Dish
from app.services import export_service, mention_service, minio_service

logger = logging.getLogger(__name__)

# The app's paprika and saffron, as print-safe values.
BRAND = colors.HexColor("#b83d0b")
ACCENT = colors.HexColor("#c88a0a")
INK = colors.HexColor("#1c1512")
INK_SOFT = colors.HexColor("#5c4a40")
RULE = colors.HexColor("#e6d7c3")

PAGE_MARGIN = 18 * mm
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN

# Cap on an embedded photo's height. Without it a portrait phone photo takes a
# whole page on its own and pushes the method to page three.
MAX_IMAGE_HEIGHT = 78 * mm

# The column a step's photos live in, to the right of its text. Wide enough to
# read what is in the pan, narrow enough to leave the instruction a full line of
# prose rather than three words a row.
STEP_IMAGE_WIDTH = 46 * mm
STEP_IMAGE_HEIGHT = 34 * mm
# Past this many photos on one step, the block is taller than it is worth
# holding together and reportlab is left to break it across pages.
KEEP_TOGETHER_LIMIT = 2


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CookitTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=30,
            alignment=TA_LEFT,
            textColor=INK,
            spaceAfter=2,
        ),
        "kicker": ParagraphStyle(
            "CookitKicker",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=BRAND,
            spaceAfter=6,
        ),
        "meta": ParagraphStyle(
            "CookitMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=INK_SOFT,
        ),
        "body": ParagraphStyle(
            "CookitBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15.5,
            textColor=INK,
        ),
        "heading": ParagraphStyle(
            "CookitHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=BRAND,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "step": ParagraphStyle(
            "CookitStep",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=16,
            textColor=INK,
        ),
        "stepNumber": ParagraphStyle(
            "CookitStepNumber",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=ACCENT,
        ),
        "footer": ParagraphStyle(
            "CookitFooter",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=INK_SOFT,
        ),
    }


def _escape(text: str) -> str:
    """Plain text into reportlab's mini-markup.

    Ampersands and angle brackets are markup to platypus, and a recipe that says
    "salt & pepper" would otherwise fail to render at all.
    """
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _step_markup(text: str) -> str:
    """A step with its mentioned ingredients in bold.

    Escaping happens on the plain segments only, so the <b> tags this adds are
    real markup and anything the person typed is not.
    """
    out: list[str] = []
    cursor = 0
    for match in mention_service.MENTION_RE.finditer(text or ""):
        out.append(_escape(text[cursor : match.start()]))
        out.append(f"<b>{_escape(match.group(1))}</b>")
        cursor = match.end()
    out.append(_escape(text[cursor:]))
    return "".join(out)


def _image_flowable(
    object_key: str, max_width: float, max_height: float = MAX_IMAGE_HEIGHT
):
    """A photo from MinIO, scaled to fit. None if it can't be fetched or read."""
    data = minio_service.download_image(object_key)
    if not data:
        logger.warning(f"PDF export could not fetch {object_key}")
        return None
    try:
        reader = RLImage(io.BytesIO(data))
        native_width, native_height = reader.imageWidth, reader.imageHeight
        if not native_width or not native_height:
            return None
        scale = min(max_width / native_width, max_height / native_height)
        return RLImage(
            io.BytesIO(data),
            width=native_width * scale,
            height=native_height * scale,
        )
    except Exception as exc:
        # A corrupt or exotic upload must not take the whole export down.
        logger.warning(f"PDF export could not read {object_key}: {exc}")
        return None


def _facts(dish: Dish) -> str:
    meals = sorted(row.meal_type for row in dish.meal_types)
    total = (dish.prep_minutes or 0) + (dish.cook_minutes or 0)
    bits = []
    if meals:
        bits.append(", ".join(meal.title() for meal in meals))
    if dish.servings:
        bits.append(f"Serves {dish.servings}")
    if total:
        if dish.prep_minutes and dish.cook_minutes:
            bits.append(
                f"{total} min ({dish.prep_minutes} prep + {dish.cook_minutes} cook)"
            )
        else:
            bits.append(f"{total} min")
    if dish.cuisine:
        bits.append(dish.cuisine)
    bits.append(dish.difficulty.title())
    return _escape("   ·   ".join(bits))


def _ingredient_table(dish: Dish, styles: dict) -> Table:
    rows = []
    for link in dish.ingredients:
        amount = export_service._amount(link)
        name = link.ingredient.name
        extras = []
        if link.note:
            extras.append(link.note)
        if link.is_optional:
            extras.append("optional")
        if extras:
            name = f"{name} ({', '.join(extras)})"
        rows.append(
            [
                Paragraph(f"<b>{_escape(amount) or '—'}</b>", styles["body"]),
                Paragraph(_escape(name), styles["body"]),
            ]
        )

    table = Table(rows, colWidths=[32 * mm, CONTENT_WIDTH - 32 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                # A hairline between rows, so a long ingredient list stays
                # readable without boxing every cell.
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
            ]
        )
    )
    return table


def _step_photos(step, styles: dict) -> list:
    """A step's photos, stacked, ready to go in the right-hand cell.

    Stacked rather than laid side by side: two photos across a 46mm column are
    23mm each, which is a thumbnail of a pan rather than a picture of one. A
    caption goes under its own photo, so several stay told apart.
    """
    cell: list = []
    for image in step.images:
        flowable = _image_flowable(
            image.minio_object_key, STEP_IMAGE_WIDTH, STEP_IMAGE_HEIGHT
        )
        if flowable is None:
            continue
        if cell:
            cell.append(Spacer(1, 4))
        cell.append(flowable)
        if image.caption:
            cell.append(Spacer(1, 2))
            cell.append(Paragraph(_escape(image.caption), styles["footer"]))
    return cell


def _step_rows(dish: Dish, styles: dict) -> list:
    flowables = []
    for step in dish.steps:
        suffix = (
            f' <font color="#5c4a40" size="9">({step.minutes} min)</font>'
            if step.minutes
            else ""
        )
        number = Paragraph(f"{step.step_index + 1}", styles["stepNumber"])
        text = Paragraph(_step_markup(step.text) + suffix, styles["step"])

        photos = _step_photos(step, styles)
        if photos:
            # Three columns: number, instruction, photos. The photo column is a
            # fixed width so every step's text starts and ends in the same
            # place, whether or not that step has a picture.
            cells = [[number, text, photos]]
            widths = [
                10 * mm,
                CONTENT_WIDTH - 10 * mm - STEP_IMAGE_WIDTH - 4 * mm,
                STEP_IMAGE_WIDTH + 4 * mm,
            ]
        else:
            cells = [[number, text]]
            widths = [10 * mm, CONTENT_WIDTH - 10 * mm]

        row = Table(cells, colWidths=widths, hAlign="LEFT")
        row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (0, -1), 0),
                    ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        # A step must not be split across a page break mid-sentence — but a step
        # carrying several photos can be taller than a page, and an unbreakable
        # block that tall is one reportlab drops on the floor.
        flowables.append(
            KeepTogether(row)
            if len(step.images) <= KEEP_TOGETHER_LIMIT
            else row
        )
    return flowables


def _footer(canvas, doc, dish_name: str):
    """Dish name left, page number right, on every page."""
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(PAGE_MARGIN, 13 * mm, A4[0] - PAGE_MARGIN, 13 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(INK_SOFT)
    canvas.drawString(PAGE_MARGIN, 9 * mm, f"{dish_name} · Cookit")
    canvas.drawRightString(A4[0] - PAGE_MARGIN, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def dish_to_pdf(dish: Dish, *, partners: list[Dish] | None = None) -> bytes:
    """The whole dish as a printable PDF, returned as bytes."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=22 * mm,
        title=dish.name,
        author="Cookit",
        subject="Recipe",
    )

    story: list = []
    story.append(Paragraph("COOKIT RECIPE", styles["kicker"]))
    story.append(Paragraph(_escape(dish.name), styles["title"]))
    story.append(Spacer(1, 3))
    story.append(Paragraph(_facts(dish), styles["meta"]))
    story.append(Spacer(1, 10))

    cover, extras = export_service.cover_and_extras(dish)
    if cover:
        image = _image_flowable(cover.minio_object_key, CONTENT_WIDTH)
        if image:
            story.append(image)
            if cover.caption:
                story.append(Spacer(1, 3))
                story.append(Paragraph(_escape(cover.caption), styles["footer"]))
            story.append(Spacer(1, 10))

    if dish.description:
        story.append(Paragraph(_escape(dish.description.strip()), styles["body"]))
        story.append(Spacer(1, 4))

    if dish.ingredients:
        story.append(Paragraph("INGREDIENTS", styles["heading"]))
        story.append(_ingredient_table(dish, styles))

    if dish.steps:
        story.append(Paragraph("METHOD", styles["heading"]))
        story.extend(_step_rows(dish, styles))

    if partners:
        story.append(Paragraph("OFTEN HAD WITH", styles["heading"]))
        story.append(
            Paragraph(
                _escape(", ".join(other.name for other in partners)), styles["body"]
            )
        )

    if dish.notes:
        story.append(Paragraph("NOTES", styles["heading"]))
        story.append(Paragraph(_escape(dish.notes.strip()), styles["body"]))

    if extras:
        gallery = [
            flowable
            for flowable in (
                _image_flowable(image.minio_object_key, CONTENT_WIDTH)
                for image in extras
            )
            if flowable is not None
        ]
        if gallery:
            # The gallery goes on its own page: it is the least useful part
            # while actually cooking, and it would otherwise shove the method
            # onto page two.
            story.append(PageBreak())
            story.append(Paragraph("MORE PHOTOS", styles["heading"]))
            for flowable in gallery:
                story.append(flowable)
                story.append(Spacer(1, 8))

    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            f"Exported {datetime.now(timezone.utc).strftime('%d %b %Y')}"
            f" · cooked {dish.times_cooked} time(s)",
            styles["footer"],
        )
    )

    footer = lambda canvas, document: _footer(canvas, document, dish.name)  # noqa: E731
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
