BEGIN;

ALTER TABLE books ADD COLUMN updated_at TEXT;
UPDATE books SET updated_at = created_at WHERE updated_at IS NULL;

COMMIT;
