<!-- BEGIN COLLECT-BUG-UPDATE-ACCELERATE -->
## Project incident acceleration guard

This guard applies only to Codex tasks rooted in this approved project; ordinary ChatGPT chats, projectless tasks, and other projects are excluded.

- Normal success: do not query or write any registry.
- Known fragile route: preflight local first, then public read-only.
- Real failure: capture-event before changing route.
- Missing dependency: when package identity and the active environment are explicit, install and verify it before retrying the original route; do not bypass it.
- Successful capture: append conversation_notice once inside the next natural progress commentary; never send a standalone incident message.
- Conversation notice stays brief; event id, status, and route remain in the registry only.
- Conversation summary: the whole notice including brackets is at most 96 characters, contains Chinese, and is never ellipsis-truncated; legacy calls use the local Chinese classifier.
- Repeated failure: reuse the incident id internally and append a fresh brief notice.
- Capture failure: append a brief not-recorded note inside natural progress commentary; never claim success.
- Never send cross-task messages solely to announce guard or notice changes.
- No network translation, daemon, watcher, or registry field is authorized.
- Never repeat the same failed route and parameters unchanged.
- Verified resolution: one successful effect-verified solution is an immediate temporary candidate; no occurrence or reuse threshold.
- Candidate review: after a new solution, reuse result, or regression, query promotion-candidates; load promotion_audit.py only when nonempty.
- Before final answer: backfill every unrecorded failed/declined/nonzero/validation item.
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
<!-- END COLLECT-BUG-UPDATE-ACCELERATE -->
