# 04 部署拓扑计划：从桌面一体到个人服务器（C/S 解绑 + 7×24）

> 创建日期：2026-07-29
> 状态：方向已确认，待启动
> 上游文档：[dojoagents_reference_analysis.md](./dojoagents_reference_analysis.md)（Dojo 生来即服务器形态的对照）
> 协同计划：[01_market_data_gateway_plan.md](./01_market_data_gateway_plan.md)、[02_news_pipeline_refactor_plan.md](./02_news_pipeline_refactor_plan.md)、[03_data_asset_plan.md](./03_data_asset_plan.md)
> 性质：**部署拓扑解绑**，不是架构重写——业务逻辑零重写

---

## 〇、核心判断（2026-07-29 与用户确认）

| # | 判断 | 结论 |
|---|---|---|
| 1 | 要不要服务器化 | **要**——它是数据战略的物理前提：01/02/03 的采集/爬虫/预计算全部隐含"持续运行"假设，桌面模式下所有管线是"上班打卡制" |
| 2 | 改造量级 | **部署解绑，非架构改造**——FastAPI/Electron/bot/UDF 在代码层已是 C/S 分离，改动集中在：服务器地址可配置、认证层、部署打包 |
| 3 | 目标形态 | **个人服务器模型**：单用户 + 多客户端（Electron/浏览器/bot），**不做多租户、不做 SaaS** |
| 4 | 桌面一体模式 | **永久保留**作为降级路径（离线可用、零运维选项） |
| 5 | 存储选型 | **不变**——SQLite（状态/写入）+ DuckDB/parquet（分析）的结论在服务器侧依然成立；将来多人化时 Postgres 是可选项而非必需品 |

---

## 一、现状与差距

### 1.1 已经是 C/S 的部分

```
现在：Electron ──spawn──> FastAPI（同机 localhost，信任网络）
目标：Electron / 浏览器 / 手机bot ──HTTPS──> FastAPI（NAS/VPS/常开主机）
```

- FastAPI 服务端独立存在（`server/main.py` + `api/v1/router.py`）
- 客户端通过 HTTP 消费（UDF 图表 API、REST API、新闻页面）
- bot（Telegram/飞书）天然是远程客户端
- Docker 已有使用经验（sandbox/）

### 1.2 缺口（Phase 0 需逐一核实的清单）

| # | 核实项 | 为什么重要 |
|---|---|---|
| 1 | Electron 如何 spawn/寻址 FastAPI（端口、就绪探测、生命周期绑定） | 决定"服务器地址可配置"的改法 |
| 2 | 客户端所有 API base URL 是否集中可配（UDF、REST、WS 各有几处硬编码 localhost） | 解绑的工作量清单 |
| 3 | 现有 API 有无任何认证/鉴权中间件、CORS 配置现状 | 认证层从什么基础上加 |
| 4 | `.env` 密钥的消费范围（哪些只服务端用、哪些泄漏到了客户端包） | 密钥回收清单 |
| 5 | SSE/WS 实时推送对网络抖动的重连/补偿行为；是否支持事件持久化 + 断点重放 | 远程客户端体验 |
| 6 | 单用户假设的分布（watchlist/portfolio/settings/会话的存储与隔离方式） | 确认"个人服务器"不做多租户的边界 |

---

## 二、目标架构

```
┌──────────────── 常开服务器（NAS / VPS / 旧主机）────────────────┐
│  FastAPI（headless，Docker Compose）                            │
│  ├─ REST/UDF/WS API ── API token 认证中间件（新增）              │
│  ├─ Scheduler：采集/预计算/归档（7×24，01/03 的管线跑在这）       │
│  ├─ NewsCrawlScheduler + feed 层（7×24，02 的管线跑在这）         │
│  ├─ bot 网关（Telegram/飞书，常驻）                              │
│  ├─ SQLite（状态/写入）+ DuckDB/parquet（分析）── 存储选型不变     │
│  └─ API keys 全部留在服务端 .env，不下发                         │
└────────────────────────▲──────────────────┬────────────────────┘
                         │ HTTPS + token    │ bot 协议
        ┌────────────────┴───┐         ┌────▼─────┐
        │  Electron 桌面端    │         │ 手机 bot  │
        │ （服务器地址可配置， │         │（已天然远程）│
        │  默认仍 localhost）  │         └──────────┘
        └────────────────────┘
        ┌────────────────────┐
        │  浏览器（Phase 3）  │
        │  FastAPI 托管 SPA   │
        └────────────────────┘
```

**边界（明确不做）**：多租户/账号体系、SaaS 化、k8s/微服务、存储引擎更换、任何业务逻辑重写。

---

## 三、四个阶段

### Phase 0：现状核实与边界确认（0.5 天）

完成 1.2 的六项核实，产出两份清单：
- **解绑改动清单**（所有 localhost 硬编码点、spawn 机制、WS 端点）
- **密钥回收清单**（确认无密钥进入客户端构建产物；有则先回收再继续）

### Phase 1：解绑（核心一步，2-3 天）

1. **服务器 headless 化**：FastAPI 脱离 Electron 独立运行的入口与配置（不依赖父进程生命周期）；日志/异常守护；`Dockerfile` + `docker-compose.yml`（含数据卷挂载 `data/`、时区 Asia/Shanghai、重启策略）
2. **认证层**：API token 中间件（单 token 起步，不做用户体系）；全 API/WS 挂载；CORS 收敛为显式白名单。参考 DojoAgents 2026-08 的 `SessionPrincipal` 设计，在 token 校验后增加一个固定的 Principal Provider（如 `("default", "local")`），让所有存储/会话层天然带单用户作用域，既保留"个人服务器不做多租户"的边界，又为未来升级多 principal 预留一致接口
3. **客户端解绑**：Electron 服务器地址可配置（设置项，默认 `http://localhost` 保持桌面一体模式）；token 存储（系统 keychain/安全存储，不明文）；所有 base URL 收敛为单一配置源（含 UDF/REST/WS）
4. **TLS/暴露面**：局域网场景可 HTTP + token；公网场景必须 HTTPS——推荐反向代理（Caddy，自动证书）或 Tailscale 组网（**零公网暴露，个人服务器首选**，在文档中给出两种部署拓扑）
5. **SSE 事件持久化与断点重放**：参考 DojoAgents 2026-08 的 `stream_persisted_run_events` + `SessionStore.read_offline_events`，把 Agent/分析流的 SSE 从"纯内存推送"改为"事件落库 + `after_seq` 游标重放"。远程客户端断线、浏览器刷新、服务器重启后都能从断点续接，直接解决 1.2 核实项 #5 的重连/补偿问题

**验收**：服务器在 Linux 主机 Docker 独立跑起来；Electron 指向远程服务器全部功能正常（图表/分析/新闻/bot 命令）；无 token 请求一律 401；SSE 断线 30 秒后重连不丢消息；桌面一体模式（localhost）回归不破坏。

**风险**：中。主要是"漏改的 localhost 硬编码"——Phase 0 清单质量决定成败，改完全局 grep `localhost|127.0.0.1` 清零。

### Phase 2：常开化（1 天，与 01/02/03 协同）

1. **全部定时任务归位服务器**：Scheduler（采集/归档/预计算/分析）、NewsCrawlScheduler、feed 层、bot 网关——桌面端不再承担任何采集职责，变为纯视图
2. **数据连续性观测**：task_log + 新鲜度统计暴露为状态 API/页面（"服务器活着、数据在流"一目了然）；断档告警（如超过 N 小时无新快照 → bot 推送告警）。参考 DojoAgents 的 `RefreshStateStore`（持久化 `last_refresh_date` + `market_data_revision`）和 `DashboardServiceHealth`，把"今日是否已刷新"作为 freshness 核心指标，避免每小时空转重复刷新
3. **客户端冷启动体验**：打开桌面端即见热数据（服务器缓存命中），无需等待本地采集

**验收**：桌面端关闭 72 小时，服务器数据无断档（kline/news/snapshot/预计算产物连续）；重开客户端数据即刻可见。

### Phase 3：BS 化（可选，1-2 天，最后做）

1. FastAPI 托管 Vue 构建产物（静态目录 + SPA fallback），浏览器成为一等客户端
2. 现有独立页面（`news.html` 等）纳入统一托管与认证
3. Electron 保留（重度图表场景），浏览器服务轻量场景

**验收**：手机/电脑浏览器 HTTPS 访问核心功能（自选股、图表、新闻流）可用。

---

## 四、安全设计（个人服务器水位）

| 项 | 方案 |
|---|---|
| 认证 | 单 API token（随机 32+ 字节），全端点强制；token 可轮换、可配置失效 |
| 传输 | 公网=HTTPS（Caddy 自动证书）；**首选 Tailscale 组网=零公网暴露** |
| 密钥 | LLM/数据源 API key 只存服务器 `.env`；客户端仅持访问 token；构建产物扫描确认无密钥 |
| 暴露面 | 默认仅监听内网/Tailscale 接口；公网暴露需显式配置；无鉴权端点清零 |
| 限流 | 认证中间件附带基础限流（防 token 泄漏后被刷） |
| 备份 | `data/` 目录单文件/目录拷贝即备份；可选每日自动快照到另一目录 |

---

## 五、与 01/02/03 的协同及启动顺序

- **04 Phase 1 是纯部署工程**，与数据计划无代码冲突，可随时插入
- **04 Phase 2 放大 01/02/03 的收益**：它们的调度类工作（采集/爬虫/预计算）只有在 7×24 下才是"承诺制"
- 建议总顺序（更新版）：

```
01 P1-2（K线收敛，治最痛）→ 04 P0+P1（解绑，拿到 7×24 载体）
→ 03 P1（基座）→ 03 P2/P3（板块+预计算，直接长在常开服务器上）
→ 01 P3（故障转移收敛）→ 02 全程可并行
```

- 03 Phase 3 的"每日预计算管线"直接按服务器常驻设计，不再考虑桌面触发

## 六、工作量

| 阶段 | 预估 | 依赖 |
|---|---|---|
| Phase 0 现状核实 | 0.5 天 | 无 |
| Phase 1 解绑 | 2-3 天 | Phase 0 |
| Phase 2 常开化 | 1 天 | Phase 1；与 01/02/03 协同落地 |
| Phase 3 BS 化（可选） | 1-2 天 | Phase 1 |

核心投入（P0-P2）约 3.5-4.5 天。

## 七、测试要求

- 认证：无 token 401、错误 token 401、WS 同样强制
- 部署：Docker 冷启动一键起（干净机器验证）；数据卷持久化（容器重建数据不丢）
- 回归：桌面一体模式全功能不破坏（这是降级路径，必须永远可用）
- 连续性：Phase 2 的 72 小时断档测试
- 安全：构建产物密钥扫描；`localhost|127.0.0.1` 硬编码清零检查（脚本化进 CI）
