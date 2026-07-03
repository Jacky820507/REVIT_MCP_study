#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-SafePath {
    param ([Parameter(Mandatory = $true)][string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    return $true
}

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "   Revit MCP Add-in Auto Installer" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan

$scriptDir = $PSScriptRoot
if ([string]::IsNullOrEmpty($scriptDir)) {
    $scriptDir = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
}
$projectRoot = Split-Path -Parent -Path $scriptDir
$projectRoot = (Resolve-Path $projectRoot).Path

$appDataPath = $env:APPDATA
$revitVersion = $null
$addonPath = $null
$foundVersions = @()
$supportedVersions = @("2026", "2025", "2024", "2023", "2022", "2020")

foreach ($version in $supportedVersions) {
    if (Test-Path (Join-Path $appDataPath "Autodesk\Revit\Addins\$version")) {
        $foundVersions += $version
    }
}

if ($foundVersions.Count -gt 0) {
    $revitVersion = $foundVersions[0] # Default to first found
    $addonPath = Join-Path $appDataPath "Autodesk\Revit\Addins\$revitVersion"
} else {
    Write-Host "No Revit installed." -ForegroundColor Red
    exit 1
}

Write-Host "Installing to Revit $revitVersion ($addonPath)"

Write-Host ""
Write-Host "✓ 將安裝到 Revit $revitVersion" -ForegroundColor Green
Write-Host "✓ Add-in 路徑：$addonPath" -ForegroundColor Green
Write-Host ""

# ============================================================================
# 安全檢查 3：驗證來源檔案
# ============================================================================

Write-Host "正在驗證來源檔案..." -ForegroundColor Yellow
Write-Host ""

# 版本→組態對應表（統一建構，所有版本使用同一個 csproj）
# ⚠️ 必須在 $sourceDllRelease 之前求值，否則 Strict Mode 下 $buildConfig 未定義
$versionConfigMap = @{
    "2020" = "Release.R20"
    "2022" = "Release.R22"
    "2023" = "Release.R23"
    "2024" = "Release.R24"
    "2025" = "Release.R25"
    "2026" = "Release.R26"
}
$buildConfig = $versionConfigMap[$revitVersion]

# 定義來源檔案路徑 (統一建構：Nice3point.Revit.Sdk)
# ⚠️ 本專案只使用 RevitMCP.csproj + RevitMCP.addin（統一多版本建構）
# ⚠️ 禁止新增 RevitMCP.2024.csproj / RevitMCP.2024.addin 等版本特定檔案
$sourceDllRelease = Join-Path $projectRoot "MCP\bin\$buildConfig\RevitMCP.dll"
$sourceDllDebug = Join-Path $projectRoot "MCP\bin\Debug\RevitMCP.dll"
$sourceAddin = Join-Path $projectRoot "MCP\RevitMCP.addin"

# 決定使用哪個 DLL
$sourceDll = $null

$sourceDll = $null
if (Test-Path $sourceDllRelease) {
    $sourceDll = $sourceDllRelease
} elseif (Test-Path $sourceDllDebug) {
    $sourceDll = $sourceDllDebug
} else {
    Write-Host "Error: RevitMCP.dll not found. Please build first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $addonPath)) {
    New-Item -ItemType Directory -Path $addonPath -Force | Out-Null
}

$pluginFolder = Join-Path $addonPath "RevitMCP"
if (-not (Test-Path $pluginFolder)) {
    New-Item -ItemType Directory -Path $pluginFolder -Force | Out-Null
}

try {
    Copy-Item -Path $sourceDll -Destination (Join-Path $pluginFolder "RevitMCP.dll") -Force -ErrorAction Stop
    Copy-Item -Path $sourceAddin -Destination (Join-Path $addonPath "RevitMCP.addin") -Force -ErrorAction Stop
    Write-Host "Install completed successfully!" -ForegroundColor Green
} catch {
    Write-Host "Install failed: $_" -ForegroundColor Red
    exit 1
}

# 複製相依套件（如果存在）
$sourceJson = Join-Path $projectRoot "MCP\bin\$buildConfig\Newtonsoft.Json.dll"
if (Test-Path $sourceJson) {
    try {
        Copy-Item -Path $sourceJson -Destination (Join-Path $addonPath "Newtonsoft.Json.dll") -Force -ErrorAction Stop
        Write-Host "✓ 已複製 Newtonsoft.Json.dll" -ForegroundColor Green
    }
    catch {
        Write-Host "⚠️  警告：無法複製 Newtonsoft.Json.dll（非關鍵檔案）" -ForegroundColor Yellow
    }
}

# 複製 Python worker（柱號對應功能 ezdxf_worker.py → %APPDATA%\RevitMCP）
# DwgColumnExecutor.FindWorkerScript 會在 dll 同層 → 開發樹 → %APPDATA%\RevitMCP 依序尋找；
# 部署版的 dll 在 Add-ins 目錄，故 worker 須落在 %APPDATA%\RevitMCP 才找得到。
$sourceWorker = Join-Path $projectRoot "bridge\python\skills\ezdxf_worker.py"
if (Test-Path $sourceWorker) {
    $workerDir = Join-Path $appDataPath "RevitMCP"
    try {
        if (-not (Test-Path $workerDir)) { New-Item -ItemType Directory -Path $workerDir -Force | Out-Null }
        Copy-Item -Path $sourceWorker -Destination (Join-Path $workerDir "ezdxf_worker.py") -Force -ErrorAction Stop
        Write-Host "✓ 已部署 ezdxf_worker.py 到 $workerDir" -ForegroundColor Green
        Write-Host "  （柱號對應 textLayerName 需系統 Python + 'pip install ezdxf'；DWG 另需 ODA File Converter）" -ForegroundColor Gray
    }
    catch {
        Write-Host "⚠️  警告：無法部署 ezdxf_worker.py（柱號對應功能將無法使用，非關鍵）" -ForegroundColor Yellow
    }
}

Write-Host ""

# ============================================================================
# 安裝完成
# ============================================================================

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "   ✓ 安裝完成！" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "安裝摘要：" -ForegroundColor Cyan
Write-Host "  - Revit 版本：$revitVersion" -ForegroundColor White
Write-Host "  - 安裝路徑：$addonPath" -ForegroundColor White
Write-Host ""
Write-Host "接下來的步驟：" -ForegroundColor Cyan
Write-Host "  1. 完全關閉 Revit（如果正在執行）" -ForegroundColor White
Write-Host "  2. 重新開啟 Revit" -ForegroundColor White
Write-Host "  3. 應該會看到「MCP Tools」面板" -ForegroundColor White
Write-Host "  4. 點擊「MCP 服務 (開/關)」啟動服務" -ForegroundColor White
Write-Host ""
Write-Host "如有問題，請參考 README.md 的「常見問題」章節" -ForegroundColor Cyan
Write-Host ""

Read-Host "按 Enter 結束"
