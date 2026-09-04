# Zotero—Obsidian 论文导入工具

> 用途：把 `01-核心论文精读.md` 中的论文安全接入 Zotero，并在确认真实 PDF 附件后回填 Obsidian 双链

<span style="background:#b1ffff">这套工具的成功条件不是“生成了一条记录”，而是 DOI、元数据、PDF、Zotero 附件 key 和 Obsidian URI 能够互相对账</span>

## 先给结论

- 唯一入口是 `SKILL.md`，它负责触发、路由、硬门和接口
- 三个 `references/` 文件与入口共同构成权威 Skill，按任务类型只加载需要的部分
- Vault 根目录的聚合说明只概括职责和关键规则，不复制三个 reference，也不是第二套规则
- `scripts/` 负责处理，`tests/` 负责验证，`运行数据/` 保存过程状态
- 任何 DOI、版本、PDF 或附件 key 不确定时，进入待核验状态，不猜测

## 文件关系

| 文件 | 作用 | 是否可以替代主文件 |
|---|---|---|
| `SKILL.md` | DOI、PDF、Zotero 和双链合同 | 不能替代 |
| `references/identity-and-acquisition-contract.md` | 固定范围、DOI 身份与合法 PDF 获取 | 不能删除或跳过对应任务 |
| `references/zotero-write-safety-contract.md` | 全库去重、写入、附件、合并与回滚 | 不能删除或跳过对应任务 |
| `references/state-verification-and-reporting-contract.md` | 状态、回链、验证与报告 | 不能删除或跳过对应任务 |
| `scripts/` | 提取、核验、下载、写入和对账 | 不能删除或压平 |
| `tests/` | DOI、PDF、manifest、canonical 入口和回链回归测试 | 不能省略 |
| 插件根 `architecture-manifest.json` | 登记六个领域 Skill、接口和数值护栏 | 必须保留 |
| `运行数据/` | 批处理状态、manifest、校验结果和 PDF 工作副本 | 不是规则文件 |

总体系说明位于 Vault 的 `Skill完整指南/Skill与Plugin的总体系说明.md`，本 Skill 的集中完整指南位于 `Skill完整指南/research/zotero-obsidian-paper-import-完整指南.md`。

## 用户语言风格触发

当用户说“使用我的 Obsidian 语言风格”、 “按我的 Obsidian 笔记风格写”或语义等价表达时，**必须先调用** `obsidian-note-style`

表达层采用：

- 结论先行，短段落说明一个中心问题
- 表格比较论文、状态和证据来源
- 明确区分 **论文报告**、**可以推断** 和 **尚不能证明**
- 用带别名的精确 WikiLink 或 Markdown 链接，不制造失效链接

本 README 的语言风格规则不能替代 DOI 身份核验、PDF 魔数检查、Zotero API 对账或附件 key 验证

## 怎么使用

执行前核对 `SKILL.md`、所需 reference 与插件协作合同；规则变化后，再由治理工具按来源哈希更新聚合说明中本 Skill 的职责段。

推荐顺序：

1. 由入口判断任务类型；全批任务加载三个 reference 各一次，局部任务只加载对应 reference
2. 读取论文编号、来源和 DOI，生成一次身份事实证据
3. 核验标题、作者、venue、年份和版本
4. 在原合同规定的每个新边界刷新 Zotero 全库快照
5. 验证 PDF 内容而不是只看文件扩展名
6. 写入后生成一次统一对账证据
7. 只有拿到真实附件 key 后回填 Obsidian URI

## 边界

<font color="#ff0000">没有真实附件 key 时，不得生成 `zotero://open-pdf/` 链接</font>

- 不猜 DOI、PDF 版本或 Zotero key
- 不把 HTML 登录页改名为 `.pdf`
- 不把 Snapshot、Web Page 或父条目当作正式论文 PDF
- 不因重跑批处理而创建重复父条目
- 不把未完成状态写成成功

## 验证

```powershell
python -m unittest discover -s .\skill-with-plugin\drone-literature-scout-plugin\skills\zotero-obsidian-paper-import\tests -v
python .\skill-with-plugin\drone-literature-scout-plugin\tests\test_architecture_governance.py -v
```

交付前必须能回答：哪些论文已导入 PDF，哪些只有元数据，哪些 DOI 待核验，哪些 PDF 下载失败，以及哪些条目仍需人工处理
