# M2 I2C 通訊量測紀錄

日期：2026-09-19　硬體：W6300-EVB-Pico2 + Adafruit MLX90640 模組（板載上拉，阻值未知）

## 1. ACK 與 EEPROM 內容

| 項目 | 400 kHz | 1 MHz |
|---|---|---|
| 韌體 | `eeprom_test_400k` | `eeprom_test_1000k` |
| 裝置 ACK（位址 0x33、暫存器位址） | ✅ | ✅ |
| 連續讀取次數／與第一次不同的次數 | 6／0 | 12／0 |
| Logic 8 線上解碼 vs RTT dump（832 words） | 0 差異 | 0 差異 |
| 400k 與 1M 兩次 dump 互相比對 | — | 完全相同 |
| EEPROM 0x240F（I2C 位址） | 0xBE33 | 0xBE33 |

線上解碼使用 `host/tools/i2c_decode.py`（Logic 2 MCP 的 I2C analyzer 設定參數無法通過驗證，見下方「已知問題」）。
檢查：`python host/tools/check_eeprom_capture.py captures/m2_ee1m/digital.csv logs/ee1m_*.log`

**Logic 2 內建 I2C analyzer 交叉驗證（1 MHz，capture `m2_ee1m_gui`）**：使用者在 GUI 加 analyzer（SDA=CH0、SCL=CH1），以 Hex 匯出後三方比對：

| 比對 | 結果 |
|---|---|
| Logic 2 analyzer vs RTT dump | 832／832 words，0 差異 |
| Logic 2 analyzer vs `i2c_decode.py` | 832／832 words，0 差異 |

指令：`python host/tools/check_logic2_i2c_table.py captures/m2_ee1m_gui/i2c_gui_hex.csv logs/ee1m_gui_20260920_010238.log captures/m2_ee1m_gui/digital.csv`
結論：自寫解碼器與 Logic 2 analyzer 結果一致，之後以自寫解碼器自動驗證即可。

## 2. 時序（Logic 8，50 MS/s）

| 項目 | 400 kHz 設定 | 1 MHz 設定 |
|---|---|---|
| SDK 計數 lcnt / hcnt / spklen（clk 150 MHz） | 225 / 150 / 14 | 90 / 60 / 5 |
| 實測 SCL（位元組內） | 346 kHz | 806 kHz |
| SCL low（中位數） | 1.620 µs | 0.720 µs |
| SCL high（中位數） | 1.180 µs | 0.520 µs |
| 位元組之間額外停頓 | 幾乎沒有 | 每位元組約 +0.84 µs |
| 整份 EEPROM（1668 bytes）線上時間 | 43.37 ms | 20.02 ms（有效 750 kbit/s） |
| mark A（整個 `MLX90640_DumpEE` 呼叫） | 43.42 ms | 20.07 ms |

說明：
- RP2350 的 I2C 控制器（DesignWare）SCL high 實際約為 (hcnt + spklen + 7) 個週期，且要等 SCL 真的升到門檻才開始計數，所以實際頻率低於設定值。
- 1 MHz 時 SDK 的 `i2c_read_*` 每個位元組都停下來等資料，造成位元組間空檔。**M3 需改用 DMA／預先填 FIFO**，並重新調整 lcnt/hcnt，否則 subpage 讀取（同樣 832 words）約 20 ms，超過 32 Hz 下的半週期 15.6 ms。

## 3. 上升時間（Logic 8，100 MS/s）

方法：`rise_test` 韌體用 PIO 在同一個時脈週期放開 SDA/SCL 並拉高 GP6 標記（推挽）。
上升延遲 − 下降延遲 = 線路從放開到越過 Logic 8 門檻的時間 t_th（平均約 72,900 個邊緣）。
Logic 8 門檻只知道介於 0.6～1.2 V，因此以 RC 曲線換算成範圍。

| | t_th | RC 時間常數 τ | 上升時間 30～70% | 1 MHz 上限 120 ns |
|---|---|---|---|---|
| SDA | 95.6 ns | 212～477 ns | 179～404 ns | ❌ 整個範圍超過 |
| SCL | 93.9 ns | 208～468 ns | 176～396 ns | ❌ 整個範圍超過 |

交叉驗證：I2C 實際波形中 SCL low 比程式設定的 (lcnt+1) 長約 113 ns，扣掉數個週期的同步延遲後，和 t_th ≈ 95 ns 一致。

### 3b. 類比量測（Logic 8 類比通道，10 MS/s，單通道各擷取一次）

Logic 8 類比頻寬約 1 MHz，本身步階響應約 150 ns（30～70%），不能直接讀。做法（`host/tools/analyze_rise_analog.py`，需 numpy，用 `py -3.13` 執行）：
1. 等效時間取樣：rise_test 週期固定（7.338 µs），擬合週期後依相位疊合約 3.2 萬個邊緣，重建 2 ns 解析度的波形（邊緣對齊抖動 2 ns rms）。
2. 以 GP6 推挽標記（邊緣只有數 ns）的類比波形當作 Logic 8 前端的步階響應，對 SDA/SCL 擬合「前端響應 ⊗ RC 曲線」的 τ。

| | 類比波形直接量 30～70% | 擬合 τ | 線路本身 30～70% 上升時間 | 擬合誤差 | 1 MHz（120 ns） | 400 kHz（300 ns） |
|---|---|---|---|---|---|---|
| SCL | 225 ns | 260 ns | **220 ns** | 0.1% rms | ❌ | ✅ |
| SDA | 226 ns | 264 ns | **224 ns** | 0.2% rms | ❌ | ✅ |

驗證：
- 反向模擬 τ=260 ns 經前端後的 30～70% = 227 ns，與實測 225 ns 相符。
- τ=260 ns 時到達數位量測 t_th（95 ns）的電壓約 0.97 V，落在 Logic 8 標示的 0.6～1.2 V 門檻範圍內，與 3. 的數位量測一致。
- 單一 RC 模型擬合誤差 ≤ 0.2%，BSS138 電位轉換的兩段式上升在此量測中看不出明顯偏離。
- 量測時 Logic 8 探棒接在線上，其輸入電容已包含在結果內；拔掉探棒時實際上升會略快。

結論：上升時間約 **220 ns**。1 MHz（Fast-mode Plus，120 ns）不合格；400 kHz（Fast-mode，300 ns）合格。1 MHz 雖然資料讀取正確，需要更強的上拉或降低匯流排電容才能符合規格。

### 3c. 1 MHz 實際 setup 餘裕（SDA 變化 → SCL 上升，於 Logic 8 門檻量測）

| | SDA 由上拉拉高 | SDA 被拉低 | 規格下限 |
|---|---|---|---|
| 400 kHz | 最小 1200 ns | 最小 1300 ns | 100 ns |
| 1 MHz | 最小 460 ns | 最小 580 ns | 50 ns |

以 τ=260 ns 換算，SDA 從 Logic 8 門檻（約 0.97 V）升到 70% VDD 還需約 0.85τ ≈ 220 ns，1 MHz 的實際 setup 餘裕約 460 − 220 ≈ 240 ns（保守估計，未計入 SCL 自己升到接收端門檻所需的時間），大於 50 ns。

## 4. 1 MHz 長時間測試（10 分鐘）

韌體 `eeprom_soak_1000k`：連續讀取整份 EEPROM（無間隔），每次與第一次讀取逐字比對，每 500 次記錄一次；任何錯誤字元與 I2C 錯誤都會立即記錄。第一次讀取的內容與 400 kHz 的 dump 完全相同（參考資料本身正確）。
Log：`logs/soak1m_20260920_012827.log`（Logic 8 探棒接在線上）

| 項目 | 結果 |
|---|---|
| 時間 | 623 s |
| 讀取次數 | 31,000 次（約 5,170 萬個資料位元組） |
| 讀錯的次數／字元 | 0／0 |
| I2C 錯誤（NACK／逾時） | 0 |
| 單次讀取時間 | 20.061～20.107 ms |
| log 完整性 | 62 行統計，編號連續無缺漏 |

## 5. M2 結論

依使用者 2026-09-20 修改後的驗收條件，M2 通過：ACK ✅、EEPROM 與 Logic 8 解碼一致 ✅、1 MHz setup 餘裕約 240 ns > 50 ns ✅、10 分鐘 0 錯誤 ✅。

## ⚠️ 待解決：1 MHz 上升時間不符合規格

- 現況：SDA／SCL 上升時間約 220 ns（τ≈260 ns），Fast-mode Plus 規格上限 120 ns。原因是 Adafruit 模組上的上拉（兩側各 4.7 kΩ，經 BSS138 電位轉換）對目前的線路電容太弱。
- 暫時接受的理由：實測 setup 餘裕約 240 ns（規格 50 ns），10 分鐘 31,000 次讀取 0 錯誤。
- 風險：餘裕取決於目前接線；換線、加長線、溫度變化都可能讓它變小。I2C 本身沒有錯誤檢查，讀錯不會被發現。
- 可能的解法：MCU 側 SDA/SCL 各加約 1 kΩ 上拉到 3.3 V、縮短線長、改接模組 3.3 V 側（繞過電位轉換）。
- 改了硬體之後：重跑 `rise_test`（數位＋類比量測）與 `eeprom_soak_1000k`。
- 在那之前：M3 起調整 SCL 時序時，SCL low 維持 ≥ 600 ns，只縮短 high；M3 的幀資料也要用 Melexis 的資料檢查輔助監控。

## 已知問題（工具）

- Logic 2 MCP 的 `add_analyzer`：參數驗證要求 `settings.SDA` 為 object，伺服器端卻要求 number，無法建立 I2C analyzer（試過 `{"value":0}`、`{"int64Value":0}`、`{"int64Value":"0"}`、`{"doubleValue":0}`、`{"int64_value":0}` 等皆失敗）。改用自寫解碼器。
- Logic 2 MCP 的 `export_data_table_csv` 不會沿用 GUI 的 radix；未指定 analyzerId＋radixType 時資料以 ASCII 輸出，43 種位元組值都變成 `.`，無法還原。GUI 建的 analyzer 其 ID 無法從 MCP 取得。
- `save_capture` 的目標資料夾不存在時會靜默失敗（回傳成功但沒有檔案）。先 `export_raw_data_csv`（會建立資料夾）再存檔。
