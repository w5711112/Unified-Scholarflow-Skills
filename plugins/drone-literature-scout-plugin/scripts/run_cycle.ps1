param(
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [int]$MaxMinutes = 120,
    [int]$MaxNewPapers = 20,
    [int]$NoProgressAngles = 2
)

$ErrorActionPreference = 'Stop'
$PluginRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$AuditReport = Join-Path $env:TEMP ('drone-scout-audit-' + [guid]::NewGuid().ToString() + '.json')
$Csv = Join-Path $WorkspaceRoot '论文库统一.csv'
$Legacy = Join-Path $WorkspaceRoot '论文总库.md'

Write-Output '[Phase 0] 轮次预检与主库审计中...'
Write-Output ("[CONFIG] max_minutes=$MaxMinutes max_new_papers=$MaxNewPapers no_progress_angles=$NoProgressAngles")
python (Join-Path $PluginRoot 'scripts\audit_corpus.py') --csv $Csv --report $AuditReport --strict

if (Test-Path -LiteralPath $Legacy) {
    Write-Output '[STOP] 发现论文总库.md：必须先完成首轮双库合并与官方来源核验，暂不开始新搜索。'
    Write-Output ("[REPORT] $AuditReport")
    exit 2
}

Write-Output '[Phase 1] 全局统计与研究方向缺口分析交给 drone-literature-scout skill 执行...'
Write-Output '[Phase 2] 本入口不伪造网页搜索；由 Codex skill 使用可用 web/browser 工具核验官方页面。'
Write-Output '[Phase 3] 等待已核验候选写入主库后更新 Markdown 分析文件...'

python (Join-Path $PluginRoot 'scripts\clean_cycle.py') `
    --workspace $WorkspaceRoot `
    --plugin $PluginRoot `
    --core-file '论文库统一.csv' `
    --core-file '论文总结.md' `
    --core-file '研究方向分析.md'

$count = @(Import-Csv -LiteralPath $Csv -Encoding UTF8).Count
Write-Output ("[COMPLETE] local cycle plumbing finished; corpus_rows=$count; core_files=论文库统一.csv,论文总结.md,研究方向分析.md")
if (Test-Path -LiteralPath $AuditReport) {
    Remove-Item -LiteralPath $AuditReport -Force
}
Write-Output '[CLEANUP] transient audit report removed.'
