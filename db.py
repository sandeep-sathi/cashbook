import re
import sqlite3
import sys
from pathlib import Path

from flask import g

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "cashbook.db"
MIGRATIONS_DIR = BASE_DIR / "migrations"

# Filenames must look like 0001_description.sql — at least 4 digits, zero-padded.
MIGRATION_RE = re.compile(r"^(\d{4,})_[\w]+\.sql$")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _discover_migrations():
    migrations = []
    seen = set()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        m = MIGRATION_RE.match(path.name)
        if not m:
            raise RuntimeError(
                f"Migration file {path.name!r} does not match NNNN_description.sql "
                "— refusing to guess its order."
            )
        version = int(m.group(1))
        if version in seen:
            raise RuntimeError(f"Duplicate migration version {version} ({path.name!r}).")
        seen.add(version)
        migrations.append((version, path))
    migrations.sort(key=lambda pair: pair[0])
    return migrations


def init_db():
    """Apply any migration files newer than the database's current user_version.

    Runs once at process startup on its own short-lived connection, separate
    from the per-request connections used by get_db(). Safe to call on every
    startup — an up-to-date database is a cheap no-op.
    """
    db = sqlite3.connect(DATABASE)
    try:
        current = db.execute("PRAGMA user_version").fetchone()[0]
        pending = [(v, p) for v, p in _discover_migrations() if v > current]

        if not pending:
            print(f"[db] Database is up to date at version {current}.")
            return

        applied = []
        for version, path in pending:
            try:
                db.executescript(path.read_text())
            except Exception:
                db.rollback()
                print(
                    f"[db] FAILED applying migration {path.name} — database left at "
                    f"version {current} (this migration's changes were rolled back). "
                    "Aborting startup.",
                    file=sys.stderr,
                )
                raise
            db.execute(f"PRAGMA user_version = {int(version)}")
            current = version
            applied.append(f"{version:04d}")

        print(f"[db] Applied migrations: {', '.join(applied)}. Now at version {current}.")
    finally:
        db.close()


# --- users -------------------------------------------------------

def get_user(user_id):
    return get_db().execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def get_user_by_username(username):
    return get_db().execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()


def get_user_by_email(email):
    return get_db().execute(
        "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
    ).fetchone()


def create_user(username, email, password_hash):
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
        (username, email, password_hash),
    )
    db.commit()
    return cur.lastrowid


def update_user_password(user_id, password_hash):
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    db.commit()


def update_user_email(user_id, email):
    db = get_db()
    db.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
    db.commit()


# --- books -------------------------------------------------------

def list_books(owner_id):
    return get_db().execute(
        "SELECT * FROM books WHERE owner_id = ? ORDER BY updated_at DESC",
        (owner_id,),
    ).fetchall()


def create_book(owner_id, name):
    db = get_db()
    cur = db.execute(
        "INSERT INTO books (owner_id, name, updated_at) VALUES (?, ?, datetime('now'))",
        (owner_id, name),
    )
    db.commit()
    return cur.lastrowid


def get_book(book_id, owner_id):
    return get_db().execute(
        "SELECT * FROM books WHERE id = ? AND owner_id = ?", (book_id, owner_id)
    ).fetchone()


def update_book_name(book_id, owner_id, name):
    db = get_db()
    db.execute(
        "UPDATE books SET name = ?, updated_at = datetime('now') WHERE id = ? AND owner_id = ?",
        (name, book_id, owner_id),
    )
    db.commit()


def touch_book(book_id):
    db = get_db()
    db.execute("UPDATE books SET updated_at = datetime('now') WHERE id = ?", (book_id,))


def delete_book(book_id, owner_id):
    db = get_db()
    db.execute("DELETE FROM books WHERE id = ? AND owner_id = ?", (book_id, owner_id))
    db.commit()


# --- categories ---------------------------------------------------------

def list_categories(book_id):
    return get_db().execute(
        "SELECT * FROM categories WHERE book_id = ? ORDER BY name COLLATE NOCASE",
        (book_id,),
    ).fetchall()


def get_or_create_category(book_id, name):
    if not name:
        return None
    db = get_db()
    row = db.execute(
        "SELECT id FROM categories WHERE book_id = ? AND name = ? COLLATE NOCASE",
        (book_id, name),
    ).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO categories (book_id, name) VALUES (?, ?)",
        (book_id, name),
    )
    db.commit()
    return cur.lastrowid


# --- parties ---------------------------------------------------------

def list_parties(book_id):
    return get_db().execute(
        "SELECT * FROM parties WHERE book_id = ? ORDER BY name COLLATE NOCASE",
        (book_id,),
    ).fetchall()


def get_or_create_party(book_id, name):
    if not name:
        return None
    db = get_db()
    row = db.execute(
        "SELECT id FROM parties WHERE book_id = ? AND name = ? COLLATE NOCASE",
        (book_id, name),
    ).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO parties (book_id, name) VALUES (?, ?)",
        (book_id, name),
    )
    db.commit()
    return cur.lastrowid


# --- transactions ---------------------------------------------------------

def list_transactions(
    book_id, date_from=None, date_to=None, category_id=None, party_id=None,
    payment_mode=None, q=None,
):
    sql = """
        WITH running AS (
          SELECT t.id, t.date, t.time, t.type, t.amount_cents, t.description, t.payment_mode,
                 c.id AS category_id, c.name AS category_name,
                 p.id AS party_id, p.name AS party_name,
                 SUM(CASE WHEN t.type='in' THEN t.amount_cents ELSE -t.amount_cents END)
                     OVER (ORDER BY t.date, t.time, t.id) AS running_balance_cents
          FROM transactions t
          LEFT JOIN categories c ON c.id = t.category_id
          LEFT JOIN parties p ON p.id = t.party_id
          WHERE t.book_id = :book_id
        )
        SELECT * FROM running
        WHERE (:date_from IS NULL OR date >= :date_from)
          AND (:date_to   IS NULL OR date <= :date_to)
          AND (:category_id IS NULL OR category_id = :category_id)
          AND (:party_id IS NULL OR party_id = :party_id)
          AND (:payment_mode IS NULL OR payment_mode = :payment_mode)
          AND (:q IS NULL OR description LIKE '%' || :q || '%')
        ORDER BY date, time, id
    """
    return get_db().execute(
        sql,
        {
            "book_id": book_id,
            "date_from": date_from,
            "date_to": date_to,
            "category_id": category_id,
            "party_id": party_id,
            "payment_mode": payment_mode,
            "q": q,
        },
    ).fetchall()


def create_transaction(
    book_id, date, time, type_, amount_cents, category_id, description, party_id, payment_mode
):
    db = get_db()
    db.execute(
        """INSERT INTO transactions
           (book_id, date, time, type, amount_cents, category_id, description, party_id, payment_mode)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (book_id, date, time, type_, amount_cents, category_id, description, party_id, payment_mode),
    )
    touch_book(book_id)
    db.commit()


def get_transaction(book_id, txn_id):
    return get_db().execute(
        "SELECT * FROM transactions WHERE id = ? AND book_id = ?",
        (txn_id, book_id),
    ).fetchone()


def update_transaction(
    book_id, txn_id, date, time, type_, amount_cents, category_id, description, party_id, payment_mode
):
    db = get_db()
    db.execute(
        """UPDATE transactions
           SET date = ?, time = ?, type = ?, amount_cents = ?, category_id = ?, description = ?,
               party_id = ?, payment_mode = ?
           WHERE id = ? AND book_id = ?""",
        (date, time, type_, amount_cents, category_id, description, party_id, payment_mode, txn_id, book_id),
    )
    touch_book(book_id)
    db.commit()


def delete_transaction(book_id, txn_id):
    db = get_db()
    db.execute(
        "DELETE FROM transactions WHERE id = ? AND book_id = ?",
        (txn_id, book_id),
    )
    touch_book(book_id)
    db.commit()


# --- reporting ---------------------------------------------------------

def monthly_totals(book_id, date_from=None, date_to=None):
    """Cash in/out per calendar month (YYYY-MM), ascending, months with no
    activity are simply absent rather than zero-filled."""
    rows = get_db().execute(
        """
        SELECT strftime('%Y-%m', date) AS month, type, SUM(amount_cents) AS total_cents
        FROM transactions
        WHERE book_id = :book_id
          AND (:date_from IS NULL OR date >= :date_from)
          AND (:date_to   IS NULL OR date <= :date_to)
        GROUP BY month, type
        ORDER BY month
        """,
        {"book_id": book_id, "date_from": date_from, "date_to": date_to},
    ).fetchall()

    by_month = {}
    for r in rows:
        entry = by_month.setdefault(r["month"], {"month": r["month"], "in_cents": 0, "out_cents": 0})
        entry[f"{r['type']}_cents"] = r["total_cents"]
    return sorted(by_month.values(), key=lambda e: e["month"])


def category_breakdown(book_id, type_, date_from=None, date_to=None):
    """Totals per category for one transaction type, largest first.
    Uncategorized transactions are grouped under a null category_id."""
    return get_db().execute(
        """
        SELECT t.category_id AS category_id,
               COALESCE(c.name, 'Uncategorized') AS category_name,
               SUM(t.amount_cents) AS total_cents
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.book_id = :book_id
          AND t.type = :type_
          AND (:date_from IS NULL OR t.date >= :date_from)
          AND (:date_to   IS NULL OR t.date <= :date_to)
        GROUP BY t.category_id
        ORDER BY total_cents DESC
        """,
        {"book_id": book_id, "type_": type_, "date_from": date_from, "date_to": date_to},
    ).fetchall()
