# M4 USB 串流量測紀錄

日期：2026-09-20　韌體：`mlx_thermal`（32 Hz）　電腦端：`host/stream_stats.py`（Python 3.13 venv）

## 1. 架構

- **封包**：`docs/protocol.md`（v1）。每個封包 ≤ 1052 bytes，可直接放進一個 UDP datagram；subpage／EEPROM 拆成 2 段。
- **韌體**
  - `protocol.c`：封包組裝、CRC-32（查表法，與 zlib.crc32 相同）。
  - `stream.c`：把 subpage／EEPROM／STATUS 切段交給傳輸層。
  - `transport.h`：傳輸層介面（`transport_send` 不阻塞，放不下就整包丟棄並計數）；`transport_usb.c` 為 USB 實作（TinyUSB CDC，自己的描述元，不用 `stdio_usb`，USB 只傳封包）。
  - 單核心、無 RTOS：USB 背景工作（`tud_task`）透過 `i2c_bus` 的 idle hook，在等待感測器、等待 DMA 時執行。
  - EEPROM：電腦打開 port（DTR）時立即送一次，之後每 2 秒重送。
  - STATUS：每秒一次，含讀取錯誤、順序錯誤、等待錯誤、丟包數、最長讀取時間。
- **電腦端**（`host/mlxstream/`）：`protocol.py`（重新同步解析）、`blocks.py`（分段組回區塊、序號檢查）、`sources.py`（資料來源抽象；目前 `SerialSource`，以 VID/PID 找 COM port）。
- **USB**：VID 0x2E8A／PID 0x0009，產品名 `MLX90640 Thermal Stream`，Windows 上為 COM9。

## 2. 解析器單元測試

`host/.venv/Scripts/python host/tests/test_protocol.py -v`：8 項全過（乾淨串流、逐位元組餵入、前後夾垃圾、從封包中間開始、翻轉 1 bit、序號跳號、不同 type 各自序號、frameData 組裝）。

## 3. 60 秒驗收（實跑 65 秒）

`host/.venv/Scripts/python host/stream_stats.py --duration 65 --save captures/m4_stream_65s.bin`
輸出：`logs/m4_stream_stats_65s.txt`

| 項目 | 結果 |
|---|---|
| 封包／subpage | 4,198 封包，2,034 個 subpage |
| CRC 錯誤 | 0 |
| subpage 序號跳號 | 0 |
| 不完整區塊 | 0 |
| subpage 0/1 交替錯誤 | 0 |
| 裝置端 subpage 速率（依裝置時間戳） | 31.292 Hz（M3：31.28 Hz） |
| 電腦端接收速率 | 31.285 Hz |
| 重新同步略過的位元組 | 0 |
| 裝置 STATUS 新增錯誤／丟包 | 0／0 |
| EEPROM | 收到 33 次，全部相同 |

另外檢查：串流中的 EEPROM 與 M2 以 RTT dump 的內容 832 words 完全相同（位元組順序正確）；subpage 控制暫存器 0x1B01（更新率代碼 6）。

## 4. USB 是否拖慢 I2C（計時標記，Logic 8 50 MS/s，串流進行中擷取 2 秒）

| 項目 | M3（無 USB） | M4（USB 串流中） |
|---|---|---|
| subpage 讀取時間（mark A） | 17.484 ms | 17.469 ms |
| SCL 速率／位元組間空檔 | 893 kHz／無 | 893 kHz／無 |
| 偵測延遲變動（mark B 對固定週期直線的殘差最大值） | 264 µs | 248 µs |

結論：USB 串流沒有拖慢 I2C 讀取，也沒有延後新資料的偵測（變動都在 200 µs 輪詢間隔＋一次 status 讀取以內）。

## 5. M4 結論

依 CLAUDE.md 的 M4 驗收條件全部通過：連續 60 秒以上無 CRC 錯誤、無序號跳號，幀率符合 M3 設定，計時標記確認 USB 沒有拖慢 I2C。
