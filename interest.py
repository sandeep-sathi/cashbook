import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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


def format_money_cents(cents):
    """Whole-rupee, Indian-grouped display for a paise-precision cents value
    (e.g. 123475 -> '1,235', rounded half-up)."""
    sign = "-" if cents < 0 else ""
    rupees, paise = divmod(abs(cents), 100)
    if paise >= 50:
        rupees += 1
    return f"{sign}{format_inr(rupees)}"


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

