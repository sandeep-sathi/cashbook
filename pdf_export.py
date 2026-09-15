"""Professional PDF export of a book's ledger (reportlab; pure-Python, no
system binary dependency, so it installs cleanly on PythonAnywhere).

Mirrors the same filtered transaction set as the CSV export, rendered as a
formatted statement instead of raw rows. User-controlled text (description,
category, party names) is always passed through `_escape` before being
placed in a Paragraph, since reportlab's Paragraph markup is a small XML
dialect and unescaped `<`/`&` in a category name would otherwise break
rendering or be misread as markup.
"""

from io import BytesIO
from xml.sax.saxutils import escape as _escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import interest

GREEN = colors.HexColor("#0a8f5b")
GREEN_DARK = colors.HexColor("#076b45")
RED = colors.HexColor("#b83232")
MUTED = colors.HexColor("#6b7280")
ROW_ALT = colors.HexColor("#f4f6f5")
BORDER = colors.HexColor("#d8dcdf")
TEXT = colors.HexColor("#1a1a1a")

PAGE_SIZE = landscape(A4)
MARGIN = 16 * mm

COL_WIDTHS = [22, 14, 30, 30, 22, 96, 24, 27]  # mm; sums to usable width
COLS = ["Date", "Time", "Category", "Party", "Mode", "Description", "Amount", "Balance"]


class _NumberedCanvas(pdfcanvas.Canvas):
    """Buffers pages so the footer can show 'Page X of Y' (reportlab's
    standard two-pass recipe for a page total, since it isn't known until
    every flowable has been laid out)."""

    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_footer(self, total_pages):
        width, _ = PAGE_SIZE
        self.setFont("Helvetica", 8)
        self.setFillColor(MUTED)
        self.drawString(MARGIN, 10 * mm, "Cashbook")
        self.drawRightString(width - MARGIN, 10 * mm, f"Page {self.getPageNumber()} of {total_pages}")


def _describe_period(filters):
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from and date_to:
        return f"Period: {date_from} to {date_to}"
    if date_from:
        return f"Period: from {date_from}"
    if date_to:
        return f"Period: through {date_to}"
    return "Period: all transactions"


def _describe_extra_filters(filters, category_lookup, party_lookup, payment_mode_labels):
    parts = []
    if filters.get("category_id"):
        name = category_lookup.get(int(filters["category_id"]))
        if name:
            parts.append(f"Category: {name}")
    if filters.get("party_id"):
        name = party_lookup.get(int(filters["party_id"]))
        if name:
            parts.append(f"Party: {name}")
    if filters.get("payment_mode"):
        parts.append(f"Payment Mode: {payment_mode_labels.get(filters['payment_mode'], filters['payment_mode'])}")
    if filters.get("q"):
        parts.append(f'Search: "{filters["q"]}"')
    return " · ".join(_escape(p) for p in parts)


def generate_ledger_pdf(
    book, rows, filters, categories, parties, payment_mode_labels,
    total_in, total_out, net, generated_at,
):
    """Returns PDF bytes for the given (already-filtered) transaction rows."""
    category_lookup = {c["id"]: c["name"] for c in categories}
    party_lookup = {p["id"]: p["name"] for p in parties}

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"{book['name']} - Cashbook Statement",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CBTitle", parent=styles["Title"], textColor=GREEN_DARK,
        fontSize=20, leading=24, alignment=0, spaceAfter=0,
    )
    subtitle_style = ParagraphStyle(
        "CBSubtitle", parent=styles["Normal"], textColor=MUTED, fontSize=10.5,
    )
    meta_style = ParagraphStyle(
        "CBMeta", parent=styles["Normal"], textColor=MUTED, fontSize=8.5, leading=12,
    )
    cell_style = ParagraphStyle("CBCell", parent=styles["Normal"], fontSize=8.5, leading=11)
    stat_label_style = ParagraphStyle(
        "CBStatLabel", parent=styles["Normal"], textColor=colors.white,
        fontSize=8, alignment=1, spaceAfter=2,
    )
    stat_value_style = ParagraphStyle(
        "CBStatValue", parent=styles["Normal"], textColor=colors.white,
        fontSize=15, alignment=1, fontName="Helvetica-Bold",
    )

    story = []

    story.append(Paragraph(_escape(book["name"]), title_style))
    story.append(Paragraph("Transaction Statement", subtitle_style))
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph(_describe_period(filters), meta_style))
    extra = _describe_extra_filters(filters, category_lookup, party_lookup, payment_mode_labels)
    if extra:
        story.append(Paragraph(extra, meta_style))
    story.append(Paragraph(f"Generated on {_escape(generated_at)}", meta_style))
    story.append(Spacer(1, 6 * mm))

    usable_width = PAGE_SIZE[0] - 2 * MARGIN
    stat_width = usable_width / 3
    summary_table = Table(
        [
            [Paragraph("CASH IN", stat_label_style), Paragraph("CASH OUT", stat_label_style), Paragraph("NET BALANCE", stat_label_style)],
            [
                Paragraph(interest.format_money_cents(total_in), stat_value_style),
                Paragraph(interest.format_money_cents(total_out), stat_value_style),
                Paragraph(interest.format_money_cents(net), stat_value_style),
            ],
        ],
        colWidths=[stat_width] * 3,
    )
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), GREEN),
        ("BACKGROUND", (1, 0), (1, -1), RED),
        ("BACKGROUND", (2, 0), (2, -1), GREEN_DARK),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 6 * mm))

    if not rows:
        story.append(Paragraph("No transactions match.", meta_style))
    else:
        data = [COLS]
        row_styles = []
        for i, r in enumerate(rows, start=1):
            is_in = r["type"] == "in"
            sign = "+" if is_in else "−"
            amount = f"{sign}{interest.format_money_cents(r['amount_cents'])}"
            balance = interest.format_money_cents(r["running_balance_cents"])
            data.append([
                r["date"],
                _format_time12(r["time"]),
                Paragraph(_escape(r["category_name"] or ""), cell_style),
                Paragraph(_escape(r["party_name"] or ""), cell_style),
                payment_mode_labels.get(r["payment_mode"], ""),
                Paragraph(_escape(r["description"] or ""), cell_style),
                amount,
                balance,
            ])
            row_styles.append(("TEXTCOLOR", (6, i), (6, i), GREEN if is_in else RED))
            row_styles.append(
                ("TEXTCOLOR", (7, i), (7, i), RED if r["running_balance_cents"] < 0 else TEXT)
            )

        table = Table(data, colWidths=[w * mm for w in COL_WIDTHS], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("ALIGN", (6, 0), (7, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("LINEBELOW", (0, 0), (-1, 0), 1, GREEN_DARK),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            *row_styles,
        ]))
        story.append(table)

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()


def _format_time12(hhmm):
    from datetime import datetime

    try:
        return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return hhmm
