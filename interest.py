import datetime
import io
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MAX_TOTAL_DAYS = 36500  # ~100 years, catches typo'd inputs

COMPOUND_OPTIONS = [
    ("none", "None"),
    ("yearly", "Yearly"),
    ("half_yearly", "Half-Yearly"),
    ("quarterly", "Quarterly"),
    ("monthly", "Monthly"),
    ("daily", "Daily"),
]

_COMPOUND_N = {
    "yearly": Decimal(1),
    "half_yearly": Decimal(2),
    "quarterly": Decimal(4),
    "monthly": Decimal(12),
    "daily": Decimal(365),
}


def parse_principal(s):
    if not s or not s.strip():
        raise ValueError("Amount is required.")
    try:
        value = Decimal(s.strip())
    except InvalidOperation:
        raise ValueError("Amount must be a number.")
    if value <= 0:
        raise ValueError("Amount must be greater than zero.")
    return value


def parse_rate(s):
    if not s or not s.strip():
        raise ValueError("Interest rate is required.")
    try:
        value = Decimal(s.strip())
    except InvalidOperation:
        raise ValueError("Interest rate must be a number.")
    if value < 0:
        raise ValueError("Interest rate cannot be negative.")
    if value > 50:
        raise ValueError("Interest rate cannot be more than 50%.")
    return value


def _parse_nonneg_int(s, label):
    s = (s or "").strip()
    if not s:
        return 0
    try:
        value = int(s)
    except ValueError:
        raise ValueError(f"{label} must be a whole number.")
    if value < 0:
        raise ValueError(f"{label} cannot be negative.")
    return value


def resolve_total_days_from_period(years_s, months_s, days_s):
    years = _parse_nonneg_int(years_s, "Year")
    months = _parse_nonneg_int(months_s, "Month")
    days = _parse_nonneg_int(days_s, "Day")
    total_days = years * 365 + months * 30 + days
    if total_days <= 0:
        raise ValueError("Enter a period greater than zero.")
    if total_days > MAX_TOTAL_DAYS:
        raise ValueError("That period is too long.")
    return total_days


def resolve_total_days_from_dates(from_s, to_s):
    if not from_s or not from_s.strip():
        raise ValueError("From date is required.")
    if not to_s or not to_s.strip():
        raise ValueError("To date is required.")
    try:
        from_date = datetime.date.fromisoformat(from_s.strip())
    except ValueError:
        raise ValueError("Invalid from date.")
    try:
        to_date = datetime.date.fromisoformat(to_s.strip())
    except ValueError:
        raise ValueError("Invalid to date.")
    total_days = (to_date - from_date).days
    if total_days <= 0:
        raise ValueError("To date must be after from date.")
    if total_days > MAX_TOTAL_DAYS:
        raise ValueError("That date range is too long.")
    return total_days


# The entered rate is never cross-converted between Year/Month bases (e.g. a
# monthly rate is NOT annualized via *12). Instead the rate basis just picks
# which unit elapsed time is measured in before applying the rate directly:
# a Year-basis rate is applied against elapsed time in years (days/365), a
# Month-basis rate against elapsed time in 30-day months (days/30). Confirmed
# against a reference calculation: P=60000, rate=2%/month, 30 days, simple
# interest -> 1,200 (60000 * 0.02 * (30/30)); the previously-assumed
# "annualize via *12" approach produced 1,184, which does not match.
_RATE_BASIS_UNIT_DAYS = {
    "year": Decimal(365),
    "month": Decimal(30),
}


def calculate(principal, rate_pct, rate_basis, compound_interval, total_days):
    unit_days = _RATE_BASIS_UNIT_DAYS[rate_basis]
    periods_elapsed = Decimal(total_days) / unit_days
    rate = rate_pct / 100

    if compound_interval == "none":
        interest_amt = principal * rate * periods_elapsed
    else:
        # Compound Interval options (Yearly/Half-Yearly/.../Daily) are
        # defined as a frequency per YEAR. Re-express that frequency in the
        # same unit as the rate basis so it composes correctly with
        # periods_elapsed above (unverified against a reference example for
        # the month-basis case, but consistent with the confirmed simple-
        # interest behavior and the already-standard year-basis formula).
        n_per_year = _COMPOUND_N[compound_interval]
        n = n_per_year if rate_basis == "year" else n_per_year / 12
        amount = principal * (1 + rate / n) ** (n * periods_elapsed)
        interest_amt = amount - principal

    total_amt = principal + interest_amt

    quantum = Decimal("1")
    return (
        interest_amt.quantize(quantum, rounding=ROUND_HALF_UP),
        total_amt.quantize(quantum, rounding=ROUND_HALF_UP),
    )


def format_inr(value):
    value = Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    negative = value < 0
    value = abs(value)
    s = str(int(value))
    if len(s) > 3:
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        s = ",".join(parts) + "," + last3
    return ("-" if negative else "") + s


# --- share-as-image ---------------------------------------------------

_FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
_COMPOUND_LABELS = dict(COMPOUND_OPTIONS)

_GREEN = (10, 143, 91)
_GREEN_DARK = (7, 107, 69)
_GREEN_TINT = (234, 250, 243)
_TEXT = (26, 26, 26)
_MUTED = (107, 114, 128)
_BORDER = (229, 231, 235)
_WHITE = (255, 255, 255)


def _font(name, size):
    return ImageFont.truetype(str(_FONT_DIR / name), size)


def _format_period_summary(years_s, months_s, days_s):
    y = _parse_nonneg_int(years_s, "Year")
    m = _parse_nonneg_int(months_s, "Month")
    d = _parse_nonneg_int(days_s, "Day")
    parts = []
    if y:
        parts.append(f"{y} Year{'s' if y != 1 else ''}")
    if m:
        parts.append(f"{m} Month{'s' if m != 1 else ''}")
    if d:
        parts.append(f"{d} Day{'s' if d != 1 else ''}")
    return " ".join(parts) if parts else "0 Days"


def build_summary_line(form):
    rate_basis_label = "Month" if form["rate_basis"] == "month" else "Year"
    compound_label = _COMPOUND_LABELS.get(form["compound"], "None")
    principal_str = f"₹{format_inr(Decimal(form['amount'].strip()))}"
    rate_str = f"{form['rate'].strip()}%/{rate_basis_label}"
    if form["mode"] == "date":
        duration_str = f"{form['from_date']} to {form['to_date']}"
    else:
        duration_str = _format_period_summary(
            form["period_years"], form["period_months"], form["period_days"]
        )
    compound_str = f", {compound_label} compounding" if form["compound"] != "none" else ""
    return f"{principal_str} @ {rate_str}{compound_str}, {duration_str}"


def generate_share_image(form, result):
    width, height = 720, 620
    img = Image.new("RGB", (width, height), _WHITE)
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([1, 1, width - 2, height - 2], radius=20, outline=_BORDER, width=2)

    header_h = 100
    draw.rounded_rectangle([2, 2, width - 3, header_h + 20], radius=20, fill=_GREEN)
    draw.rectangle([2, header_h - 20, width - 3, header_h], fill=_GREEN)
    draw.text((36, 24), "Cashbook", font=_font("DejaVuSans-Bold.ttf", 32), fill=_WHITE)
    draw.text((36, 64), "Interest Calculator", font=_font("DejaVuSans.ttf", 20), fill=_WHITE)

    label_font = _font("DejaVuSans.ttf", 22)
    value_font = _font("DejaVuSans-Bold.ttf", 26)

    rows = [
        ("Principal Amount", f"₹{format_inr(result['principal'])}", False),
        ("Total Interest", f"₹{format_inr(result['interest'])}", False),
        ("Total Days", str(result["total_days"]), False),
        ("Total Amount", f"₹{format_inr(result['total_amount'])}", True),
    ]

    row_h = 88
    y = header_h + 30
    for label, value, highlight in rows:
        if highlight:
            draw.rectangle([2, y, width - 3, y + row_h], fill=_GREEN_TINT)
        else:
            draw.line([(36, y + row_h), (width - 36, y + row_h)], fill=_BORDER, width=1)

        label_color = _GREEN_DARK if highlight else _MUTED
        value_color = _GREEN_DARK if highlight else _TEXT
        draw.text((36, y + row_h // 2 - 14), label, font=label_font, fill=label_color)

        bbox = draw.textbbox((0, 0), value, font=value_font)
        value_w = bbox[2] - bbox[0]
        draw.text(
            (width - 36 - value_w, y + row_h // 2 - 16), value, font=value_font, fill=value_color
        )
        y += row_h

    summary_font = _font("DejaVuSans.ttf", 18)
    draw.text((36, y + 24), build_summary_line(form), font=summary_font, fill=_MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()
