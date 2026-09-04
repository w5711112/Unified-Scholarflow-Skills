# 统计与报告合同

按需在生成每分钟进度、发现结束统计、最终聊天或用户要求的 Markdown 前读取。统计消息不得成为暂停点。

## 每次必交付的搜索轨迹

**每次使用本 Skill** 都必须在发现结束后的聊天与最终回答中展示一张发现—筛选完整轨迹图；用户另要求保存 Markdown 时，同样写入 `## 搜索轨迹`：

`quick_direct` 可以只含起点、权威来源返回点和结束点，并报告实际运行秒数；不得为了填满图表继续搜索。其他运行类型按批次、换路和并发变化记录完整轨迹。

- 横轴是 `T_discovery`，即纯发现时间的墙钟并集；并行重叠请求只计一次，其他思考、去重、深读和写作时间不计入。
- 纵轴是累计未去重 URL，即 `raw_url_observations`；每次出现合法 HTTP(S) URL 都计数，重复照计。
- 至少记录 `(0, 0)`、每批结束、后端切换、并发档位变化和最终点；累计时间及全部累计计数不得回退。
- 左/下轴显示纯发现时间与累计未去重 URL，发现线为绿色 `#2e7d32`、`4px`；上/右轴显示筛选阶段与保留数量，筛选线为红色 `#c62828`、`4px`；坐标轴与文字近黑色 `#111111`、坐标轴 `2.5px`。图内标注平均 URL/s、商品命中率、阶段计数和保留率；阶段标签跟随对应红色点的实际纵坐标，以短连接线标明归属，并在绘图区边界内轻量错位，不得压成两条固定水平行。图表自动缩放且不设置 URL 上限。
- 商品型 SVG 保留全部真实检查点，为每个真实检查点绘制绿色 marker；只有起点和终点时仍绘制连线和两个 marker，不插值。发现终点与红色漏斗点重合时，先绘制红点，再为重叠漏斗终点绘制绿色空心环，不偏移真实坐标。
- Codex 支持内嵌 HTML 时，**优先输出轻量 HTML fragment**：在 Codex 对话内用依赖为零的 SVG，滚轮以指针为中心在 `1×–4×` 缩放，放大后可拖动平移，并提供放大、缩小和重置按钮；标题不小于 `24px`、轴标题和图例不小于 `18px`、刻度与阶段标签不小于 `16px`。达到缩放边界后继续同方向滚动应交还对话滚动，且**不打开外部浏览器**。**无 HTML 时回退 SVG**，**非商品发现再回退 Mermaid** `xychart-beta`，**商品型任务最终回退为发现字符折线加完整漏斗数字**。
- 商品型任务的红线固定使用同一批次七级漏斗：`raw_url_observations → literal_unique_urls → normalized_unique_urls → content_unique_pages → topic_relevant_pages → product_page_candidates → unique_valid_structured_records`。阶段必须单调不增；第一阶段必须等于发现线最终原始观察数。宿主不能渲染 SVG 时，回退为发现字符折线加完整漏斗数字。

图下分别列出 `raw_url_observations_per_second`、`url_discovery_per_second`、`successful_page_bodies_per_second`、`unique_valid_structured_records_per_second`、重复率、去重边际新增率、对象收益、覆盖缺口、搜索模式与 50 URL/s 目标是否达到。商品型任务另按后端列出原始 URL、规范化唯一 URL、商品候选、有效记录、`product_candidate_yield` 和主要淘汰原因。未执行的页面或记录通道写“未执行”。

商品型任务另列 `product_candidates_per_second`、`unique_valid_records_per_second`、边际唯一型号新增量，以及 `source_role`、`brand`、`seller`、`market_region`、`purchase_access`。首次出现陌生站点时先解释它是 `brand_official`、`vertical_retailer`、`marketplace_store`、`search_index` 还是 `historical_index`；不得把零售商库存写成该零售商自有品牌型号。

**未去重 URL 增长不能单独证明搜索饱和**。搜索饱和仍需异构查询族连续零收益、规范化去重 URL/对象/字段收益为零、覆盖缺口关闭和域名不过度集中；折线只用来审计发现速度、换路效果和是否接近收益平台。

## 约每分钟进度载荷

每次进度至少报告：

- `pure_search_seconds`：已累计纯搜索秒数；
- `requests`、`batches`：请求数与查询批次数；
- `raw_results`、`valid_urls`、`normalized_unique_urls`；
- `content_unique_pages`、`unique_objects`、`independent_domains`；
- `per_source_counts`：按来源类别分区的有效结果条目数；
- `highest_concurrency`：本轮已达到的最高并发；
- `marginal_yield`：当前新增率；
- `current_gaps`：未覆盖地区、语言、时间、平台、来源与查询维度。
- `bulk_readiness_state`、`sitemap_documents_fetched`、`raw_url_observations`、`primary_urls`、`media_url_observations`、`primary_urls_per_second`、`product_page_candidates`、`product_candidates_per_second`、`error_category_counts`、`unresolved_bulk_backends`：批量闸门、Sitemap 事件和未解决后端的实时统计。

计数必须满足 `raw_results >= valid_urls >= normalized_unique_urls >= content_unique_pages`；独立域名不超过去重 URL。进度只告知，不要求用户确认，搜索继续。

用户提出页面、URL 或结构化记录吞吐目标，或任务使用高摩擦平台/电商路由时，另报：

- `raw_url_observations`：累计出现的合法 HTTP(S) URL 数，重复也计入；
- `raw_url_observations_per_second`：上述未去重累计数除以纯发现时间；
- `url_discovery_per_second`：规范化去重有效 URL 的发现吞吐
- `successful_page_bodies_per_second`：成功返回正文且对象身份匹配的唯一页面吞吐
- `unique_valid_structured_records_per_second`：具有稳定 ID 或足够关键字段、完成对象去重后的有效记录吞吐
- `coverage_scope`、`permission_requirements`、`cost_basis`、`data_freshness`：各批量来源的覆盖范围、权限、成本和数据时效

三个速度必须保持分离：原始 URL 观察/s、成功页面正文/s、有效商品记录/s 都使用各自实际请求/等待时间和分母，不相互换算。记录或 URL 达到目标不代表成功页面达到目标；错误、验证码页、空正文和重复对象不计入成功数，但保留在错误统计中。

## 发现结束载荷

发现停止时立即给出完整进度载荷，并增加：`run_type`、停止原因、适用/已尝试来源类别、访问受限 URL、域名集中度、连续饱和轮证据和仍存在的覆盖限制。`quick_direct`、`open_web_research`、`catalog_enumeration` 可报“搜索饱和”或“达到10分钟”；`bounded_dataset_extract` 可报“确定范围完成”或“达到10分钟”。时间出口要求 `pure_search_seconds >= 600`；饱和出口必须给出连续三轮异构零收益、全部适用来源/查询维度已尝试、覆盖缺口关闭和域名不过度集中的证据。确定范围完成必须给出 `boundary`、`expected_pages`、`completed_pages`、`failed_pages`，且预期页数等于完成页数并大于 0、失败页数为 0，对应 `deterministic_scope_complete`。四种运行类型统一使用 **10 分钟（600 秒）硬上限**。

`catalog_enumeration` 未闭合时必须逐项披露品牌、卖家、地区、平台、价格/规格等覆盖缺口，不得把公开网页或历史索引候选写成当前平台全量；历史索引不得证明实时价格、库存或当前全量。`bulk_unavailable` 单列阻塞项与 `unresolved_bulk_backends`，只结束对应后端并让全局调度器换路；若没有可用路线又不满足成功状态，状态是 `incomplete_blocked`，只能提交可恢复检查点。成功报告后自动进入去重、筛选、L1–L3 和严格核验，不结束任务。

完整市场报告还必须包含这些非空项目行：`全局运行 ID`、`运行类型`（四个 `run_type` 之一）、`范围指纹`、`上一轮已验证对象数`、`本轮新增已验证对象数`、`本轮重叠对象数`、`明确失效对象数`、`累计已验证对象数` 和 `停止证据`。累计数必须满足跨轮并集算式；每个明确失效对象都要在报告中列出稳定对象键、原因和新的 HTTP(S) 证据。搜索轨迹中的运行 ID 必须与统计相同，不能把预检或单批轨迹嫁接成全局运行。

## 计数定义

- **原始结果数**：工具返回条目总数，包含重复。
- **未去重 URL 观察数（`raw_url_observations`）**：每次出现合法 HTTP(S) URL 都计数，重复照计。
- **字面唯一 URL（`literal_unique_urls`）**：仅按原始 URL 字符串去重。
- **有效 URL 数**：可解析的 HTTP(S) 页面且身份/摘要与查询合理相关；身份可确认的受限页面单独标记后可计入。
- **规范化去重有效 URL 数（`normalized_unique_urls`）**：清理跟踪参数并规范化主机、路径后的唯一 URL；规模里程碑只用此数。
- **内容去重页面数（`content_unique_pages`）**：进一步合并镜像、转载和正文实质相同页面。
- **主题相关页面数（`topic_relevant_pages`）**：页面主题与目标对象匹配，包含商品详情、分类/列表、配件或相关编辑页。
- **商品页候选数（`product_page_candidates`）**：有商品详情身份或 Product 结构化证据、值得进入字段抽取的页面。
- **唯一有效结构化记录数（`unique_valid_structured_records`）**：完成商品/型号对象去重且关键字段足以确认身份的记录。
- **独立域名数**：规范化 URL 的唯一主机数，不把子路径当域名。

每条商品 URL 至少保留 `first_discovery_channel`、`all_discovery_channels`、页面类型、当前漏斗阶段、淘汰原因和对象归并键。常用淘汰原因分列为字面重复、规范化镜像、内容镜像、非主题页、文章/指南、分类/列表页、配件/非目标商品、无法确认对象和同型号重复。

## 最终聊天顺序

1. 直接结论；
2. 完整度允许范围内的对象清单或数据；
3. 比较、推荐或趋势；
4. 冲突、缺失和待核验；
5. 关键来源链接；
6. 完整检索统计、停止原因和覆盖限制。

事实、派生计算与判断分别标记。重要对象或数据行尽量附直接来源。未达到用户目标或 1,000 URL 验收时直说未达标，不改用原始条目数。

高摩擦平台或吞吐目标任务还需逐项给出上述三种实际吞吐、覆盖范围、权限、成本、数据时效和抽样核验规模；没有执行某一通道时写“未执行”，不能用估算的“等价页面”代替。

## 可选 Markdown

仅在用户明确要求保存/报告/Markdown 时写一个最终文件；默认不写。建议使用不覆盖同名文件的 `调研报告/YYYY-MM-DD-主题.md`，并包含：

- `## 调研问题与假设`
- `## 核心结论`
- `## 搜索统计`
- `## 搜索轨迹`
- `## 方法与停止原因`
- `## 完整结果或数据`
- `## 比较、排序或趋势`
- `## 冲突与缺失`
- `## 来源`
- 必要时 `## 数据附录`

`## 搜索统计` 至少使用非空项目行：全局运行 ID、运行类型、范围指纹、纯搜索时间、原始结果数、未去重 URL 数、有效 URL 数、规范化去重有效 URL 数、未去重 URL/s、规范化去重 URL/s、成功正文页/s、有效结构化记录/s、搜索模式、50 URL/s目标、独立域名数、来源类别、最高并发、上一轮已验证对象数、本轮新增已验证对象数、本轮重叠对象数、明确失效对象数、累计已验证对象数、停止原因、停止证据。未执行的页面或记录通道写“未执行”；停止原因值精确为“搜索饱和”“达到10分钟”或“确定范围完成”，并必须与运行类型匹配。`## 搜索轨迹` 必须标明相同的全局运行 ID。`## 来源` 至少包含一个有效 HTTP(S) Markdown 链接。完成后调用 `validate_report.py`。

## 产物白名单

搜索前后比较工作区文件清单。默认允许新增文件为空；用户明确要求报告时只允许约定的最终 Markdown，事故处理时另允许项目守卫指定的事故库。URL 池、页面缓存、正文、临时 CSV/JSON、截图、爬取数据库、任务队列和筛选缓存均不允许。使用 `unexpected_artifacts(before, after, allowed)` 处理 Windows/Unix 分隔符和路径大小写后验证；出现额外产物即为验证失败，不能声称完成。
