# MLX90640 熱影像串流

這個專案用 W6300-EVB-Pico2 開發板讀取 MLX90640 熱影像感測器，把原始資料即時傳到電腦，由電腦換算成溫度並顯示熱影像。

資料可以走 USB，也可以走乙太網路，兩者使用完全相同的封包格式，切換時電腦端程式不需要任何修改。

感測器每秒產生 31.3 個 subpage，相當於每秒約 15.6 張完整畫面。實測連續執行 300 秒，沒有掉包，也沒有任何 CRC 錯誤。

### 韌體執行架構

![韌體執行架構](docs/architecture_firmware.svg)

### 硬體架構

![硬體架構](docs/architecture_hardware.svg)

---

## 目錄

- [硬體與接線](#硬體與接線)
- [第一次設定](#第一次設定)
- [編譯](#編譯)
- [燒錄](#燒錄)
- [USB 模式](#usb-模式)
- [乙太網路模式](#乙太網路模式)
- [除錯](#除錯)
- [韌體一覽](#韌體一覽)
- [電腦端工具](#電腦端工具)
- [專案結構](#專案結構)

---

## 硬體與接線

| 項目 | 說明 |
|---|---|
| 開發板 | WIZnet W6300-EVB-Pico2，晶片為 RP2350A，雙核心 Cortex-M33 |
| 感測器 | MLX90640，SparkFun 模組，I2C 介面，跑在 1 MHz |
| 乙太網路 | 板載 W6300 晶片，固定佔用 GPIO15 到 GPIO22 |
| 除錯器 | SEGGER J-Link EDU，選用 |
| 邏輯分析儀 | Saleae Logic 8，選用 |

接線方式如下。

| 訊號 | 開發板腳位 | 接到 | Logic 8 通道 |
|---|---|---|---|
| I2C0 SDA | GP4 | MLX90640 SDA | CH0 |
| I2C0 SCL | GP5 | MLX90640 SCL | CH1 |
| 計時標記 A | GP6 | 僅供量測 | CH2 |
| 計時標記 B | GP7 | 僅供量測 | CH3 |
| LED | GP25 | 板載 | 無 |

感測器用 3.3V 供電，並且要和開發板共地。如果要接 J-Link，記得把 VTref 接到 3V3，否則 J-Link 會偵測不到目標板的電壓。

---

## 第一次設定

### 韌體工具鏈

用 VS Code 的 Raspberry Pi Pico 擴充功能安裝下列工具，它們會被裝在 `%USERPROFILE%\.pico-sdk\` 底下。

- Pico SDK 2.3.1
- arm-none-eabi-gcc 15.2.Rel1
- CMake 4.3.4、Ninja 1.13.2、picotool 2.3.1

版本固定寫在 [`scripts/env.ps1`](scripts/env.ps1) 裡面。就算系統 PATH 上有其他版本的工具，建置時也不會用到，所以不用擔心版本混淆。

### 電腦端 Python 環境

```bash
py -3.13 -m venv host/.venv
host/.venv/Scripts/python -m pip install -r host/requirements.txt
```

裝完就可以用了，溫度換算不需要額外編譯任何東西。之後執行電腦端程式時，都請用 `host/.venv/Scripts/python`。

### 乙太網路

只有要用網路模式時才需要準備。把開發板的網路孔接到路由器即可，不必設定 IP。

開發板開機時會先向路由器要一個 IP，要不到才會退回固定位址 192.168.1.200。電腦端會自己找到開發板，所以中間換了 IP 也不影響。

---

## 編譯

在 VS Code 裡直接按右下角的 Compile 就會編譯。

命令列的做法如下。

```bash
powershell -File scripts/build.ps1
```

加上 `-Clean` 參數會先刪掉整個 build 目錄再重建。編譯結果放在 `build/firmware/`，每個韌體都會產生兩種檔案，`.elf` 給 J-Link 用，`.uf2` 給 USB 燒錄用。

---

## 燒錄

### 用 USB 燒錄

這是平常最方便的方式，不需要 J-Link，也不用按 BOOTSEL 按鈕。在 VS Code 裡按右下角的 Run 就會先編譯再燒錄。

命令列的做法如下。

```bash
powershell -File scripts/flash_usb.ps1
powershell -File scripts/flash_usb.ps1 -Firmware pin_test
```

之所以不用按按鈕，是因為 USB 韌體裡內建了 Raspberry Pi 的 reset 介面，picotool 可以自己叫開發板重開進燒錄模式。

有兩種情況還是得按住 BOOTSEL 再插 USB 線。一種是開發板目前跑的是 `mlx_thermal_udp`，那個版本沒有 USB 功能。另一種是開發板上還沒有任何韌體。

### 用 J-Link 燒錄

```bash
powershell -File scripts/flash.ps1
powershell -File scripts/flash.ps1 -Elf build/firmware/net_test.elf
```

VS Code 裡也有對應的工作，按 `Ctrl+Shift+P` 後選 Tasks: Run Task，再選 Flash with J-Link。

---

## USB 模式

先燒錄 `mlx_thermal`，這是預設的韌體，然後把 USB 線接上電腦，執行下面的指令就會出現即時熱影像。

```bash
host/.venv/Scripts/python host/viewer.py
```

程式會依照 VID、PID 和產品名稱自動找到 COM port，不需要指定。

如果想確認串流品質，可以跑統計工具。它會連續接收 60 秒，檢查 CRC 錯誤、序號跳號、幀率和開發板端的錯誤計數，最後印出 PASS 或 FAIL。

```bash
host/.venv/Scripts/python host/stream_stats.py --source usb --duration 60
```

---

## 乙太網路模式

先燒錄 `mlx_thermal_udp`。這個版本沒有 USB 功能，所以要用 BOOTSEL 或 J-Link 燒。接著把網路線接到路由器，USB 線仍然要接著供電。

```bash
host/.venv/Scripts/python host/viewer.py --source udp
```

顯示程式和 USB 模式用的是同一支，只是換了資料來源。

電腦端尋找開發板的方式是這樣的。它會先試上次記住的位址，存在 `host/.board_address` 這個檔案裡。如果沒有回應，才會改用廣播搜尋，找到之後就固定用單播通訊，並把新位址記起來。

之所以這樣設計，是因為 Wi-Fi 的廣播封包不會重傳，比較容易丟失。把廣播限制在搜尋階段，串流本身就完全不受影響。

如果你想直接指定位址，用 `--source udp:192.168.1.50` 這種寫法。

---

## 除錯

### 韌體的 log

韌體所有的 log 都走 SEGGER RTT，透過 SWD 由 J-Link 直接讀取記憶體，因此不佔用任何腳位，也不會影響 I2C 時序。這也是規格的要求，USB 通道專門傳影像資料，不傳 log。

```bash
powershell -File scripts/rtt.ps1
powershell -File scripts/rtt.ps1 -Elf build/firmware/net_test.elf
powershell -File scripts/rtt.ps1 -Stop
```

log 會寫到 `logs/` 資料夾。VS Code 的工作清單裡也有 RTT log 可以用。

這裡有一個容易誤判的地方要提醒。RTT 的緩衝區有 8 KB，logger 接上時會先讀到上一次執行留下的舊內容，所以 log 開頭常常看起來像多開機了一次。分析時要注意這一點。

### 沒有 J-Link 的時候

沒有 J-Link 就看不到韌體的 log，但還是有三個管道可以判斷運作是否正常。

開發板每秒會送一個 STATUS 封包，裡面有讀取錯誤、subpage 順序錯誤、等待逾時、傳輸丟包和最長讀取時間。電腦端的 `stream_stats.py` 會把這些數字連同 CRC 錯誤、序號跳號和幀率一起印出來。最後，GP25 的 LED 每秒閃一次代表主迴圈正常，快速閃爍則代表感測器初始化失敗。

這些資訊足以判斷系統有沒有在正常運作，但看不到開機過程和錯誤訊息的細節。真的要追問題，還是需要 J-Link。

### 用 J-Link 查當機位置

先用 J-Link Commander 停住 CPU 並讀出暫存器。核心 1 要改用 `RP2350_M33_1` 這個裝置名稱。

```bash
"C:\Program Files\SEGGER\JLink\JLink.exe" -NoGui 1 -device RP2350_M33_0 -if SWD -speed 4000 -autoconnect 1
```

連上之後輸入 `halt` 停住，`regs` 讀暫存器，`mem32 <SP> 0x40` 倒出堆疊內容。拿到 PC 或 LR 的位址後，用下面的指令對應回原始碼的行號。

```bash
~/.pico-sdk/toolchain/15_2_Rel1/bin/arm-none-eabi-addr2line.exe -f -e build/firmware/mlx_thermal_udp.elf 0x10000E94
```

還有一點要注意。J-Link 的 reset 只會重置核心 0，所以用到核心 1 的韌體必須先呼叫 `multicore_reset_core1()`，否則核心 1 會繼續執行舊程式，導致開機卡住。這件事已經在 `transport_udp.c` 裡處理好了。

### 時序量測

GP6 和 GP7 是給 Logic 8 用的計時標記，搭配 `host/tools/` 裡的分析腳本，可以量測 I2C 波形、subpage 讀取時間和訊號上升時間。詳細做法和實測數據請看 [docs/m3_timing.md](docs/m3_timing.md)。

---

## 韌體一覽

| 韌體 | 用途 |
|---|---|
| `mlx_thermal` | 主韌體，走 USB 串流，單核心 |
| `mlx_thermal_udp` | 主韌體，走乙太網路串流，網路跑在核心 1 |
| `mlx_thermal_16hz`、`mlx_thermal_64hz` | 同上，不同更新率，用來比較時序 |
| `net_test` | 乙太網路測試，包含 ping 和 UDP 吞吐量 |
| `pin_test` | 檢查 Logic 8 四個通道的接線是否正確 |
| `rise_test` | 量測 I2C 線路的訊號上升時間 |
| `eeprom_test_400k`、`eeprom_test_1000k` | 以指定速率讀取 EEPROM 並驗證內容 |
| `eeprom_soak_1000k` | 1 MHz 下的長時間連續讀取測試 |

---

## 電腦端工具

| 工具 | 用途 |
|---|---|
| `host/viewer.py` | 即時熱影像介面 |
| `host/stream_stats.py` | 串流品質檢查，最後會印出 PASS 或 FAIL |
| `host/check_temps.py` | 檢查換算出來的溫度是否合理 |
| `host/net_test.py` | 搭配 `net_test` 韌體做 UDP 吞吐量測試 |
| `host/tools/` | Logic 8 擷取資料的分析腳本 |

常用參數整理如下。

資料來源用 `--source` 指定，可以是 `usb`、`udp`，也可以寫成 `usb:COM9` 或 `udp:192.168.1.50` 指定得更明確。

溫度換算預設使用 numpy 實作，不需要任何額外設定。如果想改用 Melexis 官方 C 程式來比對，先執行 `scripts/build_host_lib.ps1` 編出 DLL，再加上 `--calc melexis` 參數。兩者的差異小於 0.04 mK，比感測器雜訊小了大約一萬倍，驗證過程記錄在 [docs/method_b_compare.md](docs/method_b_compare.md)。

`viewer.py` 加上 `--replay 檔案` 可以離線播放先前錄下的串流，開發顯示功能時不必接著開發板。要錄製串流則是在 `stream_stats.py` 加上 `--save 檔案`。

---

## 專案結構

```
CMakeLists.txt     頂層建置檔，VS Code 擴充功能的進入點
firmware/          韌體原始碼
  src/             主程式、感測器、I2C、協定、傳輸層、網路
  tests/           各項測試韌體
host/              電腦端 Python
  mlxstream/       協定解析、資料來源、溫度換算
  native/          Melexis C 程式的包裝層，選用
  tools/           Logic 8 資料分析
scripts/           建置、燒錄、RTT 的 PowerShell 腳本
docs/              協定規格、各階段量測紀錄、架構圖
third_party/       SEGGER RTT、Melexis 函式庫、WIZnet 驅動，都保持原樣
build/             建置輸出，不進 git
captures/ logs/    量測資料與 log，不進 git
```

延伸閱讀：

- [docs/protocol.md](docs/protocol.md) 串流協定規格，USB 和乙太網路共用
- [docs/dual_core.md](docs/dual_core.md) 雙核心分工的設計與實測
- [docs/dhcp_discovery.md](docs/dhcp_discovery.md) DHCP 與自動搜尋開發板
- [CLAUDE.md](CLAUDE.md) 專案規格、里程碑與已知問題
