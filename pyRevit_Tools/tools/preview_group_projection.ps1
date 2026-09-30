# Render using Windows PowerShell (STA) or pwsh -STA.
<# Render the real XAML with illustrative data, without Revit or a shown window.
   This checks WPF layout only, never Revit geometry or Python event binding. #>
param([string]$OutputPath = "$PSScriptRoot\..\group-projection-ui-preview.png")
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
$xamlPath = Join-Path $PSScriptRoot '..\MCP_Tools.extension\lib\GroupProjection.xaml'
[xml]$markup = Get-Content -LiteralPath $xamlPath -Raw -Encoding UTF8
foreach ($node in $markup.SelectNodes('//*')) {
    foreach ($eventName in @('Click', 'TextChanged')) { $node.RemoveAttribute($eventName) }
}
$reader = New-Object System.Xml.XmlNodeReader $markup
$window = [System.Windows.Markup.XamlReader]::Load($reader)
$window.FindName('targetLabel').Text = "範例：五層排水平面圖`n5F · 目前投影目標"
$window.FindName('picker').Content = '已勾選 3 個群組 ▾'
$window.FindName('status').Text = '範例：3 個群組已投影；色票列可查看來源。'
$samples = @(
    @('↑ 上方 R1F · 屋突排水', '#DC3C28', '來源：屋突一層排水平面圖'),
    @('↑ 上方 RF · 屋頂落水頭', '#EB7823', '來源：屋頂排水平面圖'),
    @('↓ 下方 4F · 四層排水', '#2864DC', '來源：四層排水平面圖')
)
foreach ($sample in $samples) {
    $row = New-Object System.Windows.Controls.StackPanel
    $row.Orientation = 'Horizontal'
    $row.Margin = '0,0,0,12'
    $chip = New-Object System.Windows.Controls.Border
    $chip.Width = 16; $chip.Height = 16; $chip.Margin = '0,2,10,0'
    $chip.Background = [System.Windows.Media.BrushConverter]::new().ConvertFromString($sample[1])
    $label = New-Object System.Windows.Controls.TextBlock
    $label.Text = $sample[0] + "`n" + $sample[1] + ' · ' + $sample[2]
    $null = $row.Children.Add($chip)
    $null = $row.Children.Add($label)
    $null = $window.FindName('legend').Children.Add($row)
}
$root = $window.Content
$window.Content = $null
$root.Resources = $window.Resources
$border = New-Object System.Windows.Controls.Border
$border.Background = $window.Background
$border.Child = $root
$border.Measure([System.Windows.Size]::new(490, 620))
$border.Arrange([System.Windows.Rect]::new(0, 0, 490, 620))
$border.UpdateLayout()
$bitmap = [System.Windows.Media.Imaging.RenderTargetBitmap]::new(490, 620, 96, 96, [System.Windows.Media.PixelFormats]::Pbgra32)
$bitmap.Render($border)
$encoder = New-Object System.Windows.Media.Imaging.PngBitmapEncoder
$encoder.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
$output = [System.IO.File]::Create([System.IO.Path]::GetFullPath($OutputPath))
try { $encoder.Save($output) } finally { $output.Dispose(); $window.Close() }
Write-Output "WPF preview (illustrative, not live Revit): $OutputPath"
