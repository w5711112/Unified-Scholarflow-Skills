---
name: skill-ecosystem-governor
description: Use when registering, migrating, releasing or auditing Skills, synchronizing guides, scheduling ecosystem maintenance, or reviewing third-party Skill candidates.
---

# Skill Ecosystem Governor

Resolve component IDs through the plugin's single ecosystem-registry.json. Use register-component for additions and bound run-lifecycle --event routes for incident promotion or release packaging; ordinary run is not a lifecycle transaction.

## Lifecycle

1. Resolve changed IDs and reverse consumers from requires; create one staging proposal.
2. Freeze sources and backup; run owner tests and affected consumer tests.
3. After authorization and green evidence, atomically switch active registry state.
4. Every canonical change, including another owner's edit, runs component-scoped sync-guides. Changed purpose, inputs, outputs, collaboration or boundaries also require reviewed overview role updates and sync-overview.
5. Run scoped audit of changed nodes, consumers, overview markers and guides, then full audit; regenerate the ecosystem lock only when green.
6. Hand superseded material to workspace-hygiene for reviewed, reversible retirement.

Return professional semantic judgment to its owner. Refuse direct deletion, a resident background watcher/daemon, a second registry and automatic changes to a running Skill. Failed lifecycle audits restore prior registry bytes and block lock publication. Clean audits create no success ledger.

Overview and complete guides are derived reading surfaces, never canonical. Scoped sync must leave unaffected guides untouched.

## Conditional routes

- Scheduled checks, catch-up or mirror/guide conflicts: read [maintenance](references/maintenance-contract.md). The approved finite runner is scripts/ecosystem_maintenance.py at the resolved governance plugin root; invoke with Python -B -X utf8, dry-run by default.
- Third-party discovery, candidate-pool comparison or review: read [candidate pool](references/candidate-pool-contract.md). Governor owns this capability; no new Skill. Searching-at-scale discovers sources, collect handles real failures, hygiene retires files.
- These routes never authorize automatic domain-rule adoption or untested release publication. Ordinary lifecycle work does not preload their references.
