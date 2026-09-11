import datetime
from decimal import Decimal, InvalidOperation


def parse_date(s):
    if not s or not s.strip():
        raise ValueError("Date is required.")
    try:
        return datetime.date.fromisoformat(s.strip()).isoformat()
    except ValueError:
        raise ValueError("Invalid date.")


def parse_amount(s):
    if not s or not s.strip():
        raise ValueError("Amount is required.")
    try:
        amount = Decimal(s.strip())
    except InvalidOperation:
        raise ValueError("Amount must be a number.")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError("Amount can have at most 2 decimal places.")
    return int(cents)


def validate_type(s):
    if s not in ("in", "out"):
        raise ValueError("Type must be 'in' or 'out'.")
    return s


def clean_category_name(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if len(s) > 50:
        raise ValueError("Category name must be 50 characters or fewer.")
    return s


def clean_description(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if len(s) > 500:
        raise ValueError("Description must be 500 characters or fewer.")
    return s


def validate_business_name(s):
    if not s or not s.strip():
        raise ValueError("Business name is required.")
    s = s.strip()
    if len(s) > 100:
        raise ValueError("Business name must be 100 characters or fewer.")
    return s


def validate_username(s):
    if not s or not s.strip():
        raise ValueError("Username is required.")
    s = s.strip()
    if len(s) < 3 or len(s) > 50:
        raise ValueError("Username must be between 3 and 50 characters.")
    return s


def validate_password(s):
    if not s:
        raise ValueError("Password is required.")
    if len(s) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return s


def validate_invite_code(s, expected):
    if not s or s.strip() != expected:
        raise ValueError("Invalid invite code.")
    return s.strip()
