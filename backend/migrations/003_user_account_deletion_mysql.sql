-- Add the account lifecycle flag used by DELETE /api/auth/account.
ALTER TABLE users
    ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Whether the account can sign in';
