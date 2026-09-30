<#
.SYNOPSIS
    Detect whether pyRevit's compiled cache is stale, and clear it when it is
    safe to do so.

.DESCRIPTION
    Adding, renaming or deleting a .pushbutton folder leaves pyRevit's compiled
    extension DLL out of date. Revit then fails with
    「無法初始化增益集"<按鈕>"，因為在增益集組合中找不到類別 ...」, which reads
    like a code fault but is only a stale cache.

    Staleness is not guessed at here. The compiled DLL is read as text and each
    button folder on disk is looked for inside it — the same check
    domain/pyrevit-button-development.md documents. A button that is missing
    from the DLL is one Revit cannot start.

    Clearing requires Revit to be closed, because the DLL is locked while it
    runs. This script never closes Revit and never kills anything: if Revit is
    running it reports what is pending and stops, so the decision to close a
    session with unsaved work stays with the person who owns it.

.PARAMETER WhatIf
    Report only; never clear.

.EXAMPLE
    .\scripts\pyrevit-refresh.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$extension = Join-Path $repoRoot 'pyRevit_Tools\MCP_Tools.extension'
$pyRevitRoot = Join-Path $env:APPDATA 'pyRevit'

function Write-Section($text) {
    Write-Host ''
    Write-Host $text -ForegroundColor Cyan
    Write-Host ('-' * 60)
}

if (-not (Test-Path $extension)) {
    Write-Host "找不到 extension：$extension" -ForegroundColor Red
    exit 2
}

# --- 1. what is on disk -----------------------------------------------------

$buttons = @(Get-ChildItem $extension -Recurse -Directory -Filter '*.pushbutton' |
    ForEach-Object { $_.Name -replace '\.pushbutton$', '' })
$panels = @(Get-ChildItem $extension -Recurse -Directory -Filter '*.panel' |
    ForEach-Object { $_.Name -replace '\.panel$', '' })

Write-Section "磁碟上的按鈕"
Write-Host ("  {0} 個 .pushbutton，{1} 個 .panel" -f $buttons.Count, $panels.Count)

# --- 2. what the compiled caches know about ---------------------------------

$dlls = @(Get-ChildItem $pyRevitRoot -Recurse -Filter '*MCP_Tools.dll' `
    -ErrorAction SilentlyContinue)

Write-Section "pyRevit 編譯快取"
if ($dlls.Count -eq 0) {
    Write-Host "  沒有已編譯的 MCP_Tools.dll。" -ForegroundColor Green
    Write-Host "  代表 cache 已清空或尚未建立；重新啟動 Revit 就會重建，無須處理。"
    exit 0
}

$stale = @()
foreach ($dll in $dlls) {
    # ReadAllBytes rather than Get-Content: the DLL is binary, and the class
    # names are plain ASCII inside it.
    $text = [System.Text.Encoding]::ASCII.GetString(
        [System.IO.File]::ReadAllBytes($dll.FullName)).ToLower()
    $missing = @($buttons | Where-Object { -not $text.Contains($_.ToLower()) })
    Write-Host ("  {0}" -f $dll.FullName)
    Write-Host ("    修改時間：{0}" -f $dll.LastWriteTime)
    if ($missing.Count -eq 0) {
        Write-Host "    ✓ 所有按鈕都在這份 DLL 裡" -ForegroundColor Green
    } else {
        Write-Host ("    ✗ 缺少 {0} 個按鈕：{1}" -f $missing.Count,
            ($missing -join '、')) -ForegroundColor Yellow
        $stale += [pscustomobject]@{ Dll = $dll.FullName; Missing = $missing }
    }
}

if ($stale.Count -eq 0) {
    Write-Section "結論"
    Write-Host "  ✓ cache 是最新的，不需要清除。" -ForegroundColor Green
    Write-Host "  若按鈕仍然報錯，那就不是 cache 問題，要往程式碼查。"
    exit 0
}

# --- 3. clearing, only if Revit is not holding the files --------------------

$revit = @(Get-Process -Name 'Revit' -ErrorAction SilentlyContinue)

Write-Section "結論"
Write-Host "  ✗ cache 已過期，需要清除。" -ForegroundColor Yellow

if ($revit.Count -gt 0) {
    Write-Host ''
    Write-Host ("  Revit 仍在執行（PID {0}），DLL 被鎖住，現在無法清除。" -f
        (($revit | ForEach-Object { $_.Id }) -join ', ')) -ForegroundColor Yellow
    Write-Host '  請自行存檔並關閉 Revit，然後重跑這個指令：'
    Write-Host '      .\scripts\pyrevit-refresh.ps1' -ForegroundColor White
    exit 1
}

if (-not $PSCmdlet.ShouldProcess($pyRevitRoot, '清除 pyRevit cache')) {
    Write-Host '  （WhatIf：未實際清除）'
    exit 1
}

Write-Host ''
Write-Host '  Revit 未執行，開始清除…'
$cleared = $false
try {
    & pyrevit caches clear --all 2>&1 | Out-Null
    $cleared = $true
    Write-Host '  已執行 pyrevit caches clear --all' -ForegroundColor Green
} catch {
    Write-Host "  pyrevit CLI 失敗（$($_.Exception.Message)），改用手動刪除…" `
        -ForegroundColor Yellow
}

# Some pyRevit CLI builds report exit code 0 even when recursive deletion
# failed partway through (for example, an ACL-denied extension source file).
# Treat filesystem state as authoritative and use the documented scoped fallback.
$afterCli = @(Get-ChildItem $pyRevitRoot -Recurse -Filter '*MCP_Tools.dll' `
    -ErrorAction SilentlyContinue)
if ($cleared -and $afterCli.Count -gt 0) {
    Write-Host '  pyRevit CLI 未清除所有舊 DLL；改用快取目錄備援清理…' `
        -ForegroundColor Yellow
    $cleared = $false
}

if (-not $cleared) {
    $rootFull = [System.IO.Path]::GetFullPath($pyRevitRoot).TrimEnd('\') + '\'
    Get-ChildItem $pyRevitRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d{4}$' -or $_.Name -eq 'Cache' } |
        ForEach-Object {
            $targetFull = [System.IO.Path]::GetFullPath($_.FullName)
            if (-not $targetFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -or
                $targetFull -eq $rootFull.TrimEnd('\')) {
                throw "Refusing to clear path outside pyRevit cache root: $targetFull"
            }
            Write-Host ("  刪除 {0}" -f $targetFull)
            Remove-Item -LiteralPath $targetFull -Recurse -Force -ErrorAction Stop
        }
    $cacheDir = Join-Path $pyRevitRoot 'Cache'
    if (-not (Test-Path -LiteralPath $cacheDir)) {
        New-Item -ItemType Directory -Path $cacheDir | Out-Null
    }
}

# --- 4. verify ---------------------------------------------------------------

$left = @(Get-ChildItem $pyRevitRoot -Recurse -Filter '*MCP_Tools.dll' `
    -ErrorAction SilentlyContinue)
Write-Section "驗證"
if ($left.Count -eq 0) {
    Write-Host '  ✓ 已無殘留的 MCP_Tools.dll，cache 清除完成。' -ForegroundColor Green
    Write-Host '  重新啟動 Revit，pyRevit 會重建 cache（第一次開會比較慢，屬正常）。'
    exit 0
}

Write-Host '  ✗ 仍有殘留的 DLL：' -ForegroundColor Red
$left | ForEach-Object { Write-Host ("    {0}" -f $_.FullName) }
Write-Host '  請確認沒有其他行程佔用，再重跑一次。'
exit 1
