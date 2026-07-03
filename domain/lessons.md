---
name: lessons
description: "Lessons Learned：由 /lessons 指令自動維護的專案避坑經驗集。記錄高階開發規則與實作教訓，採 Append-only 追加、禁止修改或刪除已有條目。當使用者提到 lessons、開發經驗、避坑、經驗、教訓時觸發。"
metadata:
  version: "1.2"
  updated: "2026-05-26"
  created: "2026-03-13"
  contributors:
    - "Admin"
    - "shuotao"
    - "Jacky820507"
    - "Antigravity"
  references: []  # TODO: 月小聚補法規條號或外部依據
  related: []  # TODO: 月小聚補相關 domain（檔名）
  referenced_by:
    - auto-dimension
    - element-coloring
    - element-query
    - fire-safety-check
    - parking-check
    - wall-orientation-check
  tags: [lessons, 開發經驗, 避坑, 經驗, 教訓, append-only]
---

# Lessons Learned

> 此檔案由 `/lessons` 指令自動維護，記錄專案特定的高階開發規則與避坑經驗。
> 規則以 Append 方式追加，嚴禁修改或刪除已有條目。

---

## [L-001] 走廊識別策略

- **規則**：Revit 中的區域功能查詢應具備語言容錯性。
- **實踐**：篩選房間應包含 `走廊`, `Corridor`, `廊道`, `通道`, `廊下`（日文）。

## [L-002] 自動尺寸標註定位原則

- **規則**：建立 `Dimension` 必須依附於宿主元素的中心幾何，且必須匹配正確的「視圖 ID」。
- **座標轉換**：
  - 取得元素的 `BoundingBox`。
  - 標註位置線應定義在 `(max + min) / 2` 的中心軌跡上，以確保標註文字不與邊界牆重疊。
  - **警告**：嚴禁在 3D 視圖中直接建立平面標註，必須先查詢 `ActiveView`。

## [L-003] Revit 增益集部署與 AddInId 衝突排除

- **問題現象**：Revit 啟動時發生「無法初始化增益集，因為應用程式已存在此 AddInId 節點」錯誤。
- **原因分析**：
  - 歷史遺留問題：專案曾使用手動命名的 `.addin` 檔（如 `RevitMCP.2024.addin`），後改用 SDK 自動生成的 `RevitMCP.addin`。
  - 兩者指向不同的 DLL 路徑但使用相同的 GUID，導致 Revit 衝突。
- **避坑規則**：
  - 全版本統一使用 `RevitMCP.addin` 作為入口名稱。
  - 執行部署腳本或 `dotnet build` 前，應確保環境中無重複的 `.addin`。
  - **專案結構**：DLL 必須統一放置於 `Addins\{version}\RevitMCP\` 子資料夾內，避免與根目錄的舊版檔混淆。
  - **版本相容**：Revit 2022-2023 的 `Category` 缺乏 `.BuiltInCategory` 屬性，必須使用 `GetBuiltInCategoryCompat()` 擴充方法。
  - **DeployAddin 必須關閉**：Nice3point SDK 的 `<DeployAddin>true</DeployAddin>` 會在 build 時自動產生 `RevitMCP.{version}.addin`，與手動的 `RevitMCP.addin` 衝突。csproj 中必須設為 `false`。
  - **setup.ps1 自動清理**：部署步驟內建 `Get-ChildItem -Filter "RevitMCP.*.addin"` 清理邏輯，防止殘黨累積。

## [L-004] setup.ps1 PowerShell 5.1 相容性

- **問題現象**：`setup.ps1` 在 Windows PowerShell 5.1 下多處報錯。
- **根因與修復**：
  - `Join-Path` 只接受 2 個參數（PS 5.1），三段以上路徑需巢狀呼叫 `Join-Path (Join-Path a b) c`。
  - `-split` 單一值回傳字串非陣列，`Set-StrictMode` 下無 `.Count`，需用 `@()` 包裹。
  - 空 `PSCustomObject` 的 `.PSObject.Properties.Name` 在 StrictMode 下報錯，改用 `.PSObject.Properties.Match('key').Count`。
- **避坑規則**：所有 PowerShell 腳本必須在 5.1 下測試，不可假設 7.x 語法可用。

## [L-005] 走廊寬度標註需使用邊界線段而非 BoundingBox

- **問題現象**：用 `create_dimension` 的 BoundingBox 座標標註走廊寬度，得到的是外接矩形尺寸（7.29m），非實際淨寬。
- **根因**：L 型或不規則走廊的 BoundingBox 包含大量空白區域。
- **解法**：新增 `create_corridor_dimension` 命令，使用 Room BoundarySegments 的 Segment-First 演算法找平行牆對，在精確的牆面位置建立標註。
- **實測驗證**：L5 走廊 9 個區段，寬度 516mm–3045mm，兩處不合格（< 1200mm）。

## [L-006] WebSocket 埠衝突 (PID 4) 與 HTTP.sys 殘留處理

- **現象**：MCP Server 啟動後掛死在 `Waiting for Revit Plugin...`，但 `netstat` 顯示 Port 8964 已由 PID 4 (System) 監聽。
- **根因**：Windows 的 `HTTP.sys` 核心驅動程序代為持有 Revit `HttpListener` 崩潰後遺留的監聽權限。
- **專案避坑規則**：
  - 遇到通訊掛起時，優先嘗試 `netsh http delete urlacl url=http://localhost:8964/`。
  - 若失效，應重啟 Windows `http` 服務 or 直接重啟作業系統。
  - **診斷工具**：研發過程中應隨手備份 `research_ws_direct.cjs` 這類不依賴 MCP Framework 的原始 WebSocket 測試指令，用於快速定位是通訊層還是應用層故障。

## [L-009] WebSocket 大型數據處理與分片拼接機制

- **避坑經驗**：在 Revit MCP Add-in 中，隨附的 SocketService.cs 預設緩衝區（如 4096 bytes）若不具備拼接邏輯，將導致大型 JSON 指令（如 100+ 條詳圖線 ≈ 50KB+）在傳輸時被截斷，造成 JSON 解析靜默失敗。
- **規則**：
  - **接收端 (C#)**：必須使用 MemoryStream 並循環讀取 WebSocket.ReceiveAsync 直到 result.EndOfMessage 為真。
  - **緩衝區優化**：對於 BIM 數據傳輸，建議將接收緩衝區基礎大小提升至 64KB (65536 bytes) 以減少 frame 讀取次數。

## [L-010] 批次寫入的「順序執行 (Sequential Async)」原則

- **避坑經驗**：一次性向 WebSocket 送出數十個寫入指令（如 rename_element）時，若不等待回應直接關閉或繼續發送，容易發生指令遺失或 Revit 處理衝突。
- **實踐**：應在腳本中實作 sendCommand 包裝函式，利用 Promise 等待單一指令的 RequestId 回傳後，再執行下一個動作。

## [L-011] Revit 名稱正規化 (Normalization) 策略

- **規則**：Revit 中的人為命名（圖紙名稱、類型名稱）常包含不可控的符號與空格。
- **比對實踐**：
  - 統一將全形英數轉為半形。
  - 移除所有括號、減號、空格與常用修飾詞。
  - 優先提取數位部分進行 ID 比對，若 ID 無法辨識則改用正規化後的名稱進行 includes 模糊比對。

## [L-012] Revit 元件空間座標提取策略

- **避坑經驗**：Revit MCP 內建的 query_elements 預設僅回傳參數字串，缺乏幾何座標。對於需要「排序」或「對齊」的工具，這將導致邏輯失效。
- **實踐**：在 C# 核心端擴充 get_element_location 指令，判斷 Location 屬性（Point 或 Curve）並 fallback 到 BoundingBox.Center。

## [L-013] 自動化寫入時的「靜默處理 (Silent Failure Handling)」

- **避坑經驗**：修改「群組 (Group)」內元件的參數時，Revit 會強制彈出警告對話框，中斷自動化流程。
- **實踐**：在 Transaction 中套用 IFailuresPreprocessor（如 DismissWarningsPreprocessor），自動關閉警告，確保腳本能在無人值守情況下完成批次變更。

## [L-014] MCP 寫入工具的並行限制與大 payload 拆分

- **規則**：同時修改 Revit 狀態的 MCP 工具（colorize_clashes、export_clash_report、create_*、override_*）**不可並行呼叫**；回傳大物件的工具不可鏈式 pipe 給下一個工具——中間必須落盤或縮量重跑。
- **避坑經驗**：
  1. `colorize_clashes` + `export_clash_report` 一次送兩個 MCP call 時，兩個都 timeout——皆競爭 `ExternalEventManager` 的 UI thread single-threaded slot。序列化呼叫後雙雙 PASS。
  2. `detect_clashes` 全量 1000 筆結果 937KB，超過 tool output token 限制；而且即使拿到，也無法 inline 當 `clashData` 參數傳給下游（payload > 10KB 時 `format=both` 會 timeout，拆 `format=csv` 單跑 5 筆才通）。
- **實踐**：
  - **寫入類工具永遠序列化**：`await tool_A; then tool_B`，不要塞進同一個 parallel block。讀取類（`get_*` / `query_*`）可安全並行。
  - **大結果鏈式分析時**：第一次跑 `detect_clashes maxResults=1000` 取統計總覽 → 分析後**重跑小 maxResults 或窄 csaSource.categories**（例如只 `["Columns"]`）拿到可 inline 的 ~5KB 物件 → 再 pipe 給 colorize / export.
  - **payload 臨界點**：單一 MCP 工具的 input JSON **> 10KB 就降格**（format=csv 而非 both、clashes 陣列 ≤ 10 筆）。
- **警告**：Revit API 的 UI thread 限制是**結構性**的，不是 bug——MCP-Server 不會替你排隊，client 側必須自律序列化。

## [L-015] Revit Assembly (組件) 與機械 CAD 出圖邏輯之差異

- **核心觀察**：Revit 的出圖邏輯與傳統機械 CAD (如 SolidWorks, Inventor) 有顯著斷層。在機械 CAD 中，零組件 (Part)、組合件 (Assembly) 與爆炸圖均使用統一的導出邏輯；而在 Revit 中，必須透過顯性的「組件 (Assembly)」功能進行隔離，才能獲得高品質的零件三視圖。
- **實作規則**：
  - **隔離必要性**：`.rfa` 元件必須先被包裝成「組件 (Assembly)」而非「群組 (Group)」，才能調用 `AssemblyViewUtils` 產生視圖。
  - **品類陷阱**：建立組件時，傳入的 `Naming Category` 必須符合專案範本的支援清單，否則會報 `No valid type` 錯誤。若自動判定失敗，建議導引使用者先手動建立組件後再由工具接手出圖。
  - **座標系差異**：組件擁有獨立於專案全局的座標系，這對於視圖對齊與自動標註至關重要。
- **展望**：雖然目前的實作必須遵循組件化流程，但開發者應意識到這是一種平台限制。未來若 Revit 官方優化出圖邏輯，工具層應保持擴充性，以支援更靈活的零件/爆炸圖導出模式。

## [L-016] 自動化出圖的「後處理」必要性

- **核心經驗**：呼叫 `Viewport.Create` 只是完成了 50% 的工作。若沒有執行「後處理」，圖紙上會出現標題重疊、裁切框範圍過大、或顯示了不相關的標註與樓層線。
- **後處理清單**：
  - **空間整理**：必須根據各 Viewport 的實際尺寸（Outline）重新計算擺放位置，防止標題 (View Title) 堆疊在圖紙中心。
  - **環境清理**：自動化腳本應主動隱藏視圖中的 Grids (軸網) 與 Levels (樓層線)，零件圖不需要這些建築參照。
  - **裁切鎖定**：必須啟動 `View.CropBoxActive` 與 `View.CropBoxVisible`，並精確縮放到零件邊界。

## [L-017] 視埠標題 (Viewport Title) 的靜態特性陷阱

- **核心經驗**：修改視圖比例 (`View.Scale`) 時，視埠標題的座標 (`LabelOffset`) 與線條長度不會自動適應縮放。
- **陷阱後果**：當比例從 1:1 縮小到 1:20 時，視圖內容縮小了，但標題線可能還留在原地或保持極長的狀態，導致圖面看起來依然混亂，甚至誤導對「視埠實際範圍」的判定。
- **解決對策**：在執行「比例自適應」後，必須強制重新計算標題位置，或透過 API 重設標題線長度。在 MCP 開發中，應將「標題線重置」視為比例調整的連動動作。

## [L-018] 零件圖的視覺表現標準

- **核心經驗**：機械零件圖的價值在於細節。預設的「粗糙」或「中等」詳細等級會導致關鍵幾何遺失。
- **標準設定**：
  - **細節等級 (Detail Level)**：必須為 **Fine**。
  - **2D 表現**：必須為 **Hidden Line**（隱藏線），這符合工程圖學對非透視視圖的規範。
  - **3D 表現**：建議為 **Shaded**（描影），幫助閱讀者快速理解物件的立體材質與空間關係。
- **自動化實踐**：這些設定應作為「視圖生成」後的強制性初始值，而不應依賴使用者手動調整。

## [L-019] 裁切框 (Crop Region) 對幾何判定的干擾

- **核心經驗**：`View.get_BoundingBox()` 回傳的是裁切框範圍。若視圖剛生成且裁切框未收縮，其邊界通常遠大於實際零件。
- **陷阱**：使用視圖邊界計算自適應比例會導致算出過小的比例（如 1:200），使零件在圖紙上變成小點；在佈置視圖時，巨大的裁切框會導致視埠重疊或超出圖紙。
- **正確邏輯**：應以「組件成員幾何聯集」作為比例計算基準，並在後處理階段透過 API 將裁切框 (CropBox) 強制收縮至該幾何邊界。

## [L-020] Revit 2024 原生 PDF 導出 API 的陷阱與優勢

- **技術突破**：拋棄 `PrintManager` 轉向 `doc.Export`。這讓 PDF 輸出實現了「零依賴」，不需安裝任何印表機驅動。
- **API 命名陷阱**：Revit API 在 `PDFExportOptions` 中存在不對稱命名。`HideCropBoundaries` (複數), `HideScopeBoxes` (複數)，但隱藏參考平面必須使用 **`HideReferencePlane` (單數)**，否則會觸發 `AttributeError`。
- **物件層干擾 (Hyperlinks)**：PDF 導出預設會在每個視埠 (Viewport) 範圍建立「視圖超連結」物件。這會導致在 PDF 閱讀器中點擊時，整個視圖區域被視為一個可選取的「藍色大方塊」，干擾文字選取與標註閱讀。
- **視覺優化**：設置 `ViewLinksInBlue = False` 可讓這些連結物件在靜態下透明，但無法完全移除其作為 PDF 互動對象的存在（這是目前原生 API 的限制）。
- **考古重要性**：當遇到 API 報錯時，參考 `guRoo` 或 `pyRevitMEP` 等大神庫能快速定位是版本差異還是命名錯誤。

## [L-021] 停車位自動編號的起點與局部連續性

- **核心經驗**：停車場編碼不能只依全場中心點做極角順時鐘排序。多排、多島或側停混合配置會讓排序起點切在同一排中間，造成相鄰車位出現 `537, 538, 433, 434` 這類斷裂。
- **正確邏輯**：優先使用分排線性排序：`--order yx --linear` 先依 Y 座標分排，再依 X 座標排序；若使用者指定起點，必須用 `--start-element {ElementId}` 將序列旋轉到指定車位開始。
- **驗證規則**：正式寫入前必須跑 `--dry-run`，且不能只看前 10 筆。需抽查使用者指出的局部區域，確認同一排相鄰車位編號連續。
- **工具行為**：未指定 `--start-element` 時，腳本可自動判定排序後第一個元素為起點，但必須在輸出中明確列出「自動判定 ElementId」，讓使用者確認。
- **Revit 警告處理**：批次修改群組內車位參數時，`modify_element_parameter` transaction 必須套用 `DismissWarningsPreprocessor`。若警告仍跳出，需重新編譯、部署對應 Revit 版本 DLL 並重啟 Revit。

## [L-022] C-1 廠房衛浴設備檢核應做成規則引擎

- **情境**：建築設計初期，C-1 廠房配置會反覆調整，若每次都手動重算衛浴設備數量，很容易漏扣樓梯、電梯、防空避難室、停車空間，或套錯男/女設備公式。
- **經驗**：衛浴檢討不應只做單次算式，應先偵測或指定建築物種類，再套用對應規則。目前規則包只支援 `C-1 工廠、倉庫`；未來新增其他建築物種類時，應新增規則，不要覆寫 C-1 公式。
- **做法**：以當層作業廠房樓地板淨面積除以 `10 m2/person` 算人數，預設男女 `1:1`，輸出對應法規表欄位：`建築物種類 / 大便器 / 小便器 / 洗面盆 / 浴缸或淋浴`。
- **C-1 超過 100 人公式**：男用大便器 `1 + ceil((male - 100) / 120)`；女用大便器 `3 + ceil((female - 100) / 30)`；男用小便器 `2 + ceil((male - 100) / 60)`；洗面盆 `ceil(total / 15)`。
- **輸出原則**：只回報需求數量與計算依據，不寫入 shared parameters；回傳 `RuleId`、`BuildingTypeCode`、偵測原因與面積扣除摘要，方便設計者快速判斷配置是否足夠。

## [L-023] 詳圖項目同步需要保留雙路徑

- **情境**：同一批詳圖項目可能有兩種來源。新建或批次整理時，可從圖紙 Viewport 推導；維護舊資料時，則可能只能依既有類型參數反查。
- **經驗**：不要把「從 Viewport 建立/改名」與「從類型參數修圖號」混成單一隱式流程，否則容易誤改類型名稱、重複建立類型，或把使用者只想修圖號的需求擴大成完整重建。
- **做法**：保留 `create_detail_component_types_from_sheet_viewports` 與 `sync_detail_component_sheet_numbers_by_type_parameters` 兩種工具。前者處理建立、完整同步、改名；後者只依 `圖說名稱 + 詳圖名稱` 修正 `詳圖圖號`。
- **防呆**：第二種模式必須支援 `dryRun`。遇到 `not_matched` 或 `ambiguous` 不應寫入，應回報給使用者判斷。
- **命名經驗**：`圖紙上的標題` 比 `視圖名稱` 更接近出圖語意；但舊資料常用 `視圖名稱`，因此比對時要同時索引兩者。
- **家族匹配經驗**：詳圖項目與標籤家族名稱可能很接近，例如 `AE-矩形框詳圖元件` 與 `AE-矩形框詳圖元件標籤`。工具必須先做精確家族名稱比對，避免套錯目標。

## [L-024] sync_detail_component_numbers 的安全匹配要支援雙向前綴

- **情境**：`sync_detail_component_numbers` 原本只接受「類型名稱以所在圖紙編號開頭」。當類型名稱使用較短的圖紙前綴，而實際圖紙號碼較完整時，會被安全模式跳過。
- **新增作法**：保留原本作法，並新增「圖紙編號以類型名稱中的圖紙前綴開頭」的判斷。
- **實作重點**：從類型名稱拆出可能的圖紙前綴，排除太短或不含數字的前綴，再用 `sheetNumber.StartsWith(typeNamePrefix)` 判斷。
- **防護原則**：第二種作法仍只是一道安全守門；若兩種作法都不匹配，仍必須跳過，避免誤改共用或標準詳圖。
- **回傳經驗**：回傳中應分別統計第一種作法、第二種作法與安全跳過數量，方便使用者確認此次同步是靠哪一種規則命中。

## [L-025] PDF 來源的詳圖項目建立不應依賴 Revit 圖紙

- **情境**：新版 PDF 已有完整圖紙號碼、圖說名稱、詳圖編號、詳圖名稱，但 Revit 內可能沒有對應 ViewSheet，或使用者只想先建立詳圖項目類型。
- **經驗**：舊的 `create_detail_component_type` 會先查 Revit 圖紙，PDF-only 來源會因找不到 ViewSheet 而無法建立。這不代表 metadata 不足，而是入口工具耦合錯了。
- **做法**：新增 `create_detail_component_types_from_metadata`，直接吃外部 metadata，依 `詳圖圖號-圖說名稱-詳圖名稱` 建立類型，並寫入 `詳圖圖號`、`圖說名稱`、`詳圖編號`、`詳圖名稱`。
- **防呆**：OCR 或視覺辨識來源必須先 dry run，並保留原始 PDF 頁碼與人工校正清單，避免把辨識錯字寫入 Revit 類型名稱。

## [L-026] PDF 詳圖項目 OCR：詳圖編號不可用排序猜測

- **情境**：從 PDF 建立 `AE-圖號詳圖編號標頭-3.5mm` 類型時，單純依紅框詳圖名稱的版面排序產生 `詳圖編號` 會大量錯配。多視圖圖紙、尺寸數字、標題欄、重複詳圖名稱都會破壞排序法。
- **偵測規則**：優先偵測圖面上字體最大的詳圖號碼數字，排除圖框座標數字與標題欄，再找該數字附近最長、且同樣屬於大字體的繁體中文文字作為 `詳圖名稱`；小字註記、材料說明、尺寸文字即使含有「詳／圖」也先排除。
- **前綴合併**：大字標題附近若有同一基準線、緊貼標題左側的英數前綴，必須併入 `詳圖名稱`，例如 `3F,5F碼頭區排水溝/地坪覆面層/防水層詳圖`、`C3,C9鋁企口天花板安裝示意圖`；OCR 將 `C9` 誤讀為 `c` 時，需靠同頁代碼字典或相鄰詳圖號校正。
- **同名合併**：若多個詳圖號碼對應到相同 `詳圖名稱`，只建立一個類型；`詳圖編號` 以範圍或清單表示，例如 `1-5`、`1,3,7`。
- **缺號補判**：若 OCR 漏讀圓圈數字，可在同一列或同一區域的候選詳圖名稱中，用相鄰已辨識數字補缺號，但必須標記為 `sequence_fallback`，不可直接寫入 Revit。
- **安全原則**：OCR metadata 必須先輸出 preview/dry-run；若使用者已手動校正 Revit 類型參數，除非明確要求，不要覆蓋既有類型。

## [L-027] PDF 詳圖項目 OCR V5：紅框是最高可信範圍，圓圈是無框備援

- **情境**：使用者可在 PDF 中用紅框手動框出 `詳圖名稱`，但也希望沒有紅框時能自動靠圖頭圓圈編號與左側標題建立類型 metadata。
- **紅框規則**：若 PDF 頁面存在紅色 Square 註解框，將框內文字視為詳圖名稱候選；紅框只限定範圍，不保證 OCR 文字正確，因此仍要套用錯字修正與人工複核清單。
- **圓圈備援**：無紅框頁面可先偵測圖頭底線右端圓圈，再讀圈內數字，最後往左抓同一基準線的大字繁體中文標題。這比整頁找最大字體更能排除材料註記與尺寸文字。
- **過濾規則**：圓圈模式必須排除圖框座標、施工說明、表格與材料標註；標題候選需包含 `詳圖`、`立面圖`、`剖面圖`、`平面圖`、`操作圖`、`標示` 等關鍵字。
- **防呆**：圈內數字 OCR 漏讀時可用版面順序補判，但必須標記 `sequence_fallback` 並列為人工複核；V5 結果只可先產生 preview，不可直接正式寫入 Revit。

## [L-028] PDF 詳圖項目 OCR V5 inclusive：先補齊，再人工查核

- **情境**：純 V5 依紅框、圓圈圖頭與大字標題判斷，精準度較高但可能漏項；V4/OCR 較寬鬆，能補回更多候選，但錯字與誤抓風險較高。
- **使用者意圖**：若使用者明確表示「可以不用那麼保守」、「後續會人工查核」，不要只輸出純 V5 high-confidence 結果。應改用 V5 inclusive：V5 作為主來源，V4 作為補漏來源。
- **補漏規則**：若 V4 的 `詳圖圖號 + 詳圖編號` 已被 V5 覆蓋，採用 V5；未覆蓋的 V4 項目可加入 metadata，但必須標記 `review=true` 與 `v4_fallback`。
- **同名合併**：寫入 Revit 前必須依 `詳圖圖號 + 正規化後詳圖名稱` 合併；同一詳圖名稱對應多個編號時只建立一個類型，`詳圖編號` 寫成 `1-5` 或 `1,3,7`。若未合併，Revit 會對同一類型重複 update，最後只留下最後一次的編號。
- **人工查核輸出**：V5 inclusive 必須同時輸出 all-types CSV、review-only CSV 與 Markdown review report，讓使用者能在 IDE 或 Excel 中查核 OCR 疑慮項。
- **執行經驗**：批次寫入 Revit 後，Node/WebSocket 腳本可能因連線收尾讓 Codex 看似仍在運行；套用腳本應寫出 progress/result JSON，並在成功或失敗後明確結束程序。判斷完成狀態以 progress JSON 的 `status=completed` 與 counts 為準。

## [L-029] Revit API 特殊 property 不可走 LookupParameter

- **規則**：`Element.Name` 是 Revit API 的直屬 property，**不在** Parameter 集合內。任何 `LookupParameter("Name")` 或對應中文／英文／BIP 整數值的呼叫，永遠回 `null`，導致重命名類型／視圖／樓層／類別等操作靜默失敗。
- **實踐**：在 `modify_element_parameter` 的 `LookupParameter` 流程**之前**加守門，攔截 `{Name, 名稱, 類型名稱, -1002001}` 四個 alias 鍵，直接寫 `element.Name = newValue`。其他 parameterName 維持原本 `LookupParameter` 路徑（backward compatible）。實作見 `MCP/Core/CommandExecutor.cs:660`（Branch A patch，commit `1ac2485`）。
- **警告**：跨語言介面（中文「名稱」／英文「Name」／BIP 整數值「-1002001」／類型語境「類型名稱」）必須一併支援，否則 AI 在不同語系 Revit 上會表現不一致。Wall instance 在 Revit API 上 `IsValidObject = true` 但寫 `element.Name` 會直接 throw——守門邏輯需 try/catch 並回傳明確錯誤訊息。

## [L-030] 「沒動 ≠ 沒驗證」—— PR review 與 acceptance test 是雙重層級

- **規則**：PR review 看 **diff 範圍**（哪幾行改了），acceptance test 必須覆蓋 **全路徑**（所有 caller 可能進入的分支）。即使 patch 在 `if` 守門前加邏輯、完全沒動 `else` 分支的程式碼，仍必須跑 else 分支的全部子路徑才算驗證完整。
- **實踐**：Branch A 第一次只測 Name 守門 4/4 就要 merge，被使用者要求補完 else 分支三條子路徑（B：Double 正常寫入 / C：IsReadOnly 守衛 / D：TryParse 失敗），達 7/7 才正式 squash-merge。`docs/branchA.md §10` 紀錄了完整 7/7 表格。
- **警告**：「我沒動這段，應該不會壞」是工程直覺，但合入主幹的責任是「我證明這段確實沒壞」。直覺與證明的差距正是 PR 退回的主因。

## [L-031] Auto-push 與 Merge 是兩個授權層級

- **規則**：`feedback_auto_push.md` 授權「修正完成後自動 commit + push 到 **feature 分支**」，**不**授權「squash-merge 到 main」。merge 是另一個決策層級，必須等使用者明確確認。
- **實踐**：Branch A 第一次擅自 squash-merge（`cd21bab`）被使用者糾正後 revert（`118d069` + `0ab786f`），保留審計軌跡而非 force-push 抹除。第二次走完 7/7 acceptance test 並等待使用者「可以 merge 了」才正式合入（`1ac2485`）。
- **警告**：feature 分支 push 失敗最多重來，merge 到 main 影響所有下游 pull 的人——授權邊界必須在動作前判斷，不是動作後解釋。

## [L-032] Revit 既有功能優先於自寫工具

- **規則**：當 Revit 軟體本身已有功能時，AI 的價值是「**指導使用者操作既有工具**」而不是「**寫新工具取代既有功能**」。遇到「該寫工具」的衝動時，必須先問三題：
  1. **Revit UI 已有同樣功能嗎？** 若 UI 一鍵能達成，寫 tool 就是 1:1 包裝，marginal value = 0
  2. **BIM 設計師工作流真的需要嗎？** 還是 AI/腳本自造的需求？（建模初期、精修階段、AI-only workflow 各有不同判斷）
  3. **這工具能跟其他工具形成 workflow chain 嗎？** Single-shot tool 沒有下游接續 = 無意義
- **實踐（Branch C 三拒收案例）**：
  - `update_wall_curve`（拒收）：fork 老師寫來「微調牆 endpoint」，但 BIM 設計師根本不會這樣工作——對方自己 `draw_wall_from_col.mjs` 也是用 `create_wall` 從零建。**反模式：AI 為自己腳本失誤造的問題自寫解藥**
  - `auto_place_rooms`（拒收）：Revit UI 本來就有「自動置放房間」按鈕，tool 是 1:1 包裝。**反模式：UI 按鈕 1:1 包裝**
  - `update_category_line_weight`（拒收）：Revit 已有完整 Visibility 三層機制（Object Styles / Filter VG Overrides / Element-level override），對方只實作 Layer 1。**反模式：對 Revit 不熟導致的 redundant tool**
- **警告**：fork 老師若不熟 Revit 軟體本身，會反覆寫出 redundant tools。**遇到能力缺口時應先上報 issue 給 maintainer 評估，而不是直接寫工具進來**。詳細的「能力缺口 ≠ 必須寫工具」判斷流程見 `domain/tool-capability-boundary.md` 之「能力缺口 vs Revit 既有功能」一節。
- **對照**：與 L-Branch A 的 Tool Call Data Honesty 是同一哲學的兩面——AI 不該用 LM 接龍生成 number（**誠實**）；AI 不該寫新工具取代 UI 功能（**節制**）。共通邏輯：認清自己能力邊界 + 對應正確的工具/教學選擇。

## [L-033] Active State Re-Anchoring（狀態錨點重新驗證）

- **規則**：任何引用 view-state / level-state / active-context 的 claim 之前，必須在 claim 時點重新呼叫 `get_active_view`（或對應 anchor tool）確認當前狀態。**不能依賴 session 較早的 read 結果**——使用者可能已切視圖、切樓層、切 .rvt 檔，AI 無法被動偵測這些變動。
- **避坑經驗（5/22 dry-run 雙重失誤）**：
  - 第一次：呼叫 `override_element_graphics` 染 Room 時，預設用 session 開頭的 viewId——但這條只是工具邊界（L6），未驗證使用者眼前畫面
  - 第二次：使用者刻意切到 6F 視圖、再切 2F duplicate 視圖，AI 仍引用「session 開頭的 1F」做 claim。**根因不是視圖變了，而是 AI 沒在 claim 時 re-anchor**
- **實踐**：每個 level-scoped / view-scoped 工具呼叫前 → `get_active_view` 重查 → 用最新 LevelName/ViewId 帶入。多次連續呼叫同一 scope 可在「同一 turn 內」省略中間 re-anchor（前後 5-10 秒），但跨 turn 必須重查。
- **對照**：跟 Tool Call Data Honesty 是同一哲學的時間維度——Data Honesty 管「數據從哪來」（不可 LM 先驗），Active Re-Anchoring 管「狀態何時刷新」（不可用過期 snapshot）。
- **延伸至雙向協議**：使用者切視圖 / 切樓層 / 切 .rvt 檔後，可選擇 (a) 主動告知 (b) 不告知但 AI re-anchor 也能跟上。**模型重新載入 / 切 .rvt 檔則必須告知**——隱式偵測會晚一拍。詳細 SOP 見 `domain/session-context-guard.md` 之「Active State Re-Anchoring」一節。

## [L-034] Tool Scope Mismatch（同批工具回應範圍不一致）

- **規則**：同一 prompt 並行 invoke 多個工具時，這些工具 of scope 可能不一致——有的 project-wide、有的 level-scoped、有的 view-scoped。AI 必須主動 surface 範圍差異，使用者才不會誤判混合報告。
- **避坑經驗**：0523 demo Step 3「5 工具並行」中，`check_exterior_wall_openings` 是 project-wide（445 牆全跑、跨樓層回 8 項違規），其他 4 工具是 level-scoped。在 2FL 跑這 5 工具，AI 若把所有結果統一呈現為「2FL 報告」，會誤導使用者以為 8 項違規都發生在 2FL（實際 4 項在 1F、4 項在 2F）。
- **實踐**：(a) 工具 schema 中是否有 `levelName` / `viewId` / `level` 參數，是判斷 scope 的第一線索；(b) 回傳 JSON 中是否有 `LevelName` / `ViewId` 欄位呼應請求；(c) AI 主動報告：「以下 5 個工具中，4 個是 X 樓層範圍、1 個是整案範圍」。
- **未來方案**：所有 `check_*` 系列工具應在回傳中強制加 `ResultScope: "project" | "level" | "view"` 標籤。

## [L-035] Regulation Type → Coloring Strategy 對應

- **規則**：`override_element_graphics` 的染色策略**不能跨規範類型通用**——不同規範的「限制施加位置」不同，視覺化策略也不同。
- **二分類**：
  - **(A) Wall-anchored 規範**（§45/§110 外牆開口距地界線等）：限制施加在「牆上的特定開口」，直接染 violation 牆段
  - **(B) Room-anchored 規範**（§41 採光、§101/§188 排煙、停車淨高等）：限制施加在「房間整體屬性」，沒有「違規牆段」，需 proxy 染色（hosting walls / bounding walls / 該層樓所有對外開口位置）
- **避坑經驗**：5/22 dry-run 中段對 1FL 跑 §45/§110，直接染 4 道 violation 牆（2 紅 + 2 黃）成功；對 2FL 事務室（§41 採光 0% FAIL）想沿用同一染色 prompt，發現事務室沒有「違規牆段」，必須改用 hosting walls proxy 才能視覺化。**原 Step 5 redesign prompt 不直接適用於 room-anchored 規範**。
- **實踐**：handson Step 5 prompt 必須按規範類型分支——wall-anchored 走 violation 牆段；room-anchored 走 proxy SOP（首選 hosting walls，從 `get_room_daylight_info` 拿房間 Openings 的 HostWallId 集合）。
- **延伸**：詳細的 b1/b2/b3 三條 proxy 策略見 `domain/tool-capability-boundary.md` L8。

## [L-036] MCP Failure Mode & Recovery SOP

- **規則**：MCP 工具呼叫可能 timeout、無回應、或返回 error。AI 對應 SOP：第一次 timeout 重試一次；第二次 timeout 停止重試，按 Tool Call Data Honesty Branch C 立刻 surface 給使用者，**不假裝知道模型狀態繼續執行**。
- **避坑經驗**：5/22 dry-run 中段連續 2 次 `get_active_view` timeout。AI 拒絕用 session memory 推測視圖（避免基於 stale snapshot 做染色操作）→ 等使用者修復連線。
- **使用者端 diagnostic 順序**：
  1. Revit 視窗 + RevitMCP 面板 Server 燈號狀態檢查
  2. 排除 modal dialog 擋住
  3. Revit 點任意視圖一下，重新確立 active focus（最常見的修復）
  4. RevitMCP 面板「Restart Server」
  5. 關 Revit 重開
  6. Port 8964 釋放（`scripts/release-port.ps1`，需管理員權限）
- **5/23 demo 講者預備**：Live demo 中 MCP 中斷是真實會發生的事，講者應預演 (3)(4) 兩步驟並有 fallback 影片。
- **延伸**：詳細 SOP見 `domain/tool-capability-boundary.md` L9。

## [L-037] BIM 模型內在不一致的誠實 surface

- **規則**：BIM 模型中同一個概念可能有多個值（如「面積」幾何計算值 vs「面積 部屋 調整値」手填校正值），這些值可能差 1-5%。MCP 工具回的是 source value，**AI 不該自動替使用者選一個**——必須 surface「兩個值並存」這件事，由人決定哪個是合規檢討基準。
- **避坑經驗**：5/22 dry-run 比對 1FL 6 個房間的 `get_rooms_by_level`（回 Area = Revit 自動計算的幾何面積）vs `get_element_info`（同時揭露「面積 部屋 調整値」這個校正欄位）。差異從 -0.07 m²（風除室）到 +1.00 m²（店舗）不等。**這 1 m² 在排煙檢討的 2% 邊界 case 上會跨越合規門檻**。
- **實踐**：(a) 設計師若用 MCP 查面積、紙本仕上表查面積，兩個值會差→AI 應主動標記；(b) 法定報告用哪個 → 法務 / 業主決定 → AI 不替你選。
- **更上游問題**：這不是 MCP 工具 bug，是 BIM 模型本身「幾何 vs 手填表格值」的失同步。可能來源——建模時牆邊界稍有移動但仕上表沒同步；校正値本來就是對齊圖紙標註的手調值；仕上表用「外側量測」vs 面積用「內側淨空」差異等。
- **對照**：呼應 P4「限制顯現器」+ Tool Call Data Honesty——MCP 不會替你決定「哪個面積才算數」，把兩個都端出來，由你決定。

## [L-038] DLL 部署被鎖定時必須立刻停止

- **情境**：Revit 開啟時部署 `RevitMCP.dll`，`Copy-Item` 可能因拒絕存取或「檔案正被另一個處理程序使用」而失敗。
- **教訓**：不要迴圈重試部署。DLL 被鎖定後，不要繼續輪詢 WebSocket、反覆檢查 process，或繼續消耗 tool call。
- **規則**：立刻停止，告知使用者必須先關閉 Revit，並等待使用者明確回覆「已關閉」後，才嘗試一次新的部署。
- **原因**：Revit 會把 add-in DLL 載入 process。Revit 釋放 DLL 之前，後續複製嘗試都只是雜訊，並且會浪費執行預算。

## [L-039] 直接 Revit WebSocket wrapper 必須符合目前 socket contract

- **情境**：`MCP-Server/scripts/run_command.js` 一開始送出 `{ CommandName, Parameters, RequestId }`，但目前 Revit socket model 預期的是 `{ method, params, id }`。
- **症狀**：Revit log 顯示空白 command name 與空白 request id；wrapper 看起來像卡住，因為它等待的 response id 永遠無法匹配。
- **教訓**：若因 Codex 可見的 MCP schema 尚未刷新而使用 repository wrapper，wrapper 必須與 `MCP-Server/src/socket.ts` 和 `MCP/Models/CommandModels.cs` 保持一致。
- **規則**：wrapper 必須具備 command hard timeout 與 connection timeout。也應從 `REVIT_MCP_PARAMS_JSON` 接收 JSON 參數，避免 PowerShell quote mangling。
- **驗證**：健康的直接 command 會回傳匹配的 `RequestId`；dry-run command 即使 Revit 沒有回答，也必須能自行結束。

## [L-040] 視埠標題類型最安全的來源是已放置 Viewport.GetValidTypes()

- **情境**：在本專案的 Revit 2020 中，使用 `FilteredElementCollector(doc).OfCategory(OST_Viewports).WhereElementIsElementType()` 收集視埠標題類型時回傳 0 個類型。
- **教訓**：若要變更視埠類型，最可靠的來源是既有、已放置的 `Viewport`。
- **規則**：用 `viewport.GetTypeId()` 收集目前類型，並用 `viewport.GetValidTypes()` 收集可切換類型。這會反映 Revit 對 `Viewport.ChangeTypeId()` 實際允許的類型。
- **流程**：先執行 `get_viewport_types`，再以 `dryRun=true` 執行 `sync_viewport_types_by_view_scale`，接著以 `dryRun=false` 套用，最後再次 dry-run。成功判定為 `ChangedCount = 0`。
- **範圍控制**：只處理圖紙上的 `FloorPlan`、`Elevation`、`Section` 視埠。若已放置視圖名稱或 `Title on Sheet` 包含 `圖例`，則略過。若沒有精確比例標題類型，使用備援的有線條標題視埠類型。
- **Domain 參考**：`domain/viewport-type-scale-sync.md`。

## [L-041] 輕隔間算量：host-only 開口與 Revit 面積基準

- **情境**：輕隔間 CSV 初版以「門窗座標靠近 TYPE 牆」推定開口扣除，導致房間 F212 的 `廁所門-60x200 cm` 被錯扣；該門實際 `主體 ID` 是非 TYPE 的廁所隔牆。另以 `不連續高度` 直接相乘，使 `Type-B 濕式輕隔間-襯板` 從舊表約 64 m² 被高估到 76.4928 m²。
- **規則 1：開口扣除必須 host-only**。門窗或開口只有在其 `主體 ID` / Host ElementId 等於本次計算的 TYPE 牆 ElementId 時才能扣除。不得用 nearest wall、座標距離、同樓層接近、房間內接近等幾何近似替代 host 關係。
- **規則 2：表內牆高是有效高度，不是原始 `不連續高度`**。若範本要求保留 `牆長 × 牆高` 公式，應以 Revit 牆 `面積` 為基準反推有效高度：`表內牆高 = (Revit 牆面積 + 已驗證 host 開口面積) / 牆長`。Excel 再扣開口後，總計才會回到 Revit 牆面積基準。
- **驗證**：抽查一個使用者質疑的房間與一個總量敏感的牆型。F212 應無 `廁所門-60x200 cm` 扣除；`Type-B 濕式輕隔間-襯板` 應回到舊表基準約 64.0563 m²。若任一不符，停止交付並重查 host 與面積來源。
- **Domain 參考**：`domain/revit-partition-takeoff.md`。
## [L-042] 房間重新排序編號應使用 Revit 端批次交易

- **情境**：使用者要求「房間重新排序編號，只排 B1F，從 B134 開始」。若用 MCP 層逐筆 `modify_element_parameter`，每間房間都會有一次 tool 往返與一次 Revit transaction，20 間房間就會明顯變慢。
- **教訓**：大量房間編號不是單筆參數修改問題，而是「查詢、排序、批次寫入」問題；排序與寫入應放在 Revit add-in 端一次完成。
- **正確做法**：使用 `renumber_rooms_by_level`，先 `dryRun=true` 預覽，再 `dryRun=false` 寫入。工具在 Revit 端依 Room 中心點由上到下、同列由左到右排序，並用單一 Transaction 批次寫入房間 `ROOM_NUMBER`。
- **安全檢查**：寫入前先 re-anchor `get_active_view`；樓層名稱不可猜，若 `B1F` 解析為 `C-B1F` 必須在回覆中說明；若候選房號已存在於其他樓層，除非使用者明確允許，否則停止。
- **文件化**：此流程已整理到 `domain/room-numbering-workflow.md` 與 `room-numbering` Skill。後續遇到 room numbering / 房間重新排序 / 自動編號需求，優先走此批次工具，不要退回舊 WebSocket 腳本或逐筆修改。

## [L-043] 樑頂貼齊樓板底：先判斷主要覆蓋範圍，再取樓層相對偏移最低的樓板底

- **教訓**：樑頂貼齊樓板底不能只靠最近樓板命中、全模型最大樓板面積，或起點/終點各自獨立選板。這些策略可能選到完成面、相鄰上層樓板，或讓同一根樑分別貼到兩片不同樓板。
- **規則**：既有 StructuralFraming 樑若使用 `起始樓層偏移` 與 `結束樓層偏移`，應沿樑取樣，依 Floor ElementId 分組樓板底命中，保留 sample-hit 數最高的主要覆蓋群組，再選擇相對自身 Revit Level 樓板底偏移最低的樓板。該樓板應作為樑兩端共同目標。
- **校正案例**：`8546314 -> 8693275`、`8543272 -> 8115865`、`8541251 -> 8103066` 在未來邏輯變更後仍必須正確。全棟執行前要先 dry-run 這些案例。
- **安全規則**：Floor 候選應限制為真正樓板，目前為名稱包含 `樓板` 或以 `RC_` 開頭者；除非使用者明確擴大目標集合。必須先 dry-run，且只在目標 FloorId 驗證後才套用。
- **Domain/Skill**：詳見 `domain/beam-slab-alignment.md` 與 `beam-slab-alignment` Skill。

## [L-044] IFC 原生結構同步必須用 Source Fingerprint 追蹤並允許重建

- **情境**：依 IFC Link 建立 Revit 原生 `StructuralFraming` 與 `StructuralColumns` 時，幾何、族類型、樓板貼附規則可能會在工具優化後改變。舊元素若只靠 ElementId 逐筆修改，很容易留下錯族、錯參數或錯偏移。
- **規則**：同步工具建立的元素必須寫入可追蹤的來源註記，例如 LinkId、IFC ElementId、SourceKind、SourceFingerprint 與 `IFC_STRUCT_SYNC`。當判斷邏輯修正後，應支援 `replaceExisting=true` 先刪除舊同步元素再重建。
- **避坑經驗**：使用者可能已手動刪除舊梁，或工具套用逾時但 Revit 端 Transaction 其實已完成。不能用舊 ElementId 當唯一驗證基準；套用後要重新查同步標記、類型名稱、族類型、參數與幾何位置。
- **實踐**：標準流程為 `get_linked_models` → `sync_ifc_structural_to_native(dryRun=true)` → 使用者確認範圍 → `dryRun=false` → 回讀抽查。重大邏輯變更後優先用 `replaceExisting=true`，避免舊錯誤混在新模型裡。
- **Domain/Skill**：詳見 `domain/ifc-structural-native-sync.md` 與 `ifc-structural-sync` Skill。

## [L-045] IFC 結構柱 b/h 不可直接相信全域 X/Y 或類型名稱

- **情境**：IFC 柱截面轉 Revit 柱族時，局部軸、族參數語意與全域 BoundingBox 方向可能不同。若直接把 X 當 b、Y 當 h，可能產生使用者看到的 b/h 顛倒。
- **規則**：柱截面尺寸應先從 IFC 幾何或截面外框取得兩個主尺寸，再依本專案命名約定正規化為 `b = 短邊`、`h = 長邊`。類型名稱應寫成 `IFC-COL-H{h}xB{b}`，且類型參數 `b`、`h` 必須同步寫入，不可只改名稱。
- **避坑經驗**：只改類型名稱而未改類型參數，外觀或明細仍會錯。只看 BoundingBox 全域 X/Y，也可能因柱旋轉而誤判。重建後舊 ElementId 可能消失，因此要用同步標記或新元素集合回查。
- **實踐**：抽查時同時驗證三件事：族類型是否正確、`b/h` 類型參數是否正確、模型幾何尺寸是否與 IFC 主尺寸一致。方柱若兩邊相同仍要寫入參數，不可省略。
- **Domain/Skill**：詳見 `domain/ifc-structural-native-sync.md`。

## [L-046] IFC 柱族選型要判斷實心/空心，不可只靠使用者指定一次

- **情境**：同一批 IFC 柱可能混有鋼柱、SHS 方形空心鋼管柱、RC 方柱或其他實心柱。使用者更正一次 `SRC` 應為 `SHS`，不代表所有方柱都應套同一族。
- **規則**：柱族選型應由工具自動依 IFC 材料、名稱、截面外框、內孔與 solid volume ratio 判斷。空心方管使用 `SHS-正方形空心剖面-柱`，一般鋼柱使用既有鋼柱族，完全實心且材料/名稱偏 RC 的柱應使用 RC 方柱。
- **避坑經驗**：只依名稱包含 SRC、SHS、RC 會失敗，因 IFC 名稱常不穩定；只依外框尺寸也會把空心管與實心柱混在一起。必須把「是否完全實心」列為選型條件。
- **實踐**：工具回傳應揭露 `sourceKind`、判斷到的截面尺寸、空心/實心分類、族名稱與 type name。若信心不足，先 dry-run 列入人工確認，不要直接大量套用。
- **Domain/Skill**：詳見 `domain/ifc-structural-native-sync.md`。

## [L-047] 柱頂貼齊樓板底不可只用柱中心點射線

- **情境**：柱頂需頂到樓板底部，例如使用者指出某柱未貼附指定樓板。若只用柱中心點往上/下找樓板，柱位在樓板邊緣、洞口、斜板或梁柱交界時會漏判。
- **規則**：柱頂目標樓板應使用柱 BoundingBox 或截面範圍做多點取樣，至少包含中心、邊點與角點，並優先使用實際幾何 bottom face 交點，而不是只用樓板 BoundingBox。
- **避坑經驗**：BoundingBox 只能當候選篩選，不能當最終貼附高度；斜板、複合樓板或邊緣區域會讓 BoundingBox 高度與真正樓板底不同。中心點沒打到樓板不代表柱不用延伸。
- **實踐**：柱同步後應批次執行 `align_columns_top_to_floor_bottom`，先 dry-run 抽查 `targetFloorId`、`targetBottomElevation`、`newTopOffset`，再 apply。apply 後再次 dry-run，殘差應接近 0。
- **Domain/Skill**：詳見 `domain/ifc-structural-native-sync.md`。

## [L-048] 梁頂貼樓板底要同時處理斜板、接合與上下疊梁

- **情境**：IFC 梁轉成 `UB-通用樑` 後，梁頂可能仍凸出樓板。原因不只偏移值錯誤，也可能是梁端接合、cutback、斜板底面高度變化，或同位置上下疊梁未等量跟隨。
- **規則**：梁同步時先建立正確 XYZ 軸線與 `UB-通用樑` 類型，再用 `align_beams_top_to_floor_bottom` 貼板。工具需自動判斷樓板底是否傾斜；若傾斜，起點與終點偏移應各自對應樓板底高度；若水平，兩端等量下降。
- **避坑經驗**：只把 LocationCurve Z 平移不一定會改到 `起始樓層偏移` / `結束樓層偏移`；梁端接合可能讓幾何仍被拉回或凸出。貼板前應可選擇 disallow join，貼板後要做 geometry residual correction。
- **疊梁規則**：同一垂直堆疊的梁，先以最上方梁貼樓板底作為基準，下面梁依原本相對間距等量偏移，避免把所有梁都拉到同一樓板底。
- **實踐**：全棟執行前先 dry-run 代表性水平板、斜板、屋頂邊緣與疊梁案例。apply 後再次 dry-run 檢查 protruding/residual，仍凸出者優先檢查 join/cutback 與選板是否錯誤。
- **Domain/Skill**：詳見 `domain/ifc-structural-native-sync.md` 與 `domain/beam-slab-alignment.md`。

## [L-049] MCP 結構工具更新後要驗證 schema、DLL 與 Revit 狀態三者一致

- **情境**：新增或修改 `sync_ifc_structural_to_native`、`align_beams_top_to_floor_bottom`、`align_columns_top_to_floor_bottom` 後，可能發生 TypeScript schema 已改但 MCP 工具列表未刷新，或 DLL 編譯成功但 Revit 仍載入舊 DLL。
- **規則**：改工具邏輯後要完成三層驗證：MCP-Server schema 可見、Revit add-in DLL 已部署、Revit 重開後實際工具行為符合新邏輯。若 Revit 開著導致 DLL 被鎖，立即要求使用者關閉，不要重複複製。
- **避坑經驗**：工具呼叫 timeout 不等於失敗；大型 Transaction 可能在 timeout 後才完成。此時應重新回讀模型驗證，而不是重複 apply 造成重建或刪除風險。
- **實踐**：每次部署後先做小範圍 dry-run，再做單一或少量元素 apply，最後才全棟 apply。使用者回報具體 ElementId 時，先查該元素目前參數與幾何，再決定是否是工具邏輯、舊元素殘留或 Revit 接合造成。
- **Domain/Skill**：詳見 `domain/ifc-structural-native-sync.md`。

## [L-050] 施工架算量必須分清室外、一般室內與樓電梯室內裝修

- **情境**：施工架數量同時包含 `框式施工架(含防護設施)<室外施工架>`、室內一般房間施工架、樓梯/電梯類室內裝修施工架。若全部套同一個周長或同一個長寬高公式，會把單位與數量基準混在一起。
- **規則 1：室外施工架採人工描繪外周長**。優先使用 `calculate_selected_detail_line_perimeter` 讀取使用者選取的 detail line / filled region 周長。自動外牆偵測只可作輔助，不作預設正式數量來源。
- **規則 2：室內一般房間用 `周長 * 高`**。排除 `戶外平台/戶外平臺`、`露臺/露台`、`陽台/陽臺`、`管道間`、`水箱`，並排除樓層 `FN`、`TF`。
- **規則 3：樓梯/電梯類室內裝修施工架用 `長 * 寬 * 高`**。觸發字包含 `安全梯`、`無障礙梯`、`樓梯`、`電梯`、`貨梯`、`昇降機`、`升降機`、`客梯`。其中 `梯廳` 不是 `樓梯`，除非使用者另行指定，仍屬一般房間。
- **實踐**：回報時必須列出公式與單位，不可把 `m`、`m2`、`m3` 加總成單一數字。若沒有指定 `scaffoldHeightMm`，需說明是否使用房間 bounding-box 高度作為暫時計算基準。
- **Domain/Skill**：詳見 `domain/scaffold-takeoff.md` 與 `scaffold-takeoff` Skill。
