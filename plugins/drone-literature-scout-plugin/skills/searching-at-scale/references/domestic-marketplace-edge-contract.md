# 国内商品与 Edge/JD 执行合同

仅在国内商品候选、京东授权会话或 Edge Native Messaging 分支加载。本合同持有旧版入口中的 Edge/JD 协议、隐私、节奏、吞吐和恢复细则；通用来源与批量闸门仍由 `source-routing.md` 持有，完整市场停止语义仍由 `global-scheduler.md` 持有。

## 数据面、授权与唯一浏览器路线

- 国内候选默认组合为显式国内引擎的临时 SearXNG（`360search`、`baidu`、`sogou`、`quark`、`bing`、`brave`）+ Edge 已登录京东列表 + Common Crawl 历史补漏。浏览器路线固定 **Edge-only**，其中 **JD mandatory**：京东 Edge 通道必须实际运行；淘宝与京东联盟 API 都不是阻塞项。
- 京东联盟 API 对本账号固定不可用：开放平台 V0，`jd.union.open.goods.query` 关键词接口额度 0，升 V1 需月订单/GMV/UV（当前为 0）。除非出现新权限证据，否则不得把它放入候选路由、伪称全量或反复探测。
- Edge 通道复用用户已经登录的**日常 Edge**。一次安装 `edge-extension/manifest.json` 的窄权限 **Manifest V3** 扩展，并用 `scripts/install_edge_native_host.ps1 -Register` 写当前用户 HKCU Native Host；宿主 EXE 被占用且注册键缺失时只用 `-RegisterExisting`，不得删除或重编译锁定宿主。
- 扩展不启用远程调试、CDP、WebDriver 或键鼠注入，Node 不启动 Edge；不得回退 Chrome。Edge 未运行、扩展未加载或宿主未连接时返回 `edge_background_bridge_unavailable`，不得改走前台键鼠。
- Edge 运行时只允许**一个 C# Native Host** 随 Native Messaging 端口存在；不创建 Windows 服务或开机启动项。命名管道只授予**当前 Windows SID**；一个搜索分组只启动一个**一次性 Node** worker，Node 不常驻、不监听 TCP。

## 正式预检、标签与隐私边界

1. `scripts/run_jd_sustained.py` 前必须从与正式 worker 相同的 Python→Node 上下文连接命名管道，最长 **60 秒**；预检等待不计入 `T_discovery`。失败时不得创建或覆盖正式账本，返回 `edge_background_bridge_unavailable` 和非零退出。注册键缺失但管道可连仅警告重启风险。
2. 未开启翻页时每个查询最多一个 `active:false` 后台标签并在返回后关闭；显式 `--enable-jd-pagination` 后为当前查询族保留同一标签。**真实翻页默认关闭**；启用后不为深页新建标签。
3. 只读取 `search.jd.com`/`s.taobao.com` 商品卡片公开投影。必填身份为 `platform + SKU/product_id + title + canonical URL`；JD 另有 `price/shop/commit/good_rate/promo/stock/image` 七个键，页面未展示时为 JSON `null`，不得省略、拼接或猜测。
4. 明确**不读取 Cookie**、**不读取凭证**、Local Storage、Session Storage、密码、浏览器配置、完整 DOM 或用户其他标签；不绕过验证码、登录墙、反自动化或其他平台控制。
5. 多话题可重复传入 `--topic`，也接受中英文逗号、分号或换行并稳定去重。Node 的 `edge_extension_client.mjs MAX_OUTPUT_BYTES=200KB` 与 Python 的 `edge_marketplace_query.py MAX_WORKER_OUTPUT_BYTES=200KB` 必须一致；超限为 `edge_worker_output_invalid`。

## 查询族、翻页路线与安全例外

- 查询族固定五个：`<topic>`、`<topic> 自营`、`<topic> 品牌`、`<topic> 型号`、`<topic> 新品`。只先物化第一族第 1 页；成功后懒生成相邻下一页，放弃后下一族从第 1 页慢启动。
- `--max-pages-per-topic` 默认 `2`；`--max-pages-per-topic auto` 只用于深翻实验；数值 `1..512` 是每话题页数上限，协议页码边界也为 `1..512`，两者都不是十分钟运行的正常停止条件。验证成功的批次在同一 SQLite 账本按 `platform + SKU/product_id` 实施跨查询族全局 SKU 去重，失败页不提交。
- 默认转正路线 `experimental_url`（2026-08-11）先把当前 JD 标签置前，再在原标签直连 `page=逻辑页×2-1`；不为深页新建标签。前台置顶是用户授权的稳定行为，除此不抢其他标签焦点、不读取其他标签。
- `human_flow` 路线（2026-08-12）从 `www.jd.com` 首页建立 session/referer，再以带 `from=home` 且无 `page` 参数的 URL 进入搜索，翻页点击真实 `.pn-next`；成败必须用观测页码与 SKU 集变化验证。
- 扩展版本 `2.3.1` 的 `session_action` 白名单仅 `start | next | recover`：`start` 从第 1 页慢启动，`next` 在原标签前进，`recover` 只恢复当前待验证页，不能扩大安全例外。
- 首批约 30 张卡片稳定但分页控件未出现时，最多继续等待并滚动至 **8 秒**；真实 URL 仍须以同关键词相邻页验证，`href="javascript:;"`/`javascript:void(0)` 只能触发公开下一页的原生点击。
- 禁止深页 URL 回退只有一个安全例外，且只沿用 **2.2.2 相邻公开 URL 安全例外**：上一页必须 `ready + page_verified`、恰有 30 张有效卡片、公开下一页控件仍不存在，下一任务严格为同查询族 `+1`；只能在原标签导航到 `buildSearchUrl` 生成的同域同关键词相邻公开 URL，并验证目标页码和 SKU 集变化。不得新建深页标签、调用内部接口、跳页或重试风险页。

## 协议与投影白名单

- 当前 `protocol_version: 3`、`operation: search`；任务必须有 `session_action`，页码只允许 `1..512`，其他操作返回 `edge_operation_unsupported`。旧扩展、协议或投影返回不可重试的 `edge_extension_reload_required`，停止并要求重新加载。
- Edge 固定 **projection schema v4**（`projection_schema_version: 4`）和 `stable_card_fields_v2 + verified_pagination_v1 + resilient_pagination_v1`。
- 十一个诊断键精确为：`document_ready_state`、`data_sku_node_count`、`candidate_anchor_count`、`valid_item_count`、`collection_elapsed_ms`、`stable_rounds`、`observed_page_number`、`recovery_stage`、`recovery_attempt`、`source_path`、`pagination_dom`。不得增加自由正文、HTML、Cookie 或其他敏感键。
- JD 的 `source_path` 只允许 `/Search`；`pagination_dom` 只含 `#J_bottomPage` 是否存在、`.curr` 当前页和 `.pn-next` 的 href/onclick。结果同时携带 `observed_page_number`、`pagination_state`、`has_next_page`、`sku_digest`，请求页与观测页不一致则整批拒绝。
- `marketplace_candidates` 的 `card_fields_json` 只保存七个卡片键中的非空公开值；重复 SKU 只补原空字段，不覆盖已有非空值。
- `operation: detail` 只为后续公开详情定向补字段；详情域仅在 `optional_host_permissions`，启用前必须用户明确授权。详情吞吐与候选发现分开报告，且**不跟踪价格**、不保存价格历史。

## 600 秒持续窗口、吞吐与恢复

- 默认持续窗口 **600 秒**，不因候选线、单族失败、自然末页、页码 20 或一次 `pagination_session_missing` 提前结束。未知零卡片、SKU 停滞或投影暂不可用时，每逻辑页只允许一次两阶段软恢复：`reproject` 后同标签 `reload`；仍失败就放弃本族并轮换，不跳页、不第三试。
- 验证码、明确限流、风险处理重定向、登录失效和未知失败均失败关闭且不进入恢复；前四类立即阻断 JD 车道并保留 **60 分钟**客户端熔断。扩展/协议/桥接致命故障、用户取消或五个查询族均无法从第 1 页建立会话才可安全早停；最后一种必须为 `incomplete_blocked`。
- 纯搜索 600 秒另受默认墙钟安全上限 **900 秒**约束。轻量父 Python 只启动唯一子进程，看门狗等待为“最长 60 秒预检 + 配置墙钟 + 5 秒清理”；内部阻塞只终止自己创建的精确进程树，返回 `watchdog_wall_timeout`。若下一次等待+请求+2 秒清理放不进剩余墙钟，不再发请求并收口；达到墙钟上限而纯发现不足且无达标证据时必须失败且退出码非零。
- `ten_minute_limit` 只是停止条件；只有 `marketplace_discovery.decision.acceptance_passed=true` 才成功，零批次、零候选、仅超时或仅限流不能伪装达标。
- 去重候选身份为 `platform + SKU/product_id + title + canonical URL`。宽类正式验收从全新 SQLite/run/session 开始：默认 600 秒，至少 **6,000** 唯一候选、平均 **10 去重商品候选/秒**，且**任意连续 30 秒**不得零新增；计时不暂停、不重置、不延长。
- `marketplace_plan.jd_slow_lane=true` 时，零新增容忍为 **90 秒**，目标 **1 可复核卡片/秒（60/min）**，候选下限 **60**；零窗口只建议换查询族、不切来源。按允许节奏跑满窗口且字段齐全可达标，实际速度如实报告。
- 窄类只有查询生成器和所有健康 SearXNG/Edge/API 游标 exhausted、`blocked=0`、最后三批趋近零且无未尝试健康高收益族时，才可报告确定范围完成；登录、验证码、429 冷却、结构变化或权限拒绝存在时必须 incomplete/blocked。

## 慢速节奏、风控与跨运行

- `scripts/jd_pace.py` 保留 **45 秒慢启动**、**30 秒下限**、每页最多缩短 **25%** 和 **±35%** 抖动；慢页、连续空页和本地 worker 瞬态只在会话内有界退避。
- 真实限流、风险重定向或验证码让 `platform_health=blocked`；本轮不自动重开，60 分钟熔断阻止跨进程立即重试。`<ledger>.campaign.json` 强制两跑间隔 **≥1800s**、硬风控后 **≥3600s**，未到期 exit 3。
- 规模化只可用 `--append-ledger` 跨运行去重累积和 `--user-data-dir` 多 profile 分摊。profile 由 `scripts/launch_edge_profile.py` 以 `--load-extension`、`--disable-sync`、独立 `SEARCHING_AT_SCALE_PIPE_NAME` 和 `SAT_EDGE_PIPE_PATH` 启动；多 profile 不解决导航形态，不能写成绕风控。
- 2026-08-12 同机同 Edge/Cookie 对照表明风险主要与导航形态有关：人工首页→搜索正常，`about:blank` 直连缺 `from=home/pvid`/referer 时可能返回 200+正常标题但正文为风险页。因此 `human_flow`、降温、非高峰和慢节奏是风险控制；京东仍单通道、无代理、无账号池、不伪装指纹、不绕验证码。
- JD 冷却或硬阻断只影响 JD 车道，不得压低其他健康来源；网络发现可重叠，SQLite 批次保持单写入。
