# 代码整体评审报告（2026-09-29）

评审范围：`backend/`（FastAPI + SQLAlchemy + arq，~4700 行 Python）、`miniapp/`（13 个页面 + 全局 + 自定义组件 + 4 套测试）。
方法：全量只读评审 + 关键结论人工复核（复核项见文末）。未修改任何文件。

---

## 一、总体评价

**后端：成熟度明显高于普通个人项目。** 出题流水线做成了「批次状态机 + 断点续跑 + 每批单事务 + `SELECT ... FOR UPDATE` 串行化」，有幂等/回滚/恢复的专项测试背书；鉴权、上传校验、限流、时区处理成体系，生产配置 fail-fast 校验到位。**未发现 P0 级问题**（无鉴权绕过、无注入、无远程执行）。主要短板是**数据量增长后的全量拉取与 N+1 查询**，以及 SSE 长连接缺少并发/时长护栏——在 2 核 1G 机器上会被放大。

**小程序：中等偏上。** 网络层、登录状态机、弱网诊断有明确设计意图，`share.js` 的合规取舍正确，4 套单测覆盖了关键分支。**最突出的问题是页面级错误态缺失**：多个页面 `catch` 后既不置 `error` 也不置 `done`，模板无分支命中 → 白屏或永久转圈。其次是登录态失效（401）后**页面级 `loggedIn` 不同步**，界面继续显示已登录。

**总体结论：可以继续上线运营，但建议优先修 8 个 P1**（下方「修复路线图」第一批），它们都是「弱网/数据增长后必现」的问题。

---

## 二、P1（建议尽快修）

| # | 位置 | 问题 | 影响 | 建议 |
|---|---|---|---|---|
| B1 | `services/question_service.py:359-424` | `get_user_stats` 全量 `.all()` 拉取 `answer_records.answered_at` 与全部 `UserProgress`，再在 Python 里算连续打卡 | `/api/stats`、`/api/study-report` 随使用时间线性变慢、内存上涨 | 连续打卡改 `GROUP BY DATE(...)` 聚合，或建 `user_stats` 汇总表 |
| B2 | `routers/upload.py:360-432` | SSE 进度端点无并发上限、无鉴权续期，单连接最长 3600s，每 1.5s `to_thread` 新建 Session 轮询 DB | 单账号可开多连接放大资源；1G 机器尤甚 | 加单用户/全局并发上限，降低轮询频率，设更短硬上限 |
| B3 | `services/generation_service.py:36-80, 96-105` | `recover_interrupted_tasks` 把 `running` 任务一并重排，而 `_begin_generation` 无条件把 running 批次重置为 pending | 当并发任务数 >1 时，重复投递的作业会让在途批次的落库 `return 0` 静默丢题，并重复消耗 LLM 配额 | 只重排 `pending`；或给批次加租约/执行者标识 |
| B4 | `services/ai_engine.py:22-31` | 每个文本块新建 `ChatOpenAI`（含两条 chain），全程不 `aclose()` | 单任务最多 100 块 × 2 次调用 + 100 次标签分类，连接/FD 持续累积 | 模块级缓存 LLM 实例，或任务结束时显式关闭 |
| F1 | `miniapp/pages/practice/practice.js:167-169` | `catch` 只置 `loading/loadingMore=false`；模板根节点受 `question`/`loading`/`done` 控制，此时三者全为假 | **首次加载失败整页白屏**，无提示无重试 | catch 里置 `loadError` 并渲染错误态 + 重试按钮 |
| F2 | `miniapp/pages/practice/practice.js:308-318` | 最后一题翻页失败时 `questions.length` 未增长 → 走 `done:true` | 网络抖动被误判「练习完成！」，后面几十题丢失 | 区分「加载失败」与「确实无更多」，失败时保留当前题并提示重试 |
| F3 | `miniapp/utils/request.js:37-43` | 401 只清全局会话 + toast；无任何页面监听 `needLogin`，页面 `onShow` 已把 `loggedIn` 置 true | 会话失效后界面仍显示已登录与陈旧数据，游客引导卡不出现，操作连续报错 | 增加 `sessionVersion` 广播，或各页 catch 里识别 `needLogin` 并重置 `loggedIn` |

---

## 三、P2（数据量/弱网/特定机型下会显现）

### 后端

| 位置 | 问题 | 建议 |
|---|---|---|
| `routers/practice.py:185` | `exam/submit` 循环内每题单独查 `Question`，最多 100 次 N+1 | 循环外已查好 `by_id`（142 行），直接复用 |
| `routers/practice.py:339-346` | `get_daily_question` 为选 1 题把整库 active 题（含 content/options）全量 `.all()` | 先 `count()` 再 `offset(k).first()` |
| `routers/questions.py:104-112` | `get_bank_detail` 为聚合标签加载全库题目完整行 | 只 `db.query(Question.tags)`（同文件 `get_bank_tags` 已是正确写法） |
| `routers/questions.py:239-246` | `mode=random` 带 seed 时全量入内存乱序；不带 seed 时 `ORDER BY RAND()` 全表 filesort，翻页会重复/漏题 | 幂等随机键排序 + keyset 分页 |
| `services/question_service.py:136-153` | `get_latest_answer_records` 的 `NOT EXISTS` 子查询只靠两个单列索引 | 加复合索引 `(user_id, question_id, answered_at, id)`；错题/收藏避免超大 `IN (ids)` |
| `services/dedup.py:9-45` | Jaccard 按「字符集合」比较中文题面，相似度普遍虚高，0.7 阈值判重不可靠，且忽略选项 | 改 2-gram/分词，或加独立质量校验 |
| `services/doc_parser.py:104-114` | 异步路径里同步 `open()` 读 50MB PDF（阻塞事件循环）；文档整份上传第三方 MinerU | `to_thread` 读取后 `content=` 传入；复核隐私披露 |
| `database.py:45-83` + `main.py:54` | 生产走 `create_all()`，而 001-005 是手写 SQL 人工执行，`alembic` 已装但未接线 | 接入 Alembic 强制 `upgrade head`，或启动时校验关键列 |
| `routers/upload.py:35,242,301` | `_generation_admission_lock` 是进程内锁，仅在单 worker 假设下闭合竞态 | 下沉到 DB 唯一约束/Redis 锁，或固化单 worker 并告警 |
| `services/generation_service.py:325-337` | 每批落库全量拉题干做 O(n²) 去重，`_claim_batch`/`_finalize` 反复全表 count | 内容哈希索引去重，或任务级缓存已存在题面 |
| `routers/auth.py:196-209` | 注销时仅对 `owned_bank_ids` 清 `source_text`，任务/批次行不删除 | 全量清空 + 纳入定期清理 |
| `routers/upload.py:262-278` | 入队失败直接置 failed + 删文件，无退避重试 | 有限重试或落库待重投，给用户明确失败态 |

### 小程序

| 位置 | 问题 | 建议 |
|---|---|---|
| `pages/generating/generating.json` + `.wxml:1-72` | 自定义导航，但 `pending/generating` 期间**没有任何可见返回入口** | 常驻返回/关闭按钮，或改回默认导航栏 |
| `utils/request.js:184-189` | `pollTask` 对所有错误一律静默退避，`needLogin`/404 也被吞；`maxWaitMs=30min` | 区分不可恢复错误，直接回调 `onError` |
| `pages/bank-detail/bank-detail.js:22-32` | `catch {}` 为空，`bank` 保持 null，模板是「有则渲染、否则 loading」 | **永久转圈** → 加失败标记 + 重试 |
| `pages/report/report.js:25-41` | 失败时 `report=null` 且 `loading=false`，两个分支都不成立 | **白屏** → 加 error 分支 |
| `pages/practice/practice.js:179-185` | `for (let skip=0;; skip+=pageSize)` 无上界死循环（同项目 `wrong-book.js:188`、`manage.js:115` 都有 `skip<10000` 看护） | 补同样的上界 |
| `app.js:155-165` | `wxLogin()` 在 `sessionRestorePromise` 存在时直接返回恢复阶段缓存用户，不执行 `wx.login()` | 显式登录入口传 `force: true` |
| `pages/exam/exam.js:104-145` | `startExam` 无重入保护（其他提交动作都有），双击会创建孤儿会话 | 加 `starting` 标志位 |
| `upload.wxss:113` + `upload.wxml:82`；`exam.wxss:55` + `exam.wxml:76` | `safe-bottom`（app.wxss:115）被页面级 `padding` 简写覆盖（页面样式后加载，同等特异性后者生效） | 直接写 `padding-bottom: calc(20rpx + env(safe-area-inset-bottom))` |
| `pages/manage/manage.js:74-85` | `deleteQuestion` 的 `showModal` 回调里 `await request` 无 try/catch | unhandled rejection → 补 try/catch |
| `utils/request.js:104-152` | 上传单次 `wx.uploadFile`、120s 超时、无分片无重试，而允许 50MB 文件 | 大文件分片或手动重试并保留已选文件 |
| `pages/index/index.js:33-40,88-90` | `onShow` 每次重置分页（翻到第 3 页切 tab 回来被打回）；`hasMore` 用 `banks.length === 20` 判定 | 区分首次进入与返回刷新；`hasMore` 与后端 total 比较 |
| `app.js:87-105` | `promptLogin` 登录后一律回首页，**丢失原始意图** | 用 `redirect` 参数或 storage 记录待办目标 |
| `pages/index/index.js:29` 等 3 处（待确认） | 直接用 `wx.getWindowInfo()`（需基础库 ≥2.20.1），无 `getSystemInfoSync` 兜底 | 加兜底，或确认后台「最低基础库版本」设置 |

---

## 四、P3（清理项，可合并到下次顺手做）

**后端**
- `main.py:51,65` 用已弃用的 `@app.on_event`，建议迁 `lifespan`
- `routers/upload.py:12` 未使用导入；`schemas/user.py:31` `WrongQuestionOut` 死代码
- `requirements*.txt` 中 `alembic`/`requests` 无引用
- `ai_engine.py:176-184` `return_exceptions=True` 外层再包 try/except → 死代码，掩盖异常语义
- `generation_service.py:567` 的 `start_index` 被后续 `next_order+index` 覆盖，参数无效易误导
- `config.py:307-308` 模块导入时 `os.makedirs`（import 副作用）
- `routers/auth.py:301-302` async 端点里同步写 5MB 头像，阻塞事件循环
- `doc_parser.py:100,165` f-string 日志可能带出上游响应体
- `question_service.py:432-436` shim 静默吞掉未知参数
- `question_service.py:359,400-407` 统计口径不一致（`total_answered` 含历史，`wrong_count` 仅当前可访问），未文档化

**小程序**
- `utils/request.js:21,37,128` `retried` 恒为 `false` → 401 重试分支是死代码
- `practice.js:351-365` `getOptionClass`/`isCorrectOption` 已被 `format.wxs` 取代，未使用
- `exam.js:331-335` `formatTime` 未使用；`exam.js:282` `time_spent` 恒为 0
- `app.js` 的 `isNewUser`/`profileRequired` 全项目只写不读
- `wrong-book.js:41-43` tabBar 页面读 `options.bank_id`（`switchTab` 不支持传参）→ 死代码
- `wrong-book.wxml:87-89` 收藏 tab 游客态无登录入口，与错题 tab 策略不一致
- `login.js:116-118` `setTimeout(1200)` 延迟导航，用户中途返回仍会执行
- `pages/privacy` 是全项目唯一没有分享函数的页面（与「全页面支持转发」目标不完全一致）
- `images/page/favorite.png`(355KB) 等 4 个小图标合计 ~470KB，占 `images/` 七成
- `app.js:1-27` 与 `utils/request.js:66-101` 的 errMsg 分类逻辑近乎重复，建议抽 `utils/net-error.js`
- `login.js:135` 直接调用 `app._setSession` 破坏封装
- 未使用参数 `shareApp(this)`、冗余 `getUserId()` 重复调用、`goDetail` 无防抖等

---

## 五、值得肯定

1. **出题流水线的并发与幂等设计扎实**：批次状态机 + 行锁串行化，重复投递已完成批次直接返回，有 `test_completed_generation_is_idempotent_on_redelivery` 等测试背书。
2. **会话未跨协程复用**：后台逻辑一律经 `db_factory` 在各线程内新建并 `close()`，避开了 SQLAlchemy Session 非线程安全的经典坑。
3. **安全基线专业**：生产 fail-fast 校验（SECRET_KEY/DEBUG/CORS/HTTPS/Redis 密码/SQLite）、JWT 自校验 alg/iss/exp + `compare_digest`、`token_version` 注销即失效、上传扩展名+magic+zip bomb 校验、URL DNS 内网校验、文件名 UUID 白名单。
4. **容错控制细致**：LLM 超时/重试/指数退避、双层 `asyncio.timeout`、配额持久化在 DB（非内存令牌桶），还专门修掉东八区把 30 秒限流变 8 小时的坑。
5. **小程序登录状态机真实有效**：`sessionVersion` 快照拦截过期回包、`loginPromise` 合并并发登录、`app-auth.test.js` 7 个用例覆盖域名/TLS/过期会话等分支。
6. **弱网诊断有诚意且注意隐私**：errMsg 翻译成可执行提示，日志前用正则脱敏 `wxfile://` 路径。
7. **游客态改造在代码层是干净的**：`requireSession` 只静默抛 `needLogin` 绝不跳转，有 `testGuestsBrowseWithoutForcedLogin` 守住红线。

---

## 六、修复路线图（建议顺序）

**第一批（P1，建议本周内）** — 都是「弱网/数据增长后必现」
1. F1/F2 练习页错误态与「假完成」修复（用户可感知最直接）
2. F3 401 后页面级登录态同步
3. B3 出题任务重排逻辑（防丢题 + 省 LLM 配额）
4. B4 复用 LLM 客户端（防连接泄漏）
5. B1 统计聚合改 SQL；B2 SSE 加护栏

**第二批（P2 高性价比）**
- 交卷 N+1、每日一题全量加载、`get_bank_detail` 全量行、随机模式分页（后端 4 处都是「改几行」）
- 小程序：generating 返回入口、bank-detail/report 错误态、`safe-bottom` 修正、`manage` try/catch、`startExam` 防重

**第三批（P3 清理）** — 建议随功能迭代顺手做，不必单开一轮

---

## 七、复核说明

以下结论已人工读码复核，确认属实：
- 练习页 `catch` 后无任何渲染分支命中（`practice.js:167-169` + `practice.wxml:2`(question) / `:101`(loading) / `:109`(done)）→ 白屏成立
- `report.wxml:1,54` 两个分支在失败时均不成立 → 白屏成立
- `bank-detail.wxml:83` 的 `loading-page wx:if="{{!bank}}"` 在失败时恒真 → 永久转圈成立
- `upload.wxss:107-114` 的 `padding: 20rpx 30rpx` / `exam.wxss:55` 的 `padding: 16rpx 20rpx` 覆盖 `app.wxss:115` 的 `safe-bottom` → 安全区失效成立
- `practice.py:142` 已构建 `by_id`，但 `:185` 循环内重复单题查询 → N+1 成立
- `practice.py:339-346` 全量 `.all()` 后取模 → 成立
- `ai_engine.py:22-31` 每次调用新建 `ChatOpenAI` 且无关闭 → 成立

以下依赖运行期行为，标注**待确认**：
- arq 对 in-progress job 的 `_job_id` 去重语义（B3 的风险程度取决于此；但代码本身未做防御）
- 微信后台「最低基础库版本」设置是否 ≥2.20.1（影响 `wx.getWindowInfo` 兜底必要性）
- `__usePrivacyCheck__` 字段在当前基础库是否仍需显式声明

---

## 八、当前工作区状态

- **未提交改动 16 个文件**：登录整改（`app.js`/`app.json`/`utils/request.js`/index/login/profile/wrong-book）+ 本次样式优化（游客卡、tabBar 底部留白）+ 2 个测试文件。评审结论：改动方向正确、无回归（4 套测试全绿），可提交。
- **`assets/app-icon/raw/` 4 张原图**（带「AI生成」水印）仍未跟踪，建议选定头像后删除。

---

## 九、修复进展（2026-09-29 同日，第一轮）

已修复并全部通过测试（后端 60→**62 tests OK**，小程序 4 套全绿，静态自检 0 悬空引用）：

| 编号 | 状态 | 修复方式 |
|---|---|---|
| F1 练习页白屏 | ✅ | `practice.js` 增加 `loadError` 状态与 `_describeLoadError()`；`practice.wxml` 增加失败态分支（重新加载 / 返回上一页） |
| F2 分页失败被误判「练习完成」 | ✅ | `nextQuestion` 在追加失败时置 `loadMoreError`，保留已加载题目并提示重试，不再走 `done:true` |
| F3 401 后页面登录态不同步 | ✅ | `app.js` 新增 `onSessionInvalid()` 广播（`clearSession()` 触发）；index/wrong-book/profile 订阅并在回调中 `_resetToGuest()` |
| B1 统计全量拉取 | ✅ | `get_user_stats` 连续打卡改「90 天窗口 → 必要时扩到 400 天」，只查 `answered_at` 单列；收藏只查 `starred_ids` 单列 |
| B2 SSE 无护栏 | ✅ | 每用户 2 / 全局 20 连接上限（超限 429）、轮询 1.5s→3s、硬上限 min(任务陈旧时间, 900s)，`finally` 归还名额 |
| B3 在途批次被重置导致静默丢题 | ✅ | `_begin_generation` 只接管「执行者已死」的批次（`_apply_stale_batch_takeover`）；`_finalize_generation` 在仍有 running 批次时不判完成；pipeline 改为循环（处理→接管→有限等待），新增配置 `GENERATION_TAKEOVER_WAIT_SECONDS` |
| B4 LLM 客户端泄漏 | ✅ | `ai_engine.get_llm` 按 temperature 复用；新增 `close_llm_clients()` 接到 API 与 worker 的 shutdown |
| P2 练习页 `_loadProgress` 无上界循环 | ✅ | 补 `skip < 10000` |
| P2 报告页白屏 / 题库详情永久转圈 | ✅ | 两页新增 `loadError` + `retryLoad` + 失败态 UI |
| P2 出题进度页无返回入口 | ✅ | `generating` 增加常驻返回按钮 |
| P2 `safe-bottom` 被页面 padding 覆盖 | ✅ | `upload.wxss` / `exam.wxss` 直接写 `calc(... + env(safe-area-inset-bottom))` |
| P2 交卷 N+1 | ✅ | `exam/submit` 复用已批量查好的 `by_id` |
| P2 每日一题全量加载 | ✅ | 改 `count()` + `offset().limit(1)` |
| P2 `get_bank_detail` 加载完整行 | ✅ | 只查 `Question.tags` 单列 |
| P2 `manage.deleteQuestion` 无 try/catch | ✅ | 补 try/catch |
| P2 `exam.startExam` 无防重入 | ✅ | 加 `_startingExam` 标志位 |

新增回归用例：
- 小程序 `testSessionInvalidationSyncsPagesToGuest`、`testPracticeLoadFailureNeverBlanksOrFakesDone`
- 后端 `test_live_running_batch_is_not_stolen_by_duplicate_delivery`、`test_stale_running_batch_is_taken_over_in_same_job`

**仍未修（留待后续）**：`dedup.py` 中文 Jaccard 不可靠、随机练习分页重复/漏题、Alembic 未接线、SSE 之外的 P2（上传分片、`promptLogin` 丢失原始意图、`hasMore` 判定、`wx.getWindowInfo` 兜底）与全部 P3 清理项。P3 中 `@app.on_event` 已弃用 API 仍在（迁移 lifespan 会影响启动钩子，建议与 Alembic 一起做）。
