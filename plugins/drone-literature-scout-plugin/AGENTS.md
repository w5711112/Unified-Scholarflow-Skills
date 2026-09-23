# Skill 架构维护守卫

本目录的运行架构由 `architecture-manifest.json` 记录。普通内容维护只能修改已登记文件内的专业内容，不得顺带改变入口、reference 分层、证据所有权、接口版本或调用边。

- 最大 reference 深度为 1；所有运行时 reference 必须由对应 `SKILL.md` 直接路由，reference 之间不得建立强制加载链
- 同一风险在同一门内只生成一份权威证据并由后续步骤复用；原 Skill 规定的新取证边界仍必须刷新
- 不得静默减少数值护栏、白名单、状态、人工确认、失败阻断或验收项
- 每个领域只维护 canonical `SKILL.md`；规则或 reference 变化后只刷新 `Skill完整指南/research/` 中对应完整指南，职责接口变化时再更新《Skill 与 Plugin 的总体系说明》对应段与聚合总览
- 聚合总览只作导航和摘要，不得替代 canonical 规则；更新由治理命令按来源哈希定向执行，不使用常驻 watcher
- 内容变更不得修改 `architecture-manifest.json`；结构变更必须先取得用户明确批准、提升 `architecture_version`、提供兼容迁移顺序并通过迁移测试
- 正在迁移的 Skill 必须一次只迁移一个；callee 兼容旧/新接口并验证后，才允许逐个迁移 caller

## Global incident provider

- `collect-bug-update-accelerate` is provided only as `global.collect-bug-update-accelerate`; resolve and run it through the governance provider's `skillctl.py` resolver.
- This plugin must not restore a local collect Skill, mirror, registry, watcher, or incident runtime.

本文件和 manifest 只治理结构，不替代任何 Skill 的专业规则。发现冲突时，以原始 `SKILL.md` 及其强制 reference 为准并停止静默改写。
