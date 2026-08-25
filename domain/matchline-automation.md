---
name: matchline-automation
description: "銜接線自動化標註 SOP：在母視圖與從屬視圖出圖流程中，自動偵測相鄰 CropBox 邊界並建立銜接線、相鄰圖紙號碼文字與清理舊標註。"
metadata:
  version: "1.1"
  updated: "2026-07-28"
  created: "2026-04-13"
  contributors:
    - "Jacky820507"
  references:
    - "MCP/Core/Commands/CommandExecutor.Views.cs"
    - "pyRevit_Tools/MCP_Tools.extension/lib/matchline_logic.py"
    - "pyRevit_Tools/MCP_Tools.extension/lib/matchline_button.py"
  related: ["dependent-view-crop-workflow.md", "sheet-viewport-management.md"]
  referenced_by: []
  tags: [Revit, Matchline, DependentView, Sheet, CropBox, 銜接線]
---

# 切圖界線自動化標註工作流程 (Matchline Automation Workflow)

## 1. 背景與需求
在大型開發案中，單張圖紙無法容納比例尺 1/100 或 1/50 的完整平面圖，因此需將母視圖切割為多張「從屬視圖 (Dependent Views)」。
為了讓圖紙閱讀者知道各區銜接關係，標準規格要求：
- 在母視圖標示**銜接位置**。
- 顯示**相鄰圖紙號碼**（例如：接 ARA-D01015）。

## 2. 自動化邏輯
系統會遍歷目前視圖下的所有從屬視圖，並執行以下步驟：
1. **視圖配對**：先將每個從屬視圖的 `CropBox` 透過自身 `BoundingBoxXYZ.Transform` 轉到母視圖共同座標系，再逐一檢查四條邊界。每一側會依候選端點切成區段，只有相對兩側互相選中最近鄰的區段才成立；因此可排除對角重疊與跨過中間視圖的配對，同時保留 T 形及一對多邊界。
2. **邊界計算**：
   - 以兩個相對 CropBox 邊界的中間位置作為銜接線，並以共同覆蓋範圍決定線段長度。
   - 左右相鄰建立垂直線；上下相鄰建立水平線。
3. **標註生成**：
   - 讀取相鄰視圖被放置在的 `Sheet Number`。
   - 每一條有效交界固定建立 `DetailLine`，並在線段中點兩側各建立一個對應視圖的 `TextNote`，不省略任何相鄰視圖名稱。
   - 文字錨點固定使用最終線段的幾何中點，不因網格或另一條銜接線而省略或沿線移動。
4. **清理機制**：
   - 統一標記或識別關鍵字。
   - 先完成 CropBox 候選計算；若候選為 0，保留全部既有標註並停止。
   - 有有效候選時，才刪除視圖中具備特定屬性或名稱的舊標註並重畫。

## 3. 技術規格 (Revit 2020)
- **銜接線樣式**：`粗虛線` (GraphicsStyle)。
- **文字樣式**：`微軟正黑體 3.5 mm` (TextNoteType)。
- **對齊邏輯**：
  - 文字水平對齊：`Center`
  - 文字垂直對齊：`Middle`
  - 偏移距離：`1.2 ft` (約 36.5 cm)。
- **清理邏輯**：
  - 文字：比對內容包含 `銜接線` 字串。
  - 線條：比對線型名稱包含 `粗虛線`。

## 4. 注意事項
- **母視圖執行**：此腳本必須在「母視圖」中執行，且從屬視圖必須已經被放置在圖紙 (Sheet) 上才能顯示正確的圖號。
- **預覽效果**：每條真正的相鄰邊界都有兩側文字，且固定在線段幾何中點；不會因網格或交會而省略名稱。

## 5. 實戰案例：B1F 地下一層平面圖 (2026-04-13)

### 專案背景
針對「物流中心」專案的 B1F 區域進行銜接線佈署。該區域由母視圖切割為 13 個從屬區塊。

### 執行要點
1.  **動態 ID 識別**：
    - 由於母視圖 ID `11428320` 可能隨模型同步變動，佈署前使用 `detect_sheet_matchlines` 進行預檢，從圖紙佈置中反推母視圖與從屬視圖的對應關係。
2.  **大規模佈署**：
    - 一次性對 13 張圖紙 (`ARB-D02002`–`ARB-D02014`) 執行佈署。
    - 成功建立 **24 條銜接線** 與其配對文字。
3.  **驗證結果**：
    - 通過自動化掃描 confirm 每張圖紙具備一致的標註數量（約 72 個相關元素）。
    - 對於非分割圖例的圖紙 (`ARB-D02010`) 自動略過，確保資料準確性。

### 經驗總結
在大型分割圖佈署中，「先查詢 ID 再佈署」的穩健性遠高於「手動指定 ID」。透過自動化工作流程，將數小時的手動對位作業壓縮至 20 秒內完成，且達成 100% 的去重精度。

## 6. 執行入口與已知缺口（2026-07-28 盤點）

| 層 | 狀態 |
|---|---|
| C# 命令 | `create_dependent_view_matchlines`（建立）、`detect_sheet_matchlines`（掃描既有標註）——皆已在 `CommandExecutor` dispatcher 註冊 |
| MCP 工具層 | ✅ 已於 2026-07-28 補上（`MCP-Server/src/tools/dependent-view-tools.ts`），AI 對話可直接呼叫。在此之前長期未註冊，`MCP-Server/create_matchlines.js` 這類以 `tools/call` 直打命令名的舊腳本因此失效 |
| pyRevit 按鈕 | 「銜接線標註」（`Visual.panel/Matchlines.pushbutton`），走 DLL 橋接直呼 CommandExecutor |

### 按鈕的預檢責任

C# 命令**沒有 dryRun 參數**；它會先計算候選，候選為 0 時不刪除任何既有標註，
有候選時才進入「清除後重畫」。因此確認對話框仍是有候選時的主要安全閘門。
按鈕在呼叫前必須自行用 Revit API 完成下列預檢，命令本身不會做：

1. **擋下從屬視圖**：`GetPrimaryViewId()` 有效即代表目前在從屬視圖，
   必須提示切回母視圖，不可讓命令在錯誤的視圖執行。
2. **列出從屬視圖與其圖號**，並標示尚未放上圖紙者——
   那些視圖的標註會退回使用視圖名稱而非圖號（見第 4 節）。
3. **回報將被刪除的既有標註數量**（線依線型名稱、文字依含 `銜接線`），
   與 C# 的清理條件用同一組判準。
4. **線型與文字型式由使用者選擇**，預設值以「名稱包含」比對
   `粗虛線` / `微軟正黑體 3.5 mm`，與 C# 的 `Name.Contains(...)` 一致；
   不得寫死專案專屬名稱（見 `user-specified-runtime-parameters.md`）。

### timeout 注意事項

`create_dependent_view_matchlines` 的視圖配對是 O(n²)，本案 13 個從屬視圖約 20 秒，
已逼近 MCP server 預設的 30 秒 timeout。因此該命令在 `revit-tools.ts` 被列入
長時命令清單（120 秒）。從屬視圖數量再增加時，先確認 timeout 而不是先懷疑演算法。
