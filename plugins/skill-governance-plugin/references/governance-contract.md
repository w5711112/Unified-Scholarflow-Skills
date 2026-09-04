# Governance contract

This contract contains only enforceable invariants for the governance control plane.

## Authority and identity

- User-maintained authority roots must be declared explicitly in the registry. Managed runtime locations are derived state and never become Skill authority roots.
- Every component ID is unique among active records and maps to exactly one canonical path.
- A component path is resolved only as `roots[root_id].path / relative_path`; component records do not store absolute paths.
- Consumers are derived by reversing `requires`; a persisted consumer list is invalid.

## Versions and lifecycle

- `plugin.json.version`, the component release, `architecture-manifest.release_version`, and the latest changelog release must agree for one release.
- `interface_version` is an independent compatibility contract.
- Lifecycle values are `active`, `staging`, `quarantine`, and `retired`; only `active` records can be resolved.

## Integrity and runtime

- The aggregate Obsidian overview is a purpose-focused derived projection: it explains use, inputs, outputs, collaboration, and boundaries without duplicating the executable rulebook. Its generated block may change only through `sync-overview`.
- Each active Skill also has one read-only complete guide generated from canonical `SKILL.md` and `references/`. `sync-guides [component-id ...]` refreshes all or only named components and must not rewrite unaffected guides.
- Every active Skill appears exactly once in the overview and exactly once in the guide library with a reviewed source-tree hash. Missing, duplicate, unknown, stale, or unsynchronized entries are findings.
- The generated runtime lock records each resolved component and SHA-256 of its canonical content and dependency/runtime inputs.
- A lock is valid only when hashes and versions match current sources and the registry.

## Transactions and protected state

Migration and release order is: freeze source/hash/consumers/tests; copy to one staging path; register a candidate without changing active; verify content, behavior, providers, versions, overview, guides, and dependencies; update active references; atomically switch active; quarantine the old source; verify the new path; refresh the affected guide and, when its purpose contract changed, the affected overview section; then update lock and changelog and later propose cleanup.
- Failure leaves the previous active record and source intact and never leaves two active canonical sources.
- `.codex` state is protected: do not delete active databases, WAL files, plugin services, sessions, or installed system components.
- Direct source deletion is forbidden; cleanup is a separately authorized, reversible quarantine proposal.

## Failure-closed exclusions

Findings must fail closed on duplicate active IDs or paths, missing or cyclic providers, retired-path resolution, version or lock drift, overview or guide drift, unregistered local dependencies or caches, hash drift, simultaneous staging and active mutation, unavailable rollback, stale consumers, or expired verification evidence.

The architecture explicitly rejects a second registry, watcher, daemon, success ledger, persistent duplicate audit collection, and direct canonical-source deletion.
