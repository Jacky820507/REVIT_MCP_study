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

$versionConfigMap = @{
    "2020" = "Release.R20"
    "2022" = "Release.R22"
    "2023" = "Release.R23"
    "2024" = "Release.R24"
    "2025" = "Release.R25"
    "2026" = "Release.R26"
}
$buildConfig = $versionConfigMap[$revitVersion]

$sourceDllRelease = Join-Path $projectRoot "MCP\bin\$buildConfig\RevitMCP.dll"
$sourceDllDebug = Join-Path $projectRoot "MCP\bin\Debug\RevitMCP.dll"
$sourceAddin = Join-Path $projectRoot "MCP\RevitMCP.addin"

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
