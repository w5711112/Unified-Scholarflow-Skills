# drone-literature-scout

Use when searching, auditing, merging, summarizing, or periodically reviewing UAV/drone perception-control literature under strict official-source, single-UAV, compute, and deployment gates.

## Installation

Copy this directory into your Codex Skills directory, then start a new task.

## Usage

Invoke the Skill by name or describe a task that matches its description. Review `SKILL.md` for its operating rules.

## Requirements

See [REQUIREMENTS.md](REQUIREMENTS.md).

## Integration prerequisites

- Browser: Chrome or Edge with the official Zotero Connector extension; allow access only to literature sources you choose.
- Zotero: Zotero Desktop with its local API enabled. Keep Web API keys outside the repository.
- Codex: Codex with this Skill copied into the local Skills directory; grant access only to the selected working folder.
- Obsidian: Obsidian with the community plugin **Zotero Integration** installed and configured for the target vault.

Minimal data flow: capture a paper in the browser with Zotero Connector → confirm its parent item and PDF attachment in Zotero → ask Codex to audit and summarize it → write the checked note into Obsidian → verify the `zotero://open-pdf/...` link opens the same PDF. Zotero writes or metadata changes remain user-confirmed operations.

## Configuration

Replace public placeholders such as `<YOUR_VALUE>` with settings for your own environment. Keep credentials outside the repository.

## Privacy

This package was prepared from an isolated copy. Run the included release audit again after changing local paths, identifiers, or credentials.
