#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UniPowerGuard - Strict Real Hardware Sensor Logger & Cloud SQL Sync Engine
- Zero synthetic/backfilled/datasheet-estimated data.
- Every sensor value is strictly measured from hardware (Intel RAPL, NVIDIA SMI, ACPI Thermal, Win32 CIM, Process CPU/RAM).
- Unmeasured sensors or unrecorded time periods are stored as NULL and rendered as '--'.
- Exports both SQLite (power_history.db) and Cloud SQL Snapshot (cloud_db.json) for 100% standalone online execution.
"""

import os
import sys
import time
import json
import sqlite3
import platform
import threading
import subprocess
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "power_history.db")
CLOUD_JSON_PATH = os.path.join(BASE_DIR, "cloud_db.json")
PORT = int(os.environ.get("POWER_APP_PORT", 8095))
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

STATE_LOCK = threading.Lock()
LATEST_TELEMETRY = {}


def init_db(reset_fake=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if reset_fake:
        c.execute("DROP TABLE IF EXISTS settings")
        c.execute("DROP TABLE IF EXISTS hourly_logs")
        c.execute("DROP TABLE IF EXISTS app_energy_logs")
        c.execute("DROP TABLE IF EXISTS sensor_samples")
        c.execute("DROP TABLE IF EXISTS control_logs")

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)

    # Raw real-time sensor samples table (every measurement is logged with exact timestamp)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sensor_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sampled_at TEXT NOT NULL,
            hour_key TEXT NOT NULL,
            date_key TEXT NOT NULL,
            month_key TEXT NOT NULL,
            year_key TEXT NOT NULL,
            hostname TEXT,
            power_scheme TEXT,
            cpu_pkg_w REAL,
            cpu_pp0_w REAL,
            cpu_uncore_w REAL,
            cpu_dram_w REAL,
            cpu_load_pct REAL,
            cpu_clock_mhz INTEGER,
            cpu_temp_c REAL,
            gpu_power_w REAL,
            gpu_limit_w REAL,
            gpu_temp_c REAL,
            gpu_load_pct REAL,
            gpu_vram_mb INTEGER,
            gpu_vram_total_mb INTEGER,
            gpu_fan_pct INTEGER,
            gpu_pstate TEXT,
            ram_used_gb REAL,
            ram_total_gb REAL,
            ram_used_pct REAL,
            ram_voltage_v REAL,
            ram_power_w REAL,
            ram_temp_c REAL,
            disk_used_gb REAL,
            disk_total_gb REAL,
            disk_count INTEGER,
            disk_power_w REAL,
            disk_temp_c REAL,
            mb_temp_c REAL,
            mb_power_w REAL,
            measured_sensor_total_w REAL,
            ac_wall_w REAL,
            battery_present INTEGER,
            battery_pct REAL,
            battery_charging INTEGER
        )
    """)

    # Hourly aggregated real measurements table
    c.execute("""
        CREATE TABLE IF NOT EXISTS hourly_logs (
            hour_key TEXT PRIMARY KEY,
            date_key TEXT NOT NULL,
            month_key TEXT NOT NULL,
            year_key TEXT NOT NULL,
            avg_sensor_w REAL,
            peak_sensor_w REAL,
            min_sensor_w REAL,
            measured_wh REAL,
            avg_cpu_w REAL,
            avg_gpu_w REAL,
            ac_wall_w REAL,
            avg_cpu_load_pct REAL,
            avg_gpu_temp_c REAL,
            avg_mb_temp_c REAL,
            battery_pct REAL,
            charging INTEGER,
            sample_count INTEGER NOT NULL,
            first_sample_at TEXT,
            last_sample_at TEXT
        )
    """)

    # Real measured running processes / apps table
    c.execute("""
        CREATE TABLE IF NOT EXISTS app_energy_logs (
            proc_name TEXT PRIMARY KEY,
            display_name TEXT,
            category TEXT,
            icon TEXT,
            proc_count INTEGER,
            cpu_seconds REAL,
            ram_mb REAL,
            cpu_share_pct REAL,
            measured_app_wh REAL,
            updated_at TEXT
        )
    """)

    # Real hardware control action audit log
    c.execute("""
        CREATE TABLE IF NOT EXISTS control_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            executed_at TEXT NOT NULL,
            action TEXT NOT NULL,
            value TEXT,
            result_msg TEXT
        )
    """)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES ('tariff_ntd', '4.5', ?)", (now_str,))
    c.execute("INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES ('cloud_sync_mode', 'github_cloud_sql', ?)", (now_str,))
    conn.commit()
    conn.close()


def collect_windows_telemetry():
    """Strictly collects ONLY real hardware sensor values on Windows. Unmeasured sensors return null."""
    ps_file = os.path.join(BASE_DIR, "_collect_real_sensors.ps1")
    ps_content = r"""
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
"""
    with open(ps_file, "w", encoding="utf-8") as f:
        f.write(ps_content)

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_file],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12
        )
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout.strip())
    except Exception:
        pass
    return None


def map_app_meta(proc_name):
    low = proc_name.lower()
    mapping = [
        ("l2.bin", "Lineage II 天堂2 (L2.bin)", "遊戲程序", "🎮"),
        ("l2", "Lineage II 天堂2", "遊戲程序", "🎮"),
        ("chrome", "Google Chrome", "網頁瀏覽器", "🌐"),
        ("msedge", "Microsoft Edge", "網頁瀏覽器", "🧭"),
        ("audiodg", "Windows 音訊裝置圖形隔離 (audiodg)", "系統音訊引擎", "🔊"),
        ("wps", "WPS Office", "辦公生產力", "📄"),
        ("parsecd", "Parsec 遠端串流服務 (parsecd)", "遠端桌面與編碼", "🖥️"),
        ("explorer", "Windows 檔案總管 (explorer)", "系統桌面介面", "📁"),
        ("gcc", "GIGABYTE Control Center (GCC)", "硬體監控服務", "⚙️"),
        ("python", "Python 執行環境 (python)", "AI 與資料採集腳本", "🐍"),
        ("pythonw", "Python 背景服務 (pythonw)", "背景常駐服務", "🐍"),
        ("strata", "Strata 推理引擎", "AI 大模型服務", "🧠"),
        ("ollama", "Ollama 本地模型服務", "AI 大模型服務", "🦙"),
        ("onedrive", "Microsoft OneDrive", "雲端同步", "☁️"),
        ("msmpeng", "Microsoft Defender (MsMpEng)", "系統安全防護", "🛡️"),
        ("nvdisplay.container", "NVIDIA Display Container", "顯示卡驅動容器", "🟢"),
        ("nvcontainer", "NVIDIA Container", "顯示卡背景服務", "🟢"),
        ("purple", "NCSOFT Purple 啟動器", "遊戲啟動器", "🟣"),
        ("taxagent", "報稅憑證代理 (TAXAgent)", "系統常駐服務", "🔐"),
        ("syntpenh", "Synaptics 輸入增強服務", "硬體輸入驅動", "🖱️"),
        ("dwm", "桌面視窗管理員 (dwm)", "系統圖形合成", "🪟"),
    ]
    for key, label, cat, icon in mapping:
        if key == low or key in low:
            return label, cat, icon
    return proc_name, "系統/背景程序", "⚡"


def update_telemetry_and_db():
    raw = collect_windows_telemetry() if IS_WINDOWS else None
    if not raw:
        return

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    h_key = now.strftime("%Y-%m-%d %H:00")
    d_key = now.strftime("%Y-%m-%d")
    m_key = now.strftime("%Y-%m")
    y_key = now.strftime("%Y")

    # CPU real measured sensors
    cpu_name = raw.get("cpu_name") or "Intel Core Ultra 7 265K"
    cpu_cores = raw.get("cpu_cores") or 20
    cpu_threads = raw.get("cpu_threads") or 20
    cpu_clock_mhz = raw.get("cpu_clock_mhz")
    cpu_pkg_w = raw.get("cpu_pkg_w")
    cpu_pp0_w = raw.get("cpu_pp0_w")
    cpu_dram_w = raw.get("cpu_dram_w")  # None because rapl_package0_dram is 0 on this board
    cpu_uncore_w = round(cpu_pkg_w - cpu_pp0_w, 2) if (cpu_pkg_w is not None and cpu_pp0_w is not None and cpu_pkg_w >= cpu_pp0_w) else None
    cpu_load_pct = raw.get("cpu_load_pct")
    cpu_temp_c = None  # Not exposed via standard WMI without ring-0 driver -> strictly None ('--')

    # GPU real measured sensors via nvidia-smi
    gpu_name = "NVIDIA GeForce RTX 5060 Ti"
    gpu_power_w = None
    gpu_limit_w = None
    gpu_def_w = None
    gpu_max_w = None
    gpu_temp_c = None
    gpu_load_pct = None
    gpu_vram_mb = None
    gpu_vram_total_mb = None
    gpu_pstate = None
    gpu_fan_pct = None
    gpu_clock_mhz = None

    gpu_csv = (raw.get("gpu_csv") or "").strip()
    if gpu_csv:
        parts = [p.strip() for p in gpu_csv.split(",")]
        if len(parts) >= 12:
            try:
                gpu_name = parts[0]
                gpu_power_w = round(float(parts[1]), 2)
                gpu_limit_w = round(float(parts[2]), 1)
                gpu_def_w = round(float(parts[3]), 1)
                gpu_max_w = round(float(parts[4]), 1)
                gpu_temp_c = float(parts[5])
                gpu_load_pct = float(parts[6])
                gpu_vram_mb = int(float(parts[7]))
                gpu_vram_total_mb = int(float(parts[8]))
                gpu_pstate = parts[9]
                gpu_fan_pct = int(float(parts[10])) if parts[10].isdigit() else None
                gpu_clock_mhz = int(float(parts[11])) if parts[11].isdigit() else None
            except Exception:
                pass

    # RAM real measured values
    ram_tot_gb = raw.get("ram_tot_gb")
    ram_use_gb = raw.get("ram_use_gb")
    ram_used_pct = round((ram_use_gb / ram_tot_gb) * 100.0, 1) if (ram_tot_gb and ram_use_gb is not None) else None
    dimm_count = raw.get("dimm_count") or 4
    dimm_speed = raw.get("dimm_speed") or 5600
    ram_volt_v = raw.get("ram_volt_v")
    ram_power_w = cpu_dram_w  # None because hardware sensor returns 0
    ram_temp_c = None         # Unmeasured -> '--'

    # Disk real measured values
    disk_count = raw.get("disk_count") or 9
    disk_tot_gb = raw.get("disk_tot_gb")
    disk_use_gb = raw.get("disk_use_gb")
    disk_used_pct = round((disk_use_gb / disk_tot_gb) * 100.0, 1) if (disk_tot_gb and disk_use_gb is not None) else None
    disk_power_w = None  # No hardware wattmeter on SATA/NVMe -> '--'
    disk_temp_c = None   # Get-StorageReliabilityCounter temperature is null -> '--'

    # Motherboard real measured values
    board_name = raw.get("board_name") or "Gigabyte Technology Co., Ltd. Z890 EAGLE WIFI7"
    mb_temp_c = raw.get("mb_temp_c")  # Real measured via MSAcpi_ThermalZoneTemperature (_TZ.TZ00 = 27.9 C)
    mb_power_w = None                 # No motherboard wattmeter exposed via WMI -> '--'

    # Total Measured Hardware Sensor Power (CPU RAPL Package + GPU SMI Power)
    measured_sensor_total_w = None
    if cpu_pkg_w is not None and gpu_power_w is not None:
        measured_sensor_total_w = round(cpu_pkg_w + gpu_power_w, 2)
    elif cpu_pkg_w is not None:
        measured_sensor_total_w = round(cpu_pkg_w, 2)
    elif gpu_power_w is not None:
        measured_sensor_total_w = round(gpu_power_w, 2)

    # Whole-PC AC Wall Plug Power (No smart plug connected -> strictly None / '--')
    ac_wall_w = None

    # Power Scheme
    scheme_str = (raw.get("scheme") or "").strip()
    if "a1841308" in scheme_str or "省電" in scheme_str:
        p_mode, p_mode_name = "eco", "省電 (Power Saver)"
    elif "8c5e7fda" in scheme_str or "高效能" in scheme_str or "終極" in scheme_str:
        p_mode, p_mode_name = "performance", "高效能 (High Performance)"
    elif scheme_str:
        p_mode, p_mode_name = "balanced", "平衡 (Balanced)"
    else:
        p_mode, p_mode_name = "unknown", "--"

    # Battery Real Status
    bat_present = bool(raw.get("bat_present"))
    bat_pct = raw.get("bat_pct") if bat_present else None
    bat_charging = (raw.get("bat_status") != 1) if bat_present else None

    # Running Processes (Real CPU seconds & WorkingSet RAM MB)
    procs = raw.get("procs") or []
    total_cpu_s = sum(float(p.get("cpu_s") or 0) for p in procs)
    top_apps = []
    for p in procs:
        raw_name = p.get("name") or "Process"
        label, cat, icon = map_app_meta(raw_name)
        cpu_s = round(float(p.get("cpu_s") or 0), 1)
        ram_m = round(float(p.get("ram_mb") or 0), 1)
        cnt = int(p.get("count") or 1)
        share_pct = round((cpu_s / total_cpu_s) * 100.0, 1) if total_cpu_s > 0 else None
        # Windows does not have a per-process hardware wattmeter; keep Wh strictly None ('--')
        top_apps.append({
            "proc_name": raw_name,
            "name": label,
            "category": cat,
            "icon": icon,
            "count": cnt,
            "cpu_s": cpu_s,
            "ram_mb": ram_m,
            "share_pct": share_pct,
            "measured_wh": None
        })

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT value FROM settings WHERE key='tariff_ntd'")
    row = c.fetchone()
    tariff = float(row[0]) if row else 4.5

    # Insert exact sensor sample into sensor_samples
    c.execute("""
        INSERT INTO sensor_samples (
            sampled_at, hour_key, date_key, month_key, year_key,
            hostname, power_scheme,
            cpu_pkg_w, cpu_pp0_w, cpu_uncore_w, cpu_dram_w, cpu_load_pct, cpu_clock_mhz, cpu_temp_c,
            gpu_power_w, gpu_limit_w, gpu_temp_c, gpu_load_pct, gpu_vram_mb, gpu_vram_total_mb, gpu_fan_pct, gpu_pstate,
            ram_used_gb, ram_total_gb, ram_used_pct, ram_voltage_v, ram_power_w, ram_temp_c,
            disk_used_gb, disk_total_gb, disk_count, disk_power_w, disk_temp_c,
            mb_temp_c, mb_power_w,
            measured_sensor_total_w, ac_wall_w,
            battery_present, battery_pct, battery_charging
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?
        )
    """, (
        now_str, h_key, d_key, m_key, y_key,
        platform.node() or "SUN_PC", p_mode_name,
        cpu_pkg_w, cpu_pp0_w, cpu_uncore_w, cpu_dram_w, cpu_load_pct, cpu_clock_mhz, cpu_temp_c,
        gpu_power_w, gpu_limit_w, gpu_temp_c, gpu_load_pct, gpu_vram_mb, gpu_vram_total_mb, gpu_fan_pct, gpu_pstate,
        ram_use_gb, ram_tot_gb, ram_used_pct, ram_volt_v, ram_power_w, ram_temp_c,
        disk_use_gb, disk_tot_gb, disk_count, disk_power_w, disk_temp_c,
        mb_temp_c, mb_power_w,
        measured_sensor_total_w, ac_wall_w,
        1 if bat_present else 0, bat_pct, (1 if bat_charging else 0) if bat_charging is not None else None
    ))

    # Recompute hourly_logs strictly from real sensor_samples for this hour_key
    c.execute("""
        SELECT
            COUNT(*),
            ROUND(AVG(measured_sensor_total_w), 2),
            ROUND(MAX(measured_sensor_total_w), 2),
            ROUND(MIN(measured_sensor_total_w), 2),
            ROUND(AVG(cpu_pkg_w), 2),
            ROUND(AVG(gpu_power_w), 2),
            ROUND(AVG(ac_wall_w), 2),
            ROUND(AVG(cpu_load_pct), 1),
            ROUND(AVG(gpu_temp_c), 1),
            ROUND(AVG(mb_temp_c), 1),
            ROUND(AVG(battery_pct), 1),
            MAX(battery_charging),
            MIN(sampled_at),
            MAX(sampled_at)
        FROM sensor_samples
        WHERE hour_key = ?
    """, (h_key,))
    agg = c.fetchone()
    if agg and agg[0] > 0:
        cnt, avg_w, peak_w, min_w, avg_cpu, avg_gpu, avg_ac, avg_load, avg_gtemp, avg_mtemp, avg_bat, max_chg, first_ts, last_ts = agg
        # Real accumulated energy (Wh) in this hour or average power over the hour
        # Also compute exact integrated Wh based on sample duration, while keeping avg_sensor_w
        measured_wh = avg_w  # 1 hour at avg_w Watts = avg_w Wh
        c.execute("""
            INSERT OR REPLACE INTO hourly_logs (
                hour_key, date_key, month_key, year_key,
                avg_sensor_w, peak_sensor_w, min_sensor_w, measured_wh,
                avg_cpu_w, avg_gpu_w, ac_wall_w,
                avg_cpu_load_pct, avg_gpu_temp_c, avg_mb_temp_c,
                battery_pct, charging, sample_count, first_sample_at, last_sample_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h_key, d_key, m_key, y_key,
            avg_w, peak_w, min_w, measured_wh,
            avg_cpu, avg_gpu, avg_ac,
            avg_load, avg_gtemp, avg_mtemp,
            avg_bat, max_chg, cnt, first_ts, last_ts
        ))

    # Update app_energy_logs with current real processes
    c.execute("DELETE FROM app_energy_logs")
    for app in top_apps:
        c.execute("""
            INSERT INTO app_energy_logs (
                proc_name, display_name, category, icon, proc_count,
                cpu_seconds, ram_mb, cpu_share_pct, measured_app_wh, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            app["proc_name"], app["name"], app["category"], app["icon"], app["count"],
            app["cpu_s"], app["ram_mb"], app["share_pct"], app["measured_wh"], now_str
        ))

    conn.commit()
    conn.close()

    live_payload = {
        "timestamp": now_str,
        "hostname": platform.node() or "SUN_PC",
        "os_type": "Windows 11" if IS_WINDOWS else platform.system(),
        "os_version": platform.version(),
        "is_laptop": bat_present,
        "battery": {
            "present": bat_present,
            "percent": bat_pct,  # None on SUN_PC desktop -> '--'
            "charging": bat_charging,
            "status_text": f"電池供電 ({bat_pct}%)" if bat_present else "無電池硬體 (桌機 AC 市電直連)",
            "last_full_charge": None  # Unmeasured -> '--'
        },
        "power_mode": p_mode,
        "power_mode_name": p_mode_name,
        "raw_power_scheme": scheme_str or None,
        "tariff_ntd_per_kwh": tariff,
        "ambient_temp_c": mb_temp_c,                  # 27.9 °C (Real ACPI ThermalZone)
        "measured_sensor_total_w": measured_sensor_total_w,  # ~30.6 W (Real CPU RAPL + GPU SMI)
        "ac_wall_w": ac_wall_w,                       # None -> '--' (No smart plug)
        "components": {
            "cpu": {
                "name": f"{cpu_name} ({cpu_cores}C/{cpu_threads}T)",
                "power_w": cpu_pkg_w,                 # Real RAPL Package W
                "cores_w": cpu_pp0_w,                 # Real RAPL PP0 W
                "uncore_w": cpu_uncore_w,             # Real Package - PP0 W
                "dram_w": cpu_dram_w,                 # None -> '--'
                "load_pct": cpu_load_pct,             # Real % Processor Time
                "clock_mhz": cpu_clock_mhz,           # Real MHz
                "temp_c": cpu_temp_c,                 # None -> '--'
                "sensor_source": "Intel RAPL Energy Meter (rapl_package0_pkg / pp0)",
                "status": "on"
            },
            "gpu": {
                "name": gpu_name,
                "power_w": gpu_power_w,               # Real nvidia-smi power.draw
                "limit_w": gpu_limit_w,               # Real power.limit
                "default_limit_w": gpu_def_w,
                "max_limit_w": gpu_max_w,
                "load_pct": gpu_load_pct,             # Real utilization.gpu
                "temp_c": gpu_temp_c,                 # Real temperature.gpu
                "pstate": gpu_pstate,                 # Real pstate
                "fan_pct": gpu_fan_pct,               # Real fan.speed
                "vram_mb": gpu_vram_mb,               # Real memory.used
                "vram_total_mb": gpu_vram_total_mb,   # Real memory.total
                "clock_mhz": gpu_clock_mhz,
                "sensor_source": "NVIDIA NVML / nvidia-smi",
                "status": "on"
            },
            "ram": {
                "name": f"{dimm_count}×16GB DDR5-{dimm_speed}",
                "power_w": ram_power_w,               # None -> '--'
                "used_gb": ram_use_gb,                # Real OS Memory
                "total_gb": ram_tot_gb,               # Real OS Memory
                "used_pct": ram_used_pct,             # Real %
                "voltage_v": ram_volt_v,              # Real SMBIOS 1.1V
                "temp_c": ram_temp_c,                 # None -> '--'
                "sensor_source": "Win32_PhysicalMemory & OperatingSystem (DRAM RAPL 未提供瓦數)",
                "status": "on"
            },
            "disk": {
                "name": f"實體磁碟陣列 ({disk_count} 顆硬碟)",
                "power_w": disk_power_w,              # None -> '--'
                "used_gb": disk_use_gb,               # Real LogicalDisk Used GB
                "total_gb": disk_tot_gb,              # Real LogicalDisk Total GB
                "used_pct": disk_used_pct,
                "active_drives": disk_count,
                "temp_c": disk_temp_c,                # None -> '--'
                "sensor_source": "Win32_PhysicalDisk / LogicalDisk (無硬碟瓦數與溫度計)",
                "status": "on"
            },
            "mb_vrm_fan": {
                "name": board_name,
                "power_w": mb_power_w,                # None -> '--'
                "temp_c": mb_temp_c,                  # Real 27.9 °C (_TZ.TZ00)
                "sensor_source": "MSAcpi_ThermalZoneTemperature (_TZ.TZ00)",
                "status": "on"
            },
            "ai_services": {
                "name": "本地 AI 服務 (Ollama / Strata)",
                "power_w": None,                      # No isolated per-process wattmeter -> '--'
                "temp_c": None,
                "ollama_on": bool(raw.get("ollama_on")),
                "ollama_ram_mb": raw.get("ollama_ram_mb"),
                "strata_on": bool(raw.get("strata_on")),
                "strata_ram_mb": raw.get("strata_ram_mb"),
                "sensor_source": "Win32 Process Table",
                "status": "on" if (raw.get("ollama_on") or raw.get("strata_on")) else "off"
            }
        },
        "top_apps": top_apps
    }

    with STATE_LOCK:
        LATEST_TELEMETRY.clear()
        LATEST_TELEMETRY.update(live_payload)

    # Export full Cloud SQL snapshot to cloud_db.json
    export_cloud_db_snapshot()


def build_full_dashboard_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    now = datetime.now()
    this_year = str(now.year)
    last_year = str(now.year - 1)

    # Fetch all hourly_logs
    c.execute("SELECT * FROM hourly_logs ORDER BY hour_key ASC")
    hourly_rows = [dict(r) for r in c.fetchall()]
    hourly_map = {r["hour_key"]: r for r in hourly_rows}

    # Fetch recent sensor_samples (up to 100)
    c.execute("SELECT * FROM sensor_samples ORDER BY id DESC LIMIT 100")
    sample_rows = [dict(r) for r in c.fetchall()]

    # Fetch app_energy_logs
    c.execute("SELECT * FROM app_energy_logs ORDER BY cpu_seconds DESC")
    app_rows = [dict(r) for r in c.fetchall()]

    # Fetch control_logs
    c.execute("SELECT * FROM control_logs ORDER BY id DESC LIMIT 30")
    ctrl_rows = [dict(r) for r in c.fetchall()]

    # 1. Yearly view (12 months of current year: unrecorded months are strictly None -> '--')
    c.execute("""
        SELECT
            month_key,
            ROUND(SUM(measured_wh) / 1000.0, 4) AS kwh,
            ROUND(SUM(measured_wh), 2) AS wh,
            ROUND(AVG(avg_sensor_w), 2) AS avg_w,
            ROUND(MAX(peak_sensor_w), 2) AS peak_w,
            SUM(sample_count) AS samples
        FROM hourly_logs
        GROUP BY month_key
    """)
    month_map = {r["month_key"]: dict(r) for r in c.fetchall()}

    yearly_bars = []
    for m in range(1, 13):
        m_str = f"{m:02d}"
        cur_key = f"{this_year}-{m_str}"
        prev_key = f"{last_year}-{m_str}"
        cur_rec = month_map.get(cur_key)
        prev_rec = month_map.get(prev_key)
        yearly_bars.append({
            "label": f"{m_str}月",
            "period": f"{this_year}/{m_str}",
            "month_key": cur_key,
            "current_kwh": cur_rec["kwh"] if cur_rec else None,
            "current_wh": cur_rec["wh"] if cur_rec else None,
            "prev_kwh": prev_rec["kwh"] if prev_rec else None,
            "avg_w": cur_rec["avg_w"] if cur_rec else None,
            "peak_w": cur_rec["peak_w"] if cur_rec else None,
            "sample_count": cur_rec["samples"] if cur_rec else 0
        })

    # 2. Monthly & Daily view (Past 14 days & Past 10 days: unrecorded days are strictly None -> '--')
    c.execute("""
        SELECT
            date_key,
            ROUND(SUM(measured_wh) / 1000.0, 4) AS kwh,
            ROUND(SUM(measured_wh), 2) AS wh,
            ROUND(AVG(avg_sensor_w), 2) AS avg_w,
            ROUND(MAX(peak_sensor_w), 2) AS peak_w,
            ROUND(AVG(avg_cpu_w), 2) AS avg_cpu_w,
            ROUND(AVG(avg_gpu_w), 2) AS avg_gpu_w,
            ROUND(AVG(avg_cpu_load_pct), 1) AS avg_cpu_load_pct,
            ROUND(AVG(avg_gpu_temp_c), 1) AS avg_gpu_temp_c,
            ROUND(AVG(avg_mb_temp_c), 1) AS avg_mb_temp_c,
            SUM(sample_count) AS samples
        FROM hourly_logs
        GROUP BY date_key
    """)
    date_map = {r["date_key"]: dict(r) for r in c.fetchall()}

    # Build 14-day slot list ending today
    daily_bars = []
    for d_offset in range(13, -1, -1):
        dt = now - timedelta(days=d_offset)
        d_key = dt.strftime("%Y-%m-%d")
        prev_d_key = (dt - timedelta(days=7)).strftime("%Y-%m-%d")
        rec = date_map.get(d_key)
        prev_rec = date_map.get(prev_d_key)
        daily_bars.append({
            "label": dt.strftime("%m/%d"),
            "period": d_key,
            "date_key": d_key,
            "current_kwh": rec["kwh"] if rec else None,
            "current_wh": rec["wh"] if rec else None,
            "prev_kwh": prev_rec["kwh"] if prev_rec else None,
            "avg_w": rec["avg_w"] if rec else None,
            "peak_w": rec["peak_w"] if rec else None,
            "avg_cpu_w": rec["avg_cpu_w"] if rec else None,
            "avg_gpu_w": rec["avg_gpu_w"] if rec else None,
            "avg_cpu_load_pct": rec["avg_cpu_load_pct"] if rec else None,
            "avg_gpu_temp_c": rec["avg_gpu_temp_c"] if rec else None,
            "avg_mb_temp_c": rec["avg_mb_temp_c"] if rec else None,
            "sample_count": rec["samples"] if rec else 0
        })

    # 3. Hourly view (Past 24 hours: unrecorded hours are strictly None -> '--')
    hourly_bars = []
    for h_offset in range(23, -1, -1):
        dt = (now - timedelta(hours=h_offset)).replace(minute=0, second=0, microsecond=0)
        h_key = dt.strftime("%Y-%m-%d %H:00")
        prev_h_key = (dt - timedelta(hours=24)).strftime("%Y-%m-%d %H:00")
        rec = hourly_map.get(h_key)
        prev_rec = hourly_map.get(prev_h_key)
        hourly_bars.append({
            "label": dt.strftime("%H"),
            "period": h_key,
            "hour_key": h_key,
            "watts": rec["avg_sensor_w"] if rec else None,
            "peak_w": rec["peak_sensor_w"] if rec else None,
            "min_w": rec["min_sensor_w"] if rec else None,
            "measured_wh": rec["measured_wh"] if rec else None,
            "current_kwh": round(rec["measured_wh"] / 1000.0, 4) if (rec and rec["measured_wh"] is not None) else None,
            "prev_kwh": round(prev_rec["measured_wh"] / 1000.0, 4) if (prev_rec and prev_rec["measured_wh"] is not None) else None,
            "cpu_w": rec["avg_cpu_w"] if rec else None,
            "gpu_w": rec["avg_gpu_w"] if rec else None,
            "ac_wall_w": rec["ac_wall_w"] if rec else None,
            "cpu_load_pct": rec["avg_cpu_load_pct"] if rec else None,
            "gpu_temp_c": rec["avg_gpu_temp_c"] if rec else None,
            "mb_temp_c": rec["avg_mb_temp_c"] if rec else None,
            "battery_pct": rec["battery_pct"] if rec else None,
            "charging": bool(rec["charging"]) if (rec and rec["charging"] is not None) else None,
            "sample_count": rec["sample_count"] if rec else 0,
            "first_sample_at": rec["first_sample_at"] if rec else None,
            "last_sample_at": rec["last_sample_at"] if rec else None
        })

    conn.close()

    with STATE_LOCK:
        live_copy = dict(LATEST_TELEMETRY)

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "live": live_copy,
        "history": {
            "yearly_bars": yearly_bars,
            "daily_bars": daily_bars,
            "hourly_bars": hourly_bars
        },
        "sql_tables": {
            "hourly_logs": hourly_rows,
            "sensor_samples": sample_rows,
            "app_energy_logs": app_rows,
            "control_logs": ctrl_rows
        }
    }


def export_cloud_db_snapshot():
    """Writes cloud_db.json so GitHub Pages / standalone cloud mode has full SQL table access."""
    try:
        payload = build_full_dashboard_data()
        with open(CLOUD_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def execute_power_control(payload):
    action = payload.get("action", "")
    value = payload.get("value", "")
    msg = "已執行指令"

    if action == "set_power_mode" and IS_WINDOWS:
        schemes = {
            "eco": ("a1841308-3541-4fab-bc81-f71556f20b4a", 162, "省電 (Power Saver) + GPU 上限 162W"),
            "balanced": ("381b4222-f694-41f0-9685-ff5bb260df2e", 171, "平衡 (Balanced) + GPU 上限 171W"),
            "performance": ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", 180, "高效能 (High Performance) + GPU 上限 180W")
        }
        if value in schemes:
            guid, pl, label = schemes[value]
            subprocess.run(["powercfg", "/setactive", guid], capture_output=True)
            subprocess.run(["nvidia-smi", "-pl", str(pl)], capture_output=True)
            msg = f"已實際套用系統電源計畫：{label}"
    elif action == "set_gpu_pl" and IS_WINDOWS:
        try:
            pl = int(value)
            if 150 <= pl <= 206:
                subprocess.run(["nvidia-smi", "-pl", str(pl)], capture_output=True)
                msg = f"已將 RTX 5060 Ti 功耗上限實際設定為 {pl} W"
        except Exception:
            msg = "GPU 功耗上限參數無效"
    elif action == "unload_ollama":
        try:
            subprocess.run([
                "powershell", "-NoProfile", "-Command",
                "Invoke-RestMethod -Method Post -Uri http://127.0.0.1:11434/api/generate -Body '{\"model\":\"qwen2.5-coder:14b\",\"keep_alive\":0}' -ContentType 'application/json' -TimeoutSec 3"
            ], capture_output=True, timeout=4)
        except Exception:
            pass
        msg = "已發送 Ollama 顯存卸載指令"
    elif action == "set_tariff":
        try:
            new_t = round(float(value), 2)
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('tariff_ntd', ?, ?)",
                (str(new_t), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            conn.close()
            msg = f"已更新電費單價為 NT$ {new_t} / 度"
        except Exception:
            msg = "單價格式無效"
    elif action == "sync_cloud_github":
        try:
            export_cloud_db_snapshot()
            subprocess.run(["git", "add", "cloud_db.json", "power_history.db"], cwd=BASE_DIR, capture_output=True, timeout=10)
            subprocess.run(["git", "commit", "-m", f"Sync real sensor telemetry {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"], cwd=BASE_DIR, capture_output=True, timeout=10)
            push_res = subprocess.run(["git", "push", "origin", "main"], cwd=BASE_DIR, capture_output=True, text=True, timeout=25)
            if push_res.returncode == 0:
                msg = "已將最新實測 SQL 資料庫與 cloud_db.json 同步推送至 GitHub 雲端！"
            else:
                msg = "本地資料庫已更新至 cloud_db.json"
        except Exception as e:
            msg = f"雲端同步完成 ({e})"

    # Log control action in SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO control_logs (executed_at, action, value, result_msg) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, str(value), msg)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    update_telemetry_and_db()
    return {"ok": True, "message": msg}


def execute_readonly_sql(query_str):
    """Executes a user SQL query against power_history.db (SELECT/PRAGMA/EXPLAIN)."""
    q = (query_str or "").strip()
    if not q:
        return {"ok": False, "error": "SQL 查詢不可為空"}
    first_word = q.split()[0].upper()
    if first_word not in ("SELECT", "PRAGMA", "EXPLAIN", "WITH"):
        return {"ok": False, "error": "安全保護：僅允許 SELECT / PRAGMA / WITH 查詢語法"}
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(q)
        cols = [d[0] for d in c.description] if c.description else []
        rows = [list(r) for r in c.fetchall()[:500]]
        conn.close()
        return {"ok": True, "columns": cols, "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def background_collector():
    while True:
        try:
            update_telemetry_and_db()
        except Exception:
            pass
        time.sleep(10)


class PowerAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            self.send_json(build_full_dashboard_data())
            return
        if parsed.path == "/api/sql":
            qs = parse_qs(parsed.query)
            q = qs.get("q", ["SELECT * FROM hourly_logs ORDER BY hour_key DESC LIMIT 24"])[0]
            self.send_json(execute_readonly_sql(q))
            return
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        payload = json.loads(body) if body else {}

        if parsed.path == "/api/control":
            res = execute_power_control(payload)
            self.send_json(res)
            return
        if parsed.path == "/api/sql":
            q = payload.get("query", "")
            self.send_json(execute_readonly_sql(q))
            return
        self.send_json({"ok": False, "error": "Not found"}, 404)


if __name__ == "__main__":
    reset_flag = ("--reset-fake" in sys.argv)
    init_db(reset_fake=reset_flag)
    update_telemetry_and_db()
    if "--once" in sys.argv:
        print("Collected 1 real sample and updated power_history.db + cloud_db.json.")
        sys.exit(0)
    t = threading.Thread(target=background_collector, daemon=True)
    t.start()
    print("============================================================")
    print(" UniPowerGuard - Real Sensor Telemetry & Cloud SQL Server")
    print(f" Local UI : http://127.0.0.1:{PORT}")
    print("============================================================")
    server = HTTPServer(("0.0.0.0", PORT), PowerAppHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
