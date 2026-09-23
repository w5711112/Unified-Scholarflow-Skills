# Zotero Local Bridge

这是一个 Zotero 9 启动式 XPI，只承担两类本机机械操作：

- `link_bridge.js` 拦截保留域名 `https://obsidian-link.invalid/open?...`，严格验证其中的 `obsidian://open` 目标后交给系统 Obsidian handler。启动失败时失效关闭，不回退到浏览器或 Gecko 外部协议确认框。
- `annotation_bridge.js` 在 Zotero 内置的 `127.0.0.1:23119` 上注册三个固定接口：`GET /zotero-local-bridge/v1/health`、`POST /zotero-local-bridge/v1/annotations/preflight` 和 `POST /zotero-local-bridge/v1/annotations/apply`。

批注内容、选择、颜色、坐标转换、稳定 ID 与效果验收都由 `read-paper-analysis-highlight` 决定。XPI 只负责认证、只读预检、原子执行和即时读回；不提供任意 JavaScript、SQL、文件路径、全库扫描、队列、账本或常驻进程。它通过 Zotero API 写入受控的原生 PDF 批注，不直接访问 SQLite。

## 确定性打包

在本目录运行：

```powershell
python .\scripts\package_xpi.py --output .\dist\zotero-local-bridge-2.0.0.xpi
```

打包器只在标准输出返回 `output`、`sha256`、`plugin_id` 和 `version`。生成的 XPI 根目录严格只有：

- `annotation_bridge.js`
- `bootstrap.js`
- `link_bridge.js`
- `manifest.json`
- `merge_bridge.js`

打包动作不安装插件，也不包含 token、source proxy、测试文件或临时状态。插件 ID 保持 `obsidian-link-bridge@read-paper-analysis-highlight.local`，以便从旧版原位升级；清单版本为 `2.3.0`。

## 受限父条目合并

`POST /zotero-local-bridge/v1/merge/preflight` 只读核验明确指定的个人库父条目及其子项，返回有效期 5 分钟的签名回执。`POST /zotero-local-bridge/v1/merge/apply` 在一个原生事务中检查快照未变，保留附件和批注 key，合并 notes、tags、collections 与 relations，将重复父条目移入回收站并读回。请求沿用本机 HMAC 认证，拒绝浏览器 Origin、跨库、任意字段和执行脚本。

`formal_metadata` 只接受已核实的期刊或会议字段。`preprint_metadata` 是既有 arXiv 条目误分类的纠错分支，要求题名匹配、arXiv ID、来源 URL 和可选 arXiv DOI 一致，不能覆盖冲突的正式 DOI。两个模式互斥，均需要专业身份材料的 SHA-256。它们不提供新建父条目、删除附件或任意数据库写入能力。控制器为导入 Skill 的 `scripts/merge_duplicates.py`，网络结果不明时先对账，禁止自动重发。

元数据或保留项回读失败即回滚。隔离测试覆盖类型变更后的内存状态恢复、原生事务回滚与重放阻断；测试夹具不得进入正式包。现有附件挂载与正式版本文件替换仍需另一个已验证的受支持接口，合并成功不代表正式 PDF 接管完成。

## 安装边界

真实 Zotero profile 只能在用户明确批准后，通过“工具 → 插件 → 从文件安装插件”安装。打包、单元测试和隔离验收都不得触碰真实 profile 或生产论文。

若正式界面无法使用，离线原位升级只作为另行批准的恢复动作：必须确认 Zotero 已完全停止，并核对活动 profile、相同插件 ID、版本与源/目标 SHA-256。离线替换不能冒充正式安装证据；重启后须分别通过安装元数据门槛（`plugin_installation_normalized`）和行为门槛（`bridge_click_verified`），两者互不替代。

`manifest.json` 的不可解析 `update_url` 使用保留域名，只为满足 Zotero 9 清单合同，不表示存在联网更新服务。

## 隔离验收

`tests/integration_checklist.json` 要求使用 disposable profile 和 fixture PDF，禁止 live profile 与生产论文。启动前必须使用 `-headless`，确认测试端口只有一个监听者，并仅在 disposable profile 中把 Word/LibreOffice 自动安装设为跳过；批注 `sort_index` 必须符合 Zotero 9 的 `五位页码|六位偏移|五位序号` 原生格式。验收范围为：

1. preflight 零写入；
2. 原生批注创建、更新、删除；
3. 重复请求零新增；
4. 响应丢失后的指纹对账；
5. 注入失败后事务回滚；
6. 重启后 health 恢复；
7. Obsidian 回链行为不变。

清理后临时 profile、XPI staging、`.lock` 与调试窗口都必须为 0。未知的人工批注不得被修改；破坏性目标不明确时接口返回冲突。

## 真实环境验效

用户批准安装后，还需确认插件启用状态、加载版本、启动日志、health、token 文件权限，并在 disposable 附件上完成创建—编辑—读回—删除。最后实点一次 PDF 回链，确认 Obsidian 聚焦目标块，且 Edge 与外部协议提示均未出现。

在这些证据齐全之前，不把旧路径标记为已退役，也不修改 `collect-bug-update-accelerate` 的已验证路由。
