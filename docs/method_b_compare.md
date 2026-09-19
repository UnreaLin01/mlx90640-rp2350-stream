# 支線：溫度換算方法 A 與 B 的比較

日期：2026-09-20　分支：`exp/method-b`

- **A**：Melexis 官方 C 程式編成 DLL，Python 以 ctypes 呼叫（`host/mlxstream/calc_melexis.py`，M5 使用中）。
- **B**：以 Python／numpy 重寫 Melexis 的 `ExtractParameters`、`GetVdd`、`GetTa`、`CalculateTo`、`BadPixelsCorrection`（`host/mlxstream/calc_python.py`，約 400 行）。

比較工具：`host/.venv/Scripts/python host/tools/compare_calc.py captures/m4_stream_65s.bin --variants`
輸出：`logs/methodb_compare.txt`

## 1. 移植方式

- **參數解析**：逐步照抄 C 的計算，包括 C 先存成 32-bit float 再四捨五入成整數（alpha、kta、kv）的地方，也照樣模擬。
  - 過程中發現 numpy 2 的型別規則（NEP 50：Python float 與 float32 運算結果仍是 float32）會讓三處本應以 double 計算的地方變成 float32（`SCALEALPHA / alphaTemp`、alpha 的 `+0.5`、kta/kv 的 `±0.5`），已明確改成 double，否則參數可能在少數像素差 1 個單位。
- **每個 subpage 的計算**：以 numpy 一次算完該 subpage 的所有像素，使用 64-bit float（C 版是 32-bit float）。
- 保留 C 的細節：`CalculateTo` 內的 `mode` 是 0 或 **128**（bit 12 右移 5 位），與 `calibrationModeEE` 用同樣的尺度比較。

## 2. 結果（錄製檔 65 秒，2,032 張影像）

| 項目 | 結果 |
|---|---|
| 校正參數（27 個欄位，直接讀 A 的 C struct 比對） | **完全相同（bit 對 bit）** |
| 每像素溫度差 \|A−B\| | 最大 0.039 mK，平均 0.011 mK（156 萬個像素值） |
| Ta 差 | 最大 0.013 mK |
| 每個 subpage 換算時間 | A 0.07 ms，B 0.09 ms |
| 參數解析時間（B） | 約 4 ms（只在收到 EEPROM 時做一次） |

溫度差來自 C 用 float32、B 用 float64 的捨入誤差，比感測器雜訊（32 Hz 約 0.5 K）小約一萬倍，實務上兩者完全一樣。

## 3. 真實感測器沒用到的程式路徑

這顆感測器沒有壞點，而且工作模式（chess）與校正模式相同，因此壞點修補、interleaved 圖樣、「模式≠校正模式」的修正項在真實資料中都不會執行。以人為修改的輸入測試（各 400 個 subpage）：

| 變化 | 做法 | 驗證有生效 | 參數 | 最大 \|A−B\| |
|---|---|---|---|---|
| 注入壞點（chess 模式） | EEPROM 像素 0、334 設為 0（broken）；62、737 設最低位（outlier）；涵蓋角落、首末列、第 1／2／31 欄、內部 | 恰好這 4 個像素被修補改值，A、B 修補結果相同 | 相同 | 0.039 mK |
| interleaved 模式 | 控制暫存器 bit 12 清為 0 | 768 個像素全部改變（平均 0.44 °C） | 相同 | 0.039 mK |
| 兩者同時 | — | — | 相同 | 0.039 mK |

## 4. 使用方式

`viewer.py` 與 `check_temps.py` 加上 `--calc python` 即使用 B（預設 `melexis` = A）。兩種方法在錄製檔上的自動溫度檢查都通過。

## 5. 結論

| | A（C DLL） | B（numpy） |
|---|---|---|
| 準確度 | 官方基準 | 與 A 差 < 0.04 mK，參數完全一致 |
| 速度 | 0.07 ms／subpage | 0.09 ms／subpage（都遠低於 32 ms 的週期） |
| 需要編譯器 | 需要（MSYS2 gcc） | 不需要 |
| 跨平台 | 需重編 | 直接可用 |
| 看中間值／修改演算法 | 不方便 | 方便（Ta、Vdd、每像素參數都是 numpy 陣列） |

兩者在這個專案中可互換。之後若要研究或修改演算法（例如第二步的呼吸率量測），B 較方便；A 保留作為官方基準，可隨時用 `compare_calc.py` 驗證 B。
