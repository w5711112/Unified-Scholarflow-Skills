---
name: skill-ecosystem-governor
description: Use when registering, migrating, releasing, or auditing multiple user-maintained Skills and their dependency relationships.
---

# Skill Ecosystem Governor

Use the plugin's single `ecosystem-registry.json` and resolver. Never hard-code a provider path when a component ID exists.

For a lifecycle change:

Use `register-component` for registry additions. Run incident promotion and release packaging through their bound `run-lifecycle --event` route; it always audits the owning provider plus detected registry changes, while `--changed-component` adds any external target. Ordinary `run` is not a lifecycle transaction.

1. Resolve the changed component IDs and derive reverse consumers from `requires`.
2. Create one staging proposal; do not create parallel candidates or a second registry.
3. Run the changed providers' owner tests and the affected consumers' tests.
4. After explicit authorization and green evidence, atomically switch the active registry state.
5. For every registered canonical change, including one made through another owning Skill, run component-scoped `sync-guides`. If purpose, inputs, outputs, collaboration, or boundaries changed, update its overview role section and run `sync-overview`.
6. Run component-scoped `audit`; it must cover changed nodes, reverse consumers, their overview source markers, and complete guides. Run the full audit, then regenerate the ecosystem lock only after all are green.
7. Ask `workspace-hygiene` to propose retirement of superseded staging or rollback material; keep quarantine reversible.

Refuse professional semantic judgment, direct deletion, a background watcher or daemon, a second registry, and automatic changes to a running Skill. Return domain questions to the owning Skill. A clean audit writes no success ledger. A failed audit restores the prior registry bytes, blocks lock publication, and leaves the non-active candidate for reviewed quarantine.

The overview and complete guides are derived Obsidian reading surfaces, never canonical sources. Use `sync-overview` for the aggregate generated block and `sync-guides [component-id ...]` for full or component-scoped guide refresh. Component-scoped refresh must not rewrite unaffected guides.
