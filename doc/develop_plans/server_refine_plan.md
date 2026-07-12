# 服务端独立化与客户端-服务端架构改造 — 开发计划

## 一、需求背景

当前 `backend` 与前端（Electron 客户端）一起启动：客户端启动时由主进程
（`client/src/main/index.js` 的 `startFastApiServer`）通过 `uv run uvicorn server:app`
自动拉起后端，二者生命周期绑定。这带来一个核心矛盾：**部分数据需要长期、持续地
采集与归档，服务端应当 7×24 常驻运行**，而客户端会频繁开关。

### 期望达成的效果

1. 客户端启动后能**立即显示标的列表**，尽量减少现场拉取数据。
2. 服务端 **7×24 运行**，持续记录并积攒行情数据到本地数据库；客户端请求某标的
   行情时，尽量命中本地缓存，减少现场拉取。
3. 当前在内网开发测试，使用一台 mac mini（`anna@192.168.50.7`）作为服务端运行。
4. 服务端需要一个**管理功能**：查看服务状态、管理数据缓存、查看客户端连接情况等。
   管理功能通过**客户端内嵌管理面板**提供给授权用户，而非独立的 Web SPA。
5. 未来可能上线乃至商业化，服务端需考虑**客户端鉴权**：不同账号按订阅等级，可用
   的数据、模型等有所不同。
6. Bot 系统（消息推送/通知）后期应迁移到服务端常驻运行，支持多用户订阅与独立推送。

---

## 二、现有架构分析

### 2.1 启动与耦合方式

| 组件 | 现状 |
|------|------|
| Electron 主进程 | `client/src/main/index.js`：`app.whenReady` 时调用 `startFastApiServer()` 自动拉起后端；`window-all-closed`/`before-quit` 时 `stopFastApiServer()` 杀掉后端 |
| 后端入口 | `server/server.py`（`uvicorn server:app`），默认 `0.0.0.0:8100`；`server/main.py` 提供 `--serve-only` / `--schedule` 等模式 |
| FastAPI App | `server/api/app.py`：`create_app()` + `app_lifespan`（已在 lifespan 启动 `download_engine`），挂载 `/ws/market` 实时中继 |

### 2.2 前端如何连接后端（硬编码点）

前端在 **8 处**硬编码 `http://127.0.0.1:8100` / `ws://127.0.0.1:8100`，是解耦的主要改造面：

```
client/src/renderer/src/service/marketDataService.ts   (API_BASE)
client/src/renderer/src/service/realtimeWSClient.ts     (WS_URL)
client/src/renderer/src/Home.vue / SymbolBrowser.vue / MarketBrowser.vue  (API_BASE)
client/src/renderer/src/Backtest.vue / Portfolio.vue    (baseUrl)
client/src/renderer/src/components/cache-timeline/CacheTimeline.vue (baseUrl prop)
```

### 2.3 已有的数据/缓存基础设施（可直接复用）

| 组件 | 说明 |
|------|------|
| `data_provider/*` | Binance/OKX/Akshare/Baostock/Pytdx/TickFlow 等多数据源 Fetcher，含 WS 客户端 |
| `src/services/kline_cache_manager.py` | SQLite K线缓存（`kline_data` + `kline_cache_meta`），缺口分析/合并/删除 |
| `src/services/download_engine.py` | 异步批量下载任务引擎（已注册到 lifespan） |
| `src/services/realtime_ws.py` | `RealtimeWSRelay`：前端 WS 接入 + 上游实时行情中继 |
| `src/services/symbol_list_service.py` | 各市场品种列表发现（内存 TTL 缓存 1h） |
| `src/scheduler.py` | 定时任务调度（已用于分析流程） |

### 2.4 已有鉴权（与目标差距）

- `src/auth.py` + `api/middlewares/auth.py`：**单管理员口令**鉴权
  （`ADMIN_AUTH_ENABLED` 开关 + PBKDF2 口令 + 签名 session cookie），保护 `/api/v1/*`。
- **差距**：这是「单管理员」模型，缺少多租户账号体系、订阅等级、按等级的数据/模型
  权限控制。需在其之上扩展，而非替换。

### 2.5 管理前端现状

- `server/api/app.py` 在 `static/index.html` 存在时托管 SPA；`server/src/webui_frontend.py`
  期望从 `server/apps/dsa-web` 构建产物拷贝到 `static/`。
- **现状**：仓库中 `server/apps/dsa-web` 与 `static/` 目前不存在。
- **决策变更**：不再新建独立 Web SPA。管理功能嵌入 Electron 客户端的 `Settings.vue`
  或新增 Admin 页面，作为授权用户的特权入口。

### 2.6 Bot 系统现状

- `server/bot/` 下已有完善的机器人框架：命令系统（分析/问答/市场/策略等）、多平台适配
  （钉钉、飞书、Discord）以及 `server/src/notification_sender/` 下十余种通知通道。
- **现状**：bot 与主进程绑定，通知发送依赖服务端运行，但账号隔离、按用户推送尚未实现。
- **定位变更**：Bot 系统是重要但非核心功能，列为独立后置阶段（详见 Bot 规划章节）。

---

## 三、目标架构

```
┌─────────────────────────────────┐        ┌──────────────────────────────────────────┐
│  Electron 客户端 (N台)           │        │       服务端 (mac mini / 云主机, 7×24)      │
│                                 │  HTTPS │  ┌──────────────────────────────────────┐  │
│  - 交易/图表/分析 UI             │◀──────▶│  │  FastAPI (server.py, 0.0.0.0:8100)   │  │
│  - 可配置服务端地址               │  WSS   │  │  - REST /api/v1/*  + /ws/market       │  │
│  - 管理员（授权用户）：           │        │  │  - 鉴权中间件 (admin + 多租户/订阅分级) │  │
│    · 服务状态 / 缓存管理          │        │  └──────────────────────────────────────┘  │
│    · 客户端监控 / 账号管理        │        │  ┌──────────────┐  ┌────────────────────┐  │
│    · 采集任务调度监控            │        │  │ 采集守护进程  │  │  Bot 推送服务 (未来) │  │
│  - 普通用户：基础行情/分析        │        │  │ Collector    │  │  - 多用户订阅管理   │  │
│                                 │        │  │  - WS实时写入 │  │  - 按用户配置推送   │  │
│  ⚠ 管理功能仅对「管理员」可见     │        │  │  - 定时补全   │  │  - 独立于客户端活跃 │  │
│    需要在客户端登录 admin 账号     │        │  │  - 标的预热   │  └────────────────────┘  │
│    并通过鉴权后方可使用           │        │  └──────┬───────┘                       │
│                                 │        │         ▼                                │
└─────────────────────────────────┘        │  ┌──────────────────────────────────────┐  │
                                           │  │  SQLite (WAL): 行情缓存 + 标的列表     │  │
                                           │  │  + 账号/订阅/用量 + 客户端会话         │  │
                                           │  └──────────────────────────────────────┘  │
                                           └──────────────────────────────────────────┘
```

### 关键设计原则

- **后端地址可配置**：客户端不再硬编码 `127.0.0.1:8100`，改为运行时从配置读取
  `serverBaseUrl`，支持「内置本地后端」与「连接远程服务端」两种模式平滑切换。
- **后端可独立运行**：服务端不依赖 Electron，通过进程守护（macOS `launchd`）或
  Docker 容器常驻；客户端只是其消费者之一。
- **采集与服务分离**：常驻「采集守护」负责持续写入缓存；REST/WS 负责对外服务，
  二者共享同一个 SQLite。
- **分层 + 需求驱动采集**：按数据粒度分层（L0 全市场快照 / L1 全市场日线归档 /
  L2 热门实时流+分钟线 / L3 长尾按需）。廉价高价值的全量储备，昂贵的只给热集合，
  **不全量实时抓取**（详见 Phase 3）。
- **渐进式鉴权**：管理功能复用现有 admin 口令鉴权；新增多租户 + 订阅分级保护数据 API，
  通过开关控制是否强制（内网阶段可关闭）。
- **管理平台内嵌于客户端**：不再维护独立的 Web SPA 前端工程，管理功能作为 Electron
  客户端的特权模式通过 admin 鉴权访问。

---

## 四、开发阶段规划

> 优先级：Phase 1 → 2 → 3 是内网跑通「常驻服务端 + 客户端连接」的最小闭环；
> Phase 4 是管理客户端功能嵌入；Phase 5 是商业化鉴权；Phase B 是 Bot 迁移（独立后置）。

### Phase 1：前后端解耦（客户端可连接远程后端）

目标：客户端能通过配置连接任意服务端地址，不再强绑定本地自动拉起的后端。

- [x] **1.1 统一后端地址来源**
  - 新增 `client/src/renderer/src/service/serverConfig.ts`：导出 `getApiBase()` /
    `getWsUrl()`，从配置（IPC + localStorage 兜底）读取 `serverBaseUrl`，
    默认 `http://127.0.0.1:8100`。
  - 改造 8 处硬编码（见 §2.2）统一走 `serverConfig`。
  - 额外：`Settings.vue` 中的 `baseUrl` computed 也已改用 `getApiBase()`。
  - > ✅ 核查与补全（2026-06-29）：§2.2 列出的 8 处已全部改用 `serverConfig`。
    > 后续发现的 3 处遗留模块（`StockAnalysis.vue`、`News.vue`、`service/chatService.ts`）
    > 原硬编码 `http://127.0.0.1:${dsaPort}`，现已统一改为 `getApiBase()`，
    > 并清理了多余的 `dsaPort` 逻辑。至此渲染进程全部走 `serverConfig`，远程模式下
    > 分析/新闻/聊天功能可正确指向远程服务端。
- [x] **1.2 主进程配置项**
  - `client/src/main/index.js`：在 `hivelogic-config.json` 增加 `server` 段
    （`mode: 'local' | 'remote'`、`remoteBaseUrl`、`token`）。
  - 新增 IPC：`get-server-config` / `set-server-config`，供渲染进程读取/保存。
  - `client/src/preload/index.js` 暴露 `getServerConfig` / `setServerConfig`。
- [x] **1.3 本地后端按需启动**
  - `startFastApiServer()` 调整：仅当 `mode === 'local'` 时自动拉起；`remote` 模式
    跳过本地后端，直接连远程。
  - `before-quit` / `window-all-closed` 仅在本地模式停止后端。
- [x] **1.4 设置页 UI**
  - `Settings.vue` 新增「服务端连接」分组：模式切换（本地/远程）、远程地址输入、
    连接测试按钮（探测 `/api/health`）、访问令牌输入。
  - 保存时同步写入 `localStorage['hivelogic:serverBaseUrl']`，使 `getApiBase()` 立即生效。
- [x] **1.5 CORS / 跨域**
  - 远程模式下，前端 origin 与后端不同源；后端 `api/app.py` 已通过 `CORS_ORIGINS`
    环境变量加入客户端来源（代码中已存在，无需修改）。`CORS_ALLOW_ALL=true` 可用于
    内网开发。

产出验收：在 A 机器跑后端，B 机器客户端填入 `http://<A_IP>:8100` 可正常加载行情与图表。

---

### Phase 2：服务端独立部署（mac mini 常驻 + Docker 化）

目标：后端脱离 Electron，在 mac mini 上 7×24 常驻、开机自启、崩溃自拉起，
并为未来云迁移准备容器化方案。

- [x] **2.1 部署文档与脚本**
  - 新增 `doc/deploy/server_setup_macos.md`：mac mini 环境准备
    （Python/uv 安装、克隆代码、`.env` 配置、数据目录规划）。
  - 新增 `deploy/run_server.sh`：以 `python main.py --serve-only --host 0.0.0.0
    --port 8100` 启动（确认监听 `0.0.0.0`）。
- [x] **2.2 进程守护（launchd）**
  - 新增 `deploy/com.hivelogic.server.plist`：`KeepAlive=true`、`RunAtLoad=true`、
    日志重定向到 `logs/`，崩溃自动重启。
  - 文档说明 `launchctl load/unload` 与日志查看方式。
- [x] **2.3 数据目录与持久化**
  - 明确 `DATABASE_PATH` / 缓存 db / `.session_secret` / `.admin_password_hash`
    的服务端落盘路径（独立于代码目录，便于备份）。
  - 提供数据库备份脚本 `deploy/backup_db.sh`（SQLite WAL 安全备份，保留 30 份）。
- [x] **2.4 容器化（Docker）**
  - 新增 `Dockerfile`：基于 Python 3.12+ 镜像，安装 uv + 依赖，暴露 8100 端口，
    支持 `--serve-only` 模式启动。
  - 新增 `docker-compose.yml`：定义 `server` 服务 + 数据卷挂载（独立于容器生命周期
    的持久化目录）。
  - 新增 `doc/deploy/docker_deploy.md`：文档说明 Docker 运行方式：`docker compose up -d` 即可启动守护。
  - **设计考量**：
    - 数据目录通过 volume 持久化，数据库/配置文件/日志不出容器。
    - 环境变量通过 `.env` 或 `docker-compose.override.yml` 传入。
    - 后续云迁移：镜像不变，只需替换编排层（launchd → Docker Compose → K8s）。
- [x] **2.5 网络与安全（内网阶段）**
  - 固定内网 IP 或主机名；说明端口放行。
  - 内网阶段先用现有 admin 口令鉴权 + 简单访问令牌保护数据 API（Phase 5 再升级）。

产出验收：mac mini 重启后服务端自动恢复；`kill` 进程后被 launchd 拉起；
客户端断开/重连后行情不丢失；Docker 部署可替换 launchd 方案。

---

### Phase 3：持续行情采集与归档 + 标的列表预热（满足需求 1、2）

目标：服务端常驻采集，客户端「开箱即有数据」。

#### 设计基调：分层 + 需求驱动，而非全量实时

> 核心结论：**不实时抓取所有标的的实时行情**。按「数据粒度」分层——廉价高价值的
> （日线、全市场快照）全量储备；昂贵的（分钟线、实时流）只给真正有人看的热集合。
>
> 原因：A股 ~5400 + 港股 ~2800 + 美股 ~6000-8000 + 加密各 ~500，合计约 **2 万标的**。
> - 日线全量归档 ≈ 1 亿行（几个 GB），**便宜，值得全量做**；
> - 分钟线全量 ≈ **每年 12 亿行**，且绝大多数无人看，**不现实**；
> - A股/港股/美股数据源多为 REST，全量高频实时必然触发限流/封 IP（加密有聚合流，例外）。

四层采集模型：

| 层 | 范围 | 频率 | 落地策略 |
|----|------|------|----------|
| **L0 全市场快照** | 所有标的最新价/涨跌幅 | 盘中低频（数秒~数十秒） | 全市场快照接口一次拿回，供标的浏览器列表（满足需求1） |
| **L1 全市场日线归档** | 所有标的日线 | 每日收盘后增量 | 复用 `DownloadEngine`，**用全市场快照接口而非逐标的循环** |
| **L2 热门标的实时流+分钟线** | 被订阅的标的（自选∪在看∪运营重点） | 实时 | 引用计数订阅，LRU 退订；历史保留 |
| **L3 长尾冷门** | 其余标的 | 纯按需 | 客户端首次打开→现场拉一次→写缓存→升温进 L2 |

> AI 分析主要消费「日线 + 基本面 + 新闻」，由 L1 覆盖，**不依赖实时 tick**。

#### 任务清单

- [x] **3.1 标的列表持久化与预热（L0 基础）**
  - 将 `SymbolListService` 结果落库（新表 `symbol_list`：market/symbol/name/updated_at）。
  - `GET /api/v1/market/symbols?market=...` 优先读库，秒级返回。
  - 客户端启动直接拉该接口渲染标的列表（满足需求 1）。
- [x] **3.2 全市场行情快照采集（L0）**
  - 新增低频快照采集（A股用东财全量接口、加密用聚合流 `!ticker@arr`），维护「最新一份」
    全市场价格（最新价/涨跌幅），供标的浏览器；不长期归档。
  - > ✅ 补全（2026-06-29）：新增 `collect_us_stock`（东财 `stock_us_spot_em`，
    > `代码` 形如 `105.AAPL` → 取 ticker），并将列名读取改为别名兼容
    > （A股 `今开/最高/最低/昨收` ↔ 美股 `开盘价/最高价/最低价/昨收价`）。
    > 现 `collect_all` 覆盖 cn_stock/cn_etf/hk_stock/us_stock/crypto。
    > （crypto 当前仍用 REST `ticker/24hr` 轮询，非聚合流，属可接受实现差异。）
- [x] **3.3 全市场日线定时归档（L1）**
  - 见下「3.7 定时采集调度」；按市场收盘后增量补全所有标的日线。
  - > ✅ 补全（2026-06-29）：`_SNAPSHOT_TO_KLINE_MARKET` 增加 `us_stock → us`，
    > `archive_daily_from_snapshot("us_stock")` 现可用，美股日线归档已覆盖。
- [x] **3.4 实时行情写入缓存（L2）**
  - `RealtimeWSRelay` / WS 客户端中继实时 K 线时，未收盘 K 线以 `is_complete=0` 写入
    `kline_data`，收盘后更新为完整（落实 `local_database_plan` 待办项）。
  - 日终用 L1 官方收盘日线**校正**当天由实时流拼出的日线（以收盘值为准）。
- [x] **3.5 订阅管理器（L2 关键缺口）**
  - 新增 `src/services/subscription_manager.py`：把【客户端需求 → 上游订阅】做
    **引用计数 + 多路复用 + LRU**——一个标的上游只订阅一次，扇出给 N 个客户端；
    无订阅者后按 LRU 退订上游（历史缓存保留）。
  - 改造 `RealtimeWSRelay` 走订阅管理器，**杜绝每客户端各开一条上游连接**。
  - 热集合来源：各客户端自选 ∪ 正在打开 ∪ 服务端运营配置，去重。
  - > ✅ 接线（2026-06-29）：`RealtimeWSRelay` 已真正接入 `SubscriptionManager`：
    > 每个 ws 分配稳定 client_id；subscribe/unsubscribe/断连均驱动管理器引用计数，
    > 上游订阅由 0→1 回调触发、退订由 LRU grace 期满的 eviction 回调触发。
    > `_aggregated_quotes/_depth` 改为由管理器派生（含 grace 期标的）；
    > 新增 `start/stop_subscription_eviction_loop`，已在 `app.py` lifespan 启停。
    > grace 期通过 `REALTIME_LRU_GRACE_SECONDS`（默认 60s）配置。`get_status()`
    > 增加 `subscription_manager` 字段供管理面板观测。
- [x] **3.6 缓存优先读取强化 + 命中率埋点**
  - 复核 `DataFetcherManager.get_daily_data()` 的 cache-first 流程；增加命中率/缺口指标
  （供管理面板展示）。
- [x] **3.7 定时采集调度（L1 核心）**
  - **按市场收盘后分别增量**（服务端按 CST/UTC+8）：

    | 任务 | 触发(CST) | 说明 |
    |------|-----------|------|
    | A股日线增量 | 15:30 | 15:00 收盘后，仅交易日 |
    | 港股日线增量 | 16:30 | 16:00 收盘后 |
    | 美股日线增量 | 06:00 | 美股 16:00 ET ≈ 次日 04:00–05:00 CST 收盘，留余量 |
    | 加密日线增量 | 08:10 | UTC 00:00=CST 08:00 为日线边界，收线后跑 |
    | 标的列表刷新 | 07:00 | 处理新增/退市/上下架 |
    | 夜间缺口对账补全 | 02:00 | 扫描 `cache_meta` 空洞，低优先级回填 |
    | 库维护(VACUUM/清理/备份) | 03:30 | 低峰期；分钟线按保留窗口清理 |

  - **增量而非全量**：只拉「上次缓存日期 → 今天」缺口（通常 1 根）。
  - **优先全市场快照接口**：A股收盘后一次拿回 ~5400 只 OHLC，避免 5400 次请求被限流。
  - **交易日判断**：复用 `get_open_markets_today()`，休市跳过对应市场任务。
  - **断电自愈（catch-up，7×24 必备）**：`schedule` 库不会补跑错过的任务。每个任务记录
    「上次成功日期」，服务启动时/每轮检查比对「应跑未跑」并补跑（幂等 upsert 保证安全）。
  - **幂等 + 重试**：依赖 `kline_data` 的 `UNIQUE(market,symbol,interval,timestamp)` 做 upsert；
    失败带退避重试，单标的失败不影响整体。
  - **可观测**：每任务的「上次成功时间/耗时/拉取条数/失败数」落表，供管理面板与 catch-up 依据。
  - **调度器实现**：**扩展现有 `Scheduler` 支持多定时点**。当前仅支持单一 `every().day.at()`，
    扩展为维护一个定时点列表，每个任务独立配置触发时间。**不引入 APScheduler**，理由如下：
    - 当前仅有 7 个固定时刻的任务，APScheduler 的 cron 表达式 + 线程池 + job store 持有化
      对于这个场景属于过度设计。
    - 引入 APScheduler 会增加：异步调度器配置（`AsyncIOScheduler`）、job store 选型
      （内存 vs SQLite 持久化）、序列化/反序列化、以及运行时线程池管理，这些复杂度
      在当前阶段没有收益。
    - catch-up 机制在业务层实现（记录「上次成功时间」逐任务校验），比 APScheduler 的
      misfire_grace_time 更可靠也更可控。
    - 未来如果任务数量膨胀到上百个、且需要动态增删/暂停/恢复、需要精确秒级 cron 表达式
      时，再考虑 APScheduler 不迟。
  - > ✅ 补全（2026-06-29）：`_build_scheduler()` 现注册 **8 个命名任务**，与上表对齐：
    > `cn_stock_daily` 15:30、`hk_stock_daily` 16:30、`us_stock_daily` 06:00（新增）、
    > `crypto_daily` 08:10、`symbol_list_refresh` 07:00（已含 us_stock）、
    > `nightly_gap_reconcile` 02:00（新增）、`db_maintenance` 03:30、`db_backup` 03:00。
    > 夜间缺口对账对已收盘的 A股/港股做幂等补全，并记录各市场日线新鲜度
    > （`CacheMaintenance.get_daily_freshness()`）；US/crypto 此刻未收线，交由自身任务 + catch-up。
    > 顺带修复：`app.py` 模块级 `_build_scheduler() -> Scheduler` 标注引用的 `Scheduler`
    > 之前仅在 lifespan 内局部 import，导致 `import api.app` 抛 `NameError`、服务无法启动；
    > 已将 `from src.scheduler import Scheduler` 提升到模块顶层。
- [x] **3.8 SQLite 并发防护：写队列 + busy-timeout**
  - SQLite 在 7×24 场景下，采集线程持续写入 + API 读取 + WS 实时中继写入，
    虽 WAL 模式允许读写并行，但写写冲突仍需防范。
  - **写队列**：所有写入操作（采集写入、缓存更新）通过单例队列串行化，
    避免多个协程/线程同时写 SQLite 导致 `database is locked`。
  - **busy-timeout**：SQLite 连接设置 `PRAGMA busy_timeout = 5000`，
    让写入冲突时等待最多 5 秒再报错，而非立即失败。
  - **连接管理**：API 只读路径使用单独的只读连接，与写连接分离，减少锁竞争。
  - 写入队列的实现应轻量：一个 `asyncio.Queue` + 单个 consumer 协程循环消费。
- [x] **3.9 磁盘与清理策略**
  - 缓存大小统计接口 + 分钟级数据保留窗口/自动清理（落实 `local_database_plan` 待办项）。

产出验收：客户端冷启动立即看到标的列表与最新价；常用标的行情几乎全部命中本地缓存；
服务端在错过定时任务后（宕机/重启）能自动补跑当日日线，无数据缺口；
长时间运行无 `database is locked` 错误。

---

### Phase 4：管理功能嵌入客户端

目标：授权管理员可通过客户端查看和操作服务端，无需独立部署 Web SPA。

**设计思路变更**：原计划新建 `server/apps/dsa-web` 独立 SPA，现改为将管理功能
嵌入 Electron 客户端的特权模式。理由：
- 避免维护两套前端工程（Electron + Web SPA）
- 客户端已具备完整 UI 框架（Vue3 + Element Plus），复用现有组件即可
- 管理功能天然需要鉴权，客户端 admin 登录流程可与 Phase 5 统一

- [x] **4.1 管理功能入口与鉴权**
  - `Settings.vue` 新增 `admin` 导航分类 + `AdminPanel.vue` 组件：管理面板入口，
    仅当 `dsaServerRunning === true` 时显示。
  - 管理功能复用现有 `ADMIN_AUTH_ENABLED` 鉴权体系：用户通过 `POST /api/v1/auth/login`
    获取 admin session cookie，客户端通过 `credentials: 'include'` 自动携带。
  - 后端 admin 端点位于 `/api/v1/admin/*`，受 `AuthMiddleware` 统一保护
    （与 `/api/v1/*` 其他路由一致），未登录返回 401。
  - 角色字段（`role: admin` / `role: user`）预留到 Phase 5 启用。
- [x] **4.2 服务状态面板**
  - 后端新增 `GET /api/v1/admin/status`：返回进程（uptime/started_at/python_version/
    pid/version）、WS 中继状态、调度任务列表（name/schedule_time/last_run/
    last_status/last_duration/next_run/enabled）、采集器状态、缓存命中指标、
    磁盘使用、写入队列指标（enqueued/completed/failed/retries/depth/last_error）。
  - 客户端 `AdminPanel.vue` 渲染 7 张卡片：进程信息、WS 中继（含客户端表）、
    调度任务（含触发按钮）、行情采集器（含采集/归档按钮）、缓存指标（含磁盘使用）、
    写入队列、缓存维护。每 5 秒自动轮询。
- [x] **4.3 缓存管理**
  - 后端已有 `/api/v1/cache/metrics`、`/cache/disk-usage`、`/cache/maintenance`、
    `/cache/snapshot/{market}` 等端点（Phase 3.6 新增）。
  - 管理面板复用 `/admin/status` 中的 `cache_metrics` + `disk_usage` 字段统一展示，
    并提供「执行维护」按钮调用 `POST /api/v1/admin/maintenance/run`
    （清理过期 K 线 + 任务日志 + VACUUM）。
- [x] **4.4 客户端连接监控**
  - 后端新增 `RestClientTracker`（`server/api/middlewares/rest_tracker.py`）：
    有界 deque + IP 索引，通过中间件自动记录最近 REST 调用者。
  - 后端新增 `GET /api/v1/admin/clients`：返回活跃 WS 客户端
    （IP/state/订阅报价数/订阅深度数/订阅品种列表）+ 最近 REST 调用者。
  - 客户端管理面板以表格展示 WS 客户端，含状态徽章（connected=绿/disconnected=红）。
- [x] **4.5 配置与调度管理**
  - 调度任务手动触发：`POST /api/v1/admin/scheduler/trigger/{task_name}`
    （async fire-and-forget，返回 `{task, status: "triggered"}`）。
  - 采集器手动触发：`POST /api/v1/admin/collector/collect/{market}`
    （market: cn_stock/cn_etf/hk_stock/crypto/all）。
  - 快照归档：`POST /api/v1/admin/collector/archive/{market}`
    （将最新快照转为 1d K 线写入 kline_data）。
  - 系统配置编辑复用现有 `system_config` 服务（已在 Phase 1 接入 Settings.vue）。
  - Phase 5 的账号/订阅管理入口已在管理面板架构中预留。
- [x] **4.6 清理旧管理前端代码**
  - `server/main.py` 中 `prepare_webui_frontend_assets()` 调用改为受
    `WEBUI_AUTO_BUILD` 环境变量控制（默认 `false`，跳过前端资源准备）。
  - 服务端以 server-only 模式运行，前端 SPA 托管逻辑冻结，不再自动构建 `static/`。

产出验收：使用管理员账号登录客户端，可在设置中看到管理面板入口，进入后可查看
服务状态、缓存覆盖情况、在线客户端列表、手动触发采集任务。

---

### Phase 5：客户端鉴权与订阅分级（满足需求 5，商业化前置）

目标：多租户账号体系 + 订阅等级 + 按等级的数据/模型权限。

- [x] **5.1 账号与订阅数据模型**
  - 新增 `server/src/models/accounts.py`：4 个 ORM 模型 — `Account`
    （id/email/password_hash/role/status/display_name）、`Subscription`
    （account_id/tier/starts_at/expires_at/status）、`ApiToken`
    （account_id/token_hash/token_prefix/device_info/expires_at/revoked_at/last_used_at）、
    `UsageRecord`（account_id/endpoint/method/market/model_used/tokens_consumed）。
    全部继承 `storage.Base`，含 `to_dict()`。
  - 新增 `server/src/models/tiers.py`：`TierConfig` frozen dataclass 定义权限矩阵
    （markets/intervals/history_days/models/qps/daily_quota/features）。
    3 档：`FREE`（cn only, 1d/1w, 30d, 无 AI, 100/day）、`PRO`（全市场, 全周期,
    365d, standard/deepseek/qwen, 5000/day）、`ENTERPRISE`（无限历史/模型/配额）。
    `TIERS` 注册表 + `TIER_ORDER` + `get_tier_config()` / `tier_meets_minimum()` /
    `get_effective_tier()`。
  - 新增 `server/src/repositories/account_repository.py`：`AccountRepository` 单例，
    PBKDF2-SHA256 密码哈希（100k iterations, salt_b64:hash_b64）、
    `secrets.token_urlsafe(32)` 令牌生成 + SHA256 哈希存储。
    方法：`create_account` / `verify_credentials` / `get_active_subscription` /
    `get_account_tier` / `grant_subscription`（自动取消旧订阅）/ `create_token`
    （返回原始 token 一次）/ `validate_token`（更新 last_used_at）/ `revoke_token` /
    `revoke_all_tokens` / `list_accounts` / `update_account` / `delete_account` /
    `list_subscriptions` / `list_tokens` / `record_usage` / `get_usage_summary`。
  - `server/api/app.py` 新增 `import src.models.accounts` 确保 ORM 注册到
    `Base.metadata`，`DatabaseManager.__init__` 的 `create_all` 自动建表。
- [x] **5.2 客户端鉴权（区别于 admin 鉴权）**
  - 新增 `server/api/v1/endpoints/client_auth.py`：`GET /client-auth/status`、
    `POST /client-auth/login`（email+password→Bearer token）、
    `POST /client-auth/logout`（吊销当前 token）、`GET /client-auth/me`
    （返回 account+tier+usage）。`_is_client_auth_enabled()` 读 `.env` 的
    `CLIENT_AUTH_ENABLED`（与 admin auth 同模式）。
  - 改造 `server/api/middlewares/auth.py`：双鉴权分支并存。
    admin 分支（cookie `dsa_session`）+ client 分支（`Authorization: Bearer` 头）。
    client 分支调用 `AccountRepository.validate_token()` 验证，成功则设置
    `request.state.client_account`。admin-only 路径（`/api/v1/admin/*`）要求 admin
    session，client token 不可访问。`CLIENT_AUTH_ENABLED` 关闭时跳过 client 分支。
  - `server/api/v1/router.py` 注册 `client_auth.router` 到 `/client-auth` 前缀。
- [x] **5.3 权限/配额执行（entitlement）**
  - > ✅ 接线（2026-06-29）：已在 `entitlement.py` 新增端点标识归一化
    > （`normalize_market_key`：cn_stock→cn / hk_stock→hk / us_stock→us / crypto→crypto_binance；
    > `normalize_interval_key`：1/5/60/daily→1m/5m/1h/1d）与统一准入助手 `enforce_data_request`
    > （配额 402 → 市场 403 → 周期 403 → 历史深度 403，映射不到的市场/周期保守放行）。
    > `market.py`（/symbols、/kline、/realtime、/browser/data）与 `stocks.py`
    > （/{code}/quote、/{code}/history）已调用该助手，并对 /kline 记录用量。
    > **关键**：所有检查在客户端鉴权未启用/无客户端账号时自动跳过，内网免登录模式零影响。
    > （`/history` 为分析报告历史、无市场维度，未纳入市场门禁。）
  - 新增 `server/src/services/entitlement.py`：`EntitlementService` 单例 +
    FastAPI 依赖工厂。
    - `check_market_access` / `check_interval_access` / `check_history_depth` /
      `check_model_access` / `check_daily_quota` / `check_feature` — 无权抛 403，
      超额抛 402，响应含 tier/error/message 便于前端展示升级提示。
    - `get_entitlements(account_id)` 返回完整权限矩阵。
    - FastAPI 依赖：`require_market(market)` / `require_interval(interval)` /
      `require_model(model)` / `require_feature(feature)` / `check_client_quota` —
      client auth 未启用时自动跳过（`request.state.client_account` 为 None）。
    - `record_api_usage()` fire-and-forget 记录用量。
  - 新增 admin 账号管理端点（`server/api/v1/endpoints/admin.py`）：
    `GET /admin/accounts` / `POST /admin/accounts` / `PUT /admin/accounts/{id}` /
    `DELETE /admin/accounts/{id}` / `GET /admin/accounts/{id}/subscriptions` /
    `POST /admin/accounts/{id}/subscriptions`（授予订阅）/ `GET /admin/accounts/{id}/tokens` /
    `POST /admin/accounts/{id}/tokens/revoke-all` / `DELETE /admin/tokens/{id}` /
    `GET /admin/accounts/{id}/usage` / `GET /admin/accounts/{id}/entitlements`。
- [x] **5.4 客户端登录 UI**
  - `Settings.vue`「服务端连接」分组新增「客户端账号」卡片：
    - 未启用时显示 `.env` 配置提示。
    - 未登录时显示邮箱+密码输入框与登录按钮。
    - 已登录时显示邮箱/显示名/订阅等级（带 tier badge 着色）+ 用量统计
      （总请求/今日请求/Token 消耗）+ 退出登录按钮。
    - token 存储于 `localStorage['hivelogic:clientToken']`，请求头自动携带
      `Authorization: Bearer`。
    - 服务启动/状态变化时自动调用 `loadClientAuthStatus()` 同步状态。
- [x] **5.5 管理面板账号管理**
  - `AdminPanel.vue` 新增第 8 张卡片「账号管理」：
    - 账号列表表格（ID/邮箱/显示名/角色/状态/订阅等级/操作）。
    - 创建账号对话框（邮箱/密码/显示名/角色）。
    - 授予订阅对话框（等级 free/pro/enterprise + 有效期天数）。
    - 账号详情对话框：基本信息 + 订阅权限矩阵 + 用量统计 + 令牌列表（含吊销按钮）。
    - 删除账号需二次确认。吊销全部令牌需二次确认。
    - 挂载时调用 `loadAccounts()`，与 5s 轮询独立。

产出验收：不同等级账号登录后，可用市场/粒度/模型按矩阵生效；超额被正确拦截；
管理员可在客户端管理面板管理账号与订阅。

---

### Phase 6：稳定性、安全与上线准备

- [x] **6.1 传输安全**
  - 新增 `deploy/Caddyfile`：Caddy 反向代理配置，自动 Let's Encrypt TLS 证书签发+续期，
    支持 HTTP/3 (QUIC)，配置安全头（HSTS / X-Content-Type-Options / X-Frame-Options /
    Referrer-Policy），基础限流（30r/m per IP），请求体大小限制 50MB。
  - 新增 `docker-compose.proxy.yml`：Caddy 容器编排 override，开放 80/443/443-udp 端口，
    挂载 Caddyfile + 证书数据卷，`depends_on: server (healthy)`，覆盖基础 compose 不再
    直接暴露 8100 端口。内网无域名场景 Caddy 使用 internal CA 自动签发。
  - 新增 `doc/deploy/https_setup.md`：HTTPS 部署完整指南，含 Caddy vs Nginx vs Traefik
    选型对比、公网域名/内网 IP 两种场景、证书管理、故障排查、回滚方案。
- [x] **6.2 监控与告警**
  - 新增 `server/src/services/health_monitor.py`：聚合健康快照服务，5 个组件检查：
    - **scheduler**：任务 catch-up 滞后检测（last_success vs 预期触发时间，warning 2h /
      critical 26h，阈值可通过 `HEALTH_LAG_*` 环境变量覆盖）
    - **collector**：市场快照新鲜度（last_collected 时间，warning/critical 阈值）
    - **write_queue**：失败率 + 队列积压检测（`HEALTH_QUEUE_FAILURE_RATE_CRITICAL`）
    - **disk**：磁盘使用率（warning 80% / critical 90%）
    - **data_sources**：数据源失败环形缓冲区（`record_data_source_failure()` API，
      过去1小时失败计数告警）
  - 新增 `GET /api/v1/admin/health` 端点：返回聚合健康快照（overall status + 各组件
    详情），供外部监控（Uptime Robot / 阿里云监控）探测。
  - 扩展 `server/src/logging_config.py`：新增 `JsonFormatter`，`LOG_JSON=true` 时
    所有 handler（console + file + debug file）切换为 JSON 格式，供 ELK/Loki/Datadog
    等日志聚合系统消费。
- [x] **6.3 限流与防滥用**
  - 新增 `server/api/middlewares/rate_limit.py`：滑动窗口限流中间件，双桶策略：
    - **Per-IP**：默认 60 req/min（`RATE_LIMIT_PER_MINUTE` 可配置）
    - **Per-account**：默认 120 req/min（`RATE_LIMIT_ACCOUNT_PER_MINUTE` 可配置，
      已登录客户端账号优先于 IP 桶）
    - 超限返回 429 + `Retry-After` 头 + bucket/limit 信息
    - 豁免路径：`/api/health`、`/api/v1/admin/*`、`/api/v1/auth/*`、`/api/v1/client-auth/*`、
      `/ws/*`、`/docs` 等（admin 暴力破解由 `src/auth.py` 限流层处理）
    - 信任 `X-Forwarded-For`（`TRUST_X_FORWARDED_FOR=true` 时取最右值，配合反向代理）
    - 自动清理过期 bucket（每 5 分钟一次）
  - `server/api/app.py` 注册中间件，顺序：RateLimit → Auth → RestTracker（Auth 设置
    `request.state.client_account` 后 RateLimit 可读取账号 ID）。
- [x] **6.4 备份与迁移**
  - `server/api/app.py` `_build_scheduler()` 新增 `db_backup` 定时任务（每日 03:00 CST），
    调用 `deploy/backup_db.sh`（WAL 安全备份，保留 30 份），通过 scheduler catch-up
    机制保证宕机后自动补跑。备份失败/超时/错误均记录日志。
  - 新增 `doc/deploy/cloud_migration.md`：mac mini → 云主机 Docker 完整迁移指南，
    含数据备份-传输-恢复流程、`.env` 云环境适配（CORS/TRUST_X_FORWARDED_FOR/LOG_JSON/
    限流配置）、DNS 切换、回滚方案、迁移后验证清单、后续运维（日志聚合/监控告警/定期更新）。
- [x] **6.5 容器化生产部署**
  - 新增 `docker-compose.prod.yml`：生产环境 override，强制鉴权（ADMIN/CLIENT_AUTH_ENABLED=true）、
    CORS 限定域名、`TRUST_X_FORWARDED_FOR=true`、`LOG_JSON=true`、限流配置、
    `restart: always`、内存限制 4GB/预留 1GB、日志驱动 json-file（50MB × 5 份）。
  - 扩展 `server/.env.example`：新增 Phase 5/6 配置项文档（CLIENT_AUTH_ENABLED、
    TRUST_X_FORWARDED_FOR、RATE_LIMIT_*、LOG_JSON、HEALTH_* 阈值），含注释说明。
  - 重写 `doc/deploy/docker_deploy.md` §8 多环境配置：环境概览表（开发/生产/生产+TLS）、
    三种启动命令、各环境关键配置差异、环境变量管理（根目录 .env + server/.env 分层）、
    自定义 override 示例。
- [x] **6.6 测试**
  - 新增 `server/tests/test_auth.py`（15 测试）：密码哈希设置/验证/修改/磁盘格式、
    Session 创建/验证/过期/密钥轮换、登录限流（IP 计数/窗口过期/成功清除/多 IP 独立）。
  - 新增 `server/tests/test_entitlement.py`（22 测试）：TierConfig 定义正确性（free/pro/enterprise
    市场/周期/模型/配额/功能）、`tier_meets_minimum` 等级比较、`get_effective_tier` 降级处理、
    EntitlementService 403/402 抛出逻辑（mock repo，覆盖市场/周期/历史深度/模型/配额/功能）。
  - 新增 `server/tests/test_server_config.py`（8 测试）：Tier 配置与设计文档一致性、
    等级递增单调性（权限只增不减）、frozen dataclass 不可变性、加密市场标识命名。
  - 新增 `server/tests/test_scheduler_catchup.py`（10 测试）：命名任务注册/重复替换/
    无效时间拒绝、catch-up 自愈（从未运行→补跑/今天已跑→跳过/触发时间未到→跳过/
    昨天跑过今天漏→补跑/catchup 禁用→跳过）、任务成功状态记录。
  - 全部测试通过 `uv run pytest`（含原有 test_crypto_and_cache + test_data_source_chain）。
  - > ✅ 核查（2026-06-29）：实测 `109 passed`（已较计划撰写时的 63 个增长）。
    > 注意：本机 `uv run pytest` 会落到 anaconda 基础环境（venv 内未装 pytest），
    > 需用 `uv run --with pytest python -m pytest tests/` 才能在 venv 内跑通；
    > 建议把 `pytest` 正式加入 dev 依赖组。

---

### Phase B：Bot / 消息推送系统服务端化（后置独立阶段）

目标：将 Bot 系统从当前与主进程/客户端绑定的模式，迁移为服务端常驻的多租户推送服务。

#### 现状

- `server/bot/` 已有一套完整的机器人命令框架和平台适配（钉钉、飞书、Discord）。
- `server/src/notification_sender/` 有 10+ 种通知通道实现（邮件、telegram、slack、pushplus 等）。
- **当前问题**：
  - 推送逻辑依赖服务端运行（已满足），但**用户偏好/订阅/凭证是全局的**，没有按用户隔离。
  - 用户希望接收特定标的的推送通知，且**不依赖客户端活跃** — 即使客户端关闭，
    服务端也应能根据用户预配置的推送通道主动发送消息。
  - 不同用户可能使用不同推送通道（有人用飞书、有人用 telegram），且订阅的标的和分析
    类型不同。

#### 任务清单

- [ ] **B.1 推送偏好数据模型**
  - 新表 `notification_preferences`：`account_id` / `channel`（枚举：telegram/email/feishu/discord/…）/
    `channel_config`（JSON：各通道所需的凭证/地址/Webhook URL）/ `subscribed_events`
    （JSON：订阅的事件类型列表，如 `signal_generated` / `price_breach` / `daily_report` 等）/
    `enabled` / `created_at` / `updated_at`。
  - 关联到 `accounts` 表（Phase 5 建立），每个用户可以配置多个推送通道、订阅不同事件。
- [ ] **B.2 推送事件总线**
  - 在服务端新增轻量事件总线（可用 `asyncio.Queue` 或基础 pub/sub 模式），
    当分析引擎/采集系统/策略引擎产生需要推送的事件时，发布到事件总线。
  - 事件类型：`price_alert` / `signal_generated` / `daily_report` / `system_alert` 等。
- [ ] **B.3 推送调度器**
  - 新增 `src/services/notification_dispatcher.py`：
    - 消费事件总线消息
    - 查询 `notification_preferences` 匹配当前事件的用户和通道
    - 按用户预配置的通道调用对应的 `notification_sender/*` 发送
    - 失败重试 + 退避
- [ ] **B.4 用户偏好配置 UI**
  - 客户端 `Settings.vue`「推送通知」分组：配置推送通道凭证、选择订阅的事件类型。
  - 通过 Phase 5 的鉴权绑定到具体账号，配置存储在服务端而非本地。
- [ ] **B.5 现有 Bot 命令整合**
  - `server/bot/commands/*` 中的功能（问市场、分析标的、策略推送等）在服务端常驻后
    可对接推送事件总线，例如「研究助手」的分析结果可通过事件总线触达订阅用户。

#### 设计与非设计

| 决策点 | 方案 | 理由 |
|--------|------|------|
| 推送触发 | 事件驱动（事件总线），而非轮询 | bot 已具备异步通知能力；匹配推送场景 |
| 推送状态 | 服务端离线时推送丢失（不积攒）| Phase B 版本追求简洁，未来可加消息队列重试 |
| 与 bot 的关系 | bot 命令系统保持，推送作为 bot 能力的补充 | bot 命令用于实时互动，推送用于异步触达 |
| 优先级 | **Phase B 在所有 Phase 1–6 之后** | Bot 推送是增值功能，不影响核心闭环 |

---

## 五、里程碑与依赖关系

```
Phase 1 (解耦) ─→ Phase 2 (常驻部署+Docker) ─→ Phase 3 (持续采集) ─→ M1 内网闭环 ✅
                                                    │
                                                    └─→ Phase 4 (管理面板-嵌入客户端) ─→ M2 可运维
                                                                  │
                                                                  └─→ Phase 5 (鉴权/订阅) ─→ Ph6 (上线) ─→ M3 可商业化

Phase B (Bot 推送服务化) = 后置，不依赖 Phase 5，但可与 Phase 5 的 accounts 表配合
```

| 里程碑 | 包含阶段 | 价值 |
|--------|----------|------|
| M1 内网常驻闭环 | Phase 1–3 | 服务端 7×24 采集，客户端连接远程、开箱即有数据 |
| M2 可运维 | Phase 4 | 通过客户端管理面板监控服务、缓存、客户端连接 |
| M3 可商业化 | Phase 5–6 | 多租户鉴权、订阅分级、安全上线、生产部署 |
| M4 推送服务化 | Phase B（后置） | 多用户独立推送通道、事件驱动通知、不依赖客户端 |

---

## 六、关键技术决策

| 决策点 | 方案 | 理由 |
|--------|------|------|
| 后端地址配置 | 客户端运行时配置 `serverBaseUrl`，本地/远程双模式 | 平滑过渡，开发期仍可本地内置后端 |
| 进程守护 | macOS `launchd`（后续云上用 Docker Compose） | mac mini 原生；Docker 化后迁移路径清晰 |
| 部署容器化 | Docker + docker-compose，数据卷持久化 | 与 launchd 共存（内网 launchd，云上容器），镜像不变 |
| 采集范围 | 分层 + 需求驱动（L0/L1 全量、L2/L3 按需） | 全量实时不经济也不合规；详见 Phase 3 |
| 日线增量方式 | 优先全市场快照接口，而非逐标的循环 | 避免 5000+ 次请求触发限流/封 IP |
| 定时调度 | 按市场收盘后分别增量 + catch-up 自愈 | 跨时区各市场收盘不同；7×24 须能补跑漏跑 |
| 调度器实现 | **扩展现有 `Scheduler` 支持多定时点，不引入 APScheduler** | 7 个固定时刻无需 APScheduler 的 cron/持久化/线程池；catch-up 在业务层更可靠 |
| SQLite 并发 | WAL + 写队列（`asyncio.Queue`）+ busy_timeout + 读写分离 | 7×24 写入场景下防 `database is locked`，轻量实现 |
| 实时订阅 | 引用计数 + 多路复用 + LRU 的订阅管理器 | 一标的上游只订一次，扇出多客户端，防限流 |
| 存储 | 沿用 SQLite（WAL），账号/订阅同库或独立 db | 复用现有基础设施，内网够用；分钟线热集合扩大或商业化放量时迁移 PostgreSQL/TimescaleDB |
| 客户端鉴权 | JWT/Bearer，独立于 admin session | 多端、可吊销、便于配额统计 |
| 鉴权开关 | `CLIENT_AUTH_ENABLED` 运行时开关 | 内网阶段免登录，商业化阶段强制 |
| 管理平台形态 | **内嵌于 Electron 客户端**，不独立维护 Web SPA | 避免双工程维护；复用现有 UI 框架和鉴权体系 |
| 管理平台鉴权 | 复用 admin 口令鉴权，区分 admin/user 角色 | Phase 4 即完成管理功能，无需等待 Phase 5 |
| Bot 推送 | 事件总线 + per-user 偏好配置 | 低优先级后置；事件驱动简化架构 |
| 云迁移路径 | Docker 镜像不变 → 云主机/容器平台 | launchd → Docker → K8s 逐级演进 |

---

## 七、主要文件变更清单（预估）

### 客户端（Electron / 渲染进程）
```
client/src/renderer/src/service/serverConfig.ts        # 新增：统一后端地址
client/src/renderer/src/service/marketDataService.ts   # 改：去硬编码
client/src/renderer/src/service/realtimeWSClient.ts    # 改：去硬编码
client/src/renderer/src/{Home,SymbolBrowser,MarketBrowser,Backtest,Portfolio}.vue  # 改
client/src/renderer/src/components/cache-timeline/CacheTimeline.vue                 # 改
client/src/renderer/src/AdminPanel.vue                 # 新增：管理面板（Phase 4）
client/src/renderer/src/Settings.vue                   # 改：服务端连接 + 管理入口 + 登录 + 推送偏好
client/src/main/index.js                               # 改：server 配置 + 按需启动后端
```

### 服务端（backend）
```
server/src/services/market_collector.py        # 新增：持续采集守护（L0/L1 定时 + catch-up）
server/src/services/subscription_manager.py    # 新增：实时订阅引用计数/多路复用/LRU
server/src/services/db_write_queue.py          # 新增：SQLite 写队列（Phase 3）
server/src/services/notification_dispatcher.py # 新增：推送事件总线/调度器（Phase B）
server/src/scheduler.py                         # 改：支持多定时点（数处小改动，不引入 APScheduler）
server/src/services/entitlement.py             # 新增：订阅权限/配额（Phase 5）
server/api/v1/endpoints/admin.py               # 新增：status/clients/采集任务监控 等（Phase 4）
server/api/v1/endpoints/auth.py                # 改：新增客户端登录（Phase 5）
server/api/middlewares/auth.py                 # 改：客户端 token 分支（Phase 5）
server/src/services/symbol_list_service.py     # 改：落库 + 预热
server/src/services/realtime_ws.py             # 改：实时写入缓存（Phase 3）
server/api/app.py                              # 改：lifespan 启动采集守护 + 写队列
server/src/repositories/ (accounts/subscriptions/...)  # 新增数据访问层（Phase 5）
```

### 部署与基础设施
```
deploy/run_server.sh
deploy/com.hivelogic.server.plist
Dockerfile                                       # 新增（Phase 2）
docker-compose.yml                               # 新增（Phase 2）
doc/deploy/server_setup_macos.md
doc/deploy/docker_deploy.md                      # 新增：容器化部署说明
```

### 废弃/冻结
```
server/src/webui_frontend.py                     # 冻结：不再用于 SPA 托管（Phase 4 清理）
server/apps/dsa-web/                             # 不再新建：管理功能已嵌入客户端
server/static/                                   # 不再需要托管 SPA
```

---

## 八、风险与注意事项

1. **CORS/同源**：Electron 渲染进程 origin 特殊，远程连接时需仔细配置后端
   `allowed_origins`，避免内网图省事开 `CORS_ALLOW_ALL` 带到生产。
2. **数据一致性**：实时未收盘 K 线写缓存需正确标记 `is_complete` 并在收盘后更新。
3. **SQLite 并发**：采集守护与 REST/WS 同库读写，需确保 WAL + 写队列 + busy_timeout；
   分钟线热集合扩大后写压力上升，须预留迁移 PostgreSQL/TimescaleDB 的迁移点。
4. **数据源限流**：日线增量务必走全市场快照接口而非逐标的循环；多个采集器（L0/L1/L2）
   共享数据源额度，需统一限速/优先级编排，避免互相挤兑触发封禁。
5. **存储增长**：日线全量约 1 亿行可控；分钟线全量不可行，须严格限定 L2 热集合 + 保留窗口。
6. **定时漏跑**：`schedule` 库不补跑错过任务，必须实现 catch-up，否则宕机当日出现数据缺口。
7. **实时连接放大**：严禁每客户端对上游各开一条连接，必须经订阅管理器多路复用，否则
   客户端增多即触发数据源限流。
8. **鉴权双轨**：admin 鉴权（Phase 4 管理面板）与客户端鉴权（Phase 5 数据 API）并存，
   中间件分支要清晰，避免越权。
9. **网络环境**：Binance/OKX 在大陆可能需代理，服务端需稳定代理配置。
10. **客户端离线降级**：远程服务端不可达时，客户端应给出明确提示与（可选）本地后端兜底。
11. **凭据安全**：内网测试机口令（如 mac mini）不得写入代码库；token/密码哈希落盘需
    权限 0600。
12. **管理面板安全**：管理功能嵌入客户端后，需确保管理 API 有服务端鉴权兜底，
    不能依赖客户端隐藏入口作为安全手段。

---

## 九、实现核查记录（2026-06-29）

> 对照本计划逐阶段核查代码库后的结论。整体完成度高、文件与接线基本属实、
> 服务端测试 `109 passed`。初次核查发现 3 处「标记 ✓ 实际未真正落地/接线」的关键差距，
> **已于 2026-06-29 全部补全并通过验证**（详见下方更新记录）。

### 阶段完成度概览（2026-06-29 更新后）

| 阶段 | 结论 | 说明 |
|------|------|------|
| Phase 1 解耦 | ✅ 完成 | 8 处 + 遗留 3 处（StockAnalysis/News/chatService）均已走 `serverConfig` |
| Phase 2 部署/Docker | ✅ 文件齐全 | 脚本/plist/Dockerfile/compose/部署文档均存在 |
| Phase 3 采集归档 | ✅ 完成 | 写队列/实时写缓存/标的落库 OK；订阅管理器已接线、美股采集已补、8 个定时任务齐全 |
| Phase 4 管理面板 | ✅ 完成 | admin 端点 + AdminPanel + rest_tracker |
| Phase 5 鉴权订阅 | ✅ 完成 | entitlement 已挂到 market/stocks 数据端点（鉴权关闭时自动跳过） |
| Phase 6 稳定性安全 | ✅ 完成 | Caddy/health_monitor/rate_limit/备份任务/生产 compose 齐全 |
| Phase B Bot | ⬜ 未开始 | 后置独立阶段，按计划暂不实现 |

### 2026-06-29 补全记录（让已勾选项真正生效）

1. **Phase 5.3（已完成）** `entitlement.enforce_data_request` 挂到 `market.py`/`stocks.py`
   数据端点，含市场/周期标识归一化；鉴权关闭时自动跳过，内网零影响。
2. **Phase 3.5（已完成）** `RealtimeWSRelay` 真正接入 `SubscriptionManager`（引用计数 +
   多路复用 + LRU grace 退订），eviction loop 在 lifespan 启停。
3. **Phase 3.2/3.3/3.7（已完成）** 新增 `collect_us_stock` + 美股日线归档映射；调度器补注
   `us_stock_daily`(06:00) 与 `nightly_gap_reconcile`(02:00)，现共 8 个命名任务。
4. **Phase 1（已完成）** `StockAnalysis.vue`/`News.vue`/`chatService.ts` 改用 `getApiBase()`。
5. **工程（已完成）** `pyproject.toml` 新增 `[dependency-groups].dev`（pytest）。
6. **顺带修复** `app.py` 模块级 `Scheduler` 标注引用未导入导致 `import api.app` 抛 `NameError`
   的潜在启动阻断，已将其导入提升到模块顶层。

> 验证：`uv run --with pytest python -m pytest tests/` → `109 passed`；
> `import api.app; create_app()` 成功（136 路由），订阅管理器/美股采集/8 定时任务均确认就绪。
