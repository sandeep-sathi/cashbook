BEGIN;

ALTER TABLE businesses RENAME TO books;
ALTER TABLE categories RENAME COLUMN business_id TO book_id;
ALTER TABLE transactions RENAME COLUMN business_id TO book_id;

DROP INDEX IF EXISTS idx_businesses_owner_name;
CREATE UNIQUE INDEX IF NOT EXISTS idx_books_owner_name ON books(owner_id, name COLLATE NOCASE);

DROP INDEX IF EXISTS idx_categories_business_name;
CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_book_name ON categories(book_id, name COLLATE NOCASE);

DROP INDEX IF EXISTS idx_transactions_business_date;
CREATE INDEX IF NOT EXISTS idx_transactions_book_date ON transactions(book_id, date, id);

COMMIT;
