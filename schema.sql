PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS businesses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_businesses_name
    ON businesses(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name        TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_business_name
    ON categories(business_id, name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id   INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    date          TEXT NOT NULL,
    type          TEXT NOT NULL CHECK(type IN ('in','out')),
    amount_cents  INTEGER NOT NULL CHECK(amount_cents > 0),
    category_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    description   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_transactions_business_date
    ON transactions(business_id, date, id);
