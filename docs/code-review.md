# 智题学习笔记上线前 Code Review 报告

> 初审时间：2026-09-14 · 复审时间：2026-09-15 · 范围：backend/ 全部 Python 源码 + deploy/ 部署文件 + miniapp/ 全部页面
> 说明：第 17-42 行保留初审问题记录；其中 #1-#4 已在复审中修复。当前是否可提审，以文末“当前上线前置条件”和复审结果为准。

---

## ✅ 先说做对了的（不用动）

- **生产配置自校验**：`config.py` 的 `validate_runtime_security()` 会强制校验 SECRET_KEY 强度、禁 mock 登录、禁 SQLite，配错直接拒绝启动——相当于内置部署检查清单
- **安全基础扎实**：JWT 鉴权覆盖完整、上传有类型/大小校验、SSRF 有防护、openid 不下发前端
- **小程序端工程质量好**：统一请求封装、401 静默换 token、隐私授权回调（`onNeedPrivacyAuthorization`）、考试结果走 storage 传参都是正确做法
- **baseUrl 已配好**：`app.js` 正式环境已是 `https://api.quizapp.chat`，无占位符残留

---

## 🔴 阻塞上线（必须修复）

### 1. 【后端·安全】`.dockerignore` 缺失，真实密钥会被打进镜像
- **位置**：`backend/Dockerfile:9`（`COPY . .`），backend 目录下无 `.dockerignore`
- **问题**：本地带真实密钥的 `backend/.env`（WX_SECRET、DEEPSEEK_API_KEY、SECRET_KEY）会被复制进镜像层，拿到镜像即可提取全部密钥
- **修复**：新建 `backend/.dockerignore`，至少包含 `.env`、`uploads/`、`tests/`、`__pycache__/`

### 2. 【后端·稳定性】AI 出题任务同步阻塞事件循环，任务期间整站无响应
- **位置**：`backend/app/services/question_service.py:451`（`run_generate_task`）
- **问题**：async 函数内部全是同步阻塞调用（`db.commit()`、`parse_word`、PDF 解析）。出题任务执行期间，`/health`、SSE、所有接口全部卡死——**单 worker 架构下等于整站不可用**
- **修复**：解析与 DB 重操作用 `asyncio.to_thread()` 包裹；或把整个任务体移入线程池

### 3. 【后端·稳定性】DeepSeek 调用无超时，失败被伪装成"成功"
- **位置**：`backend/app/services/ai_engine.py:23-30`（`ChatOpenAI` 未设 `timeout`/`max_retries`）；`generate_from_chunk:169-176`（异常返回 `[]` 后任务仍置 ready）
- **问题**：① DeepSeek 挂起时任务永久卡在 running（`recover_stale_tasks` 只在启动时跑一次）；② API key 错误导致全部 chunk 失败时，题库照样置 ready、0 道题，用户看到"生成成功"
- **修复**：`ChatOpenAI(timeout=60, max_retries=2)`；生成数为 0 时将 task 置为 failed

### 4. 【小程序·审核】AIGC 内容无标识（审核硬门槛）
- **位置**：`generating.wxml`、`practice.wxml`、`result.wxml` 等所有 AI 生成内容展示处
- **问题**：微信对 AIGC 类内容要求显著标识，目前全站没有任何"内容由 AI 生成"的角标或免责文案
- **修复**：生成完成页与解析区加"AI 生成 · 仅供参考"标识

### 5. 【后台配置·待确认】两项微信后台配置必须在提审前完成
- 《用户隐私保护指引》：声明头像昵称收集 + **上传资料交由第三方 AI 处理**的用途（不配则 chooseAvatar 被平台拦截）
- request/uploadFile 合法域名配置 `https://api.quizapp.chat`，并确认 ICP 备案号生效、证书有效

---

## 🟡 重要（建议上线前一并修复）

| # | 位置 | 问题 | 修复 |
|---|---|---|---|
| 6 | `upload.py:214-261` | SSE 进度轮询是同步 DB 查询，多用户同时看进度互相卡顿 | 同 #2 用 `to_thread` |
| 7 | `question_service.py:556-562` | `task.error` 把内部异常（路径/SQL 细节）原样下发前端 | 下发通用文案，详情进日志 |
| 8 | `question_service.py:133-152` | 错题查询有死代码且全量加载用户所有答题记录，越用越慢 | 删死代码，SQL 侧取最新 + LIMIT |
| 9 | `question_service.py:304/396` | 正确率读改写无锁，并发提交丢更新 | SQL 原子更新 |
| 10 | `ai_engine.py:264-268` | 标签分类未剥离 ```json 围栏，静默失败 | ✅ 已复用 `_parse_llm_output` 的剥离逻辑 |
| 11 | `upload.py` | 单用户可无限提交出题任务（刷 DeepSeek 费用 + 磁盘） | 限流：同时 pending/running ≤ 2 |
| 12 | `deploy/docker-compose.yml` | 首次部署时证书不存在，nginx 挂载 443 配置会 **crash loop**；acme-challenge webroot 未挂载，HTTP-01 签发 404 | 首次签发用仅 80 端口的最小 conf；conf 顶部已有说明但 compose 默认挂载，容易踩 |
| 13 | `deploy/docker-compose.yml` | backend 无 healthcheck；MySQL 无备份方案 | 加 healthcheck；补 mysqldump 定时备份到宿主机 |
| 14 | `utils/request.js` | 轮询失败每 1.5s 弹一次 toast（网络抖动 = toast 轰炸） | 增加静默请求选项，轮询调用传 silent |
| 15 | `utils/request.js` / `upload.js` | 请求无 timeout；上传 50MB 无大小校验、无进度提示 | 前端校验 file.size，用 uploadTask 显示进度 |
| 16 | `wrong-book.js:89-113` | 不筛选题库时，错题练习/背题只取第一个题库，其余静默丢弃 | 后端支持跨题库，或前端按题库分批 |
| 17 | `index.js` / `wrong-book.js` / `profile.js` | onLoad+onShow 双重加载（首次进页 6 个重复请求） | 数据加载统一放 onShow |
| 18 | `exam.js:76-86` | 最多 100 题全量 setData，首帧卡顿 | 完整列表存 `this._questions`，setData 只放当前题 |
| 19 | `index.js:50-51` | 分类快速切换有竞态，列表可能停留在旧分类 | ✅ 已增加请求序号校验，只应用最新响应 |

## 🟢 建议（不阻塞）

- `requirements.txt`：`faiss-cpu`/`numpy`/`redis`/`sse-starlette` 未被代码使用，可瘦身镜像
- `tags.contains()` 未转义 LIKE 通配符（非 SQL 注入，仅匹配异常）
- 头像旧文件不删除，avatars 目录会无限增长
- `wx.getSystemInfoSync`（`app.js:28`）已废弃，换成 `wx.getWindowInfo()`
- `project.config.json`：`ignoreUploadUnusedFiles: false`，tests 目录会被打进包体
- `upload.wxml:72` `input type="url"` 非法，✅ 已改为 `type="text"`
- `manage.wxml:37` `data-q="{{item}}"` 序列化整题对象，改传 index
- 生产建议 uvicorn 加 `--proxy-headers`（头像 URL 生成场景）
- 无登录/上传限流，nginx 层补 `limit_req`

---

## 建议的修复顺序

```
第一批（半天，全是小改动）：
  #1 .dockerignore → #3 LLM 超时+失败置 failed → #4 AIGC 标识 → #7 错误文案
第二批（一天）：
  #2/#6 异步化 to_thread → #12 首次部署证书顺序 → #14/#15 前端请求体验
第三批（上线后一周内）：
  #8/#9 查询与并发 → #11 任务限流 → #13 备份 → 其余 🟡
同时人工确认：#5 两项微信后台配置 + 体验版真机全链路回归
```

## 总体结论

代码底子是好的，后端鉴权、输入校验和生产自校验已达到灰度上线基础。当前代码本身没有发现新的高危阻断，但生产发布仍受外部条件约束：域名/DNS/HTTPS、微信后台合法域名与隐私指引、生产 MySQL 迁移和备份、AI 内容安全策略，以及 Docker/真机链路验证必须在发布前完成。

## 当前上线前置条件

1. `api.quizapp.chat` 完成 DNS A 记录和 HTTPS 证书部署，`/health` 返回 200。
2. 微信后台配置 request/uploadFile 合法域名、隐私保护指引、备案信息，并用体验版真机验证一键登录、头像、文件选择和上传。
3. 生产 `.env` 使用真实微信凭证、DeepSeek Key、随机 `SECRET_KEY`、MySQL 连接；执行三份 MySQL migration，完成备份和恢复演练。
4. 接入微信 `msgSecCheck` 或等价内容安全审核，或在提审前明确人工审核和下架流程；当前页面提示不等于内容审核。
5. 本机 Docker 不可用时，必须在部署主机执行镜像构建、Compose 启动、Nginx/证书联调和回滚演练。

## 2026-09-15 复审结果

本轮已修复并回归验证：Docker 构建上下文排除 `.env` 和上传目录；AI 客户端超时/重试、零题目失败、标签 JSON 容错、任务并发/分块/题量上限；考试未答题按错题提交、提交失败恢复计时；任务错误不再向前端暴露原始异常；数据库健康检查和生产 OpenAPI 关闭；文档解析移出事件循环；头像内容校验、旧文件清理和注销任务终止；上传进度与轮询静默错误；答题统计原子更新；随机刷题分页稳定去重；错题查询数据库侧取最新记录；管理员编辑对象传递和跨题库练习提示；生成、练习、考试结果页增加 AI 内容提示；分类切换竞态修复；个人中心增加本地缓存清理入口；根项目配置明确指向 `miniapp/`。

自动化结果：后端 `30/30` 个 unittest、认证回归、随机分页回归、Python 编译、17 个小程序 JS 运行时代码语法、86 个 WXML 事件绑定、全部 JSON/页面契约、`pip check` 均通过。Docker 未安装，无法在本机执行镜像构建或 Compose 启动；微信开发者工具 RPC、真机登录、生产域名/DNS/HTTPS、DeepSeek/MinerU 实际调用仍需上线环境人工验证。
