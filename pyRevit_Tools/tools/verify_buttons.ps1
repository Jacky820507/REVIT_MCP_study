<#
.SYNOPSIS
    Pre-deploy regression gate for the Takeoff Excel buttons (and everything
    else the offline test suite covers).

.DESCRIPTION
    Collects three checks that, until 2026-09-01, only existed as one-off
    scripts in a session scratchpad and vanished when the session ended:

      1. Real IronPython 2.7.12 compile + Python-3-only construct scan,
         against every extension root (delegates to verify_ironpython.ps1).
      2. The full offline unittest suite under tests\ — ~1700+ cases,
         including the golden-regression tests (test_golden_regression.py)
         that diff every SheetLayout-migrated button's actual output
         (cells, formulas, merged ranges, column widths, COM call sequence)
         against tests\goldens\*.json, and the hand-written-address lint
         that scans the whole extension for Excel column letters that
         should have come from sheet_layout.py instead.
      3. A summary table, and a nonzero exit code if anything failed.

    This is a MANUAL entry point, run before copying anything into
    %APPDATA%\pyRevit\. It deliberately does NOT run on every edit — the
    existing PostToolUse hooks (ironpython-guard-hook.ps1,
    pyrevit-compile-gate-hook.ps1, pyrevit-test-runner-hook.ps1 in
    ~\.claude\scripts\) already do that per-edit, and running the full suite
    plus a real compile on every keystroke would be wasteful on top of what
    those hooks already cost.

    If you changed a button's actual output on purpose (not a refactor —
    a real formula/layout change), run tools\regen_goldens.py first and look
    at the diff before re-running this gate.

.PARAMETER SkipIronPython
    Skip the real-compile gate (use when the IronPython 2.7.12 engine isn't
    installed on this machine).

.PARAMETER IncludeMutationCheck
    Also run tools\mutation_check.py — deliberately reintroduces known
    regression shapes (the $V-column off-by-one, a skipped confirmation
    dialog, a backup taken after the write instead of before) into temporary
    copies of the source and asserts the test suite catches every one. This
    verifies the *tests* are worth trusting, not that today's code is
    correct, so it is opt-in rather than part of the default run: it is
    slower (each mutation re-imports a test module and runs unittest) and its
    useful cadence is "after adding a new wiring test" or "when in doubt
    about test quality", not "before every deploy".

.EXAMPLE
    .\pyRevit_Tools\tools\verify_buttons.ps1
.EXAMPLE
    .\pyRevit_Tools\tools\verify_buttons.ps1 -IncludeMutationCheck
#>
[CmdletBinding()]
param(
    [switch] $SkipIronPython,
    [switch] $IncludeMutationCheck
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $PSScriptRoot
$TestsDir = Join-Path $Root 'tests'
$ExtensionRoots = @(
    (Join-Path $Root 'MCP_Tools.extension'),
    (Join-Path (Split-Path -Parent $Root) 'dist\RcVolume.extension')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Container }

$results = New-Object System.Collections.Generic.List[pscustomobject]

function Add-Result([string]$Name, [bool]$Pass, [string]$Detail) {
    $results.Add([pscustomobject]@{ Name = $Name; Pass = $Pass; Detail = $Detail })
}

Write-Host '=== 1/2 IronPython 2.7 真編譯 gate ===' -ForegroundColor Cyan
if ($SkipIronPython) {
    Add-Result 'IronPython 2.7 compile' $true '(skipped by -SkipIronPython)'
} else {
    $ipyAllPassed = $true
    $ipyDetail = @()
    foreach ($extRoot in $ExtensionRoots) {
        $out = & (Join-Path $PSScriptRoot 'verify_ironpython.ps1') -ExtensionPath $extRoot 2>&1
        $code = $LASTEXITCODE
        $out | ForEach-Object { Write-Host $_ }
        if ($code -ne 0) {
            $ipyAllPassed = $false
            $ipyDetail += "$extRoot exit $code"
        }
    }
    Add-Result 'IronPython 2.7 compile' $ipyAllPassed ($ipyDetail -join '; ')
}

Write-Host ''
Write-Host '=== 2/2 離線測試套件（含 golden 回歸與欄位字母 lint）===' -ForegroundColor Cyan
Push-Location $TestsDir
try {
    $testOutput = & python -m unittest discover -s $TestsDir 2>&1
    $testCode = $LASTEXITCODE
} finally {
    Pop-Location
}
$testOutput | Select-Object -Last 12 | ForEach-Object { Write-Host $_ }
$summaryLine = ($testOutput | Select-String -Pattern '^Ran \d+ tests? in' | Select-Object -Last 1)
Add-Result 'python -m unittest (tests\)' ($testCode -eq 0) `
    ($(if ($summaryLine) { $summaryLine.ToString().Trim() } else { "exit $testCode" }))

if ($IncludeMutationCheck) {
    Write-Host ''
    Write-Host '=== +1 突變測試（-IncludeMutationCheck，選用）===' -ForegroundColor Cyan
    $mutOutput = & python (Join-Path $PSScriptRoot 'mutation_check.py') 2>&1
    $mutCode = $LASTEXITCODE
    $mutOutput | ForEach-Object { Write-Host $_ }
    $mutSummary = ($mutOutput | Select-String -Pattern '^\d+/\d+ ' | Select-Object -Last 1)
    Add-Result 'mutation_check.py' ($mutCode -eq 0) `
        ($(if ($mutSummary) { $mutSummary.ToString().Trim() } else { "exit $mutCode" }))
}

Write-Host ''
Write-Host '=== 結果 ===' -ForegroundColor Cyan
$anyFail = $false
foreach ($r in $results) {
    $mark = if ($r.Pass) { 'PASS' } else { 'FAIL'; $anyFail = $true }
    $color = if ($r.Pass) { 'Green' } else { 'Red' }
    Write-Host ("  {0,-32} {1,-5} {2}" -f $r.Name, $mark, $r.Detail) -ForegroundColor $color
}

if ($anyFail) {
    Write-Host ''
    Write-Host '未通過。修好上面列出的項目再部署——不要跳過這一步直接複製 DLL/腳本進 pyRevit。' -ForegroundColor Yellow
    exit 1
}

Write-Host ''
Write-Host '全部通過，可以部署。' -ForegroundColor Green
exit 0
