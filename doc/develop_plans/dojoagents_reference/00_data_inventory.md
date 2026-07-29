# HiveLogic 数据现状盘点

> 盘点日期：2026-07-28
> 范围：`server/data_provider/`、`server/src/services/`、`server/src/search_service.py`、`server/src/storage.py`
> 用途：阶段 1（统一数据网关）设计的输入基线
> 上游文档：[dojoagents_reference_analysis.md](./dojoagents_reference_analysis.md) 第九节（数据方向）
> 衍生计划：[01_market_data_gateway_plan.md](./01_market_data_gateway_plan.md)（行情数据收敛）、[02_news_pipeline_refactor_plan.md](./02_news_pipeline_refactor_plan.md)（新闻/搜索管线重构）

---

## 〇、总体判断

**问题不是"没有基础设施"，而是"同一能力存在 2-3 套并行实现"**：

- K线存储有 **3 处**（`kline_cache` 遗留表 / `kline_data` 现代表 / `stock_daily` 分析库表），互不同步
- 故障转移有 **2 套**（`DataFetcherManager` 传统优先级循环 / `DataSourceChain` 指数退避链），外加独立的 `MarketCollector`
- 新闻管线有 **2 条**（`search_service.py` 七源搜索 / `news_crawler/` 东财爬虫），互不相通

统一网关的工作性质是**收敛**，不是从零建设。

---

## 一、行情数据源清单（10 个 fetcher）

### 1.1 基础接口（`data_provider/base.py`）

`BaseFetcher` 抽象类**只强制约束日K线一条路径**：
- `_fetch_raw_data()` → `_normalize_data()` → 统一 `STANDARD_COLUMNS`（date/open/high/low/close/volume/amount/pct_chg）
- 模板方法 `get_daily_data()` 附带 MA5/10/20、volume_ratio 计算

其余一切能力（实时报价、指数、市场统计、板块排名、筹码分布、股票名称、股票列表）**不在接口契约内**，靠 `hasattr()` 探测——这是"snowflake"现状的根源。

### 1.2 覆盖矩阵

| Fetcher | 优先级 | 认证 | A股 | 港股 | 美股 | 加密 | 日K | 实时 | 基本面 | 筹码 | 指数 | 板块排名 | 股票列表 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Efinance | 0 | 无 | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| Akshare | 1 | 无 | ✅ | ✅ | ❌ | ❌ | ✅ | ✅(3后端) | ✅ | ✅ | ❌ | ❌ | ❌ |
| Tushare | -1(有token)/2 | TUSHARE_TOKEN | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Pytdx | 2 | 无 | ✅ | ❌ | ❌ | ❌ | ✅ | ⚠️返回dict | ❌ | ❌ | ❌ | ❌ | ❌ |
| Baostock | 3 | 匿名登录 | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Yfinance | 4 | 无 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Longbridge | 5 | 3个key | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅(衍生) | ❌ | ❌ | ❌ | ❌ |
| Binance | 6 | 可选 | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| OKX | 7 | 可选 | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| TickFlow | 99(不在管理器) | TICKFLOW_API_KEY | ✅ | ✅ | ✅ | ❌ | ✅(独立格式) | ✅ | ✅(付费档) | ❌ | ✅ | ❌ | ✅ |

优先级可被环境变量覆盖（`EFINANCE_PRIORITY` 等）。

### 1.3 关键不一致项

| 问题 | 位置 |
|---|---|
| Pytdx 的 `get_realtime_quote` 返回原生 dict，违反 `UnifiedRealtimeQuote` 契约 | `pytdx_fetcher.py:407-444` |
| TickFlow 完全不走 BaseFetcher 日K管线（返回 list-of-dicts） | `tickflow_fetcher.py:103-113` |
| `_calc_market_stats` 在 Tushare/Efinance 中复制粘贴（含变量名冲突 bug） | `tushare_fetcher.py:924` / `efinance_fetcher.py:908` |
| `_is_etf_code`/`_is_us_code` 每个 fetcher 各写一份 | 全部 fetcher |
| `amount` 币种语义不一（人民币/港币/美元/USDT/估算值） | 各 `_normalize_data` |
| 单位换算不一致：Tushare A股 vol×100、amount×1000，港股不换算 | `tushare_fetcher.py:544-548` |
| `pct_chg` 来源不一（源直给 vs 本地 pct_change 计算，首行恒为 0） | 各 fetcher |
| 实时缓存 TTL 不一（efinance 600s vs akshare 1200s） | 两 fetcher |

---

## 二、故障转移机制现状（两套并行 + 一个独立采集器）

### 2.1 `DataFetcherManager`（传统，base.py L471-2638）
- 日K：缓存优先 → 按市场硬编码路由（crypto→Binance→OKX；US→Longbridge/Yfinance 互备；CN/HK→优先级循环）
- 实时报价：按 `config.realtime_source_priority` CSV 链式尝试，支持**主源字段补全**（从副源补 volume_ratio/PE/市值等）
- `CircuitBreaker`：3 次失败 → 300s 冷却 → 半开探测（实时报价与筹码各一个实例）

### 2.2 `DataSourceChain` + `MarketGateway`（较新，src/services/）
- 按类别注册链：`symbols:cn_stock → TickFlow→AKShare`、`kline:hk → TickFlow`、`realtime:cn → TickFlow→DataFetcherManager` 等
- 指数退避 2^fail_count 秒（上限 300s），401/403 永久跳过

### 2.3 `MarketCollector`（独立采集器）
- 周期性批量快照写入 `market_snapshot` 表（L0），可归档为日K（L1）
- 不参与故障转移

**问题：两套系统的优先级逻辑各自为政，TickFlow 只在新链里，老管理器不认识它。**

---

## 三、持久化现状

### 3.1 两个 SQLite 库

| 库 | 管理方 | 主要内容 |
|---|---|---|
| `data/stock_analysis.db` | SQLAlchemy ORM（`storage.py`） | stock_daily、news_intel、fundamental_snapshot、analysis_history、backtest_*、portfolio_*、llm_usage |
| `data/market_cache.db` | 裸 sqlite3（5+ 个模块各自操作） | symbol_cache、kline_cache（遗留）、kline_data+kline_cache_meta（现代）、market_snapshot、crawled_news、scheduler_task_log |

### 3.2 K线三处存储（核心冗余）

| 存储 | 表 | 特点 | 消费方 |
|---|---|---|---|
| 遗留 | `kline_cache` | 无 market 字段、无缺口检测 | MarketGateway 兜底 |
| 现代 | `kline_data` + `kline_cache_meta` | 多市场、缺口检测（`find_gaps`）、TTL 分级（1m→30d, 1d→永久） | TradingView 图表、MarketGateway 首选 |
| 分析库 | `stock_daily` | 含 MA/量比，仅 A股 | 分析管线、回测 |

三处**互不同步**：回测时 `stock_daily` 缺数据会走网络拉取，即使 `kline_data` 里已有。

### 3.3 易失数据（重启即丢）

- `MarketGateway._realtime_cache`（内存 dict，600s TTL）
- WS tick 流建的 1 分钟 K 线（`realtime_ws.py` CandleBuilder，纯内存）
- SearchService 搜索缓存（内存，600s TTL，500 条上限）
- 社媒情绪缓存、name-to-code 缓存

### 3.4 其他缺口

- **无任何列式存储**（无 parquet/duckdb）
- `fundamental_snapshot` 是**只写不读**（P0 遗留，分析时每次重新拉取）
- L0 快照每轮全量覆盖，**无历史**
- 新闻两处去重互不相通（`news_intel` 按 URL / `crawled_news` 按 dedupe_key）

---

## 四、新闻/搜索管线

### 4.1 七个搜索源（`search_service.py`，3480 行）

| 优先级 | Provider | 免费额度 | 熔断 |
|---|---|---|---|
| 0 | Anspire（insert(0) 置顶） | 不明（付费） | ❌ |
| 1 | Bocha（中文优化） | 不明 | ❌ |
| 2 | Tavily | 1000 次/月 | ❌ |
| 3 | Brave | 有免费档 | ❌ |
| 4 | SerpAPI（Google） | 100 次/月 | ❌ |
| 5 | MiniMax | Coding Plan | ✅（3连败→300s） |
| 6 | SearXNG | 自建免费/公共实例 | 实例轮换 |

已有机制：key 轮换（错误≥3 跳过）、A股优先中文源、新鲜度过滤（news_max_age_days 与策略档位取小）、超采（×2）、in-flight 去重。

### 4.2 不稳定根因（按严重度）

1. **缓存纯内存**——重启即冷启动，所有源同时被打
2. **主搜索路径无跨源去重/合并**——只取"最佳单源"结果，不做多源汇聚
3. **无健康探测**——源宕机数小时仍每次先试它，白白增加延迟
4. **仅 MiniMax 有熔断**，其余源没有
5. **SearXNG 公共实例不稳**（5s×3 次=最多 15s 才降级）
6. **newspaper3k 正文抽取**：5s 单次超时、无重试、主线程阻塞、错误静默吞
7. **配额耗尽无声**：Tavily 1000/月、SerpAPI 100/月，key 错误计数进程内，重启清零
8. **`news_crawler/` 东财爬虫子系统完全独立**，结果不与搜索管线汇合

---

## 五、与 DojoAgents 对照

| 能力 | DojoAgents | HiveLogic 现状 | 差距性质 |
|---|---|---|---|
| 统一网关 | `dojo_data_gateway`：GatewayResult + 错误族（Timeout/Unavailable/BadResponse） | 两套并行故障转移，异常模型不统一 | **收敛** |
| K线存储 | 单一份 parquet 快照 + 窗口计算 | 三处 SQLite 表互不同步 | **收敛** |
| 实时数据 | 快照 + 实时尾巴延伸 | 内存即丢 | **补建** |
| 板块分类 | L1/L2/L3 远端资产 | 完全缺失（仅 `get_belong_board`/`get_sector_rankings` 零散能力） | **新建** |
| 新闻 | 远端 `analysis.get_market_dynamics` 结构化事件 | 七源搜索 + 独立爬虫，无合并无持久缓存 | **整合** |
| 数据新鲜度 | manifest + 小时级刷新循环 | CacheMaintenance TTL 清理（已较好） | 基本持平 |

---

## 六、对阶段 1（统一数据网关）的输入

设计网关时必须面对的既有事实：

1. **不能推翻重写**——`DataFetcherManager` 被 stock_service/backtest/market_analyzer 等 6+ 消费方使用；网关应是包裹层
2. **能力声明替代 hasattr 探测**——每个 fetcher 声明 markets × datatypes 能力矩阵（1.2 表可直接作为初始数据）
3. **统一异常模型**——借鉴 GatewayError 族：Timeout / Unavailable / BadResponse / RateLimited / AuthFailed（401/403 永久跳过逻辑已有雏形）
4. **K线读取路径先统一**——三处存储确定唯一权威源（建议 `kline_data`，它有缺口检测），其余做兼容适配
5. **TickFlow 的定位要决策**——它能力最全（美/港/A + 基本面）但格式独立、付费分档，是收进统一契约还是保持旁路
6. **两套熔断/退避逻辑合并**——CircuitBreaker（300s）与 DataSourceChain 指数退避取其一
