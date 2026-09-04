# Zotero 写入、去重与回滚安全合同

本文件由 `SKILL.md` 直接在 Zotero 读取、创建、附件上传、去重、合并或回滚任务中加载。

## 全库唯一性快照

在批处理开始、每次新论文搜索或重跑、正式来源抓取完成，以及每次 `saveItems` 紧前，必须重新分页读取 Zotero 全部条目，形成 `PREWRITE_LIBRARY_SNAPSHOT`；旧 manifest、缓存、搜索框、collection、标签过滤或“本批只有一条”均不能替代。只审计无 `parentItem` 的论文父条目，附件和笔记不得充当父条目。

对每篇论文同时建立三组：

- **规范化 DOI 组**：去 DOI URL 前缀，忽略大小写、首尾空格与句末标点
- **题名身份组**：HTML 解码、大小写归一，移除末尾 venue/年份括号、标点和空白；第一作者、venue、年份用于交叉核验，不用不明相似度自动合并
- **Obsidian 编号组**：检查 `obsidian-paper-N` 标签是否对应多个父条目

零父条目命中才可创建，唯一命中才可复用。任一组命中两个或更多父条目时，记录全部 `duplicate_parent_keys`、匹配依据及附件来源，状态设为 `duplicate_merge_required`，并禁止新建父条目、上传/改挂附件、把任一项当作 `duplicate_existing` 或回填 `zotero://open-pdf`。

精确 DOI、题名、作者、venue、年份一致的组才可合并。版本冲突、会议版/期刊扩展版、预印本/正式版、勘误或不同 DOI 的题名命中，标记 `metadata_conflict` 或 `manual_review`，不得按题名自动删除。合并时优先保留期刊或正式会议 PDF；仅无正式版时保留 arXiv/作者副本。元数据以 DOI 落地页、出版社页或正式 proceedings 为准；合并后刷新全库与 children，确认只剩一个父条目、附件为其真实 `application/pdf`，再以反查后的附件 key 回链。

## 读取与创建

- Zotero 必须开启“允许本机其他应用程序通信”；用 `curl.exe` 读取 `http://localhost:23119/api/users/0/items`，本机 API 是只读事实源
- 查重先比较规范化 DOI，再核对题名、第一作者和年份；标题相同不能单独证明同一记录
- 始终分开读取父条目 key 与 PDF 附件 key
- 写入前生成 dry-run manifest，列出字段、来源证据和父 key 写前快照
- 用 Zotero Connector `POST /connector/saveItems` 创建父条目；每条使用唯一 sessionID 和 connector item id，每批最多 10 条，每条写后立即反查
- Connector 写入当前选中的 Collection；写前确认目标 Collection，且不得把 payload 的 `collections` 字段当作移动成功证据

## Stored PDF

- 有真实 PDF 时，对同一 session 调用 `POST /connector/saveAttachment`，提供 `Content-Type: application/pdf`、文件长度和 `X-Metadata`
- 只有 Connector 返回且经本机 API 反查的附件才是 Zotero stored attachment；不得默认创建 linked file，也不得把工作区 PDF 路径当成最终附件
- 本机 API 不能更新旧父条目；已有父条目缺 PDF 时只加入附件队列，不得创建第二个父条目

## 写后对账与唯一可证回滚

`saveItems` 不是不重复的证明。每条写入后必须再次分页读取全库，以规范化 DOI、题名变体和 Obsidian 编号重算命中集合并生成 `POSTWRITE_RECONCILIATION`：

- 命中数为 1：父 key 必须取自写后反查，才可继续上传 PDF
- 命中数大于 1：立即停止附件与回链。仅当写前快照和写后集合能证明恰有一个本次新增父 key 时，才可用本地 Zotero API 删除该误建项；删除后再次分页确认唯一
- 无法唯一确定新增 key、删除失败或删除后仍不唯一：不得猜测删除对象；保持 `duplicate_merge_required` 或 `manual_review`，保存全部 key、写前后快照与响应
- 只有二次审计完成且正式 PDF 已反查为该父条目的真实 `application/pdf` 附件，才可写入或更新 `zotero://open-pdf`
- `write_rolled_back_duplicate` 仅表示本次误建已回滚，不表示历史重复已合并；续跑、重跑和并发写入仍须重新执行写前快照与写后反查

本合同对应 `scripts/paper_import.py` 的 `classify_post_write_matches`、`zotero_delete_item` 和两个导入入口。修改规则或实现时，须先更新 canonical，再由治理工具按来源哈希更新聚合说明中受影响的职责段。
