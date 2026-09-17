# 智题学习笔记上线操作手册（宝塔面板版）

> 服务器：阿里云轻量 2核1G / 武汉 / 公网 IP `8.148.21.181` / 宝塔 Linux 面板
> 域名：`quizapp.chat`（备案进行中），后端域名用 `api.quizapp.chat`
> 方案说明：因服务器只有 1G 内存，**不使用** deploy/ 下的 docker-compose（MySQL+Redis+Nginx 三容器会吃满内存），改用宝塔自带的 Nginx + MySQL + Python 项目管理器，更省内存也更好维护。

> **备案期间限制**：可以安装软件、创建数据库并让后端仅监听 `127.0.0.1`，但不要通过域名对外提供内容。第 2、7、8 步必须等 ICP 备案通过后再执行。

---

## 第 0 步：域名解析（阿里云控制台，5 分钟）

1. 登录阿里云控制台 → 云解析 DNS → `quizapp.chat` → 添加记录：
   - 记录类型：`A`　主机记录：`api`　记录值：`8.148.21.181`　TTL：默认
2. 验证：本机 `ping api.quizapp.chat` 返回 8.148.21.181 即生效

## 第 1 步：宝塔安装软件（软件商店，约 10 分钟）

宝塔面板 → 软件商店，安装以下三个（安装时选生产环境默认项）：

| 软件 | 说明 |
|---|---|
| **Nginx** | 反向代理 + SSL |
| **MySQL 8.0**（内存紧张可装 5.7） | 数据库 |
| **Python 项目管理器** | 托管 uvicorn 进程、开机自启 |

⚠️ 不要装"phpMyAdmin/PHP"等用不到的东西，1G 内存要省着用。

## 第 2 步：备案通过后放行端口（两处都要）

1. **阿里云控制台** → 轻量应用服务器 → 防火墙 → 添加规则：放行 `80`、`443`（TCP）
2. 宝塔面板 → 安全 → 同样放行 `80/443`（22 端口保持只允许自己的 IP 更佳）

## 第 3 步：建数据库（宝塔 → 数据库）

1. 添加数据库：库名 `quizapp`，用户名 `quizapp`，密码点"生成"（复制保存）
2. 字符集选 `utf8mb4`

## 第 4 步：上传代码（宝塔 → 文件）

1. 在已经通过测试的提交上执行 `git archive --format=zip --output quizapp-release.zip HEAD`。不要直接压缩工作目录，避免把 `.env`、上传资料、缓存或未提交文件带上服务器
2. 宝塔文件管理进入 `/www/wwwroot/`，上传 zip 并解压为 `/www/wwwroot/quizapp`
3. 目录结构应为 `/www/wwwroot/quizapp/backend/app/main.py`

## 第 5 步：写生产配置（宝塔文件管理）

在 `/www/wwwroot/quizapp/backend/` 新建 `.env`，参照 `.env.production.example` 填写，关键字段：

```ini
APP_ENV=production
DEBUG=false
APP_TIMEZONE=Asia/Shanghai
WX_MOCK_LOGIN=false
WX_APPID=wxaec3bef13eea7842
WX_SECRET=你的AppSecret
SECRET_KEY=（至少32位随机串，本地 openssl rand -hex 32 生成）
LLM_API_KEY=重新生成的DeepSeek模型Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
LLM_MAX_TOKENS=4096
DATABASE_URL=mysql+pymysql://quizapp:数据库密码@127.0.0.1:3306/quizapp?charset=utf8mb4
PUBLIC_BASE_URL=https://api.quizapp.chat
ALLOWED_ORIGINS=https://servicewechat.com
UPLOAD_DIR=/www/wwwroot/quizapp/uploads
MAX_ACTIVE_GENERATION_TASKS=2
MAX_CONCURRENT_GENERATION_TASKS=1
MAX_DAILY_GENERATION_TASKS=10
MIN_GENERATION_INTERVAL_SECONDS=30
GENERATION_TIMEOUT_SECONDS=1800
# 文本分块：块过小会让 LLM 调用次数成倍增加，出题极慢（默认 1500 字/块）
GENERATION_CHUNK_SIZE=1500
GENERATION_CHUNK_OVERLAP=150
GENERATION_CHUNK_CONCURRENCY=3
MAX_DOCX_ENTRIES=2000
MAX_DOCX_TOTAL_UNCOMPRESSED_MB=100
MAX_DOCX_SINGLE_ENTRY_MB=20
MAX_DOCX_COMPRESSION_RATIO=200
MAX_PDF_PAGES=300
MAX_EXTRACTED_TEXT_CHARS=1000000
```

⚠️ 注意：`validate_runtime_security()` 会校验这些字段，任何一项不合格服务会拒绝启动——这是故意的，照报错改即可。
数据库密码如果包含 `@`、`:`、`/`、`#` 等 URL 特殊字符，必须先进行百分号编码再写入 `DATABASE_URL`。
本部署步骤默认使用与小程序隐私声明一致的 DeepSeek。切换到 WienerAI 或其他兼容模型前，必须先确认服务商运营主体，更新小程序隐私页和微信后台《用户隐私保护指引》，再按 [`custom-llm.md`](custom-llm.md) 修改配置。模型地址必须填 API 根地址，不要填完整的 `/chat/completions`；生产环境只接受 HTTPS。

## 第 6 步：Python 项目管理器启动后端

1. Python 项目管理器 → 添加项目：
   - 项目路径：`/www/wwwroot/quizapp/backend`
   - Python 版本：3.11（没有就先在管理器里装）
   - 启动方式：**命令行启动**，命令（Python 可执行文件由宝塔所选环境提供）：
     ```
     uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1
     ```
   - 端口 `8000`
2. 先在管理器里为本项目创建虚拟环境并安装精简生产依赖：`pip install -r requirements-prod.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
3. 启动后验证：SSH 或宝塔终端执行
   ```bash
   curl http://127.0.0.1:8000/health
   ```
   返回正常 JSON 即成功（首次启动会自动建表）。**8000 端口不要对外放行**，只走 Nginx。

## 第 7 步：备案通过后建站 + 反向代理 + SSL（核心步骤）

1. 宝塔 → 网站 → 添加站点：域名 `api.quizapp.chat`，纯静态，不建数据库
2. **SSL**：站点设置 → SSL → Let's Encrypt → 勾选域名 → 申请（免费，自动续期）；申请成功后开启"强制 HTTPS"
3. **反向代理**：站点设置 → 反向代理 → 添加：目标 URL `http://127.0.0.1:8000`，发送域名 `$host`
4. **先安装限流共享区（关键）**：将 [`docs/nginx/baota-http-rate-limit.conf`](nginx/baota-http-rate-limit.conf) 保存为 `/www/server/nginx/conf/quizapp-rate-limit.conf`，并在 `/www/server/nginx/conf/nginx.conf` 的 `http { ... }` 内加入 `include /www/server/nginx/conf/quizapp-rate-limit.conf;`。`limit_req_zone` 不能放进站点 `server` 块。

5. **改代理配置（关键）**：完整的宝塔直部署配置以 [`docs/nginx/baota-quizapp-backend.conf`](nginx/baota-quizapp-backend.conf) 为准，对应服务器文件为 `/www/server/panel/vhost/nginx/python_quizapp-backend.conf`。该配置使用 `127.0.0.1:8000`，不要使用 Docker 配置中的 `backend:8000`。在 `server` 块中至少确认/加入：

```nginx
    # 上传 50MB 文档，留余量
    client_max_body_size 60m;

    # SSE 出题进度：必须关缓冲，否则进度条卡住不动
    location ~ ^/api/task/[^/]+/sse$ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
```

   普通 API 不使用 WebSocket，必须删除宝塔自动生成的 `proxy_set_header Upgrade $http_upgrade;` 和 `proxy_set_header Connection "upgrade";`，消除无效的连接升级并降低连接复用异常风险。

6. 修改前先备份现有配置：
   ```bash
   sudo cp /www/server/panel/vhost/nginx/python_quizapp-backend.conf /www/server/panel/vhost/nginx/python_quizapp-backend.conf.bak
   ```
   然后在宝塔“配置文件”中按模板修改并保存，最后验证并重载：
   ```bash
   sudo /www/server/nginx/sbin/nginx -t
   sudo /www/server/nginx/sbin/nginx -s reload
   curl -i https://api.quizapp.chat/health
   ```
   `nginx -t` 失败时不要重载，先用 `.bak` 文件恢复。`/health` 必须返回 HTTP 200 和正常 JSON；随后再进行小程序体验版验证。

7. 宝塔“网站监控报表”会给站点注入 `site_total.conf`。当前版本若反复重写全局日志格式并每 5 分钟 reload Nginx，会造成真机请求偶发断开。该功能不是本项目必需能力，应在宝塔中关闭；关闭后确认：
   ```bash
   systemctl is-active site_total
   test -f /www/server/site_total/stop_always.txt
   ls /www/server/panel/vhost/nginx/extension/quizapp-backend/
   ```
   预期服务为 `inactive`、停止标记存在，且扩展目录内没有 `site_total.conf`。不要用计划任务反复删除文件；应通过宝塔开关关闭，必要时先备份再处理残留扩展配置。

## 第 8 步：备案通过后完成小程序后台配置

1. mp.weixin.qq.com → 开发管理 → 开发设置 → 服务器域名：
   - request 合法域名 + uploadFile 合法域名都填 `https://api.quizapp.chat`（**每月限改 5 次**）
2. 微信客户端真机体验版测试全流程：登录 → 上传出题 → 刷题 → 错题本
3. 提审前确认：AIGC“AI 生成”标识已加；《用户隐私保护指引》明确列出实际使用的 AI 服务商完整主体、Jina Reader，以及启用时使用的 MinerU

## 上线前后运维清单

- [ ] 上线前配置数据库定时备份：宝塔 → 计划任务 → 添加“备份数据库 quizapp”，每天一次，保留 7 份，并执行一次恢复演练
- [ ] 上线前运行 README 中的后端与小程序自动化测试，记录对应 Git 提交号
- [ ] 生产虚拟环境执行 `python -m pip check`，结果必须为 `No broken requirements found`
- [ ] `backend/.env` 权限为 `600`，且 `.env`、数据库、`uploads/` 均未进入 Git 或发布压缩包
- [ ] 备案号挂在 privacy/关于页；30 日内做公安联网备案
- [ ] 观察内存：生产环境保持 `MAX_CONCURRENT_GENERATION_TASKS=1`；若仍频繁使用 swap，再评估扩容或调整 MySQL

---

## 常见问题速查

| 症状 | 原因 |
|---|---|
| 后端启动报配置校验失败 | `.env` 某项不合规，按报错改（SECRET_KEY 长度/SQLite/WX_SECRET） |
| SSL 申请失败 | 域名解析未生效，或 80 端口未放行 |
| 进度条卡住不动 | SSE location 没加 `proxy_buffering off` |
| 上传大文件 413 | `client_max_body_size` 未改 60m |
| 小程序请求失败但浏览器正常 | 域名没加进 request/uploadFile 合法域名，或用了 http 而非 https |
