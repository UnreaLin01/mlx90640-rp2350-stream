# 除錯與硬體驗證

這份文件收錄開發階段才會用到的東西，包含怎麼讀韌體的 log、怎麼查出當機的位置、怎麼細看串流的品質，以及幾支用來驗證硬體的測試韌體。如果你只是想接上板子看熱影像，照 [README](../README.md) 走就夠了，不需要這裡的任何內容。

## 讀韌體的 log

韌體所有的 log 都送到 SEGGER RTT，由 J-Link 透過 SWD 直接讀取記憶體取出，因此不佔用任何腳位，也不會影響 I2C 的時序。這也是專案規格的要求，USB 通道專門用來傳影像資料，不摻雜 log。

```bash
powershell -File scripts/rtt.ps1
powershell -File scripts/rtt.ps1 -Elf build/firmware/net_test.elf
powershell -File scripts/rtt.ps1 -Stop
```

log 會同時顯示在終端機並寫進 `logs/` 資料夾。VS Code 的工作清單裡也有 RTT log 這一項可以直接叫起來。

接 J-Link 的時候，除了 SWDIO 與 SWCLK 之外記得把 VTref 接到開發板的 3V3。J-Link 靠這支腳判斷目標板的工作電壓，沒接的話它會認為板子沒通電而拒絕連線。

> [!WARNING]
> RTT 的緩衝區有 8 KB，logger 接上去的時候會先讀到上一次執行留下來的舊內容，所以 log 的開頭常常看起來像是多開機了一次。分析的時候要特別注意這一點，不然很容易誤判。

## 查出當機的位置

先用 J-Link Commander 連上開發板並且停住 CPU。要看核心 1 的話，把裝置名稱換成 `RP2350_M33_1`。

```bash
"C:\Program Files\SEGGER\JLink\JLink.exe" -NoGui 1 -device RP2350_M33_0 -if SWD -speed 4000 -autoconnect 1
```

連上之後輸入 `halt` 停住 CPU，`regs` 讀出暫存器，`mem32 <SP> 0x40` 把堆疊內容倒出來。拿到 PC 或 LR 的位址之後，再用下面的指令把位址對應回原始碼的行號。

```bash
~/.pico-sdk/toolchain/15_2_Rel1/bin/arm-none-eabi-addr2line.exe -f -e build/firmware/mlx_thermal_udp.elf 0x10000E94
```

> [!WARNING]
> J-Link 的 reset 只會重置核心 0，核心 1 會繼續執行上一版韌體留下來的程式。所以有用到核心 1 的韌體必須在啟動前先呼叫 `multicore_reset_core1()`，否則開機會直接卡住。這件事已經在 `transport_udp.c` 裡處理好了，但你日後如果自己寫雙核心的程式，記得也要這樣做。

## 細看串流品質

開發板每秒會主動送一個 STATUS 封包出來，裡面帶了讀取錯誤、subpage 順序錯誤、等待逾時、傳輸丟包與最長讀取時間。串流統計工具會把這些數字連同 CRC 錯誤、序號跳號與實際幀率一起印出來，最後給一個 PASS 或 FAIL。

```bash
host/.venv/Scripts/python host/stream_stats.py --source usb --duration 60
host/.venv/Scripts/python host/stream_stats.py --source udp --duration 300 --save captures/run.bin
```

加上 `--save` 會把收到的原始位元組錄下來，之後可以用 `viewer.py --replay 檔案` 離線重播，開發顯示功能的時候就不必一直接著開發板。

> [!NOTE]
> 幀率是用第一個到最後一個 subpage 之間的時間算的，不含程式啟動到收到第一包之前的空窗，否則短時間的測試會把幀率算得偏低。

## 檢查換算出來的溫度

這支工具會把每一張完整影像都換算一次，確認沒有 NaN 或無限大、影像中位數落在 15 到 40 度的室溫範圍內、感測器自身溫度 Ta 落在 15 到 60 度之間，同時報告一次換算要花多久。

```bash
host/.venv/Scripts/python host/check_temps.py --duration 20
host/.venv/Scripts/python host/check_temps.py --file captures/m4_stream_65s.bin
```

預設走 numpy 實作。加上 `--calc melexis` 會改用 Melexis 官方的 C 程式，但要先執行 `scripts/build_host_lib.ps1` 編出 DLL。兩者的比對結果記錄在 [method_b_compare.md](method_b_compare.md)。

## 測試網路吞吐量

先燒錄 `net_test` 韌體，它會回應 ping 並且提供一個 UDP 吞吐量測試的端點，再從電腦端跑對應的腳本。

```bash
host/.venv/Scripts/python host/net_test.py
```

## 驗證硬體的測試韌體

| 韌體 | 用途 |
|---|---|
| `pin_test` | 在四支量測腳位上輸出不同頻率的方波，用來確認邏輯分析儀的通道對應正確 |
| `rise_test` | 量測 I2C 線路的訊號上升時間 |
| `eeprom_test_400k`、`eeprom_test_1000k` | 以指定的速率讀取 EEPROM 並驗證內容 |
| `eeprom_soak_1000k` | 1 MHz 下的長時間連續讀取測試 |
| `net_test` | 乙太網路測試，包含 ping 與 UDP 吞吐量 |

如果你日後動到 I2C 的接線或換了上拉電阻，重新跑 `rise_test` 與 `eeprom_soak_1000k` 可以確認線路品質還撐得住 1 MHz。重新接邏輯分析儀的探棒之後，先跑一次 `pin_test` 確認通道沒有接反，可以省掉後面一堆誤判。

量測腳位的定義是 GP6 在讀取感測器的期間維持高電位，GP7 每收到一個新的 subpage 就翻轉一次。搭配 `host/tools/` 裡的分析腳本，可以量出 I2C 波形、subpage 讀取時間與訊號上升時間。

`mlx_thermal_16hz` 與 `mlx_thermal_64hz` 是主韌體換成不同更新率的版本，用來比較不同速率下的時序表現。

實測的數據與結論記錄在下面兩份文件裡。

- [m2_i2c.md](m2_i2c.md) I2C 通訊與訊號品質
- [m3_timing.md](m3_timing.md) I2C 時序與 subpage 讀取時間
