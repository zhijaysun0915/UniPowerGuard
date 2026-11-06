# UniPowerGuard ⚡ — 跨平台電腦與筆電電源管控中心 (Cross-Platform Power & Battery Manager)

[![GitHub Pages](https://img.shields.io/badge/Demo-GitHub%20Pages-2ea44f?style=flat-square&logo=github)](https://zhijaysun0915.github.io/UniPowerGuard/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-blue?style=flat-square)](https://github.com/zhijaysun0915/UniPowerGuard)
[![License](https://img.shields.io/badge/License-MIT-orange?style=flat-square)](LICENSE)
[![Zero Dependency](https://img.shields.io/badge/Dependencies-Zero%20(Python%20Stdlib)-brightgreen?style=flat-square)](https://github.com/zhijaysun0915/UniPowerGuard)

> 🚀 **免安裝直接線上體驗 Live Demo**：[https://zhijaysun0915.github.io/UniPowerGuard/](https://zhijaysun0915.github.io/UniPowerGuard/)  
> （點擊上方連結即可在瀏覽器直接操作完整 UI、分頁切換、節點模擬與電費試算！）

---

## 🌟 簡介 (Overview)

**UniPowerGuard** 是一套專為 **Windows（桌機 / 筆電）** 與 **macOS（MacBook / Mac mini）** 設計的輕量化、通用跨平台電腦電源監控與管控系統。

本專案**零外部套件依賴 (Zero Dependency)**，完全使用 Python 內建標準庫（Standard Library）搭配輕量 SQLite 資料庫與 HTML5 + Tailwind CSS 現代化前端，可自動記錄**每年 / 每月 / 每日 / 每時**之功耗、度數（kWh）與電費，並具備即時硬體電源策略切換功能。

---

## 📱 核心介面特色 (UI Features)

本系統參考現代主流電力 APP 與行動裝置系統介面進行整合設計：

1. **🔌 用電總覽 (Overview)**
   * **年 / 月 / 日 / 時** 四種粒度無縫切換。
   * 柱狀圖對比（前期 vs 當期），點擊任一長條即時顯示虛線導航與精確度數。
   * 自訂每度電單價（新台幣 NT$），即時試算累計度數與預估電費。
2. **📋 電腦設備與電源管控 (Devices & Control)**
   * 頂部即時顯示機殼環境溫度、AC 市電輸入功耗與 DC 直流內部功耗。
   * **👍 一鍵快速控制**：
     * 🌿 **省電靜音模式**（Windows 省電方案 + GPU 162W 功耗牆）
     * ⚖️ **日常平衡模式**（Windows 平衡方案 + GPU 171W 最佳甜蜜點）
     * 🚀 **AI 算力全開**（Windows 高效能方案 + GPU 180W 滿血釋放）
     * 🧹 **釋放 AI 顯存**（一鍵卸載本地 Ollama / Strata 避免顯存與待命耗電）
   * **🏠 硬體組件卡片**：即時顯示 CPU (RAPL)、GPU (NVIDIA)、RAM、SSD/HDD 儲存陣列、主機板與散熱群之個別瓦數與運作狀態。
3. **🔋 電池與 APP 耗電 (iOS Battery Style)**
   * 經典 **過去 24 小時 / 過去 10 天** 時間軸切換。
   * 綠色電量/負載曲線（支援筆電充電狀態指示條）。
   * 藍色活躍運算時間柱狀圖（滿載 60 分鐘基準）。
   * **依 APP / 處理程序分類之用電排行榜**：精確計算 Chrome、Office、Parsec、Python AI、Explorer 等程序之耗電佔比（%）與瓦時（Wh）。
4. **🔍 歷史查詢 (History & Export)**
   * 詳細紀錄每小時、每日、每月之平均功率、峰值功率、CPU/GPU 分流耗電與度數。
   * 支援一鍵匯出 **CSV 報表**。

---

## 💻 支援平台與感測器對應 (Cross-Platform Telemetry)

| 平台類別 | 代表裝置 | 硬體感測器與控制方式 |
| :--- | :--- | :--- |
| **Windows 桌機** | `SUN_PC` (Intel Core Ultra 7 265K + RTX 5060 Ti) | • **CPU**：Intel RAPL 硬體暫存器 (`rapl_package0_pkg`)<br>• **GPU**：`nvidia-smi` 即時瓦數、溫度、時脈與 P-State<br>• **控制**：`powercfg /setactive` + `nvidia-smi -pl` 功耗牆限制 |
| **Windows 筆電** | 各廠牌 Windows 筆電 | • **電池**：Win32_Battery API 取得電池殘量與充放電狀態<br>• 自動偵測 Optimus 獨顯休眠與螢幕背光能耗 |
| **macOS 筆電** | Apple MacBook Air / MacBook Pro | • 呼叫 `pmset -g batt` 與 `AppleSmartBattery` 讀取充放電週期與電量<br>• 監控系統活躍度與低耗電模式 (Low Power Mode) |
| **macOS 迷你主機** | Apple Mac mini Gateway / Studio | • 常駐極低功耗模式（10~15W 待命）監控<br>• 支援遠端調度 GPU 算力機與 SSH 關閉算力節點 |

---

## 🚀 快速啟動指南 (Quick Start)

### 方式 A：免安裝直接在瀏覽器預覽 (GitHub Pages)
直接點擊：[https://zhijaysun0915.github.io/UniPowerGuard/](https://zhijaysun0915.github.io/UniPowerGuard/)

---

### 方式 B：本地運行（連接本機硬體感測器）

#### 1. 下載專案
```bash
git clone https://github.com/zhijaysun0915/UniPowerGuard.git
cd UniPowerGuard
```

#### 2. 啟動服務

* **Windows 用戶**：
  直接按兩下執行 **`start_windows.bat`**  
  *或在 PowerShell 執行：*
  ```powershell
  python server.py
  ```

* **macOS / Linux 用戶**：
  在終端機執行：
  ```bash
  chmod +x start_mac.sh
  ./start_mac.sh
  ```
  *或直接執行：*
  ```bash
  python3 server.py
  ```

#### 3. 開啟管控介面
服務啟動後，瀏覽器會自動開啟，亦可手動訪問：
* 本機訪問：`http://127.0.0.1:8095`
* 區網設備（Mac mini、手機、平板）：`http://<這台電腦的區域IP>:8095`

---

## 📂 專案結構 (Directory Layout)

```text
UniPowerGuard/
├── index.html            # 現代化響應式前端 (HTML5 + Tailwind CSS + 多分頁架構)
├── server.py             # 輕量後端與硬體感測器採集引擎 (純 Python 標準庫，零依賴)
├── start_windows.bat     # Windows 一鍵啟動批次檔
├── start_mac.sh          # macOS / Linux 一鍵啟動腳本
├── power_history.db      # SQLite 本地歷史資料庫 (初次啟動自動生成)
├── LICENSE               # MIT 開源授權條款
└── README.md             # 專案詳細說明文件
```

---

## 📄 授權條款 (License)

本專案採用 [MIT License](LICENSE) 開源授權，歡迎自由修改、擴充與整合。
