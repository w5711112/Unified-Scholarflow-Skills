---
name: read-paper-analysis-highlight
description: Use after a verified Zotero paper import to read every PDF page and visual object, build evidence-grounded Obsidian notes and knowledge links, research designated authors, and create precise, editable Zotero-native highlights and comments.
---

# 论文全文精读、证据原子分析与 Zotero 原生批注

## 插件级轻量故障协作

> [!important]- **快路径与慢路径**
> - 正常成功路径不写故障库，也不包装每次工具调用
> - 组件已知脆弱、准备复用历史方案或路线刚失败时，才运行 `incident_registry.py preflight`：先查项目守卫指定的本地事故库，再查公共事故库只读
> - 任意异常、非零退出、权限拒绝、结果缺失或验证失败立即 `capture-event`；记录后才换路，同签名/参数/路线重试前通过 retry guard
> - 最终回答前扫描真实工具结果；预期 TDD RED、受控探针和用户取消不算产品事故
> - 只有本轮事件发生变化、复用结果新增或回归状态变化才查候选；候选非空才加载 `promotion_audit.py`
> - 图/表/公式读取的 verified 方案必须带 `quality_guard`：视觉模型直接读取渲染图像；`ocr-downgrade`、`text-ocr-then-read`、`paddleocr-fallback`、`tesseract-fallback` 均为禁止降档路线
> - 插件任务开始或 Skill 清单变化时读取插件根目录的 `references/skill-collaboration-contract.md`；同一任务内拓扑和来源哈希未变时不重复枚举
> - 本 Skill 的效果验证只由下文证据对象与最终门承担，不在故障协作层重复运行

## 触发、职责与权威读取

本 Skill 在 `zotero-obsidian-paper-import` 核验正式 `application/pdf` 后执行。完整流程用 `workflow_scope: full`；`obsidian-only` 只作阶段交付并保持 `待精读`。复用现有 PDF 不能跳过 Zotero 批注、回链、附件身份或元数据同步。

中文笔记固定走 `专业语义草稿 → global.renhua → obsidian-note-style`，由 `scripts/validate_language_gate.py` 核验 `language-gate.json`；自报“已润色”无效。全文证据、作者、PDF 定位、原生批注和完成门仍由本 Skill 独占。

`read-paper-analysis-highlight` 唯一负责批注选择、评论、颜色、坐标转换；`zotero-local-bridge` 只负责机械写入与原生读回；`global.collect-bug-update-accelerate` 只记录并路由真实故障。

用户要求自己的 Obsidian 风格时调用 `obsidian-note-style`，且不改变先 `global.renhua`、后样式定稿的顺序。

按当前任务分支完整读取一次下列直接参考；不预载无关分支，**直接参考不得继续路由第二层参考**：

| 分支 | 唯一直接参考 |
| --- | --- |
| 身份、版本、状态、固定总流程、职责边界 | `references/identity-state-and-capability-contract.md` |
| 全文遍次、逐页台账、研究问题、公式、图表、实验和知识归属 | `references/full-reading-protocol.md` |
| 证据原子、评论、关系组、双坐标、Zotero 原生批注 schema | `references/pdf-annotation-contract.md` |
| 一作/共同一作/通讯作者外部证据 | `references/author-research-contract.md` |
| 唯一论文 Callout、强调语义、个人理解与 Sheets Extended | `references/obsidian-callout-template.md` |
| 原生 bridge、首页记忆句、回链、插件安装与一次 UI 门 | `references/zotero-memory-link-and-ui-contract.md` |
| Windows 路线、依赖、增量/最终验证、清理与交付 | `references/runtime-validation-and-cleanup.md` |

本文件与上述参考是权威合同；清单、计划、测试和报告只作记录。

## 单一证据主链

每个对象在同一证据边界只验证一次；输入实质变化时，仅刷新受影响对象及下游。

| 对象 | 唯一内容 | 消费门 |
| --- | --- | --- |
| `PAPER_BASELINE` | 身份、版本、PDF/backup 哈希、状态、block、个人内容、能力预检 | 是否允许全文处理 |
| `READING_LEDGER` | schema v4 每页正文/公式/图/表/图注与 unresolved | 全文完成 |
| `CLAIM_EVIDENCE_MAP` | 研究问题、公式、实验五槽、证据原子、知识缺口 | 笔记与批注选择 |
| `AUTHOR_EVIDENCE` | 指定角色、身份消歧、字段、URL、日期、不确定性 | 三处作者交付 |
| `VERSION_RECONCILIATION` | 无冲突的正式身份核验，或旧附件到正式附件的接管、元数据读回、backup 与证据重建 | 是否允许继续定位与完成 |
| `LANGUAGE_GATE` | 语义草稿、renhua 输出、最终 block 哈希、术语取舍、个人内容哈希和通读验收 | 中文笔记可读性与真实性 |
| `NOTE_PACKAGE` | 唯一 Callout、记忆句、精确链接、个人内容、视觉交接 | Obsidian 验收 |
| `ANNOTATION_PLAN` | 稳定 ID、quote/quads、area 双坐标、颜色、评论、允许 keys | bridge preflight/apply |
| `NATIVE_READBACK` | digests、回执、native keys、逐字评论、可编辑/删除/无锁、回链行为 | 原生效果门 |
| `PAPER_ACCEPTANCE` | 新鲜最终全检、架构、清理和状态结论 | 最终交付 |

## 不可妥协的内容与质量硬门

### 身份、全文与状态

- 摘要、网页、旧笔记和二手综述只定位，不能替代 PDF；优先从 Zotero PDF 跳转取得本地 PDF，本地 PDF 可用时，不先抓取网页，工具失败不等于论文不存在
- DOI、标题、作者、版本冲突，非 `application/pdf`，页数/哈希不符，无可信 annotation-free backup，Snapshot/残缺 OCR 冒充全文，任一立即停止并保持 `待精读`；冲突进入 `VERSION_CONFLICT`，按身份参考交回导入 Skill 完成正式版接管与读回后才能继续
- 正式全文能力以可逐页读取的 `full-text` PDF 为准；身份、附件类型、协议能力预检与权限预检只在 `PAPER_BASELINE` 建立时验证一次，后续复用其哈希和状态
- 读取真实 ProductVersion；本合同在 **Zotero 9.0.6** 验证，其他 Zotero 9 小版本重新做一次原生批注读回测试
- overwrite 前必须有 SHA-256 可核验的 annotation-free、干净 backup；任何定义、公式、符号、下标、数量、几何形状、更新顺序、条件和边界都回到原 PDF，不能确认就写“未从原文确认”，不能改写成更强的绝对结论，**do not invent**
- 从第 1 页到最后一页完成三遍全文阅读；视觉直读公式、图表、图注、坐标轴、图例和排版关系，不得用文本模型 OCR 冒充完成；补证和验证不增加新的全文阅读轮次
- 未完成时至少每隔 **20 分钟**汇报遍次、页码、已查公式/图/表、当前环节和剩余门；汇报不能替代验证或催生粗读
- 只有所有证据、笔记、知识/视觉、原生批注、回链、清理和最终门通过后，才从 `待精读` 改为 `已AI全文读`

### 阅读、公式、图表与实验

- `READING_LEDGER` **每页恰好一条**；新建根对象必须声明 `schema_version: 4`，v3 仅兼容读取
- 每页的 `equations_checked`、`figures_checked`、`tables_checked`、`captions_checked` 必须为 `checked|not_present`；`unresolved` 为空。图存在时 `figure_audits` 非空，不存在才允许 `not_present`
- 每幅 `Fig.` 和每个 panel 实际视觉检查：标题/图注、正文引用、轴/单位/范围/刻度、图例、颜色/线型/形状、模块/箭头/数据流、趋势/数值/异常/失败及正文—公式—表一致性；不能以 OCR、空列表或 `not_present` 掩盖未读
- 研究问题审计前先回答“作者声称解决了什么当下的问题”，按“当下压力 → 现有失败 → 声称目标 → 证据边界”建立上下文，不写术语清单、不复制 What/Why/How；随后审计 Interesting、Solvable、Current level、Impactful 与新旧问题/方法分类，并完成 What/Why/How、Pros/Cons 和拓展
- 控制、感知和机器人论文的每个主链模块必须按八项合同解释：**模块任务、输入来源、输入内容、实际处理顺序、输出的物理意义、下游接口、训练阶段与部署阶段的差异、条件与失效边界**。不能用术语替代解释，不能把“射线距离”“速度目标”“PPO 选速度”“几何投影”等词组当成已经说明；原文未给出的单位、维度、坐标系、频率或实现细节写“论文未报告”
- 问题评估的稳定字段为 `Interesting（问题值得研究吗）`、`Solvable（问题可解吗）`、`Current level（当前研究水平）`、`Impactful（问题影响大吗）` 和 `新旧问题/方法分类`；字段名不得被摘要性改写替代
- 其余研究审计槽位继续用 `What / Why / How`、`Pros / Cons` 与 `如何拓展与利用` 作为兼容检查名；实际笔记可在不改变含义的前提下展开为完整中文问句
- 每个主张先确定**唯一语义归属**：在最合适的栏目完整陈述一次，其他栏目只新增事实、机制、条件、证据或边界；不得用同义改写再次陈述，也不得以“去重”为由删除数字、假设、局限或复现缺口
- **可读性不是压缩率**：方案、模块或条件多时自然扩写为单一任务短段，禁止把知识点挤成长句或名词串。算法、模型、软件/硬件、数据集、API、缩写、符号及生硬/失真的中文译名保留英文；首次仍解释本文职责，并记录 `TERM_DECISION_LEDGER`
- 每个公式解释整体作用、逐符号、从左到右计算与方向/正负、系统位置、设计原因、成立条件/失效方式。内部证据记录保留 `（PDF第 N 页）（公式 X）`；完成态 `已AI全文读` Callout 不显示 PDF 页码，只保留准确的公式、图、表和算法编号。三个以上待解释符号或解释超过两条列表时用嵌套折叠，不能只标编号或写“鼓励安全”
- **知识点递进解释合同**：必须先写`第一层：直觉理解`，再写`第二层：公式与原理`，坚持“先直觉、后数学”；不得只用图代替公式。第二层给公式原文、逐符号解释、最小推导，以及数值代入或极端情形，再回扣直觉；够用即止，同一结论只说一次。组织顺序固定为“正文说明 → 现有图 → 读图与图例 → 公式与原理”，论文 Callout 只保留本文用途
- 每个主张记录 Claim、Evidence、Condition、Status、Boundary；严格区分 `supported | partially_supported | not_established`、论文报告、可以推断、尚不能证明、论文明确承认的局限、未报告与疑点
- 每项实验分开保存方法名、baseline、结果、条件、边界、复现缺口、作者局限和参考文献角色，写入前复述“对象—条件—样本—结果—边界”；N/N 成功先忠实写结果，缺失项不能抹掉正面证据
- 高亮和批注**不设置每页、每篇、每类型数量上下限**，评论**不设置字符上限**；数量不是目标，证据原子必须脱离上下文仍能说明问题、机制、证据、条件和边界

### 证据原子、评论与作者

- selection mode 保留 `semantic-span`、`key-term`、`key-metric`、`key-link`、`author-name`、`area`；关系组默认 `connector_mode: shared-id`，至少一个 predicate 和一个 entity/effect/condition。只有 Zotero 原生 Ink 的可编辑、可删除、坐标、刷新和不遮字全部实证后才用 `connector_mode: native-ink`
- 关系型证据原子必须形成“技术实体 → 谓词/动作 → 作用对象/效果 → 条件/边界”；连接词只用于定位候选，保留否定、范围、模态、数值限定。`we propose` 只作话语脚手架，`success rate remains` 必须连同数值、条件和边界；测试锚点 `incurs cumulative latency`、`lack theoretical safety guarantees`、`out-of-distribution generalization failures`、`tightly couples reinforcement learning with model-based safety mechanisms`、`alleviates local minima in Euclidean distance objectives` 均须按完整关系抽取，不能截成孤立短语
- 普通评论第一行必须先给结论并使用 `结论：`，作者评论第一行必须 `外部信息：`；至少再有一行说明通过什么原理、构建什么结构、实现什么效果，或给出意义/复现/边界/疑点/定位/来源。评论不设置字符上限，与 annotation manifest 的 `annotation_comment` 逐字相等，自动翻译后缀为 0；原批注、翻译后缀与新批注分别计数
- 只调查论文明确的一作、共同一作和通讯作者，多人全部调查；先消歧，再核验教育、在读阶段/年级、机构、实验室、职称、导师、研究、项目、成果、荣誉、会籍、动态计量、QS 版本和谨慎影响力判断
- 一作/共同一作必须明确核验硕士生还是博士生、具体年级，或标为已毕业/当前非在读；无法核验写“未公开核验”，不得根据入学年份自行推算
- 每个外部事实记录 URL 与 `as_of`；Google Scholar、机构页与其他来源属于“外部核验，不是论文正文事实”，QS 必须注明版本。403、429、CAPTCHA、Access Denied、登录墙不能作唯一入口。未知写 `not_publicly_verified`，不能写 0、空串或按入学年推算；替代平台指标写真实平台，不能冒充 Google Scholar
- 作者信息只交付到当前论文折叠“作者与团队背景”、PDF 作者姓名批注、内部作者调研 JSON；**不得创建独立作者/团队笔记**、人物库或作者知识枢纽

### Obsidian Callout、知识与视觉交接

- 每篇标题下只保留一个 `> [!note]-`。来源第一行的下载链接、DOI、Zotero key、等级与标点原样保留；唯一 `^block-id` 必须单独放在论文标题下方、主 Callout 之前
- 来源下一行写与 PDF 首页逐字相同的“**一眼记住这篇论文**”；允许使用 **1–3 个完整句子**，先让初学者知道谁接收什么、做什么、输出给谁，再收束原理—结构—效果。它不是术语口号，不能为了短而省略主语、对象归属或关键数据来源
- **论文 Callout 强调语义合同**：粗体只作短扫描锚点，`==...==` 必须可独立复述；绿色只标有全文证据支撑的正面结果，红色标未提供链接、参数、硬件或解释等明确缺口/冲突/不成立。颜色与 `==...==` 不叠加，同一语义一个主强调，不得为了凑齐颜色而使用
- 必须有明确 `**作者贡献**`；只有字段名加粗，逐项给贡献核心短语、新增内容、相对改变、正文/公式/图/实验定位和不能推出什么；分开写作者声称的贡献与全文证据支持的真实增量
- “**作者声称解决了什么当下的问题？**”固定在论文类型/相关工作之后、研究问题审计之前；先交代作者当时面对的压力与目标，再由审计判断价值、可解性和证据
- `知识索引` 仅链接既有或经 `obsidian-note-style` 验收的正式知识点，使用 `[[笔记#标题|别名]]` 或 `[[笔记#^block-id|别名]]` 精确定位；支撑链接（supporting links）必须能回到论文页码、公式、图表或可信外部来源。证据选择不设死板名单，以独立信息价值决定是否保留
- **用户个人理解区强制合同**：每次生成完成态 AI Callout 时，必须在同一次写入中同步生成或核验紧随其后的 `> [!personal]+ 个人理解`，不得出现只有 AI Callout、没有个人理解 Callout。两者之间源码必须恰好保留一个真实空行；新建时内部必须为空，已有个人内容逐字保留。它在阅读模式默认展开，AI 不得生成、润色、移动或覆盖，不得拆分到单独笔记。个人 Callout 末行到下一篇 `###` 标题前的源码空行必须为 0，即下一篇 `###` 标题前不保留空行，可见间距必须为 0
- 若 Sheets Extended 已启用且目标含普通 Markdown 表格，局部合并 `disable-sheet: true`；不得全局禁用/卸载，不机械加到无表笔记
- 基础概念、扩展概念与论文特定用法形成的概念前置缺口、公式解释闭环和示意图需求交给 `obsidian-note-style`，附 PDF 页码、公式号、图号或原文定义；本 Skill 不得自行创建零散知识文件
- 笔记正文和知识链接全部写入完成后，**每篇论文只触发一次** `obsidian-note-style`；处理中不触发，逐段写入和单图完成时不重复。它审计 Vault 全部正式知识点，不限于当前论文，每点独立 `0` 或 `1` 张，已有合格图快速跳过；缺图调用 `draw-style` 的**八项硬质量门槛**，媒体引用审计与孤儿图片清理由 `obsidian-note-style` 独占负责
- 视觉审计和必要配图完成前，不得把本次论文处理标记为完成；唯一归属和全部链接也必须通过

### 定位、Zotero 原生化与 PDF 回链

- 文本严格 `quote → quads → actual_text`：零匹配、多匹配未用 context/occurrence 消歧、读回不等即停止；普通文本禁止手填矩形
- area 只用于公式布局、算法框、图、表和视觉关系；同时保存 `pymupdf-page-top-left` 的 `rect`、`page_box`、`page_rotation` 和 `pdf-page-bottom-left` 的 `zotero_rect`
- 外部暂存审计必须识别 PDF /Square 与 PDF /Ink，但二者不得当作 Zotero 原生路线：文本 quads 最终映射为 `highlight`，area 映射为 `image`。area 的两矩形均在 page box 内、面积一致，坐标往返的正反变换最大误差 **≤ 0.01 pt**；旋转页单独验证；每个 area 渲染并人工核对
- 先由 `build_zotero_native_annotation_plan.py` 构造计划，再由 `zotero_local_bridge_client.py` 调用 `zotero-local-bridge`；固定 `health → preflight → apply → readback`，完成原生读回。同一计划/digests/回执原子执行。`409` 安全停止重建计划，`503` fresh health 恢复后最多重试一次；禁止前台脚本和鼠标，禁止直接写 SQLite，禁止重复 apply
- 完整流程中，“未单独点名导入 Skill / PDF 已在本机 / 不重新下载”均不能把原生写回、版本接管或回链变成 `not_applicable`；只有明确 `obsidian-only` 才停在 `待精读`
- 最终 `storage_mode: zotero-native`、可编辑、可删除、无锁、位置准确，未知用户批注变化为 0；只按 native key、完整指纹和 allow-key 精确删除
- PDF 本体最终 embedded/external markup 为 0；首页记忆句和回链从干净 backup 单次生成，至少 **150–200 dpi** 渲染，并固定在 PDF 首页左上角；在 Zotero 内置阅读器点击后返回 Obsidian的对应精读位置
- 回链固定 `https://obsidian-link.invalid/open?uri=<percent-encoded obsidian://open?...>`，`bridge_url_count = 1`、`direct_obsidian_uri_count = 0`；真实点击到当前论文 block，无外部协议确认框且 Edge 未调用
- 禁止把直接 Obsidian URI 写入 PDF；`plugin_installation_normalized` 与 `bridge_click_verified` 是两个独立门。回链行为门槛只允许协议 handler 的 `launchWithURI(...)`，明确禁止 `Zotero.launchURL(obsidianURI)`；不能用安装缓存、不可见会话或“窗口打开”冒充真实行为，离线原位升级后仍须验证，失败状态记 `ui_gate_pending`

### Windows、删除、增量验证与最终门

- Python 先锁解释器与 import；低风险 allow-list 至少 `yaml → PyYAML`、`fitz → PyMuPDF`。缺依赖才用同一解释器 `python -m pip install` 一次，安装后重新 import，不静默切环境
- 中文统一 UTF-8；优先 `Python -X utf8`，`PYTHONPYCACHEPREFIX` 长路径用 `python -B`、内存 compile 或已验证短路径，不留 `__pycache__`
- split writable roots、PowerShell 乱码、临时目录、Poppler、GUI 权限和同卷替换按运行参考的固定路线；同签名禁止循环
- 对 `0x80070005`、PowerShell/GUI 权限与不可见会话采用固定故障路由；Computer Use 仅承担一次逐图结构化审计或必要 UI 门，默认无界面且不得抢占鼠标。原生 Ink、回链或 UI 失败必须失败闭合，交给 `global.collect-bug-update-accelerate` 记录与路由，不能降级成非原生结果
- 只删除本轮/明确旧批次 AI 批注和目标运行目录内可再生产物、中间文件；旧批注、未知用户批注、个人理解、原件、backup、其他论文运行数据和代码依赖均保护。知识副本先合并独有内容、验证链接，再按绝对路径白名单删除并重建索引
- `scripts/validation_gate_cache.py` 仅用于中途增量验证：缓存输入指纹“已通过且输入未变”的成功门；失败门槛、输入变化和受影响的下游门槛必须重跑，不重复运行无影响门
- 默认不限制完成时间。最终交付前忽略中途成功缓存，从新鲜输入完整运行一次最终全量验证：Python 编译/`python -B`、Skill 本地测试、插件全测、manifest/坐标/原生效果、行为点击、聚合说明来源标记与清理

## 执行与交付

按 `PAPER_BASELINE → VERSION_RECONCILIATION → READING_LEDGER → CLAIM_EVIDENCE_MAP → AUTHOR_EVIDENCE → LANGUAGE_GATE → NOTE_PACKAGE → ANNOTATION_PLAN → NATIVE_READBACK → PAPER_ACCEPTANCE` 执行。语言门通读完整 AI block，定稿后重验哈希；本 Skill 负责事实与批注语义，bridge 只机械写入，故障 Skill 只记录路由。

本文件及其强制 reference 是唯一 canonical。规则或直接参考集合变化后，只刷新 `Skill完整指南/research/read-paper-analysis-highlight-完整指南.md`；用途、输入输出、协作或边界变化时，再更新《Skill 与 Plugin 的总体系说明》对应段与自动关系区。派生说明不得替代或反向覆盖 canonical。架构层级或直接参考集合只有在用户明确批准、架构版本提升并通过迁移测试后才可改变；普通内容增删不得顺带改变架构。
