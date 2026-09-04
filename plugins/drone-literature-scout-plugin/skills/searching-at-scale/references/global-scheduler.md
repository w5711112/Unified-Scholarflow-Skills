# 全局市场发现调度器

本参考规定完整市场发现如何跨来源持续运行、跨重启恢复，以及何时才允许结束。它约束 `scripts/market_scheduler.py`；单次预检或单个后端批次不能代替全局运行。

## 运行身份与三个层级

- `preflight_probe`：验证某条路线是否真实可用，只产生能力证据。
- `backend_batch`：执行一个来源、查询族和覆盖切片，只产生批次结果。
- `market_discovery`：拥有全局运行 ID、`run_type`、范围指纹、来源池、查询维度、覆盖缺口、纯发现时间、失败审计、SQLite 账本路径和跨轮已验证对象并集；大量 URL 不进入状态 JSON。

只有 `market_discovery` 可以得出市场层面的完成状态。`bulk_ready` 只说明某个批量通道可用；`queue_exhausted` 只结束当前批次或当前任务，不得冒充全局搜索饱和。

## 必须执行的循环

1. 用 `start` 创建全局状态，声明范围指纹、来源池、查询种子、适用查询维度、覆盖缺口、上一轮已验证对象及其证据。
2. 查询矩阵以游标惰性分批；用 `next` 租用当前最高收益且健康的任务，或用 `run-backends` 把 Sitemap/RSS、临时 SearXNG、Common Crawl URL Index 等统一信封直接交给后端组运行器。
3. `backend_runner.py` 为每个任务创建不超过 64 KiB/行的有界 NDJSON 卷轴，完整关闭后由主线程流式写入任务专属 SQLite；批次先提交账本，再返回只含计数、时间区间、轮次和遥测的小结果。
4. 用 `ingest` 原子合并小结果。批次 ID 幂等；调度器按 SQLite 中已提交的批次身份和计数对账，重启时重放已提交但未写入 JSON 的终端摘要。失败批次记录路线与参数摘要，禁止原样重试，并切换查询、来源或并发。
5. 调度器根据对象新增率、URL 新增率、覆盖价值、错误率和延迟重新评分；一个来源 `queue_exhausted` 后自动选择另一来源或查询族。
6. 候选反馈出的品牌、材质、型号族、地区或平台只扩张一次，进入新的查询任务，避免反馈回路无限复制。
7. 每批后保存状态。进程中断或电脑重启时使用 `resume`；恢复不得清零纯发现时间、累计 URL、已尝试维度、失败审计或跨轮并集。
8. 用 `status` 检查全局状态。`running` 继续调度；`incomplete_blocked` 保存检查点并明确缺口，不能写成完成；只有与 `run_type` 匹配的三个成功状态之一才进入最终筛选和报告。

## 运行类型与三个成功状态

每轮必须声明 `quick_direct`、`open_web_research`、`catalog_enumeration` 或 `bounded_dataset_extract`。四种 `run_type` 统一使用 **10 分钟（600 秒）硬上限**，不另设其他默认时间预算。`market_discovery` 仍是全局运行身份，`run_type` 决定证据和停止语义：

- `search_saturated`：所有适用来源类别和查询维度均已尝试；连续三轮来自不同查询角度和不同来源且没有新增；主要结果为重复；覆盖缺口关闭；域名不过度集中；继续搜索不太可能改变候选集合。
- `ten_minute_limit`：纯发现时间的墙钟并集达到 `600 秒`。达到阈值后不再提交新发现请求，只接收已在途批次。
- `deterministic_scope_complete`：只适用于 `bounded_dataset_extract`；boundary 非空，`expected_pages == completed_pages > 0` 且 `failed_pages == 0`。只完成一个分页、看到空页或达到预计 URL 数不得使用此状态。

任何单一后端空结果、单批队列耗尽、`bulk_ready`、URL 数量、对象数量、预算里程碑、无当前可租用任务或工具暂不可用，都不是成功出口。无法继续但又不满足成功条件时状态必须是 `incomplete_blocked`。

## 纯发现时间

`T_search` 只累计发现请求在途的单调时钟区间并集；并发重叠只计一次。方向设计、去重、聚类、正文抓取、页面验证、计算、绘图和写报告不计时。

状态按会话保存单调区间。重启后开启新的计时会话，绝不拿不同系统启动周期的单调时钟直接相减。全局纯发现时间等于各会话区间并集长度之和，永久最大值为 `600 秒`。

## 跨轮累计并集

父轮已验证对象与本轮新增对象按稳定对象键做并集：

`累计已验证对象数 = 上一轮已验证对象数 + 本轮新增已验证对象数 - 本轮重叠对象数 - 明确失效对象数`

累计并集不得自然缩小。删除旧对象必须逐条提供失效原因和新的证据 URL，并保留原证据与失效审计。查询方向变窄、某轮没重新搜到、页面临时失败或批次被跳过都不能让旧对象消失。

## 来源切换与并发

- 来源池至少区分 `search`、`sitemap`、`open_index`、`dataset`、`bulk_api` 和 `page`，只调度本轮真实可用的来源。
- 商品发现优先商品 Sitemap、分类页、公开 Product 结构和商品 Feed；低命中根 Sitemap 自动降权并切换方向。
- 轻量档位按适配器独立设置：SearXNG `2 → 4`、Common Crawl `1 → 2`、静态 Sitemap/页面 `4 → 8 → 16`、浏览器正文 `1 → 2`。只有健康批量后端的真实上限之和才组成 `24 → 32 → 40` 聚合目标；429、验证码、空正文或高延迟只降低对应通道。
- 排序优先边际有效对象/秒，其次为规范 URL/秒和覆盖缺口价值；不能仅凭原始 URL/s 把低命中来源长期排在前面。
- 外部工具返回 `queue_exhausted` 时只标记对应任务已耗尽。只要还有未尝试来源、查询维度或未闭合覆盖缺口，就必须继续生成或选择任务。

## 工具桥批次信封

`next`/`run-backends` 使用的任务信封至少包含：

- `run_id`、`scope_fingerprint`、`task_id`、`lease_id`、`time_session_id`
- `adapter` 和 JSON 可序列化 `payload`
- `query_family`、`source_class`、查询或 Sitemap/Common Crawl 范围
- 当前真实并发档位与覆盖目标

工具执行后回传的批次结果至少包含：

- 相同的 `run_id`、`task_id` 和以租约为批次 ID 的 `batch_id`
- `ledger_committed=true`、SQLite 对账计数和 `end_reason`
- 本批单调时间区间
- `raw_url_observations`、有效 URL、唯一新增和账本总唯一数；不得返回 URL 列表
- 新增有效对象键、字段收益和覆盖变化
- 429、验证码、空正文、延迟与错误类别

调度器先在副本上验证整个批次，再原子替换状态；字段错误或运行 ID 不匹配时不得留下半批更新。

## CLI 最小路线

```text
market_scheduler.py start --config CONFIG --state STATE
market_scheduler.py next --state STATE
market_scheduler.py run-builtins --state STATE
market_scheduler.py run-backends --state STATE --max-tasks 8
market_scheduler.py ingest --state STATE --batch BATCH
market_scheduler.py status --state STATE
market_scheduler.py resume --state STATE
market_scheduler.py finalize --state STATE
```

状态 JSON 和 SQLite 账本只能位于调用方明确给出的任务专属路径。调度器采用临时文件加原子替换保存 JSON；SQLite 使用单事务批次、外键和幂等批次 ID，不使用 WAL，避免遗留常驻 sidecar。`run-backends` 成功、失败和中断都删除精确卷轴；临时 SearXNG 不自动启动 Docker Desktop、不创建持久 volume，按精确容器 ID 清理。其他确定性脚本仍保持无任务状态文件接口。

## 报告要求

最终统计必须写出全局运行 ID、运行类型、范围指纹、停止状态、停止证据、纯发现秒数、上一轮/本轮新增/重叠/失效/累计已验证对象数。轨迹图数据必须来自同一全局运行 ID。

如果状态是 `incomplete_blocked`，只能输出未完成检查点：说明已用来源、不可用来源、剩余查询维度、覆盖缺口、失败路线和恢复命令。不得把它包装成“搜完”“饱和”或最终市场清单。
