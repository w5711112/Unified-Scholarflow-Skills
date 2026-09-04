# Codex Research Skills

A small public collection of reusable Codex Skills for drone literature review and PowerPoint production. The repository contains architecture and operating instructions, while each user supplies their own research topic, local paths, accounts, credentials, and tool configuration.

## Included Skills

| Skill | Purpose | Main prerequisites |
| --- | --- | --- |
| [drone-literature-scout](skills/drone-literature-scout/) | Search, screen, audit, and summarize drone literature | Browser, Zotero, Codex, Obsidian |
| [academic-native-ppt-design](skills/academic-native-ppt-design/) | Design editable academic PPTX decks | Codex, PowerPoint-compatible editor |
| [codex-ppt](skills/codex-ppt/) | Privacy-clean redistribution of the MIT-licensed upstream Skill by `ningzimu` | Codex, Python, image-generation provider, PowerPoint-compatible viewer |

## Installation

Clone the repository:

```powershell
git clone https://github.com/w5711112/codex-research-skills.git
```

Copy only the Skill you need into your Codex Skills directory, then start a new Codex task:

```powershell
Copy-Item -Recurse .\codex-research-skills\skills\drone-literature-scout "$env:USERPROFILE\.codex\skills\drone-literature-scout"
```

Read that Skill's `README.md`, `REQUIREMENTS.md`, and `SKILL.md` before use.

## Configuration and privacy

- Replace placeholders such as `<YOUR_RESEARCH_TOPIC>` and `<YOUR_APPLICATION_TASK>`.
- Keep API keys, OAuth tokens, Zotero identifiers, vault paths, and account credentials outside Git.
- Local research corpora, runtime databases, logs, caches, Git histories, and mathematical-modeling workflows are not included.
- The first release intentionally excludes the site-specific `searching-at-scale` implementation; users should add a search backend and keywords for their own domain.

## Attribution and license

This collection is released under MIT except where a component carries its own
license notice. `codex-ppt` is derived from
[`ningzimu/codex-ppt-skill`](https://github.com/ningzimu/codex-ppt-skill) and
retains the upstream copyright and MIT license in its own folder.

See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
