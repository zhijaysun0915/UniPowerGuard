[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== 1. SYSTEM UPTIME & BOOT ==="
$os = Get-CimInstance Win32_OperatingSystem
$boot = $os.LastBootUpTime
$uptime = (Get-Date) - $boot
Write-Host "LastBootUpTime : $boot"
Write-Host "Uptime Days    : $([math]::Round($uptime.TotalDays, 2)) days ($([math]::Round($uptime.TotalHours, 1)) hours)"

Write-Host "`n=== 2. BATTERY / SLEEP TRANSITIONS IN WINDOWS SYSTEM LOG ==="
$events = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName=@('Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter')} -MaxEvents 30 -ErrorAction SilentlyContinue
$events | Select-Object TimeCreated, Id, ProviderName, @{N='Summary';E={$_.Message.Split("`n")[0]}} | Format-Table -AutoSize

Write-Host "`n=== 3. CHECK RUNNING APPS REAL CPU SECONDS & WORKING SET ==="
Get-Process | Where-Object { $_.CPU -gt 5 -or $_.WorkingSet64 -gt 150MB } |
    Sort-Object CPU -Descending |
    Select-Object Id, ProcessName, @{N='CPU_Seconds';E={[math]::Round($_.CPU, 1)}}, @{N='RAM_MB';E={[math]::Round($_.WorkingSet64/1MB, 1)}}, StartTime |
    Format-Table -AutoSize
