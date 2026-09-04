# 状态、回链、验证与报告合同

本文件由 `SKILL.md` 直接在 Obsidian 回填、状态判定、批处理、失败防护、验收或交付任务中加载。

## Obsidian 双链回填

仅当 Zotero 父条目的题名、作者、DOI 与目标论文匹配，PDF 是正式版本，本机 API 已反查真实附件 key、父子关系和 `application/pdf`，且 URI 可打开时，才修改 `01-核心论文精读.md`。保留正式出版链接和 DOI，只新增或更新：

`[Zotero的PDF](zotero://open-pdf/library/items/<attachment-key>)`

无附件 key 不得生成 URI；回填前备份并记录逐行变更。

## 状态合同

以下状态不得合并为“成功”：

- `ready`：身份和元数据已核验，可导入
- `imported_metadata`：父条目已创建，暂无 PDF
- `imported_pdf`：父条目和 stored PDF 均已反查
- `duplicate_existing`：已有唯一匹配条目，复用其 key
- `duplicate_merge_required`：同一身份组命中多个父条目；合并复核前禁止写入
- `doi_candidate_review`：候选 DOI 证据不足
- `no_public_doi_confirmed`：正式记录无公开 DOI
- `pdf_download_failed`：元数据可用但 PDF 获取失败
- `metadata_conflict`：来源间存在版本或书目信息冲突
- `manual_review`：需用户登录、选择版本或确认候选

`write_rolled_back_duplicate` 只表示本次误建项已按合同回滚，不等同于历史重复已合并。

## 落盘与批次报告

每条完成入口状态机后立即写入状态日志，再处理下一条；仅 `imported_pdf` 可回填 Obsidian URI。每批分别报告已处理编号、PDF 成功、仅元数据、已存在、DOI 待确认、PDF 失败、冲突和人工待处理数量，不把未完成项描述为完成。

## 失败防护

- 不猜 DOI，不把网页或 Snapshot 改名冒充 PDF，不把父 key 当附件 key
- 不把预印本 PDF 附到正式出版条目，不在 Zotero 反查前回链
- 不因重跑新建重复父条目；重复未合并时不得继续 `saveItems` 或把 `duplicate_merge_required` 算作成功
- 不删除原始来源行、原始 PDF 或用户已有 Zotero 条目；唯一可证的本次误建项只能按写后回滚合同处理
- 不复制 Cookie、Token、机构账号或浏览器认证文件，不为完成率忽略版本冲突或合并疑似重复

## 必须运行的验证

- 单元测试：DOI 规范化、编号提取、候选接受/拒绝、PDF 魔数、重复判定、payload、来源行回填
- dry-run：不得访问 Connector 写接口
- 写后 API 对账：父条目、附件 key、DOI、content type 和文件存在性
- Markdown 审计：编号、来源、DOI、Zotero URI 与状态一致
- 镜像审计：canonical `SKILL.md` 与唯一完整指南必须字节级一致
