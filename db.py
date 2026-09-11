import sqlite3
from pathlib import Path

from flask import g

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "cashbook.db"
SCHEMA = BASE_DIR / "schema.sql"


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


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript(SCHEMA.read_text())
    db.close()


# --- businesses -------------------------------------------------------

def list_businesses():
    return get_db().execute(
        "SELECT * FROM businesses ORDER BY name COLLATE NOCASE"
    ).fetchall()


def create_business(name):
    db = get_db()
    cur = db.execute("INSERT INTO businesses (name) VALUES (?)", (name,))
    db.commit()
    return cur.lastrowid


def get_business(business_id):
    return get_db().execute(
        "SELECT * FROM businesses WHERE id = ?", (business_id,)
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
