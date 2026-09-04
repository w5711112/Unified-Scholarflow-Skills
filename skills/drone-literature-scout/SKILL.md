---
name: drone-literature-scout
description: Use when searching, auditing, merging, summarizing, or periodically reviewing UAV/drone perception-control literature under strict official-source, single-UAV, compute, and deployment gates.
---

# 无人机文献证据补全与调研
## 插件级轻量故障协作

> [!important]- **快路径与慢路径**
> - **正常成功路径不写故障库**；普通成功步骤直接继续，不为每次工具调用扫描、查询或记录
> - 当前组件已知脆弱、准备复用历史方案或某路线刚失败时，才运行 `incident_registry.py preflight`：先查项目守卫指定的**本地事故库**，未命中再查**公共事故库只读**；都无匹配就继续
> - 出现**任意异常、非零退出、权限拒绝、结果缺失或验证失败**时，立即运行 `capture-event` 写入本地事故库；记录后才改变路线，同一路线再次执行前必须通过 retry guard
> - **最终回答前**扫描本任务的实际工具结果，补记尚未入库的真实失败、拒绝、非零退出和验证失败；预期 TDD RED、受控探针和用户取消不算产品事故
> - **只有本轮事件发生变化**或历史方案获得新的复用结果时才检查候选；候选非空才加载 `promotion_audit.py`，否则不增加额外工作
> - **本 Skill 的效果验证**：检索结果具有可访问的官方来源，论文身份与外部事实可核验，筛选字段和评分证据一致，未把推断写成论文事实
> - 插件任务开始或 Skill 清单变化时读取 `references/skill-collaboration-contract.md` 并动态核对职责；同一任务内清单未变时不重复枚举全部 Skill

### 通用大规模搜索前置

需要扩展跨网站、跨语言或跨来源候选时，可调用 `searching-at-scale` 完成前期候选发现、URL 去重和通用证据采集。返回结果只作为候选证据包；本 Skill 继续独占 venue、单无人机、感知—控制闭环、算力/部署门槛、论文库写入、方向评分和最终接纳，`searching-at-scale` 不得接管论文接纳。
## Obsidian 语言风格触发规则

当用户说“使用我的 Obsidian 语言风格”、 “按我的 Obsidian 笔记风格写”或语义等价表达时，**必须调用** `obsidian-note-style`，再生成或修改中文 Markdown。该 skill 负责表达层的标题、段落、表格、双向链接和“论文报告—可以推断—尚不能证明”分层；本 skill 继续负责论文筛选、官方证据、算力门槛、评分和插件流程。两者不能互相替代

维护一个以证据为先的无人机感知—控制论文库，并从全库动态生成研究方向。CSV 是唯一论文事实源；两个 Markdown 是分析视图，不得反向覆盖 CSV。

## 单次证据主链与按需加载

同一轮只维护一条证据主链；同一任务、同一版本下，每个 reference 只完整读取一次：

1. 先按 `references/file-format-spec.md` 与 `references/workflow.md` 审计三个核心文件、旧数据、锁和写入前提，形成 `CORPUS_AUDIT`；只要主 CSV 有不完整行就停止新检索。
2. 需要发现候选时，再加载 `references/screening-criteria.md` 与 `references/venue-white-list.md`；将身份、官方来源、完整原始摘要、全文状态、硬门和排除原因合并为 `CANDIDATE_EVIDENCE`。
3. 需要更新研究方向时，才加载 `references/scoring-rubric.md`，以已接纳全库和前述证据形成 `DIRECTION_EVIDENCE`；不得用排名掩盖硬门失败。
4. 仅在处理 Zotero/Obsidian 入口或双向回链时加载 `references/zotero-obsidian-entry-contract.md`，形成 `ZOTERO_RECONCILIATION`；它不替代论文事实核验。
5. 写入、生成中文分析视图、清理和测试只引用上述当前证据，最终形成 `CYCLE_ACCEPTANCE`，报告 accepted count、total count、direction count、三个核心文件和测试/审计/白名单结果。

同一证据边界内，每一 distinct risk 只核验一次，后续阶段引用证据 ID，不重复搜索、重复核验或另建平行台账。主 CSV、候选页面/全文、Zotero 状态、方向池、配置、锁、生成产物或用户授权发生变化时，只刷新受影响证据；官方全文、写入后重读和最终测试仍是新的证据边界，不得跨边界复用旧结论。

## 不可协商的合同

### 方案 A 偏好

- 优先选择能够在 Isaac Lab/vectorized RL 或同等级大规模并行仿真中训练的感知—控制闭环，尤其是需要强化学习训练、可通过多并行环境缩短墙钟时间的课题。
- 算力目标是 RTX 4090 single-digit hours，或 RTX 5070 Ti within one day。这些是项目预算门槛，不是论文事实；没有官方全文数字时必须写“未报告/待核验”。
- 部署不得超过 Jetson-class deployment，优先 Jetson Orin NX 或更低；above-Jetson、multi-GPU-only 或大显存模型方向不得晋级。
- generic single-UAV obstacle avoidance、generic multi-UAV collaboration 和普通路径规划只能作为基线或背景，不能因为传统可做而获得高排名。方向必须暴露非显然的学习/控制缺口和可信的发表上限。
- 方案 A 权重固定为：推荐度 0.05、前景 0.15、可行性 0.25、venue 匹配 0.10、独特性 0.25、证据强度 0.05、学习价值 0.15；所有排名保留两位小数。
- 未知训练时间、峰值显存、功耗、参数量、Jetson 延迟或真实飞行结果可以保留为“待核验”，但不能支撑定量可行性结论。

### 官方证据和写入合同

- 先完成 first corpus audit 和两来源合并，再开始新论文检索；只要主 CSV 有不完整行，就不得检索新论文，也不得做定量方向判断。
- 论文身份、venue、年份和摘要 URL 必须来自 official publisher/proceedings/DOI page。搜索结果、Google Scholar、社交媒体、Kimi 文件和 arXiv 只能发现线索，不能单独作为最终官方证据。
- 每行必须保留 complete original abstract 和 official abstract URL。标题、摘要改写、搜索摘要或助手生成的摘要都不能入库。
- 任何 compute、latency、memory、parameter、power、control frequency 或 experiment number，先查 official/open full text 或 supplement；全文没有报告就写“未报告”，不能猜测。
- 只接受 venue 白名单、单无人机或允许的无人机—地面系统、感知输入加闭环控制/安全输出。多无人机、群体、事件相机、VLA/VLM/LLM、大型 NeRF/3DGS、纯检测、纯综述和高速度特技方向按门槛排除。
- 方向池动态保留 0–15 个方向，不保护固定名额；每轮重新评分。

### 永久格式和语言防回归

- 只能用 UTF-8 或 UTF-8-SIG 的结构化 CSV writer 写入，禁止把中文经过 ANSI 控制台、管道或默认编码写入 CSV。
- CSV 必须严格为固定 15 列，顺序由 file-format-spec.md 定义；verification_date 永远是最后一列，日期不能写进三个 evidence 列。
- method_evidence、compute_evidence、experiment_evidence 禁止出现 ?? 占位符或 U+FFFD 替换字符。标题中的正常问号允许保留。
- 每次结构化写入后必须执行 CSV 完整性检查；列数、列位、UTF-8 解码、证据占位符和日期错位任一失败，都必须阻止审计和 Markdown 生成。
- 两份 Markdown 的标题、说明、表头、分析正文和结论必须用中文；论文原题、venue、算法名、硬件名、URL、DOI 和必要技术术语可以保持原文。
- 生成器禁止输出 Strict search cycle log、This-cycle evidence table、Scheme A top-direction snapshot、Scheme A preference gates、Isaac Lab minimum viable route 等英文模板标题；必须输出对应中文标题。
- 每轮结束前运行完整测试、严格审计和核心文件白名单清理；没有新鲜输出不得声称完成。

## 插件、研究状态与宿主边界

- **插件本体**包括 manifest、六个领域 Skill、scripts、references、tests、README 和示例配置；迁移时只复制一个 `SKILL.md` 不能称为完整插件
- **研究事实源**与插件分离：`论文库统一.csv` 是论文事实源，`论文总结.md` 和 `研究方向分析.md` 是派生视图；想延续当前研究状态时必须另外迁移这些数据
- **宿主状态**不属于插件：自动化任务、浏览器登录态、应用授权、凭据和会话进度必须在目标宿主重新配置
- 需要迁移本插件或任一 skill 到其他模型、Codex、Claude Code、Kimi Code 或普通 Agent 时，必须调用 `global.migration-skill`，通过能力矩阵和三层验收处理平台差异
- 插件核心规则只有一个事实源；不同宿主的 manifest、工具映射和调度外壳只能作为适配层，禁止复制多套核心规则后分别漂移
## canonical 与聚合说明

本文件及其强制 reference 是本 Skill 的唯一权威来源。规则或 reference 变化后，只刷新 `Skill完整指南/research/drone-literature-scout-完整指南.md`；用途、输入输出、协作或边界变化时，再更新《Skill 与 Plugin 的总体系说明》对应段与自动关系区。两类派生说明只用于阅读和导航，不得反向覆盖本文件。
