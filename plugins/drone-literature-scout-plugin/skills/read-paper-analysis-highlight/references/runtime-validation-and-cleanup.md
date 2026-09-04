# Windows 运行、增量验证、清理与交付合同

## 解释器、编码与依赖

- 运行 Python 前固定实际 `sys.executable` 并探测 import；不因为另一个 Conda 环境有包就假定当前环境可用
- `scripts/ensure_python_dependencies.py` 只处理低风险 allow-list：至少 `yaml → PyYAML`、`fitz → PyMuPDF`；由同一解释器安装一次，重新 import、记录版本再重跑原命令
- 未知包、系统软件、Zotero/Obsidian 插件、驱动、服务、全局配置和用户数据变更不自动安装
- 文本统一 UTF-8；Python 用 `-X utf8`。PowerShell→Python 中文管道前设置 `[Console]::OutputEncoding`、`$OutputEncoding`、`PYTHONUTF8=1`；中文变 `?` 先按编码故障处理
- 不依赖 `Get-CimInstance`；版本读可执行文件 ProductVersion，进程存在性用 `Get-Process` 或等价只读接口

## 固定故障路线

| 签名 | 直接路线 | 禁止循环 |
| --- | --- | --- |
| `apply_patch` / split writable roots | 一次预检后用范围限定 UTF-8 进程内 API；断言目标根、唯一旧片段、替换次数、逐字回读与 SHA-256 | 重复补丁、提权、shell 引号试错 |
| Poppler 包装器找不到路径 | 从工作区依赖清单解析真实程序，或用 PyMuPDF | 重试已坏包装器 |
| 预览器拒绝双可写根 | 在同一已验证论文运行根完成渲染与读取 | 跨根反复搬运 |
| `PYTHONPYCACHEPREFIX` 权限/长路径 | `python -B`、内存 `compile` 或已验证短路径 | 深层 bytecode cache |
| Computer Use / `0x80070005` / 鼠标冲突 | 文件 API、本机脚本、PyMuPDF、正式 Zotero bridge；仅留最终实点 | 抢焦点、盲点、重启 GUI |
| Python import 缺失 | 核对 import→distribution，同一解释器安装一次并复验 | 反复安装或静默换环境 |
| PowerShell 中文乱码 | UTF-8 字节回读和哈希比较 | 因控制台字形重写文件 |
| GNU patch signal pipe | UTF-8 `git apply --check` 后应用同一范围补丁 | 扩大权限、重复 patch |
| 临时目录拒绝 | 使用已验证论文运行目录 | 假设 `C:\tmp`/系统 TEMP 可写 |
| `File.Replace(..., null, ...)` 路径错误 | 核验同卷 staged/目标绝对路径、页数、SHA-256 后 `Move-Item -LiteralPath -Force` | 循环尝试、扩大权限 |

发现 `.orig`、`.rej`、全 NUL、正式 JSON 缺失或半写文件时停止后续写入；先验证候选可解析且哈希/字段完整，再原子恢复并清理。图/表读取的 verified 路线必须携带 `quality_guard`，保持视觉模型直读，禁止 `ocr-downgrade`、`text-ocr-then-read`、`paddleocr-fallback`、`tesseract-fallback`。

## 批注、坐标与写回防回归

- 删除旧批注前按 native keys 分“本轮、明确旧批次、未知”并计数；只删 manifest 登记项，未知不为 0 立即停止，删除后读回
- 每个 area 都执行 PyMuPDF top-left → Zotero PDF bottom-left → 反向变换并逐区域渲染；不复用未经 page box/rotation 核验的矩形
- 重跑批注或首页增强始终从 SHA-256 核验的干净 backup 开始
- 覆盖 Zotero PDF 前在附件同目录生成单一 staged 文件并核验路径、页数和哈希；正式文件读回一致才成功
- 最终 `zotero-native` manifest 按 `storage_mode` 分流，核验 `current_pdf_sha256`、native keys、annotation plan、数据库对账、可编辑/可删除和 0 locked/external/embedded；不强制旧嵌入字段

## 中途增量验证与最终全量验证

用 `scripts/validation_gate_cache.py` 为各门生成输入指纹；只包含相关 Skill/reference/script、PDF、笔记 block、manifest 哈希、Zotero 版本、批注路径、作者或链接输入，不含时间戳。

- 中途：已通过且输入未变的门不重复；失败门、输入变化和所有受影响下游必须重跑
- 不能因历史一直通过就永久跳过
- **最终全量验证**：交付前忽略中途成功缓存，对全部必需门从新鲜输入完整运行一次
- 最终包括 Python 内存编译/`python -B`、Skill 本地测试、插件全量测试、manifest/位置/可编辑性、行为点击，以及 `SKILL.md` 与完整指南字节级相等
- 最终失败只修受影响链；修好后再执行一轮新鲜最终全检，不能拿旧缓存完成

## 清理白名单

截图、草稿 PDF、临时 manifest、调试 JSON、渲染页和导入脚本统一放到该论文运行目录。最终只保留：

- annotation-free backup
- 最终 manifest
- 必要作者/逐页/知识索引证据
- 最终核验报告
- 用户实际使用的 PDF

只删除本轮运行目录内可再生产物、失败草稿和重复版本。不能删除用户原件、用户手工批注、个人理解、其他论文运行数据或代码依赖。清理前解析绝对路径并核验位于目标运行目录；清理后复查引用和链接。误建知识笔记先交 `obsidian-note-style` 合并独有内容、验证链接，再按白名单删除并重建索引，不能当普通临时文件直接删。

## 交付门

交付时复用本轮 8 个证据对象，但最终验证器从新鲜输入运行。至少确认：

1. 每页正文、公式、图、表、图注已读且 `unresolved` 为空
2. 高亮均为独立信息证据原子；方法、baseline、参考角色、量化值和 support link 语义完整
3. 评论首行结论、后续分析；`quote`、`actual_text`、`quads`、页码一致
4. area 的 `rect`/`zotero_rect` 往返和视觉对象一致
5. 作者完整、可达、带日期、使用“外部信息：”，三处一致且无独立作者笔记
6. 唯一 Callout、独占行 block ID、个人理解逐字保留；PDF 页码定位和多页压缩正确
7. 每个公式逐符号、计算逻辑、系统位置、设计原因、条件与边界完整
8. 记忆句在笔记/PDF逐字相同，回答原理—结构—效果且不遮挡
9. 回链只有 `bridge_url_count = 1`、`direct_obsidian_uri_count = 0`，真实点击到当前论文 block
10. 论文报告、可以推断、尚不能证明、作者局限、未报告疑点和实验对象—条件—样本—结果—边界分开
11. 控制、感知和机器人论文的主链模块逐项通过八项解释合同；初学者能沿数据流复述输入来自哪里、怎样处理、输出属于谁并交给谁；中文正文已按 `专业语义草稿 → renhua → obsidian-note-style` 处理
12. backup、overwrite、SHA-256、annotation manifest 通过；Zotero 原生、可编辑、可删除、无锁、位置准确
13. 正文和知识链接完成后**每篇论文只触发一次** `obsidian-note-style`；全 Vault 视觉审计、每知识点 0/1 决策、`draw-style` **八项硬质量门槛**与媒体审计通过
14. 中间文件零残留，镜像字节一致，最终状态才为 `已AI全文读`
