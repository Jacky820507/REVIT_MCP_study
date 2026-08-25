---
name: rc-filled-region
description: "RC 智慧填滿區域：在剖面或詳圖視圖中自動產生 RC 結構（牆、柱、版、樑）剖切面的深灰色填滿貼紙，具備幾何指紋比對與批次圖紙處理。觸發條件：使用者提到 RC 貼紙、RC 填滿、結構塗黑、塗灰、filled region、智慧更新、剖面 RC、批次貼紙。工具：create_rc_filled_region、batch_create_rc_filled_region。"
metadata:
  references:
    - domain/rc-filled-region-workflow.md
---

# RC 智慧填滿區域（RC Smart Fill）

執行前讀取 `domain/rc-filled-region-workflow.md`。domain 與本檔衝突時以 domain 為準。

## 使用場景

- 剖面圖與大樣詳圖需要把 RC 結構部分塗黑／塗灰
- 模型頻繁修正，需要快速同步所有圖紙上的 RC 填滿範圍
- 批量圖紙（如全區剖面圖）一次產生所有填滿區域

## 可用工具

| 工具 | 用途 |
|------|------|
| `create_rc_filled_region` | 單一視圖產生 RC 填滿區域 |
| `batch_create_rc_filled_region` | 批次處理，支援依圖紙編號智慧更新 |

`batch_create_rc_filled_region` 參數：

- `sheetNumbers`（可選）：圖紙編號清單，例如 `["ARA-D04002", "ARA-D04003"]`
- `viewIds`（可選）：直接指定視圖 ID 清單
- `filledRegionTypeName`：填滿樣式名稱（預設 `深灰色`）

## 核心技術要點

1. **幾何指紋偵測**：以剖切面 CurveLoop 的「重心座標 + 總面積」作為指紋，精度 0.3 mm（0.001 units）。模型沒動就不重繪，只有幾何變了才更新。
2. **智慧標記保護**：自動產生的物件在 `Comments` 標記為 `RC_AUTO`。工具只清理與更新帶此標記者，**使用者手繪的填滿區域不會被誤刪**。
3. **精確幾何提取**：比對面法線與視圖方向，只在剖切面上產生貼紙；距離容差 0.1 ft，過濾非切割面的背景物件。
4. **效能**：圖紙／視埠解析在 C# 端完成，避免把巨量視圖資料經 WebSocket 傳回來。

## 注意

批次執行前先在單一視圖確認填滿樣式名稱確實存在；`filledRegionTypeName` 找不到時整批會失敗而不是部分成功。
