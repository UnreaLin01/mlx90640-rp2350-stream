# 串流協定 v1

USB CDC 與 UDP 共用同一種封包，換傳輸層時封包格式不變。

## 設計重點

- **傳輸層無關**：封包自帶 magic、長度、CRC，不依賴傳輸層的封包邊界。
- **可重新同步**：USB CDC 是位元組串流。接收端逐位元組找 magic，再用長度＋CRC 確認；任一檢查失敗就從 magic 的下一個位元組繼續找。
- **每個封包 ≤ 1052 bytes**：可以整個放進一個 UDP datagram（乙太網路 MTU 1500，UDP payload 上限 1472），不需要 IP 分片。
- **大資料分段**：subpage（1666 bytes）與 EEPROM（1664 bytes）超過單一封包，拆成多個「分段」（part），每段最多 1024 bytes。同一個資料區塊（block）的所有分段有相同的 `seq`。
- **全部 little-endian**。

## 封包格式

| 偏移 | 大小 | 欄位 | 說明 |
|---|---|---|---|
| 0 | 4 | `magic` | ASCII `"MLXT"`（0x4D 0x4C 0x58 0x54） |
| 4 | 1 | `version` | 協定版本，目前 `1` |
| 5 | 1 | `type` | 資料類型（見下表） |
| 6 | 1 | `subpage` | subpage 編號 0／1；非 subpage 類型填 `0xFF` |
| 7 | 1 | `part` | 分段編號，從 0 開始 |
| 8 | 1 | `part_count` | 這個區塊共有幾段（≥ 1） |
| 9 | 1 | `reserved` | 保留，填 0 |
| 10 | 2 | `payload_len` | 本段 payload 長度（bytes），0～1024 |
| 12 | 4 | `seq` | 區塊序號，**每種 type 各自**從 0 遞增；同一區塊的各段相同 |
| 16 | 8 | `timestamp_us` | 開發板開機後的微秒數（subpage：偵測到新資料的時間） |
| 24 | N | `payload` | 本段資料，N = `payload_len` |
| 24+N | 4 | `crc32` | CRC-32（與 zlib.crc32 相同：多項式 0xEDB88320、初值 0xFFFFFFFF、結尾反相），範圍是位元組 0 到 24+N−1 |

- 封包總長 = 28 + `payload_len`。
- 分段在區塊中的位置：`offset = part × 1024`。區塊總長依 type 固定（見下表）。

## 資料類型

| type | 名稱 | 區塊內容 | 區塊長度 | 分段數 | 送出時機 |
|---|---|---|---|---|---|
| 1 | SUBPAGE | 833 個 uint16：`[0..767]` 像素、`[768..831]` aux、`[832]` 控制暫存器 0x800D | 1666 | 2 | 每讀完一個 subpage |
| 2 | EEPROM | 832 個 uint16：EEPROM 0x2400～0x273F | 1664 | 2 | 接收端連上時立即送一次，之後每 2 秒重送 |
| 3 | STATUS | 6 個 uint32（見下表） | 24 | 1 | 每秒一次 |

SUBPAGE 的 833 個 word 就是 Melexis `MLX90640_GetFrameData` 產生的 `frameData[0..832]`，接收端再補上 `frameData[833] = subpage` 即可直接交給 Melexis 的溫度換算函式。只有通過 Melexis 資料檢查的 subpage 才會送出。

STATUS payload：

| 索引 | 欄位 | 說明 |
|---|---|---|
| 0 | `subpages` | 開機後成功讀取的 subpage 總數 |
| 1 | `read_errors` | Melexis 讀取／資料檢查錯誤次數 |
| 2 | `order_errors` | subpage 編號沒有 0/1 交替的次數（代表漏讀） |
| 3 | `wait_errors` | 等待新資料逾時或 I2C 錯誤次數 |
| 4 | `tx_dropped` | 已連線但傳輸緩衝區滿、只好丟掉的封包數 |
| 5 | `read_us_max` | 過去一秒內最長的 subpage 讀取時間（µs） |

## 接收端檢查

- **CRC 錯誤**：magic 與長度合理但 CRC 不符的封包數。
- **序號跳號**：同一 type 的 `seq` 不連續。
- **區塊不完整**：同一 `seq` 缺少分段。
- **subpage 交替**：連續兩個 SUBPAGE 的 `subpage` 應為 0、1 交替。
- **丟棄位元組**：重新同步時略過的位元組數。

## 重新同步規則

1. 在緩衝區中找 `"MLXT"`。
2. 需要至少 24 bytes 才檢查標頭：`version == 1`、`payload_len ≤ 1024`、`part < part_count`，不符合就略過這個 magic，從下一個位元組繼續找。
3. 湊滿 28 + `payload_len` bytes 後檢查 CRC，不符合同樣略過這個 magic。
4. 通過後輸出封包，從封包結尾繼續。
