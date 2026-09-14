# Production deployment

This project expects the backend to run behind Nginx on an HTTPS domain. The
production example domain is `api.quizapp.chat`; verify DNS, certificate and
WeChat legal domains before release, and replace every `<...>` placeholder.

## Backend

1. Install Python 3.11, MySQL and Nginx on the server.
2. Create a MySQL database with `utf8mb4` and a least-privilege application user.
3. Create `/opt/quizapp/backend/.env` from `backend/.env.example` and set:

```env
APP_ENV=production
DEBUG=false
SECRET_KEY=<openssl rand -hex 32>
WX_APPID=<mini-program appid>
WX_SECRET=<mini-program appsecret>
WX_MOCK_LOGIN=false
WX_MOCK_ADMIN=false
ADMIN_OPENIDS=<comma-separated openids>
DATABASE_URL=mysql+pymysql://quizapp:<password>@127.0.0.1:3306/quiz_app
PUBLIC_BASE_URL=https://api.quizapp.chat
UPLOAD_DIR=/var/lib/quizapp/uploads
ALLOWED_ORIGINS=https://api.quizapp.chat
DEEPSEEK_API_KEY=<deepseek key>
```

4. Install dependencies in `/opt/quizapp/backend/.venv`. Back up the database,
   inspect duplicate `(user_id, bank_id)` rows, and apply
   `backend/migrations/001_user_progress_unique_mysql.sql` and
   `backend/migrations/002_user_token_version_mysql.sql`, and
   `backend/migrations/003_user_account_deletion_mysql.sql` before starting
   the service. `create_all()` creates missing tables but does not alter existing
   production tables.
5. Install `quizapp.service` as a systemd unit and start it.
6. Install `nginx/quizapp.conf`, issue an HTTPS certificate, and reload Nginx.

The current worker uses FastAPI `BackgroundTasks`, so run one Uvicorn worker until
AI generation is moved to a durable Redis/Celery/RQ worker. Do not use `run.py`
with production reload enabled.

## WeChat platform

In the Mini Program console, add `https://api.quizapp.chat` to request and
uploadFile legal domains. Use the same HTTPS origin in `miniapp/app.js`, build
the `miniapp/` directory, test the experience version, then submit for review.

## Smoke checks

```bash
curl --fail https://api.quizapp.chat/health
curl --fail -I https://api.quizapp.chat/uploads/avatars/known-avatar.png
```

The source-document directory must not be exposed by Nginx. Only the avatar
subdirectory is mounted by the application.
