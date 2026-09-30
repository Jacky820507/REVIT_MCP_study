$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition (Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot '../MCP/Core/DrainageReviewMath.cs'))
$cases = @(
    @('6" RP', 6.0), @('1/2"', 0.5), @('1 1/2"', 1.5),
    @(('3' + [char]0x540B), 3.0), @(('4' + [char]0x2033), 4.0), @('4 inch', 4.0),
    @('4" / 6"', $null), @('DN100', $null), @('0"', $null), @('1/0"', $null)
)
foreach ($case in $cases) {
    $actual = [RevitMCP.Core.DrainageReviewMath]::NominalInches($case[0])
    if ($actual -ne $case[1]) { throw "Size parsing failed: $($case[0]) => $actual" }
}
Write-Output "PASS: $($cases.Count) nominal-inch tests (not physical outside diameter)."
$directions = @(@('down','both',$true), @('down','down',$false), @('both','up',$true), @('up','both',$false), @('unknown','both',$null))
foreach ($case in $directions) {
    if ([RevitMCP.Core.DrainageReviewMath]::DirectionsConnect($case[0], $case[1]) -ne $case[2]) { throw 'Direction connection test failed' }
}
Write-Output "PASS: $($directions.Count) directional connection tests."
