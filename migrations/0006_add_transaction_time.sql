BEGIN;

-- Time-of-day for each transaction, 24-hour "HH:MM". Existing rows backfill
-- to '00:00' since their original time was never recorded.
ALTER TABLE transactions ADD COLUMN time TEXT NOT NULL DEFAULT '00:00';

DROP INDEX IF EXISTS idx_transactions_book_date;
CREATE INDEX IF NOT EXISTS idx_transactions_book_date ON transactions(book_id, date, time, id);

COMMIT;
