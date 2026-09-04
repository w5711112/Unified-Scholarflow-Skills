# 作者外部信息证据合同 V3

## 适用范围

每篇论文只调查论文作者行、脚注或贡献声明明确标出的一作、共同一作和通讯作者。指定角色有多人时全部纳入；先完成姓名、机构、实验室和研究方向消歧，再写背景信息。

外部履历不能冒充论文正文事实。PDF 作者姓名批注统一以：

```text
外部信息：
```

开头。

## 顶层结构

```json
{
  "author_research_schema_version": 3,
  "paper_id": "paper-001",
  "verified_at": "2026-07-26",
  "designated_authors": [],
  "authors": []
}
```

`verified_at` 使用合法 ISO 日期或日期时间。`designated_authors` 与 `authors` 中的姓名集合及每位作者的角色集合必须完全一致；同一作者的多个角色合并在一个对象中。

## 每位作者的必需字段

```json
{
  "name": "Fei Gao",
  "roles": ["corresponding_author"],
  "education": {},
  "current_position": {},
  "qs_ranking": {},
  "scholar": {},
  "memberships": {},
  "standing_assessment": {},
  "research_areas": {},
  "lab": {},
  "projects": {},
  "honors": {},
  "representative_outputs": {},
  "bibliometrics": {},
  "metric_source": "Google Scholar|OpenAlex|Semantic Scholar|AD Scientific Index|not_verified",
  "url_checks": []
}
```

### 应调查的信息

- 本科、硕士、博士院校、专业和时间
- 当前大学、学院、实验室、职称和导师资格
- 当前机构的 QS 排名、版本和查询日期
- Google Scholar Citations、H-index 和查询日期
- IEEE、ACM 等 Fellow、Senior Member、Member 会籍
- 研究方向及其与当前论文的关系
- 主要科研项目、荣誉、头衔和代表性成果
- 无法访问 Google Scholar 时的替代计量信息
- 是否可谨慎判断为该领域高影响力研究者

## 证据状态

普通证据字段允许：

- `verified`
- `not_publicly_verified`
- `not_applicable`
- `inference`

已核验事实：

```json
{
  "status": "verified",
  "value": "浙江大学控制科学与工程学院长聘副教授、博士生导师",
  "sources": ["https://person.zju.edu.cn/fgaoaa"]
}
```

无法公开核验：

```json
{
  "status": "not_publicly_verified",
  "searched_sources": ["https://person.zju.edu.cn/fgaoaa"]
}
```

未知值不能写成 `0`、空字符串或根据同名人物补全。

## 来源优先级

1. 学校、学院、实验室、基金或学会官方页面
2. 官方简历、学位论文、出版社作者简介
3. 身份唯一且可正常访问的 Google Scholar
4. ORCID、OpenReview 等作者控制或学术身份页面
5. OpenAlex、Semantic Scholar、AD Scientific Index 等替代计量平台

搜索摘要、百科、营销聚合站和同名人物页面不能单独支持正面事实。替代计量平台只能支撑明确标注平台名与查询日期的动态指标，不能替代学校或学会官方页面证明履历、职位、荣誉或会籍。

## 链接可访问性

每个输出来源必须实际请求并记录：

```json
{
  "requested_url": "https://person.zju.edu.cn/fgaoaa",
  "final_url": "https://person.zju.edu.cn/fgaoaa",
  "status_code": 200,
  "checked_at": "2026-07-26",
  "accessible": true
}
```

规则：

- `verified.sources` 中每个 URL 必须有 `accessible=true` 的 `url_checks` 记录
- `403`、`429`、CAPTCHA、Access Denied 或机器人验证页不能标为可访问
- Google Scholar 被拒绝访问时，不得作为唯一可点击来源
- 无法核验 Google Scholar 指标时，`scholar.status` 写 `not_publicly_verified`
- OpenAlex、Semantic Scholar 或 AD Scientific Index 数字只能写入 `bibliometrics`，并把 `metric_source` 写成真实平台名称
- 不能把替代平台的引用量和 H-index 标成 Google Scholar 指标

使用：

```powershell
python scripts/check_evidence_urls.py URL [URL ...]
```

## 动态指标

- `scholar.status=verified` 时必须包含 `as_of`，且 `metric_source` 必须为 `Google Scholar`
- `bibliometrics.status=verified` 时必须包含平台、查询日期和可访问来源，`metric_source` 必须为 `OpenAlex`、`Semantic Scholar` 或 `AD Scientific Index`
- `qs_ranking.status=verified` 时必须包含 `edition`

## 影响力判断

“领域大牛”“高影响力研究者”等不是官方事实，只能放在：

```json
{
  "status": "inference",
  "basis": "依据官方履历中的代表作、项目、奖项、任职和可核验计量信息作出的谨慎综合判断。"
}
```

不得把该判断写成 `verified`。

## PDF 批注内容

作者姓名批注可以较长，不设置字符上限。建议结构：

```text
外部信息：作者角色、当前职位、实验室和主要研究方向。
履历：可核验的教育或任职经历。
成果与影响：代表作、项目、奖项、会籍和带日期的计量信息。
与本文关系：其长期研究如何连接当前论文，但不把履历当成本文方法证据。
缺失：未从可靠公开来源核验的学历、会籍或 Scholar 信息。
来源：可正常访问的官方链接；核验日期。
```

## 交付位置与禁止项

作者外部信息只交付到三个位置，三处可以详略不同，但事实、日期、角色和不确定性边界必须一致：

- 当前论文折叠“作者与团队背景”：保留角色、经核验履历、与本文关系、客观影响力证据及未核验字段
- PDF 作者姓名批注：以“外部信息：”开头，并给出可访问来源和核验日期
- 当前论文内部作者调研 JSON：保存完整结构化证据、URL 检查与动态指标日期

**不得创建独立作者/团队笔记**、实验室人物库或作者知识枢纽，也不得把作者履历写入通用知识主笔记。同一作者跨论文出现时，各篇仍保留本篇所需且经重新核验的充分背景，并突出作者与该篇论文的具体关系。

## 验证

```powershell
python scripts/validate_author_research.py path/to/author-research.json
```

有效输入输出：

```json
{"valid": true, "errors": []}
```

无效 UTF-8、JSON 或合同输入必须返回受控错误，不显示 traceback。
