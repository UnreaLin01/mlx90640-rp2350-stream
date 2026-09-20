# 雙核心分工（網路移到核心 1）

日期：2026-09-20　韌體：`mlx_thermal_udp`

## 1. 為什麼

網路呼叫會阻塞：第一次送封包給某台電腦要等 ARP 回應（M7 實測約 78 ms），初始化要等網路線接上。單核心時這些等待會卡住感測器讀取迴圈，M7 就在連線瞬間漏掉 1～2 個 subpage。

RP2350 有兩顆 Cortex-M33（另有兩顆 RISC-V，但開機時只能選一種架構，本專案用 ARM）。工作只有兩件，剛好一件配一顆核心，不需要 RTOS 排程器。

## 2. 分工與溝通

```
核心 0（main.c）                     核心 1（transport_udp.c 的 net_task）
─────────────────                    ──────────────────────────────────
讀 I2C → 組封包                       net_init（等網路線）→ 開 UDP socket
transport_send() ──放入 tx_queue──>  取出 → sendto()（可能等 ARP，不影響核心 0）
                 <──旗標── peer_known  收 REQUEST → 記住對方位址
```

- **佇列**：`queue_t`（`pico/util/queue.h`），內部用硬體 spin lock 保護，兩顆核心可同時存取。16 格、每格 1054 bytes，約 0.25 秒的資料量。
- **不阻塞**：`transport_send()` 只把封包複製進佇列就返回。佇列滿就整包丟棄並計數（`stream_dropped()`），網路再慢也不會拖慢感測器。
- **狀態旗標**：`peer_known`、`last_request_us` 由核心 1 寫、核心 0 讀，都是單一 word，不會讀到寫一半的值。

## 3. 兩個必須處理的細節

### RTT log 的跨核心保護

SEGGER RTT 的鎖是設定 BASEPRI，只擋得住**同一顆核心**的中斷，兩顆核心同時印會互相覆寫。`log.h` 的 `LOG()` 改為先取得一個硬體 spin lock 再印：

```c
uint32_t state = spin_lock_blocking(log_spin_lock);
SEGGER_RTT_printf(0, __VA_ARGS__);
spin_unlock(log_spin_lock, state);
```

`spin_lock_blocking()` 同時會關閉該核心的中斷，所以同核心的中斷不會在持鎖期間再次進入 `LOG()` 造成死結。

### 啟動前必須先重置核心 1

`multicore_launch_core1()` **不會**重置核心 1，而它的交握在核心 1 已經在執行別的程式時永遠不會完成。用 J-Link 燒錄／重置時，**只有核心 0 被重置**，核心 1 還在跑剛被覆寫掉的舊韌體，於是開機就卡在 `multicore_launch_core1()`。

解法是啟動前呼叫 `multicore_reset_core1()`。這個問題只有在接偵錯器時會遇到（一般上電是兩顆核心一起重置），但整個開發流程都靠 J-Link，所以必須處理。

偵錯過程：用 J-Link halt 核心 0，PC 停在 `__wfe`，LR 指向 `best_effort_wfe_or_timeout`；核心 1 的 PC 卻在舊韌體的 WIZnet QSPI 驅動裡打轉，兩邊對照後確認是核心 1 沒被重置。

## 4. 結果（65 秒，UDP，接偵錯器）

| 項目 | 單核心（M7） | 雙核心 |
|---|---|---|
| 連線瞬間漏讀 subpage | 1～2 個（ARP 等待） | **0** |
| 掉包／CRC 錯誤／序號跳號 | 0 | 0 |
| 延遲抖動 中位數／99%／最大 | 3.68／59.0／129.3 ms | **2.24／6.83／32.9 ms** |
| subpage 讀取時間 | 17.482 ms | 17.51 ms（+0.03 ms，兩核心共用匯流排） |
| 速率 | 31.28 Hz | 31.30 Hz |

延遲尾端大幅改善：核心 1 一有封包就送，不必等核心 0 讀完 subpage。

## 5. 已知限制

- **USB 韌體仍是單核心**：USB 傳輸不會阻塞（寫進 FIFO 就返回），不需要第二顆核心。
- **`mlx_thermal_udp` 沒有 USB**，所以不能用 `scripts/flash_usb.ps1` 燒錄，需要 BOOTSEL 或 J-Link。
