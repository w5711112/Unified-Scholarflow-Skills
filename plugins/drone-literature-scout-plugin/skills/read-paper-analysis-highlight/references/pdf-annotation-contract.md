# PDF 批注契约 V4

## 1. 目标

批注数量从来不是目标。每条批注必须是一个有独立信息价值的证据原子，并同时满足：

- 原文选择范围准确
- 批注说明证据在本文中真正支持什么
- 解释机制、意义、复现条件、疑点或边界，而非只翻译
- Zotero 中为原生、可编辑、可删除、无锁
- 文本和区域位置都经过读回与视觉复核

## 2. 文件级 schema

```json
{
  "schema_version": 4,
  "source_pdf": "annotation-free backup.pdf",
  "source_sha256": "...",
  "page_count": 8,
  "zotero_version": "9.0.6",
  "annotations": []
}
```

`schema_version >= 4` 时必须执行本契约的关系分组、评论质量、URL 可达性和双坐标检查；历史 schema v3 只兼容读取。

## 3. 文本证据原子

### 3.1 公共字段

```json
{
  "id": "paper-001-a001",
  "schema_version": 4,
  "page": 1,
  "annotation_type": "highlight",
  "selection_mode": "semantic-span",
  "quote": "complete source-language evidence",
  "context_before": "optional disambiguating text",
  "context_after": "optional disambiguating text",
  "occurrence": 1,
  "kind": "problem|motivation|method|theory|implementation|experiment|limitation|reuse|author-background",
  "color": "yellow|blue|purple|green|orange|red",
  "note_question": "这条证据回答什么问题？",
  "claim": "它支撑的精确主张",
  "reason": "为什么选择该范围",
  "information_roles": ["method", "mechanism"],
  "relation_group_id": "rel-001",
  "relation_role": "entity|predicate|effect|condition",
  "relation_type": "causes|constrains|solves|couples|improves|depends_on|contrasts_with",
  "relation_summary": "完整关系的可独立复述摘要",
  "connector_mode": "shared-id|native-ink",
  "evidence": "PDF第 1 页 / Introduction",
  "confidence": "high|medium|low",
  "annotation_comment": "结论：...\n机制：..."
}
```

定位器必须：

1. 在指定页按 PDF 词序匹配完整 `quote`
2. 零匹配时停止
3. 多匹配且无上下文或 `occurrence` 消歧时停止
4. 生成逐行 `quads`
5. 读回 `actual_text`
6. 规范化后的 `actual_text` 与 `quote` 不一致时停止
7. 将 `match_count`、`quads`、`actual_text` 写入 manifest

普通文本高亮禁止手填矩形。

### 3.2 selection_mode

#### `semantic-span`

- 用于完整技术句、因果句、贡献句、结论句或必要段落
- `quote`、`claim`、`reason` 都必须非空
- 范围应最小但足以重建完整技术关系

#### `key-term`

- 用于方法名、模块名、理论名、接口名或 baseline
- 单个词也允许，如 `YOPO`、`NavRL`
- 必须有 `context_summary` 和 `annotation_comment`
- 批注要说明它在本文中的角色，不得只写“这是一个方法”

#### `key-metric`

- 用于关键数值或小型数值组，如 `90.61 μs`、`13.06%`、`7.5 m/s`
- 必须有 `metric_context`、`condition` 和 `annotation_comment`
- 批注写清指标、单位、样本/场景/速度、对照以及能与不能说明什么

#### `key-link`

- 用于论文正文中的 DOI、GitHub、视频/演示、补充材料、项目页或数据集 URL
- `information_roles` 必须包含 `support_link`
- `quote` 必须是公开 HTTP(S) URL
- 必须记录 URL 可达性检查；403、429、Access denied、CAPTCHA 或登录墙视为不可交付

#### `author-name`

- 仅用于论文明确的一作、共同一作和通讯作者
- `kind` 必须为 `author-background`
- `information_roles` 必须包含 `author_context`
- 必须有 `author_context`、`external_evidence`、`external_sources`、`verified_at`
- 评论第一行必须以 `外部信息：` 开头

### 3.3 关系分组与最小真值范围

同一技术关系可以拆成多个精确片段，但必须通过同一个 `relation_group_id` 重建：

- `relation_role` 只能为 `entity`、`predicate`、`effect` 或 `condition`
- 每组至少一个 `predicate`，并至少包含一个 `entity/effect/condition` 参与者
- 一组只能有一个 `relation_type`；每条都有非空 `relation_summary`
- `quote` 删除 discourse scaffolding，例如 `Despite these advantages`、`however`、`moreover`、`therefore`；但否定、范围、模态、数值界限和成立条件若影响真值必须保留
- 短片段只有在关系组能还原主语—谓词—效果/条件，且评论说明分析意义时才合法；不能借关系分组放行空泛名词
- 使用 `validate_relation_groups()` 做组级验证，不能只逐条通过 `information_failures()`

连接方式：

- 默认 `connector_mode: shared-id`，靠共享 ID、统一颜色和互相引用的评论重建关系
- `connector_mode: native-ink` 只在 Zotero 原生 Ink 能力预检同时证明可编辑、可删除、坐标准确、刷新可见且 `text_overlap_verified: false` 时使用，并记录 `ink_native_key`
- 任一证明缺失都回退为 `shared-id`；禁止把箭头扁平化或烧录进源 PDF

## 4. 批注正文质量

普通证据：

```text
结论：这段证据在本文中支撑的精确判断。
机制：为什么会这样，或方法怎样起作用。
意义：它对理解、比较或复用的价值。
复现：必要参数、接口、条件或未报告项。
边界：不能据此推出什么。
疑点：缺失证据为何影响判断。
定位：PDF 第 N 页；章节/公式/图/表。
```

作者证据：

```text
外部信息：作者角色、当前身份与已核验背景；不是论文正文事实。
研究：方向、实验室、项目、代表成果及与本文关系。
荣誉：职称、奖项、人才项目、协会身份。
指标：Citations、H-index、来源和统计日期。
来源：可访问链接。
边界：同名消歧或无法公开核验的信息。
```

强制规则：

- 第一行只能以 `结论：` 或 `外部信息：` 开头
- 至少还有一行以 `机制：`、`意义：`、`复现：`、`边界：`、`疑点：`、`定位：`、`来源：`、`论文报告：`、`可以推断：` 或 `尚不能证明：` 开头
- **不设置字符上限**
- 禁止纯翻译、空泛评价和重复正文
- `evidence_gap` 必须明确写“未报告”“不能证明”“无法核验”等缺口
- 原文事实与分析推断必须分开

## 5. 区域批注 schema

区域只用于公式布局、算法框、图、表和无法由文本 quads 表达的视觉关系。
外部暂存中的 area 仅用于坐标渲染验收。Zotero 9 会忽略第三方 **PDF /Square**，普通第三方 **PDF /Ink**、`/FreeText` 与 image 也不能假定可原生导入；只有 Zotero 自身导出的特定格式可能例外。最终由 `scripts/build_zotero_native_annotation_plan.py` 把 area 映射为桥接协议的 `image`，不得把 PDF subtype 当作原生化路线。

```json
{
  "id": "paper-001-v001",
  "schema_version": 4,
  "page": 4,
  "annotation_type": "area",
  "selection_mode": "semantic-span",
  "coordinate_space": "pymupdf-page-top-left",
  "rect": [337.0, 659.0, 557.0, 694.0],
  "page_box": [0.0, 0.0, 594.0, 792.0],
  "page_rotation": 0,
  "zotero_coordinate_space": "pdf-page-bottom-left",
  "zotero_rect": [337.0, 98.0, 557.0, 133.0],
  "coordinate_round_trip_error": 0.0,
  "visual_object": "Equation 8 and its underbraced A_cbf and b_cbf terms",
  "kind": "theory",
  "color": "blue",
  "note_question": "公式 8 如何把安全约束写成控制输入线性不等式？",
  "claim": "左侧是沿障碍梯度的控制分量，右侧汇总速度惯性与 barrier 条件。",
  "reason": "公式二维布局及下括号关系无法由文本 quads 保留。",
  "information_roles": ["theory", "mechanism"],
  "evidence": "PDF第 4 页，公式 8",
  "confidence": "high",
  "annotation_comment": "结论：...\n机制：...\n定位：PDF 第 4 页，公式 8。"
}
```

### 5.1 双坐标空间

- PyMuPDF：`pymupdf-page-top-left`
- Zotero 原生 image position：`pdf-page-bottom-left`

未旋转页面的变换：

```text
zotero_rect = [
  x0,
  page_box_y0 + page_box_y1 - y1,
  x1,
  page_box_y0 + page_box_y1 - y0
]
```

要求：

- Zotero 写入只能使用 `zotero_rect`
- 正反向变换最大误差不超过 0.01 pt
- 两个矩形都必须位于 `page_box` 内且面积相等
- `page_rotation != 0` 时默认失败，除非有单独验证的旋转变换
- 每个 area 都要渲染并核对实际对象、框选范围与评论

## 6. 颜色语义

| 颜色 | 语义 |
|---|---|
| 黄色 | 问题、动机、定义、贡献或核心事实 |
| 蓝色 | 方法、架构、公式、理论、算法或接口 |
| 紫色 | 经外部核验的一作/共同一作/通讯作者背景 |
| 绿色 | 实验 setting、量化证据、对比、消融或结果 |
| 橙色 | 可复用设计、实现条件、工程机制或 support link |
| 红色 | 假设、局限、失败、证据缺口或过度外推风险 |

颜色不是优先级。不要为了颜色均衡而选低信息内容。

## 7. 外部暂存与覆盖

1. 从 annotation-free backup 开始
2. 验证 `%PDF-`、身份、页数与 SHA-256
3. 验证每条语义证据
4. 解析 quote/quads 或验证 area 双坐标
5. 写入同论文运行目录的临时 PDF
6. 重新打开，核对页数、位置、actual_text、评论和数量
7. 保留原始 backup；只有显式 `--overwrite` 才覆盖目标 PDF
8. 暂存阶段记录 `storage_mode = external-staging`

## 8. Zotero 原生化

外部 PDF 批注带锁，不算完成。原生写入只有一条路线：

1. 从已验证的 annotation manifest 调用 `scripts/build_zotero_native_annotation_plan.py`
2. builder 保留稳定 ID、`page_label`、`sort_index`、颜色、逐字评论与坐标；area 转成 `image`，文本 quads 转成 `highlight`
3. 用 `scripts/zotero_local_bridge_client.py` 调用 `GET /zotero-local-bridge/v1/health`，要求初始化、schema 与类型能力匹配
4. 调用 `POST /zotero-local-bridge/v1/annotations/preflight`；检查 create/update/delete/no-op、冲突、计划/快照 digest 与短期签名回执。预检不得写 Zotero
5. 冲突为空才调用 `POST /zotero-local-bridge/v1/annotations/apply`；请求携带同一计划、两个 digest 和回执
6. `apply` 必须在单一 Zotero 事务内执行并即时读回；核对 native keys、稳定 ID、完整指纹、类型、物理页、显示页码、排序、位置、颜色、评论和文本
7. 评论与 manifest 的 `annotation_comment` 逐字相等；清除本轮 AI 批注中的 `🔤…🔤`、机器翻译或其他自动翻译后缀后重新走受控 update/readback
8. 用同一路线修改一条受控评论或颜色并恢复，再创建并精确删除测试批注；禁止全附件删除、按评论模糊删除或触碰未知用户批注
9. 删除旧批次必须同时提供明确 native key、写入前完整指纹和允许 key；未知 key 数不为 0 时禁止删除
10. 响应丢失时重新 preflight；已有完整指纹必须返回 no-op，不能产生重复对象
11. 用 annotation-free backup 恢复 PDF 本体并确认 embedded/external annotation 数为 0；Zotero 原生子条目保留
12. 禁止回退到脚本控制台、前台鼠标输入或 SQLite

状态合同：

| 状态 | 调用方行为 |
|---|---|
| `400/422` | 修正 annotation plan，不原样重试 |
| `401/403` | 停止并检查 profile token/权限，不回退界面路线 |
| `404` | 修正 attachment 或 native key |
| `409` | 正常安全阻断；重新读取附件/manifest 后再生成计划，不持久化一次性冲突 |
| `500` | 要求事务回滚，记录最小技术证据并停止 |
| `503` | fresh health 已恢复时最多重试一次，否则停止 |

`read-paper-analysis-highlight` 拥有语义与效果验证；`zotero-local-bridge` 只做认证、预检、原子机械执行和原生读回；`global.collect-bug-update-accelerate` 只记录认证、版本、500、回滚/幂等回归或跨任务重复故障。
最终 manifest：

```json
{
  "storage_mode": "zotero-native",
  "native_annotation_keys": ["..."],
  "editable_verified": true,
  "deletable_verified": true,
  "locked_annotation_count": 0,
  "verified_at": "ISO-8601 timestamp"
}
```

任一位置错位、锁定、不可编辑、不可删除或数量不一致都阻止更新 Obsidian 完成状态。

## 9. URL 可达性

`key-link` 和作者外部来源必须记录：

```json
{
  "requested_url": "https://example.org/page",
  "final_url": "https://example.org/page",
  "status": 200,
  "checked_at": "2026-07-26T12:00:00+08:00",
  "accessible": true
}
```

URL 可达性只证明用户能够打开页面，不证明页面内容正确；事实仍需逐字段核对。
