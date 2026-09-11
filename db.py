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


def create_user(username, password_hash):
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    db.commit()
    return cur.lastrowid


# --- businesses -------------------------------------------------------

def list_businesses(owner_id):
    return get_db().execute(
        "SELECT * FROM businesses WHERE owner_id = ? ORDER BY name COLLATE NOCASE",
        (owner_id,),
    ).fetchall()


def create_business(owner_id, name):
    db = get_db()
    cur = db.execute(
        "INSERT INTO businesses (owner_id, name) VALUES (?, ?)", (owner_id, name)
    )
    db.commit()
    return cur.lastrowid


def get_business(business_id, owner_id):
    return get_db().execute(
        "SELECT * FROM businesses WHERE id = ? AND owner_id = ?", (business_id, owner_id)
    ).fetchone()


# --- categories ---------------------------------------------------------

def list_categories(business_id):
    return get_db().execute(
        "SELECT * FROM categories WHERE business_id = ? ORDER BY name COLLATE NOCASE",
        (business_id,),
    ).fetchall()


def get_or_create_category(business_id, name):
    if not name:
        return None
    db = get_db()
    row = db.execute(
        "SELECT id FROM categories WHERE business_id = ? AND name = ? COLLATE NOCASE",
        (business_id, name),
    ).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO categories (business_id, name) VALUES (?, ?)",
        (business_id, name),
    )
    db.commit()
    return cur.lastrowid


# --- transactions ---------------------------------------------------------

def list_transactions(business_id, date_from=None, date_to=None, category_id=None, q=None):
    sql = """
        WITH running AS (
          SELECT t.id, t.date, t.type, t.amount_cents, t.description,
                 c.id AS category_id, c.name AS category_name,
                 SUM(CASE WHEN t.type='in' THEN t.amount_cents ELSE -t.amount_cents END)
                     OVER (ORDER BY t.date, t.id) AS running_balance_cents
          FROM transactions t
          LEFT JOIN categories c ON c.id = t.category_id
          WHERE t.business_id = :business_id
        )
        SELECT * FROM running
        WHERE (:date_from IS NULL OR date >= :date_from)
          AND (:date_to   IS NULL OR date <= :date_to)
          AND (:category_id IS NULL OR category_id = :category_id)
          AND (:q IS NULL OR description LIKE '%' || :q || '%')
        ORDER BY date, id
    """
    return get_db().execute(
        sql,
        {
            "business_id": business_id,
            "date_from": date_from,
            "date_to": date_to,
            "category_id": category_id,
            "q": q,
        },
    ).fetchall()


def create_transaction(business_id, date, type_, amount_cents, category_id, description):
    db = get_db()
    db.execute(
        """INSERT INTO transactions (business_id, date, type, amount_cents, category_id, description)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (business_id, date, type_, amount_cents, category_id, description),
    )
    db.commit()


def get_transaction(business_id, txn_id):
    return get_db().execute(
        "SELECT * FROM transactions WHERE id = ? AND business_id = ?",
        (txn_id, business_id),
    ).fetchone()


def update_transaction(business_id, txn_id, date, type_, amount_cents, category_id, description):
    db = get_db()
    db.execute(
        """UPDATE transactions
           SET date = ?, type = ?, amount_cents = ?, category_id = ?, description = ?
           WHERE id = ? AND business_id = ?""",
        (date, type_, amount_cents, category_id, description, txn_id, business_id),
    )
    db.commit()


def delete_transaction(business_id, txn_id):
    db = get_db()
    db.execute(
        "DELETE FROM transactions WHERE id = ? AND business_id = ?",
        (txn_id, business_id),
    )
    db.commit()
