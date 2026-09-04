# 已验证故障解法手册

## 目录

- Windows 与 PowerShell
- Codex 工具与沙箱
- Python 与项目依赖
- Zotero 9
- PDF 坐标与批注
- Obsidian
- 验证与清理

本手册只给出路线选择和验收点。每次执行前仍需查询 `incident-registry.json`，确认环境版本和禁用参数。

正常成功路径不查询本手册、不写故障库；只有已知脆弱组件、失败路线或历史方案复用时才进入这里。

## 固定路线优先级与依赖门

效果等价时，路线顺序固定为：正式 MCP/API/CLI → 本地文件或脚本 → 应用内部 API/JavaScript → 不移动鼠标的 UIA/窗口消息 → `foreground-computer-use`。前台路线只有在没有等价后台方案、用户明确允许且不会干扰当前操作时才可使用；输入权限拒绝后立即停止前台路线。

缺失依赖且安装目标明确时，先在当前环境安装并验证，再重试原路线，不得先绕行：

- Python 先读取 `sys.executable`；import 名与发行包映射明确时，用同一解释器调用 `ensure_dependencies.py`，重新 import、读取版本，再重试原失败操作。
- 提权环境能读用户包而普通沙箱不能时，用 `--target` 安装到批准项目的本地依赖目录，并以任务级 `PYTHONPATH` 回到普通环境验证。只有本次新建的精确目录缺少继承权限时，才对该目录运行 `icacls /reset /T /C`；不得扩到项目根。
- Matplotlib 用户缓存不可写时，把任务级 `MPLCONFIGDIR` 指向批准项目的运行目录，不改全局目录。Node 依赖仅在清单、锁文件或明确报错能确定包名和项目目录时，用项目现有包管理器安装。
- 安装失败是新证据：记录网络、权限、版本冲突、解释器不一致或仓库不可用；不得原样重试。映射不明、来源可疑、驱动、系统服务、浏览器扩展、Zotero XPI、应用插件、全局版本或用户数据变更不得自动进行。
- 网络受限时走平台审批，不循环联网。只有安装不可行、映射不明或风险过高时才能提出降档路线，并明确它不是永久修复。

路线与参数组合失败后先运行 `retry-check`。只有新证据、关键变量变化、已验证替代路线或外部权限状态确实变化才能重试；修改描述、重复点击或重新聚焦不算新路线。

## 质量档位：解决方案不得降挡

记录的方案必须保持与原路线相同或更高的输出质量档。**降档路线不是永久修复**——例如"原生视觉大模型直接读图"明显优于"文本模型 OCR 后读图"，前者失败时不得把后者记成 `verified` 方案。

- 只有确认主路线不可行（权限、依赖、平台限制等）时，才允许提出降档路线，并明确它不是永久修复，记 `observed`，不记 `verified`
- 涉及领域语义（读图、批注、论文判断、标注语义等）的方案，写入 `quality_guard.preserve_output_fidelity` 声明质量下限，并把"退回低档路线"列入 `forbidden_downgrade_routes`
- `reuse-result` 记复用成功时，本次若走了任一 `forbidden_downgrade_routes`，成功会被拒绝并给出证据；这也防止用"有输出"冒充"质量不降档"
- 记录 `quality_guard` 的 `resolve`：`--quality-guard '<json>'`

## Windows 与 PowerShell

### `foreach` 语句块直接接管道

- **症状**：`An empty pipe element is not allowed`
- **根因**：PowerShell 语句块不是可直接置于该位置的管道表达式
- **固定解法**：先 `$rows = foreach (...) { ... }`，再运行 `$rows | Format-Table`
- **禁止**：原样重提同一管道

### UTF-8 与中文路径

- 对文本显式使用 `-Encoding UTF8`；Python 进程需要可读中文输出时设置任务级 `PYTHONIOENCODING=utf-8`
- 内联脚本尽量不用易被 shell 二次解释的中文路径和特殊符号；使用 `-LiteralPath`
- PowerShell 不跨 shell 枚举并删除文件

### 前台输入权限拒绝

- 连续权限拒绝不是“坐标不准”；停止 `GetCursorPos` / `SendInput` / 盲点
- 改走 API、应用内部 API、UIA 控件模式或窗口消息
- 只有权限状态发生可验证变化后，才允许一次无副作用探测

## Codex 工具与沙箱

### Thread API 硬上限

- `list_threads` 当前服务端上限为 50；不要提交 100
- `read_thread` 当前服务端 `turnLimit` 上限为 10；使用游标分页
- 某些客户端元数据展示 `query`，但当前服务端可能拒绝该字段；第一次收到 `Unrecognized key` 后改用无查询列表和本地过滤

### Windows split writable roots

- **症状**：`windows unelevated restricted-token sandbox cannot enforce split writable root sets`
- `apply_patch` 或 `view_image` 第一次命中后不要重复相同调用；先检查 `<USER_HOME>\.codex\config.toml` 的 `[windows]` 沙箱模式和 `.codex\.sandbox\setup_error.json`
- 如果错误停在 `apply deny-read ACLs`，且 `deny_read_acl_state.json` 是全零字节或无效 JSON：先备份该文件并保留校验值，再移出活动路径；把配置改为 `sandbox = "elevated"`，随后重启 Codex 并完成管理员批准
- 验证门：`setup_error.json` 不存在，新生成的 ACL 状态是有效 JSON，并分别直接验证一次 `apply_patch` 与 `view_image`
- 后台 Node 精确替换只是在暂时不能重启时使用的临时路线；必须断言旧文本只命中 1 次、写回 UTF-8 并重读测试，不能登记为永久修复
- 不用前台编辑器，不使用不带断言的全文件覆盖；备份在验证成功前不得删除
- JavaScript 正则没有 `\z` 终止锚点；跨段替换必须使用可验证的下一个标题边界，并断言完整命中内容，不能把 `\z` 当作 PCRE 写法

### Python 子进程无法写临时目录

- 先用最小文件探针区分代码权限与沙箱权限
- 真实目标在工作区但受限子进程仍被拒绝时，只提升范围明确的测试/生成命令
- 不把权限拒绝误判为原子写入算法错误
- 在允许写入的环境中使用同目录临时文件与 `os.replace`；不要假设系统 `TEMP` 可写

### 路径不存在或目录不可见 → 枚举优先（已验证模式）

- **症状**：提权创建的联系表/渲染输出目录对受限沙箱 PowerShell“不可见”或后续读取时消失；预期文件名（如 `contact-005-008.png`、`page-01.png`）路径不存在；工作记录父目录不可见
- **根因**：不可见常来自提权创建目录的 ACL 与受限沙箱不一致，或文件名/子目录结构与假设不符；不是内容真的缺失
- **固定解法**：**不要假设路径或文件名**——先枚举实际目录树（`Get-ChildItem`/`rg --files`/只读提权枚举），拿到真实返回的对象与文件名，再绑定渲染/读取/复制逻辑
- 已验证先例：`result-copy`、`docx-final4-png-baseline`、`task7-final5-page-baseline`、`post-cleanup-final-verification`、`q2-quick-fix-path-resolution` 均用“先枚举再操作”通过验证
- 受限 PowerShell 对提权创建目录不可见时，用只读提权枚举定位实际路径，再降回普通沙箱按真实路径操作；不把“看不见”当成“不存在”

### Windows `TemporaryDirectory` 的 0700 ACL

- **症状**：父目录可写，但 `tempfile.TemporaryDirectory` 创建后，内部文件立即 `PermissionError`，清理也被拒绝
- **根因**：当前沙箱中 0700 模式破坏了所需的继承 ACL；不是被测原子写逻辑失败
- **固定解法**：测试专用目录使用 `Path.mkdir` 创建 UUID 子目录继承父 ACL，在 `finally` 中精确删除；不要改弱生产原子写或锁语义
- **验证**：孤立测试、完整测试和零残留三项都要通过

### Windows 独占锁把竞争报告成 `PermissionError`

- `os.open(O_CREAT|O_EXCL)` 在现有锁被另一线程打开时，可能返回 EACCES 而不是 `FileExistsError`
- 只有**精确锁路径当前存在**时才把该 `PermissionError` 视为竞争并进入等待；锁不存在时必须原样抛出
- 保留超时、陈旧锁和最终清理门，防止吞掉真实权限故障

## Python 与项目依赖

- 先输出 `sys.executable`，不要混用 `python`、`py`、Conda 和虚拟环境
- 缺包是明确根因、包名和当前环境也明确时，先安装、验证，再重试原路线；不得先绕行
- Python 明确映射后调用 `ensure_dependencies.py` 自动安装；安装和验证必须使用同一解释器
- 若提升权限环境能看到用户包、普通 Codex 沙箱却看不到，给 `ensure_dependencies.py` 传入显式 `--target`，安装到批准项目的本地依赖目录，并用任务级 `PYTHONPATH` 在普通环境重试原操作
- 若提升权限运行的 pip 搬入目录后普通沙箱仍报拒绝访问，先确认目标是本次新建且位于批准项目内，再只对该精确目录运行 `icacls.exe "<目标目录>" /reset /T /C` 恢复继承；不得作用于项目根、用户目录或 Python 根目录
- Matplotlib 能导入但用户字体缓存目录不可写时，把任务级 `MPLCONFIGDIR` 指向批准项目的 `.codex-runtime` 缓存目录；不改用户全局目录
- 常见明确映射：`yaml=PyYAML`、`fitz=PyMuPDF`、`PIL=Pillow`、`cv2=opencv-python`
- Node 等项目依赖只在清单、锁文件或明确报错能可靠确定包名时安装，并使用项目已有的包管理器
- 安装失败后记录实际原因，不重复相同命令；只有安装不可行、映射不明或属于高风险安装时才提出降级路线
- 驱动、系统服务、浏览器扩展、Zotero XPI、应用插件、全局版本替换和用户数据变更仍需单独授权
- 网络被沙箱阻断时直接走平台受控提升，不循环重试 pip

## Zotero 9

### CodeMirror 表面值与内部状态不一致

- 不对已有非空 Run JavaScript 编辑器直接使用 `ValuePattern.SetValue`
- 打开新 Run JavaScript 窗口，聚焦真实编辑区，使用 `WM_PASTE` 写入精确脚本
- 执行前读取并比对编辑器规范化文本

### 异步执行未生效

- 不假设调用 `Toggle()` 就已改变状态
- 聚焦“作为异步函数执行”复选框，使用控件键盘消息切换，并读取 `CurrentToggleState == 1`
- 顶层 `return not in function` 出现时，先确认异步状态和加载器包装，不直接归咎批注逻辑

### 尚未执行到批注脚本

按阶段记录：编辑器写入 → 异步状态 → loader 语法 → Zotero API → 目标附件 → 批注保存。loader 失败时不得继续修改批注计划。

### Zotero 写入边界

- 本地 Zotero HTTP API 用于读取，不假设支持原生批注写入
- 原生可编辑批注使用 Zotero 9 应用内 `Zotero.Annotations.saveFromJSON` 路线
- 创建后重新查询 `isExternal=false`、数量、文本、颜色和位置；做一次可编辑/恢复验证

### 自动翻译后缀

- 第三方翻译插件可能在批注评论后追加 `🔤…🔤`
- 等插件处理完成后，逐条与计划文本比较，重写不一致评论并再次查询
- 交付门要求后缀计数为 0

### Zotero—Obsidian 返回链接

- 直接 `obsidian://` 可能触发浏览器确认；使用已安装且匹配 Zotero 9 的保留 HTTPS bridge
- XPI manifest 必须声明 Zotero 9 兼容范围；安装后验证插件处于活动状态和目标 block 可达

## PDF 坐标与批注

### 框选漂移

- PyMuPDF/PDF 渲染常用左上原点，Zotero PDF area position 使用左下原点；必须显式转换并保存两套坐标
- 公式、图、表先渲染可视预览，做坐标 round-trip 和边界检查
- 重新生成时从干净备份开始，不能在已标注 PDF 上叠加

### 批注被锁

- 直接嵌入 PDF 的 markup 可能成为外部或不可编辑批注
- 优先创建 Zotero 原生批注并验证 `isExternal=false`
- 交付前做临时创建—编辑—删除测试，不用用户正式批注做破坏性实验

### 图/表内容读取：视觉直读优先，OCR 降档禁止

读图、读公式、读表格内容属于 `read-paper-analysis-highlight` 的领域语义，输出质量档位固定为：

- **主路线（最高档）**：原生视觉大模型直接读取渲染后的图/表/公式图像
- **降档路线（禁止记为 verified）**：文本模型对图像做 OCR 后再读取——识别精度、版面结构、公式/表格语义都会明显损失

规则：

- 视觉直读失败时，先按"根因→修复"处理（渲染、坐标、权限、模型能力），**不得直接切换 OCR**
- 只有确认视觉路线真正不可行（权限/依赖/平台/模型限制）时，才允许 OCR 作为**临时**降级，记 `observed` 并明确非永久，**不得**标记 `verified`/`promoted`
- 涉及图像读取的 verified 方案必须带质量守卫（`resolve --quality-guard`）：

```json
{"preserve_output_fidelity": "必须由视觉大模型直接读取渲染图像，不得退回文本模型 OCR",
 "forbidden_downgrade_routes": ["ocr-downgrade", "text-ocr-then-read", "paddleocr-fallback", "tesseract-fallback"]}
```

- `reuse-result` 会把上述低档路线并入禁止副作用：复用走了任一 OCR 路线时成功被拒绝

## Obsidian

### Vault 根目录误判

- 从当前项目向上寻找 `.obsidian`，确认真实 Vault 根后再索引
- 新建知识笔记前搜索全 Vault 的标题、别名、heading 和 block
- 不在论文项目子目录复制已存在的知识中心

### Callout 折叠失效

- 每篇论文只保留一个顶层 `> [!note]-`
- 嵌套折叠使用正确的 `> >` 层级和空行
- heading 后的 block ID 保持固定位置；修改后运行结构验证

### 状态提前切换

只有全文 ledger、图表审计、证据笔记、双链、作者证据、原生批注和最终验证全部通过，才能从“待精读”改为“已AI全文读”。

## 验证与清理

### 已通过门反复执行

- 记录输入哈希和验证器版本
- 未变化时复用增量结果；修改影响到的门必须重跑
- 最终交付仍执行一次全量测试和镜像检查

### 临时文件残留

- 创建工作目录前确定最终保留清单
- 清理前解析绝对路径并验证位于任务运行目录内
- 只删除明确的临时产物；备份、manifest、ledger 和最终验证报告按业务 skill 合同保留
- **大体积中间产物不留**：解压的参考论文副本、虚拟环境、PDF/图像缓存、旧备份、提取工作目录处理完即清理；可再生副本不长期驻留工作区（示例：曾清理 345M 的 `problem-b-style-revision` 参考论文提取目录，由提取脚本即可重建）
- 收尾复查：除明确成果输出外，不应残留可再生的大体积中间文件；`.codex-runtime` 仅保留激活依赖目录、事故库与运行数据


### 镜像同步基线过期

- `--sync-auto` 报双方都变化时先停止，不猜方向
- 若本轮开始已有字节测试证明两侧相同，而且本轮只修改 canonical，可使用这份证据运行一次 `--sync` 并刷新 baseline
- 没有修改前相等证据时必须人工合并，不能把“通常改 canonical”当作证据

### 中文 Skill 验证与退出码掩盖

- Windows 上运行 `quick_validate.py` 前设置任务级 `PYTHONUTF8=1`
- PowerShell 的 `$ErrorActionPreference='Stop'` 不会自动把所有 native 非零退出码变成终止错误；每个 native 命令后检查 `$LASTEXITCODE`
- 不把同一批命令最后一项成功当作前面全部成功
