-- Run against the production MySQL database after taking a backup.
-- Inspect duplicate groups first; reconcile or remove duplicate rows before
-- executing the ALTER TABLE statement.
SELECT user_id, bank_id, COUNT(*) AS duplicate_count
FROM user_progress
GROUP BY user_id, bank_id
HAVING COUNT(*) > 1;

ALTER TABLE user_progress
    ADD CONSTRAINT uq_user_progress_user_bank UNIQUE (user_id, bank_id);
