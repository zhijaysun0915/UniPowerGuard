# UniPowerGuard ⚡ — 實測感測器電源管控與雲端 SQL 系統

[![GitHub Pages](https://img.shields.io/badge/Live%20App-GitHub%20Pages-2ea44f?style=flat-square&logo=github)](https://zhijaysun0915.github.io/UniPowerGuard/)
[![Cloud SQL](https://img.shields.io/badge/Cloud%20SQL-SQL.js%20WASM%20%2B%20SQLite-00699e?style=flat-square)](https://zhijaysun0915.github.io/UniPowerGuard/)
[![Real Sensors](https://img.shields.io/badge/Telemetry-100%25%20Real%20Measured-teal?style=flat-square)](https://github.com/zhijaysun0915/UniPowerGuard)

> 🚀 **免安裝直接線上執行 (不依賴本地後端、內建雲端 SQL 引擎)**：  
> 👉 **[https://zhijaysun0915.github.io/UniPowerGuard/](https://zhijaysun0915.github.io/UniPowerGuard/)**

---

## 🌟 核心設計原則 (Strict Real Measurement & Cloud SQL)

1. **100% 實際硬體感測器量測值 (`實際量測值`)**：
   * 絕不回填假造歷史數據，亦不使用規格書公式捏造瓦數。
   * **有硬體感測器之項目**：直接讀取並記錄實際量測數值（如 Intel RAPL CPU 封裝/核心功率、NVIDIA `nvidia-smi` GPU 功率/溫度/轉速/P-State、ACPI 主機板環境溫度 `_TZ.TZ00`、WMI 記憶體容量與電壓、磁碟容量、`Get-Process` 各程序實際 CPU 秒數與記憶體 MB）。
   * **無硬體感測器或未開機記錄之項目/時段**：資料庫嚴格儲存為 `NULL`，前端介面統一顯示為 **`--`**（如無智慧插座功率計之 AC 牆壁功耗 `-- W`、無溫度暴露之 CPU 溫度 `-- °C`、無感測器之 RAM/硬碟/主機板獨立瓦數 `-- W`、桌機無電池 `-- %`、尚未量測之歷史月份/日期/小時 `--`）。
2. **不依賴本地、可完全線上運行 (`Cloud SQL in Browser`)**：
   * 線上網頁內嵌 **SQL.js (SQLite WebAssembly)** 引擎，開啟網頁時自動從雲端載入 `cloud_db.json` / `power_history.db`，在瀏覽器記憶體中建立完整的 SQLite 關聯式資料表（`hourly_logs`、`sensor_samples`、`app_energy_logs`、`control_logs`）。
   * 即使完全不開本地 Python 服務，也能在線上直接切換所有分頁、檢視實測數據、並在「🔍 歷史查詢 & 雲端SQL」分頁執行任意標準 `SELECT` SQL 查詢！

---

## 📊 `SUN_PC` 實測感測項目與 `--` 對應一覽表

| 設備 / 欄位 | 感測器來源 | 實測狀態与顯示範例 |
| :--- | :--- | :--- |
| **CPU 封裝/核心功耗** | `\Energy Meter(rapl_package0_pkg / pp0)\Power` | ✅ **實測值** (`17.93 W ~ 25.40 W`) |
| **CPU 負載率 & 時脈** | `\Processor(_Total)\% Processor Time` / `Win32_Processor` | ✅ **實測值** (`12.6%` / `3300 MHz`) |
| **CPU 溫度** | WMI 未暴露核心溫度計 | ⚪ 顯示 **`-- °C`** |
| **GPU 功耗 / 功耗上限** | `nvidia-smi` (`power.draw` / `power.limit`) | ✅ **實測值** (`5.19 W ~ 8.33 W` / `171 W`) |
| **GPU 溫度 / P-State / 風扇 / VRAM** | `nvidia-smi` | ✅ **實測值** (`34~36 °C` / `P8` / `0%` / `2397 MB`) |
| **RAM 使用量 / 電壓** | `Win32_OperatingSystem` / `Win32_PhysicalMemory` | ✅ **實測值** (`29.49 / 63.46 GB` · `1.10 V`) |
| **RAM 功耗 / 溫度** | `rapl_package0_dram` 回傳 0、無溫度計 | ⚪ 顯示 **`-- W`** / **`-- °C`** |
| **硬碟容量 (9 顆實體硬碟)** | `Win32_PhysicalDisk` / `Win32_LogicalDisk` | ✅ **實測值** (`3793.7 / 6183.3 GB`) |
| **硬碟功耗 / 溫度** | 無硬碟瓦數計、`Get-StorageReliabilityCounter` 為空 | ⚪ 顯示 **`-- W`** / **`-- °C`** |
| **主機板環境溫度** | `MSAcpi_ThermalZoneTemperature` (`_TZ.TZ00` = `301.0 K`) | ✅ **實測值** (`27.9 °C`) |
| **主機板 / 風扇功耗** | 無主機板獨立功率計 | ⚪ 顯示 **`-- W`** |
| **感測器實測總功 (CPU+GPU)** | `CPU RAPL + GPU SMI` | ✅ **實測值** (`26.26 W ~ 30.55 W`) |
| **AC 牆壁插座功率計** | 未連接外部智慧插座 | ⚪ 顯示 **`-- W`** |
| **電池狀態 (`SUN_PC` 桌機)** | `Win32_Battery` (0 顆電池) | ⚪ 顯示 **`-- %`** (無電池硬體) |
| **APP 程序資源消耗** | `Get-Process` (`CPU` 秒數與 `WorkingSet64` MB) | ✅ **實測秒數/佔比/MB** (`L2.bin`、`chrome`、`parsecd` 等)；單一程序瓦時顯示 **`-- Wh`** |

---

## 📱 四大分頁與所有子選項完整功能

1. **🔌 用電總覽 (`Overview`)**：
   * 支援 **`[年]`、`[月]`、`[日]`、`[時]`** 四種時間粒度切換。
   * 支援 **`總用電量 (kWh/Wh)`、`平均功率 (W)`、`實測電費 (NT$)`** 指標下拉切換與單價設定。
   * 有實際取樣的時段顯示真實柱狀圖與樣本數；未取樣的時段嚴格顯示 `--`。
2. **📋 電腦設備資訊 (`Devices & Control`)**：
   * 顯示主機名稱、目前實際生效之 Windows 電源計畫、主機板 ACPI 實測溫度 (`27.9 °C`)、感測器實測功耗 (`CPU+GPU`) 與 AC 插座 (`-- W`)。
   * **一鍵控制**：省電模式 (`a1841308`)、平衡模式 (`381b4222`)、高效能模式 (`8c5e7fda`)、釋放 AI 顯存，每次點擊皆會記錄至 `control_logs` SQL 資料表。
   * **6 張硬體組件卡片**：CPU、GPU、RAM、實體磁碟陣列、主機板、AI 服務，全數顯示實測值或 `--`。
3. **🔋 電池與 APP 耗電 (`Battery & Apps`)**：
   * 支援 **`[過去 24 小時]`** 與 **`[過去 10 天]`** 切換。
   * 顯示實測功率柱狀圖、實測 CPU 負載率柱狀圖，以及真實執行中程序 (`L2.bin`、`chrome`、`parsecd`、`explorer`、`audiodg`、`python` 等) 之 CPU 秒數、佔比 `%`、記憶體 `MB` 與 `-- Wh`。
4. **🔍 歷史查詢 & 雲端 SQL (`History & Cloud SQL Console`)**：
   * 內建 **線上 SQL 查詢主控台**，可直接在網頁執行標準 SQL 查詢 `hourly_logs`、`sensor_samples`、`app_energy_logs`、`control_logs` 四張表。
   * 支援一鍵同步最新實測資料至 GitHub 雲端與匯出實測 CSV 報表。

---

## 🚀 本地感測器採集與雲端同步指令

```powershell
# 啟動本地背景採集與 API 服務 (每 10 秒自動讀取硬體感測器並更新 power_history.db 與 cloud_db.json)
python server.py

# 單次抓取實測值並更新雲端 JSON 快照
python server.py --once
```
