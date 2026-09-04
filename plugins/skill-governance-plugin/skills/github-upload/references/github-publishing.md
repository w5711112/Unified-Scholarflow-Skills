# GitHub 发布门禁

## 1. 远程确认对象

在任何远程写入前生成 `publication-confirmation.json`，并让用户确认当前值：

```json
{
  "repository": "OWNER/REPOSITORY",
  "visibility": "public",
  "branch": "main",
  "target_path": "skills/research-scout",
  "license": "MIT",
  "approved": true
}
```

还要展示：待发布文件树、删除/重命名清单、秘密审计摘要、功能守恒结果和最终 diff。`approved: true` 只能记录当前用户对当前包哈希的确认；包变化后必须重新确认。

## 2. 认证与仓库

优先使用已安装的 GitHub CLI 和 `gh auth status` 检查状态；需要登录时让用户通过 `gh auth login` 的交互流程完成，不索取 Token 文本。已有仓库先读取远程和默认分支；新仓库只有在用户明确要求后才用 `gh repo create` 创建，并按确认值设置可见性。

不要覆盖现有远程、强制推送、删除分支或重写历史，除非用户另行明确授权并理解影响。目标目录已有内容时先比较并停止处理冲突。

## 3. 提交与推送

在隔离 Git 工作区中只暂存发布包目标文件。提交前再次运行本地验证和 `git diff --cached`；提交信息描述实际 Skill 和版本。推送精确分支，不依赖会推送额外 ref 的模糊配置。

若 push protection 阻断，默认动作是移除/轮换秘密并重新生成干净提交，不绕过保护。只有被确认是假阳性且用户明确批准时才考虑平台提供的例外流程。

## 4. 发布后核验

读取远程仓库中的目标树，核对文件数量和关键哈希；检查 README 链接、安装命令和许可证可访问；记录仓库 URL、分支、提交 SHA 和目标路径。远程实物与本地包不一致时不宣称发布完成。

