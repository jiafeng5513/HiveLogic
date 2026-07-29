# DojoAgents 项目借鉴分析

> 调研日期：2026-07-28
> 参考项目：`D:\ProjectsSoftware\Treading\DojoAgents`
> 目标项目：HiveLogic（当前仓库）

---

## 一、两个项目的定位对比

| | **HiveLogic**（当前项目） | **DojoAgents**（参考项目） |
|---|---|---|
| 定位 | A股自选股智能分析 + Electron 桌面交易终端（TradingView 图表） | 全市场 LLM Agent 运行时（个人投资 copilot） |
| 架构 | Electron+Vue 客户端 / FastAPI 服务端 / Docker sandbox / bot 命令 | 纯 Python 包 + FastAPI 仪表盘 + React SPA |
| 已有能力 | Gemini 分析器、搜索服务、回测、定时任务、策略 skill、bot 命令、事件监控 | Agent Loop、工具注册/沙箱、技能蒸馏、记忆、插件、多智能体、规划引擎、Cron、聊天网关 |
| 技术栈 | Python(FastAPI) + Vue/Electron + uv | Python>=3.11(FastAPI, strands-agents, mcp) + React19/Vite + uv |

DojoAgents 是一个**成熟度更高的 Agent 运行时**，它的很多基础设施正是 HiveLogic 目前用"土办法"实现的。

---

## 二、高价值借鉴（架构级）

### 1. Agent Loop 引擎 —— `dojoagents/agent/loop.py`（1523 行，核心资产）

HiveLogic 目前是"单次 LLM 调用生成报告"模式（`server/src/analyzer.py::GeminiAnalyzer`）。DojoAgents 的 Loop 实现了：

- **多轮工具编排**：LLM 决定调工具 → 执行 → 结果回注 → 继续推理
- **上下文压缩**：`agent/compressor.py` + `agent/token_ledger.py` + `agent/token_policy.py`，长会话不爆 token
- **防金融幻觉护栏**：`agent/guardrails.py::ToolCallGuardrailController`
- **Harness 任务校验**：`agent/harnesses/tool_orchestrated.py` 提供：
  - 工具预算（`tool_budget`，按工具名限制调用次数）
  - 每轮最大工具调用数（`max_tool_calls_per_turn`）
  - 进度校验（`validate_progress`）
  - 失败恢复 prompt（`build_recovery_prompt`）—— agent 跑偏会被拉回

**借鉴价值**：HiveLogic 的 `/ask` 分析可升级为"多轮工具调用"模式（先拉行情 → 再查新闻 → 再算指标 → 最后成文），而不是一次性把数据塞进 prompt。

### 2. 工具系统三件套 —— `tools/registry.py` + `tools/executor.py` + `SandboxPolicy`

- `ToolSpec`（name / description / parameters / async handler / sandbox_policy）
- `ToolRegistry`（注册 / get / schema_list / clone / remove）
- `ToolExecutor.execute_one()` 是 AGENTS.md 钦定的"黄金模式"：
  - 统一超时（`asyncio.wait_for(timeout=sandbox.timeout_seconds)`）
  - 延迟统计（`latency_ms`）
  - 结构化 `ToolResult(ok / error / content / data)`
  - 异常边界 `LOGGER.exception()`，绝不静默吞异常
- `SandboxPolicy(allowed_roots, allow_network, allowed_commands, timeout_seconds)` + 多执行环境适配器（local / Docker / SSH / Modal，见 `tools/environments/`）

**借鉴价值**：HiveLogic 的 `sandbox/` 目前只有一个 Dockerfile + 数据脚本，可以把策略执行、指标计算纳入带策略管控的沙箱，并统一工具执行的错误模型。

### 3. ConfigStore 配置体系 —— `config/loader.py` + `config/models.py`

- 冻结 dataclass 类型化 schema（`AgentsConfig`），YAML 存储（默认 `~/.dojo/agents.yaml`）
- 环境变量展开、深合并（`_deep_merge`）
- **`redacted()`**：API 暴露时自动脱敏 API key
- `snapshot()` 读 / `raw()` + `save_raw()` 写，支持 UI 直接改配置
- 配套仪表盘图形化设置页：OpenAI / Anthropic / Gemini / 智谱 / DeepSeek 预设 + 自定义 Base URL（可接 Ollama / vLLM 等本地端点）

**借鉴价值**：HiveLogic 目前靠 `.env` + `get_config()`，WebUI/bot 无法安全地读写配置。这套模式可直接搬到 FastAPI 端做设置页。

---

## 三、中价值借鉴（机制级）

### 4. 技能蒸馏与记忆 —— `skills/manager.py` + `memory/skill_summary.py`

DojoAgents 会把成功的多步分析流程**自动沉淀为可复用的 SKILL 文件**（`generated_skill_dir`），下次直接调用；`SkillSummaryMemoryProvider` 把技能摘要作为记忆注入。HiveLogic 已有 `strategies/` 和 `src/agent/factory.py` 的 skill manager，但缺"运行时生成新技能"这一环。

技能目录加载顺序（`agent/runtime.py`）：用户技能目录 → 生成技能目录 → 内置技能 → 外部目录 → 插件技能目录 →（可选）`~/.claude/skills`。

### 5. 插件系统 —— `plugins/registry.py`

- 多种清单格式：`plugin.yaml` / `.claude-plugin/plugin.json` / `hooks.json` / `.mcp.json` / `__init__.py`
- `VALID_HOOKS` 生命周期钩子（`pre_llm_call`、`post_tool_call` 等）；多智能体触发器就是挂在钩子上的
- 用户插件从 `~/.dojo/plugins` 自动发现，内置插件在 `plugins/built_in/`

### 6. 网关适配器模式 —— `gateway/adapters/base.py::BaseGatewayAdapter`

Slack / Telegram / 微信 / 飞书各自一个适配器，统一 `GatewayEvent` / `GatewaySendResult` 契约，带配对（pairing）与 SQLite 状态（`gateway/state.py`）。通过 `gateway/registry.py` 注册。HiveLogic 的 `bot/` 目前只有命令层，扩展多平台推送可借鉴此分层。

### 7. 原子存储 —— `dashboard/services/file_store_base.py`

- `AtomicJsonStore` / `AtomicJsonlStore`：写入原子化，避免半截文件
- 错误族：`FileStoreError` / `CorruptStoreError` / `SchemaVersionError` / `InvalidStoreKeyError`
- 防路径穿越：用户控制的 store key 不做不安全的路径拼接

### 8. Agent 活动可视化 UI —— `dashboard/web/src/components/DojoAgent/AgentToolActivity.tsx`

流式渲染 agent 每一步工具调用：

- 状态图标（running / done / error）、耗时（latency_ms）
- 可展开查看生成的 Python 代码与执行结果
- 会话输出文件可直接下载
- 时间线模型：`AgentActivityStep = text | think | tool | eval`（`web/src/types/agent.ts`）
- 后端为 **OpenAI 兼容 chat API + SSE 流式推送**

可移植到 HiveLogic 的 Vue 客户端，让 `/ask` 分析过程透明可见。

---

## 四、工程实践借鉴（立即可做）

1. **AGENTS.md 护栏文件**：DojoAgents 的 AGENTS.md 是教科书级——明确"黄金代码片段"、Must NOT 清单、扩展路径（加工具 / 加路由 / 加适配器分别去哪）、统一 CONFIG/LOGGER 强制约定。HiveLogic 应照写一份，对 AI 协作开发极有价值。
2. **Runtime 组合根模式**：`agent/runtime.py::Runtime.from_config_store()` 把全部对象图（工具、技能、记忆、沙箱、多智能体、规划、MCP）在一个工厂方法里装配，按 config 条件化启用。HiveLogic 的 `server/main.py` 模式分发逻辑（回测 / 复盘 / 定时 / 单次）已显臃肿，值得重构成组合根。
3. **统一 LOGGER**：单一 `dojoagents/logging.py` 暴露 `LOGGER` 与 `get_logger(name)`，禁止 `print()` 和 `logging.basicConfig()` 散落各处。
4. **测试结构**：`tests/` 完整镜像包结构（`tests/dashboard/routers/` 对应 `dashboard/routers/`），pytest + pytest-asyncio。
5. **打包发布**：`pyproject.toml` + uv.lock + console script（`dojoagents dashboard --port 8765`）+ PyPI 发布，前端构建产物打进包内（`packaging_hooks.py`）。

---

## 五、建议优先级

如果只做三件事：

1. **Agent Loop + 工具执行器** —— 让分析从"单次生成"变"多轮推理"
2. **ConfigStore** —— 打通 UI 配置与密钥脱敏
3. **活动可视化 + SSE 流式** —— 用户体验提升最大

---

## 六、注意事项与风险

- DojoAgents 的 Agent Loop **深度绑定 `strands-agents` SDK 和 `dojosdk`**（`DojoBridgedTool` / `DojoStrandsModelBridge` 桥接层），直接搬代码不现实。**借鉴的是分层设计与模式**（Registry / Executor / Sandbox / Harness / ConfigStore），而非整体引入依赖。
- DojoAgents 前端是 React，HiveLogic 是 Vue —— UI 借鉴需要重写组件，只借交互模型（activitySteps 时间线、可展开工具结果）。
- DojoAgents 仓库 AGENTS.md 规定**禁止在其仓库内使用 git 命令**——后续如需读取其历史，注意不要违反该仓库规则（对 HiveLogic 无影响）。
- 许可证：DojoAgents 为 Apache-2.0，借鉴模式与思路无问题；若直接复制代码片段需保留许可证声明。

---

## 七、市场数据体系深挖（市场动态页面）

> 针对"市场动态"页（美/A/港指数卡片 + 每日市场发现[新闻时间轴+板块热图] + 行业板块涨跌榜）的完整数据链路调研。

### 7.1 总体架构：三层混合模式

| 层 | 内容 | 方式 |
|---|---|---|
| 第 1 层：重历史数据 | 板块成分、板块日线、个股日线 | 远端预计算 → 发布 HuggingFace 数据集 `dojo_sector_precomputed` → 用户端启动时 `download_dataset()` 同步为本地 parquet → 之后窗口计算全在本地 pandas |
| 第 2 层：实时数据 | 指数行情、个股报价、新闻事件时间轴 | 请求时通过 `dojosdk`（`AsyncDojo` 客户端）直拉远端 Dojo 数据 API |
| 第 3 层：缓存粘合 | 计算结果缓存、后台刷新 | `DojoSphereService`/`SectorMetricsStore` 按 key 缓存；`RefreshStateStore` + `market_refresh_jobs.py` 后台刷新 |

同步降级：HF 同步失败用本地旧文件；`DOJO_HF_OFFLINE=true` 完全离线。

### 7.2 板块分类体系（taxonomy）来源

- **自有三级行业分类**（L1/L2/L3），中英双语，id 为不透明数字串（`id_scheme=sector_id`，如 153/160/161）
- 分类体系由 **Dojo 远端数据平台定义维护**，经 `client.sectors.get_info(tree=True)` 下发；`sector_store` 本地缓存，`build_taxonomy_tree()`（`services/domain_api.py`）组装成树供前端与 agent 工具使用
- 个股→板块归属同样来自远端：`sectors.get_symbol_relations()` 接口 + 预计算 constituents.parquet 中每股已带 level1/2/3 id
- **仓库内无任何本地分类生成逻辑**（无 LLM 打标、无规则映射表）；`dojoagents/data/` 只有默认组合与 ticker 别名。分类是他们的核心数据资产，不在算法层

### 7.3 板块热图数值计算链（以"家用电器及智能家居 +19.72%"为例）

**不是直接拉取的**，是从成分股 K 线算出来的；计算在离线预计算阶段完成，请求时只做窗口首尾相除。

pipeline：`dashboard/services/precompute_sector_daily.py`（仓库内完整可见）

1. **定成分**：按 L3 路径取个股归属，过滤（有行情、市值>0、高于市场市值下限、有K线），记录最新市值快照与 PE
2. **个股日收益**：`daily_return_pct = close.pct_change() * 100`（`_compute_ticker_daily`）
3. **板块日收益 = 市值加权平均**（`_build_index_rows`）：
   ```
   daily_return_pct = Σ(个股日收益ᵢ × 市值ᵢ) / Σ市值ᵢ   # 当日有数据者
   index_level     *= 1 + daily_return_pct/100          # 基期100逐日复利
   ```
   - 权重为**最新市值快照**（manifest: `weighting_method=latest_market_cap_snapshot`），即"用今天的权重回看历史"
   - 覆盖率护栏（`sector_day_return_coverage_ok`）：当日有收益股票太少/覆盖市值太低 → 该日丢弃，视为数据缺口
4. **发布**：三份 parquet + manifest（sha256、schema_version、各市场最新交易日）→ staging 目录原子替换 → 上传 HF
5. **展示时**（本地 pandas）：`窗口涨跌幅 = (末日index_level/首日index_level − 1) × 100`
   L1/L2 级别同理，仅分组粒度不同

工程亮点：schema 校验、sha256、staging 原子发布、拒绝发布空快照/丢市场快照（`validate_precompute_market_coverage`）。

### 7.4 行业板块涨跌榜链路

与热图**同源**（同一份 parquet），请求时计算路径：

```
GET /api/v1/market/sector-movers?days=5&limit=5&min_cap_cn=...
  → SectorMoversService.build_market_movers_response()
  1. 窗口解析 resolve_market_analysis_window（对齐实际 trade_date，跳过非交易日）
  2. 窗口计算 get_sector_movers_window_frame_for_window（index_level 首尾变化率）
  3. 只取 scope=="L3"；名称经 sector_store.find_resolved_path 解析
  4. 资格过滤 sector_eligible_for_movers_ranking（成员数下限+板块总市值下限）
  5. 排序：/market/sector-movers 纯按 change_percent；
          /dojo-mesh/sectors（总览页）按 avg_market_cap × change_percent（大板块优先，防小板块噪音霸榜）
  6. 丰富化：成员列表（constituents+stock_store 报价）、
     领涨股贡献度 compute_leader_concentration（权重%/收益%/贡献%/集中度分级）、
     strength 0-100 强度条、sample_tickers（|涨跌|Top3）
```

缓存：`_catalog_cache` 键为 `(load_generation, window.cache_key())`，parquet 重载后自动失效。

热图 vs 涨跌榜差异：热图走 `include_members=false`（只要板块级数值）；涨跌榜 `include_members=true`（加成员与领涨股分析）；热图按日期选择器，涨跌榜默认 days=5（0-90 可调）。

### 7.5 更新频率

**生产端（Dojo 团队侧）**：
- 预计算为 CLI 命令（`cli/precompute_sector.py --upload`），仓库内无调度代码，由其运维/CI 触发
- 节奏佐证：refresh 循环日志 "preload_offline_data at 8:00 AM daily"，整个数据生态按每日早 8 点更新
- 每次**全量重建**（`DATA_START_DATE="2025-01-01"` 起算），非增量

**消费端（用户 dashboard）**：`dashboard/server.py` lifespan 启动 `start_refresh_loop`（`market_refresh_jobs.py`）：
- `poll_interval=3600` 每小时一轮（注释误写 10 mins）
- 每轮：`client.preload_offline_data()` → `registry.refresh_after_offline_data_update()`：清 K线/指数/新闻/财报缓存、`sector_precomputed_store.clear_cache()+reload()`（重新同步 HF parquet 并重建索引）、`sector_movers_service.invalidate()`

**各元素实际节奏**：

| 页面元素 | 更新频率 | 粒度 |
|---|---|---|
| 板块热图 / 涨跌榜数值 | 每交易日一次（生产端日更 → 用户端最迟 1 小时内同步） | T 日收盘，盘中定格 |
| 成员 last_price | 服务启动预载 + 每日刷新重拉 | 非 tick 级实时 |
| 顶部指数卡片 | 请求时实时拉取（benchmark.get_kline） | 近实时 |
| 新闻事件时间轴 | 请求时拉取 + 每日清缓存 | 近实时 |
| 改窗口/过滤参数 | 重新请求，秒级（本地计算） | — |

### 7.6 对 HiveLogic 的复刻评估

| DojoAgents 做法 | 复刻度 | 说明 |
|---|---|---|
| 预计算数据集 + 本地 parquet + pandas 窗口计算 | ✅ 高 | akshare/东财拉数，自建每日预计算 pipeline；snapshot→compute→validate→stage→publish 结构可照搬 |
| 板块指数算法（pct_change→市值加权→复利→窗口首尾相除） | ✅ 高 | 无黑盒，含覆盖率护栏思想 |
| 三级板块分类体系 | ⚠️ 需替代源 | A股用申万三级/东财行业（akshare 有接口），美港股可用 GICS；有维护成本 |
| 新闻事件时间轴（带板块影响标注） | ⚠️ 需自建 | 可用现有 SearchService + Gemini 做"新闻→板块影响"LLM 标注 pipeline |
| 远端 SDK 统一数据网关（GatewayResult/错误族/超时分类） | ✅ 高 | `dojo_data_gateway.py` 模式可直接借鉴 |
| 小时级后台刷新循环 + 缓存全面失效机制 | ✅ 高 | `market_refresh_jobs.py` + `refresh_after_offline_data_update()` 结构简单有效 |

**潜在改进点**（DojoAgents 未做）：日级预计算导致盘中热图/榜单定格在上一交易日。HiveLogic 可在快照之上叠加"当日实时报价修正层"（用实时 quote 算当日临时板块收益），实现盘中动态。

---

## 八、板块页（Sectors）数据拆解

> 针对 Sectors 页（L1/L2/L3 分类下钻 + 动量曲线 + 风险指标 + 成分股）的云端/本地数据划分与借鉴评估。

### 8.1 页面数据清单：云端 vs 本地

前端仅 4 个 API（`web/src/api/sector.ts`）：

| 页面元素 | API | 数据来源 | 计算位置 |
|---|---|---|---|
| L1/L2/L3 分类树 | `/utility/taxonomy/tree` | 云端（`sectors.get_info` 下发，`sector_store` 本地缓存） | 云端生产，本地缓存+组装 |
| 板块指标卡（成员数/总市值/加权PE） | `/dojo-sphere/sectors/metrics` | 本地 parquet（`sector_daily` 预计算列） | 云端预计算，本地直读 |
| 动量曲线（美/A/港三条线） | `/sector/analysis` | 本地 parquet `index_level` + 实时K线延伸 | **混合（见 8.2）** |
| 风险指标表（累计收益/波动率/夏普/卡玛/最大回撤） | 同上 | 由合并曲线本地计算（`compute_market_performance_stats`） | ✅ 纯本地 |
| 成分股列表（含窗口涨跌幅） | `/sector/constituents` | 本地 parquet 成分表 + `stock_store` 报价 | 本地组装 |
| 主题状态/广度/动量/alpha 因子 | 预计算 parquet（theme_state/horizon/alpha 等五张表） | 云端 pipeline（CLI 阶段B）生产 | 云端算，本地读 |

### 8.2 关键机制：实时尾巴延伸（live tail extension）

`services/sector_scope_performance.py::_extend_series_with_live_klines`——动量曲线**不停在预计算快照最后一天**：

```python
# 1. 读本地 parquet 的 index_level 曲线（截至快照日 T）
# 2. kline_store 按需拉成分股近期K线（云端，有缓存）
# 3. 本地计算 T 日之后的市值加权指数
# 4. 以 parquet 最后一天为锚点缩放拼接：
scale = last_level / anchor_value
# 只追加 T 之后的日期，保证曲线连续
```

注意：此机制**仅在板块页实现**，市场页的热图/涨跌榜没有（盘中定格）。

**跨市场日历合并**（`_merge_market_series`）：三市场交易日不同 → 并集日历 + 前值填充 + 每市场独立窗口边界（休市市场的曲线停更，不硬填）。做跨市场展示的必答题，他们已给出答案。

### 8.3 借鉴评估（对 HiveLogic 参考价值最高的页面）

**直接可借鉴（高价值）：**

1. **打包式 API**：`/sector/analysis` 一次返回"指标 + L1/L2/L3 三条曲线"，前端 `dedupeFetch` 去重 → 避免下钻时请求风暴
2. **曲线 = 快照 + 实时尾巴**：日更 parquet 保速度，实时延伸保新鲜度，锚点缩放保连续性。HiveLogic 有实时行情（Binance WSS / ccxt），天然适配——**建议直接采用**
3. **风险指标本地算**：波动率/夏普/回撤从曲线现算，几行 pandas，无需预计算
4. **跨市场日历合并逻辑**：forward-fill + 独立窗口边界
5. **自绘 SVG 迷你图**：`SectorLevelPerformanceSparkline` 支持拖拽平移 + 滚轮缩放 + 悬停快照，400×72 纯 SVG 无依赖；交互模式可移植 Vue（代码需重写）

**受限项：**

- 成分归属、taxonomy 依赖其数据资产 → 需申万/东财分类替代
- 主题状态/alpha 因子依赖生产端 pipeline 阶段B → 概念可借鉴，需自建

**一句话：板块页 = "云端重资产（taxonomy+预计算）× 本地轻计算（窗口/风险指标/实时尾巴）"的教科书范例。**

---

## 九、战略结论：HiveLogic 发展方向判断

> 基于前八节调研，对 HiveLogic 短板的诊断与三大发展方向的建议。

### 9.1 核心诊断：短板是"数据工程"，不是"数据源"

DojoAgents 仓库里**没有任何独家数据源**——K线、财报、新闻、报价全是普通金融数据。其真正的护城河：

1. **taxonomy 资产**（L1/L2/L3 分类 + 成分股归属）——人工/半人工维护的关系数据
2. **预计算管线**（每日全量重建 → parquet → 分发）——代码在仓库内，可照搬
3. **统一数据网关**（`dojo_data_gateway`：GatewayResult / 错误族 / 超时分类）——把不稳定的源头包装成稳定的内部接口

**结论：HiveLogic 不需要找到"完美的数据源"（不存在），需要建的是"把混乱源头变成稳定资产"的管线。** DojoAgents 的源头同样不稳定——它只是用网关和预计算把不稳定隔离在了系统边界之外。

### 9.2 三大方向及其依赖关系

```
数据 ──决定──> Agent 框架的产出上限 ──决定──> UI 能展示什么
```

- **Agent 框架是数据工具的放大器**：DojoAgents 的 `get_sector_movers`、`get_market_overview` 等工具全建立在预计算数据集上。没有数据底座，Agent Loop 做得再好也只是"更优雅地胡说八道"
- **UI 丰富度是结构化数据的函数**：热图、榜单、动量曲线背后都有 parquet 快照
- 三方向不是并行而是**螺旋**：数据 pipeline 先行 → 每沉淀一层数据，agent 多一批工具、UI 多一类组件

### 9.3 数据方向落地顺序建议

| 阶段 | 做什么 | 治什么病 | 投入 |
|---|---|---|---|
| 1 | **统一数据网关**（借鉴 `dojo_data_gateway`：统一返回类型、错误分类、超时、降级） | "混杂混乱" | 小，1-2 周，见效最快 |
| 2 | **行情/K线管道 + 本地 parquet 持久化** | "不稳定"——源头挂了用本地快照 | 中 |
| 3 | **板块分类**：不自建三级体系，先用现成的（A股申万/东财行业，akshare 有接口）+ 概念板块，落成本地 constituents 表 | "完全没有" | 中，需想清楚维护策略 |
| 4 | **每日预计算 pipeline**（照搬 `precompute_sector_daily.py` 的 snapshot→compute→validate→stage→publish 结构） | 把 1-3 变成"数据资产" | 中 |
| 5 | 新闻多源聚合 + 失败降级 + 缓存 | "极其不稳定" | 持续工程 |

### 9.4 风险提醒

1. **不要复刻 DojoAgents 的全套数据平台**——那是团队级资产（云端生产 + HF 分发）。HiveLogic 是单机桌面端，数据管线要内嵌在应用里，做"轻量单机版"：本地 pipeline + 本地 parquet，无云端分发环节
2. **收敛市场范围**：先做透 A股的分类+预计算，美股/港股/加密后谈。跨市场日历合并等复杂度都是多市场带来的
3. **最小闭环验证**：先跑通"统一网关 + 一个行业分类 + 每日预计算 + 一个榜单 UI"的最小闭环，证明管线可行再铺开

---

## 十、后续可深入方向（待讨论）

> 2026-07-29 更新：**数据方向已展开**——现状盘点见 [00_data_inventory.md](./00_data_inventory.md)，细化计划见 [01_market_data_gateway_plan.md](./01_market_data_gateway_plan.md)（行情数据收敛）、[02_news_pipeline_refactor_plan.md](./02_news_pipeline_refactor_plan.md)（新闻/搜索管线重构）。Agent / UI 方向待展开。目录组织见 [README.md](./README.md)。

- [x] ~~市场数据体系（数据来源/分类体系/热图计算链/涨跌榜链路/更新频率）~~ → 见第七节
- [x] ~~板块页数据拆解（云端vs本地/实时尾巴/跨市场日历合并）~~ → 见第八节
- [x] ~~数据方向现状盘点与细化计划~~ → 见 00 / 01 / 02 号文档
- [ ] 详细拆解 Agent Loop 多轮工具调用流程（loop.py 全部 1523 行 + providers 桥接）
- [ ] ConfigStore 完整实现细节（loader.py 的 env 展开 / redacted / deep_merge）
- [ ] SSE 流式协议设计（dashboard 的 chat API 事件类型与前端 activitySteps 还原）
- [ ] Harness 护栏体系如何落地到 HiveLogic 的 `/ask` 分析
- [ ] 多智能体（`multi_agent/pool.py` + delegation 工具）是否适合 HiveLogic 的多策略并行分析
- [ ] 撰写 HiveLogic 自己的 AGENTS.md
