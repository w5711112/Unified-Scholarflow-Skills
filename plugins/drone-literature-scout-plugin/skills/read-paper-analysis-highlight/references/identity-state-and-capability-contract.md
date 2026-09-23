# 论文身份、状态与能力合同

## 适用前提

本 Skill 只在 `zotero-obsidian-paper-import` 已核验正式版本和 `application/pdf` 附件后执行。摘要、网页、旧笔记、搜索摘要和二手综述只能定位，不能替代 PDF 全文；本地 PDF、annotation-free backup 或哈希核验副本可用时，不先抓网页。

开始时明确二选一：

- `workflow_scope: full`：执行完整精读、Obsidian 笔记、Zotero 原生批注与 PDF 回链，只有全部门通过才可 `已AI全文读`
- `workflow_scope: obsidian-only`：只做阅读分析和 Obsidian 集成；必须明确写为部分交付并保持 `待精读`，不得把未执行的 Zotero 门标成已通过或不适用

“使用现有 PDF”或“不重新下载”只改变 PDF 获取步骤；该文件仍须核验并绑定到 Zotero 正式父条目/附件。用户要求完整精读时，即使没有再次点名导入 Skill，也必须调用其承担身份、正式版本和附件职责。

## `PAPER_BASELINE`

开始前一次生成并冻结：

- 标题、作者、期刊/会议、年份、DOI
- Zotero 父条目 key、PDF 附件 key、本地路径、MIME
- 正式发表版、接收稿或预印本的版本身份
- PDF 页数、大小、SHA-256
- annotation-free backup 的路径和 SHA-256
- Obsidian 标题、来源行原字段、独占行 block ID、状态和个人理解源码
- 实际 `zotero.exe` ProductVersion、当前 Python 解释器和依赖探测

以下任一情况立即停止，状态保持或恢复为 `待精读`：DOI/标题/作者/版本冲突，附件不是 `application/pdf`，页数或哈希与登记不一致，找不到可信无批注 backup，Snapshot/网页存档/残缺 OCR 被当作全文。不能从原文确认的内容写“未从原文确认”，不能凭常识补齐。

### `VERSION_RECONCILIATION`

身份无冲突时也要留下 `status: not_required`、`conflict_detected: false` 和 `formal_identity_verified: true`。一旦发现标题、作者人数/次序、DOI、venue、年份或版本冲突，状态改为 `VERSION_CONFLICT`，暂停所有页码、quads、area、批注与回链工作，并调用 `zotero-obsidian-paper-import`：

1. 记录旧父条目 key、旧附件 key、旧 PDF SHA-256 和可恢复保留状态
2. 以正式来源核验题名、全部作者、venue、年份、DOI/无 DOI 状态和 URL
3. 把正式 PDF 作为独立 stored attachment 接入正确父条目，更新父条目元数据；Connector 的 `saveAttachment.parentItemID` 只能使用同一 `saveItems` session 的 connector item id，不能把 Zotero 父 key 当成 connector id
4. 从本机 API 读回父条目、children、正式附件 key、`application/pdf`、页数和 SHA-256；若因接口限制受控新建正式父条目，旧父条目须通过 Zotero UI/受支持 bridge 移入回收站并再次读回
5. 为正式附件建立新的 annotation-free backup，并验证文件存在、哈希一致
6. 旧附件上的页码、坐标、逐页台账、批注和回链证据全部失效；在正式附件上重新绑定/重建

若正式父条目、附件、元数据和新证据均已完成，但旧父条目仍因只读 API 或界面不可用而留在活动库，回执写 `status: pending_manual_retirement`，并记录准确旧 key、人工动作和原因。该回执可以证明已经安全停在人工门前，但 `completion_ready` 必须为 `false`。只有旧父条目从活动库退役、正式父条目读回唯一，且 `scripts/validate_version_reconciliation.py` 返回 `valid: true`、状态为 `verified`，才退出冲突态并允许进入 `已AI全文读`。发现正式版后的纠错属于用户已授权完整精读的正常职责，不要求用户再次逐项提醒；删除旧条目或旧附件仍是独立的破坏性动作，不在该授权内。

## 不可妥协原则

1. 全文优先：从第 1 页到最后一页，逐词、逐句、逐公式、逐图、逐表、逐图注读取
2. 证据优先：先完成逐页台账和 Claim–Evidence 映射，再写总结
3. 语义优先：翻译不等于分析；评论解释机制、意义、复现条件、疑点或边界
4. 视觉优先：必须渲染并由视觉模型直读图、表、公式、图注、轴和图例；文本 OCR 只能是明确的临时 `observed` 降级，不能成为 `verified`/`promoted`
5. 准确优先：默认不限制时间，不用数量、字数和速度换表面完成
6. 可逆优先：覆盖 PDF 前必须有 SHA-256 可核验的 annotation-free backup；只删除可追踪的旧 AI 批注
7. 唯一归属：知识只在一个规范位置完整解释，论文笔记用精确 WikiLink 复用
8. 进度透明：从运行开始计时；未完成时至少每隔 20 分钟说明阅读遍次、PDF 页码、已检查公式/图/表、当前环节与剩余门槛

## Zotero 能力边界

- 每次运行读取真实 `zotero.exe` 的 ProductVersion，不信应用 ID、标题或缓存目录名
- 合同已在 **Zotero 9.0.6** 验证；其他 Zotero 9 小版本重新做一次原生批注读回测试
- 区域批注可重新框选或调整范围；已验证版本的弹出卡片不能靠拖拽任意拉伸
- 评论**不设置字符上限**；长内容第一行仍须先给结论，不能以长度为由重复或堆翻译
- 不支持的版本、桥接 schema/type 不匹配、真实行为门未通过时不得更新完成状态

## 固定流程与状态机

```text
核验导入、身份和无批注备份
  → 状态保持/恢复“待精读”
  → 全文阅读与逐页视觉台账
  → Claim–Evidence、作者和知识归属证据
  → 完整 AI block 经过 language-gate.json 验证的 renhua 通读
  → 唯一论文 Callout 与一次 Obsidian 全库视觉交接
  → annotation manifest、quote/quads/area 双坐标
  → health → preflight → apply → 原生读回
  → 可编辑/可删除/无锁/未知变化为 0
  → 从干净 backup 生成首页记忆句与回链层
  → 清理 → 新鲜最终全量验证
  → 最后改为“已AI全文读”
```

只有 `workflow_scope: full`、版本核对、逐页台账、作者调研、`LANGUAGE_GATE`、知识链接、笔记、PDF 位置、Zotero 原生化、可编辑/可删除、无锁、回链行为和 manifest 全部通过后，才改为 `已AI全文读`。安装元数据未规范化与行为门必须分开记录；行为门失败即保持 `待精读`。

## 职责边界

- 本 Skill：全文证据、作者调研、论文 Callout 强调语义、证据原子、坐标计划、批注语义与最终效果
- `zotero-obsidian-paper-import`：论文身份、正式版本、DOI/PDF/Zotero key
- `obsidian-note-style`：知识归属、通用 Callout/WikiLink、全 Vault 视觉覆盖、媒体生命周期
- `draw-style`：通用科研绘图与八项硬质量门槛
- `zotero-local-bridge`：认证、health、preflight、原子机械 apply、冲突阻断和原生读回，不决定语义
- `global.collect-bug-update-accelerate`：执行故障记录与路线复用，不选批注、不生成计划、不裁决论文事实

用户要求“使用我的 Obsidian 语言风格”或语义等价表达时，必须调用 `obsidian-note-style` 后再写中文精读笔记；两者不能互相替代。
