# 薄型权威合同结构

本文件只说明 `schema_version: 3` 的记录结构，不定义任何任务要求。任务要求始终来自原始 `SKILL.md` 和强制参考。

## 1. 顶层字段

- `schema_version`：固定为 `3`；旧结构不得继续运行。
- `contract_authority`：固定为 `record_only`。
- `task.task_root`：本轮用户授权的当前任务根。
- `scope.authorized_roots[]`：允许访问的根及 `file`/`directory` 类型。
- `scope.exclusions[]`：明确禁止访问的路径。
- `sources[]`：已选 Skill 和强制参考的当前快照。
- `requirements[]`：从原文逐条定位的要求台账。
- `evidence[]`：当前证据回执。
- `gates[]`：`G0` 至 `G5` 的要求分组。
- `observed_paths[]`：本任务实际观察的路径，包括合同自身。
- `forward_audit`：交付前正向审计；非交付阶段可以为 `null`。

## 2. 来源快照

每个 `sources[]` 项包含：

- `id`、绝对 `path`、当前文件 `sha256`；
- `read_complete: true`；
- `mandatory_reference_ids[]`，用于证明强制参考已解析并分别作为来源完整读取。

来源路径必须在当前授权范围内，不能引用排除路径。文件不存在、没有读完、引用未知或哈希变化时，相关要求不能通过。

## 3. 原文要求

每个 `requirements[]` 项包含：

- `id`、`source_id`；
- `anchor.start_line`、`anchor.end_line`；
- `anchor.source_text` 和 `anchor.sha256`；
- `stage`；
- `applicability`：`applicable`、`not_applicable` 或 `pending`；
- `dependencies[]`；
- `evidence_ids[]`。

`non_authoritative_note` 可用于解释，但不得影响验证结果。每个要求必须恰好属于一个 gate；未知依赖、重复要求或虚构锚点均失败。

## 4. 证据回执

每个 `evidence[]` 项包含：

- `id`、`requirement_id`；
- `kind`：`automated_check`、`artifact_inspection`、`user_decision` 或 `negative_branch`；
- `source_sha256`；
- `target_path`、`target_sha256`；
- `record_path`、`record_sha256`；
- `result: pass`。

`negative_branch` 还包含：

- `fact_record_path`、`fact_record_sha256`；
- `inspection_record_path`、`inspection_record_sha256`。

中央锁只核对这些文件、哈希、范围和连接是否当前。证据记录中的专业结论必须由原始 Skill 规定的工作流产生，不能由中央锁或合同自创。

## 5. 门禁与正向审计

`gates[]` 按顺序包含 `G0` 至 `G5`。每个 gate 的 `requirement_ids[]` 与要求台账一一覆盖且不重复。

`forward_audit` 在交付阶段包含：

- `result: pass`；
- `record_path`、`record_sha256`；
- `source_sha256`：来源编号到当前哈希的完整映射；
- `artifact_sha256`：证据目标绝对路径到当前哈希的完整映射。

正向审计必须从原始来源逐条走到当前成果，用来发现台账遗漏。它不能新增要求或用旧成果哈希通过。

## 6. 状态推导

- `pending` 适用性永远不通过；
- `applicable` 要求只有在全部引用回执当前且通过时才验证完成；
- `not_applicable` 要求只有在存在当前 `negative_branch` 回执时才验证完成；
- 任一上游依赖未完成，下游保持待验证；
- 来源、目标或记录哈希变化后，旧回执失效。

合同不保存可支配权威的手填 `status`。测试、清单和报告的自报状态不能覆盖上述推导。
