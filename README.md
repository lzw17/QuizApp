# 智题宝 — AI 刷题微信小程序

基于 DeepSeek + LangChain 自动从 PDF/Word/URL 生成题库，提供类驾考宝典的多模式刷题体验。

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

# 1. 复制配置
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动（默认 SQLite，无需额外配置）
python run.py
# → http://127.0.0.1:8000
# → API 文档: http://127.0.0.1:8000/docs
```

### 小程序

1. 用微信开发者工具打开 `miniapp/` 目录
2. 修改 `app.js` 中 `globalData.baseUrl` 为本机 IP（如 `http://192.168.x.x:8000`）
3. 编译预览

## 核心功能

| 功能 | 说明 |
|------|------|
| 文档解析 | PDF（MinerU API / PyPDF 降级）、Word（python-docx）、URL（Jina Reader）|
| AI 出题 | DeepSeek 双 Agent 并行生成直白题+逻辑题，Jaccard 去重 |
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
| `DEEPSEEK_API_KEY` | DeepSeek API Key（必填） | — |
| `DATABASE_URL` | 数据库连接 | SQLite（开发） |
| `MINERU_API_KEY` | MinerU PDF 解析（可选） | 无则用 PyPDF |
| `DEEPSEEK_MODEL` | 模型名称 | deepseek-chat |

## 生产部署

- 后端：腾讯云 CVM + Nginx 反向代理，MySQL 替换 SQLite
- 小程序：在微信公众平台配置服务器域名白名单
- 文件存储：配置腾讯云 COS，替换本地 `uploads/` 目录
