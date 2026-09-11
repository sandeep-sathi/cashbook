import csv
import io
import os
import sqlite3
import sys
import threading
import time
from collections import deque
from datetime import date
from urllib.parse import urlparse

from flask import Flask, flash, redirect, render_template, request, Response, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf import CSRFProtect
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import db
import mailer
import validation

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["PREFERRED_URL_SCHEME"] = "https"

_secret_key = os.environ.get("SECRET_KEY")
_invite_code = os.environ.get("CASHBOOK_INVITE_CODE")
if not _secret_key or not _invite_code:
    print(
        "[app] WARNING: SECRET_KEY and/or CASHBOOK_INVITE_CODE are not set via "
        "environment variables — falling back to insecure development defaults. "
        "Set both before deploying anywhere real users can reach this app.",
        file=sys.stderr,
    )
app.secret_key = _secret_key or "dev-secret-change-me"
app.config["INVITE_CODE"] = _invite_code or "change-me"

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
)

app.teardown_appcontext(db.close_db)

csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"


class AuthUser(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]
        self.email = row["email"]


@login_manager.user_loader
def load_user(user_id):
    row = db.get_user(int(user_id))
    return AuthUser(row) if row else None


def _safe_next_url(next_url):
    if next_url and next_url.startswith("/") and urlparse(next_url).netloc == "":
        return next_url
    return None


# --- password reset tokens -------------------------------------------------

def _reset_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="password-reset")


def generate_reset_token(user):
    return _reset_serializer().dumps({"uid": user["id"], "fp": user["password_hash"][-12:]})


def verify_reset_token(token, max_age=3600):
    try:
        data = _reset_serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    user = db.get_user(data.get("uid"))
    if not user or user["password_hash"][-12:] != data.get("fp"):
        return None
    return user


# --- forgot-password abuse guard (in-memory; single-process deployment) ---

_send_lock = threading.Lock()
_last_sent_by_email = {}
_recent_sends = deque()

COOLDOWN_SECONDS = 60
MAX_SENDS_PER_HOUR = 50


def _should_send(email):
    now = time.time()
    with _send_lock:
        while _recent_sends and now - _recent_sends[0] > 3600:
            _recent_sends.popleft()
        if len(_recent_sends) >= MAX_SENDS_PER_HOUR:
            return False
        last = _last_sent_by_email.get(email)
        if last and now - last < COOLDOWN_SECONDS:
            return False
        _last_sent_by_email[email] = now
        _recent_sends.append(now)
        if len(_last_sent_by_email) > 1000:
            cutoff = now - COOLDOWN_SECONDS
            for k in [k for k, v in _last_sent_by_email.items() if v < cutoff]:
                del _last_sent_by_email[k]
        return True


def _send_reset_email_safe(to_email, reset_url):
    try:
        mailer.send_password_reset_email(to_email, reset_url)
    except Exception as e:
        print(f"[mailer] Failed to send password reset email: {e}", file=sys.stderr, flush=True)


@app.template_filter("money")
def money_filter(cents):
    return f"{cents / 100:,.2f}"


@app.route("/")
def index():
    return redirect(url_for("businesses"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("businesses"))

    if request.method == "POST":
        try:
            username = validation.validate_username(request.form.get("username"))
            email = validation.validate_email(request.form.get("email"))
            password = validation.validate_password(request.form.get("password"))
            if password != request.form.get("confirm_password"):
                raise ValueError("Passwords do not match.")
            validation.validate_invite_code(
                request.form.get("invite_code"), app.config["INVITE_CODE"]
            )
            password_hash = generate_password_hash(password)
            user_id = db.create_user(username, email, password_hash)
            login_user(AuthUser(db.get_user(user_id)))
            return redirect(url_for("businesses"))
        except sqlite3.IntegrityError as e:
            if "username" in str(e):
                flash("That username is already taken.")
            else:
                flash(
                    "That email or username can't be used — if you already have an "
                    "account, try logging in or use Forgot password."
                )
        except ValueError as e:
            flash(str(e))
        return render_template(
            "signup.html",
            form_username=request.form.get("username", ""),
            form_email=request.form.get("email", ""),
        )

    return render_template("signup.html", form_username="", form_email="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("businesses"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user_row = db.get_user_by_username(username)
        if user_row and check_password_hash(user_row["password_hash"], password):
            login_user(AuthUser(user_row), remember=bool(request.form.get("remember")))
            return redirect(_safe_next_url(request.args.get("next")) or url_for("businesses"))
        flash("Invalid username or password.")
        return render_template("login.html", form_username=username)

    return render_template("login.html", form_username="")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("businesses"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        if email:
            user = db.get_user_by_email(email)
            if user and _should_send(email):
                token = generate_reset_token(user)
                reset_url = url_for("reset_password", token=token, _external=True)
                threading.Thread(
                    target=_send_reset_email_safe, args=(email, reset_url), daemon=True
                ).start()
        flash("If an account with that email exists, we've sent a password reset link.")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = verify_reset_token(token)
    if user is None:
        flash("That password reset link is invalid or has expired.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        try:
            password = validation.validate_password(request.form.get("password"))
            if password != request.form.get("confirm_password"):
                raise ValueError("Passwords do not match.")
            db.update_user_password(user["id"], generate_password_hash(password))
            flash("Your password has been reset. Please log in.")
            return redirect(url_for("login"))
        except ValueError as e:
            flash(str(e))
            return render_template("reset_password.html", token=token)

    return render_template("reset_password.html", token=token)


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    user_row = db.get_user(current_user.id)

    if request.method == "POST":
        try:
            if not check_password_hash(
                user_row["password_hash"], request.form.get("current_password", "")
            ):
                raise ValueError("Current password is incorrect.")
            email = validation.validate_email(request.form.get("email"))
            db.update_user_email(current_user.id, email)
            flash("Email updated.")
            return redirect(url_for("account"))
        except sqlite3.IntegrityError:
            flash("That email is already associated with another account.")
        except ValueError as e:
            flash(str(e))
        return render_template("account.html", email=request.form.get("email", ""))

    return render_template("account.html", email=user_row["email"] or "")


@app.route("/businesses", methods=["GET", "POST"])
@login_required
def businesses():
    if request.method == "POST":
        try:
            name = validation.validate_business_name(request.form.get("name"))
            business_id = db.create_business(current_user.id, name)
            return redirect(url_for("ledger", business_id=business_id))
        except sqlite3.IntegrityError:
            flash("A business with that name already exists.")
        except ValueError as e:
            flash(str(e))
        return render_template(
            "businesses.html",
            businesses=db.list_businesses(current_user.id),
            form_name=request.form.get("name", ""),
        )

    return render_template(
        "businesses.html", businesses=db.list_businesses(current_user.id), form_name=""
    )


def _filter_args():
    return {
        "date_from": request.args.get("date_from") or None,
        "date_to": request.args.get("date_to") or None,
        "category_id": request.args.get("category_id") or None,
        "q": request.args.get("q") or None,
    }


@app.route("/businesses/<int:business_id>/ledger")
@login_required
def ledger(business_id):
    business = db.get_business(business_id, current_user.id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    filters = _filter_args()
    rows = db.list_transactions(business_id, **filters)

    total_in = sum(r["amount_cents"] for r in rows if r["type"] == "in")
    total_out = sum(r["amount_cents"] for r in rows if r["type"] == "out")

    query_args = {k: v for k, v in filters.items() if v}

    grouped = []
    for r in reversed(rows):
        if not grouped or grouped[-1]["date"] != r["date"]:
            grouped.append({"date": r["date"], "rows": []})
        grouped[-1]["rows"].append(r)

    return render_template(
        "ledger.html",
        business=business,
        grouped=grouped,
        categories=db.list_categories(business_id),
        filters=filters,
        query_args=query_args,
        total_in=total_in,
        total_out=total_out,
        net=total_in - total_out,
    )


@app.route("/businesses/<int:business_id>/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction(business_id):
    business = db.get_business(business_id, current_user.id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    if request.method == "POST":
        try:
            txn_date = validation.parse_date(request.form.get("date"))
            txn_type = validation.validate_type(request.form.get("type"))
            amount_cents = validation.parse_amount(request.form.get("amount"))
            category_name = validation.clean_category_name(request.form.get("category"))
            description = validation.clean_description(request.form.get("description"))
            category_id = db.get_or_create_category(business_id, category_name)
            db.create_transaction(
                business_id, txn_date, txn_type, amount_cents, category_id, description
            )
            return redirect(url_for("ledger", business_id=business_id))
        except ValueError as e:
            flash(str(e))
            return render_template(
                "transaction_form.html",
                business=business,
                action="new",
                txn=request.form,
                business_categories=db.list_categories(business_id),
            )

    default_type = request.args.get("type")
    if default_type not in ("in", "out"):
        default_type = "in"

    return render_template(
        "transaction_form.html",
        business=business,
        action="new",
        txn={"date": date.today().isoformat(), "type": default_type},
        business_categories=db.list_categories(business_id),
    )


@app.route("/businesses/<int:business_id>/transactions/<int:txn_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(business_id, txn_id):
    business = db.get_business(business_id, current_user.id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    txn = db.get_transaction(business_id, txn_id)
    if txn is None:
        flash("Transaction not found.")
        return redirect(url_for("ledger", business_id=business_id))

    if request.method == "POST":
        try:
            txn_date = validation.parse_date(request.form.get("date"))
            txn_type = validation.validate_type(request.form.get("type"))
            amount_cents = validation.parse_amount(request.form.get("amount"))
            category_name = validation.clean_category_name(request.form.get("category"))
            description = validation.clean_description(request.form.get("description"))
            category_id = db.get_or_create_category(business_id, category_name)
            db.update_transaction(
                business_id, txn_id, txn_date, txn_type, amount_cents, category_id, description
            )
            return redirect(url_for("ledger", business_id=business_id))
        except ValueError as e:
            flash(str(e))
            return render_template(
                "transaction_form.html",
                business=business,
                action="edit",
                txn=request.form,
                txn_id=txn_id,
                business_categories=db.list_categories(business_id),
            )

    category_row = None
    if txn["category_id"]:
        category_row = next(
            (c for c in db.list_categories(business_id) if c["id"] == txn["category_id"]), None
        )
    form_values = {
        "date": txn["date"],
        "type": txn["type"],
        "amount": f"{txn['amount_cents'] / 100:.2f}",
        "category": category_row["name"] if category_row else "",
        "description": txn["description"] or "",
    }
    return render_template(
        "transaction_form.html",
        business=business,
        action="edit",
        txn=form_values,
        txn_id=txn_id,
        business_categories=db.list_categories(business_id),
    )


@app.route("/businesses/<int:business_id>/transactions/<int:txn_id>/delete", methods=["POST"])
@login_required
def delete_transaction(business_id, txn_id):
    business = db.get_business(business_id, current_user.id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    db.delete_transaction(business_id, txn_id)
    return redirect(url_for("ledger", business_id=business_id))


@app.route("/businesses/<int:business_id>/export.csv")
@login_required
def export_csv(business_id):
    business = db.get_business(business_id, current_user.id)
    if business is None:
        flash("Business not found.")
        return redirect(url_for("businesses"))

    filters = _filter_args()
    rows = db.list_transactions(business_id, **filters)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Type", "Category", "Description", "Amount", "Running Balance"])
    for r in rows:
        writer.writerow(
            [
                r["date"],
                r["type"],
                r["category_name"] or "",
                r["description"] or "",
                f"{r['amount_cents'] / 100:.2f}",
                f"{r['running_balance_cents'] / 100:.2f}",
            ]
        )

    safe_name = "".join(c for c in business["name"] if c.isalnum() or c in " -_").strip() or "business"
    filename = f"{safe_name}_{date.today().isoformat()}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
