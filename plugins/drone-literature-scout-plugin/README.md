# 无人机文献研究插件

> 用途：把无人机论文的严格检索、Zotero 导入、全文精读、PDF 标注和 Obsidian 写作放进同一个可审计插件
<span style="background:#b1ffff">六个领域 skill 横向并列：通用网页调研、检索、导入、精读、Obsidian 表达和科研绘图各自保持清晰边界；治理能力通过稳定 global provider ID 解析</span>
## 先给结论
这是一个正式 Codex plugin，唯一入口为 `.codex-plugin/plugin.json`。完整功能由六个领域 sibling skills 组成：

| Skill                           | 输入                         | 输出                                  |
| ------------------------------- | -------------------------- | ----------------------------------- |
| `drone-literature-scout`        | 官方来源、现有论文库和算力/部署约束         | 可审计论文事实源与研究方向                       |
| `zotero-obsidian-paper-import`  | Obsidian 论文索引和核验后的 DOI/PDF | Zotero 父条目、真实附件和双链                  |
| `read-paper-analysis-highlight` | 已核验的 Zotero 正式 PDF         | 全文精读 callout、作者证据、知识双链和 Zotero 原生批注 |
| `obsidian-note-style`           | 需要新增或修改的中文研究笔记             | 标题、证据分层、视觉覆盖、链接与媒体集成                |
| `draw-style`                    | PPT、知识点、论文方法或数据图的语义要求与证据   | 跨场景科研绘图、提示词与视觉质量验收                  |
| `searching-at-scale`            | 跨来源网页、动态字段和用户调研问题          | 大规模候选发现、严格核验与可溯源调研收敛                |



当前插件位置：`skill-with-plugin/drone-literature-scout-plugin/`

## 京东后台分页入口

`searching-at-scale` 的 Edge 扩展 `2.3.1` 位于 `skills/searching-at-scale/edge-extension/`。首次安装或更新后，在 `edge://extensions` 开启开发人员模式，选择该目录“加载解压缩的扩展”；已安装时对同一份扩展点击“重新加载”，确认显示版本 2.3.1，不要并行加载第二份。

运行前先按 Skill 正文注册现有 Native Host 并执行桥接预检。启用真实分页时使用 `--enable-jd-pagination`（默认每话题 `2` 页、广度优先）；`--max-pages-per-topic auto` 解除上限、仅用于深翻实验。后台会话动作为 `start` / `next` / `recover`，查询族稳定轮换为 `topic → topic 自营 → topic 品牌 → topic 型号 → topic 新品`。多次运行共享同一账本时用 `--append-ledger` 累积去重，并受 campaign 闸门约束（两跑至少间隔 1800 秒，硬风控后 3600 秒）。带 `--user-data-dir` 的 profile 先用 `scripts/launch_edge_profile.py` 拉起（自动注入随包扩展、`--disable-sync` 隔离、独立命名管道，无需手工安装）。2026-08-12 实证（含用户手动对照）：京东风控是**导航形态级而非 IP 级**——同 IP/同浏览器/同 Cookie 下手动先逛首页再搜索就正常，直连 `Search?keyword=…&page=1` 就被风控；`--jd-pagination-route human_flow` 模拟人的导航形态（首页→`from=home` 搜索→点击 `.pn-next` 翻页）是主杠杆，多 profile 只摊行为预算。完整恢复、风险停止、证据和统计合同以 `skills/searching-at-scale/SKILL.md` 为准。

## 为什么横向组织

六个领域 skill 解决同一条研究链上的不同问题，不能互相替代：

- 论文库审计不能证明 Zotero 附件正确
- 附件导入不能替代全文阅读
- 全文阅读不能跳过证据与 PDF 原文的对应
- 表达风格不能改变 DOI、实验数字或安全结论的事实强度

流程为：

- 严格检索 ==`-->`== Zotero 导入 ==`-->`== 全文精读 ==`-->`== PDF 高亮与 Obsidian 总结

`searching-at-scale` 负责通用网页调研和候选发现；`obsidian-note-style` 负责中文表达和知识点视觉覆盖；`draw-style` 负责跨场景科研绘图与验收。`global.collect-bug-update-accelerate`、`global.migration-skill` 和 `global.renhua` 是外部治理提供方，不接管领域业务事实核验。

## 自动协作前置

插件任务开始或 Skill 清单变化时读取根 `references/skill-collaboration-contract.md`，动态枚举一次 `skills/` 下全部含 `SKILL.md` 的当前领域 Skill；同一任务内拓扑未变时不重复枚举。正常成功路径不写故障库；只有已知脆弱组件、失败路线或历史方案复用才进入 `global.collect-bug-update-accelerate` 的慢路径。只协同当前步骤需要的 Skill，不复制职责；新增、删除或改名时同步协作登记、唯一归属、动态测试与聚合总览。

## 聚合总览

六个领域的 canonical `SKILL.md` 是各自规则的唯一来源，`architecture-manifest.json` 只登记结构、接口、调用边和数值护栏。`Skill完整指南/Skill与Plugin的总体系说明.md` 只概括用途、输入输出、协作与边界；`Skill完整指南/research/` 中的完整指南由 canonical 与 references 单向生成，便于集中阅读，但不成为第二套规则源。

Skill 的职责或规则变化后，治理工具按来源哈希只更新聚合说明中受影响的职责段、来源标记和自动关系区；未变化的段落不重写，也不依赖常驻 watcher。若来源标记缺失、重复或过期，审计直接报告问题并停止把旧摘要当成当前说明。

## 用户语言风格触发

当用户说“使用我的 Obsidian 语言风格”“按我的 Obsidian 笔记风格写”或语义等价表达时，**必须调用** `obsidian-note-style`

该 skill 负责首次术语解释、短段落、表格、局部强调、精确链接，以及 **论文报告—可以推断—尚不能证明** 的证据分层。语言风格不会降低 venue 白名单、DOI、PDF、全文、实验和安全假设的核验标准

## 三个核心研究文件

| 文件 | 角色 | 写入边界 |
|---|---|---|
| `论文库统一.csv` | 唯一论文事实源 | 固定 15 列，摘要和官方来源必须完整 |
| `论文总结.md` | 全库统计与周期复盘 | 由事实源生成，不反向覆盖 CSV |
| `研究方向分析.md` | 方向池、排名、证据和实验建议 | 建议不能伪装成论文事实 |

## 边界

- 只接受白名单 venue、官方出版社记录、正式 proceedings 或 DOI 页面作为最终身份依据
- 未报告的训练时间、显存、功耗、参数量、Jetson 延迟和真实飞行结果写“未报告”
- 没有真实 Zotero PDF 附件时不得进入全文精读和覆盖标注
- PDF 覆盖前必须保留 SHA-256 备份并验证 annotation manifest
- 聚合说明不是第二套规则，任何冲突都以 canonical `SKILL.md` 及其强制 reference 为准

## 验证

```powershell
python -m unittest discover -s .\skill-with-plugin\drone-literature-scout-plugin\tests -v
```

交付前必须确认六个领域 Skill 的 canonical 入口、聚合说明、通用网页调研、科研绘图、Zotero 导入测试、PDF 标注测试和外部治理提供方合同都能独立核验
