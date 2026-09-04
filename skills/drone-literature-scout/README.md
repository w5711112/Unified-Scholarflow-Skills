# drone-literature-scout

用于组织无人机相关文献的检索、核验、筛选和总结流程。本 Skill 提供证据链与文件结构，不附带任何个人论文库、研究结论或可直接复用的检索配置；使用前需要结合自己的课题补充检索词、来源范围、筛选条件和工作目录。

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

## 最小联调流程

1. 在 Chrome 或 Edge 中通过 **Zotero Connector** 保存一篇论文；只处理自己允许访问的来源。
2. 打开 Zotero Desktop，确认该条目具有正确的父条目和 PDF 子附件。浏览器快照或网页条目不等同于 PDF 附件。
3. 在 Codex 中说明自己的主题、工作目录和要做的任务。Codex 默认只读取 Zotero 本地 API 返回的条目与附件信息，不直接读取 `zotero.sqlite`，也不会把读取成功当作已经修改 Zotero。
4. 让 Codex 在用户指定的 Vault 相对路径生成 Markdown。需要从 Zotero 插入引文时，在 Obsidian 中用 **Zotero Integration** 的模板导入到当前光标位置；该插件不会自动定位笔记文件。
5. 只有确认 PDF 附件 key 存在后，才使用 `zotero://open-pdf/library/items/<attachment-key>` 链接。在 Obsidian 中打开链接，确认它指向刚才核验过的同一份 PDF。

Zotero 元数据写入或批量修改必须先由 Codex 给出 dry-run 差异，再由用户明确确认并在 Zotero 中执行；完成后重新读取本地 API 验证结果。

## Configuration

Replace public placeholders such as `<YOUR_VALUE>` with settings for your own environment. Before a full run, define your own topic, search terms, source scope, screening criteria, output folder, and acceptance standard. Keep credentials outside the repository.

## Privacy

This package was prepared from an isolated copy. Run the included release audit again after changing local paths, identifiers, or credentials.
