-- 服务端退出登录立即撤销已签发 token。
-- 执行前请确认 users 表中不存在同名字段。
ALTER TABLE users
    ADD COLUMN token_version INT NOT NULL DEFAULT 0 COMMENT '服务端撤销登录态的版本号';
