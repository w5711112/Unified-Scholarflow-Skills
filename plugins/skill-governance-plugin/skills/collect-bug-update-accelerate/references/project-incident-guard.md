<!-- BEGIN COLLECT-BUG-UPDATE-ACCELERATE -->
## Project incident acceleration guard

捕获时优先提供 `family_id`，或提供 `operation`、`failure_phase`、`error_class` 三个结构化特征。只有自由文本时，只能用问题族目录中的确定性规则归类；字符串相似度只能给候选，不能触发复用。

只有组件名的预检用于列出候选问题族。没有唯一问题族、唯一已验证方案和通过的环境守卫时，不得宣称“已有方案必须复用”。未分类事件继续保存原始事实，并进入后续诊断，不为满足统计而强行合并。

schema v2 库先 dry-run，再核对守恒，最后逐库 apply。普通捕获、查询或复用回执不得顺带迁移。

This guard applies only to Codex tasks rooted in this approved project; ordinary ChatGPT chats, projectless tasks, and other projects are excluded.

- Normal success: do not query or write any registry.
- Known fragile route: preflight local first, then public read-only.
- Real failure: capture-event before changing route. Exit 43 means the recorded event is still open; continue diagnosis and do not record exit 43 as another incident.
- Missing dependency: when package identity and the active environment are explicit, install and verify it before retrying the original route; do not bypass it.
- Successful capture: append conversation_notice once inside the next natural progress commentary; never send a standalone incident message.
- Conversation notice stays brief; event id, status, and route remain in the registry only.
- Conversation summary: the whole notice including brackets is at most 96 characters, contains Chinese, and is never ellipsis-truncated; legacy calls use the local Chinese classifier.
- Repeated failure: reuse the incident id internally and append a fresh brief notice.
- Capture failure: append a brief not-recorded note inside natural progress commentary; never claim success.
- Never send cross-task messages solely to announce guard or notice changes.
- No network translation, daemon, watcher, or registry field is authorized.
- Never repeat the same failed route and parameters unchanged.
- Verified resolution: one successful effect-verified solution is an immediate temporary candidate; no occurrence or reuse threshold. Run `closure-check` for the event id before treating the failure as complete.
- Candidate review: after a new solution, reuse result, or regression, query promotion-candidates; load promotion_audit.py only when nonempty.
- Before final answer: backfill every unrecorded failed/declined/nonzero/validation item, then require `closure-check` success for every real failure captured in this task. Historical unclassified events are handled when reproduced; never mass-classify them without evidence.
- If inherited guards overlap, the deepest approved project root owns the local registry.

Use these canonical paths:

- Project root: `{PROJECT_ROOT}`
- Writable local registry: `{LOCAL_REGISTRY}`
- Read-only public registry: `{PUBLIC_REGISTRY}`
- Canonical incident CLI: `{SKILLCTL} run {INCIDENT_COMPONENT} -- {INCIDENT_SCRIPT}`

For a known fragile component, run preflight before the risky route:

`python -X utf8 "{SKILLCTL}" run {INCIDENT_COMPONENT} -- {INCIDENT_SCRIPT} preflight --registry "{LOCAL_REGISTRY}" --fallback-registry "{PUBLIC_REGISTRY}" --component "<component>"`

Immediately after a real failure, record the minimal event before diagnosing or changing route:

`python -X utf8 "{SKILLCTL}" run {INCIDENT_COMPONENT} -- {INCIDENT_SCRIPT} capture-event --registry "{LOCAL_REGISTRY}" --component "<component>" --symptom "<stable symptom>" --environment "os=windows" --route "<next changed route>" --notice-summary "<brief Chinese problem summary>"`

At final-answer time, scan this task's actual tool results and backfill only real missed failures. Expected TDD RED, deliberate probes, user cancellations, and normal success are not product incidents. No daemon, file watcher, or per-tool wrapper is authorized.

After `resolve` or successful `reuse-result`, close the event explicitly:

`python -X utf8 "{SKILLCTL}" run {INCIDENT_COMPONENT} -- {INCIDENT_SCRIPT} closure-check --registry "{LOCAL_REGISTRY}" --incident-id "<event-id>"`
<!-- END COLLECT-BUG-UPDATE-ACCELERATE -->
