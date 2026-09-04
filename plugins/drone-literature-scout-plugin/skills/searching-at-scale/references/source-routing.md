# 来源路由合同

按需在构造查询宇宙、分配并发或判断饱和前读取。本合同不绑定某个供应商；每轮只使用当时真实可调用且获授权的工具。

## 来源类别

| 类别 | 典型入口 | 主要用途 | 最低要求 |
| --- | --- | --- | --- |
| 一手/官方 | 政府、主办方、品牌、酒店、交易所、原始文件 | 身份、日期、规则、规格、原始数据 | 只要适用就必须尝试 |
| 通用搜索 | 多个搜索引擎或搜索 API | 扩展长尾域名、语言和查询角度 | 不让单一引擎代表全网 |
| 媒体/专业库 | 权威媒体、行业媒体、数据库 | 背景、历史、交叉核验 | 记录独立来源与转载关系 |
| 目录/聚合 | 行业目录、黄页、活动/机构目录 | 枚举对象和别名 | 回到对象页核验关键事实 |
| 地图/预订 | 地图、酒店/票务/服务预订 | 地点、营业、价格、可用性 | 记录平台、日期、条件 |
| 电商/垂直平台 | 电商、二手、招聘、房产等 | 商品/卖家/列表公开字段 | 只读公开或授权页面 |
| 论坛/社交 | 论坛、社区、评测、用户内容 | 体验、缺点、线索 | 不单独支撑主要事实 |
| 公开 API/数据集 | 官方开放接口、可下载数据 | 批量记录和时间序列 | 记录版本、口径与采集时间 |
| 已授权浏览器 | 用户现有登录会话 | 查看用户已授权的公开/账户可见字段 | 不扩大权限、不绕过控制 |

某类不适用时写明理由；适用但工具不可用、登录受限或反自动化限制时记录覆盖缺口，切换其他类别继续。

## 默认零凭证加速顺序

默认按 **Sitemap/RSS + 宿主已有搜索种子 → 临时 SearXNG → Common Crawl URL Index** 扇出：

- Sitemap、Sitemap Index、RSS 和站内目录优先，适合一次枚举已知品牌、商店、媒体或目录站的大量公开 URL。
- 宿主已有搜索先产出高质量查询、域名和样本 URL；需要更宽的多引擎/长尾覆盖时，每任务临时启动 SearXNG，查询完立即精确停止。
- Common Crawl URL Index 用于历史与批量扩张；公共 CDX 请求以 **1 → 2** 的低并发、高单批返回量运行，不下载 WARC 正文，也不用高并发冲击公共服务。**历史索引不得证明实时价格、库存或当前全量**。
- Common Crawl 的选择合同固定为：**exact URL → 单次 CDX**，由 `scripts/common_crawl_query.py` 执行；**domain/subdomain/prefix → DuckDB URL Index**，由 `scripts/common_crawl_url_index.py` 与 `scripts/duckdb_runtime.py` 做分钟级历史扩张。宽查询不得使用 CDX 分页；任务服从 10 分钟总时限，触及结果上限或时限时返回显式 `partial`，不能伪装完整覆盖。
- Firecrawl Map 和独立搜索 API 只在连接器、密钥、额度、成本真实可用并获准时加入；它们不是第一阶段必需主干，返回链接数不能记成成功正文页数。
- 联盟或其他授权接口仅在用户明确选择且权限探测通过后使用；京东/淘宝无权限时标记 `available=false`，只用公开索引和搜索摘要，不能宣称平台全量，也不以凭据缺失阻塞零凭证路线。**京东联盟 API 对本账号固定 `available=false`**：开放平台等级 V0、`jd.union.open.goods.query` 关键词接口额度 0、升 V1 需月订单/GMV/UV（当前为 0）；不进入候选路由，仅在出现新权限证据时重新评估。

这条路线空闲零常驻：不自动启动 Docker Desktop，不创建持久 volume，不保留监听端口或索引。临时 SearXNG 使用回环端口、768 MiB/2 CPU 限制和精确容器 ID；Docker、镜像或健康检查不可用时只降级该后端。成功、失败和中断都验证精确清理，其他后端继续。

### 商品型任务的命中优先路线

通用路线不等于商品路线。目标对象是商品、型号或 SKU 时，按以下顺序执行：

1. **商品专用 Sitemap**，包括 `sitemap_products_*.xml`、商品 URL 前缀分片及明确标为 product 的 Sitemap；
2. **商品分类页**、collection/category 列表及其中的商品详情链接；
3. **JSON-LD Product**、公开商品 Feed、站内公开商品 API 或可直接导出的商品结构化数据；
4. Firecrawl Map、独立搜索 API、Common Crawl URL Index 用于发现新品牌、别名与长尾商品入口；
5. **根 Sitemap 仅作覆盖审计和补漏**，不得把整站文章、法律页、语言镜像和其他非商品 URL 计作商品覆盖。

每个后端同时计算 `product_candidate_yield = product_page_candidates / normalized_unique_urls`。根 Sitemap 连续批次低于 **5%** 时停止扩张同类根 Sitemap，切换商品专用入口；这只是后端换路条件，不是全局搜索停止条件。站点本身高度垂直且命中率健康时仍可继续使用其根 Sitemap。

商品搜索的预期新增量按**纯发现时间 × URL 发现速度 × 商品/记录命中率**理解；原始 URL/s 只是发现容量，不是最终效用。每个后端、每个批次同时记录 `product_candidates_per_second`、`unique_valid_records_per_second` 和边际唯一型号新增量。覆盖缺口仍存在时，将追加时间优先分配给**单位发现时间新增有效型号最多**且访问健康的商品 Sitemap、分类页或结构化入口；持续产出 URL 却不新增型号的入口降低份额或停止，延长时间不得替代纠正方向。

商品来源必须区分制造者、销售者与发现索引。记录 `source_role`、`brand`、`seller`、`market_region` 和 `purchase_access`；`source_role` 枚举为 `brand_official`、`vertical_retailer`、`marketplace_store`、`search_index`、`historical_index`。首次出现用户可能陌生的站点时用一句话解释角色、地区和购买可达性。例如 **Pillows.com 是美国枕头与床品垂直零售商，不是枕头品牌**；其目录可扩展多个品牌的在售线索，但关键型号与材料仍优先回到品牌官网核验，也不能默认中国用户可直接购买。

商品相关性必须按字段隔离判断，避免“大网撒对了、分类器算错了”：

- URL 证据只使用规范化 URL 的 path（按完整 path token 词边界匹配，`pillowcase`、`production`、`nonproduct` 等子串不晋升）；不得使用 query 或 fragment；域名品牌词不能让站内所有商品自动命中。受控例外：`discover_sitemaps.py` 的 `product_hostnames` 精确名单识别主流平台商品子域名（`item.jd.com`、`item.m.jd.com`、`item.taobao.com`、`detail.tmall.com`、`detail.tmall.hk`、`detail.1688.com`）作为 `product_hostname` 证据——京东/淘宝的商品标记在子域名而非路径，这是**受控精确名单**，不是品牌关键词启发式，也不让站内其余 URL 命中。默认 `product_path_hints` 扩至 `product/products/prod/goods/spu/commodity/catalog`，可用配置覆盖。
- 文本证据优先使用主商品标题；不得把图片 alt、图片 caption、描述、推荐商品标题与主标题拼接后再做相关性判断。
- 英文关键词采用完整词或受控词边界；`pillowcase`、`pillow-top`、品牌名中的 `pillow` 等不得仅凭子串晋升为枕头商品。
- `product_page_candidates` 至少需要商品 URL/分类成员资格或 `Product` 结构化证据之一；`unique_valid_structured_records` 还必须有可独立确认的主标题、规范 URL 与稳定 ID/型号归并键，并通过配件/非目标排除。
- 若抽检发现字段串扰或子串污染，保留并报告机器候选数与污染原因；受影响记录只算待复核候选，不得晋升为 `unique_valid_structured_records`。

商品 URL 账本必须保留 `first_discovery_channel` 和 `all_discovery_channels`，才能计算 Sitemap-only、搜索-only、分类页-only 及其交集。没有该账本时，不得把最终对象强行归因给任一发现渠道。

## 免费批量与本地索引

按从轻到重的顺序选择路线：

1. 先复用当前宿主已可调用且获授权的搜索、公开 API、站点地图、RSS 和垂直数据源，不安装服务。
2. 万次级发现或按次费用不合预算时，优先查询 **开放索引/开放数据**；通用网页使用 Common Crawl 的 URL/列式索引，领域任务使用相应开放数据集。一次批量查询应产生许多候选 URL，不把 10,000 个目标机械转换成 10,000 次搜索 API 调用。
3. 需要反复检索一批已知网站或需要可复用全文索引时，才部署 Fess 作为爬取、OpenSearch 索引和查询的一体化首选。
4. 只有 Fess 的抓取吞吐经测量不足时才增加 Spider；只有需要多进程、多机器或异构爬虫统一调度时才增加 Crawlab。

不为 URL 规模里程碑预装 Fess、Spider、Crawlab、浏览器集群或常驻服务。临时 SearXNG 可作为本轮搜索域名扩张器，但不能代替 Sitemap、开放索引或严格核验；OpenSERP、4get、LibreY 等其他**元搜索只补漏**。所有元搜索都继承上游引擎的验证码、429、结果窗口和可用性；Parallel 等免费额度也只作补充，不作为永久免费承诺。付费接口必须服从用户的硬预算闸门。

GitHub 万次级路线固定为 **发现 → 按需获取 → 本地索引 → 本地查询**：

- GitHub Search API 不作为大规模主干；它只负责小规模即时补漏、最新状态和最终一手核验，并遵守返回的配额与重置时间。
- 优先用 GH Archive 发现仓库与活动，用 Software Heritage 和 World of Code 补充公开代码与历史关系；只获取或克隆筛选后的相关仓库。
- 用户明确需要可复用代码搜索且批准持久索引时，用 Zoekt 建立本地索引；普通单次调研仍使用会话内存和固定提交证据链接，不落盘索引。

用户单独批准的 Fess/Zoekt 可复用索引属于基础设施产物，不属于一次普通调研可隐式创建的中间文件；未获得这种明确批准时仍执行零部署路线。

## 接力式扇出

默认数据流是 **种子发现 → 批量扩张 → 去重抓取 → 证据回流**，由本 Skill 在会话中调度，无需新增常驻总控服务：

- 种子发现：用 Codex 内置网页搜索、已连接的搜索工具和垂直入口产生高质量关键词、域名与样本 URL。先读取当前会话工具 schema，遵守单次查询数组上限，不把计划并发强加给工具。
- 批量扩张：把种子域名和 URL 模式交给 Common Crawl、公开数据集、站点地图/RSS、站内目录及公开 API；优先选择一次返回大量 URL 的入口。
- 去重抓取：先规范化并去重，再按页面类型选择内置正文读取、已配置的 Firecrawl、普通 HTTP 抓取或已授权浏览器；同一规范化 URL 只抓取一次，动态页面才进入较重路线。
- 证据回流：把新增域名、别名、字段和缺口反馈给下一轮查询；只把高相关对象送入严格核验，不把全文重新投入所有后端。

每轮按新增有效 URL/秒分配下一批：高收益后端继续扇出，低收益或重复率高的后端切换查询族，受限后端进入补偿队列。嵌套只传递新增种子和未闭合缺口，不递归重复整批结果。



## Sitemap 实时预检与批量闸门

批量候选发现必须先运行 `scripts/discover_sitemaps.py`，以 JSON 事件流建立实时证据；Windows 的规范 Sitemap 传输是 Python `urllib`/OpenSSL，而 PowerShell/curl 的 Schannel 路线是独立传输。Python `urllib`/OpenSSL 不返回 Schannel `SEC_E_NO_CREDENTIALS`。从每个种子域名的 `robots.txt` 读取声明的 Sitemap，合并用户给出的显式 Sitemap，并依次尝试 `/sitemap.xml`、`/sitemap_index.xml` 与 `/sitemap-index.xml`。递归解析 Sitemap index，优先访问产品、collection、page、blog 分片；每个文档有大小和超时上限，递归有最大深度，已见 URL/索引必须防循环。没有全局 URL 数量上限，但必须执行每文档、时间、深度与循环界限。

每个 primary 与 media URL 事件都必须显式输出 `discovery_channel="sitemap"`；去重合并时把该值归入 `first_discovery_channel` 和 `all_discovery_channels`，不得依赖下游根据 `sitemap_url` 猜测通道。事件中的 `url_kind=primary` 才进入候选页账本；`url_kind=media` 只增加 `media_url_observations`，不得冒充页面候选。

primary 事件用稳定列表 `product_candidate_evidence` 解释商品候选：包含它的 Sitemap URL path 只有按非字母数字边界切分后出现精确 path token `product` 或 `products`，才加入 `sitemap_product_shard`；商品 URL path 命中受控配置时加入 `url_path_hint`。query、任意 substring 与 `nonproduct` 均不得触发商品分片证据。`sitemap_product_shard` 只是进入商品页候选的受控身份证据，不等于已核验商品或唯一有效记录。media 事件的该列表必须为空。

汇总分别报告 `raw_url_observations`、`primary_urls`、`primary_urls_per_second`、`media_url_observations`、`product_page_candidates` 与 `product_candidates_per_second`。每个失败事件保留稳定 `error_category`，汇总保留 `error_category_counts`、`unresolved_bulk_backends`，不丢弃受限、超时、XML 无效或文档过大的失败。

批量就绪状态必须精确采用脚本终端汇总的 `bulk_readiness_state`：

- `bulk_unchecked`：尚未得到该后端的终端汇总，不能开始或宣称批量发现。
- `bulk_ready`：有有效 Sitemap，且满足以下任一实测条件：站点范围产生 `primary_urls > 0`；原始 URL 观察速度达到 50/s；或 `exhaustive_seed_count >= 2` 且同时有 `primary_urls > 0`。空 Sitemap 不能进入 `bulk_ready`；**只有 `bulk_ready`** 可以称为大规模发现。
- `bulk_degraded`：有有效 Sitemap 但未达到上述就绪条件；可保留结果与错误统计，并披露为降级发现，不能把它写成大规模发现。
- `bulk_unavailable`：普通 `search` 后端、没有有效 Sitemap，或预检终端状态如此判定；必须报告阻塞项并**硬停止**该大规模阶段，不能继续用搜索结果冒充批量资格。

普通搜索不能满足批量闸门：它至多提供下一轮的种子、域名或显式 Sitemap。`bulk_unavailable` 后可以分别预检 Firecrawl Map、独立搜索/API、离线索引或 Common Crawl 等后备后端；其中只有获得其可审计的批量就绪证据的路线才能重新进入大规模发现。仅当 PowerShell/curl 的 Schannel 路线返回 `SEC_E_NO_CREDENTIALS` 时，切换到 Python `urllib`/OpenSSL 或另一实际可用且已预检的后备路线，并且绝不重复相同路线和参数。

## 后端能力清单与低速换路

每轮开始时把可调用能力映射为以下 `kind`；名称不同但能力相同的工具仍按能力归类，且分别记录 `available`、`attempted`、真实并发上限、成本、权限和覆盖范围。

| kind | 能力边界 | 典型入口 |
| --- | --- | --- |
| `search` | 返回搜索结果页中的 URL 观察值，通常有结果窗口 | 搜索引擎、Codex 网页搜索 |
| `sitemap` | 一次枚举站点公开 URL | Sitemap、RSS、站内目录 |
| `open_index` | 批量查询历史网页 URL/对象 ID | Common Crawl Columnar Index |
| `dataset` | 离线或开放数据集批量发现 | GH Archive、开放商品/目录数据 |
| `bulk_api` | 返回实时或准实时结构化记录 | 官方 API、淘宝联盟、获授权导出（京东联盟对本账号固定 `available=false`，见上文） |
| `page` | 打开真实网页并验证正文或字段 | HTTP、Firecrawl、已授权浏览器 |

批量发现目标为 **50 个未去重 URL/秒**，分母是纯发现活动墙钟时间，分子是所有合法 HTTP(S) URL 出现次数，重复也计入。完成**至少两个批次**且达到 **5 秒**后，累计速率或最近窗口仍低于目标时必须立即换路：

1. 优先加入一个 `available=true`、`attempted=false` 的 `sitemap`、`open_index`、`dataset` 或 `bulk_api`；
2. 可用批量后端均已尝试时，切换查询族、URL 前缀分片或领域入口；
3. 没有可用批量后端时记为 `bulk_unavailable`，报告阻塞项并硬停止大规模阶段；后续只能为新的后备后端收集种子和重新预检，普通 ranked search 不得替代闸门。

低于目标持续到 **15 秒**时，进度消息必须披露累计与最近窗口速率、当前 `kind`、各后端真实并发上限、已尝试的加速路线及未达标原因。50 URL/s 是换路和披露目标，不是停止条件，也不授权绕过验证码、配额、付费或登录控制。

## 高摩擦平台与电商

当平台存在登录、验证码、动态渲染、严格限流，或用户提出页面/记录吞吐目标时，按以下顺序分层，不用受保护 HTML 页面承担大规模主干：

1. **零凭证批量发现**：先用 Sitemap、可用的 Firecrawl Map、独立搜索 API 和开放索引/开放数据（含 Common Crawl URL Index）扩展 URL 或对象 ID
2. **搜索摘要**：补充近期候选、长尾入口和未闭合查询族；摘要只能用于发现，关键字段回到一手来源
3. **直接 HTTP/已授权浏览器**：只读取去重后的代表样本、异常记录和最终候选，核对对象身份、字段映射、价格/库存时点和页面可见性
4. **官方或获授权的批量 API/数据导出**：仅在用户明确选择后使用；先确认字段、页大小、配额、权限和费用，不把联盟或精选商品误称为全站

每个批量来源都登记 `coverage_scope`（全站、联盟推广池、精选/策展池、商家自有或历史索引）、`permission_requirements`（权限）、`cost_basis`（成本）和 `data_freshness`（数据时效）。不能确认覆盖范围时标为未知，不从结果数量反推全站覆盖；没有授权批量入口时继续发现并抽样核验，同时明确大规模实时覆盖未达标，不绕过访问控制。

吞吐分别计算，不能互相换算：


- `raw_url_observations_per_second`：纯发现时间内所有合法 HTTP(S) URL 出现次数，包含重复；这是折线图与 50 URL/s 目标的口径
- `url_discovery_per_second`：纯发现时间内新增的规范化去重有效 URL 数
- `successful_page_bodies_per_second`：正文非空、对象身份匹配且不是验证/拦截页的唯一页面数除以页面读取时间
- `unique_valid_structured_records_per_second`：具有稳定对象 ID，或关键字段足以可靠去重的有效记录数除以批量数据请求时间

用户要求 **30 个页面/秒**时，只能用 `successful_page_bodies_per_second` 验收；批量接口达到 **30 条/秒**时，只能报告为 `unique_valid_structured_records_per_second`。不得把商品记录数、URL 发现数或“等价页面”写成成功页面数。

## 查询族覆盖

建立查询族而非机械改写一句话。至少评估：

- 主题、同义词、旧称、缩写、英文名、常见错写；
- 国家—省—市—区—商圈等地区层级；
- 当前、目标和历史时间表达；
- 品牌、型号、用途、规格、价格档和对象关系；
- 官网、媒体、目录、地图/预订、电商、论坛、数据库等来源限定；
- 适用语言和地区版本；
- 排除词、歧义消解词和反向线索。

每个适用维度登记 `applicable`、`attempted` 和未解决缺口。使用 `build_query_matrix.py` 惰性生成组合，先投放能覆盖新来源/对象的查询；重复率升高时切换角度，不设置查询数或 URL 数上限。

## 并发提升与独立退避

始终使用宿主、工具和速率限制允许的**最高安全并发**；下列档位按后端独立探测，**不是全局并发上限**。

1. 为每个后端维护独立队列、并发、延迟、错误率、429/配额和新增 URL 率；所有档位变更只通过 `BackendConcurrencyState` / `advance_concurrency`，补偿完成只通过 `drain_compensation`，调用方不得只保存整数档位或删除失败查询。
2. 普通任务按后端真实上限起步：SearXNG **2 → 4**、Common Crawl **1 → 2**、静态 Sitemap/页面 **4 → 8 → 16**、浏览器正文 **1 → 2**。只有健康的 Sitemap、`open_index`、`dataset` 或 `bulk_api` 聚合后才按 **24 → 32 → 40** 逐级爬坡；这些是调度目标档位，不是对单个工具的能力声明，40 不是通用上限。
   商品候选发现执行**跨来源并行**，但京东 Edge 固定为 1，并在同一授权会话中顺序翻页；SQLite 批次提交保持单写入。京东冷却不得压低其他来源，不能把同一京东会话的多标签并行当作独立配额。
3. 以规范化去重有效 URL/秒、覆盖缺口闭合率、延迟和补偿队列积压判断净收益；健康窗口完成后才升一级。
4. 少量、孤立的 429 不触发降档；失败查询进入补偿队列，用较低并发或其他后端补搜，且不得从错误统计中删除。
5. 持续或成批限流、有效吞吐下降或关键缺口扩大时，只让受限后端从 40 降至 32 并进入 **32 稳定窗口**；其他后端维持或提升。
6. 32 恢复健康时先稳定运行，窗口完成后再回升 40；只有 32 仍不健康才再降至 24，24 仍不健康时继续逐级降低。
7. 相同失败参数不得原样重试；真实故障先遵守事故合同。

页面通道按 429、验证码、空正文和延迟**独立退避**；API/离线索引通道按各自配额与延迟单独控制，在健康时可保持高并发。页面通道的降档不得压低 `bulk_api`、`dataset` 或 `open_index`，反之亦然；聚合目标 24 → 32 → 40 由各健康后端真实并发之和构成。


调度层统计的是跨后端的**聚合在途任务数**，可达到的聚合值最多是各后端真实并发上限之和；不得向单一后端强塞聚合档位。进度和最终统计同时报告调度目标档位与**实际达到的最高并发**；不得把目标档位写成实际并发，也不得为凑档位突破后端限制。

完整市场任务由 `scripts/market_scheduler.py` 的 `market_discovery` 全局运行驱动，具体状态与工具信封见 `global-scheduler.md`。Sitemap 预检、Firecrawl、独立搜索、开放索引和数据集都是可切换的 `backend_batch`；某条路线的 `bulk_ready` 只证明能力，`queue_exhausted` 只结束当前批次。全局调度器根据有效对象/秒、规范 URL/秒、覆盖价值和通道健康度自动换来源、换查询、补偿失败任务；没有当前可租用任务但覆盖仍有缺口时只能保存 `incomplete_blocked`，不能宣布完成。

## 纯搜索时钟和停止

查询方向、关键词矩阵和来源类别准备完成后才启动 `T_search`。只累计请求、等待、翻页、扩展查询和发现 URL；理解、去重、深读、核验、计算与写作不计时。

发现只允许：

- **搜索饱和**：全部适用来源和查询维度已尝试；连续三轮来自不同查询族和不同来源；新增有效 URL、对象、字段均为零且主要为重复；地区/语言/时间/平台缺口为空；域名不过度集中；继续搜索不会实质改变集合。
- **确定范围完成**：仅 `bounded_dataset_extract` 可用；必须给出非空 boundary，且 `expected_pages == completed_pages > 0`、`failed_pages == 0`，对应状态为 `deterministic_scope_complete`。
- **600 秒纯搜索上限**：停止提交新请求，接收即将完成结果，然后直接进入收敛与核验。

四种 `run_type`（`quick_direct`、`open_web_research`、`catalog_enumeration`、`bounded_dataset_extract`）统一使用 **10 分钟（600 秒）硬上限**；轻量任务可按上述证据提前结束，不另设其他默认时间预算。



任何数量里程碑、单次空结果、某个后端失败、单批 `queue_exhausted` 或少数域名高度集中都不是停止理由。**未去重 URL 增长不能单独证明搜索饱和**；必须结合规范化去重边际收益、对象/字段收益、重复率、异构零收益轮次和覆盖缺口。跨重启恢复不得清零纯发现时间，跨轮已验证对象按有明确失效证据的累计并集维护。发现结束先报告统计，报告不暂停后续阶段。

## 访问与完整度边界

不绕过验证码、登录、付费墙、robots/反自动化限制或平台访问控制；不从公开页面反推隐私字段。访问受限但页面身份可确认时保留 URL 并标记限制。最终用尝试过的来源类别、独立域名、边际新增率、停止原因和未覆盖入口表达完整度，不声称绝对穷尽互联网。
