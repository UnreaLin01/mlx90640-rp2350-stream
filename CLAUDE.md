# CLAUDE.md — MLX90640 熱影像串流（W6300-EVB-Pico2）

## 專案目標

第一步（目前唯一範圍）：在 W6300-EVB-Pico2 上撰寫韌體，以 I2C 高速讀取 MLX90640 熱影像感測器，把原始資料串流到電腦，電腦端換算溫度並即時顯示。

傳輸分兩階段：**先用 USB 串流把感測器、協定、電腦端顯示全部做到穩定**，最後才把傳輸層換成 W6300 乙太網路。

第二步（暫定，**未經使用者同意不要開始**）：用 MLX90640 量測生理訊號，優先目標為呼吸率。

## 硬體

| 項目 | 規格 |
|---|---|
| 開發板 | WIZnet W6300-EVB-Pico2（RP2350A，Cortex-M33 ×2，520 KB SRAM，2 MB Flash） |
| 乙太網路 | W6300，經 PIO 以 QSPI 連接，**GPIO15～22 保留給 W6300，禁止另作他用** |
| 感測器 | MLX90640（32×24，I2C，最高 1 MHz Fast-mode Plus） |
| 除錯器 | SEGGER J-Link EDU，SWD 介面 |
| 邏輯分析儀 | Saleae Logic 8，透過 Logic 2 MCP server 控制 |
| 主機 | Windows，PowerShell（pwsh） |
| USB | RP2350 原生 USB（Full-speed 12 Mbps），以 USB CDC 傳輸影像資料 |

## 腳位與接線【使用者需確認後再開始 M2】

| 訊號 | RP2350 腳位 | 接到 | Logic 8 通道 |
|---|---|---|---|
| I2C0 SDA | GP4 | MLX90640 SDA | CH1 |
| I2C0 SCL | GP5 | MLX90640 SCL | CH0 |
| 計時標記 A | GP6 | —（僅供量測） | CH2 |
| 計時標記 B | GP7 | —（僅供量測） | CH3 |
| 板載 LED | GP25 | — | — |
| SWD | SWCLK / SWDIO / GND 除錯排針 | J-Link（已驗證可連線） | — |

- J-Link 的 VTref 必須接到板子的 3V3，否則 J-Link 偵測不到目標電壓。
- MLX90640 模組供電 3.3V。1 MHz I2C 需要夠小的上拉電阻，是否足夠以 Logic 8 量測上升時間判斷，不要用猜的。
- Logic 8 與開發板必須共地。

## 工具鏈

- **編譯**：Pico SDK + CMake + Ninja + arm-none-eabi-gcc（由 VS Code 的 Raspberry Pi Pico 擴充功能安裝於 `%USERPROFILE%\.pico-sdk\`）。建置目標板設為 `pico2`。
- **乙太網路驅動**：以 WIZnet 官方 `WIZnet-PICO-C` 範例的 ioLibrary 與 W6300 QSPI（PIO）port 為基礎，`BOARD_NAME` 設為 `W6300_EVB_PICO2`，QSPI 模式用 `QSPI_QUAD_MODE`。
- **MLX90640 驅動**：以 Melexis 官方 `mlx90640-library` 為準。韌體端只需要 I2C 讀寫與取得原始 frame data；溫度換算在電腦端做。
- **燒錄**：J-Link Commander，裝置名稱 `RP2350_M33_0`，SWD 4000 kHz（使用者已驗證可連線）。執行檔：`C:\Program Files\SEGGER\JLink\JLink.exe`。
- **Log**：SEGGER RTT（原始碼在 J-Link 安裝目錄的 `Samples/RTT`），用 `JLinkRTTLogger` 存到 `logs/` 讓自己讀。不使用 UART printf，避免干擾 I2C 時序。燒錄前先停掉 RTT logger。
- **USB 只傳影像資料，不傳 log**：log 一律走 RTT，USB CDC 通道專門傳影像封包，兩者不可混用。不要啟用 `stdio_usb` 把 printf 導到 USB。
- **邏輯分析儀**：Logic 2 MCP server（`http://127.0.0.1:10530`）。Logic 8 的門檻電壓是固定的，**不要傳 `digitalThresholdVolts`**。I2C 量測取樣率至少 25 MS/s。擷取檔與匯出的 CSV 放在 `captures/`。
- **電腦端**：Python 3，套件需求寫在 `host/requirements.txt`。

## 串流協定（USB 與乙太網路共用）

- 封包格式由你設計，**必須與傳輸層無關**：USB 和乙太網路使用同一種封包，換傳輸層時不改封包格式。
- 必須包含：magic、協定版本、封包長度、幀序號、subpage 編號、時間戳、原始資料 payload、CRC。
- USB CDC 是位元組串流、沒有封包邊界，接收端要能靠 magic＋長度＋CRC 重新同步（例如中途開始接收、資料錯位時）。
- EEPROM 校正資料要能讓晚啟動的接收端也拿得到（例如定期重送，或回應請求）。
- 格式定稿後寫進 `docs/protocol.md`。

## 網路設定（M6 起才需要）

- 電腦乙太網路介面：靜態 IP `192.168.50.1/24`（由使用者設定）
- 開發板：靜態 IP `192.168.50.10/24`
- 串流：UDP，開發板送往 `192.168.50.1:5005`，一個 UDP datagram 放一個完整封包

## 架構原則

1. 韌體只送原始資料（EEPROM 832 words 與每個 subpage 的 frame data），不在 MCU 上算溫度。
2. 效能瓶頸在 I2C，不在傳輸層（USB 與乙太網路的頻寬都遠大於需求）。優化順序：I2C 時脈與讀取時序 → 避免阻塞（視需要用 DMA 或雙核分工）→ 傳輸層。
3. 傳輸層抽象化：韌體端把「送出一個封包」包成介面，USB 與 W6300 各實作一份；電腦端接收程式把資料來源（COM port／UDP socket）抽象化，解析、統計、顯示的程式碼共用。
4. 讀取 subpage 的邏輯（等待 status register 的 new-data flag、清除 flag、判斷 subpage）以 Melexis 官方驅動的行為為準。
5. 用 GP6／GP7 翻轉作為計時標記（例如：開始讀取、讀取完成、封包送出），以 Logic 8 量測，而不是用 RTT 時間戳估計。USB 中斷可能影響 I2C 讀取時序，這點也要用計時標記確認。

## 里程碑與驗收條件

每完成一個里程碑：更新本檔的「目前進度」、git commit，然後停下來向使用者回報結果與量測數據。

- **M0 環境檢查（不寫韌體）**：確認 cmake、ninja、arm-none-eabi-gcc、Pico SDK、J-Link、Python、git 都找得到並列出版本；J-Link 能連上並辨識 RP2350；Logic 2 MCP 能列出實體 Logic 8。缺什麼就列出來請使用者安裝，不要自己改系統設定。
- **M1 燒錄與 log**：LED 閃爍＋RTT 每秒印出計數。驗收：`logs/` 內的 RTT 輸出計數持續遞增。
- **M2 I2C 通訊**：以 400 kHz 讀取 MLX90640 EEPROM，再提升到 1 MHz。驗收：裝置 ACK、EEPROM 內容與 Logic 8 的 I2C 解碼一致、1 MHz 下波形上升時間合格。
- **M3 讀取時序**：設定更新率（基準 32 Hz subpage rate，挑戰 64 Hz），連續讀取 subpage。驗收：以計時標記量出單一 subpage 讀取時間，並低於 subpage 週期的一半。
- **M4 USB 串流**：原始 subpage 資料經 USB CDC 串流，電腦端接收腳本統計幀率、CRC 錯誤、序號連續性。驗收：連續 60 秒無 CRC 錯誤、無序號跳號，幀率符合 M3 設定；並以計時標記確認 USB 傳輸沒有拖慢 I2C 讀取。
- **M5 顯示（USB）**：電腦端換算溫度並即時顯示熱影像。自動驗收：溫度落在合理範圍（室溫約 15～40°C）。最終驗收由使用者目視確認（手靠近時影像與溫度要有對應變化）。**M5 通過代表整條資料路徑已穩定，之後只換傳輸層。**
- **M6 乙太網路 bring-up**：W6300 初始化、電腦 ping 得到開發板、UDP 吞吐量測試。此階段不接感測器資料。驗收：ping 成功，UDP 吞吐量數據寫入報告。
- **M7 乙太網路串流**：把 M4 的傳輸層換成 UDP，封包格式不變，電腦端只換資料來源。驗收：連續 60 秒掉包率 < 0.1%、幀率符合 M3 設定、M5 的顯示程式不需修改即可運作；比較 USB 與乙太網路的延遲與穩定度，寫入報告。

## 目前進度

- [x] M0　- [ ] M1　- [ ] M2　- [ ] M3　- [ ] M4　- [ ] M5　- [ ] M6　- [ ] M7

## 必須停下來找使用者的情況

- 需要改接線、插拔裝置、按 BOOTSEL、把感測器對準某處等實體操作。
- 需要安裝軟體，或修改 Windows 網路介面、防火牆等系統設定。
- 同一個問題連續嘗試 3 次仍失敗：停止嘗試，列出你目前的假設與下一個想驗證的點。
- 任何要寫入 RP2350 **OTP** 的操作：一律禁止（OTP 無法復原）。

## 程式碼風格

- C 語言使用 1TBS 風格：縮排用 tab（寬度 2），所有大括號與陳述式同一行，函式定義也一樣（`void f(void) {`、`if (x) {`、`} else {`）。
- 關鍵字與小括號之間空一格（`if (x)`、`while (1)`），函式呼叫不空格（`f(x)`）。
- 指標星號靠變數名（`char *p`）。
- 單行的 if／迴圈也一律加大括號。
- 函式呼叫換行時，續行對齊左括號：縮排用 tab、對齊填充用空格。
- 第三方程式碼（Pico SDK、WIZnet ioLibrary、Melexis library、SEGGER RTT）維持原樣，不套用上述風格。
- git commit 訊息只寫一句話，簡短描述改了什麼。

## 目錄結構（建議）

```
firmware/     韌體（CMake 專案）
host/         電腦端 Python：接收、統計、溫度換算、顯示
scripts/      燒錄、RTT、建置等 PowerShell 腳本
docs/         protocol.md、各里程碑的量測紀錄
captures/     Logic 8 擷取與匯出（加入 .gitignore）
logs/         RTT log（加入 .gitignore）
third_party/  Pico SDK 以外的外部程式碼
```
