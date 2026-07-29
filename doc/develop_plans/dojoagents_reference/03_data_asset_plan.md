# 03 数据资产化计划：板块分类 / 预计算管线 / 持久化与主数据治理

> 创建日期：2026-07-29
> 状态：待决策确认后启动
> 上游文档：[00_data_inventory.md](./00_data_inventory.md)、[dojoagents_reference_analysis.md](./dojoagents_reference_analysis.md) 第 9.3 节（阶段 3/4）
> 姊妹计划：[01_market_data_gateway_plan.md](./01_market_data_gateway_plan.md)、[02_news_pipeline_refactor_plan.md](./02_news_pipeline_refactor_plan.md)
> 范围：01（行情）、02（新闻）之外的**剩余数据域**——板块分类、每日预计算、持久化治理、主数据、缓存维护

---

## 〇、定位与边界

分析文档 9.3 的数据方向五阶段中：阶段 1（统一网关）= 01 计划；阶段 2 的 K线持久化部分在 01 Phase 4；**本计划 = 阶段 2 剩余 + 阶段 3（板块分类）+ 阶段 4（每日预计算）+ 贯穿性的持久化/主数据治理**。

| 域 | 性质 | 对应 9.3 |
|---|---|---|
| 持久化治理 + 主数据 | **收敛/补建**（基座，先行） | 贯穿 |
| 板块分类体系 | **新建**（对照 Dojo 的 L1/L2/L3 taxonomy 资产） | 阶段 3 |
| 每日预计算管线 | **新建/接线**（代码已写好但没接调度） | 阶段 4 |
| 缓存维护扩展 | **补建** | 贯穿 |

**明确不在本计划内**（避免与 01/02 重叠）：
- K线三存储收敛、`kline_data` 权威源、列式存储 **POC** → 01 计划
- `fundamental_snapshot` 读路径打通 → 01 Phase 4（本计划只在其之上做"基本面资产化"的衔接）
- 新闻两表合并 → 02 计划

---

## 一、现状盘点（2026-07-29 探索确认）

### 1.1 板块分类：完全没有本地化

- 唯一实现：`efinance_fetcher.get_belong_board()`（L1082），**每次实时调 efinance API**
- `akshare_fetcher.get_sector_rankings()`（L1748）：只有排名，无缓存
- `_normalize_belong_boards()` 有**两份重复实现**（`base.py:734` / `data_processing.py:43`）
- 消费方 5 处（pipeline / portfolio_risk / data_tools / efinance 增强数据 / data_processing）各自实时调用
- **无本地板块成分表、无快照、无增量更新**——Dojo 对照中的"新建"缺口，也是热图/榜单类 UI 的前置条件

### 1.2 预计算：代码写好了但没接上

- `MarketCollector.collect_all()`（全市场行情快照）+ `archive_daily_from_snapshot()`（快照→日线归档）**逻辑完整，但从未注册为定时任务**
- `Scheduler` 当前只注册了 1 个每日任务：`run_full_analysis()`
- 不存在"每日快照→计算→校验→发布"管线；Dojo 的 `precompute_sector_daily.py` 结构可照搬
- `market_snapshot`（L0）每轮全量覆盖，无历史（盘点已记录）

### 1.3 持久化：双库并存，裸 sqlite3 六处开花，schema 无版本

- `market_cache.db` 被 **6 个模块**用裸 sqlite3 各自操作（scheduler / market_cache / kline_cache_manager / market_collector / cache_maintenance / symbol_list_service，另有 watchlist），连接/PRAGMA 管理各写各的，存在隐式锁竞争
- `stock_analysis.db` 由 SQLAlchemy 管理（16+ 表），**但探索发现物理文件疑似不存在**（配置默认路径 `./data/stock_analysis.db` 可能依赖 CWD）——**P0 待核实**：若属实，等于 ORM 库一直在一个"临时位置"建库，数据可能散落在不同工作目录
- 无 alembic；手写 try-ALTER 迁移散落三处（`storage.py:762-846`、`market_cache.py:114-136`）
- 无任何 parquet/duckdb 文件

### 1.4 主数据：三套映射 + 两套 symbol 表

- name-to-code 有 **3 套**：`stock_mapping.py` 硬编码 ~100 只（永不更新）/ `stocks.index.json`（前端 build 产物）/ AkShare 在线回落（30min 缓存）
- symbol 缓存有 **2 套**：`symbol_cache` 表（带拼音，24h TTL，全量替换刷新）/ `symbol_list` 表（symbol_list_service）
- 交易日历：依赖 `exchange_calendars` 库，fail-open，无本地缓存

### 1.5 CacheMaintenance：只管 K线

- 现有：kline TTL 分级清理（1m→30d … 1d→永久）、task_log 90d、VACUUM、磁盘/新鲜度统计——这部分已较好
- **未覆盖**：`market_snapshot`（无 TTL）、`symbol_list`（只读时判过期，无主动清理）、`watchlist`、未来的板块表/预计算产物

### 1.6 fundamental_snapshot：资产化起点已具备

- payload 结构良好（成长/财报/分红/机构 + source_chain 追踪），写入方就绪；读路径打通在 01 Phase 4，本计划衔接其成为"基本面资产"

---

## 二、目标架构

```
┌─────────── 基座（Phase 1）───────────┐
│  统一 DB 访问层（收拢 6 处裸 sqlite3）  │
│  迁移纪律（版本化迁移脚本）             │
│  SymbolMaster（单一权威 symbol 主数据） │
│  交易日历本地缓存                       │
└──────┬─────────────────┬─────────────┘
       ▼                 ▼
┌─────────────┐   ┌──────────────────────────┐
│ 板块分类体系  │   │ 每日预计算管线              │
│ board/       │   │ collect → archive →       │
│ constituents │──→│ compute → validate →      │
│ 本地表+日刷新 │   │ publish（parquet 快照）    │
└──────┬──────┘   └───────────┬──────────────┘
       │                      │
       ▼                      ▼
  消费方切换（5处）        板块日指标 / 榜单 / 热图数据
  （消除实时调用）        （Agent 工具 + UI 的数据底座）
```

---

## 三、四个阶段

### Phase 1：持久化与主数据基座（收敛，先行）

**目标**：把"地基"收拢，后续所有新表都长在规范上。

1. **P0 核实 `stock_analysis.db` 路径问题**：确认物理文件位置与 CWD 依赖；统一为绝对路径（基于 server 根目录解析），如有多处散落的 DB 文件做归并
2. **统一 DB 访问层**：`market_cache.db` 的 6 处裸 sqlite3 收拢为单一访问模块（统一连接管理、WAL/PRAGMA、异常边界）；各模块改为调用访问层，不直接 `sqlite3.connect`
3. **迁移纪律**：引入版本化迁移机制——轻量方案（`schema_migrations` 表 + 编号 SQL 脚本目录）或 alembic，二选一；现有三处手写 try-ALTER 迁移收编为初始版本记录
4. **SymbolMaster 单一权威**：
   - 合并 `symbol_cache` / `symbol_list` 为一张 symbol 主表（保留拼音、exchange、currency、status 字段）
   - name-to-code 三套映射统一为层级策略：**SymbolMaster（DB）→ 内存缓存 → 在线回落**；`stock_mapping.py` 硬编码迁移入库后删除；`stocks.index.json` 改为从 SymbolMaster 导出的 build 产物
   - 全量替换刷新 → **增量刷新**（按 updated_at 差量 + 定期全量校验）
5. **交易日历本地化**：`exchange_calendars` 结果落本地缓存表（市场 × 日期，预存 3 年），消除运行时依赖与 fail-open 的不确定性

**验收**：全代码库无直接 `sqlite3.connect`（访问层除外）；迁移机制下 `PRAGMA user_version` 可追溯；`stock_mapping.py` 删除后 name-to-code 命中率不下降；日历离线可用。

### Phase 2：板块分类体系（新建）

**目标**：本地板块成分表 + 每日刷新，消除 5 处实时调用。

1. **新表设计**：
   - `board`（板块主表）：board_code / name / type（行业/概念/地域）/ source / updated_at
   - `board_constituent`（成分表）：board_code × symbol × market，含权重/纳入日期，快照式存储
   - 分类标准：**东财行业 + 概念板块先行**（akshare 接口现成、覆盖 A股全市场），申万作为后续可选增补（接口需评估）——⚠️ 决策点 1
2. **每日刷新任务**：收盘后全量拉取板块列表 + 成分，快照写入（保留历史，支持"T 日成分"查询）；增量校验（成分变动打 log，这是天然的事件信号源）
3. **消费方切换**：5 处消费方（pipeline / portfolio_risk / data_tools / efinance / data_processing）从实时 API 改为查本地表；`_normalize_belong_boards` 两份重复实现随之删除
4. **板块级聚合指标**（为 Phase 3 供数据）：板块涨跌幅、涨跌家数、涨停数——先落表，供后续榜单/热图 UI 和 Agent 工具消费

**验收**：个股分析全流程零板块 API 实时调用；板块成分可回溯任意交易日；板块聚合指标与东财口径抽查一致。

### Phase 3：每日预计算管线（新建/接线）

**目标**：照搬 Dojo `precompute_sector_daily.py` 的 snapshot→compute→validate→stage→publish 结构，把"已写好但没接上"的代码变成数据资产。

1. **接线**：`MarketCollector.collect_all()` + `archive_daily_from_snapshot()` 注册为 Scheduler 命名每日任务（收盘后，如 15:30/16:00），进 `scheduler_task_log` 享受 catch-up 机制
2. **显式编排**：collect → archive →（板块指标 compute）→ 形成任务 DAG，每步状态可观察（替代隐式顺序调用）；失败可单步重跑
3. **parquet 产物**：每日预计算结果落 parquet 快照（`data/precompute/YYYY-MM-DD/*.parquet`）——与 01 Phase 4 的列式 POC 呼应，但本阶段只产出"预计算产物"，不动 K线存储引擎
4. **validate→publish 纪律**：校验规则（行数/字段非空/涨跌幅合理区间）通过后标记 publish；消费方只读 published 快照
5. **首批预计算产物**：板块日指标（涨幅/涨跌家数/涨停数/成交占比）、市场宽度（涨跌平家数、新高新低）、自选股日摘要

**验收**：任务连续 N 日自动跑通（task_log 可证）；失败日 catch-up 补跑成功；parquet 产物 schema 稳定，Agent 工具/未来 UI 可离线读取。

### Phase 4：缓存维护扩展（补建）

1. 清理范围扩展到：`market_snapshot`（TTL 策略，如 90d）、`symbol_list` 旧表（Phase 1 合并后清退）、`watchlist`、板块历史快照（保留窗口，如 2 年）、预计算 parquet（保留窗口 + 磁盘配额）
2. 保留策略外置为配置（不再硬编码）
3. `get_disk_usage()` 统计覆盖新表/新目录

**验收**：全部数据资产有明确保留策略；清理任务 dry-run 输出可审。

---

## 四、待决策点

| # | 决策点 | 选项 | 我的建议 |
|---|---|---|---|
| 1 | 板块分类标准 | 东财行业+概念 / 申万 / 两者并存 | **东财行业+概念先行**（akshare 现成、全市场覆盖）；申万接口稳定性待评估，作后续增补 |
| 2 | 迁移机制 | 轻量编号 SQL 脚本 / alembic | **轻量编号脚本**——单机 SQLite 场景 alembic 过重，且 market_cache.db 是非 ORM 库 |
| 3 | 板块快照保留 | 全量历史 / 窗口（如 2 年） | 成分表全量历史（行小），聚合指标窗口管理 |
| 4 | 启动顺序 | 本计划 vs 01/02 的先后 | 见下节 |

## 五、与 01/02 的关系及启动顺序建议

- **依赖 01**：Phase 3 预计算的日线归档理想情况下走 01 的 `KlineStore`；若 01 未启动，Phase 3 先按现状接 `archive_daily_from_snapshot`，01 落地后再切
- **依赖 02**：无硬依赖（新闻管线独立）
- **建议顺序**：**01 Phase 1-2（K线收敛）→ 03 Phase 1（基座）→ 03 Phase 2/3 → 02 可与任意阶段并行**
  - 理由：03 Phase 1 的 DB 访问层会给 01/02 的新表（news_item、KlineStore）提供统一地基；03 Phase 2/3 是"数据资产化"的见效主力（板块+预计算是 Agent/UI 方向的前置）
  - 若只选一个最先做：**01 Phase 1-2**（治最痛的"拉三遍存三份"）

## 六、工作量

| 阶段 | 预估 | 依赖 |
|---|---|---|
| Phase 1 持久化与主数据基座 | 2-3 天 | 无 |
| Phase 2 板块分类体系 | 2-3 天 | Phase 1（SymbolMaster/DB 访问层） |
| Phase 3 每日预计算管线 | 2-3 天 | Phase 2（板块表）；01 的 KlineStore（可选增强） |
| Phase 4 缓存维护扩展 | 1 天 | Phase 1-3 的新资产就位 |

总计约 1.5 周量级。

## 七、测试要求

- DB 访问层：并发读写、锁竞争回归、WAL 行为
- 迁移机制：从空库到最新版本、从各历史版本升级、幂等
- SymbolMaster：三套旧映射的一致性 diff（迁移前跑报告，名称/代码冲突清单人工确认）
- 板块表：成分快照可回溯、增量变动检测正确性
- 预计算：validate 规则单测；publish 门禁（脏数据不发布）；catch-up 补跑
