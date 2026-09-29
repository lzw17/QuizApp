-- 006: 游客账号支持
-- 小程序新增「免授权游客模式」：首次打开静默创建与微信身份无关的游客账号，
-- 可体验示例题库与全部练习功能；微信登录时把游客数据迁移到正式账号。
-- MySQL 5.7 / utf8mb4

ALTER TABLE users
    ADD COLUMN is_guest TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为免授权游客账号（无微信身份）';

-- 游客清理依赖 last_login，加索引避免全表扫描
CREATE INDEX ix_users_is_guest_last_login ON users (is_guest, last_login);
