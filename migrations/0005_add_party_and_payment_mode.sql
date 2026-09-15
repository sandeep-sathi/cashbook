BEGIN;

CREATE TABLE IF NOT EXISTS parties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    name        TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_parties_book_name
    ON parties(book_id, name COLLATE NOCASE);

ALTER TABLE transactions ADD COLUMN party_id INTEGER REFERENCES parties(id) ON DELETE SET NULL;
ALTER TABLE transactions ADD COLUMN payment_mode TEXT
    CHECK(payment_mode IN ('cash','bank_transfer','upi','cheque','card','other') OR payment_mode IS NULL);

COMMIT;
