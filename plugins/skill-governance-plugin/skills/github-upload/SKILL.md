---
name: github-upload
description: Use when preparing local Skills for GitHub by creating a privacy-clean copy, adding public README and dependency guidance, auditing the package, or publishing it after explicit confirmation.
---

# github-upload：本地 Skill 公开打包

把用户本轮授权的本地 Skill 整理成可直接检查和上传的公开副本。普通任务默认采用轻量模式：只去除关键个人隐私和本机耦合，保留作者偏好、专业规则和领域内容；只有用户明确指出的研究词才通用化。

## 模式

- **轻量模式（默认）**：单个或少量 Skill，需要干净副本、README、使用说明和依赖说明。只读取源 `SKILL.md`、它直接引用的包内文件以及实际依赖文件。
- **治理模式（按需）**：用户要求完整发布审计、多 Skill 依赖闭合、冗余裁决、Git 历史清理或正式发布门禁时，读取 [发布合同](references/release-contract.md)、[通用化与冗余](references/generalization-and-redundancy.md) 并沿用 `build → audit → validate`。

包将离开本机时读取 [隐私策略](references/privacy-and-secret-policy.md)。需要补充公开文档时读取 [文档说明](references/documentation-and-integrations.md)。只有用户要求实际上传时读取 [GitHub 发布](references/github-publishing.md)。

## 轻量工作流

1. 确认本轮源 Skill 和输出目录；源目录保持只读，所有修改在隔离副本中完成。
2. 默认保留全部语义文件、专业规则、质量阈值、领域偏好和示例。自动排除 `.git`、缓存、日志、备份、`.env*`、运行数据库和 `node_modules`。
3. 自动替换可识别的密钥、真实邮箱和用户目录绝对路径。额外研究关键词只按用户明确提供的 `redactions` 替换，不自行猜测研究方向。
4. 运行 `prepare`。它会生成或保留 README、生成依赖说明、写入清单，并执行一次集中隐私审计。
5. 检查 `audit-report.json`。有阻断项就只修复副本并重跑；通过时将目录标记为本地已准备，不声称已经允许远程发布。

```powershell
python -X utf8 scripts/release_tool.py prepare --source <skill-dir> --output <release-dir>
```

需要替换用户明确指定的敏感研究词时，使用可选配置：

```powershell
python -X utf8 scripts/release_tool.py prepare --source <skill-dir> --profile <release-profile.json> --output <release-dir>
```

最小配置示例：

```json
{
  "package_name": "public-skill-name",
  "redactions": [
    {"find": "private research phrase", "replace": "<YOUR_TOPIC>"}
  ]
}
```

`release-manifest.json` 只记录源目录名称、公开文件哈希、排除项和各类替换数量，不记录源绝对路径或被替换的原始私密值。`local_prepared: true` 仅表示本地基础审计通过；`ready_for_remote` 始终为 `false`。

## README 与依赖

若源包已有 README，保留并净化它；否则生成简洁 README，至少说明用途、安装、调用方式、配置、依赖入口和隐私提醒。`REQUIREMENTS.md` 根据实际文件记录 Python 源文件、待人工映射的第三方 import、Node 清单和发布配置声明的必要集成；它是轻量提示，不能把 import 名直接宣称为可安装包名。

检测到浏览器、Zotero、Codex、Obsidian 联动时，这四端必须作为复现前提逐项写入 README：准确软件版本或验证范围、需要安装的插件/扩展、权限、连接配置、输入输出位置、四端数据流，以及一个从浏览器采集到 Zotero、由 Codex 处理并写入 Obsidian 的最小端到端验证。具体名称必须来自源 Skill 或当前验证结果，不能猜测。可在发布配置的 `required_integrations` 中声明必要软件；这不会替代 README 中的实际安装与联调说明。

不要为未检测到的集成生成冗长章节，也不要声称未验证的平台或版本受支持。

## 远程发布边界

准备本地副本不代表授权创建仓库、提交、推送或建立 PR。用户明确要求上传后，才读取 GitHub 发布参考并确认账号/组织、仓库、可见性、分支、目标目录、许可证和当前差异。包内容变化后重新确认。

## 工具维护

若本 Skill 的维护改动落在生态注册表中的 canonical 组件，完成前必须交由 `skill-ecosystem-governor` 同步该组件的完整指南、总览 source marker 和生态锁，并通过组件级及全量审计。普通 `prepare` 只写隔离副本，不触发这项移交。

修改脚本后运行：

```powershell
python -X utf8 -m unittest discover -s tests -v
```

测试位于 `tests/test_release_tool.py`。现有 `build`、`audit`、`validate` 是治理模式兼容接口，不得用轻量入口绕过其发布确认门禁。
