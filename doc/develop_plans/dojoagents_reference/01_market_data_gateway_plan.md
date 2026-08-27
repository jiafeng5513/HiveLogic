# 行情数据收敛计划（统一数据网关）

> 创建日期：2026-07-29
> 状态：决策已确认，待启动
> 输入基线：[00_data_inventory.md](./00_data_inventory.md) 第一~三节（fetcher 清单/故障转移/持久化现状）
> 姊妹计划：[02_news_pipeline_refactor_plan.md](./02_news_pipeline_refactor_plan.md)（新闻/搜索管线）
> 性质：对应盘点文档"阶段 1（统一数据网关）"，工作性质是**收敛**，不是从零建设

---

## 〇、决策记录（2026-07-29 与用户确认）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 三处 K线存储的权威源 | **`kline_data`（+`kline_cache_meta`）为唯一权威源**——唯一具备缺口检测（`find_gaps`）和多市场支持。`stock_daily` 降级为分析衍生视图（从权威源构建）；`kline_cache` 淘汰（读适配过渡后删除） |
| 2 | TickFlow 定位 | **收进统一契约**——规范化其独立格式（list-of-dicts 日K、独立实时格式），纳入能力矩阵和故障转移；付费分档作为能力声明的一部分处理 |
| 3 | 熔断机制合并 | **保留 CircuitBreaker 语义**（closed/open/half-open 三态），**冷却曲线吸收 DataSourceChain 的指数退避**（2^fail 秒，上限 300s），并吸收 401/403 永久跳过逻辑 |

---

## 一、问题回顾（为什么收敛）

行情域是三个维度的分裂互相交织：

```
分裂 1（存储）：kline_cache（遗留）≠ kline_data（现代）≠ stock_daily（分析库）
分裂 2（故障转移）：DataFetcherManager（优先级循环）≠ DataSourceChain（指数退避）
分裂 3（接口契约）：BaseFetcher 只约束日K，其余能力靠 hasattr() 探测
```

最痛的具体后果（详见盘点文档）：

- **同一份 K线可能从网上拉三遍、存三份**——回测时 `stock_daily` 缺数据会走网络拉取，即使 `kline_data` 里已有
- **能力最全的 TickFlow 只有部分消费方可用**——它只注册在新链，老管理器不认识它
- **数据质量硬伤静默存在**：Tushare A股 vol×100/amount×1000 而港股不换算；`pct_chg` 首行恒 0 假象；`amount` 币种混乱；Pytdx 返回原生 dict 违反契约；`_calc_market_stats` 复制粘贴且含变量名冲突 bug
- **易失数据重启即丢**：实时缓存、WS 建的 1 分钟 K线全在内存

收敛的铁律（来自盘点）：**不能推翻重写**——`DataFetcherManager` 被 stock_service/backtest/market_analyzer 等 6+ 消费方使用，网关只能是包裹层。

---

## 二、目标架构

```
┌──────────────── 消费方（全部不变）────────────────┐
│ stock_service / backtest / market_analyzer /      │
│ pipeline / TradingView UDF / bot / Agent 工具      │
└──────────────────────┬───────────────────────────┘
                       ▼
┌──────────────── MarketDataGateway（包裹层）────────┐
│  · 统一入口：get_kline / get_realtime / get_fund…  │
│  · 路由表：markets × datatypes → 源链（合并两套）  │
│  · 统一熔断器：CB 三态 + 指数退避冷却 + 401/403 跳过│
│  · 统一异常族：Timeout/Unavailable/BadResponse/    │
│    RateLimited/AuthFailed                          │
└──────┬───────────────────┬───────────────────────┘
       ▼                   ▼
┌─────────────┐   ┌─────────────────────────────────┐
│ KlineStore   │   │ Fetcher 层（10 个，全部保留）     │
│ 唯一读写入口  │   │ · 能力声明矩阵替代 hasattr 探测   │
│ 权威=kline_  │   │ · 统一规范化：单位/币种/pct_chg   │
│ data         │   │ · TickFlow 收编进同一契约        │
└──────┬──────┘   └─────────────────────────────────┘
       ▼
┌─────────────────────────────────────┐
│ kline_data（权威）→ stock_daily（衍生视图，含MA/量比）│
│ kline_cache（读适配过渡 → 删除）                     │
└─────────────────────────────────────┘
```

**设计要点**：
- 消费方 API 签名不变——网关是包裹层，第一阶段甚至可以只是"代理 + 埋点"
- 读路径先统一（Phase 2），写路径跟随；故障转移收敛（Phase 3）在读取统一之后做，因为那时路由决策已有统一数据可依
- 新闻管线 Phase 2 的 `providers/base.py`（熔断/健康/配额）与本计划的治理基座**同源设计**，异常族完全一致

---

## 三、四个阶段

### Phase 1：契约与治理基座（非侵入）

**目标**：不改动任何数据流，先把"度量衡"统一。

1. **能力声明矩阵**：每个 fetcher 声明 `markets × datatypes` 能力（盘点文档 1.2 覆盖矩阵直接作为初始数据）；`hasattr()` 探测点全部改为查矩阵，行为不变
2. **统一异常族**：`GatewayError` 基类 + Timeout/Unavailable/BadResponse/RateLimited/AuthFailed；各 fetcher 的裸异常在边界处转译，暂不改变传播路径
3. **公共逻辑收拢**：
   - `_is_etf_code` / `_is_us_code` 等各 fetcher 私有副本 → 单一实现
   - `_calc_market_stats` 两份复制粘贴合并，**修掉 `tushare_fetcher.py:924` 变量名冲突 bug**
4. **规范化规则文档化 + 落地**：
   - 单位：统一 vol/amount 基准量纲（消除 Tushare A股 ×100/×1000 与港股不换算的混乱）
   - `pct_chg`：统一语义（源直给优先，本地计算时明确首行 NaN 而非 0）
   - `amount`：增加币种标记或统一折算，消除币种语义混乱
5. 每个收拢点配单元测试（这是现状零覆盖区域）

**验收**：能力矩阵与 1.2 表一致；全部现有调用方行为不回归；规范化前后数据 diff 报告（**允许值变化、必须可解释**——单位修正会改变数值，这是预期内的）。

**风险**：规范化修正会改变分析/回测的输入数据，需 diff 测试圈定影响面。

### Phase 2：K线读取路径统一（决策 1 落地）

**目标**：三处存储收敛为一权威 + 一衍生，回测不再重复拉网。

1. `KlineStore` 单一读写入口：封装 `kline_data` + `kline_cache_meta`（缺口检测、TTL 分级逻辑收拢进来）
2. **`kline_cache` 淘汰**：存量数据比对迁移（仅迁 `kline_data` 没有的）→ 改为只读适配 → 所有写入停止 → 删表
3. **`stock_daily` 衍生化**：
   - 构建同步任务：从 `kline_data` 增量构建 stock_daily（附加 MA5/10/20、volume_ratio）
   - 分析管线/回测的读取改走 `KlineStore` 门面（缺数据时从权威源取 + 现场算衍生列），**删除回测的独立网络拉取路径**
4. TradingView UDF、MarketGateway 的读路径切到 `KlineStore`

**验收**：回测在 `kline_data` 有数据时**零网络请求**（可断言）；`stock_daily` 与权威源数据一致性抽查；`kline_cache` 零写入后无功能回归。

**风险**：中。消费方多，建议双读比对期（新旧路径并行读、记录 diff 不拦截）后再切换。

### Phase 3：故障转移收敛 + TickFlow 收编（决策 2、3 落地）

**目标**：两套故障转移合并为网关路由表，TickFlow 成为一等公民。

1. **统一熔断器**：CircuitBreaker 三态语义 + 指数退避冷却（2^fail 秒，上限 300s）+ 401/403 永久跳过；按 `(source, datatype)` 维度各一个实例，替换现有两个并行实现
2. **路由表合并**：`DataSourceChain` 的类别注册（`symbols:cn_stock` / `kline:hk` / `realtime:cn` 等）与 `DataFetcherManager` 的优先级循环合并为一张显式路由表；`config.realtime_source_priority` 等环境变量覆盖能力保留
3. **TickFlow 收编**：
   - 日K：list-of-dicts → `STANDARD_COLUMNS` 管线（`tickflow_fetcher.py:103-113` 改造）
   - 实时：独立格式 → `UnifiedRealtimeQuote`
   - 能力矩阵注册（美/港/A + 基本面），付费分档声明为能力约束
   - 从"优先级 99 不在管理器"变为正常链内位置
4. **Pytdx 契约修复**：`get_realtime_quote` 返回 `UnifiedRealtimeQuote`（`pytdx_fetcher.py:407-444`）
5. 实时报价主源字段补全逻辑（从副源补 volume_ratio/PE/市值）迁入网关
6. `MarketCollector` 保持独立采集，但写入改走 `KlineStore`

**验收**：单源故障时全消费方走同一条降级链（日志可证）；TickFlow 通过统一契约服务日K+实时+基本面；TickFlow key 失效时 401/403 永久跳过且告警。

**风险**：中高。`DataFetcherManager` 行为复杂（2600+ 行），包裹层先做"代理+埋点"跑影子期，确认路由决策一致后再接管。

### Phase 4：数据资产补强（P2 缺口，部分可选）

1. **易失数据持久化**：实时缓存、WS CandleBuilder 的 1 分钟 K线落 SQLite/parquet，重启恢复（盘中重启不再归零）
2. **L0 快照历史**：`market_snapshot` 改追加写或按日归档，保留时序；在此基础上支持 `as_of` 历史窗口查询（参考 DojoAgents 的 `as_of=YYYY-MM-DD` 右边界裁剪模式）
3. **`fundamental_snapshot` 打通读路径**：分析时先查快照再决定拉网（消除只写不读）
4. **列式存储评估**：duckdb/parquet 作为分析/回测读取引擎的可行性验证（POC 先行，不直接迁移）

**验收**：重启后分钟线可恢复；基本面分析命中快照时零网络请求；列式 POC 有明确性能对比数据支撑后续决策。

---

## 四、与新闻管线计划的关系

| 共享资产 | 新闻管线 | 本计划 |
|---|---|---|
| 统一异常族 | Phase 2 落地 | Phase 1 落地（同源定义，放公共模块） |
| 熔断/健康/配额基座 | `search/providers/base.py` | 统一熔断器（Phase 3）——语义一致，实现各自轻量 |
| 治理模式 | 能力声明 + 注册表 | 能力矩阵 + 路由表 |

两个计划可并行推进，但**异常族定义应先在公共模块落地一次**，两边引用，避免第三套并行定义。

---

## 五、工作量与顺序

| 阶段 | 预估 | 依赖 |
|---|---|---|
| Phase 1 契约与治理基座 | 2 天 | 无，可立即启动 |
| Phase 2 K线读取统一 | 2-3 天 | Phase 1 的规范化规则 |
| Phase 3 故障转移收敛+TickFlow | 3 天 | Phase 2（读取统一后路由有依据） |
| Phase 4 资产补强 | 2 天+（POC 另计） | 独立，可与 2/3 并行 |

总计约 1.5~2 周量级。Phase 4 各项相对独立，可按需裁剪。

## 六、测试要求

- 能力矩阵完整性测试（矩阵声明 vs 实际行为抽查）
- 规范化 diff 测试（单位/pct_chg/币种修正前后对比，变化必须可解释）
- `KlineStore`：缺口检测、TTL 分级、双读比对
- 统一熔断器：三态流转 + 指数退避曲线 + 401/403 永久跳过
- 集成：回测零网络断言、TickFlow 全链路、降级链一致性
