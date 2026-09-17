# 智题学习笔记 - AI 刷题微信小程序

基于 OpenAI 兼容模型 + LangChain 自动从 PDF/Word/URL 生成题库，提供类驾考宝典的多模式刷题体验。

## 项目结构

```
question_to_test/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── main.py           # 应用入口
│   │   ├── config.py         # 配置（读 .env）
│   │   ├── database.py       # SQLAlchemy + 建表
│   │   ├── models/           # ORM 模型（题库/题目/用户/记录）
│   │   ├── schemas/          # Pydantic 请求/响应模型
│   │   ├── routers/          # API 路由（auth/upload/questions/practice）
│   │   ├── services/         # 业务逻辑（文档解析/AI 出题/答题）
│   │   └── utils/            # 工具（Jaccard 去重）
│   ├── requirements.txt
│   ├── .env.example          # 环境变量模板
│   └── run.py                # 启动脚本
└── miniapp/          # 微信小程序前端
    ├── app.js / app.json / app.wxss
    ├── pages/
    │   ├── index/            # 首页：题库列表
    │   ├── upload/           # 上传文档/URL
    │   ├── generating/       # AI 出题进度
    │   ├── bank-detail/      # 题库详情 + 模式选择
    │   ├── practice/         # 刷题页（顺序/随机/分类/错题/收藏）
    │   ├── exam/             # 模拟考试（倒计时+答题卡）
    │   ├── result/           # 考试结果
    │   ├── wrong-book/       # 错题本 + 收藏
    │   ├── profile/          # 个人统计
    │   └── manage/           # 题库管理（管理员）
    └── utils/request.js      # 网络请求封装
```

## 快速启动

### 后端

```bash
cd backend

# 1. 复制本地开发配置（默认 SQLite + mock 微信身份）
cp .env.example .env
# 需要测试 AI 出题时，再填写 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

# 2. 安装依赖
pip install -r requirements.txt

# 也可以构建虚拟环境进行安装
# conda create -n quizapp python=3.11
# conda activate quizapp
# pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

# 3. 启动（默认 SQLite，无需额外配置）
python run.py
# → http://127.0.0.1:8000
# → API 文档: http://127.0.0.1:8000/docs
```

### 上线前本地验证

从仓库根目录执行：

```bash
python -m unittest discover -s backend/tests -t . -v
python -m compileall -q backend
node miniapp/tests/app-auth.test.js
node miniapp/tests/review-flow.test.js
node miniapp/tests/upload-flow.test.js
```

后端测试使用标准库 `unittest`，不依赖 pytest。生产环境必须使用
`backend/.env.production.example` 配置真实微信、数据库、HTTPS 和 AI 密钥，不能复用本地 `.env`。

### 小程序

1. 用微信开发者工具打开 `miniapp/` 目录
2. 开发者工具中的开发版自动连接 `http://127.0.0.1:8000`；真机调试、体验版和正式版统一连接 `https://api.quizapp.chat`
3. 真机调试前确认生产域名已配置为 request/uploadFile 合法域名，然后编译预览

## 核心功能

| 功能 | 说明 |
|------|------|
| 文档解析 | PDF（MinerU API / PyPDF 降级）、DOCX（python-docx）、URL（Jina Reader）|
| AI 出题 | OpenAI 兼容模型双 Agent 并行生成直白题+逻辑题，Jaccard 去重 |
| 顺序练习 | 按题序作答，记录断点，下次续做 |
| 随机练习 | 随机抽题，碎片化学习 |
| 分类练习 | 按知识点标签筛题 |
| 模拟考试 | 限时作答 + 答题卡 + 交卷判分 |
| 错题本 | 自动记录错题，一键专项练习 |
| 收藏功能 | 练习时收藏难题，随时复习 |
| 学习统计 | 答题数、正确率、连续天数等 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `APP_NAME` | 产品显示名称 | 智题学习笔记 |
| `APP_TIMEZONE` | 业务自然日时区 | Asia/Shanghai |
| `JWT_ISSUER` | 登录令牌签发者技术标识，部署后保持稳定 | quizapp-api |
| `LLM_API_KEY` | OpenAI 兼容模型 API Key（生产必填） | — |
| `LLM_BASE_URL` | 模型 API 根地址，不包含 `/chat/completions`，生产必须 HTTPS | — |
| `LLM_MODEL` | 模型名称 | — |
| `LLM_TIMEOUT_SECONDS` | 单次模型请求超时（秒） | 60 |
| `LLM_MAX_RETRIES` | 单次模型请求最大重试次数 | 2 |
| `LLM_MAX_TOKENS` | 单次模型响应 token 上限 | 4096 |
| `DATABASE_URL` | 数据库连接 | SQLite（开发） |
| `MINERU_API_KEY` | MinerU PDF 解析（可选） | 无则用 PyPDF |
| `DEEPSEEK_*` | 旧部署兼容项，仅在三个 LLM 核心项均未配置时使用 | deepseek-chat |
| `WX_APPID` | 微信小程序 AppID（生产必填） | wxaec3bef13eea7842 |
| `WX_SECRET` | 微信小程序 AppSecret，仅保存在后端（生产必填） | — |
| `SECRET_KEY` | 应用登录 token 签名密钥，生产需至少 32 位随机值 | — |
| `AUTH_TOKEN_EXPIRE_DAYS` | 应用登录有效期（天） | 30 |
| `WX_MOCK_LOGIN` | 本地固定身份模拟登录，仅允许 development | true（示例配置） |
| `WX_MOCK_ADMIN` | mock 用户是否作为本地管理员 | true（示例配置） |
| `ADMIN_OPENIDS` | 管理员 OpenID 列表，多个值用英文逗号分隔 | — |
| `MAX_ACTIVE_GENERATION_TASKS` | 单用户 pending/running 任务上限 | 2 |
| `MAX_CONCURRENT_GENERATION_TASKS` | 单进程同时执行的 AI 任务上限 | 2 |
| `MAX_DAILY_GENERATION_TASKS` | 单用户每日 AI 生成任务上限 | 10 |
| `MIN_GENERATION_INTERVAL_SECONDS` | 同一用户两次生成请求的最短间隔（秒） | 30 |
| `MAX_PDF_PAGES` | 单个 PDF 最大页数 | 300 |
| `MAX_EXTRACTED_TEXT_CHARS` | 单份资料最大提取字符数 | 1000000 |
| `GENERATION_TIMEOUT_SECONDS` | 单个 AI 出题任务总超时（秒） | 1800 |
| `GENERATION_CHUNK_SIZE` | 文本分块大小（字符），越小 LLM 调用次数越多 | 1500 |
| `GENERATION_CHUNK_OVERLAP` | 相邻分块重叠字符数 | 150 |
| `GENERATION_CHUNK_CONCURRENCY` | 单个任务内并行处理的段落数 | 3 |

自定义模型配置、HTTPS 要求和宝塔重启步骤见
[`docs/custom-llm.md`](docs/custom-llm.md)。

## 微信登录流程

1. 小程序启动时先使用本地 token 请求 `GET /api/auth/me`；无有效 token 时停留在登录页，等待用户点击微信登录按钮。
2. 小程序获取一次性临时 code，并发送到 `POST /api/auth/login`。
3. 后端使用 `WX_APPID`、`WX_SECRET` 和 code 请求微信 `code2Session`，openid 和 session_key 不下发给小程序。
4. 后端按 openid 查找或创建用户，并签发有过期时间的应用 Bearer token。
5. 登录成功后所有用户直接进入首页；头像和昵称只在个人中心按需完善，不是登录前置条件。
6. 受保护请求统一携带 `Authorization: Bearer <token>`；遇到 401 时清理会话并回到登录页，主动退出会让服务端立即撤销 token。
7. 用户主动退出会清除本机 token，下一次进入登录页后再次点击微信登录按钮。

完整的能力边界、接口约定和上线检查见 [微信小程序登录方案](docs/wechat-login.md)。

题库删除采用创建者/管理员权限和软删除策略，详细约定见 [题库删除方案](docs/bank-deletion.md)。

本地联调若暂时没有可用的微信配置，可在 `.env` 设置
`APP_ENV=development` 和 `WX_MOCK_LOGIN=true`。mock openid 是固定值，避免每次登录创建新用户；生产环境启动时会强制拒绝 mock 登录、空微信密钥或弱 `SECRET_KEY`。

## 生产部署

当前生产环境采用阿里云服务器上的宝塔 Nginx + MySQL + Python 项目管理器，
不是 Docker。以 [宝塔上线操作手册](docs/server-deploy-steps.md)、
[Nginx http 级限流配置](docs/nginx/baota-http-rate-limit.conf) 和
[Nginx 站点配置模板](docs/nginx/baota-quizapp-backend.conf) 为准：

- 后端只监听 `127.0.0.1:8000`，公网仅开放 HTTPS 443（以及证书续签所需的 80）。
- 生产配置从 `backend/.env.production.example` 创建，禁止把本地 `.env` 上传或提交。
- 源文档保存在服务器 `uploads/`，Nginx 不直接暴露该目录；仅头像目录由应用按需提供。
- 微信后台的 request 与 uploadFile 合法域名都配置为 `https://api.quizapp.chat`。
