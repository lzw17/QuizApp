# Production deployment

This project expects the backend to run behind Nginx on an HTTPS domain. The
production example domain is `api.quizapp.chat`; verify DNS, certificate and
WeChat legal domains before release, and replace every `<...>` placeholder.

## Backend

1. Install Python 3.11, MySQL and Nginx on the server.
2. Create a MySQL database with `utf8mb4` and a least-privilege application user.
3. Create `/opt/quizapp/backend/.env` from
   `backend/.env.production.example`. For a systemd deployment, change the
   database host to `127.0.0.1` and set `UPLOAD_DIR=/var/lib/quizapp/uploads`:

```env
APP_NAME=智题学习笔记
APP_ENV=production
DEBUG=false
SECRET_KEY=<openssl rand -hex 32>
JWT_ISSUER=quizapp-api
WX_APPID=<mini-program appid>
WX_SECRET=<mini-program appsecret>
WX_MOCK_LOGIN=false
WX_MOCK_ADMIN=false
ADMIN_OPENIDS=<comma-separated openids>
DATABASE_URL=mysql+pymysql://quizapp:<password>@127.0.0.1:3306/quiz_app
PUBLIC_BASE_URL=https://api.quizapp.chat
UPLOAD_DIR=/var/lib/quizapp/uploads
ALLOWED_ORIGINS=https://servicewechat.com
DEEPSEEK_API_KEY=<deepseek key>
MAX_ACTIVE_GENERATION_TASKS=2
MAX_CONCURRENT_GENERATION_TASKS=2
GENERATION_TIMEOUT_SECONDS=900
```

4. Install `requirements-prod.txt` in `/opt/quizapp/backend/.venv`. Back up the database,
   inspect duplicate `(user_id, bank_id)` rows, and apply
   `backend/migrations/001_user_progress_unique_mysql.sql` and
   `backend/migrations/002_user_token_version_mysql.sql`, and
   `backend/migrations/003_user_account_deletion_mysql.sql` before starting
   the service. `create_all()` creates missing tables but does not alter existing
   production tables.
5. Install `quizapp.service` as a systemd unit and start it. The unit creates
   `/var/lib/quizapp`; the application creates its `uploads/` and `avatars/`
   subdirectories as the `quizapp` service user.
6. For the Docker layout (Docker Compose v2.24+), keep the production
   template's `DATABASE_URL` host as `mysql` and `UPLOAD_DIR=/app/uploads`.
   The normal Nginx config expects an existing certificate
   in `deploy/certs/`. On a new host, first create the ACME webroot and start the
   HTTP-only bootstrap config:

```bash
mkdir -p deploy/certbot-webroot deploy/certs
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.bootstrap.yml up -d --build
certbot certonly --webroot -w deploy/certbot-webroot -d api.quizapp.chat
cp /etc/letsencrypt/live/api.quizapp.chat/fullchain.pem deploy/certs/api.quizapp.chat.pem
cp /etc/letsencrypt/live/api.quizapp.chat/privkey.pem deploy/certs/api.quizapp.chat.key
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.bootstrap.yml down
docker compose -f deploy/docker-compose.yml up -d
```

   Renew the certificate before expiry and reload the Nginx container. Do not
   start the normal compose file before both certificate files exist.

The current worker uses FastAPI `BackgroundTasks`, so run one Uvicorn worker until
AI generation is moved to a durable Redis/Celery/RQ worker. Do not use `run.py`
with production reload enabled.

## WeChat platform

In the Mini Program console, add `https://api.quizapp.chat` to request and
uploadFile legal domains. Use the same HTTPS origin in `miniapp/app.js`, build
the `miniapp/` directory, test the experience version, then submit for review.
The User Privacy Protection Guide must also disclose that uploaded file or URL
content is sent to DeepSeek for question generation, URL addresses are sent to
Jina Reader for webpage extraction, and, when enabled, PDFs are sent to MinerU
for cloud parsing. Keep the provider list aligned with production config.

## Smoke checks

```bash
curl --fail https://api.quizapp.chat/health
curl --fail -I https://api.quizapp.chat/uploads/avatars/known-avatar.png
```

The source-document directory must not be exposed by Nginx. Only the avatar
subdirectory is mounted by the application.
