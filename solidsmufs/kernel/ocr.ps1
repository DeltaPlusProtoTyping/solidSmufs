# Reads the text in images with the OCR engine built into Windows 10/11 (Windows.Media.Ocr).
# Runs locally, nothing is sent anywhere. Usage: powershell -File ocr.ps1 <image> [<image> ...]
# Prints one JSON line per image as soon as it's read: {"i": 0, "lines": [{"text", "x", "y", "w", "h"}, ...]}
# (so the caller can show progress), then {"done": true, "lang": "en-US"}.
param([Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Images)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($op, [Type]$type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $t.Wait() | Out-Null
    $t.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw "Windows has no OCR language installed (Settings > Time & Language > Language)." }
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$i = 0
foreach ($image in $Images) {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $image).Path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = foreach ($line in $result.Lines) {
        $xs = $line.Words | ForEach-Object { $_.BoundingRect }
        $x0 = ($xs | Measure-Object -Property X -Minimum).Minimum
        $y0 = ($xs | Measure-Object -Property Y -Minimum).Minimum
        $x1 = ($xs | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
        $y1 = ($xs | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
        $words = @($line.Words | ForEach-Object { $r = $_.BoundingRect; [pscustomobject]@{ text = $_.Text; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height } })
        [pscustomobject]@{ text = $line.Text; x = [int]$x0; y = [int]$y0; w = [int]($x1 - $x0); h = [int]($y1 - $y0); words = $words }
    }
    $stream.Dispose()
    [Console]::Out.WriteLine((@{ i = $i; lines = @($lines) } | ConvertTo-Json -Depth 6 -Compress))
    [Console]::Out.Flush()
    $i++
}
[Console]::Out.WriteLine((@{ done = $true; lang = $engine.RecognizerLanguage.LanguageTag } | ConvertTo-Json -Compress))
