---
name: collect-bug-update-accelerate
description: Use when a Skill, script, or tool has a real technical failure, a verified route must be reused, or a resolved failure needs owner-routed regression or promotion handling.
---

# Codex 故障记忆、复用与加速

## 范围与读取

本 Skill 只拥有真实技术故障捕获、已验证方案复用、原样重试阻断、回归状态、效果验证，以及将经验路由给唯一负责人的永久化。它不裁决领域语义、研究质量或专业方法，也不拥有 Vault 扫描、空间盘点、版本清理、文件删除或运行时生命周期。

按分支只读取一份直接参考：项目守卫与事故库路径读 `references/project-scope.json` 和 `references/project-incident-guard.md`；字段、命令、状态和回执读 `references/incident-schema.md`；已验证路线和依赖读 `references/known-solution-playbook.md`；负责人、风险和永久化读 `references/improvement-routing.json`。这些参考与本文件同属权威要求；不要预载无关参考或从参考继续加载第二层。

## 快路径与故障闭环

- **正常成功路径不写故障库**；不为普通工具调用预检、候选审计或创建成功流水账。
- 已知脆弱、准备复用历史方案、前一步失败或环境版本变化时，先对本地库执行只读 `preflight`；本地未命中才读取公共库。
- 任意异常、非零退出、权限拒绝、结果缺失或验证失败后，先 `capture-event` 再改变路线。预期 TDD RED、受控探针和用户取消不算产品事故。
- `use-verified-solution` 的 **42（REUSE_REQUIRED）** 不是普通成功：核对环境、质量守卫、`domain_semantics` 与唯一负责人，执行 `preferred_route`，成功即 `reuse-result --outcome success` 并给出效果验证；失败即登记 `failure` 为回归。不得原样重试 `forbidden_retries`。
- 新故障按“症状 → 阶段 → 最小复现 → 单一假设 → 修复 → 效果验证”闭环；本轮已解决必须 `resolve` 为 `verified`。状态固定为 `observed`、`diagnosed`、`verified`、`promoted`、`regressed`、`retired`。

`EFFECT_VERIFICATION` 至少记录预期效果、禁止副作用、是否改变领域语义、可复核验证位置和 `cleanup_complete`。退出码 0 不替代效果验证。临时候选一次真实成功并经效果验证即可复用；本轮出现新解法、复用结果或回归才查询 `promotion-candidates`，候选非空才运行只读 `promotion_audit.py`。

## 与 workspace-hygiene 的协作

空间、路径、版本或运行时生命周期事故按以下状态机处理：

```text
space/path/version/runtime-lifecycle incident
→ emit one HYGIENE_REQUEST
→ workspace-hygiene returns HYGIENE_RESULT
→ collect verifies the original expected effect
→ collect resolves or records the technical failure
```

普通空间整理直接调用 `workspace-hygiene`，不制造 incident。hygiene 失败最多报告一个真实技术故障；**同一事件不得递归调用 workspace-hygiene**。这一协作是 handoff，不新增反向 `requires` 边，因此 provider graph 保持无环。

## 依赖、负责人和交付

缺失依赖且安装目标明确时，先在当前环境安装并验证，再重试原路线；安装失败是新证据，不能循环同一命令。只有安装不可行、映射不明或高风险时才提出降级路线。外部平台或版本结论先查官方资料，再做本地回归；不可访问或冲突则保留临时候选。

永久写回遵循 `improvement-routing.json` 的唯一负责人和风险策略。`domain_semantics=true`、数据写入、研究/搜索语义与不可逆动作必须走完整效果合同和回归；修改前保留可恢复原内容，失败即恢复并登记，不能记成功。

交付前仅在本轮事件变化时查询候选；确认正常快路径未改写事故库、每个真实事故有唯一观察和对应回执、没有原样重试、且受影响 owner 测试通过。用 resolver 调用脚本：`skillctl.py run global.collect-bug-update-accelerate -- incident_registry.py ...`。canonical `SKILL.md` 是唯一权威；根目录 `collect-bug-update-accelerate-完整指南.md` 必须是字节级镜像。
