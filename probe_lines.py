$bytes = [System.IO.File]::ReadAllBytes("models.py")
$crlf = 0
$lfOnly = 0
for ($i = 0; $i -lt $bytes.Length - 1; $i++) {
    if ($bytes[$i] -eq 13 -and $bytes[$i + 1] -eq 10) {
        $crlf++
    } elseif ($bytes[$i] -eq 10 -and ($i -eq 0 -or $bytes[$i - 1] -ne 13)) {
        $lfOnly++
    }
}
Write-Host "CRLF: $crlf"
Write-Host "LF-only: $lfOnly"
Write-Host "Total: $($crlf + $lfOnly)"
