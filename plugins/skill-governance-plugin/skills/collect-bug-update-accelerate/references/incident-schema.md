# 故障注册表字段与命令合同

## schema v3：事件、问题族、方案

现行注册表只使用 schema v3。顶层固定包含 `events[]`、`problem_families[]` 和 `solutions[]`：事件记录实际发生了什么，问题族描述可重复识别的失败机制，方案保存可复用步骤与验证合同。不得再用“组件名 + 症状文本”直接决定强制复用。

问题族按以下顺序识别：显式 `family_id` → `operation + failure_phase + error_class` 结构化精确命中 → 目录中的确定性特征规则 → 候选列表 → `unclassified.<component>.<hash>`。环境不参与问题族身份，只参与方案的 `applicability_guard`。

强制复用必须同时满足：问题族唯一、该族恰有一个 `status=verified` 的方案、实际环境通过守卫。只有组件时，`preflight` 返回候选族且 `reuse_required=false`；未分类、候选冲突、守卫失败或多个有效方案都不得返回退出码 42。

## 三类记录

### 事件 `events[]`

事件至少保留：`event_id`、`legacy_id`、`component`、`symptom_signature`、`family_id`、分类置信类型、候选族、方案引用、根因、诊断证据、验证证据、环境、首末时间、发生次数、状态、来源范围和 owner。未分类事件的 `solution_id` 必须为空。

同一组件、标准化症状和环境生成稳定事件 ID。再次捕获只增加发生次数并更新时间；不得覆盖已经确认的根因或方案。环境变化保留为不同事件，避免把回归写成同一成功事实。

### 问题族 `problem_families[]`

问题族至少保留：`family_id`、规范组件、`operation`、`failure_phase`、`error_class`、方案 ID 列表和 owner。新增问题族必须有结构化三元组；不能只把一条症状换个名字当成问题族。

权威目录只登记有直接证据的问题族。目录暂未覆盖的故障保持未分类，或在实际解决后通过 v3 `resolve` 建立本地问题族。不得为了提高覆盖率猜测分类。

### 方案 `solutions[]`

方案至少保留：`solution_id`、`family_id`、`catalog_source`、步骤、适用守卫、禁止路线、验证合同、效果合同、质量守卫、状态、owner，以及复用成功数和失败数。涉及领域语义的方案还必须保存可执行的回归测试。

权威目录中的方案在运行库里只保存 `catalog_source=builtin` 的轻量引用和本地计数，不复制步骤、守卫或合同正文。运行时先解析权威引用，再执行预检和复用登记。本地实际解决形成的方案使用 `catalog_source=local`，正文只保存一份。

复用失败只回归实际命中的方案，不改同族其他方案，也不改写事件事实。复用成功必须再次核对实际环境、等效效果、清理状态、禁止副作用和禁止降档路线。

## 迁移与 v2 边界

`migrate-v3 --dry-run` 先按完整 schema v2 合同校验源库，再生成计划、预览和守恒报告，不修改源库。`--apply` 前重新比较源字节 SHA-256，随后生成同目录 `.v2-<timestamp>.bak` 字节备份，原子写入并重新验证。守恒项包括旧 ID、发生次数、复用成功数和复用失败数；任一不一致即拒绝写入并恢复原文件。

schema v2 只保留读取、校验和显式迁移。`capture`、`capture-event`、`reuse-result`、`record`、`resolve`、`promotion-result` 和 `refresh-catalog` 对 v2 统一返回 `migration-required`，不得隐式迁移或继续写入。旧 `incidents[]` 字段只用于迁移识别，不再定义现行复用身份。

## 现行命令

### 校验与迁移

```powershell
python scripts/incident_registry.py validate --registry <registry.json>
python scripts/incident_registry.py migrate-v3 --registry <registry.json> --dry-run --report <report.json> --preview <preview.json>
python scripts/incident_registry.py migrate-v3 --registry <registry.json> --apply --report <report.json>
python scripts/incident_registry.py refresh-catalog --registry <registry.json>
```

`refresh-catalog` 只执行源码中明确声明的问题族 ID 别名迁移，同时更新事件、候选族和方案引用。命令在锁内读取原始 JSON，变更前生成 `.pre-refresh-catalog-<timestamp>.bak` 字节备份，再原子写入并执行 v3 全量校验；没有声明的 ID 不会被猜测或改名。

### 匹配、预检与捕获

```powershell
python scripts/incident_registry.py match --registry <registry.json> --component <component> --symptom <text> --operation <operation> --failure-phase <phase> --error-class <class>
python scripts/incident_registry.py preflight --registry <registry.json> --component <component> --family-id <family-id> --environment os=windows --environment shell=pwsh-7
python -X utf8 scripts/incident_registry.py capture-event --registry <registry.json> --component <component> --symptom <stable-signature> --environment os=windows
```

`preflight` 只有在唯一方案与环境守卫均通过时返回 42。调用方必须执行该方案并登记复用结果。捕获无已验证方案时返回 `resolve_required=true` 和退出码 43；调用方必须继续诊断、修复、验证和固化，不能把 43 当成新的事故递归捕获。根因未知时暂时保持 `unconfirmed`，但新故障不能以未分类状态结束任务。

### 固化新问题族与方案

```powershell
python -X utf8 scripts/incident_registry.py resolve `
  --registry <registry.json> --incident-id <event-id> `
  --family-id <family-id> --solution-id <solution-id> `
  --family-title <title> --operation <operation> `
  --failure-phase <phase> --error-class <class> `
  --root-cause <confirmed-cause> --diagnosis-evidence <evidence> `
  --solution <first-step> --solution-title <title> `
  --applicability-guard '{"os":["windows"]}' `
  --verification-contract <contract> `
  --effect-contract '{"expected_effect":"...","forbidden_side_effects":[],"domain_semantics":false}' `
  --verification <executed-evidence> --preferred-route <route>
```

新问题族必须提供结构化三元组。方案至少有一个实际执行步骤、适用守卫、效果合同和非空验证证据。`resolve` 会把事件绑定到该问题族和方案，并允许后续事件通过显式族或结构化三元组复用。

当效果合同中的 `domain_semantics=true` 时，还必须提供 `--regression-test <executable-check>`。缺少回归测试的领域语义方案不能进入 `verified`，也不会成为强制复用候选。

### 登记复用结果

```powershell
python scripts/incident_registry.py reuse-result `
  --registry <registry.json> --incident-id <event-id> `
  --outcome success --effect-verified --cleanup-complete `
  --environment os=windows --environment shell=pwsh-7 `
  --verification <evidence>
```

成功必须同时满足环境守卫、效果验证、非空证据、清理完成，且未命中效果合同或质量守卫中的禁止路线。成功会把本次事件标记为 `verified` 并写入实际验证证据；失败会增加该方案的回归次数并标记 `regressed`，事件仍未闭环。

### 故障闭环门

```powershell
python scripts/incident_registry.py closure-check --registry <registry.json> --incident-id <event-id>
```

只有事件已归入稳定问题族、绑定 `status=verified` 的方案、事件状态为 `verified/promoted`，并保存了本次实际效果验证时，命令才返回 0。未分类、缺少方案、方案回归或本次验证缺失时返回 43。交付前对本轮每个真实故障的事件 ID 执行该命令。

### 报告、重试门与晋升

```powershell
python scripts/incident_registry.py family-report --registry <registry.json>
python scripts/incident_registry.py classification-report --registry <registry.json>
python scripts/incident_registry.py scan-fragments --registry <registry.json>
python scripts/incident_registry.py retry-check --registry <registry.json> --incident-id <event-id> --route <route> --parameters-json '{}'
python scripts/incident_registry.py promotion-candidates --registry <registry.json>
python scripts/promotion_audit.py --registry <registry.json> --routing references/improvement-routing.json --ecosystem-registry <ecosystem-registry.json>
```

只有 `catalog_source=local`、状态为 `verified` 且绑定了已验证事件的方案，才进入 v3 晋升候选。权威目录引用已经是公共方案，不在本地重复晋升。晋升结果绑定实际方案；完整路线要求效果合同，轻量路线仍要求验证证据、复核定位和清理完成。

## 规范组件名与敏感信息

`canonical_component()` 统一分隔符、大小写和已登记同义名。新增同义碎片时先补规范映射，再处理存量冲突，不能人工逐条改名。

注册表递归拒绝 token、authorization、cookie、password、secret、credential、clipboard、conversation 等敏感字段。错误证据只保留定位所需的最短片段；不得把敏感值塞进普通字段规避检查。
