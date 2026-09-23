# Zotero 写入、去重与回滚安全合同

本文件由 `SKILL.md` 直接在 Zotero 读取、创建、附件上传、去重、合并或回滚任务中加载。

## 全库唯一性快照

初始分页盘点供查重和 dry-run 共用；每次 `saveItems` 紧前由统一写入函数在跨进程锁内重新分页读取全库，形成 `PREWRITE_LIBRARY_SNAPSHOT`。写入函数生成一次写后回执，上层直接消费，不紧接着再次读取。附件上传造成新变化后，再取一次最终快照核验真实文件、唯一父条目及回链。搜索或来源抓取本身不触发重复全库读取。旧 manifest、搜索框、collection 或标签过滤均不能代替写入边界的全库事实；只审计未删除且无 `parentItem` 的论文父条目。

该锁只协调使用同一导入函数的本机进程，不能控制手工操作或其他客户端。写后发现竞争写入、网络结果不明或元数据改变时停止后续上传与回链，保存回执，不自动重发创建请求。无变化部分不重新查来源、不重新哈希；实际待上传字节变化时必须重新验证。

对每篇论文同时建立三组：

- **规范化 DOI 组**：去 DOI URL 前缀，忽略大小写、首尾空格与句末标点
- **题名身份组**：HTML 解码、大小写归一，移除末尾 venue/年份括号、标点和空白；第一作者、venue、年份用于交叉核验，不用不明相似度自动合并
- **Obsidian 编号组**：检查 `obsidian-paper-N` 标签是否对应多个父条目

零父条目命中才可创建，唯一命中才可复用。任一组命中两个或更多父条目时，记录全部 `duplicate_parent_keys`、匹配依据及附件来源，状态设为 `duplicate_merge_required`，并禁止新建父条目、上传/改挂附件、把任一项当作 `duplicate_existing` 或回填 `zotero://open-pdf`。

精确 DOI、题名、作者、venue、年份一致的组才可合并。版本冲突、会议版/期刊扩展版、预印本/正式版、勘误或不同 DOI 的题名命中，标记 `metadata_conflict` 或 `manual_review`，不得按题名自动删除。合并时优先保留期刊或正式会议 PDF；仅无正式版时保留 arXiv/作者副本。元数据以 DOI 落地页、出版社页或正式 proceedings 为准；合并后刷新全库与 children，确认只剩一个父条目、附件为其真实 `application/pdf`，再以反查后的附件 key 回链。

用户已授权版本冲突处理时，冲突状态触发正式来源核实，不止于记录待办。按 DOI 落地页、出版社或会议 proceedings 确定正确身份，由正确父条目接管可确认属于同一文献的错误/重复条目。缺失字段可用正式来源与文件证据补证；不得把缺失值当成已核实的一致值。独立的会议论文和期刊扩展论文不因题名相近而合并。没有正式出版证据时保持不确定状态，不能根据 `journalArticle` 类型推定已发表。

接管前保存父 key、附件 key、原字段、附件 SHA-256、批注和关联的可恢复映射。重复父条目通过受支持原生操作合并并移入回收站，不直接改数据库。历史旧版附件和批注先保护，再按明确映射处理；默认不永久删除。旧版不得继续作为当前正式阅读入口，旧批注坐标不能直接移植到新版本。当前桥接不支持某项元数据修正或附件退役时，保留该项未完成状态，不能降低身份检查强行合并。

### 正式版本接管

当完整论文精读中已经确认正式版本而 Zotero 仍是旧版/错误版时，不等待用户再次点名本 Skill。先冻结写前快照，再按下列顺序执行：

1. 记录旧父 key、旧附件 key、旧 PDF 哈希；旧附件或其身份记录保持可恢复，禁止静默删除
2. 通过经过验证的 Zotero UI/bridge 更新保留父条目的题名、全部作者、venue、年份、DOI/无 DOI 状态和 URL；接口能力不足时暂停该项，不以新建第二父条目绕过。既有条目误标为期刊、但只核实到预印本时，使用明确的既有预印本纠错分支，保留真实出版状态；该分支不授权新增预印本
3. 正式 PDF 作为不同于旧附件的 stored attachment 写入；`saveAttachment.parentItemID` 必须是同一 `saveItems` session 返回的 connector item id，不能使用 Zotero 父条目 key。没有新附件 key 不得声称已替换
4. 复用操作后的全库快照与 children，核验正式父条目元数据逐字段一致、正式附件 `application/pdf`、页数和 SHA-256；重复父条目经受支持原生合并进入回收站并读回后，才能声明父条目唯一
5. 创建并实读 annotation-free backup；backup 路径存在、哈希与正式 PDF 相同
6. 生成 `version-reconciliation.json` 并通过 `scripts/validate_version_reconciliation.py`；旧附件上的页码、坐标、批注计划和回链全部作废，由下游在正式附件上重建

若当前写入接口不能安全更新保留父条目、挂载正式附件或退役重复父条目，状态保持 `metadata_conflict`/`manual_review`，报告具体缺口。不得创建第二父条目、覆盖旧文件或只改 Obsidian 文本绕过。

## 读取与创建

- Zotero 必须开启“允许本机其他应用程序通信”；用 `curl.exe` 读取 `http://localhost:23119/api/users/0/items`，本机 API 是只读事实源
- 查重先比较规范化 DOI，再核对题名、第一作者和年份；标题相同不能单独证明同一记录
- 始终分开读取父条目 key 与 PDF 附件 key
- 写入前生成 dry-run manifest，列出字段、来源证据和父 key 写前快照
- 用 Zotero Connector `POST /connector/saveItems` 创建父条目；每条使用唯一 sessionID 和 connector item id，每批最多 10 条，每条写后立即反查
- Connector 写入当前选中的 Collection；写前确认目标 Collection，且不得把 payload 的 `collections` 字段当作移动成功证据

## Stored PDF

- 有真实 PDF 时，对同一 session 调用 `POST /connector/saveAttachment`，提供 `Content-Type: application/pdf`、文件长度和 `X-Metadata`
- `X-Metadata.parentItemID` 只能使用同一 session 中 `saveItems` payload 的 connector item id；Zotero 本机父条目 key 不是 connector item id。禁止用“空 `saveItems` session + 旧父 key”伪造已有条目附件上传
- 只有 Connector 返回且经本机 API 反查的附件才是 Zotero stored attachment；不得默认创建 linked file，也不得把工作区 PDF 路径当成最终附件
- 本机 API 是只读事实源，不能更新旧父条目、不能删除条目，也不能把附件挂到已有父条目；已有父条目缺 PDF 时进入 `existing_parent_attachment_requires_supported_ui_or_bridge`，不得假装自动上传成功

## 写后对账与唯一可证回滚

`saveItems` 不是不重复的证明。每条写入后必须再次分页读取全库，以规范化 DOI、题名变体和 Obsidian 编号重算命中集合并生成 `POSTWRITE_RECONCILIATION`：

- 命中数为 1：父 key 必须取自写后反查，才可继续上传 PDF
- 命中数大于 1：立即停止附件与回链。即使写前快照和写后集合能证明恰有一个本次新增父 key，本机 API 也不支持 `DELETE`；只能把该 key 写入人工复核单，由 Zotero UI 或经验证支持删除的 bridge 退役，随后再次分页确认唯一
- 无法唯一确定新增 key、界面退役未执行或退役后仍不唯一：不得猜测或直接改 SQLite；保持 `duplicate_merge_required` 或 `manual_review`，保存全部 key、写前后快照与响应
- 只有二次审计完成且正式 PDF 已反查为该父条目的真实 `application/pdf` 附件，才可写入或更新 `zotero://open-pdf`
- `write_rolled_back_duplicate` 仅能在受支持 UI/bridge 已实际退役本次误建项并完成读回时使用；本机 API 返回 501 或仅生成待办不得使用该状态。它也不表示历史重复已合并；续跑、重跑和并发写入仍须重新执行写前快照与写后反查

本合同对应 `scripts/paper_import.py` 的 `classify_post_write_matches`、`zotero_delete_item` 和两个导入入口。修改规则或实现时，须先更新 canonical，再由治理工具按来源哈希更新聚合说明中受影响的职责段。
