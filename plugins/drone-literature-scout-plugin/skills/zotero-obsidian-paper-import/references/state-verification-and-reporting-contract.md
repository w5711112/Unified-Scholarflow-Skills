# 状态、回链、验证与报告合同

本文件由 `SKILL.md` 直接在 Obsidian 回填、状态判定、批处理、失败防护、验收或交付任务中加载。

## Obsidian 双链回填

仅当 Zotero 父条目的题名、作者、DOI 与目标论文匹配，PDF 是正式版本，本机 API 已反查真实附件 key、父子关系和 `application/pdf`，且 URI 可打开时，才修改 `01-核心论文精读.md`。保留正式出版链接和 DOI，只新增或更新：

`[Zotero的PDF](zotero://open-pdf/library/items/<attachment-key>)`

无附件 key 不得生成 URI；回填前备份并记录逐行变更。

### 合并和版本接管后的全局引用一致性

- 在同一份 `VERSION_RECONCILIATION` 或同版本合并回执中登记旧/新父 key、旧/新附件 key、论文编号、正式来源、关联 Obsidian 文件及标题/块。复用此映射，不另建第二份事实注册表
- 写前盘点当前 Vault 中 Markdown、Canvas、索引和实际在用状态文件的相关引用，同时检查 Zotero notes、relations、extra 等已有返回 Obsidian 的引用。扫描限于已授权 Vault；保留历史快照与备份的原始事实，不对它们做全局字符串替换
- 同版本合并若保留附件 key，核验现有 PDF URI 的附件存在、未删除、属于正确保留父条目且文件身份一致；验证通过时保留原链接，不为统一外观改 key。引用已退役父 key 的当前入口按映射更新
- 正式版本替换若附件 key 改变，更新所有在用阅读入口，并逐项检查页码和批注锚点；无法对应的新旧页码标为待重建，禁止直接沿用。返回 Obsidian 的已有链接必须仍能定位真实文件和标题/块，不新建空占位笔记消除错误
- 最终用一次合并后的事实快照核验 `论文编号 → 唯一父条目 → 正式附件 → Obsidian 正向入口 → Zotero 返回笔记`。适用的任一方向断开或引用旧版时，版本接管与双链同步不得标为完成；原先没有反向链接的情况单列为缺失，不声称已验证双向链
- 用途、输入输出或验收边界变化时，同步本 Skill 的完整指南、协作接口和总体系说明对应部分。正文语言及链接格式分别由 `renhua`、`obsidian-note-style` 处理，论文身份和 Zotero key 仍由本 Skill 负责

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

`VERSION_CONFLICT` 是 `metadata_conflict` 下的强制阻断子状态，不增加第十一种批处理状态：它表示完整精读已确认现有父条目/附件不是正式版本；完成正式版本接管、元数据/附件读回、旧父条目退役和证据重建前不得退出 `metadata_conflict` 或进入完成状态。若只差 Zotero UI 中退役旧父条目，`version-reconciliation.json` 使用 `pending_manual_retirement`；该回执本身可通过结构验证，但 `completion_ready: false`，不能被完成门接纳。

## 落盘与批次报告

每条完成入口状态机后立即写入状态日志，再处理下一条；仅 `imported_pdf` 可回填 Obsidian URI。每批分别报告已处理编号、PDF 成功、仅元数据、已存在、DOI 待确认、PDF 失败、冲突和人工待处理数量，不把未完成项描述为完成。

## 失败防护

- 不猜 DOI，不把网页或 Snapshot 改名冒充 PDF，不把父 key 当附件 key
- 不把预印本 PDF 附到正式出版条目，不在 Zotero 反查前回链
- 不把“文件已经下载”解释为“可以跳过 Zotero”；不把 `VERSION_CONFLICT` 标成不适用，也不在只更新 Obsidian 后声称正式版本已接管
- 不因重跑或版本更新创建第二父条目；接口不足时记录待处理，不用临时候选规避唯一性。旧条目未退役时不得把 `duplicate_merge_required`、`pending_manual_retirement` 或版本接管算作完成
- 不删除原始来源行、原始 PDF 或用户已有 Zotero 条目；唯一可证的本次误建项只能按写后回滚合同处理
- 不复制 Cookie、Token、机构账号或浏览器认证文件，不为完成率忽略版本冲突或合并疑似重复

## 必须运行的验证

- 单元测试：DOI 规范化、编号提取、候选接受/拒绝、PDF 魔数、重复判定、payload、来源行回填
- dry-run：不得访问 Connector 写接口
- 写后 API 对账：父条目、附件 key、DOI、content type 和文件存在性
- 版本接管对账：`validate_version_reconciliation.py` 通过，正式父条目字段、正式附件、annotation-free backup 和下游证据重建均有读回
- Markdown 审计：编号、来源、DOI、Zotero URI 与状态一致
- 镜像审计：完整指南由 canonical `SKILL.md` 与三份直接 reference 确定性展开，逐来源核验哈希与内容覆盖；完整指南不与入口单文件作字节相等比较。实际文件镜像仍要求逐文件字节级一致
