---
name: lessons
description: "Lessons Learned：由 /lessons 指令自動維護的專案避坑經驗集。記錄高階開發規則與實作教訓，採 Append-only 追加、禁止修改或刪除已有條目。當使用者提到 lessons、開發經驗、避坑、經驗、教訓時觸發。"
metadata:
  version: "1.1"
  updated: "2026-05-20"
  created: "2026-03-13"
  contributors:
    - "Admin"
    - "shuotao"
    - "unknown"
  references: []  # TODO: 月小聚補法規條號或外部依據
  related: []  # TODO: 月小聚補相關 domain（檔名）
  referenced_by:
    - auto-dimension
    - element-query
    - fire-safety-check
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
  - **大結果鏈式分析時**：第一次跑 `detect_clashes maxResults=1000` 取統計總覽 → 分析後**重跑小 maxResults 或窄 csaSource.categories**（例如只 `["Columns"]`）拿到可 inline 的 ~5KB 物件 → 再 pipe 給 colorize / export。
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
---

## [L-023] 詳圖項目同步需要保留雙路徑

- **情境**：同一批詳圖項目可能有兩種來源。新建或批次整理時，可從圖紙 Viewport 推導；維護舊資料時，則可能只能依既有類型參數反查。
- **經驗**：不要把「從 Viewport 建立/改名」與「從類型參數修圖號」混成單一隱式流程，否則容易誤改類型名稱、重複建立類型，或把使用者只想修圖號的需求擴大成完整重建。
- **做法**：保留 `create_detail_component_types_from_sheet_viewports` 與 `sync_detail_component_sheet_numbers_by_type_parameters` 兩種工具。前者處理建立、完整同步、改名；後者只依 `圖說名稱 + 詳圖名稱` 修正 `詳圖圖號`。
- **防呆**：第二種模式必須支援 `dryRun`。遇到 `not_matched` 或 `ambiguous` 不應寫入，應回報給使用者判斷。
- **命名經驗**：`圖紙上的標題` 比 `視圖名稱` 更接近出圖語意；但舊資料常用 `視圖名稱`，因此比對時要同時索引兩者。
- **家族匹配經驗**：詳圖項目與標籤家族名稱可能很接近，例如 `AE-矩形框詳圖元件` 與 `AE-矩形框詳圖元件標籤`。工具必須先做精確家族名稱比對，避免套錯目標。
---

## [L-024] sync_detail_component_numbers 的安全匹配要支援雙向前綴

- **情境**：`sync_detail_component_numbers` 原本只接受「類型名稱以所在圖紙編號開頭」。當類型名稱使用較短的圖紙前綴，而實際圖紙號碼較完整時，會被安全模式跳過。
- **新增作法**：保留原本作法，並新增「圖紙編號以類型名稱中的圖紙前綴開頭」的判斷。
- **實作重點**：從類型名稱拆出可能的圖紙前綴，排除太短或不含數字的前綴，再用 `sheetNumber.StartsWith(typeNamePrefix)` 判斷。
- **防護原則**：第二種作法仍只是一道安全守門；若兩種作法都不匹配，仍必須跳過，避免誤改共用或標準詳圖。
- **回傳經驗**：回傳中應分別統計第一種作法、第二種作法與安全跳過數量，方便使用者確認此次同步是靠哪一種規則命中。

---

## [L-025] PDF 來源的詳圖項目建立不應依賴 Revit 圖紙

- **情境**：新版 PDF 已有完整圖紙號碼、圖說名稱、詳圖編號、詳圖名稱，但 Revit 內可能沒有對應 ViewSheet，或使用者只想先建立詳圖項目類型。
- **經驗**：舊的 `create_detail_component_type` 會先查 Revit 圖紙，PDF-only 來源會因找不到 ViewSheet 而無法建立。這不代表 metadata 不足，而是入口工具耦合錯了。
- **做法**：新增 `create_detail_component_types_from_metadata`，直接吃外部 metadata，依 `詳圖圖號-圖說名稱-詳圖名稱` 建立類型，並寫入 `詳圖圖號`、`圖說名稱`、`詳圖編號`、`詳圖名稱`。
- **防呆**：OCR 或視覺辨識來源必須先 dry run，並保留原始 PDF 頁碼與人工校正清單，避免把辨識錯字寫入 Revit 類型名稱。

---

## [L-026] PDF 詳圖項目 OCR：詳圖編號不可用排序猜測

- **情境**：從 PDF 建立 `AE-圖號詳圖編號標頭-3.5mm` 類型時，單純依紅框詳圖名稱的版面排序產生 `詳圖編號` 會大量錯配。多視圖圖紙、尺寸數字、標題欄、重複詳圖名稱都會破壞排序法。
- **偵測規則**：優先偵測圖面上字體最大的詳圖號碼數字，排除圖框座標數字與標題欄，再找該數字附近最長、且同樣屬於大字體的繁體中文文字作為 `詳圖名稱`；小字註記、材料說明、尺寸文字即使含有「詳／圖」也先排除。
- **前綴合併**：大字標題附近若有同一基準線、緊貼標題左側的英數前綴，必須併入 `詳圖名稱`，例如 `3F,5F碼頭區排水溝/地坪覆面層/防水層詳圖`、`C3,C9鋁企口天花板安裝示意圖`；OCR 將 `C9` 誤讀為 `c` 時，需靠同頁代碼字典或相鄰詳圖號校正。
- **同名合併**：若多個詳圖號碼對應到相同 `詳圖名稱`，只建立一個類型；`詳圖編號` 以範圍或清單表示，例如 `1-5`、`1,3,7`。
- **缺號補判**：若 OCR 漏讀圓圈數字，可在同一列或同一區域的候選詳圖名稱中，用相鄰已辨識數字補缺號，但必須標記為 `sequence_fallback`，不可直接寫入 Revit。
- **安全原則**：OCR metadata 必須先輸出 preview/dry-run；若使用者已手動校正 Revit 類型參數，除非明確要求，不要覆蓋既有類型。

---

## [L-027] PDF 詳圖項目 OCR V5：紅框是最高可信範圍，圓圈是無框備援

- **情境**：使用者可在 PDF 中用紅框手動框出 `詳圖名稱`，但也希望沒有紅框時能自動靠圖頭圓圈編號與左側標題建立類型 metadata。
- **紅框規則**：若 PDF 頁面存在紅色 Square 註解框，將框內文字視為詳圖名稱候選；紅框只限定範圍，不保證 OCR 文字正確，因此仍要套用錯字修正與人工複核清單。
- **圓圈備援**：無紅框頁面可先偵測圖頭底線右端圓圈，再讀圈內數字，最後往左抓同一基準線的大字繁體中文標題。這比整頁找最大字體更能排除材料註記與尺寸文字。
- **過濾規則**：圓圈模式必須排除圖框座標、施工說明、表格與材料標註；標題候選需包含 `詳圖`、`立面圖`、`剖面圖`、`平面圖`、`操作圖`、`標示` 等關鍵字。
- **防呆**：圈內數字 OCR 漏讀時可用版面順序補判，但必須標記 `sequence_fallback` 並列為人工複核；V5 結果只可先產生 preview，不可直接正式寫入 Revit。

---

## [L-028] PDF 詳圖項目 OCR V5 inclusive：先補齊，再人工查核

- **情境**：純 V5 依紅框、圓圈圖頭與大字標題判斷，精準度較高但可能漏項；V4/OCR 較寬鬆，能補回更多候選，但錯字與誤抓風險較高。
- **使用者意圖**：若使用者明確表示「可以不用那麼保守」、「後續會人工查核」，不要只輸出純 V5 高信心結果。應改用 V5 inclusive：V5 作為主來源，V4 作為補漏來源。
- **補漏規則**：若 V4 的 `詳圖圖號 + 詳圖編號` 已被 V5 覆蓋，採用 V5；未覆蓋的 V4 項目可加入 metadata，但必須標記 `review=true` 與 `v4_fallback`。
- **同名合併**：寫入 Revit 前必須依 `詳圖圖號 + 正規化後詳圖名稱` 合併；同一詳圖名稱對應多個編號時只建立一個類型，`詳圖編號` 寫成 `1-5` 或 `1,3,7`。若未合併，Revit 會對同一類型重複 update，最後只留下最後一次的編號。
- **人工查核輸出**：V5 inclusive 必須同時輸出 all-types CSV、review-only CSV 與 Markdown review report，讓使用者能在 IDE 或 Excel 中查核 OCR 疑慮項。
- **執行經驗**：批次寫入 Revit 後，Node/WebSocket 腳本可能因連線收尾讓 Codex 看似仍在運行；套用腳本應寫出 progress/result JSON，並在成功或失敗後明確結束程序。判斷完成狀態以 progress JSON 的 `status=completed` 與 counts 為準。
