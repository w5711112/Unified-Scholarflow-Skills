# 核心文件格式

## 论文库统一.csv

CSV 必须使用 UTF-8 或 UTF-8-SIG 编码，并且严格固定为以下 15 列，顺序不可改变：

title,venue_time,source,abstract,url,citation,lab_group,doi,abstract_source_url,fulltext_status,fulltext_url,method_evidence,compute_evidence,experiment_evidence,verification_date

- abstract 必须是完整原始摘要，不得改写；abstract_source_url 必须是提供摘要的官方出版社、会议 proceedings 或 DOI 页面。
- fulltext_status 只能是 reviewed_open_access、reviewed_official、abstract_only 或 needs_access。
- 只有 reviewed_open_access 或 reviewed_official，同时存在直接 fulltext_url 和对应证据字段时，才能记录参数量、训练时间、显存、延迟、功耗、控制频率或实验数字。
- method_evidence、compute_evidence、experiment_evidence 是证据列，禁止出现连续问号占位符、U+FFFD 替换字符或把日期错写到 experiment_evidence。
- verification_date 永远是最后一列，格式为 YYYY-MM-DD；日期不得通过手工拼接放入其他字段。
- 标题中的正常问号可以保留；证据列中的问号占位符必须让结构化校验失败。
- 所有字段必须由 csv.DictWriter 使用 UTF-8/UTF-8-SIG 写入，禁止通过 ANSI 控制台、默认编码管道或复制粘贴表格写入。
- 每次写入后运行 corpus_tools.validate_csv_file；审计、清理和 Markdown 生成都必须在校验通过后进行。

## 论文总结.md

使用中文保留全库规模、venue/年份/实验室统计、证据覆盖、严格检索记录、拒收和待核验说明、搜索策略复盘及总体结论。论文原题、venue、算法名、硬件名、URL、DOI 可以保持原文，但固定模板标题和说明必须为中文。

## 研究方向分析.md

使用中文保留动态方向池、两位小数评分、硬门槛、技术路线、证据表、全文支持的定量可行性、最小可行实验和明确证据缺口。方向只能来自全库动态评分，不能为了填满名额而固定保留。链接到 CSV 官方记录，不复制长摘要。

## 生成和退出检查

生成器不得输出英文固定模板标题，例如 Strict search cycle log、This-cycle evidence table、Scheme A top-direction snapshot、Scheme A preference gates 和 Isaac Lab minimum viable route；对应内容必须用中文。周期结束后只保留三个核心研究文件，插件源代码、技能说明和计划文档受保护。
