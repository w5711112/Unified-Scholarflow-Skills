# Zotero 原生写入、PDF 记忆层与 UI 合同

## 唯一原生批注路线

1. 从已验证 annotation manifest 调用 `scripts/build_zotero_native_annotation_plan.py`：area → `image`，文本 quads → `highlight`；保留稳定 ID、`page_label`、`sort_index`、颜色、评论和坐标
2. 首次需要 Zotero 读写时，用 `scripts/zotero_local_bridge_client.py` 调用 `GET /zotero-local-bridge/v1/health`；要求初始化完成、schema 匹配且支持 `highlight`/`image`
3. 调用 `POST /zotero-local-bridge/v1/annotations/preflight`，核对 create/update/delete/no-op、冲突、`plan_digest`、`snapshot_digest` 与短期签名回执；不得写 Zotero
4. 冲突为空才以同一计划、两个 digest 和回执调用 `POST /zotero-local-bridge/v1/annotations/apply`
5. 单一事务原子执行并即时读回 native keys、完整指纹、类型、物理页、显示页码、排序、位置、颜色、评论和文本
6. 评论与 manifest 的 `annotation_comment` 逐字相等（允许 Unicode NFC）；清除本轮 AI 批注中的 `🔤…🔤`、机器翻译或自动翻译后缀后受控 update/readback
7. 修改一条受控评论/颜色并恢复，再创建并按 key/指纹精确删除测试批注，证明可编辑、可删除
8. 响应丢失时重新 preflight；完整指纹匹配必须成为 no-op，不得重复 apply
9. 从 annotation-free backup 恢复 PDF 本体，确保 embedded/external markup 为 0，Zotero 原生子条目保留

最终必须满足：`storage_mode: zotero-native`、`editable_verified: true`、`deletable_verified: true`、`locked_annotation_count: 0`，未知用户批注变化数为 0。禁止脚本控制台、前台鼠标、直接 SQLite、全附件清理、按评论模糊删除和删除未知 key。

状态处理：`400/422` 修计划；`404` 修 attachment/native key；`401/403` 停止查令牌/权限；`409` 是安全阻断，重读附件/manifest 后重建计划；`500` 要求事务回滚并登记；`503` 仅在 fresh health 恢复后最多重试一次。

## PDF 首页记忆句

- 每篇论文一条“**一眼记住这篇论文**”，依次回答通过什么原理、构建什么结构、实现什么效果，不复述标题或 Index Terms
- 同一句逐字同步到 Obsidian 来源行之后和 PDF 首页标题上方空白处
- 先渲染首页并记录期刊头、标题、作者、正文的 protected rectangles
- `scripts/augment_pdf_memory_layer.py` 从干净 backup 单次生成，拒绝越界、互相重叠和侵入保护区
- 生成后重新提取记忆句、读回链接并确认 PDF markup 仍为 0
- 至少以 **150–200 dpi** 渲染首页，人工检查字号、居中、留白、点击区和遮挡

## Zotero → Obsidian 回链

Zotero 9 内置阅读器不会把 PDF `/URI` 中的直接 `obsidian://` 当作可打开 external link。首页左上角固定显示“**返回 Obsidian的对应精读位置**”，实际 URL 固定为：

`https://obsidian-link.invalid/open?uri=<percent-encoded obsidian://open?...>`

`.invalid` 是不可解析保留域；禁止公共重定向服务。manifest 必须记录 `obsidian_uri`、`bridge_url`、vault、相对笔记路径、独占行 block ID、`link_rect`、`bridge_url_count = 1`、`direct_obsidian_uri_count = 0`、插件版本和 `bridge_click_verified`。

唯一配套插件位于 `integrations/zotero-local-bridge/`。回链模块只拦截上述 origin/path，解码后只允许含 `vault` 和 `file` 的 `obsidian://open`；通过 `getProtocolHandlerInfo("obsidian")` 设置 handler，再调用 `handler.launchWithURI(...)`。**禁止 `Zotero.launchURL(obsidianURI)`**，直连失败必须失效关闭，不能把保留域交给 Edge。

## 插件安装与两个独立门

- XPI 根必须含 `manifest.json`，声明 `id`、失效关闭的 `https://obsidian-link.invalid/updates.json`、`strict_min_version = 9.0`、`strict_max_version = 9.0.*`
- 首选 Zotero“从文件安装插件”；不能仅投放 XPI/source proxy 就声称安装
- 仅在用户事前明确确认、同 ID 已安装、Zotero 完全停止且交互桌面不可进入插件界面时，允许对哈希核验且版本更高的同 ID XPI做一次离线原位升级；它不等于已加载
- `extensions.json` 版本一致、`active=true`、`userDisabled=false`、`appDisabled=false` 且 startup 已确认，才设置 `plugin_installation_normalized = true`
- 真实点击后 Obsidian 聚焦到目标 `#^block-id`、无外部协议确认框、Edge 未调用，才设置 `bridge_click_verified = true`
- 两项必须并列报告，不能互相冒充

唯一 `^block-id` 位于论文标题下方、主 Callout 之前的独立行；行为门不是“Obsidian 窗口已打开”，而是目标论文标题进入可视区。

## 无界面优先与一次 UI 门

全文抽取、台账、渲染、批注计划、Obsidian 写入、链接验证、依赖、哈希和插件包检查默认走文件、脚本或本机接口。Computer Use 只用于没有可靠接口替代的插件安装或最终实点，并集中一次；开始前在 commentary 通知用户。

鼠标正在使用、焦点变化、`0x80070005`、黑屏、授权超时或模态窗口不可输入时，立即停止 UI，记录 `ui_gate_pending = true`；主窗口只允许刷新选择并重试一次。受限 shell 启动的不可见 GUI 只能诊断，不能成为成功证据；用户可完成一次手工点击，再由 block、日志或窗口状态验收。

权限与协议预检只做一次：读取 Zotero ProductVersion、`HKCR\obsidian\shell\open\command` 或等价注册、XPI 根和清单、活动 profile `extensions.json`、底层 `obsidian://open`、桥接真实点击。工作区外目标先解析精确绝对路径和哈希，再合并为一次范围限定授权，不申请整盘或整个用户目录权限。
