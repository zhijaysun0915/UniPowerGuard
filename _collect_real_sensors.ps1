
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1. Intel RAPL Energy Meter (mW -> W) & CPU Total Load
$counters = Get-Counter -Counter "\Energy Meter(rapl_package0_pkg)\Power", "\Energy Meter(rapl_package0_pp0)\Power", "\Energy Meter(rapl_package0_dram)\Power", "\Processor(_Total)\% Processor Time"
$pkgMW  = ($counters.CounterSamples | Where-Object { $_.Path -match "rapl_package0_pkg" }).CookedValue
$pp0MW  = ($counters.CounterSamples | Where-Object { $_.Path -match "rapl_package0_pp0" }).CookedValue
$dramMW = ($counters.CounterSamples | Where-Object { $_.Path -match "rapl_package0_dram" }).CookedValue
$cpuLoad = ($counters.CounterSamples | Where-Object { $_.Path -match "processor time" }).CookedValue

# 2. CPU Name & Clock Speed
$cpuCim = Get-CimInstance Win32_Processor | Select-Object -First 1
$cpuName = if ($cpuCim) { $cpuCim.Name.Trim() } else { $null }
$cpuClock = if ($cpuCim) { [int]$cpuCim.CurrentClockSpeed } else { $null }
$cpuCores = if ($cpuCim) { [int]$cpuCim.NumberOfCores } else { $null }
$cpuLogicals = if ($cpuCim) { [int]$cpuCim.NumberOfLogicalProcessors } else { $null }

# 3. NVIDIA GPU Real Sensors via nvidia-smi
$gpuRaw = & nvidia-smi --query-gpu=name,power.draw,power.limit,power.default_limit,power.max_limit,temperature.gpu,utilization.gpu,memory.used,memory.total,pstate,fan.speed,clocks.current.graphics --format=csv,noheader,nounits

# 4. RAM Real Usage & Voltage
$os = Get-CimInstance Win32_OperatingSystem
$ramTot = if ($os) { [math]::Round($os.TotalVisibleMemorySize / 1MB, 2) } else { $null }
$ramUse = if ($os) { [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 2) } else { $null }
$dimms = Get-CimInstance Win32_PhysicalMemory
$dimmCount = if ($dimms) { @($dimms).Count } else { 0 }
$dimmSpeed = if ($dimms) { ($dimms | Select-Object -First 1).ConfiguredClockSpeed } else { $null }
$dimmVoltMV = if ($dimms) { ($dimms | Select-Object -First 1).ConfiguredVoltage } else { $null }
$dimmVoltV = if ($dimmVoltMV -and $dimmVoltMV -gt 0) { [math]::Round($dimmVoltMV / 1000.0, 2) } else { $null }

# 5. Physical Disks & Logical Volumes Real Capacity
$physDisks = Get-PhysicalDisk
$diskCount = if ($physDisks) { @($physDisks).Count } else { 0 }
$diskModels = if ($physDisks) { ($physDisks | Select-Object -ExpandProperty FriendlyName) -join ", " } else { "" }
$vols = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
$diskTotalGB = 0.0
$diskFreeGB = 0.0
foreach ($v in $vols) {
    $diskTotalGB += ($v.Size / 1GB)
    $diskFreeGB  += ($v.FreeSpace / 1GB)
}
$diskTotalGB = [math]::Round($diskTotalGB, 1)
$diskUsedGB  = [math]::Round($diskTotalGB - $diskFreeGB, 1)

# 6. Motherboard & ACPI Thermal Zone Real Temperature
$board = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
$boardName = if ($board) { "$($board.Manufacturer) $($board.Product)".Trim() } else { $null }
$tzPerf = Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation | Select-Object -First 1
$mbTempC = if ($tzPerf -and $tzPerf.Temperature -gt 273) { [math]::Round([double]$tzPerf.Temperature - 273.15, 1) } else { $null }
if ($null -eq $mbTempC) {
    $tz = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | Select-Object -First 1
    if ($tz -and $tz.CurrentTemperature -gt 2732) {
        $mbTempC = [math]::Round(($tz.CurrentTemperature / 10.0) - 273.15, 1)
    }
}

# 7. Battery Real Check
$bat = Get-CimInstance Win32_Battery
$batPresent = [bool]($null -ne $bat)
$batPct = if ($batPresent) { [double]$bat.EstimatedChargeRemaining } else { $null }
$batStatus = if ($batPresent) { [int]$bat.BatteryStatus } else { $null }

# 8. Active Power Scheme
$schemeRaw = (& powercfg /getactivescheme) -join " "

# 9. Top Real Running Processes (CPU seconds & WorkingSet RAM MB)
$procs = Get-Process | Where-Object { $_.CPU -gt 0.5 -or $_.WorkingSet64 -gt 50MB } |
    Group-Object ProcessName | ForEach-Object {
        $cpuSum = ($_.Group | Measure-Object CPU -Sum).Sum
        $ramSum = ($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1MB
        [PSCustomObject]@{
            name = $_.Name
            count = $_.Count
            cpu_s = [math]::Round([double]$cpuSum, 1)
            ram_mb = [math]::Round([double]$ramSum, 1)
        }
    } | Sort-Object cpu_s -Descending | Select-Object -First 12

$strataProc = Get-Process -Name "strata*"
$ollamaProc = Get-Process -Name "ollama*"
$ollamaRamMB = if ($ollamaProc) { [math]::Round((($ollamaProc | Measure-Object WorkingSet64 -Sum).Sum / 1MB), 1) } else { 0.0 }
$strataRamMB = if ($strataProc) { [math]::Round((($strataProc | Measure-Object WorkingSet64 -Sum).Sum / 1MB), 1) } else { 0.0 }

[PSCustomObject]@{
    cpu_name     = $cpuName
    cpu_cores    = $cpuCores
    cpu_threads  = $cpuLogicals
    cpu_clock_mhz = $cpuClock
    cpu_pkg_w    = if ($null -ne $pkgMW -and $pkgMW -gt 0) { [math]::Round($pkgMW / 1000.0, 2) } else { $null }
    cpu_pp0_w    = if ($null -ne $pp0MW -and $pp0MW -gt 0) { [math]::Round($pp0MW / 1000.0, 2) } else { $null }
    cpu_dram_w   = if ($null -ne $dramMW -and $dramMW -gt 0) { [math]::Round($dramMW / 1000.0, 2) } else { $null }
    cpu_load_pct = if ($null -ne $cpuLoad) { [math]::Round($cpuLoad, 1) } else { $null }
    cpu_temp_c   = $null
    gpu_csv      = [string]$gpuRaw
    ram_tot_gb   = $ramTot
    ram_use_gb   = $ramUse
    dimm_count   = $dimmCount
    dimm_speed   = $dimmSpeed
    ram_volt_v   = $dimmVoltV
    disk_count   = $diskCount
    disk_models  = $diskModels
    disk_tot_gb  = $diskTotalGB
    disk_use_gb  = $diskUsedGB
    board_name   = $boardName
    mb_temp_c    = $mbTempC
    bat_present  = $batPresent
    bat_pct      = $batPct
    bat_status   = $batStatus
    scheme       = $schemeRaw
    strata_on    = [bool]($null -ne $strataProc)
    strata_ram_mb = $strataRamMB
    ollama_on    = [bool]($null -ne $ollamaProc)
    ollama_ram_mb = $ollamaRamMB
    procs        = $procs
} | ConvertTo-Json -Depth 4 -Compress
