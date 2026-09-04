# Cycle Workflow

## 工作模式

| 用户意图 | 必须执行 |
|---|---|
| 先清理/合并论文库 | 只做预审计和合并，不检索新论文 |
| 执行搜索周期 | 预审计、缺口分析、官方来源检索、核验、总结、清理 |
| 更新研究方向 | 全库评分和方向分析；只有用户明确要求时才检索 |
| 自动化任务 | 执行一次可恢复的单周期入口，不启动常驻循环 |

## Manual cycle

1. 确认工作区和 `论文库统一.csv`、`论文总结.md`、`研究方向分析.md` 三个核心文件存在。
2. 运行 `audit_corpus.py --strict`，检查固定 15 列、完整原始摘要、官方摘要 URL、重复项和证据字段。
3. 如果有旧 Markdown，先合并并按官方来源复核；任何不完整记录都留在临时决策报告，不写主 CSV。
4. 完成全库 venue、年份、实验室、关键词和方向缺口分析。
5. 仅从官方出版社、会议 proceedings 和 DOI 页面检索候选；依次检查单机门槛、感知—控制闭环、排除主题、12GB 训练目标、Jetson 级部署和新颖性。每次只搜索一个角度；20 分钟没有新增接纳就轮换。
6. 通过 official/open full text 或 supplement 补全定量证据；摘要级记录只能用于主题相关性，不能用于算力或实验方向结论。
7. 更新 `论文总结.md` 和 `研究方向分析.md`：两位小数排名、技术路线、证据表、定量可行性证据、最小可行实验和明确证据缺口全部用中文。
8. 运行 `clean_cycle.py`，只保留三个核心研究文件以及插件和文档；删除已知临时产物。
9. 运行完整测试、严格审计和清理白名单；没有新鲜输出不得声称完成。

## Scheduled cycle

Use `scripts/install_task.ps1` to create a Windows Task Scheduler entry. The task invokes `scripts/run_cycle.ps1` once per trigger. It never keeps a resident process and it does not bypass the preflight gate.

## Failure handling

If one source fails, record the failure and continue with other sources. If official evidence is unavailable, mark the candidate `needs_verification`. If the lock is stale, write a stale-lock note and exit or retry according to the configured policy; never overwrite an active cycle.

## Progress contract

Emit `[Phase 0]` preflight, `[Phase 1]` gaps, `[Phase 2]` search, `[Phase 3]` write, `[Phase 4]` analysis, and `[COMPLETE]` cleanup/verification messages. Final output includes counts, direction count, and the three core files.

## 工具和最终输出边界

- 不使用 Kimi-only tools 或 handoff 机制。
- 需要浏览官方页面时使用 browser 或 firecrawl-web；需要最终引用时记录官方页面。
- 用户触发其 Obsidian 风格时，使用 `obsidian-note-style` 完成最终 Markdown 语言和结构检查。
- 不得在主 CSV 有不完整行时开始新论文搜索。
- 最终输出必须包含 accepted count、total count、direction count、三个核心文件和测试/审计/白名单结果。
