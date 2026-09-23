---
name: collect-bug-update-accelerate
description: Use when a Skill, script, or tool has a real technical failure that must be captured as an event, classified into a stable problem family, matched to one verified guarded solution, or routed for regression and permanent owner handling.
---

# Codex 故障族、方案复用与加速

## 范围与读取

本 Skill 只处理真实技术故障：保存事件事实，把证据充分的同类事件归入稳定问题族，并复用该问题族下唯一适用的已验证方案。它还负责原样重试阻断、方案回归、效果验证，以及将可永久化的经验路由给唯一负责人。它不裁决领域语义、研究质量或专业方法，也不拥有 Vault 扫描、空间盘点、版本清理、文件删除或运行时生命周期。

按分支读取直接参考：项目守卫与事故库路径读 `references/project-scope.json` 和 `references/project-incident-guard.md`；字段、命令、状态和迁移读 `references/incident-schema.md`；问题族定义读 `references/problem-family-catalog.json`；可复用方案读 `references/solution-catalog.json` 和 `references/known-solution-playbook.md`；负责人、风险和永久化读 `references/improvement-routing.json`。这些参考与本文件同属权威要求；不要从参考继续加载第二层。

## 三层记录

- **事件 `events[]`**：保留原始症状、环境、证据、时间、发生次数和旧 ID，不因分类而删除事实。
- **问题族 `problem_families[]`**：只表达可重复的失败机制。匹配顺序固定为显式 `family_id`、结构化特征、确定性规则、候选、未分类；环境只用于方案适用性判断，不参与问题族身份。
- **方案 `solutions[]`**：步骤、适用守卫、禁止路线和验证合同只保存一次。权威目录方案在本地库只保存引用与计数，本地验证形成的方案只保存一份正文。复用成功或失败记在实际命中的方案上，不为同族每个事件复制一套方案。

## 快路径与故障闭环

- **正常成功路径不写故障库**；不为普通工具调用预检、候选审计或创建成功流水账。
- 已知脆弱、准备复用历史方案、前一步失败或环境版本变化时，先对本地库执行只读 `preflight`；本地未命中才读取公共库。只有 `--component` 时只返回候选问题族，不能强制复用。
- 任意异常、非零退出、权限拒绝、结果缺失或验证失败后，先 `capture-event` 再改变路线。预期 TDD RED、受控探针和用户取消不算产品事故。
- 只有唯一问题族、唯一已验证方案和适用环境守卫同时通过，才返回 `use-verified-solution` 和 **42（REUSE_REQUIRED）**。它不是普通成功：按方案步骤执行，成功即 `reuse-result --outcome success` 并给出效果验证；失败即把该方案标为 `regressed`。同族其他方案和事件状态不受牵连。
- 新故障按“症状 → 阶段 → 最小复现 → 单一假设 → 修复 → 效果验证”闭环。`capture-event` 没有找到唯一适用的已验证方案时返回 **43（RESOLUTION_REQUIRED）**；这不是新的产品故障，而是继续处理的控制信号。必须在本次任务中完成诊断和修复，用 `resolve` 固化稳定问题族与 `verified` 方案，再运行 `closure-check`。已知方案复用成功后同样运行 `closure-check`。
- 从本版本开始，新捕获的真实故障不能以零散 `unclassified` 事件结束任务。根因尚未确认时，先继续取证并按可直接观察的 `operation + failure_phase + error_class` 定义问题族；仍然不能确认时，任务保持未完成并说明实际阻断，不得编造根因或伪造方案。历史未分类记录不批量猜测；再次出现时按本规则闭环。
- `closure-check` 只有在事件已进入稳定问题族、绑定唯一 `status=verified` 的方案、本次事件状态为 `verified/promoted` 且具有实际效果验证时才通过。复用失败、方案回归、守卫不满足或只有候选族时都不能通过交付门。
- 当前权威目录只收录现有证据能够确定的 7 个问题族。新族可先按可观察失败类型定义，根因和方案仍需实际诊断、执行与验证；不得按设计清单凑数。

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

真实故障揭示本地能力缺口时，将症状、最小复现、已验证边界和验证需求交给 `global.skill-ecosystem-governor` 的 Skill 候选池。候选搜索、外部优劣比较和采用审批由 governor 协调对应 owner；普通搜集不创建 incident，也不由故障层自动改写专业规则。

缺失依赖且安装目标明确时，先在当前环境安装并验证，再重试原路线；安装失败是新证据，不能循环同一命令。只有安装不可行、映射不明或高风险时才提出降级路线。外部平台或版本结论先查官方资料，再做本地回归；不可访问或冲突则保留临时候选。

永久写回遵循 `improvement-routing.json` 的唯一负责人和风险策略。`domain_semantics=true`、数据写入、研究/搜索语义与不可逆动作必须走完整效果合同和回归；修改前保留可恢复原内容，失败即恢复并登记，不能记成功。

schema v2 只读兼容，写入前必须显式运行 `migrate-v3 --dry-run`，核对旧 ID、发生次数和复用计数守恒后再 `--apply`。迁移必须保留同目录字节备份；普通查询和捕获不得隐式迁移。

交付前仅在本轮事件变化时查询候选。确认正常快路径未改写事故库、组件级预检没有强制复用，并对本轮每个真实故障的事件 ID 运行 `closure-check`；任一返回 43 时继续处理，不能提交完成结论。每个真实事故还要有对应回执，且受影响 owner 测试通过。用 resolver 调用脚本：`skillctl.py run global.collect-bug-update-accelerate -- incident_registry.py ...`。常用命令为 `migrate-v3`、`refresh-catalog`、`family-report`、`classification-report`、`preflight`、`capture-event`、`resolve`、`reuse-result` 和 `closure-check`。canonical `SKILL.md` 与直接参考是唯一规则权威。
