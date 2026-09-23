---
name: zotero-obsidian-paper-import
description: Use when a Codex task must import papers listed in an Obsidian Markdown index into Zotero, verify DOI and publication identity, detect or merge duplicate Zotero parent items, obtain legal PDFs, create stored Zotero attachments, or maintain zotero://open-pdf backlinks
---

# Obsidian 论文目录导入 Zotero 并建立双链

## 插件级轻量故障协作

- 本 Skill 负责 DOI—正式 PDF—Zotero 父条目/附件—Obsidian 双链的事实与流程；不确定时暂停，不猜标识、版本或 URI
- 用户要求“使用我的 Obsidian 语言风格”“按我的 Obsidian 笔记风格写”或语义等价表达时，先调用 `obsidian-note-style`；表达可调整，本文的事实、状态和安全合同优先
- 插件任务开始或 Skill 清单变化时读取插件根 `../../references/skill-collaboration-contract.md` 并核对职责；同一任务内拓扑未变不重复读取
- **正常成功路径不写故障库**。仅在组件已知脆弱、复用历史方案或路线刚失败时运行 `incident_registry.py preflight`：本地事故库优先，未命中才查公共事故库只读
- 任意异常、非零退出、权限拒绝、结果缺失或验证失败均先 `capture-event`，再改路线；原路线重试前通过 retry guard。最终回答前扫描实际工具结果并补记；预期 TDD RED、受控探针和用户取消不算产品事故
- **只有本轮事件发生变化**或历史方案产生新复用结果时才检查候选；候选非空才加载 `promotion_audit.py`
- **本 Skill 的效果验证**：DOI/标题/年份身份一致；Zotero parent 与 stored PDF 附件可打开且去重无误；Obsidian 的 `zotero://` 与返回链接命中正确对象

## 权威与按需加载

`SKILL.md` 与下列三个一级 reference 共同构成本 Skill 的权威要求。先判断任务类型，再加载对应文件；全批任务加载三者，每个 reference 只加载一次。reference 之间不形成强制加载链。

| 当前任务 | 本轮直接加载 |
| --- | --- |
| 编号、DOI、出版身份、PDF 来源或合法获取 | `references/identity-and-acquisition-contract.md` |
| Zotero 查重、父条目、附件、合并、写入或回滚 | `references/zotero-write-safety-contract.md` |
| 状态、Obsidian 回链、批处理报告、失败防护或交付验收 | `references/state-verification-and-reporting-contract.md` |

## 不可越过的运行门

1. **身份**：DOI、正式页面、PDF 版本或 Zotero key 任一不确定即暂停；不猜 DOI、版本、父 key、附件 key 或 URI
   - 已发现正式版与现有条目的标题、作者、DOI、venue、年份或版本不一致时进入 `VERSION_CONFLICT`，不得把“已有 PDF”“无需重新下载”或“用户没有再次点名本 Skill”当作跳过理由；完整论文精读已授权本 Skill 完成正式版本接管和元数据读回，但未授权删除旧附件
2. **唯一性**：在详细合同规定的每个刷新边界分页读取全库，同时审计规范化 DOI、题名身份和 Obsidian 编号；任一组多父条目即 `duplicate_merge_required`
3. **写入**：零命中才创建，唯一命中才复用；写前必须有 dry-run 与父 key 写前快照，写入后必须再次分页读取。本机 API 只作只读事实源，不支持更新或删除；需要这些动作时必须使用已验证 UI/bridge，否则进入人工复核
4. **附件**：仅正式版本、`%PDF-` 魔数、身份匹配且本机 API 反查为 `application/pdf` stored attachment 才成功。Connector 的 `saveAttachment.parentItemID` 只接受同一 `saveItems` session 的 connector item id，禁止传 Zotero 父 key
5. **回链**：实际附件 key、父子关系、内容类型和 URI 全部反查后才改 Obsidian；父 key 不得充当附件 key
6. **权限**：不绕过付费墙、验证码、访问控制、版权或限速；403、429 或登录页立即退避或转获授权流程
7. **架构**：批处理前核对 canonical 入口、协作合同与插件清单；冲突时停止导入、下载、写入和回链

## 单证据门与刷新边界

同一门内只生成一份权威证据，后续步骤引用证据 ID，不重复执行同一验证：

| 证据 ID | 一次生成后可供 |
| --- | --- |
| `IDENTITY_EVIDENCE` | DOI 接纳、正式元数据、PDF 版本核验 |
| `VERSION_RECONCILIATION` | 旧/正式身份映射、父条目元数据更新、正式附件读回、annotation-free backup 与下游证据重建 |
| `PREWRITE_LIBRARY_SNAPSHOT` | 写入门内的 DOI/题名/编号三组审计、dry-run 与父 key 快照 |
| `POSTWRITE_RECONCILIATION` | 写后唯一性、children、附件 content type、URI、状态与回链 |

刷新以实际变化和写入边界为准：初始盘点供查重与 dry-run 共用；`saveItems` 紧前由唯一写入层在进程锁内刷新并查重，写后只生成一次父条目回执；附件上传后生成一次最终对账供状态与回链共用。搜索开始、来源抓取完成、进入新章节不单独触发全库重读。续跑、外部修改、合并或回滚使旧事实失效时刷新受影响证据；身份、PDF 与来源未变时复用核验结果。

## 执行状态机

1. 核对 canonical 入口与插件协作合同
2. 提取编号、来源并验证连续性
3. 生成 `IDENTITY_EVIDENCE`
4. 若身份冲突，先完成 `VERSION_RECONCILIATION`；未验证前停止后续导入、批注与回链
5. 刷新 `PREWRITE_LIBRARY_SNAPSHOT`；零/一/多父条目分别创建、复用或阻断
6. 生成 dry-run；每批最多 10 条
7. 创建或复用父条目；合格 PDF 上传为 stored attachment。已有父条目缺附件而当前没有受支持 UI/bridge 时，写入 `existing_parent_attachment_requires_supported_ui_or_bridge` 并停止，不以空 session 伪造上传
8. 生成 `POSTWRITE_RECONCILIATION`；新增重复只按回滚合同处理本次唯一可证明的误建项
9. 仅用已反查的真实附件 key 回填 `zotero://open-pdf`
10. 按详细状态合同落盘，未完成不得写成成功
11. 运行单元测试、API/Markdown/架构审计，按状态分类报告

## 与论文精读样式的职责边界

论文 Callout 的强调语义不属于本 skill。本 Skill 只负责身份、父条目/附件、回链、状态和幂等性；来源行仅保留正式链接、DOI、Zotero PDF、状态与真实附件 key。全文证据、作者贡献和高亮语义移交 `read-paper-analysis-highlight`；Markdown/HTML、全称—简称、Callout 与 WikiLink 规范移交 `obsidian-note-style`。导入后如需精读则显式调用前者；如需写入或整理 Obsidian，由其协同后者。

## 交付判定

交付前确认：所需 reference 各加载一次；每个刷新边界均有新证据；十种状态和 `write_rolled_back_duplicate` 未合并；父条目、附件、DOI、content type、文件、URI 已对账；实际失败已闭环；canonical 入口与聚合说明来源标记有效。

## canonical 与聚合说明

本文件及其三个强制 reference 是本 Skill 的唯一权威来源。规则或 reference 变化后，只刷新 `Skill完整指南/research/zotero-obsidian-paper-import-完整指南.md`；用途、输入输出、协作或边界变化时，再更新 `architecture-manifest.json`、协作合同与《Skill 与 Plugin 的总体系说明》对应段。派生说明不得反向覆盖 canonical。
