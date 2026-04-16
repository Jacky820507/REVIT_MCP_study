# Revit MCP 學習經驗錄 (GEMINI.md)

## 🔬 智慧提煉

### 2026-03-20: WebSocket 多重連線並行修復與效能優化

#### 問題背景
在執行樓梯隱藏線腳本時，發現 `get_active_view` 指令反應極慢（固定等待 30 秒），導致自動化流程卡住。原本以為是 Revit API 運算速度問題，但經測試發現內部執行僅需 0.1 秒。

#### 根本原因
- **Socket 獨佔問題**：C# 端的 `SocketService.cs` 原始設計僅能保存「最後一個連線」的 WebSocket 物件 (`private WebSocket _webSocket;`)。
- **路由失效**：當同時開啟多個 AI 用戶端（如 VS Code Copilot 與 Terminal 腳本）時，最新的連線會搶走唯一的回應通道。舊的連線送出請求後，Revit 會誤將結果傳回給「最新的那個 Socket」，導致原請求端進入 30 秒等待超時。

#### 解決方案
- **引入 ConcurrentDictionary**：在 `SocketService` 中改用 `ConcurrentDictionary<WebSocket, byte>` 管理所有活動中的連線。
- **精準路由**：建立 `CommandReceivedEventArgs` 包含 `SourceSocket`，讓指令在跨執行緒 (ExternalEvent) 執行完畢後，能依照請求來源精準回傳結果。
- **異步關閉**：優化服務停止時的 Socket 關閉邏輯，確保每個連線都獲得正確釋放。

#### 學習心得
- **分散式診斷**：當指令「變慢」時，應先區分是運算慢還是通訊慢（超時）。
- **多用戶端考量**：開發 WebSocket Server 時必須考慮多重連線並行，避免全域變數鎖死單一通道。

---

### 2026-03-20: 組合式樓梯剖面隱藏線繪製經驗

#### 技術要點
- **Assembled Stairs 識別**：需偵測 `stringer` (側板) 存在的樓梯。
- **幾幾何過濾**：
  - 排除距離剖切面太近 (0.05ft) 的前景。
  - 僅繪製第一排踏階 (2.5ft 容差)，避免背景樓梯線條堆疊造成視覺混亂。
- **線條樣式**：使用 `虛線(極密)` (ID: 11911982) 能提供最佳的細部圖解效果。
---

### 2026-03-20: 大量圖紙批次建立 (CSV to Sheets) 經驗

#### 技術要點
- **編碼處理**：台灣專案 CSV 常見為 `Big5` (950)，在 Node.js 中需先轉為 `UTF-8` 或使用 `iconv-lite` 讀取，避免中文字元落入 Revit 時變亂碼。
- **批次傳輸策略**：
  - 即使 MCP 工具沒限制，建議以 50-100 張為一批次 (Batch) 執行。
  - 優點：降低 WebSocket 單次傳輸過大 (64KB 限制) 的風險，且在發生錯誤時較容易定位受影響的圖紙範圍。
- **腳本化控制**：直接使用 Node.js `spawn` MCP Server 並透過 `stdin/stdout` 發送 JSON-RPC 指令，比手動在 AI 對話中分批更穩定且快速。

#### 執行成效
- 成功一次性匯入 370 張圖紙，耗時約 30 秒，成功率 100%。

#### 學習心得
- **自動化工具鏈**：當對話窗口的資料截斷 (Truncation) 影響操作時，應果斷改用本地腳本 (Node.js/Python) 驅動 MCP 工具。

---

### 2026-03-20: 詳圖項目批次同步 (v4.0 順序執行與模糊比對) 經驗

#### 技術要點
- **順序執行策略 (Sequential Async)**：當批次執行大量寫入指令（如 74 條重新命名與參數修改）時，使用 `async/await` 等待每個回應，而非發送後即關閉。這能確保 Revit 處理隊列的穩定性，避免指令在傳輸過程中遺失。
- **加強型名稱比對 (Fuzzy Matching)**：
  - **正規化處理**：移除括號 `（）()`, 空格, 及關鍵字 `詳圖`。
  - **全形轉半形**：確保數字與英文字母在比對前統一格式。
  - **包含比對**：不僅比對完全相等，也支援 `contains` 比對，增加容錯率。
- **圖紙號碼格式不一處理**：圖紙編號存在 `ARB-D09001` 與 `AR-B-D0901` 多種格式時，優先使用「名稱比對」回填正式圖號。

#### 執行成效
- 成功將 37 個 `TEST-D09xxx` 類型轉變為 `ARB-D09xxx` 格式，成功率達 97%。

#### 學習心得
- **日誌即診斷**：透過記錄 `Normalized Name` 狀態，快速發現括號差異。
- **數據完整性勝過速度**：對於 BIM 數據，穩定的順序更新優於盲目的批次發送。

---

### 2026-03-24: 停車格自動編號 (座標提取與 SpecTypeId 修復) 經驗

#### 技術要點
- **自定義 GetElementLocation**：Revit MCP 預設的 `query_elements` 與 `get_element_info` 主要回傳參數字串，缺乏幾何座標。本次在 `CommandExecutor.cs` 中新增 `get_element_location` 指令，能直接提取 `LocationPoint` 或 `BoundingBox.Center`，解決排序所需的座標來源問題。
- **Revit API SpecTypeId 修正**：在舊版 Compatibility code 中發現 `SpecTypeId.Int` 會導致編譯錯誤（為巢狀類別而非常數），正確用法應為 `SpecTypeId.Int.Integer` (Revit 2022+)。
- **模糊分類策略**：由於 `query_elements` 回傳的 JSON 結構簡化，需將元素 `Name`（類型名稱）納入分類關鍵字比對範圍，而非僅依賴獨立的 `TypeName` 欄位。
- **Y 軸容差分群排序**：使用 `Math.abs(y1 - y2) > tolerance` 進行分群，能有效處理大面積停車場「同排」車位的邏輯判定。

#### 執行成效
- 成功在「物流中心」專案中，一次性為 1011 個（汽車、機車、大客車）停車格完成分類與排序座標提取，模擬測試 (dry-run) 指標 100% 正確。

#### 學習心得
- **核心工具擴充**：當現有工具無法滿足幾何運算需求時，直接修改 C# 端新增基礎 API (如 Location 提取) 比在 JS 端進行複雜的參數解析更穩定。
- **編譯鎖定處理**：部署新版 DLL 前務必確認 Revit 已完全關閉，避免檔案鎖定導致更新失敗。

---

### 2026-03-25: 製圖填滿圖案轉模型圖案 (Drafting to Model Pattern) 經驗

#### 技術要點
- **動態物理縮放精準度**：製圖樣式 (Drafting) 在 Revit 中是以「圖紙毫米」定義間距，而模型樣式 (Model) 是以「真實物理尺寸 (ft/mm)」定義。轉換時必須精準乘上 `ActiveView.Scale`，才能確保視覺效果不變。
- **FillGrid 深度處理**：單純修改 `FillPattern.Target` 無效，必須提取 `GetFillGrids()` 集合，並對每個 Grid 的 `Offset`, `Shift` 以及 `GetSegments()` 回傳的線段數值進行比例縮放後，重新建立 `FillPatternElement`。
- **Revit 命名禁忌**：Revit 元素名稱絕對禁止包含冒號 `:`。在自動化命名（如標註比例 `1:50`）時，務必替換為 `_` 或 `-`，否則會觸發 `InternalException`。

#### 執行成效
- 成功解決圖紙旋轉時，填滿區域（Filled Region）紋理不跟著旋轉的問題。
- **進階版 (2026-03-25)**：實作全自動視埠掃描，並增加 **群組保護機制**。成功一次性處理了 17 個旋轉視圖（包含 `ARB-D04011` 等採用 `VIEWPORT_ATTR_ORIENTATION_ON_SHEET` 隱藏旋轉的視窗），替換了 209 個物件，並安全略過 27 個群組內物件，確保不破壞使用者群組結構。
- 新增 `check_viewports_rotation` 診斷工具，可全面排查被 Revit 內部參數隱藏的旋轉屬性。
- 測試於 Revit 2020 環境，成功將選取的圖面標註轉換並維持視覺尺寸 100% 一致。


#### 學習心得
- **視覺一致性守則**：自動化轉換工具的首要任務是「不改變現有視覺結果」。透過 API 直接讀取視圖比例並回算物理尺寸，是達成此目標的關鍵路徑。
- **屬性隱藏陷阱**：Revit 中 `Viewport.Rotation` 列舉有時會失效（回報 None），必須額外檢查 `BuiltInParameter.VIEWPORT_ATTR_ORIENTATION_ON_SHEET` 才能確保偵測 100% 準確。
- **群組完整性高於自動化**：在大型專案中，不應為了方便而強制解除群組。實作 `GroupId` 檢查並給予使用者選擇權（或略過處理）是更專業的 BIM 自動化做法。
- **異常防禦**：針對命名規範（禁止冒號）進行防禦性程式設計，能大幅減少部署後的除錯時間。

---

---

### 2026-03-26: 房間自動編號 (幾何排序與 Regex 前綴) 經驗

#### 技術要點
- **多元樓層前綴映射**：使用 `LevelName.match()` 進行 Regex 解析，實現了跨類型樓層的統一編碼：
  - 地下層：`B1F` -> `B101` (`B` + `\d+` + `seqNum`)
  - 地上層：`1F` -> `F101` (`F` + `\d+` + `seqNum`)
  - 屋突層：`R1F` -> `R101` (`R` + `\d+` + `seqNum`)
- **Y-X 機械排序穩定性**：設定 `TOLERANCE = 3000mm` 作為房間分群標準。相較於停車格 (1500mm)，房間中心點的 Y 軸波動較大，需更大的容差以確保「同一橫排」的判定符合人類閱讀習慣。
- **參數名動態適配**：Revit 預設參數名在不同語系下可能為 `Number` 或 `編號`。腳本實作了 `get_category_fields` 預檢機制，自動偵測並選用正確的參數 Internal Name 進行寫入。
- **Batch 模式通訊優化**：在全專案查詢 (`--all`) 時，發現 `returnFields` 回傳的資料會展開在物件根層級而非 `parameters` 子物件中。腳本已實作相容性判斷，確保跨模式執行的穩定性。

#### 執行成效
- 成功為 B1F 至 R1F 建立了一套一致且可預測的編號腳本，並一次性處理了全專案 239 個房間。

#### 學習心得
- **範例驅動開發**：在開發前要求使用者提供明確的「輸入(LevelName) -> 輸出(Number)」範例，能大幅減少 Regex 除錯的時間。
- **分群容差調優**：不同類型的 BIM 物件（停車格 vs 房間）對空間排序的容差容忍度不同，應將其參數化開放給使用者調整。
---

### 2026-04-08: RC 智慧填滿區域 (Smart Fill) 與 WebSocket 通訊優化經驗

#### 技術要點
- **幾何指紋比對 (Fingerprinting)**：
  - 為了實現「僅在模型變動時更新」的智慧更新功能，計算了剖切面 `CurveLoop` 的指紋：`{重心X, 重心Y, 總面積 (Shoelace 法)}`。
  - 將精度設定為 0.3mm (0.001 ft)，在執行時與現有帶有 `RC_AUTO` 標記的 FilledRegion 比對，成功達成「無變動即 Skip」的效能。
- **標記保護機制 (Tagging)**：藉由在 `Comments` 參數寫入 `RC_AUTO` 字串，區分「自動產出」與「手動繪製」內容，確保自動化流程不會誤刪使用者的手動標註。
- **後端解析策略 (Server-side Parsing)**：
  - 為了處理大規模圖紙批量任務，將「圖紙 -> 視埠 -> 視圖 ID」的解析邏輯移至 C# 端。
  - **優點**：避免 JS 端透過 WebSocket 傳送龐大的 Viewport 物件集合，降低延遲並解決傳輸封包過大的問題。

#### 執行成效
- 成功為兩張圖紙的 4 個剖面視圖產出 162 個 RC 貼紙。
- 第二次重複執行時，系統能在 2 秒內偵測到無幾何變更並自動跳過。

#### 學習心得
- **型別匹配陷阱 (WebSocket ID Mismatch)**：
  - **現象**：腳本發送指令後 Revit 已執行完畢，但 JS 端 Promise 永遠不 resolve (Timeout)。
  - **根因**：JS `Date.now()` 產生的是 `number`，而 C# 端 `RevitCommandRequest.RequestId` 宣告為 `string`。雖然 JSON 傳輸沒問題，但回傳比對時 `(response.id === request.id)` 因 `3 !== "3"` 而失敗。
  - **解決方案**：JS 端發送前強制轉型為 `String(Date.now())`。
- **指紋偵測的邊界**：對於極其複雜的幾何（如非常小的碎邊），指紋比對能大幅降低 CPU 負擔與 Transaction 同步時間。

---

### 2026-04-13: 叢屬視圖銜接線 (Matchlines) 自動化與 2020 舊版相容性經驗

#### 技術要點
- **裁切幾何拓撲 (Matchline Logic)**：
  - 核心邏輯在於計算兩組 `CropBox` 的重疊區域中心。
  - 對於水平交界與垂直交界，需動態旋轉文字標註。
- **Revit 2020 屬性缺失陷阱**：
  - **現象**：寫入 `Comments` 標記 (`MATCHLINE_AUTO`) 後，第二次執行卻無法偵測到舊物件，導致標註重疊。
  - **根因**：Revit 2020 的 `TextNote` 與 `DetailCurve` (細部線) 預設不具備 `Comments` (註解) 參數。
  - **解決方案**：
    - 文字：改用 `Text` 內容模糊比對關鍵字（如「銜接線」）。
    - 線條：改用 `GraphicsStyle.Name` (線型名稱) 進行批量篩選清理。
- **文字視覺對齊 (Visual Centering)**：
  - 設定 `TextNoteOptions.VerticalAlignment = VerticalTextAlignment.Middle` 與 `HorizontalAlignment.Center`。
  - 偏移量調整為 `1.2 ft` (約 36cm)，比預設的 1.5ft 更貼合線條且不顯擁擠。

#### 執行成效
- 成功在 Revit 2020 環境下實作了具備「自我清理」功能的銜接線工具。
- 一次性清理了 8 組因舊版標記失效而殘留的孤兒文字，並重建乾淨的圖面。

#### 學習心得
- **API 版本差異預檢**：在開發跨版本工具時，不能假設 `ALL_MODEL_INSTANCE_COMMENTS` 永遠存在。針對標註類物件，應優先建立基於「內容」或「樣式名」的備用清理邏輯。
- **部署路徑正確性**：若發現修改程式碼後 Revit 表現無變化，優先檢查 `.addin` 指向的 DLL 路徑是否被舊版檔案佔據，或是否漏掉了版本子資料夾 (`\2020\RevitMCP\`)。

---

### 2026-04-13: Socket 衝突與 HTTP.sys PID 4 孤兒連線處理經驗

#### 問題背景
在執行 B1F 銜接線佈署時，MCP Server 啟動後持續顯示 `Waiting for Revit Plugin...`。手動連線測試顯示 `CONNECTED`，但標準工具指令卻無法與 Revit 通訊。

#### 根本原因
- **HTTP.sys 核心佔用 (PID 4)**：C# 端使用 `HttpListener`。當 Revit 異常關閉或未正確呼叫 `Stop()` 時，Windows 核心驅動程序 `HTTP.sys` 會代為持有該埠（Port 8964）的監聽權，並在 `netstat` 中顯示由 PID 4 (System) 佔用。
- **Node.js 綁定失敗**：Node.js 若嘗試啟動一個新的 HTTP Server 在同一個 Port，會因 `EADDRINUSE` 錯誤（或在 Windows 上靜默掛起）而無法正確接收來自插件的請求。

#### 解決方案
- **清理 URL ACL**：使用管理員權限執行 `netsh http delete urlacl url=http://localhost:8964/` 以清除孤兒綁定。
- **重啟連線三部曲**： 
  1. 結束所有 Node 殭屍進程。
  2. 重啟 Revit MCP 服務。
  3. 使用具備「連線偵測」功能的專屬腳本（如 `research_d02_sheets.cjs`）進行即時驗證。

#### 學習心得
- **PID 4 並非真正佔用**：在 Windows 上看到 PID 4 佔用 Port 通常代表這是「核心級標記」，必須透過 `netsh` 或重啟 `http` 服務處理。
- **工具鏈隔離**：自動化指令若掛起，應優先使用「最小 WebSocket Ping」腳本測試通訊層，排除業務邏輯干擾。
- **母視圖 ID 驗證**：在大型專案中，母視圖 ID 可能隨模型更新變動。執行腳本前實施「自動化視圖映射查詢」比人工指定 ID 更穩健。

---
