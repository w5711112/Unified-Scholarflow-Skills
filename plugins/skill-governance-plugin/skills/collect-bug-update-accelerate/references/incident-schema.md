# 故障注册表字段合同

## 目录

- 数据位置
- 顶层结构
- 事件字段
- 指纹与去重
- 敏感信息边界
- 命令接口

## 数据位置

项目运行库固定为：

```text
skill-with-plugin/运行数据/collect-bug-update-accelerate/incident-registry.json
```

它是运行数据，不与 `SKILL.md` 镜像，也不复制到其他 Vault 知识笔记。

## 顶层结构

```json
{
  "schema_version": 2,
  "updated_at": "2026-07-29T10:00:00+08:00",
  "incidents": []
}
```

UTF-8、LF、JSON；通过单写者锁、同目录临时文件与 `os.replace` 原子更新。schema v1 在读入时无损、幂等迁移为 v2；正常成功路径不写本文件。
轻量模式不新增事件字段；事件库继续使用 schema v2，风险策略只存在于 `improvement-routing.json`。

## 事件字段

| 字段 | 含义 | 门槛 |
| --- | --- | --- |
| `id` | 组件、标准化症状、完整环境对象的稳定 SHA-256 指纹 | 唯一且必须由脚本生成 |
| `slug` | 可选的人类可读别名 | 不参与去重，不可替代 `id` |
| `component` | 出错组件 | 使用稳定名称 |
| `symptom_signature` | 去除 UUID、时间戳、行号等波动值的症状 | 不写整份日志 |
| `root_cause` | 证据确认的根因 | 未确认时直写 `unconfirmed` |
| `known_good_solution` | 最小成功解法 | 猜测不能写成已知可用 |
| `verification` | 命令、状态或结果证据 | `verified` 必填 |
| `forbidden_retries` | 已失败的路线与规范化参数 | 同组合不得重试 |
| `preferred_route` | 下次首选路线 | 优先后台 |
| `environment` | OS、工具、应用、解释器与版本 | 用于匹配 |
| `first_seen` / `last_seen` | 首次与最近发生时间 | ISO 8601 |
| `occurrences` | 同指纹出现次数 | 正整数 |
| `status` | `observed` / `diagnosed` / `verified` / `promoted` / `regressed` / `retired` | 证据驱动 |
| `source_scope` | `current-task` / `same-project-history` / `runtime-discovery` | 不复制聊天正文 |
| `owner_skill` | 唯一负责固化该经验的 Skill | 未知组件先归本 Skill |
| `effect_contract` | 预期效果与禁止副作用；可为 `null` | 高风险永久晋升必填；轻量晋升可为 `null` |
| `quality_guard` | 质量下限守卫：`preserve_output_fidelity`（必须保持的输出保真度）与 `forbidden_downgrade_routes`（禁止退回的低档路线列表）；可为 `null` | 方案改变路线档位或涉及领域语义时必填；`reuse-result` 会把 `forbidden_downgrade_routes` 并入禁止副作用检查 |
| `diagnosis_evidence` | 根因定位所需的最小证据 | 不复制完整堆栈 |
| `reuse_success_count` / `reuse_failure_count` | 已验证复用结果 | 非负整数 |
| `promotion` | `none` / `eligible` / `applied` / `rolled_back` | 不与 `status` 混用 |
| `regression_test` | 防复发测试或轻量效果复核定位 | 候选时可为 `null`；写回永久结果时必填 |
| `last_verified_environment` | 最近通过效果验证的环境 | 可为 `null` |

## 指纹与去重

- 症状标准化时消除 UUID、时间戳、行号和明确的临时运行编号；保留错误码、版本、阈值等有语义数字，避免把不同故障错误合并
- 指纹只使用稳定组件、标准化症状和排序后的完整 `environment` 对象
- 输入已有 `id` 时也必须与脚本计算值完全一致；手写可读名放进可选 `slug`
- 相同指纹执行 upsert：保留 `first_seen`，刷新 `last_seen`，增加 `occurrences`
- `verified` 再次失败时显式改为 `regressed`；禁止退回 `observed`
- 工具或版本发生实质变化时保留环境差异，不把回归覆盖成同一成功事实

## 质量档位规则（不得降挡）

`verified`/`promoted` 方案的输出质量档不得低于被替代的原路线。若已知方案只有降档路线（如视觉模型直接读图 → 文本模型 OCR 后读图），该方案**不得标记为 `verified`**，只能记 `observed` 并明确其为非永久降级。需要记录"必须保持的输出质量下限"与"禁止退回的低档路线"时，用 `quality_guard` 字段：

```json
"quality_guard": {
  "preserve_output_fidelity": "必须直接视觉读取图像，不得退回 OCR",
  "forbidden_downgrade_routes": ["ocr-downgrade", "text-ocr-then-read"]
}
```

`reuse-result` 记复用成功时，会把 `quality_guard.forbidden_downgrade_routes` 并入禁止副作用检查：本次复用若走了任一低档路线，成功被拒绝并给出证据。这保证"通过"不仅是"有输出"，而是"输出质量不降档"。

## 敏感信息边界

注册表递归拒绝包含以下含义的字段名：

- token、authorization、cookie、password、secret、credential；
- clipboard、conversation；
- 同义大小写和下划线变体。

不要把敏感值塞进普通字段规避检查。错误证据只保留定位所需的最短片段；路径可保留到组件或项目层，随机临时目录应标准化。

## 命令接口

### 轻量触发规则

- 普通成功流程不调用脚本、不写注册表。
- 已知脆弱组件或本轮已经失败时才调用 `preflight`。
- 任意异常、非零退出、权限拒绝、结果缺失或验证失败调用 `capture`。
- 一个真实故障一次成功解决并验证后即成为临时候选；临时候选本身就是可复用方案，不再以复用次数作为候选门槛。复用解法后仍调用 `reuse-result` 记录回归；只有注册表本轮变化时查询 `promotion-candidates`。
- 退出码为 0 不能单独证明效果等价。

### 迁移与校验

```powershell
python scripts/incident_registry.py migrate --registry <registry.json>
```

### 校验

```powershell
python scripts/incident_registry.py validate --registry <registry.json>
```

### 查询

```powershell
python scripts/incident_registry.py match --registry <registry.json> --component <component> --symptom <text> --environment os=windows
```

`--symptom ""` 可列出同组件候选，随后必须按环境和实际症状复核。

### 按组件预检

```powershell
python scripts/incident_registry.py preflight --registry <registry.json> --component <component> --environment os=windows
```

无匹配时返回 `continue-without-runtime-write`，且文件字节不变。

### 捕获报错

```powershell
python scripts/incident_registry.py capture --registry <registry.json> --incident-file <one-incident.json>
```

匹配已验证事件时保留原解法和状态，只增加复发元数据并返回首选路线。

### 登记复用结果

```powershell
python scripts/incident_registry.py reuse-result --registry <registry.json> --incident-id <id> --outcome success --effect-verified --verification <evidence> --cleanup-complete
```

成功必须同时满足效果验证、非空证据、清理完成且没有命中禁止副作用；失败会增加回归次数并标记 `regressed`。

### 查询传播候选

```powershell
python scripts/incident_registry.py promotion-candidates --registry <registry.json>
```

该命令只读；`status=verified`、`promotion=none` 且成功方案与验证证据均非占位值时立即返回临时候选。`occurrences` 与 `reuse_success_count` 不再作为候选门槛。

候选非空时才加载唯一的只读晋升审计：

```powershell
python scripts/promotion_audit.py --registry <registry.json> --routing references/improvement-routing.json --ecosystem-registry <ecosystem-registry.json>
```

审计输出 `reusable_now`、`promotion_policy`、候选阶段、唯一归属、证据路线、canonical/mirror 路径、复核要求与是否允许自动固化。`promotion_policy=lightweight` 的低风险问题不预先要求完整效果合同或测试文件；依赖外部平台或版本时仍必须查官方资料并做本地效果复核。`full` 路线继续要求完整效果合同和回归测试。审计不修改 Skill，也不在正常成功路径运行。

### 写回永久修复结果

轻量路线仅用于审计明确标记为低风险的候选：

```powershell
python scripts/incident_registry.py promotion-result --lightweight --registry <registry.json> --incident-id <id> --outcome applied --verification <evidence> --regression-test <recheck> --cleanup-complete
```

完整路线保持原命令：

```powershell
python scripts/incident_registry.py promotion-result --registry <registry.json> --incident-id <id> --outcome applied --verification <evidence> --regression-test <test-path> --cleanup-complete
```

`--lightweight` 只放宽预先存在完整 `effect_contract` 的要求，仍强制验证证据、复核定位和清理完成；轻量模式不新增事件字段。默认模式继续要求 `effect_contract.expected_effect` 和完整回归测试。修改失败时先恢复原内容，再用 `--outcome rolled-back` 写为 `status=verified`、`promotion=rolled_back`。

### 记录

```powershell
python scripts/incident_registry.py record --registry <registry.json> --incident-file <one-incident.json>
```

命令输出必须是本次新增或更新的精确记录，而不是注册表数组末项。

### 重试门

```powershell
python scripts/incident_registry.py retry-check --registry <registry.json> --incident-id <id> --route <route> --parameters-json "{}"
```

### 将已观察事件升级为已验证

```powershell
python scripts/incident_registry.py resolve --registry <registry.json> --incident-id <id> --solution <solution> --verification <evidence> --preferred-route <route>
```

升级前必须已经执行并验证解法；不得用“理论上可行”作为验证证据。

## 规范组件名

同一底层问题必须使用同一规范组件名，否则精确组件匹配会断链。`incident_registry.py` 的 `canonical_component()` 集中执行两级归一：先把 `.`、`_`、`:`、`/`、空格等分隔符转成 `-` 并小写，再使用 `COMPONENT_CANONICAL` 与 `COMPONENT_PREFIX_CANONICAL` 合并同一问题族。捕获时自动归一并按规范名计算指纹；查询时同时归一查询名与库存名称。发现新的同义碎片族时，先补显式映射，再对存量库重算 ID 并处理冲突，不能人工逐条改名。

当前已登记族包括：`python-dependency`、`pdf-render`、`pdf-contact-sheet`、`office-docx-render`、`skill-creator-quick-validate`、`matplotlib-font-cache`、`apply-patch`、`apply-patch-windows-split-root-sandbox`、`view-image`、`view-image-windows-split-root-sandbox`、`shell-command`、`ripgrep`、`git`、`windows-sandbox-visibility`、`codex-thread-api`、`web-run`、`web-open`、`web-search`、`web-arxiv-fetch`、`powershell`、`unittest`、`sandbox-escalation-review`、`plugin-creator-validate`、`firecrawl-web-script`、`search-timeline-renderer`、`functions-exec-output`。未登记组件只做机械拼写归一，不猜测语义改名。

## 捕获、回执与强制复用合同

普通最小事件优先直接运行：

```powershell
python -X utf8 "<INCIDENT_SCRIPT>" capture-event --registry "<LOCAL_REGISTRY>" --component zotero-run-js --symptom "stable error signature" --environment os=windows --route "changed-background-route" --notice-summary "Zotero 无法执行内部脚本"
```

- 摘要至少包含一个汉字；整条回执包括 `【】` 最多 96 个字符，不用省略号截断半句话。缺少合格摘要时使用本地中文分类，无法分类时使用“工具执行失败，详细原因已写入故障库”。分类只读组件和症状，不联网、不新增字段。
- 捕获成功后，把 `conversation_notice` 嵌入下一条自然进度 commentary，格式为 `【发现故障：<中文问题摘要>，已记录】`；捕获失败只能写 `【发现故障：<中文问题摘要>，尚未记录】`。二者均不得作为单独消息发送。
- `capture-event` 先匹配既有记录。匹配 `verified` 时保留原解法与状态，只增加复发元数据，返回 `action=use-verified-solution` 和退出码 **42（REUSE_REQUIRED）**；任何调用方不得吞掉 42。
- 命中后不得当新故障从头解决；唯一合法后续是执行 `preferred_route`、启用 `forbidden_retries` 和 `quality_guard`，再运行 `reuse-result`。成功回执格式为 `【故障的解决方案复用成功：xx方法解决xx问题】`，失败使用同结构的“复用失败”。
- 无已验证方案时返回 `action=recorded-observation`、`resolve_required=true`；本轮实际解决后必须 `resolve`。根因未知时保持 `unconfirmed`/`observed`。
- `reuse-result --outcome success` 要求 `effect_verified`、非空 `verification`、`cleanup_complete`、非空效果合同且未命中禁止副作用或降档路线；失败增加 `reuse_failure_count` 并标 `regressed`。复用失败完成登记后，才允许重新捕获并诊断。

## 事件变化与候选合同

一次成功解决并通过效果验证即可成为 `verified` 临时候选；候选没有 `occurrences` 或 `reuse_success_count` 门槛。仅新增成功解法、复用结果或回归状态算“本轮事件变化”。只有变化后才查询候选，且候选非空才运行晋升审计。

轻量永久化仍需保存可恢复原内容、实际验证、效果复核定位和清理；完整永久化还需完整 `effect_contract` 与回归测试。失败时先恢复，再登记 `promotion=rolled_back`。`status` 和 `promotion` 是两个独立状态机，不得混写。
