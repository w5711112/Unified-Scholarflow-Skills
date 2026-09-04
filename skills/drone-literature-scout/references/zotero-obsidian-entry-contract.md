# Zotero 与 Obsidian 论文入口合同

## 论文入口

- `01-核心论文精读.md` 中论文来源行只保留正式期刊/会议下载主页，统一使用 `[下载网页链接]`；优先指向出版社、会议 proceedings 或正式 PDF 页面，DOI 仅在没有更直接的正式入口时使用；禁止继续使用 `[DOI]` 作为固定显示标签。
- 已在 Zotero 中核验过的 PDF 附件统一使用 `[Zotero的PDF]`，链接格式为 `zotero://open-pdf/library/items/<attachment-key>`；只写真实存在的附件 key，禁止猜测或写占位 key。
- 索引只展示一个 Zotero PDF 入口，不重复展示 Zotero 父条目链接；父条目和 citation key 在 Zotero 内部核验。
- 每篇论文必须保留稳定块 ID，建议格式为 `^paper-<slug>`，并放在来源行末尾；论文标题、段落移动时不得改动该 ID。
- 来源行不再单独展示 `[作者全文]`、`[arXiv]` 或其他重复的全文入口；这些证据如有必要写入论文分析正文，而不是占用索引入口。
- 尚未进入 Zotero 的论文不得伪造 `zotero://` 链接，应只保留 `[下载网页链接]` 并注明 `Zotero PDF：待导入`。
- Zotero 的 Web Page/Snapshot 不等于论文条目或 PDF；只有确认父条目、PDF 子附件和附件 key 后，才可升级为 `[Zotero的PDF]`。
- 如果会议官方页面暂时只有 program page、没有可导入的 BibTeX/DOI，条目标记为“会议元数据待补全”；不得根据 paper ID、年份或 URL 猜 DOI。先保留官方 program page 和 PDF，后续正式 proceedings/BibTeX 发布后再更新或合并。
- Obsidian Zotero Integration 是 Zotero → 当前 Obsidian 光标位置的模板导入，不负责自动定位 `01-核心论文精读.md`，也不保证默认模板生成 Zotero PDF URI；模板必须显式输出 PDF 打开链接。
- 论文事实、venue、版本和安全证据等级仍以官方来源与论文原文为准，Zotero 链接只承担可追溯阅读入口。

## DOI 核验与显示规则

- 论文来源行固定按 `[下载网页链接]` ==`-->`== `[DOI]`（已核验时） ==`-->`== `[Zotero的PDF]`（已核验时）排列；没有真实 DOI 时不留空占位，不得从标题、年份、Paper ID 或 URL 片段推测。
- DOI 只有在出版社/会议 proceedings 的 BibTeX、正式元数据页、Crossref 或 Zotero 父条目的 DOI 字段相互吻合时才能写入；应核对标题、作者、venue 和年份至少两项。
- DOI 链接统一写成 `https://doi.org/<真实 DOI>`；若下载页面本身就是 DOI，优先替换为正式出版社/会议页面，避免把同一个 DOI 当作两个不同来源。
- 对没有找到 DOI 的论文，在论文记录中写 `DOI：未找到` 或保留待核验状态；不得用“看起来像 DOI”的字符串填充。
- 每次续写或更新前复核已有 DOI 链接；解析失败、跳转到不同论文或元数据不一致时，移除 `[DOI]` 并列入待核验清单。

## Zotero—Obsidian 入口对账与双向回链

- 每次生成或更新 `01-核心论文精读.md` 前，先读取 Zotero 本地条目与附件清单，按 DOI、citation key、规范化标题三层匹配；只有确认父条目存在且存在 `contentType=application/pdf` 的子附件时，才补写 `[Zotero的PDF](zotero://open-pdf/library/items/<attachment-key>)`。
- `Snapshot`、Web Page、独立网页条目、只有父条目没有 PDF 子附件的记录，都不得升级为 `[Zotero的PDF]`；必须进入“待导入/待核验”清单。
- 对账是幂等的：已有正确链接不重复添加，附件 key 发生变化时替换旧链接，论文来源、分析正文、评分和 `^paper-<slug>` 块 ID 不被覆盖。
- Obsidian 侧以稳定块 ID 作为回链目标，Zotero 笔记或 `extra` 字段如需回链，使用 `[[01-核心论文精读#^paper-<slug>|核心论文精读]]`；论文段落移动时不改块 ID，因此回链不依赖行号。
- Codex 默认只读 Zotero 本地 API；不得把“读取成功”描述成“已经写入 Zotero”。任何 Zotero 元数据修改都必须先输出 dry-run 差异，再由用户在 Zotero【工具】==`-->`==【开发者】==`-->`==【运行 JavaScript】中执行经确认的脚本，完成后重新读取 API 验证。
- 批量对账顺序固定为：读取与备份状态 ==`-->`== 生成匹配报告 ==`-->`== 用户确认写入 Zotero（如有） ==`-->`== 重读 Zotero ==`-->`== 更新 Obsidian 链接 ==`-->`== 报告已匹配、歧义和未匹配项；不得静默猜测会议 DOI、作者或 PDF key。
