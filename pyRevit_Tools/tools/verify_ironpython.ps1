<#
.SYNOPSIS
    Compatibility gate for pyRevit button scripts that run on IronPython 2.7.

.DESCRIPTION
    Buttons under MCP_Tools.extension have no `#! python3` shebang, so pyRevit
    executes them with its default IPY2712PR engine (IronPython 2.7.12), not
    CPython. Editing them with CPython 3 habits produces code that imports and
    unit-tests fine on a dev box and then throws at ribbon-click time.

    Two checks:
      1. Compile every .py in the extension with the real 2.7 engine.
      2. Grep for constructs that only exist on Python 3.

    Do NOT substitute the sibling IPY342 (IronPython 3.4.2) engine: it accepts
    things 2.7 rejects, so a pass there proves nothing.

.PARAMETER ExtensionPath
    Extension root to scan. Defaults to the repo's MCP_Tools.extension.

.PARAMETER SkipCompile
    Run only the Python 3 construct scan (use when the engine is unavailable).

.EXAMPLE
    .\pyRevit_Tools\tools\verify_ironpython.ps1
#>
[CmdletBinding()]
param(
    [string] $ExtensionPath,
    [switch] $SkipCompile
)

$ErrorActionPreference = 'Stop'

if (-not $ExtensionPath) {
    $ExtensionPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'MCP_Tools.extension'
}
if (-not (Test-Path $ExtensionPath)) {
    Write-Error "Extension path not found: $ExtensionPath"
    exit 2
}

$files = Get-ChildItem -Path $ExtensionPath -Recurse -Filter '*.py' -File |
    Where-Object { $_.FullName -notmatch '\\__pycache__\\' }

Write-Output "IronPython 2.7 compatibility gate"
Write-Output "  extension : $ExtensionPath"
Write-Output "  files     : $($files.Count)"
Write-Output ''

$failures = 0

# ---------------------------------------------------------------- check 1
if (-not $SkipCompile) {
    $flavour = if ($PSVersionTable.PSEdition -eq 'Core') { 'netcore' } else { 'netfx' }
    $engineDir = Join-Path $env:APPDATA "pyRevit-Master\bin\$flavour\engines\IPY2712PR"

    if (-not (Test-Path (Join-Path $engineDir 'pyRevitLabs.IronPython.dll'))) {
        Write-Output "  SKIP  compile - IPY2712PR engine not found at $engineDir"
        Write-Output '        (install pyRevit, or rerun with -SkipCompile to scan only)'
        $engineDir = $null
    }

    if ($engineDir) {
        foreach ($dll in @('pyRevitLabs.Microsoft.Scripting.dll',
                           'pyRevitLabs.Microsoft.Dynamic.dll',
                           'pyRevitLabs.IronPython.dll',
                           'pyRevitLabs.IronPython.Modules.dll')) {
            Add-Type -Path (Join-Path $engineDir $dll)
        }
        $engine = [IronPython.Hosting.Python]::CreateEngine()
        $version = $engine.Setup.DisplayName
        Write-Output "[1/2] Compile with $version"

        foreach ($file in $files) {
            try {
                $null = $engine.CreateScriptSourceFromFile($file.FullName).Compile()
            }
            catch {
                $relative = $file.FullName.Substring($ExtensionPath.Length).TrimStart('\')
                $message = $_.Exception.Message -split "`n" | Select-Object -First 1
                Write-Output "  FAIL  $relative"
                Write-Output "        $message"
                $failures++
            }
        }
        if ($failures -eq 0) { Write-Output "  PASS  all $($files.Count) files compile" }
        Write-Output ''
    }
}

# ---------------------------------------------------------------- check 2
Write-Output '[2/2] Python 3 only constructs'

$patterns = @(
    @{ Rx = '\b(?:max|min)\s*\([^)]*\bdefault\s*=' ; Why = 'max/min default= is Python 3.4+' },
    # Must stay case-sensitive and reject a quote/brace before the f, or
    # ['f'], 'F' and u'{}F' all read as f-string prefixes.
    @{ Rx = '(?<![\w"''}])f[rRbB]?["'']'           ; Why = 'f-string is Python 3.6+' },
    @{ Rx = '\bnonlocal\b'                         ; Why = 'nonlocal is Python 3' },
    @{ Rx = '\byield\s+from\b'                     ; Why = 'yield from is Python 3' },
    @{ Rx = '\.casefold\s*\('                      ; Why = 'str.casefold is Python 3' },
    @{ Rx = '\bmath\.isclose\s*\('                 ; Why = 'math.isclose is Python 3.5+' },
    @{ Rx = '\bsuper\s*\(\s*\)'                    ; Why = 'zero-arg super() is Python 3' },
    @{ Rx = '\bexist_ok\s*='                       ; Why = 'makedirs(exist_ok=) is Python 3' },
    @{ Rx = '\bsubprocess\.run\b'                  ; Why = 'subprocess.run is Python 3.5+' },
    @{ Rx = '->\s*\w+\s*:'                         ; Why = 'return annotation is Python 3' },
    @{ Rx = '^\s*def\s+\w+\s*\([^)]*\*\s*,'        ; Why = 'keyword-only args are Python 3' }
)

foreach ($file in $files) {
    $lineNumber = 0
    $usesTrueDivision = $false
    $lines = Get-Content -LiteralPath $file.FullName -Encoding UTF8
    foreach ($line in $lines) {
        if ($line -match 'from __future__ import .*\bdivision\b') { $usesTrueDivision = $true }
    }
    $inDocstring = $false
    foreach ($line in $lines) {
        $lineNumber++
        if ($line.TrimStart().StartsWith('#')) { continue }

        # Skip triple-quoted blocks: prose there is not code, and it produced
        # false positives (a docstring saying "1/2/3" read as int division).
        $fences = ([regex]::Matches($line, '"""|''''''')).Count
        if ($inDocstring) {
            if ($fences % 2 -eq 1) { $inDocstring = $false }
            continue
        }
        if ($fences % 2 -eq 1) { $inDocstring = $true; continue }
        if ($fences -ge 2) { continue }
        foreach ($p in $patterns) {
            if ($line -cmatch $p.Rx) {
                $relative = $file.FullName.Substring($ExtensionPath.Length).TrimStart('\')
                Write-Output "  FAIL  ${relative}:$lineNumber  $($p.Why)"
                Write-Output "        $($line.Trim())"
                $failures++
            }
        }
        # Integer/integer division floors on Python 2 without the future import.
        if (-not $usesTrueDivision -and $line -cmatch '(?<![\d.\w])\d+\s*/\s*\d+(?![\d.])') {
            $relative = $file.FullName.Substring($ExtensionPath.Length).TrimStart('\')
            Write-Output "  WARN  ${relative}:$lineNumber  int/int floors on Python 2"
            Write-Output "        $($line.Trim())"
        }
    }
}

if ($failures -eq 0) { Write-Output '  PASS  no Python 3 only constructs' }

Write-Output ''
if ($failures -gt 0) {
    Write-Output "RESULT: FAILED ($failures)"
    exit 1
}
Write-Output 'RESULT: PASSED'
exit 0
