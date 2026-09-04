# Codex Research Skills

面向文献调研和演示文稿制作的可复用 Codex Skills。仓库提供工作流、接口约定和质量检查思路；使用者需要结合自己的课题、资料来源和本地工具完成配置。

> 本仓库不是开箱即用的研究结论或预置检索库。尤其是文献调研类 Skill，使用前应自行补充研究主题、检索词、来源优先级、筛选规则和输出目录，再以小规模样本验证流程。

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

## First-time configuration

1. 选择一个 Skill 并完整复制其目录，不能只复制 `SKILL.md`。
2. 在 Skill 的 README 和配置中填入自己的研究主题、任务目标和工作目录。不同领域的检索词、来源范围、筛选标准与质量门槛应由使用者自行确定。
3. 用 1–3 篇文献或一份短材料完成一次最小验证，再扩展到完整论文库或正式演示文稿。

## Browser · Zotero · Codex · Obsidian 联动

`drone-literature-scout` 使用的是可追溯的文献整理链路，而不是替代 Zotero 或 Obsidian。

1. 在 Chrome 或 Edge 安装 **Zotero Connector**，将用户确认的论文页面保存到 Zotero。
2. 在 Zotero Desktop 中核对父条目、元数据和 PDF 附件；仅在本机启用本地 API，且不要把 Web API Key 写入仓库。
3. 将 Skill 安装到 Codex 后，由 Codex 读取用户授权的工作目录和 Zotero 条目/附件信息，生成筛选记录、分析结果或 Markdown 草稿。默认读取不等于允许修改 Zotero。
4. 在 Obsidian 安装社区插件 **Zotero Integration**，为目标 Vault 配置导入模板。该插件负责把 Zotero 信息插入当前光标位置；它不会自动选择笔记文件，也不会替你生成已经核验过的 PDF 链接。
5. 将 Codex 生成的 Markdown 写入用户指定的 Vault 相对路径；只有确认 Zotero 中存在真实 PDF 附件 key 后，才写入对应的 `zotero://open-pdf/...` 阅读链接。最后在 Obsidian 中打开该链接，确认它指向同一份 PDF。

这四端的安装要求、权限边界与更细的操作说明见 [drone-literature-scout README](skills/drone-literature-scout/README.md)。

## Configuration and privacy

- Replace placeholders such as `<YOUR_RESEARCH_TOPIC>` and `<YOUR_APPLICATION_TASK>`.
- Treat the included workflow as a starting point: adapt search terms, source scope, screening criteria, and output conventions to your own use case.
- Keep API keys, OAuth tokens, Zotero identifiers, vault paths, and account credentials outside Git.
- Local research corpora, runtime databases, logs, caches, Git histories, and mathematical-modeling workflows are not included.
- The first release intentionally excludes the site-specific `searching-at-scale` implementation; users should add a search backend and keywords for their own domain.

## Attribution and license

This collection is released under MIT except where a component carries its own
license notice. `codex-ppt` is derived from
[`ningzimu/codex-ppt-skill`](https://github.com/ningzimu/codex-ppt-skill) and
retains the upstream copyright and MIT license in its own folder.

See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
