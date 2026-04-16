$enc = [System.Text.Encoding]::GetEncoding(950);
$text = [System.IO.File]::ReadAllText('E:\RevitMCP\圖紙清單.csv', $enc);
[System.IO.File]::WriteAllText('E:\RevitMCP\圖紙清單_utf8.csv', $text, [System.Text.Encoding]::UTF8);
Write-Output 'Conversion Done'
