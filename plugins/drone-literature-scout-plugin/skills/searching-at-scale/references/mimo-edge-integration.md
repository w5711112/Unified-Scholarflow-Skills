# MiMo Desktop 与 Edge 的真实联动

本说明写给使用 **MiMo Desktop**（以及 Codex、Claude Code、Kimi Code 等任意能执行本机命令的 Agent）的使用者。目标是让 Agent 加载 Edge，通过扩展与 Native Host 收到页面投影。

## 联动链路

```text
MiMo Desktop / 其他 Agent
    │  执行 scripts/edge_bridge_ctl.py
    ▼
Edge（用户日常登录态或专用 profile）
    │  加载 edge-extension/（MV3）
    │  chrome.runtime.connectNative("com.codex.searching_at_scale")
    ▼
SearchingAtScaleNativeHost.v2.exe
    │  命名管道 \\.\pipe\codex.searching_at_scale.v1
    ▼
scripts/edge_extension_client.mjs / edge_marketplace_query.py
    │
    ▼
searching-at-scale 的结构化候选与证据
```

`com.codex.searching_at_scale` 是 Native Messaging 协议主机名。注册表指向本包内的宿主清单后即可使用。MiMo 发起的安装与探测走同一路径。

## MiMo 一次接通

在 MiMo Desktop 对话里让 Agent 在 `searching-at-scale` 目录执行：

```powershell
# 1. 查看桥接状态（路径、宿主、注册表、管道）
python scripts\edge_bridge_ctl.py status

# 2. 安装/刷新 Native Host 并写入 HKCU（不改系统级配置）
python scripts\edge_bridge_ctl.py install
# 若 EXE 已被占用且只是缺注册表：
# python scripts\edge_bridge_ctl.py install --register-existing

# 3. 用独立 profile 启动 Edge 并 --load-extension 加载本包扩展
#    目录名必须以 edge-profile 结尾
$profile = Join-Path $env:TEMP 'mimo-scholarflow\edge-profile'
New-Item -ItemType Directory -Force -Path $profile | Out-Null
python scripts\edge_bridge_ctl.py launch --profile $profile --replace
# 返回 JSON 中的 pipe 即本 profile 的专用管道

# 4. 探测该 profile 管道（不要探默认 v1 管道）
python scripts\edge_bridge_ctl.py probe --profile $profile --timeout-ms 15000
```

`status.ready_for_edge_launch` 为 `true` 且 `probe.ok` 为 `true` 时，MiMo 已与 Edge 完成真实联动，后续可调用 `edge_marketplace_query.py` / `market_scheduler.py` 做批量投影。

## 和 Codex 路径的关系

| 步骤 | Codex | MiMo Desktop | 其他 Agent |
|---|---|---|---|
| 加载 Skill/Plugin | 插件或 `~/.agents/skills` | 同目录约定 / 对话内指定路径 | 同左 |
| 安装 Edge 扩展与 Native Host | `edge_bridge_ctl.py install` | 同一命令 | 同一命令 |
| 启动 Edge | `launch_edge_profile.py` | `edge_bridge_ctl.py launch`（内部同一脚本） | 同左 |
| 收投影 | Node/Python 客户端 | 同一客户端 | 同一客户端 |

差异只在 Agent 如何找到脚本与授予命令执行权限，不在 Edge 协议本身。

## 权限与边界

- Native Host 注册写在 `HKCU\SOFTWARE\Microsoft\Edge\NativeMessagingHosts\com.codex.searching_at_scale`，可随时删除该键卸载。
- 扩展权限保持最小集：`nativeMessaging`、`storage`、`alarms`，外加检索站点 host 权限。
- 专用 profile 与日常 Edge 分管道，避免抢同一 `codex.searching_at_scale.v1`。
- 公开包不携带维护者本机绝对路径；安装脚本会按当前机器写入宿主清单。

## 故障排查

| 现象 | 处理 |
|---|---|
| `status` 里 `native_host_exe_exists=false` | 先 `install`（会调用系统 .NET 编译器）或 `--register-existing` |
| `probe` 报 named pipe unavailable | 确认 Edge 已用 `launch` 启动且扩展已加载；必要时加大 `--timeout-ms` |
| 扩展连上但无数据 | 检查站点权限、登录态与 `host_permissions` 是否覆盖目标站 |
| 与日常 Edge 冲突 | 使用独立 `--profile`，不要共用默认管道 |

验证成功后，在 Agent 会话里应能读到 `probe` 的 `ok: true` 与管道名，这才算“MiMo 能加载 Edge 并联动”。

