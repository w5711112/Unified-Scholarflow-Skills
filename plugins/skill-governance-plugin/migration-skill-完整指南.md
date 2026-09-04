---
name: migration-skill
description: Use when moving, rebuilding, adapting, or validating one or more skills across Codex, Claude Code, Kimi Code, or another Agent where plugin APIs, tools, paths, scheduling, or runtime capabilities may differ.
---

# Skill 跨模型与跨 Agent 迁移

## 插件级轻量故障协作

> [!important]- **快路径与慢路径**
> - **正常成功路径不写故障库**；普通成功步骤直接继续，不为每次工具调用扫描、查询或记录
> - 当前组件已知脆弱、准备复用历史方案或某路线刚失败时，才运行 `incident_registry.py preflight`：先查项目守卫指定的**本地事故库**，未命中再查**公共事故库只读**；都无匹配就继续
> - 出现**任意异常、非零退出、权限拒绝、结果缺失或验证失败**时，立即运行 `capture-event` 写入本地事故库；记录后才改变路线，同一路线再次执行前必须通过 retry guard
> - **最终回答前**扫描本任务的实际工具结果，补记尚未入库的真实失败、拒绝、非零退出和验证失败；预期 TDD RED、受控探针和用户取消不算产品事故
> - **只有本轮事件发生变化**或历史方案获得新的复用结果时才检查候选；候选非空才加载 `promotion_audit.py`，否则不增加额外工作
> - **本 Skill 的效果验证**：能力清单、路径与依赖替换、无专用插件降级和三层验收均达到原 Skill 的效果，不把宿主特性误写成通用能力
> - 插件任务开始或 Skill 清单/协作结构变化时读取 `../../references/governance-contract.md`，仅按其注册表解析、provider、mirror 与失败关闭规则动态核对职责；同一任务内清单未变时不重复枚举全部 Skill

> [!note]- **镜像维护**
> - 本文件是 canonical；插件根 `migration-skill-完整指南.md` 是其字节级派生镜像
> - 修改 canonical 后，先将 canonical bytes 单向复制到镜像并核对字节相等，再运行 `../../scripts/skillctl.py audit --json --components global.migration-skill`
> - 若 canonical 哈希漂移、audit 出现 finding 或复制后的镜像不一致，必须停止；不得把镜像反向当作合并来源

## Obsidian 语言风格触发规则

当用户说“使用我的 Obsidian 语言风格”“按我的 Obsidian 笔记风格写”或语义等价表达时，**必须调用** `obsidian-note-style`，再生成或修改中文迁移说明。该 skill 只负责表达层，不能降低能力核验、秘密边界和三层验收要求。

## 结论、范围与硬边界

迁移不是复制提示词，而是保留源 Skill 的触发条件、判断顺序、证据合同、资源和可验证行为，再把平台专属能力映射为目标宿主能真实执行的**替代**工具或明确降级路径。只有**文件级验收、能力级验收、行为级验收**全部通过，才能称为迁移完成；目标环境缺少关键能力时，必须报告差异，**不得宣称无损兼容**。

适用于 Codex、Claude Code、Kimi Code 与普通 Agent 之间的迁移、重建、适配或等价性审查，也适用于依赖浏览器、PDF、Shell、Zotero、调度器和应用连接器的 Skill。不用于普通文件复制，不把目标 Agent 尚未具备的能力描述成已经实现；只复制 `SKILL.md` 而遗漏资源或测试，只能称为近似提示词。

始终保持这些不变量：

- 源 `SKILL.md` 及其直接引用资源是当前迁移语义的权威；工具名称可变，决策顺序、证据等级、备份要求和失败条件不可变
- `scripts、references、assets、fixtures 和 tests` 的相对关系、路径、编码与验证资产不得遗漏
- 平台无关核心、宿主适配、工作区数据、配置和秘密必须分层；缺失能力必须显式降级，不得静默跳过
- 不复制 API key、token、cookie、浏览器登录态、OAuth 凭据、用户认证数据库或私有会话记录
- 写入型能力必须先备份、先 dry-run、写后重读；重复运行不得制造重复数据或不可解释漂移

## 单次迁移主链与证据复用

一次迁移只维护一条证据主链：

1. 完整读取源 Skill 及直接资源，冻结文件、哈希、测试与外部状态为 `MIGRATION_BASELINE`。
2. 加载 `references/inventory-and-capability-matrix.md`，划分核心、适配、状态、配置和秘密；逐项形成 `CAPABILITY_MAP`。
3. 只按目标宿主加载 `references/host-adapters-and-secrets.md` 的对应分支，复制核心并建立适配层、配置模板与降级路径。
4. 加载 `references/validation-and-reporting.md`，依次执行文件级、能力级、行为级验收，形成 `MIGRATION_ACCEPTANCE` 和迁移报告。
5. 三层均通过才宣布完成；否则交付已验证子集、差异与恢复条件，不虚报等价。

同一任务、同一版本下，每个 reference 只完整读取一次。同一证据边界内，后续步骤引用上述证据 ID，不重复扫描、重复建矩阵或另立平行验收表；源/目标文件、宿主能力、配置、秘密状态、外部状态或测试产物变化时，只刷新受影响证据，原规则要求的新层级验收仍是新的证据边界。

若任一直接资源未读、源哈希在迁移中变化、能力矩阵有未验证映射、秘密边界不清、双端同时变化或交付要求未验证，立即停止，不以文字相似或“文件存在”代替行为等价。
