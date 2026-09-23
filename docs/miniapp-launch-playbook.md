# 微信小程序从零到上线完全手册

> 沉淀自「智题学习笔记」（quizapp.chat）2026-09 完整上线过程，供下一个小程序项目参考。
> 本手册默认场景：**个人主体小程序 + 自建后端（FastAPI/Python）+ 云服务器（宝塔面板）**。

---

## 一、资质与账号（第 1 天就能做，免费）

1. 到 [mp.weixin.qq.com](https://mp.weixin.qq.com) 注册小程序账号（个人主体免费）
2. 注册后拿到 **AppID / AppSecret**（填入后端 `.env`）
3. 个人主体的限制，规划功能时就要避开：
   - ❌ 不能开通支付、❌ 不能用 `getPhoneNumber` 手机号快捷登录
   - ❌ 不能选「教育」等需资质的服务类目 → 选 **工具-效率 / 工具-信息查询**
   - ❌ 不做 UGC（社区/评论/排行榜）——审核负担远超收益
4. 命名规范（见 4.3 命名章节）：
   - 个人备案网站名 ≥4 个汉字、中性词，**禁用**：教育/培训/商城/交易/官网/科技/中心/系统 等
   - 小程序名按公式 **品牌词 + 功能描述**（如「智题学习笔记」），纯功能词（"刷题助手"）会被判通用词驳回

## 二、域名与备案（周期最长，第一时间启动）

### 2.1 域名购买
- 阿里云/腾讯云注册，`.chat`/`.xyz`/`.top`/`.com` 等工信部批复后缀均可备案
- 实名认证后确认**距到期 > 45 天**（备案硬性要求）

### 2.2 两件备案必须同时办（最容易漏第二件）

| | 办理入口 | 作用 | 周期 |
|---|---|---|---|
| ① 网站 ICP 备案 | 云厂商备案系统（如 beian.aliyun.com） | 域名才能作为小程序请求域名 | 3~22 个工作日 |
| ② 小程序备案 | MP 后台 → 设置 → 基本设置 | 2023 年起强制，不备案无法上架 | 1~20 个工作日 |

### 2.3 ICP 备案关键填写项
- 硬性前提：**中国内地节点、包年包月 ≥3 个月**的服务器（按量付费/试用机没有备案资格）
- 主办者信息与身份证完全一致；通信地址精确到门牌号；手机号必须是本人实名号
- 网站内容/服务类型选「其他」，**不要选教育类**（触发前置审批，个人拿不到文件）
- 网站备注模板：「为微信小程序 XX 提供后端接口服务，包含 XX 功能；不提供新闻、出版、教育等需前置审批的信息服务」
- 🔴 **工信部 12381 短信必须在 24 小时内点链接核验**，超时自动驳回（最高频驳回原因）
- 备案期间 80/443 **不能开站**，此期间用 `IP:端口` 联调
- 备案成功后 **30 日内**做公安联网备案（beian.mps.gov.cn）

## 三、服务器选购与初始化

- 1G 内存实践结论：
  - **MySQL 选 5.7 不选 8.0**（8.0 启动即吃 400MB）
  - **不用 Docker 全家桶**（MySQL+Redis+Nginx 容器会吃满内存），全用宝塔自带组件
  - **先加 1G swap 兜底**：
    ```bash
    sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    ```
  - 依赖安装用精简清单（剔除未使用的 faiss/numpy 等重包；保留轻量的 Redis/ARQ 客户端）
- 系统自带 Python（如 3.6）**绝对不能动**（宝塔面板跑在上面），项目用 Python 在「python环境管理器」里单独装 3.11

## 四、宝塔面板配置清单

### 4.1 软件安装
- 软件商店装：**Nginx**（极速安装）+ **MySQL 5.7** + **Redis** + **python环境管理器**（新版宝塔老"Python项目管理器"仅支持 CentOS 7）
- Redis 仅监听 `127.0.0.1`，设置强密码、`maxmemory 128mb` 和 `noeviction`，不要放行 6379
- Python 3.11 在管理器内源码编译安装（2核1G 约 5~20 分钟），自定义参数留空
- 初始化推荐配置弹窗**不要一键安装 LNMP/Docker**，手动逐个装

### 4.2 防火墙双层结构（都要放行）
1. **阿里云控制台 → 轻量服务器 → 防火墙**：放行 80、443、8888（面板）
2. **宝塔 → 安全**：同步放行
3. 8000 等后端端口**不对公网开放**，只走 Nginx 内部转发

### 4.3 建数据库
- 名称/用户名、字符集 **utf8mb4**、访问权限「本地服务器」
- 常见坑：新装 MySQL 报「root 用户连接失败」→ 数据库页顶部「root密码」重置提交后再建库

## 五、后端部署（以 FastAPI 为例）

### 5.1 上传代码
- 只传 `backend/` 目录；打包前排除 `.env`（本地配置）、`uploads/` 内容、`__pycache__`、本地 SQLite 文件
- 目标路径示例：`/www/wwwroot/<项目名>/backend/app/main.py`
- SSH 解压权限问题：`/www/wwwroot` 归 root，需 `sudo tar -zxf`，最后 `sudo chown -R www:www /www/wwwroot/<项目名>`

### 5.2 生产 `.env` 必填项（逐项检查）
```ini
APP_ENV=production
DEBUG=false
SECRET_KEY=<openssl rand -hex 32 生成>          # 强度有自校验，不够拒绝启动
DATABASE_URL=mysql+pymysql://用户:密码@127.0.0.1:3306/库名?charset=utf8mb4
WX_APPID=... / WX_SECRET=... / WX_MOCK_LOGIN=false
LLM_API_KEY=...                                 # 使用未泄露的新密钥
LLM_BASE_URL=https://服务商域名/v1              # 填 API 根地址，生产禁止 HTTP
LLM_MODEL=...                                   # 与服务商模型 ID 完全一致
UPLOAD_DIR=<宝塔路径>/uploads                    # 目录需手动创建并 chown www:www
ALLOWED_ORIGINS=https://api.xxx.com             # 逗号分隔字符串
GENERATION_QUEUE_MODE=arq
REDIS_URL=redis://:URL编码后的密码@127.0.0.1:6379/0
ARQ_QUEUE_NAME=quizapp:generation
```
- **.env 里不要写行内注释**（`KEY=value # 注释` 的解析器兼容性风险，全部删掉）
- 生产 .env 归属改为 `www:www`（程序以 www 用户运行）
- 好的实践：后端写一个 `validate_runtime_security()`，生产模式强制校验密钥强度/禁 mock/禁 SQLite，配置错误直接拒绝启动

### 5.3 添加 Python 项目（宝塔 网站 → Python项目）
- 项目路径 `/www/wwwroot/<项目名>/backend`
- 启动命令：`uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1`
- 另建一个常驻 Worker：`python -m arq app.worker.WorkerSettings`，使用相同目录、虚拟环境和 `.env`
- 依赖包路径指向精简版 `requirements-prod.txt`
- 验证：API/Worker 均为「运行中」+ `/health` 返回 `database: ok`、`queue: ok`
- 数据表由 SQLAlchemy `create_all` 自动建；`migrations/*.sql` 只给已有数据升级用

## 六、域名解析 + HTTPS + 反向代理

### 6.1 解析
- 阿里云解析 → 添加记录：主机记录 `api`、类型 A、记录值 服务器公网 IP（用精确子域，不用 `*` 泛解析）
- 本地验证：`nslookup api.xxx.com`

### 6.2 宝塔 11 的正确路径（踩坑总结）
- 网站页按类型分标签：**静态站 = HTML项目；后端 = Python项目**
- ✅ 实践结论：**域名绑在 Python项目 上**（域名管理添加 → 外网映射开关打开 → 代理路由 `/`、代理端口 8000 → SSL 标签申请证书 → 部署 → 强制 HTTPS）
- ❌ 不要用顶部独立「反向代理」标签给已建站点加域名（会报"网站已存在"）
- ❌ HTML项目 设置里没有「反向代理」标签；Python项目设置里才有「外网映射」
- HTML 空壳站点建了要删，否则占用域名冲突

### 6.3 Nginx 必改三处（不改必出问题的经验）
1. **上传大小**：`client_max_body_size 60m;`（按上传上限+余量）
2. **SSE/流式接口关缓冲**，否则进度条永远卡住——`location /` 之前插入：
   ```nginx
   location ~ ^/api/task/[^/]+/sse$ {
       proxy_pass http://127.0.0.1:8000;
       proxy_http_version 1.1;
       proxy_set_header Connection "";
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_buffering off;
       proxy_cache off;
       proxy_read_timeout 3600s;
   }
   ```
3. **普通接口放宽超时**：AI/长任务类接口 `proxy_read_timeout 300s` 起（宝塔默认 60s 会掐断）
- ⚠️ 编辑 Nginx 配置时**新 location 是插入一个完整块（花括号成对）**，不是改原有 `location /` 那一行——改错会导致全站 404

### 6.4 SSL
- Let's Encrypt 免费证书，有效期 **3 个月**，宝塔自动续签
- 申请（文件验证）→ **部署**（不部署 443 不生效，页面还是报"未开启SSL"）→ 开**强制 HTTPS**
- 验证标准：浏览器 `https://api.xxx.com/health` 出现锁标 + JSON

## 七、小程序端上线配置

1. **服务器域名**（MP 后台 → 开发管理 → 开发设置，**每月只能改 5 次**）：
   - request 合法域名：`https://api.xxx.com`（**末尾不要带分号**）
   - uploadFile 合法域名：同上
   - socket/downloadFile/udp/tcp：用不到就留空
2. **《用户隐私保护指引》**（不配提审大概率被拒）：声明昵称、头像、做题记录、上传文档（注明交由第三方 AI 处理）
3. **app.js baseUrl 配置**：
   ```js
   baseUrl: 'https://api.xxx.com'  // 开发者工具、真机、体验版和正式版统一走线上 HTTPS
   ```
   本机未启动后端时不要加入 `127.0.0.1` 的自动覆盖逻辑；需要本地后端联调时再临时修改，并在提交前恢复线上域名。
4. **登录方案**：wx.login → code2Session（后端换 openid）→ 自签 JWT → 401 静默重登，全程无感。不要透传 session_key，AppSecret 绝不进前端
5. **AIGC 标识**：所有 AI 生成内容展示处加「AI 生成 · 仅供参考」角标（审核硬要求）
6. 真机调试 Console 里 `[广告调试]`、`backgroundfetch privacy fail` 红字是微信框架噪音，无视

## 八、上线前 Code Review 检查清单（阻塞项）

部署/提审前逐条核对，全部 ✅ 才继续：

- [ ] `.dockerignore`/打包排除项存在，密钥不进镜像/压缩包
- [ ] 异步任务不阻塞事件循环（同步重操作 `asyncio.to_thread` 包裹 + 并发限制 + 总超时）
- [ ] LLM 客户端有 `timeout` + `max_retries`；生成失败/空结果置 failed 而非"成功 0 题"
- [ ] 对外错误信息脱敏（不含服务器路径/SQL 细节）
- [ ] AI 生成内容有标识
- [ ] **账号注销接口**（软删除+吊销 token+清理文件）——合规刚需
- [ ] 上传：前端+后端双重校验（类型/大小），存储目录不对外
- [ ] 前端 baseUrl 各环境正确
- [ ] 用户隐私保护指引已提交
- [ ] 合法域名已配置且与代码一致

## 九、发布流程

1. 开发者工具「上传」→ MP 后台版本管理 → 设为体验版 → 真机全流程回归（登录/核心功能/注销）
2. 提交审核：类目选工具类；准备功能介绍+页面截图；说明测试方式（免登录则写"扫码即用"）
3. 审核被拒会告知原因，改完重提即可
4. 发布后待办：公安联网备案（30 日内）、网站页脚悬挂 ICP 备案号、证书续期监控

## 十、本次踩坑速查表

| 坑 | 解法 |
|---|---|
| 12381 短信超 24h 未核验 | 驳回重提，看到初审通过立刻查短信 |
| 备案网站名含"题/教育"味 | 用中性词（智题学习笔记），类目选工具不选教育 |
| 宝塔老 Python 插件装不上 | 装「python环境管理器」，走 网站→Python项目 |
| MySQL root 连接失败 | 面板「root密码」重置 |
| tar 解压 Permission denied | `sudo tar` + `chown -R www:www` |
| 模型 Key 无效或疑似截断 | 在服务商后台重新生成，并核对 `LLM_API_KEY` 完整值 |
| .env 行内注释 | 全部删除 |
| 反代后 404 | location 块被误改/未插入完整块；根路径本就无路由，测 `/health` |
| 证书申请了但 https 不通 | 忘点「部署」 |
| SSE 进度卡住 | `proxy_buffering off` |
| 开发者工具或真机连不上后端 | 确认 baseUrl 为线上 HTTPS 域名，并同时配置 request/uploadFile 合法域名 |
| 轮询/SSE 失败 toast 轰炸 | 失败提示做静默重试+次数上限 |

---

*最后更新：2026-09-17 · 智题学习笔记上线记录*
