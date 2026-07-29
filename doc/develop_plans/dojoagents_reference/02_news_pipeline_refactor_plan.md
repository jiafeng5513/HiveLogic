# 新闻/搜索管线重构计划

> 创建日期：2026-07-29
> 状态：已确认方向，待启动
> 输入基线：[00_data_inventory.md](./00_data_inventory.md) 第四节（新闻/搜索管线现状）
> 性质：三步打包为一个专项，整体推进

---

## 〇、决策记录（2026-07-29 与用户确认）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 统一表 schema 以谁为准 | 以 `crawled_news`（`CrawledNewsItem`）为权威范式，它是字段超集 |
| 2 | LLM 加工范围 | 只对**入库存储**的结果加工；瞬态搜索响应不加工。落库先存裸数据，异步补加工 |
| 3 | 推进节奏 | 三步打包为一个专项，不拆分单独上线 |
| 4 | requester 追踪的处置 | **不**作为主表列，拆为独立关联表 `news_attribution`（N:N），同时修掉现有"后触发者覆盖归属"的隐患 |
| 5 | 源调整（2026-07-29 确认） | 删 MiniMax / SerpAPI / SearXNG 公共实例；新增 Exa / Serper / ddgs + akshare·Tushare feed 适配器层；SearXNG 转自建；Brave 待确认 key 状态后定去留（详见"四、源调整清单"） |

### 决策 4 的背景

`news_intel` 的 6 个 `requester_*` 字段由 bot 触发的分析写入（`pipeline.py:1167-1172`），记录"谁在哪个平台/会话问了什么导致这条新闻被搜到"。现状：

- **只写不读**：唯一查询入口是 `get_news_intel_by_query_id`，无任何代码按 requester 消费
- **归属覆盖**：`storage.py:1075-1091` 用 `新值 or 旧值` 更新，同一 URL 被第二个用户触发时归属被覆盖，历史丢失
- **潜在价值**：`notification.py` 已用 `source_message` 做回复路由，"新闻命中你问过的股票 → 主动推送"链路是通的，N:N 归属表可直接支撑

---

## 一、问题回顾（为什么重构）

新闻域是"双轨制"，比 K线三存储更严重——两条管线各干各的：

```
管线 A（爬虫，主动）              管线 B（搜索，被动）
EastMoneyCrawler                 7 个 SearchProvider（3480 行单文件）
  ↓ 5min 定时                      ↓ 分析时同步调用
crawled_news                     news_intel
(market_cache.db)                (stock_analysis.db)
  ↓ LLM 摘要/情感/重要性            ↓ 裸 snippet，无加工
  ✗ 互不相通 ✗
```

核心矛盾：**A 管线有 LLM 加工能力但只服务东财快讯一个源；B 管线覆盖 7 个源但产出裸数据，落库后没有然后**。LLM 加工能力被锁死在爬虫管线上，是最大的价值漏损。

### 问题分级

**P0（架构级）**
1. 两张表、两个库、两套 schema、两套去重键（`dedupe_key` vs `url`），无桥接
2. `search_service.py` 3480 行：7 个 Provider + 编排 + 工具函数塞一个文件
3. 源治理碎片化：仅 MiniMax 有熔断；key 错误计数进程内（重启清零）；配额耗尽无声（Tavily 1000/月、SerpAPI 100/月）

**P1（价值漏损）**
4. 搜索结果不过 LLM 加工管线（摘要/情感/重要性无法复用）
5. 搜索只取"最佳单源"，不做多源汇聚去重——七源配置名存实亡
6. `news_crawler` 注释里的雪球/新浪/财联社只有东财一个实现

**P2（健壮性）**
7. 缓存纯内存（600s TTL），重启冷启动所有源同时被打
8. 爬虫 cursor 不持久化，重启丢断点
9. newspaper3k 同步阻塞、5s 超时、错误静默吞
10. 零测试覆盖

---

## 二、目标架构

```
┌─────────────────── 采集层 ───────────────────┐
│  爬虫（主动流）          搜索引擎（被动/汇聚） │
│  EastMoney/财联社/雪球   providers/ 七源      │
│  +NewsCrawlScheduler     +多源 fan-out 汇聚   │
└──────────────┬────────────────┬──────────────┘
               ▼                ▼
        ┌─────────────────────────────┐
        │  dedupe.py                   │
        │  URL 归一化 + 跨源去重/合并   │
        └──────────────┬──────────────┘
                       ▼
        ┌─────────────────────────────┐
        │  news_item（权威表，唯一）    │───┐
        │  stock_analysis.db          │   │ N:N
        └──────────────┬──────────────┘   ▼
                       │            news_attribution
                       ▼            (query/requester 溯源)
        ┌─────────────────────────────┐
        │  NewsProcessor（公共服务）    │
        │  异步加工：摘要/情感/重要性   │
        │  仅加工 is_processed=false   │
        └──────────────┬──────────────┘
                       ▼
        下游：IntelAgent / Bull·Bear / ResearchAgent
              NewsService API / bot / 前端新闻流
```

**设计要点**：
- 爬虫与搜索不再各自落库，统一经 dedupe 进 `news_item`
- `news_item` 只描述"这条新闻是什么"，不描述"谁为什么搜到它"——后者归 `news_attribution`
- LLM 加工从爬虫管线解耦为公共服务，对全量入库数据生效（决策 2）

---

## 三、Schema 设计

### 3.1 `news_item`（权威表，新建于 `stock_analysis.db`，SQLAlchemy 管理）

以 `CrawledNewsItem` 为基，增量如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | String(32) PK | uuid hex（沿用爬虫侧惯例） |
| source | String(50) | 来源站点（eastmoney/cls/xxx 或搜索引擎命中的站点） |
| source_url | String(500) | 原始 URL |
| **normalized_url** | String(500) **UNIQUE** | 归一化 URL，全表唯一去重键（替代 dedupe_key 和 url 双轨） |
| author | String(100) | |
| title | String(500) | |
| content | Text | 全文/正文 |
| publish_time | DateTime | |
| fetched_at | DateTime | 入库时间（统一命名，替代 crawl_time） |
| symbols | JSON | 关联标的数组 |
| markets | JSON | 关联市场数组 |
| tags | JSON | |
| summary | Text | LLM 生成摘要 |
| sentiment_score | Float | -1.0 ~ 1.0 |
| sentiment_label | String(20) | 枚举（`NewsSentimentLabel`） |
| importance | String(20) | high/medium/low（`NewsImportance`） |
| **sector_impacts** | JSON | 板块影响数组（sector/方向/理由），参照 Dojo `MarketDynamicsSectorImpact`，LLM 加工产出，加工前为 NULL |
| language | String(10) | |
| is_processed | Boolean | LLM 加工完成标志 |
| **origin** | String(20) | 首次发现渠道：`crawl` / `search` |
| created_at / updated_at | DateTime | |

**对比旧 schema 的取舍**：
- 弃用 `news_intel` 的 `snippet`（搜索引擎摘要）——有 `content` 和 LLM `summary` 后它是冗余
- 弃用 `news_intel` 的单 `code` + `dimension`——被 `symbols`/`tags` 数组覆盖
- `provider`（哪个引擎搜到的）**不放主表**，放 attribution——同一新闻可能被多个引擎在不同查询中命中

### 3.2 `news_attribution`（溯源关联表，N:N）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | Integer PK autoincrement | |
| news_id | String(32) FK→news_item.id | |
| query_id | String(64) | 关联分析查询（兼容现有 `get_news_intel_by_query_id` 读路径） |
| query_text | String(255) | 触发搜索的查询词 |
| provider | String(50) | 命中该新闻的搜索引擎（search 来源时） |
| platform | String(20) | bot 平台（telegram 等），原 requester_platform |
| user_id / user_name | String(64) | 原 requester_user_* |
| chat_id / message_id | String(64) | 原 requester_chat_id / message_id |
| created_at | DateTime | 归属建立时间（不再被覆盖，多次触发多行） |

索引：`(news_id)`、`(query_id)`、`(chat_id, created_at)`（为将来"按会话推送"准备）。

### 3.3 归一化 URL 规则（`dedupe.py`）

- 去除 tracking 参数（`utm_*`、`spm`、`from`、`ref` 等）
- scheme/host 小写，去末尾 `/`，去 `#fragment`
- 东财等站内跳转链接提取真实目标 URL
- 归一化结果即 `normalized_url`，全管线唯一去重键

### 3.4 库存放决策

`news_item` 放 **`stock_analysis.db`**（SQLAlchemy 管理），不放 `market_cache.db`：
- 新闻是分析域数据，消费方（Agent/分析管线/attribution）都在分析库一侧
- 收拢到 SQLAlchemy 单一管理路径，摆脱 `market_cache.db` "5+ 个模块裸 sqlite3 各自操作"的现状
- `market_cache.db` 回归纯行情缓存定位；旧 `crawled_news` 表数据迁移后废弃

---

## 四、源调整清单（2026-07-29 确认）

### 4.1 框架：两类需求，两种工具

| 需求 | 性质 | 合适的工具 |
|---|---|---|
| 快讯监控（面）：全市场发生了什么 | 主动、持续、免费为佳 | 快讯订阅流（feed） |
| 按需查询（点）：这只票/这件事有什么新闻 | 被动、精准、可付费 | 搜索引擎 API |

现状的畸形之处：快讯监控只有东财一个爬虫，其余全靠按次计费的搜索引擎顶。调整的核心是**把"面"的需求从搜索引擎转移到 feed 层**。

### 4.2 新增：feed 适配器层（管线 A，零新依赖、零新 key）

akshare/Tushare 已是行情 fetcher 依赖，其资讯接口一直闲置——这是 Dojo"上游结构化事件流"模式的丐版平替：

| 接口 | 内容 | 特点 |
|---|---|---|
| Tushare `pro.news(src=...)` | 一个接口覆盖 **9 个快讯源**：新浪/华尔街见闻/同花顺/东财/云财经/凤凰/金融界/财联社/第一财经 | 已有 token，白捡 9 源 |
| akshare `stock_zh_a_alerts_cls` | 财联社电报全量 | 盘中快讯主力 |
| akshare `js_news` | 金十数据实时资讯（近 4 小时） | 盘中速度最快的一批 |
| akshare `stock_news_em` | 东财**个股**新闻，按代码查询 | **自带标的关联**，补爬虫正则提取的不可靠 |
| akshare `news_cctv` | 新闻联播文字稿 | 政策面 |

全部统一经 dedupe 落 `news_item` + 异步 LLM 加工，与爬虫共用调度器。

### 4.3 新增：搜索引擎（管线 B）

| 源 | 定位 | 理由 |
|---|---|---|
| **Exa** | 语义/研究型搜索 | "找同类事件、概念相关"是关键词引擎给不了的，服务 ResearchAgent；Contents API 自带正文+摘要，多数场景可干掉 newspaper3k |
| **Serper** | Google 数据平价替代 | $1/1k（SerpAPI 的 1/5 价），~800ms 低延迟 |
| **ddgs**（DuckDuckGo） | 零 key 最终兜底 | Dojo 同款方案，零配额 |

### 4.4 删除

| 源 | 理由 |
|---|---|
| **MiniMax**（已确认取消） | Coding Plan 订阅副产品、用法灰色；无原生时间范围参数，靠 query 拼"最近一周"不可靠。删除前提取其熔断状态机泛化到 base.py |
| **SerpAPI** | 免费档仅 100/月；是 3480 行中最臃肿的 provider（400+ 行含 newspaper3k）；由 Serper 替代 |
| **SearXNG 公共实例** | 不稳定（5s×3 次=最多 15s 才降级），由自建实例替代 |

### 4.5 转自建：SearXNG

- 官方 Docker 镜像 `searxng/searxng`，半小时部署，~200-400MB 内存，**成本 $0**（跑本地 Docker Desktop 或已有服务器，无需单独 VPS）
- **注意 IP 信誉**：聚合 Google/Bing 时数据中心 IP 易被封，本地/住宅 IP 反而更稳
- 维护成本：定期更新镜像（约几个月一次），引擎适配偶发失效跟随官方修复
- 定位：零配额聚合兜底源，一次配置聚合几十个引擎，不做高优先级源（延迟高于商业 API）

### 4.6 待确认 / 降级

- **Brave**：2026-02 起取消免费档——实施 Phase 2 前先确认 key 状态，失效则不迁移
- **Anspire**：额度不明，从优先级 0 降到中文源梯队（Bocha 之后）；无法度量的源没有资格排第一

### 4.7 调整后的源全景

```
管线 A（快讯监控，免费为主）              管线 B（按需搜索，按质量排序）
─────────────────────────                ─────────────────────────
EastMoneyCrawler（存量）                  Bocha（中文主力）
财联社 crawler（独立化）                  Exa（语义/研究型）
雪球/新浪 crawler（Phase 3 扩展）         Tavily（通用精准）
Tushare news × 9 源（feed 层）            Serper（Google 数据）
akshare × 4 接口（feed 层）               自建 SearXNG（零配额聚合兜底）
                                          ddgs（最后免费防线）
                ↓ 统一 dedupe → news_item → 异步 LLM 加工 ↓
```

---

## 五、三个阶段

### Phase 1：统一存储（收敛，不动生产路径）

**目标**：权威表 + 关联表落地，双写过渡，旧读路径不受影响。

1. 新建 `news_item` + `news_attribution` 表（SQLAlchemy model + 迁移）
2. 实现 `dedupe.py`（URL 归一化）与 `NewsStore`（统一写入入口）
3. 改造两个写入方为**双写**：
   - `NewsRepository.save_batch()`（爬虫）→ 同时写 `news_item`
   - `DatabaseManager.save_news_intel()`（搜索）→ 写 `news_item` + `news_attribution`（requester 上下文从 `query_context` 拆出）
4. 存量数据迁移脚本：`crawled_news` → `news_item`；`news_intel` → `news_item` + `news_attribution`（按 URL 归一化合并，冲突时保留字段更全的记录）
5. 读路径逐个切到 `NewsStore`：`NewsService`（前端 API）、`get_news_intel_by_query_id` 消费方、Agent 工具

**验收**：双写期间新旧表数据一致（抽查）；迁移脚本幂等（可重复跑）；旧表只读不写后所有消费方功能不回归。

**风险**：低。旧表保留，可随时回退。

### Phase 2：拆分 `search_service.py` + 统一源治理

**目标**：3480 行单文件拆为包，所有源获得熔断/健康探测/配额台账；同步执行源换血（详见"四、源调整清单"）。

```
server/src/search/
├── providers/
│   ├── base.py        # 统一基类：熔断 + 健康探测 + key 轮换 + 配额挂钩
│   │                  # + register_provider() 注册入口（对齐 Dojo 注册表模式）
│   ├── bocha.py / tavily.py / exa.py / serper.py / brave.py
│   ├── anspire.py     # 降级到中文源梯队（Bocha 之后），额度不明不再是 P0
│   ├── searxng.py     # 改为对接自建实例（SEARXNG_BASE_URLS 指向自己的部署）
│   └── ddgs.py        # DuckDuckGo，零 key 零配额的最终兜底
├── service.py         # 纯编排：路由、缓存、故障转移
├── dedupe.py          # （Phase 1 产物，移入/共享）
└── quota.py           # 配额台账，SQLite 持久化，重启不清零
```

**新优先级**（源调整后的编排顺序）：

```
Bocha（中文主力）→ Exa / Tavily（精准/研究型）→ Serper（Google 数据）
→ 自建 SearXNG（零配额聚合兜底）→ ddgs（最后免费防线）
```

1. Provider 各拆一个文件，公共逻辑上提 `base.py`；**SerpAPI / MiniMax 直接删除不迁移**（MiniMax 是 Coding Plan 订阅副产品、用法灰色且时间过滤靠 query 拼接；SerpAPI 由 Serper 替代，同数据 1/5 价）
2. MiniMax 的熔断实现泛化到基类（删除前提取其状态机），**全源生效**（3 连败 → 300s 冷却 → 半开探测）
3. 健康探测：源连续失败或探测不通过即跳过，不再"宕机数小时每次先试它"
4. `quota.py`：按 provider+key 记录调用计数/错误计数，持久化到 SQLite；月配额（Tavily 1000 等）接近阈值时降级并**显式告警**（消除"配额耗尽无声"）
5. 搜索缓存持久化到 SQLite（替代纯内存 600s TTL），重启不冷启动
6. newspaper3k 正文抽取：移出同步路径，加超时/重试，错误不再静默吞；**评估用 Exa Contents API / trafilatura 替代**（Exa 结果自带正文+摘要，多数场景可免抓正文）；补 SSRF 防护（见 3.1 节借鉴点 3）

**验收**：每个 provider 有单元测试（mock HTTP）；熔断/配额行为有测试覆盖；`search_service.py` 不再存在，import 全部指向 `search/` 包且行为兼容（`get_search_service()` 单例签名不变）；Brave key 状态已确认（2026-02 Brave 取消免费档，若 key 失效则标记 deprecated 不迁移）。

### Phase 3：LLM 加工打通 + 多源汇聚 + 源扩展（发展）

**目标**：从"裸搜索结果"升级为"结构化情报流"。

1. `NewsProcessor` 从 `news_crawler/` 解耦为公共服务（`services/news_processor.py`）：
   - prompt 外置为可配置模板（消除 `processor.py:27-38` 硬编码）
   - 并发化处理（消除串行 + 500ms/条的瓶颈）
2. 异步加工队列：`news_item` 落库 `is_processed=false` → 后台 worker 批量加工回写（summary/sentiment/importance）——决策 2 的落地：只加工入库数据，瞬态搜索响应零成本
3. 搜索升级为**多源汇聚**：查询并行 fan-out 到 top-N 源 → dedupe 合并 → 按新鲜度/来源质量排序，替代"最佳单源"
4. **feed 适配器层**（新增，详见"四、源调整清单"）：akshare/Tushare 新闻接口封装为 feed adapter，与爬虫共用调度器和落库路径；爬虫扩展：财联社独立成 crawler（目前是东财的备用逻辑）、雪球、新浪
5. 爬虫 cursor 持久化到 DB，重启续采
6. `SocialSentimentService` 接入统一治理（降级策略），评估其结果是否也入 `news_item`

### 3.1 DojoAgents 方案对照与借鉴（2026-07-29 补充）

DojoAgents 的市场新闻方案是**不自己做搜索**——消费上游 Dojo 平台的结构化事件流（`market_dynamics_service.py`，事件到手即含双语摘要+板块影响+方向+理由），本地仅归一化+缓存；通用 web 搜索只是一个 303 行的 agent 工具（`web_searcher.py`，DuckDuckGo 默认后端 + 注册表扩展）。我们没有 Dojo 平台可依赖，无法照搬"外包给上游"，但其价值取向验证了本阶段方向：**新闻的终点是结构化事件，不是裸搜索结果**。

具体借鉴三点：

1. **`sector_impact` 纳入 LLM 加工输出**：参照 Dojo 的 `MarketDynamicsSectorImpact`（sector_id / sector_name / affected_markets / direction / reason），在 NewsProcessor 的加工产物中增加"板块影响"字段——这条新闻影响哪个板块、方向（利好/利空/分化）、理由是什么。`news_item` 增加 `sector_impacts` JSON 列（加工前为 NULL），IntelAgent/Bull·Bear 可直接消费做板块级推理
2. **provider 注册表模式对齐**：`web_searcher.py` 用 `register_search_backend(name, adapter)` 注册后端，与 Phase 2 的 `providers/` 包同构——确认方向一致，无需改设计，但可在基类上补一个统一的 `register_provider()` 入口，让新增源不需要改编排代码
3. **`web_extract` 的 SSRF 防护**：Dojo 抓正文前做 URL 安全校验（仅允许 http/https、拦 localhost/私有 IP/保留地址、拦含 `api_key|token|secret|sig` 等参数的 URL）。我们的 `fetch_url_content()` 目前**零校验**，Phase 2 改造正文抽取时必须补上同等防护（放 `search/` 包的公共工具中，爬管子系统复用）

**验收**：IntelAgent/Bull·Bear 拿到的入库新闻带 summary/sentiment/importance；多源汇聚结果去重率可度量；爬虫重启后续采不重复入库（去重键兜底）。

---

## 六、与阶段 1（统一数据网关）的关系

- 新闻管线**不塞进行情网关**：行情是"拉取-缓存"模型，新闻是"流+加工"模型，生命周期不同
- 但**治理机制共享**：Phase 2 的 `providers/base.py`（熔断/健康/配额/统一异常）就是行情 fetcher 治理的模板；新闻域后续作为网关第二个域（`news:` 类别）接入
- 统一异常族与网关对齐：Timeout / Unavailable / BadResponse / RateLimited / AuthFailed

---

## 七、工作量与顺序

| 阶段 | 预估 | 依赖 |
|---|---|---|
| Phase 1 统一存储 | 1-2 天 | 无，可立即启动 |
| Phase 2 搜索包拆分+源治理 | 2-3 天 | Phase 1 的 dedupe.py |
| Phase 3 LLM 打通+汇聚+扩源 | 2-3 天 | Phase 1 的 news_item、Phase 2 的 search/ 包 |

总计约一周量级。三阶段内部按上述顺序串行（有真实依赖），不拆分单独上线（决策 3）。

## 八、测试要求（现状零覆盖，本次补齐）

- `dedupe.py`：URL 归一化规则全 case 单测
- `NewsStore`：双写一致性、迁移幂等性
- `providers/base.py`：熔断状态机、配额计数、key 轮换
- 异步加工队列：is_processed 状态流转、失败重试
- 集成：双写 → 迁移 → 读路径切换全链路冒烟
