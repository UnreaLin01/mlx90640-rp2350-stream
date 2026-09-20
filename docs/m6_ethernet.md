# M6 乙太網路 bring-up 量測紀錄

日期：2026-09-20　韌體：`net_test`　電腦端：`host/net_test.py`

## 1. 連線架構

電腦沒有實體乙太網路埠，改為經路由器連線：開發板 ──網路線──> 路由器 ──Wi-Fi──> 電腦。
開發板 `192.168.1.200/24`（靜態），電腦 `192.168.1.247`（Wi-Fi，DHCP）。

## 2. WIZnet 驅動整合

- `third_party/WIZnet-PICO-C/`：只保留程式碼（去掉 41 MB 的文件圖片、mbedtls、pico-sdk submodule、.chm），含 `libraries/ioLibrary_Driver`（W6300 驅動）。
- `firmware/CMakeLists.txt` 以 `_WIZCHIP_=W6300`、`DEVICE_BOARD_NAME=W6300_EVB_PICO2`、`_WIZCHIP_QSPI_MODE_=QSPI_QUAD_MODE` 編譯所需檔案。
- 腳位由板子固定：INT 15、CS 16、SCK 17、IO0～IO3 18～21、RST 22，與 CLAUDE.md 保留的 GPIO15～22 一致，與 I2C（GP4/5）、計時標記（GP6/7）無衝突。
- PIO：WIZnet 取用一個未使用的狀態機；DMA：`dma_claim_unused_channel()` 取 2 個。與 `i2c_bus` 的 2 個 DMA 通道同為動態取得，不會互搶。
- `src/net.c`：初始化與狀態回報；MAC 由 RP2350 唯一碼產生（首位元組 0x02，本機管理位址）。

踩到的兩點：
1. 讀寫晶片暫存器的 callback 是在 WIZnet 的 `wizchip_initialize()` 內註冊的，必須先呼叫它，否則讀晶片 ID 得到 0x0000。
2. `wizchip_initialize()` 內有等待 PHY link 的無限迴圈，沒有逾時；網路線未接會卡住。已在呼叫前寫 log 標示。

## 3. 驗收一：ping

`Test-Connection 192.168.1.200 -Count 8`：8/8 成功，延遲 1～2 ms（第一筆 64 ms 含 ARP）。ARP 表顯示 `192.168.1.200 → 02-1e-16-f4-22-e6`。

## 4. 驗收二：UDP 吞吐量

電腦送出一個封包後，開發板以 1024 bytes payload 連續送 5 秒（每包前 4 bytes 為計數器）。
`logs/m6_udp_throughput.txt`

| 項目 | 結果 |
|---|---|
| 開發板送出 | 21,452 packets（板端 log 亦為 21,452，0 errors） |
| 電腦收到 | 21,452 packets，21,452 kB |
| 掉包 | **0（0.00%）**，亂序 0 |
| 吞吐量 | **35.34 Mbit/s**（4,313 kB/s；板端量得 4,393 kB/s） |

M7 串流需求約 0.43 Mbit/s（32 subpage/s × 1,694 bytes），約為實測頻寬的 1.2%，餘裕充足。經 Wi-Fi 仍為 0 掉包，但 Wi-Fi 品質可能隨時間變動，M7 的 60 秒測試需實測確認。

## 5. M6 結論

依 CLAUDE.md 的 M6 驗收條件全部通過：ping 成功，UDP 吞吐量數據已記錄。此階段未接感測器資料。
