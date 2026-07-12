# AI 原生升级计划 — 从「报告生成器」到「自主投资助手」

> **创建日期**: 2026-07-02
> **前置依赖**: `server_refine_plan.md` Phase 1-6（已完成）、`multi-agent-refine/`（已完成）
> **北极星**: 充分利用当今最强 AI，做一个真正能自主规划、能编程、能看图、能学习的股票投资助手

---

## 一、为什么有这个计划

### 1.1 迷失感的来源

`server_refine_plan.md` 的 Phase 1-6 做得非常扎实——服务端常驻、分层采集、多租户鉴权、
Docker 部署、健康监控全部落地。但**这六个月的工作本质是「基础设施重构」，不是「AI 演进」**。
与此同时，`multi-agent-plan` / `multi-agent-refine` 聚焦于模式合并、数据流贯通、报告页面，
停留在「让 AI 报告生成器更可靠」的层面。

结果：项目变得更可商用，但离「充分利用最强 AI」这个北极星几乎没有移动。本计划正是
补上这一段差距。

### 1.2 差距评估矩阵

| 维度 | 当今最强 AI 应有的样子 | 当前状态 | 完成度 |
|------|----------------------|---------|--------|
| 多 agent 协作 | 角色分工、辩论、反思 | Tech/Intel/Risk/Debate/RiskDebate/Skills/Decision + Reflection | **75%** ✅ |
| 模型覆盖 | 接入最强前沿 + 推理模型深度利用 | LiteLLM 多 provider；支持 deepseek-reasoner 但只当"选项"用 | **50%** |
| **Agentic loop** | AI 自主规划看什么、跑什么、何时收尾 | 固定 stage 串行 + prompt 强制固定工作流 | **20%** ⚠️ |
| **代码执行** | AI 写并运行回测/因子/统计检验 | `backtest_tools` 预封装，AI 不能写代码 | **10%** ⚠️ |
| **多模态** | 看 K 线图、财报截图、分时图 | 纯文本/数值输入 | **5%** ⚠️ |
| **长记忆/个性化** | 记住偏好、持仓、跟踪决策结果并学习 | Reflection 只记录信号，不跟踪结果，不学用户 | **15%** ⚠️ |
| 持续/proactive | 主动监控、异动告警、机会推送 | Bot 推送 Phase B 未启动；分析仍用户触发 | **10%** ⚠️ |
| 投资组合视角 | "我整体仓位该如何调整" | 有 `portfolio_agent` 但单标的分析为主 | **25%** |
| 数据→决策→执行闭环 | 分析→建议→确认→下单→反馈 | 到 dashboard 为止，无执行/反馈 | **30%** |
| 基础设施 | 7×24 采集、缓存、鉴权、可运维 | Phase 1-6 完成 | **90%** ✅ |

**加权估算：距离「充分利用最强 AI 的股票投资助手」约 35-40%。** 基础设施不拖后腿，
差距在 AI 的**使用模式**——固定 pipeline vs 自主 agent、文本 vs 多模态、预封装工具 vs
代码执行、单次报告 vs 持续陪伴学习。

---

## 二、北极星定义

「充分利用最强 AI」不是抽象口号，拆解为五个可验证的能力：

| # | 能力 | 验证标准 |
|---|------|---------|
| C1 | **自主规划** | 用户问"宁德时代能不能买"，AI 自己决定先看技术面→发现量价背离→主动查龙虎榜→发现机构卖出→查行业景气度→综合判断。工具调用顺序由 AI 决定，不是代码写死。 |
| C2 | **能编程** | 用户说"帮我回测过去三年所有均线金叉后的胜率"，AI 自己写 Python、自己跑、自己解读结果。不是调用固定接口。 |
| C3 | **能看图** | 用户贴一张 K 线截图问"这个形态怎么看"，AI 能看图分析。AI 也能主动生成图表自己看。 |
| C4 | **能学习** | AI 记住用户持仓/风险偏好；N 天后回看上次决策对不对；错的策略降权，对的加码。 |
| C5 | **能主动** | 自选股异动、机会触发时主动推送，不等用户问。 |

当前 C1-C5 全部不达标。本计划逐一补齐。

---

## 三、技术约束（继承并强化）

继承 `multi-agent-refine/00_overview.md` 的约束，并新增：

| 约束 | 说明 |
|------|------|
| 不引入 LangGraph/LangChain | 自研轻量 agentic loop，复用现有 `run_agent_loop` + `ToolRegistry` |
| 保持 `AGENT_ARCH=single` 降级 | 新模式作为 `deep` 之上的可选增强，不破坏现有 quick/deep |
| 兼容现有 API 契约 | 渐进式，dashboard JSON schema 只增不减 |
| **模型栈以国产为主** | DeepSeek（推理）/Kimi（长上下文+视觉）/GLM-4V（视觉）/MiniMax-M2.7（视觉+function calling）。无 OpenAI/Anthropic 直连 key，多模态优先用 GLM-4V / Kimi |
| **沙箱安全第一** | 代码执行必须隔离，禁止访问文件系统/网络/真实账户 |
| **成本可控** | agentic loop 步数有上限；代码执行有超时；推理模型只在关键决策用 |

---

## 四、改造方向与优先级

```
Phase A (Agentic Loop)  ──→  Phase B (代码沙箱)  ──→  Phase C (多模态)
                                                            │
                                                            └─→  Phase D (长记忆)  ──→  Phase E (主动陪伴)
```

| Phase | 能力 | 优先级 | 理由 |
|-------|------|--------|------|
| **A** | Agentic Loop（自主规划）| **P0** | 最高杠杆。固定 pipeline 下用推理模型等于浪费；改完才能发挥 deepseek-reasoner 价值 |
| **B** | 代码执行沙箱 | **P0** | 最强 AI 杀手锏。区别于"报告生成器"的本质。已有 Docker 基础设施 |
| **C** | 多模态感知 | **P1** | 当今模型视觉能力极强，纯文本是巨大浪费 |
| **D** | 长记忆与学习 | **P1** | 让助手"认识用户"，Reflection 框架已在，需补结果跟踪 |
| **E** | 主动陪伴 | **P2** | 依赖 Phase B 推送（server_refine_plan Phase B），但可先做监控触发 |

---

## 五、Phase A：Agentic Loop — 从固定 pipeline 到自主规划

### 5.1 现状问题（精确到代码）

当前有两套执行路径：

1. **`AgentOrchestrator`（multi-agent, AGENT_ARCH=multi）**：`_build_agent_chain()` 返回固定
   `[technical, intel, risk, decision]` 列表，`_execute_pipeline()` 串行跑。每个 agent 内部
   是 ReAct loop，但**整体流程是写死的 stage 串行**。
2. **`AgentExecutor`（single-agent, AGENT_ARCH=single）**：`run_agent_loop()` 是纯 ReAct，
   理论上 AI 可自主调工具——**但 `executor.py` 的 system prompt 强制了固定工作流**：

   ```
   第一阶段 · 行情与K线... 第二阶段 · 技术与筹码... 第三阶段 · 情报搜索...
   > 禁止将不同阶段的工具合并到同一次调用中
   ```

   这句话把 ReAct 的自主性彻底锁死。即使 LLM 想"先查新闻发现利空→跳过技术分析直接
   给风险警告"，prompt 也不允许。

**核心矛盾**：项目已经有了 ReAct 引擎（`run_agent_loop`），但被 prompt 和固定 stage
两层枷锁锁成了"伪 agentic"。

### 5.2 目标

新增一个 `autonomous` 模式（在 quick/deep 之上），让一个 planner agent：
- 拿到全部工具列表（含代码执行、图表生成等 Phase B/C 新增工具）
- **自己规划**调用顺序、是否需要追加数据、何时收尾
- 用推理模型（deepseek-reasoner）做规划，用快速模型做信息提取
- 输出与现有 dashboard 兼容的结构化结果

关键：**不是删掉 quick/deep，而是新增 autonomous 作为"最强大脑"模式**。quick/deep 保留
给不需要深度规划的场景（快速看一眼、固定流程复盘）。

### 5.3 任务清单

- [ ] **A.1 解放 system prompt**
  - `executor.py`：将强制固定工作流的 prompt 改为**目标导向 + 工具说明 + 安全护栏**。
    保留"必须用工具获取真实数据""风险优先排查"等护栏规则，**删除"第一阶段/第二阶段"
    阶段强制和"禁止合并阶段"限制**。
  - 新增 `autonomous` 模式专用 prompt：强调"自主规划、按需调用、先规划再执行"。
  - 保留 `quick`/`deep` 模式仍用旧 prompt（向后兼容）。

- [ ] **A.2 新增 AutonomousPlannerAgent**
  - 新增 `server/src/agent/agents/autonomous_agent.py`：
    - 持有完整 `ToolRegistry`（含所有工具）
    - 用 `deepseek-reasoner`（DEEP tier）做规划：先输出"调研计划"（要看哪些数据、跑哪些
      分析、预期几步），再逐步执行
    - 每步执行后**重新评估**：是否需要追加数据？是否发现异常需要深挖？
    - 步数上限可配（默认 15 步，硬上限 30），超限自动收尾
    - 支持中途向用户"汇报发现"（progress callback 已有）
  - 复用 `run_agent_loop`，扩展支持"规划-执行"两阶段循环（plan → act → observe → replan）

- [ ] **A.3 Orchestrator 接入 autonomous 模式**
  - `orchestrator.py`：`VALID_MODES` 增加 `"autonomous"`；`MODE_MAPPING` 把它映射到自身。
  - `_build_agent_chain()`：autonomous 模式返回 `[autonomous_planner]`（单 agent，但内部
    自主规划）。
  - 保留 quick/deep 的多 agent 链不变。
  - `factory.py`：模式选择透传到 orchestrator。

- [ ] **A.4 调研计划可观测**
  - AutonomousPlannerAgent 执行时，把"调研计划"和"每步决策原因"通过 progress_callback
    推给前端（`plan_generated` / `step_reasoning` 事件类型）。
  - 前端 StockAnalysis.vue / AgentWindow 展示"AI 的思考过程"时间线（已有 stage_start/
    stage_done 机制，扩展即可）。
  - 调研计划落库（复用 ReflectionRepository 扩展），供 Phase D 学习。

- [ ] **A.5 推理模型分层利用**
  - `model_tier.py`：新增 `REASONING` tier（高于 DEEP）。
  - AutonomousPlannerAgent 的"规划"步骤用 REASONING tier（deepseek-reasoner）；
    "执行"步骤（调工具、提取信息）用 QUICK tier（deepseek-chat / kimi）。
  - `llm_adapter.py`：`get_model_for_tier()` 增加 REASONING 分支，读 config
    `agent_reasoning_model`（默认 `deepseek/deepseek-reasoner`）。
  - 推理模型的 `reasoning_content`（思维链）完整保留并在前端可展开查看。

- [ ] **A.6 安全力护栏**
  - 工具调用白名单：autonomous 模式只能调 `ToolRegistry` 注册过的工具（不能任意执行）。
  - 单次分析成本上限：token 数 + 步数双限，超限强制收尾（复用现有 timeout 机制）。
  - "风险一票否决"护栏保留：发现利空必须体现在最终决策。

**产出验收**：用户问"宁德时代能不能买"，autonomous 模式下 AI 自主决定调研路径
（可能先看新闻发现利空→跳过深度技术分析→直接给风险警告；也可能先看技术面发现突破
→深入查龙虎榜确认→给买入建议），**两次问同一只股票可能走不同路径**。调研过程时间线
在前端可见。quick/deep 模式行为不变。

---

## 六、Phase B：代码执行沙箱 — 最强 AI 的杀手锏

### 6.1 为什么

预封装工具（`get_daily_history`、`analyze_trend`）让 AI 只能拿到固定 schema 的数据。
但真正的投资分析需要：自定义回测、自定义因子计算、统计检验、画自定义图——这些
**无法预先穷举**。给 AI 一个 Python 沙箱，等于给它整个数据科学栈。这是"最强 AI 投资
助手"区别于"AI 报告生成器"的本质。

### 6.2 方案选型

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 服务端 `subprocess` + 超时 | 简单 | 无隔离，危险 | ❌ |
| 服务端 Docker exec 进隔离容器 | 强隔离，复用现有 Docker | 需要容器管理 | ✅ **主方案** |
| 浏览器 Pyodide | 前端跑，零服务端负担 | 无法访问服务端数据/缓存 | ❌ 数据在服务端 |
| E2B / Modal 沙箱 API | 免运维 | 依赖外部服务，数据出境 | ❌ 内网阶段不可用 |

**选 Docker exec**：项目已有 `Dockerfile` + `docker-compose.yml`，在 server 容器内
`docker exec` 进一个预构建的 `sandbox` sidecar 容器（镜像含 pandas/numpy/akshare/
matplotlib，挂载只读数据卷）。沙箱容器无网络、无写权限、CPU/内存受限。

### 6.3 任务清单

- [x] **B.1 沙箱容器** ✅
  - 新增 `sandbox/Dockerfile`：基于 `python:3.12-slim`，预装 pandas/numpy/scipy/
    matplotlib/akshare，**不装网络库**（requests/httpx 等移除）。非 root 用户运行。
  - 新增 `docker-compose.sandbox.yml`：定义 `sandbox` 服务，`network_mode: none`，
    `read_only: true`（仅 `/tmp` 可写 tmpfs），`mem_limit: 1g`，`cpus: 0.5`，
    `no-new-privileges: true`，`cap_drop: [ALL]`，`profiles: [sandbox]`。
  - 新增 `sandbox/hivelogic_data.py`：只读封装（`load_kline`/`load_analysis_history`/
    `list_available_symbols`/`db_info`），通过 `immutable=1` SQLite URI 挂载只读数据卷。

- [x] **B.2 代码执行工具** ✅
  - 新增 `server/src/agent/tools/code_tools.py`：
    - `SandboxManager`：单例，懒加载 Docker SDK，容器复用，base64 编码用户代码（防注入）。
    - `execute_python` 工具：接收 `code: str` + `context: object`（可选预加载数据）。
    - 通过 Docker SDK (`docker-py`) `exec_run` 在 sandbox 容器内执行。
    - 超时 30s，输出截断（stdout/stderr 各 10KB），返回 `{stdout, stderr, figures, ...}`。
    - matplotlib 图表自动捕获（Agg 后端 + 标记解析），返回 base64 PNG。
  - 预置"安全数据访问助手"：沙箱内可 `from hivelogic_data import load_kline`（只读封装），
    让 AI 不用写 SQL 也能拿缓存数据。支持 `kline_data`（多市场）+ `kline_cache`（A 股）双表。

- [x] **B.3 工具注册与权限** ✅
  - `registry.py`：`ToolDefinition` 增加 `requires_approval: bool = False` 字段。
  - `to_openai_tools(allow_approval_required=False)` 安全默认，`@tool` 装饰器转发 flag。
  - `runner.py`：`run_agent_loop(allow_approval_required=False)` 默认禁用，
    `autonomous_agent.py` 传 `True` 启用。Legacy `executor.py` 用安全默认。
  - `factory.py`：`ALL_CODE_TOOLS` 注册，`TOOL_DISPLAY_NAMES` + `_THINKING_TOOL_LABELS` 补充。

- [x] **B.4 典型用例验证** ✅
  - B.4a 包装脚本生成 + matplotlib 标记解析：通过。
  - B.4b 真实数据连接（`kline_data` crypto + `kline_cache` A 股双表，`immutable=1` 拒写）：通过。
  - B.4c 四用例（MA 交叉回测 / 自定义 RSI / 量价散点图 / 正态性检验）本地执行：4/4 通过。
  - B.4d Docker 不可用时优雅降级（4 场景：disabled / SDK 缺失 / daemon 不可达 / 多次调用）：通过。

- [~] **B.5 安全审计** （部分完成）
  - [ ] 沙箱镜像扫描（trivy）纳入 CI — **待办**（项目尚无 `.github/workflows`）。
  - [x] 代码执行日志全量落库（`code_execution_log` 表，含代码/输出/耗时/调用者）。
  - [x] `entitlement.py` 增加代码执行配额：`code_execution_daily_quota`（FREE=0, PRO=50,
        ENTERPRISE=-1 不限）+ `code_execution` feature flag + `require_code_execution()`
        FastAPI 依赖。

**产出验收**：autonomous 模式下，AI 能自主写 Python 回测自定义策略、算自定义因子、
画图，并在分析报告中引用代码执行结果。沙箱无网络、只读数据、资源受限，无法越狱。

---

## 七、Phase C：多模态感知

### 7.1 为什么

当今模型视觉能力极强（GLM-4V、Kimi 视觉、MiniMax-M2.7）。纯文本输入是巨大浪费：
- K 线形态识别：AI 看图比看 OHLC 数组更准
- 财报截图：用户直接贴图，不用手动 OCR
- AI 自主生图：Phase B 沙箱画完图后，AI 自己"看一眼"验证

### 7.2 任务清单

- [x] **C.1 LLM 适配层支持多模态消息**
  - `llm_adapter.py`：`_convert_messages()` 支持 OpenAI vision 消息格式：
    `{"role":"user","content":[{"type":"text","text":"..."},{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]}`。
  - LiteLLM 自动转换为各 provider 格式（GLM-4V / Kimi / MiniMax 均支持）。
  - `model_tier.py`：新增 `VISION` tier，`get_model_for_agent` 支持 vision agent。
  - config 新增 `agent_vision_model`（默认 `glm/glm-4v` 或 `moonshot/moonshot-v1-8k-vision`）。

- [x] **C.2 图表工具**
  - 新增 `server/src/agent/tools/vision_tools.py`：
    - `capture_kline_chart`：服务端用 `matplotlib` 生成 K 线截图（含成交量、均线标注），
      返回 base64 PNG。复用 `klinecharts` 数据格式。
    - `capture_intraday_chart`：分时图截图。
    - 截图可作为工具返回值，也可直接喂给 vision LLM 做"看图分析"。
  - autonomous 模式下，AI 可自主决定"我看一下 K 线图"→ 调 capture → 喂给自己（vision tier）。

- [x] **C.3 图像分析 Agent**
  - 新增 `server/src/agent/agents/vision_agent.py`：
    - 接收图片 + 问题，用 VISION tier 模型分析。
    - 用途 1：用户贴图问"这个形态怎么看"。
    - 用途 2：被 autonomous planner 调用，对生成的 K 线图做形态确认。
  - 注册为可被 orchestrator 插入的 specialist agent（类似 skill agent）。

- [x] **C.4 前端支持图片输入**
  - StockAnalysis.vue / AgentWindow 对话框：支持粘贴图片、拖拽上传、截图粘贴。
  - 图片转 base64，随消息发送到后端（`/api/v1/agent/chat` 增加 `images` 字段）。
  - 分析结果中的 AI 生成图表（Phase B 产出）在 dashboard 内联展示。

- [x] **C.5 财报/公告 OCR 增强**
  - `vision_agent` 支持识别用户上传的财报截图、公告图片，提取关键数据。
  - 与 `news_service` 结合：爬取的公告若为 PDF/图片，转图喂 vision 提取要点。

**产出验收**：用户可贴 K 线截图问形态；AI 在分析中自主生成 K 线图并"看图"确认形态
判断；财报截图能被识别提取数据。多模态走 GLM-4V / Kimi 视觉模型。

---

## 八、Phase D：长记忆与个性化学习

### 8.1 现状

`ReflectionService` 已存在：记录每次决策的 signal/confidence/reasoning。但：
- **不跟踪结果**：AI 说"买"后涨了没？不知道。
- **不学习**：策略权重固定，错的策略不会降权。
- **不认识用户**：不知道用户持仓、风险偏好、历史操作。

### 8.2 任务清单

- [ ] **D.1 决策结果跟踪**
  - 新增 `server/src/services/decision_tracker.py`：
    - 决策入库时记录 `stock_code` / `decision_type` / `target_price` / `timestamp`。
    - 定时任务（复用 scheduler）：决策 N 天后（1/5/20 日）回看价格，计算收益，更新
      `decision_outcome` 字段（win/loss/neutral + 实际涨幅）。
    - 决策时 AI 可查"这只股上次我怎么说、对不对"（作为 context 注入）。

- [ ] **D.2 策略权重学习**
  - 扩展 `ReflectionService`：
    - 统计每个 skill（策略）的历史胜率：`skill_id` / `total_calls` / `win_count` /
      `avg_return`。
    - `SkillRouter.select_skills()`：选 skill 时参考历史胜率，低胜率（<40%）的 skill
      降权或跳过（可配 `agent_skill_learning_enabled` 开关）。
    - 高胜率 skill 在报告中标注"历史验证有效"。
  - 保守起见：学习结果只影响排序和标注，不直接禁用任何 skill（用户可覆盖）。

- [ ] **D.3 用户画像与偏好**
  - 新增 `server/src/models/user_profile.py`：`UserProfile` 表（account_id / risk_tolerance /
    holding_horizon / preferred_markets / preferred_sectors / excluded_stocks / notes）。
  - 扩展 `entitlement.py`：已登录用户分析时，自动注入用户画像到 agent context。
  - 分析建议考虑用户实际持仓（复用 `get_portfolio_snapshot` 工具）："你已持有新能源
    仓位 30%，再买这只会过度集中"。

- [ ] **D.4 对话长记忆**
  - `conversation_manager` 扩展：跨 session 的"用户笔记"（用户告诉 AI 的长期偏好，
    如"我是长线投资者""我不碰 ST"）。
  - 用 Kimi 长上下文（128k/200k）承载完整对话历史 + 用户画像 + 历史决策，做"认识用户"
    的对话。
  - 关键偏好自动提取入库（AI 识别到用户表达偏好时，主动询问是否记入画像）。

- [ ] **D.5 学习反馈闭环**
  - 管理面板新增"决策复盘"卡片：展示决策历史 + 实际结果 + 策略胜率统计。
  - 用户可标注"这个决策我执行了/没执行/结果如何"，反哺学习。
  - 定期生成"AI 自我评估报告"：本月决策胜率、哪些策略有效、哪些需调整。

**产出验收**：AI 分析时引用"上次我说买，结果跌了 5%，这次更谨慎"；策略权重按历史胜率
自动调整；用户画像影响建议（持仓集中的会被提示）；跨 session 记住用户偏好。

---

## 九、Phase E：主动陪伴（Proactive）

### 9.1 依赖

依赖 `server_refine_plan.md` Phase B（Bot 推送服务化）。但监控触发可先做，推送通道
后接。

### 9.2 任务清单

- [ ] **E.1 异动监控引擎**
  - 新增 `server/src/services/anomaly_monitor.py`：
    - 订阅用户自选（watchlist）+ 持仓（portfolio）。
    - 监控规则：价格突破/跌破阈值、放量异动、新闻利空、技术形态破位。
    - 复用 L0 全市场快照 + L2 实时流 + news_service，低延迟检测。
  - 触发时发布事件到事件总线（Phase B 的 event bus，可先内存队列）。

- [ ] **E.2 主动分析触发**
  - 异动事件触发 autonomous 分析（轻量版，步数上限低）：
    "你持有的 X 今日放量下跌 5%，AI 快速分析原因 → 推送结论"。
  - 复用 Phase A 的 autonomous 模式，但配置为"快速主动分析"profile。

- [ ] **E.3 机会发现**
  - 定时（如每日盘后）跑"机会扫描"：全市场快照筛异动 → autonomous 深度分析 top N →
    推送"今日值得关注"。
  - 结合用户画像：只推用户关注的市场/板块。

- [ ] **E.4 推送通道接入**
  - 等 `server_refine_plan.md` Phase B 完成后，事件接入推送调度器。
  - 内网阶段先做管理面板内的"主动消息中心"展示。

**产出验收**：自选股异动时主动收到 AI 分析；每日收到个性化机会推送；不需要用户主动问。

---

## 十、里程碑与依赖关系

```
Phase A (Agentic Loop)  ──→  M1 自主规划可用
    │
    ├─→ Phase B (代码沙箱)  ──→  M2 AI 能编程
    │       │
    │       └─→ Phase C (多模态)  ──→  M3 AI 能看图
    │                                   │
    │                                   └─→ Phase D (长记忆)  ──→  M4 AI 能学习
    │                                                               │
    │                                                               └─→ Phase E (主动陪伴)  ──→  M5 真·助手
    │
    └─→ (可与 server_refine_plan Phase B Bot 推送并行)
```

| 里程碑 | 包含 | 价值 | 预估难度 |
|--------|------|------|----------|
| M1 自主规划 | Phase A | AI 自主决定调研路径，推理模型发挥价值 | 中（改架构，不增依赖）|
| M2 能编程 | Phase B | 区别于报告生成器的本质飞跃 | 高（沙箱安全是重点）|
| M3 能看图 | Phase C | 多模态利用，形态识别更准 | 中（LiteLLM 已支持）|
| M4 能学习 | Phase D | 认识用户，策略自我进化 | 中（框架已在）|
| M5 真·助手 | Phase E | 主动陪伴，不等用户问 | 低（依赖前置）|

**建议执行顺序**：A → B → C → D → E。A 和 B 可部分并行（A 改架构，B 加沙箱，互不冲突）。
C 依赖 B 的图表生成能力。D 可在 A/B 后任意时点插入。E 依赖 D 的用户画像 + 推送基础设施。

---

## 十一、关键技术决策

| 决策点 | 方案 | 理由 |
|--------|------|------|
| Agentic loop 实现 | 扩展 `run_agent_loop`，不引入 LangGraph | 项目已有 ReAct 引擎；LangGraph 增加复杂度且与现有 ToolRegistry 不兼容 |
| 模式策略 | 新增 `autonomous` 模式，保留 quick/deep | 不破坏现有体验；autonomous 作为"最强大脑"可选 |
| 推理模型利用 | 新增 REASONING tier，规划用 deepseek-reasoner | 固定 pipeline 下推理模型价值有限；agentic loop 下规划是推理模型的最佳场景 |
| 代码沙箱 | Docker sidecar 容器，无网络只读 | 项目已有 Docker；隔离性强；数据不出服务端 |
| 多模态模型选型 | GLM-4V / Kimi 视觉优先 | 无 OpenAI/Anthropic 直连 key；国产模型视觉能力已可用 |
| 长上下文承载 | Kimi 128k/200k | 承载完整对话历史+用户画像+历史决策 |
| 策略学习 | 影响排序和标注，不禁用 | 保守起步，避免误杀有效策略；用户可覆盖 |
| 用户画像存储 | 复用 SQLite accounts 表体系 | Phase 5 已建账号体系，UserProfile 关联 account_id |
| 异动监控数据源 | 复用 L0 快照 + L2 实时流 | Phase 3 已建采集基础设施，不重复造轮子 |
| 推送通道 | 等 server_refine_plan Phase B | 推送服务化已在规划，避免重复 |

---

## 十二、主要文件变更清单（预估）

### 新增

```
server/src/agent/agents/autonomous_agent.py    # Phase A: 自主规划 agent
server/src/agent/agents/vision_agent.py        # Phase C: 图像分析 agent
server/src/agent/tools/code_tools.py           # Phase B: 代码执行工具
server/src/agent/tools/vision_tools.py         # Phase C: 图表生成工具
server/src/services/decision_tracker.py        # Phase D: 决策结果跟踪
server/src/models/user_profile.py              # Phase D: 用户画像
server/src/services/anomaly_monitor.py         # Phase E: 异动监控
sandbox/Dockerfile                             # Phase B: 沙箱镜像
docker-compose.sandbox.yml                     # Phase B: 沙箱编排
```

### 修改

```
server/src/agent/orchestrator.py               # 接入 autonomous 模式
server/src/agent/executor.py                   # 解放 prompt（新增 autonomous prompt）
server/src/agent/runner.py                     # 扩展 plan-act-observe-replan 循环
server/src/agent/llm_adapter.py                # 多模态消息 + REASONING/VISION tier
server/src/agent/model_tier.py                 # 新增 REASONING / VISION tier
server/src/agent/tools/registry.py             # requires_approval 字段 + code category
server/src/agent/skills/router.py              # 策略权重学习（Phase D）
server/src/agent/reflection/service.py         # 决策结果跟踪 + 策略胜率统计
server/src/services/entitlement.py             # 用户画像注入 + 代码执行配额
server/src/config.py                           # agent_reasoning_model / agent_vision_model 等
server/src/scheduler.py                        # 决策回看 / 机会扫描定时任务
client/src/renderer/src/components/            # 图片输入 / 思考时间线 / 决策复盘 UI
```

---

## 十三、风险与注意事项

1. **Agentic loop 不可控**：AI 自主规划可能跑偏、死循环、成本失控。必须步数硬上限 +
   token 双限 + 超时强制收尾。先在小范围（内网）验证再放开。
2. **代码沙箱越狱**：AI 生成的代码可能尝试逃逸。无网络 + 只读 + 资源限制是底线；
   requires_approval 让用户确认代码；日志全量审计。
3. **推理模型成本**：deepseek-reasoner 调用成本高于普通模型。仅在 autonomous 模式的
   规划步骤用，信息提取仍用 quick 模型。
4. **多模态幻觉**：视觉模型可能误读图表。关键判断（买卖信号）不能只靠看图，必须
   与数值数据交叉验证。
5. **策略学习偏差**：小样本下胜率统计不可靠。设最低样本数（如 20 次才纳入权重），
   且只影响排序不禁用。
6. **用户画像隐私**：画像数据敏感，须与账号鉴权绑定，仅用户自己可见。商业化时需
   纳入隐私协议。
7. **主动打扰**：推送过频会打扰用户。须可配频率上限 + 用户可关闭 + 仅异动才推。
8. **国产模型 API 稳定性**：DeepSeek/Kimi/GLM 偶有限流/波动。复用现有 LiteLLM Router
   多 key + 跨 provider fallback 机制。
9. **向后兼容**：所有新功能通过模式选择 / 配置开关控制，quick/deep 行为不变，
   dashboard schema 只增不减。

---

## 十四、与现有计划的关系

| 现有计划 | 关系 |
|---------|------|
| `server_refine_plan.md` Phase 1-6 | **前置依赖**，已完成。本计划在其基础设施之上构建 AI 能力 |
| `server_refine_plan.md` Phase B（Bot 推送）| **并行 + 依赖**。Phase E 依赖其推送通道；Phase E 的监控触发可先行 |
| `multi-agent-refine/` | **基础**。模式合并、数据流贯通已完成，本计划的 autonomous 模式是其上的演进 |
| `local_database_plan.md` | **复用**。决策跟踪、策略胜率统计落库复用其 SQLite 基础设施 |

本计划不替代任何现有计划，是在其完成后的**下一阶段战略方向**。

---

> **下一步行动**：建议从 Phase A（Agentic Loop）开始。它是最高杠杆改动，且不增依赖、
> 不破坏现有功能。完成后 Phase B（代码沙箱）将让 AI 能力产生质变。
> 若要启动实施，可基于本计划的 Phase A 任务清单，用 Plan Agent 出详细实施步骤。
