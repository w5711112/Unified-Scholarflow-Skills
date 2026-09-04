param(
    [switch]$Register,
    [switch]$RegisterExisting
)

$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path -Parent $PSScriptRoot
$hostRoot = Join-Path $skillRoot 'native-host'
$sourcePath = Join-Path $hostRoot 'SearchingAtScaleNativeHost.cs'
$hostPath = Join-Path $hostRoot 'SearchingAtScaleNativeHost.v2.exe'
$manifestPath = Join-Path $hostRoot 'com.codex.searching_at_scale.json'
$extensionId = 'ackhakolgkcedgagblkfbjfnkceplcop'
$registryKey = 'HKCU:\SOFTWARE\Microsoft\Edge\NativeMessagingHosts\com.codex.searching_at_scale'

if ($RegisterExisting) {
    if (-not (Test-Path -LiteralPath $hostPath -PathType Leaf)) {
        throw 'edge_native_host_existing_binary_missing'
    }
} else {
    if (Test-Path -LiteralPath $hostPath) {
        Remove-Item -LiteralPath $hostPath -Force
    }

    # 使用系统自带 .NET Framework 编译器，不下载 SDK 或常驻服务。
    $compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    $webExtensions = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Web.Extensions.dll'
    $systemCore = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Core.dll'
    if (
        -not (Test-Path -LiteralPath $compiler) `
        -or -not (Test-Path -LiteralPath $webExtensions) `
        -or -not (Test-Path -LiteralPath $systemCore)
    ) {
        throw 'edge_native_host_compiler_unavailable'
    }
    & $compiler `
        /nologo `
        /nowin32manifest `
        /target:exe `
        "/reference:$webExtensions" `
        "/reference:$systemCore" `
        "/out:$hostPath" `
        $sourcePath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $hostPath)) {
        throw 'edge_native_host_compile_failed'
    }
}

$manifest = [ordered]@{
    name = 'com.codex.searching_at_scale'
    description = 'Searching at Scale Edge public marketplace projection bridge'
    path = $hostPath
    type = 'stdio'
    allowed_origins = @("chrome-extension://$extensionId/")
}
$manifestJson = $manifest | ConvertTo-Json -Depth 3
$utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8NoBom)

if ($Register -or $RegisterExisting) {
    New-Item -Path $registryKey -Force | Out-Null
    Set-Item -Path $registryKey -Value $manifestPath
}

[ordered]@{
    host_path = $hostPath
    manifest_path = $manifestPath
    extension_id = $extensionId
    registered = [bool]($Register -or $RegisterExisting)
    reused_existing = [bool]$RegisterExisting
} | ConvertTo-Json -Compress
