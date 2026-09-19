# M5 溫度換算與顯示

日期：2026-09-20　韌體：`mlx_thermal`（32 Hz，與 M4 相同）

## 1. 溫度換算（方法 A：Melexis 官方 C 程式）

- `host/native/mlx_wrap.c`：包裝層，只露出 `mlxw_extract`、`mlxw_get_ta`、`mlxw_get_vdd`、`mlxw_calculate_to`、`mlxw_bad_pixels_correction`；Melexis 原始碼不修改。I2C 函式在電腦端用不到，以回傳錯誤的空函式滿足連結。
- `scripts/build_host_lib.ps1`：用 MSYS2 MinGW-w64 gcc 15.2（x86_64，與 64-bit Python 相符）編成 `host/native/build/mlx90640.dll`（只依賴 KERNEL32、msvcrt；不進 git，需要時重建）。
- `host/mlxstream/calc_melexis.py`：ctypes 載入 DLL。流程同 Melexis 範例：EEPROM → `ExtractParameters` 一次；每個 subpage → `GetTa`、`CalculateTo`（只更新該 subpage 的像素，保留一份 768 像素陣列）→ 修補 EEPROM 標記的壞點／異常點。
  - 放射率預設 0.95；反射溫度 tr = Ta − 8 °C（Melexis 建議的開放空間值）。
  - chess／interleaved 模式由 subpage 資料中的控制暫存器 bit 12 判斷。

## 2. 自動驗收（溫度合理範圍）

`host/.venv/Scripts/python host/check_temps.py`：每張完整影像（兩個 subpage 都到齊後）檢查無 NaN、影像中位數在 15～40 °C、Ta 在 15～60 °C。

| 資料 | 影像數 | 影像中位數 | 像素最低／最高 | Ta | 換算時間／subpage | 結果 |
|---|---|---|---|---|---|---|
| 錄製檔 `captures/m4_stream_65s.bin` | 2,032 | 28.84～30.25 °C | 24.90／38.33 °C | 31.09～31.76 °C | 0.08 ms | PASS |
| 實機 20 秒（`logs/m5_check_temps_live.txt`） | 623 | 28.37～29.56 °C | 23.75／34.28 °C | 31.89～32.46 °C | 0.21 ms | PASS |

`MLX90640_ExtractParameters` 回傳 0（EEPROM 正常）。

## 3. 顯示程式

`host/.venv/Scripts/python host/viewer.py`（或 `--replay captures/m4_stream_65s.bin` 離線播放，`--port COMx` 指定埠）

- pyqtgraph 0.14 + PySide6 6.11，深色介面。
- 背景執行緒讀取／解析／換算（`host/mlxstream/worker.py`），GUI 不會被 COM port 卡住。
- 左：熱影像＋色條（標出最高溫像素「+」與中心點「○」）、下方最近 30 秒的最高／中心點（2×2 平均）／中位數曲線。
- 右：最高、最低、中心點、游標處溫度；subpage 速率、Ta、序號、CRC 錯誤、跳號／不完整、裝置錯誤／丟包；色彩表、自動／手動溫度範圍、放射率、時間平均（EMA 權重 0.2，約 5 個 subpage，僅影響顯示）、雙線性平滑、左右／上下翻轉。
- `--snapshot file.png --after N`：N 秒後存視窗截圖並結束（搭配 `QT_QPA_PLATFORM=offscreen QT_QPA_FONTDIR=C:/Windows/Fonts` 可不開視窗測試）。

## 4. 最終驗收（使用者目視）

使用者 2026-09-20 目視確認通過：手靠近感測器時，影像與溫度有對應變化。M5 通過，整條資料路徑（I2C → USB → 解析 → 溫度換算 → 顯示）已穩定。
