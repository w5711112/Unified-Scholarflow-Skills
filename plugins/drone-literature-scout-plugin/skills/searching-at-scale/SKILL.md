---
name: searching-at-scale
description: Use when a user needs broad or exhaustive current-web research, enumeration of many options or sellers, multi-source price or availability comparison, platform-wide discovery, historical datasets, purchase research, or a source-backed report across any topic.
---

# 大规模通用网页调研

## 插件级轻量故障协作

- 本文件是执行入口；下表七份直接参考保存不可压缩的来源路由、平台协议、调度、证据、报告和清理合同。原始要求仍具最高权威，摘要、计划、清单、测试或中间产物都不能替代它们。
- 开始插件任务或 Skill 拓扑变化时读取 [`../../references/skill-collaboration-contract.md`](../../references/skill-collaboration-contract.md)；同一任务内拓扑未变不重复枚举。**正常成功路径不写故障库**，也不包装每次工具调用。
- 仅当组件已知脆弱、准备复用历史方案或路线刚失败时运行 `incident_registry.py preflight`：先查项目守卫指定的本地事故库，未命中再查公共事故库只读。出现任意异常、非零退出、权限拒绝、结果缺失或验证失败时，先 `capture-event`；成功后下一条 commentary 原样显示 `conversation_notice`，再诊断或换路线。记录失败要明确披露。预期 TDD RED、受控探针和用户取消不算产品事故。
- 不以相同参数原样重试失败路线。**只有本轮事件发生变化**、新解法完成效果验证或历史方案获得新的复用结果时才检查候选；候选非空才加载 `promotion_audit.py`。最终回答前补记遗漏的真实故障。
- 本 Skill 的效果验证是：候选可回溯、统计口径一致、大规模发现先于严格核验、报告后继续执行，且未留下搜索中间文件。

## 触发与退出

| 模式 | 触发 | 执行 |
| --- | --- | --- |
| `quick_direct` | 星期、时间、单个官网或单一稳定事实 | 用最短权威路线回答；不得据此声称全市场已饱和 |
| 自动大规模触发 | “调研一下”“有哪些”“尽量搜全”“所有卖家”、购买比较、平台枚举、完整历史数据、跨来源核验或调研报告 | 执行完整发现—收敛—核验流程 |
| 显式调用 | 调用 `$searching-at-scale`，或明确要求千次级、万次级、尽量穷尽 | 直接进入大规模模式；不设置固定 URL 数量上限，URL 里程碑不是停止条件 |

快速直达遇到来源冲突、字段漂移、信息分散或多对象枚举时自动升级并简短告知。地区、年份、日期或预算可以合理补全时采用明确假设并披露，不反复阻塞提问。四种 `run_type` 精确为 `quick_direct`、`open_web_research`、`catalog_enumeration`、`bounded_dataset_extract`；均服从 **10 分钟（600 秒）硬上限**，可凭已验证的搜索饱和或确定边界提前结束。

## 单层直接参考

按任务读取适用参考；涉及相应阶段或交付条件时必须完整读取。**直接参考不得继续路由第二层参考**。

| 唯一职责 | 直接参考 |
| --- | --- |
| 来源类别、查询族、批量闸门、并发和饱和 | `references/source-routing.md` |
| 国内市场、Edge/JD 协议、吞吐和风控 | `references/domestic-marketplace-edge-contract.md` |
| 全局换源、恢复、停止、跨轮累计 | `references/global-scheduler.md` |
| 动态字段、关系、时间序列、证据原子 | `references/adaptive-schema.md` |
| A–E、时效、冲突与推荐置信度 | `references/verification-contract.md` |
| 聊天、图表、可选 Markdown 与校验 | `references/report-contract.md` |
| 空闲零常驻、任务产物、精确清理 | `references/runtime-lifecycle-and-cleanup.md` |

## 单一证据脊柱

所有阶段只维护下列八个有向对象。上游未变时禁止重复验证；发生变化时**只刷新受影响对象及下游**。交付前对最终对象执行一次**最终新鲜验证**，不在每个子部分反复验证同一事实。

| 对象 | 最小内容 | 产生/消费 |
| --- | --- | --- |
| `SEARCH_SCOPE` | 目标、对象、地区、时间、语言、限制、假设、`run_type`、范围指纹 | 入口产生；全流程只读 |
| `BACKEND_CAPABILITIES` | `name/kind/available/attempted/concurrency/coverage` 与批量四态 | 预检产生；调度消费 |
| `MARKET_RUN` | 全局 run ID、计时会话、停止状态、跨轮并集、平台健康 | 调度器唯一写入 |
| `DISCOVERY_LEDGER` | URL/渠道/SKU 的 SQLite 账本、批次检查点、去重键 | 发现写入；收敛读取 |
| `COVERAGE_STATE` | 来源/查询/地区/语言/时间/平台缺口、边际收益、饱和证据 | 每批增量更新 |
| `EVIDENCE_PACKAGE` | L0–L3、证据原子、来源等级、冲突、时效、缺失原因 | 收敛与核验产生 |
| `REPORT_PACKAGE` | 轨迹、漏斗、四种速率、统计、来源和限制 | 报告阶段产生 |
| `RUN_ACCEPTANCE` | `passed/status/stop_reason/residuals/cleanup_verified` | 最终统一判定 |

依赖顺序为 `SEARCH_SCOPE → BACKEND_CAPABILITIES → MARKET_RUN + DISCOVERY_LEDGER → COVERAGE_STATE → EVIDENCE_PACKAGE → REPORT_PACKAGE → RUN_ACCEPTANCE`。任何“成功”只能由 `RUN_ACCEPTANCE.passed=true` 给出；`bulk_ready`、候选数、时间到或单批队列耗尽都不等于最终成功。

## 标准执行流

### 1. 定义范围与能力预检

1. 解析目标、对象类型、地区、时间、语言、价格/规格、决策场景和输出要求，登记歧义、假设、排除词、同义词、旧称、缩写、错写、品牌/型号/用途/价格档及语言版本。大矩阵用 `scripts/build_query_matrix.py` 惰性分批，不预先物化全部组合。
2. 盘点本轮真实可用的搜索、程序化工具、授权浏览器、公开 API 和垂直平台。后端 `kind` 只允许 `search`、`sitemap`、`open_index`、`dataset`、`bulk_api`、`page`；缺失工具、登录态、额度或权限必须标为 unavailable，禁止假装拥有。
3. 对每个适用来源类别、查询族、地区、语言、时间和平台建立覆盖缺口。方向准备完成后才启动纯发现计时；理解、去重、深读、核验、计算和写作不计入 `T_search/T_discovery`。
4. 批量候选发现前必须实时 Sitemap 预检，事件状态只允许 `bulk_unchecked`、`bulk_ready`、`bulk_degraded`、`bulk_unavailable`。仅 `bulk_ready` 可称大规模发现；某后端 `bulk_unavailable` 硬停止该后端批量阶段，随后只可切换到重新预检成功的后备后端；若无后备则 `incomplete_blocked`。Windows 优先 Python `urllib`/OpenSSL；只有 PowerShell/curl 的 Schannel 路线返回 `SEC_E_NO_CREDENTIALS` 时才能换路，且不能同参重试。
5. `market_discovery` 是全局运行；`preflight_probe` 仅验证路线，`backend_batch` 仅表示来源批次，`queue_exhausted` 只结束当前批次。全局成功状态只允许开放任务 `search_saturated`、所有运行类型 `ten_minute_limit`，以及满足确定边界的 `deterministic_scope_complete`。

### 2. 先召回，再收敛

- 接力扇出：宿主与现有连接器生成种子，Sitemap/RSS、开放索引/开放数据扩张，SQLite 规范化去重后才抓正文，新别名和覆盖缺口回流查询。默认零凭证数据面顺序为 **Sitemap/RSS + 宿主已有搜索种子 → 临时 SearXNG → Common Crawl URL Index**；Firecrawl 仅在连接器和额度真实可用时加入，联盟或其他授权接口仅在用户明确选择且权限探测通过后使用。历史索引不得证明实时价格、库存或当前全量。
- Common Crawl 固定分流：exact URL 用单次 CDX；domain/subdomain/prefix 用 DuckDB URL Index。宽查询不得 CDX 分页；触及时间或结果上限必须返回 `partial`，不下载 WARC 正文。
- 商品路线优先商品 Sitemap、分类页/商品链接、JSON-LD Product、公开 Feed/API，再用搜索/API/Common Crawl 补漏；根 Sitemap 只做覆盖审计。连续批次 `product_candidate_yield < 5%` 时换商品入口。
- 每个合法 HTTP(S) URL 都增加 `raw_url_observations`，即使重复。漏斗固定为 `raw_url_observations → literal_unique_urls → normalized_unique_urls → content_unique_pages → topic_relevant_pages → product_page_candidates → unique_valid_structured_records`；不得用去重数替代原始观察量。
- 商品记录至少保存 `source_role/brand/seller/market_region/purchase_access`；`source_role` 只允许 `brand_official`、`vertical_retailer`、`marketplace_store`、`search_index`、`historical_index`。不得把零售商当品牌。
- L0 只去明显无关、垃圾、恶意、损坏与重复；L1 建对象簇和字段清单；L2 提取高相关正文与公开字段；L3 只严格核验进入结论的对象和事实。陌生类别不得被过早过滤，高产域名不得垄断深读预算。

### 3. 国内商品与京东受控车道

- 主线是显式国内引擎 SearXNG（360search、baidu、sogou、quark、bing、brave）+ Edge 已登录京东列表 + Common Crawl；浏览器固定 **Edge-only**，且 **JD mandatory**。京东联盟账号 V0、关键词接口额度 0，因此联盟 API 不进入候选，除非出现新权限证据。
- 复用用户已登录的**日常 Edge**：窄权限 **Manifest V3** 扩展 + 当前用户 HKCU Native Host。**不启用远程调试**、CDP、WebDriver、键鼠注入；不启动 Edge，不创建服务。预检从正式 worker 同一 Python→Node 上下文连接命名管道，最长 60 秒且不计纯发现时间；失败不得覆盖正式账本。
- 运行期只允许**一个 C# Native Host**和一个搜索分组对应的**一次性 Node**；管道 ACL 只授予**当前 Windows SID**。搜索标签通常 `active:false`，翻页授权置前除外。明确不读取 Cookie、**不读取凭证**、存储、密码、完整 DOM 或其他标签，**不回退 Chrome**，不绕过验证码、登录墙或平台限制。
- 京东查询族精确为 `<topic>`、`<topic> 自营`、`<topic> 品牌`、`<topic> 型号`、`<topic> 新品`；`--max-pages-per-topic` 默认 2，`auto` 仅用于深翻实验，数值边界 `1..512`。多话题可重复传入 `--topic`。协议固定 `protocol_version: 3`，`session_action` 只允许 `start | next | recover`；搜索使用 `operation: search`，详情预留 `operation: detail`，详情域只在用户明确授权后启用 `optional_host_permissions`，且**不跟踪价格**。
- 投影固定 **projection schema v4**，能力含 `stable_card_fields_v2`、`verified_pagination_v1`、`resilient_pagination_v1`。诊断键、七个 JD 卡片字段、`/Search` 限制、页码/SKU digest 校验、200KB 双端输出上限及缺失置空规则不得增删；扩展/协议/投影旧版返回不可重试的 `edge_extension_reload_required`。
- 默认翻页为已转正 `experimental_url` 同标签相邻直连；`human_flow` 用首页→`from=home` 搜索→点击 `.pn-next` 保持导航上下文。真实翻页默认关闭，只能显式 `--enable-jd-pagination`；每话题页数用 `--max-pages-per-topic`。分页控件最多等待并滚动至 8 秒。仅上一页 `ready + page_verified`、恰有 30 张有效卡片、无公开下一页控件且任务严格 `+1` 时，可在原标签用同域同关键词相邻公开 URL；之后仍验证页码与 SKU 集。
- 未知零卡、SKU 停滞或投影暂不可用，每逻辑页仅一次 `reproject → reload` 软恢复；仍失败则换查询族。验证码、限流、风险重定向、登录失效、未知失败都失败关闭；前四类阻断京东车道并保留 60 分钟熔断。京东受阻不得压低其他来源。
- 正式宽类验收从全新账本/run/session 开始：600 秒纯发现、至少 **6,000** 个唯一候选、平均 **10 去重商品候选/秒**，且**任意连续 30 秒**不为零新增。京东慢速车道固定 90 秒零新增容忍、**1 可复核卡片/秒（60/min）**目标、至少 60 个候选；1/s 是目标与披露口径，不是持续绝对速率闸门，必须跑满平台允许的窗口、字段齐全并如实报告。
- 600 秒纯发现受 **900 秒**绝对墙钟约束。父看门狗等待上限为 60 秒预检 + 配置墙钟 + 5 秒清理；若下一次等待、请求和 2 秒清理余量放不进剩余墙钟，不发送新请求。`ten_minute_limit` 结束发现，但只有 `marketplace_discovery.decision.acceptance_passed=true` 才能成功；零批次、零候选、仅超时或仅限流不得达标。
- 京东节奏固定 45 秒慢启动、30 秒下限、每页最多缩短 25% 和 ±35% 抖动；两跑间隔 **≥1800s**，硬风控后 **≥3600s**。规模累积只用 `--append-ledger` 与隔离 profile；多 profile 不解决导航形态，不得作为绕过风控。

### 4. 并发、吞吐与停止

- 普通起步档位：SearXNG **2 → 4**、CDX **1 → 2**、静态 Sitemap/页面 **4 → 8 → 16**、浏览器正文 **1 → 2**；健康批量后端的聚合目标为 **24 → 32 → 40**。每级用新查询观察净收益；报告实际最高并发而非目标。DuckDB 按 CPU、可用内存和临时盘动态分配，无固定资源绝对值。
- 批量发现性能目标是 `raw_url_observations_per_second >= 50`。完成**至少两个批次**且累计 **5 秒**纯发现时间后若不足，先加入未尝试的健康批量后端，再换查询族；低于目标达到 **15 秒**必须披露当前速率、真实上限和原因。429 按后端独立退避；持续异常时 40→32 稳定窗口→24，不牵连健康来源。
- 窄类只有查询生成器、健康后端游标全部 exhausted，`blocked=0`，最后三批新增趋近零且无未尝试高收益查询族，才能 `deterministic_scope_complete`。对一般 `bounded_dataset_extract`，还须 boundary 非空、`expected_pages == completed_pages > 0` 且 `failed_pages == 0`。
- **搜索饱和停止前必须经验证**：`search_saturated` 必须经过连续三轮不同查询角度和不同来源，确认无新增有效 URL/对象/字段/高相关页，覆盖缺口关闭、域名不过度集中、规范化去重有效 URL 的边际新增与对象收益趋零。**未去重 URL 增长不能单独证明搜索饱和**。快速直达不做该声明。存在登录、验证码、429 冷却、结构变化、权限拒绝或未闭合缺口时只能 incomplete/blocked。
- 到 600 秒停止提交新请求并有界接收尾部结果；约每分钟报告纯搜索时间、请求/批次、漏斗计数、域名、来源类别、边际新增、覆盖缺口和实际最高并发。发现结束先报告统计与停止原因，**报告后不得暂停**，自动进入去重、筛选和严格核验，再完成交付。

### 5. 核验、报告与最终验收

- 每条证据保存对象、字段、原始值、标准化值、来源、时间和可复算变换。稳定事实优先一个直接一手来源；无一手来源时至少两个独立可靠来源。易变价格、库存、日期、营业状态、排名必须带采集时间、平台和条件。冲突按直接性、时效、身份和口径比较并公开保留；证据不足写“待核验”，公开字段缺失不等于零。
- 报告必须区分原始结果、未去重 URL 观察、有效 URL、规范化唯一 URL、内容去重页、唯一对象、独立域名；市场型报告还含全局 run ID、运行类型、范围指纹、停止证据、上一轮已验证、本轮新增/重叠/失效和累计并集。跨轮并集不得无证据缩小。
- 每次使用都在聊天输出发现—筛选轨迹。商品图使用绿色发现线 `#2e7d32`、红色筛选线 `#c62828`，均 `4px`，坐标/文字 `#111111`、轴 `2.5px`；真实检查点全部保留。Codex 内优先可交互 HTML（滚轮中心缩放 `1×–4×`、拖动、重置），标题不小于 `24px`、轴标题与图例不小于 `18px`、刻度与阶段标签不小于 `16px`，不打开外部浏览器；无 HTML 时依合同回退 SVG/Mermaid/字符图。
- 图下分别报告 `raw_url_observations_per_second`、`url_discovery_per_second`、`successful_page_bodies_per_second`、`unique_valid_structured_records_per_second`，未执行写“未执行”，禁止互相换算；同时给出去重边际新增率、重复率、唯一对象收益、未闭合缺口、后台漏斗和淘汰原因。`catalog_enumeration` 另列候选/记录数、平均和最近 30 秒候选速率、最长零新增、各来源 raw/unique/duplicate、blocked、实际最高并发及确定边界。
- 最终聊天顺序为“直接结论 → 完整度允许的清单/数据 → 比较/推荐/趋势 → 冲突、缺失和待核验 → 关键来源 → 完整统计、停止原因和覆盖限制”。只有用户明确要求保存/生成报告/形成 Markdown 时写一个 Markdown；同名不覆盖并用确定性脚本校验。不得声称绝对穷尽互联网。
- `RUN_ACCEPTANCE` 最后统一检查：范围未漂移；权威参考已读；候选可追溯；计时、并发、漏斗、吞吐、来源和停止原因口径一致；主要结论证据充分；平台限制未被绕过；图表与统计来自同一 run；清理与架构验证通过。任何项不满足都返回 `incomplete` 或 `failed` 并列出残余问题。

## 脚本接口与状态所有权

| 职责 | 入口 |
| --- | --- |
| 查询矩阵 | `scripts/build_query_matrix.py` |
| URL 规范化与 L0 账本 | `scripts/normalize_and_dedupe.py` |
| 证据聚合 | `scripts/aggregate_evidence.py` |
| 时间序列 | `scripts/compute_timeseries.py` |
| 报告校验 | `scripts/validate_report.py` |
| 轨迹图 | `scripts/render_search_timeline.py` |
| Sitemap 预检 | `scripts/discover_sitemaps.py` |
| 后端卷轴与提交 | `scripts/backend_runner.py` |
| Edge Python worker | `scripts/edge_marketplace_query.py` |
| Edge Node 客户端 | `scripts/edge_extension_client.mjs` |
| Native Host 安装 | `scripts/install_edge_native_host.ps1` |
| Edge 权限白名单 | `edge-extension/manifest.json` |
| Edge profile 启动 | `scripts/launch_edge_profile.py` |
| 临时 SearXNG 生命周期/查询 | `scripts/runtime_manager.py`、`scripts/searxng_query.py` |
| Common Crawl CDX/URL Index/DuckDB | `scripts/common_crawl_query.py`、`scripts/common_crawl_url_index.py`、`scripts/duckdb_runtime.py` |
| 全局状态机 | `scripts/market_scheduler.py` |
| JD 节奏/持续 driver | `scripts/jd_pace.py`、`scripts/run_jd_sustained.py` |

除 `scripts/market_scheduler.py` 外，其他确定性脚本只通过函数导入或**标准输入/输出**承接业务数据，**不得读写任务状态文件**或 URL 池；调度器只读写调用方显式给出的**任务专属状态路径**。任务使用专属 SQLite 和有界 NDJSON；调度 JSON 只存聚合计数与 cursor digest。成功、失败和中断走同一精确清理；空闲时不留搜索进程、容器、TCP 端口、卷轴或批次文件，已授权的 Edge Native Messaging 宿主仅随 Edge 存在。

## 兄弟 Skill 交接

- 向领域 Skill 只返回候选 URL、对象簇、覆盖统计、冲突和证据包，不接管领域接纳、事实库或评分。
- `drone-literature-scout` 独占 venue、单无人机、感知—控制闭环、算力/部署门槛、论文库写入、方向评分和最终接纳。
- 个人 Obsidian 表达交给 `obsidian-note-style`；跨宿主迁移交给 `global.migration-skill`；故障复用交给 `global.collect-bug-update-accelerate`。每项语义只保留一个负责人。

本文件及其强制 reference 是本 Skill 的唯一 canonical。规则或 reference 变化后，只刷新 `Skill完整指南/research/searching-at-scale-完整指南.md`；用途、输入输出、协作或边界变化时，再更新《Skill 与 Plugin 的总体系说明》对应段与自动关系区。两类派生说明只作阅读导航，不得替代或反向覆盖 canonical。
