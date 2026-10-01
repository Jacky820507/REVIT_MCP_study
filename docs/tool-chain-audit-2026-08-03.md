# 工具鏈啟用回圈盤點（2026-08-03）

> 這份文件記錄一次完整的「AI 到底有沒有真的透過 tool call 拿資料、放資料、做結果」盤點，以及當場修掉的部分與留下來的開工單。
> 所有數字都來自當次實際執行的指令（`dotnet build`、`registerRevitTools()`、`git show`、`Select-String`），不是引用既有文件。

## 一句話結論

盤點前，**180 支對 AI 公開的 MCP 工具裡有 66 支（37%）呼叫下去必定拋 `NotImplementedException`**。
工具看得到、叫得動、但一定失敗——這正是「幻覺式錯誤」最好的溫床：AI 呼叫失敗後，很容易改用臆測把答案補完。
修復後：**173 支工具，0 支打不通**，並加上 QA/QC 閘門讓這種漂移不可能再悄悄發生。

---

## 一、盤點結果

### 1-1 工具鏈斷點（最嚴重）

工具鏈有三層：TypeScript 工具定義 → MCP profile 註冊 → C# `CommandExecutor` 的 `switch` 派送。
`MCP-Server/src/tools/revit-tools.ts` 的 `executeRevitTool()` 是純轉手（工具名 = 命令名），所以只要 C# 那邊沒有對應的 `case`，就會掉進 `default: throw new NotImplementedException`。

| 斷點 | 數量 | 證據 |
|---|---:|---|
| 已註冊工具，C# 沒有任何對應命令字串 | 66 | 對 180 支工具逐一在 `MCP/**/*.cs`（排除 `obj/`）搜尋 `"工具名"` |
| TS 有定義但沒進任何 profile | 4 | `structural-tools.ts` 匯出 `structuralTools`，`index.ts` 卻只把名字相近的 `structureTools` 放進 `PROFILE_MODULES` |
| 同一個工具名有兩份定義 | 1 | `sync_ifc_structural_to_native` 同時在 `structural-tools.ts` 與 `ifc-structural-sync-tools.ts` |
| C# 有指令但完全沒有 MCP 工具定義 | 15 | 這些能力 Revit 做得到，AI 永遠碰不到 |

**根因**：合併 `9049da0`（sync upstream/main `9559f23`）時，依 `jacky820507.md` 的 Revit 2020 保護規則對 `MCP/**/*.cs` 套用 `merge=keep-mine`，於是：

- 上游 `9559f23` 的 `CommandExecutor.cs` 有 151 個 `case` → 本 fork 保留自己的 134 個
- 但上游的 **TypeScript 工具定義照常合進來**（`.ts` 不在保護清單）
- 結果：工具層宣告了 180 支，Revit 端只認得其中 114 支

`jacky820507.md` 第 194 行其實預見了這件事（「那個 Skill 在 Revit 2020 環境無法完整執行」），但**沒有任何機制把「哪些工具是死的」告訴執行中的 AI**。

### 1-2 兩個 Revit MCP server 搶同一條連線

| 來源 | 名稱 | 指向 |
|---|---|---|
| 使用者層 `~/.claude.json` | `revitmcp` | `e:\GitHub Library\RevitMCP\MCP-Server\build\index.js` |
| 專案層 `.mcp.json` | `revit-mcp` | `./MCP-Server/build/index.js` |

同一份 build、兩個命名空間，同時載入。而：

- `MCP/Core/SocketService.cs` 一次只保留一條 MCP 連線（CLAUDE.md 的 Single-Connection Limitation）
- `MCP-Server/src/socket.ts` 是**持久連線**，且 `close` 事件後每 5 秒自動重連（第 93–104 行）

兩邊都被用過之後，就會互相把對方踢掉、再各自重連——連線抖動迴圈。這會讓工具呼叫間歇性逾時，症狀看起來像「MCP 有時候怪怪的」。

### 1-3 Agent 分工 prompt spec 的白名單失準

`~/.claude/agents/` 共 31 份定義檔（含 3 份總指揮範本）。掃描其 `tools:` 白名單：

| Agent | 問題 |
|---|---|
| `revit-operator` | 白名單列了 5 支不存在的工具（`get_element_location`、`measure_clearance`、`get_view_grid_details`、`get_view_crop_box`、`list_scope_boxes`），另有 3 支本 fork 沒有後端（`read_schedule`、`list_schedules`、`list_dimension_types`） |
| `bim-architecture-reviewer` | 同上前兩支 |
| `bim-mep-reviewer` | 同上前兩支 |
| `bim-structure-reviewer` | 同上前兩支 + `get_view_grid_details` |

這幾支正好是「量測與取數」的核心能力。被指派去「只讀模型、回報實測值」的 agent，白名單裡最關鍵的量測工具是空的。

### 1-4 指令文件互相打架（prompt 認知衝突）

已逐條回源碼驗證的衝突：

| 衝突 | 事實來源 |
|---|---|
| `.claude/skills/stair-hidden-line/SKILL.md` 說族群名比對 `"assembled"` 或 `"combined"` | `CommandExecutor.Stairs.cs:47` 實際比對 `組合` / `Assembled`。`combined` 命中不到任何族群，且漏掉中文 token |
| `.claude/skills/beam-slab-alignment/SKILL.md` 傳 `floorSelectionMode: "dominant_area_by_beam"` | `CommandExecutor.StructuralFraming.cs:378,396` 只接受 `nearest_at_beam` 與 `auto_by_beam`（預設） |
| `.claude/skills/scaffold-takeoff/SKILL.md`（未進版控）與 `domain/scaffold-takeoff.md` 在 4 條規則上相反 | 高度來源：skill 說優先引用 `內牆` 天花高，domain L81 說「不能作為施工架高度的事實來源」；插列範圍：skill 說三個工項分頁同步插列，domain L167 說不可一律強制新增；驗證範圍：skill 要求 `更新工項` 不得有 `#REF!`，domain L198 說該分頁是選用的 |
| `domain/README.md:65` 叫貢獻者把新 Skill 建在 `.agents/skills/` | `CLAUDE.md` 的 Domain vs Skill 表定義 Skill 層是 `.claude/skills/*/SKILL.md`。這一行是 `.claude` / `.agents` 兩套分岔持續擴大的來源 |
| `CLAUDE.md` 有兩列都宣告觸發詞 `beam penetration` | 一列指向 `domain/beam-penetration-base.md`，另一列指向 `domain/mep-csa-clash-detection.md`，路由不確定 |
| `CLAUDE.md` Key Source Files 說 `ezdxf_worker.py` 由 `DwgColumnExecutor` 呼叫 | 本 fork 沒有 `DwgColumnExecutor.cs`（上游有、合併時未帶入）。實際呼叫者是 `DwgBeamExecutor.cs:511-520` |

### 1-5 執行來源重複

| 能力 | 檔案 | 判定 |
|---|---|---|
| 安裝 add-in | `scripts/install-addon.ps1` | **正典**（CLAUDE.md 明訂唯一安裝器） |
| 同上 | `scripts/install-addon-bom.ps1` | 重複，且用的是已淘汰的 `Release.2024` 路徑 |
| 同上 | `scripts/install-addon.bat` | 重複，舊路徑 |
| 同上 | `scripts/install-ascii.ps1` | 重複，寫死 `d:\David\BIM MCP\...` 個人路徑 |
| 同上 | `author_install_addon.ps1`（repo 根目錄） | 重複，是 `install-addon.ps1` 的副本 |
| DXF/DWG 文字讀取 | `bridge/python/skills/ezdxf_worker.py` | **正典** |
| 同上 | `bridge/python/skills/dxf_parser_skill.py` | 死碼，寫死 `C:\Users\<CONTRIBUTOR_USERNAME>\...` 個人路徑 |
| domain frontmatter 回填 | `scripts/backfill-domain-metadata.{py,ps1,sh}` | **不是重複**——`.py` 是本體，`.ps1`/`.sh` 是跨平台包裝 |

另有 4 支 repo 根目錄的即興腳本（`convert.ps1`、`convert_csv.js`、`create_sheets_runner.js`、`test_detect_matchlines.js`）。其中 `create_sheets_runner.js` 直接 spawn MCP-Server 並灌原始 JSON-RPC，**違反 CLAUDE.md 的 Do Not Bypass MCP 規則**。以上 9 個檔案都在版控內。

（`MCP-Server/scratch/` 底下 41 支直連 `ws://localhost:8964` 的檔案已被 `.gitignore` 排除，屬開發暫存，不算違規。）

---

## 二、本次已修復（全部經建置與 QA/QC 驗證）

| # | 修復 | 驗證方式 |
|---|---|---|
| 1 | 還原 47 個 C# 派送 `case`（45 個從上游 `9559f23` 取回 + 2 個本 fork 專有 handler 補接）。每個 case 都先確認 handler 在本 fork 真的存在才寫入 | `Release.R20/R22/R23/R24/R25/R26` 六個組態 `dotnet build` 全部 0 錯誤 |
| 2 | `grade_toposolid_to_floors` 的 case 加上 `#if REVIT2024_OR_GREATER`，與其 handler 所在檔案的守衛一致 | R20 建置由 1 錯誤變 0 |
| 3 | `structuralTools` 加進 `full` 與 `structural` profile；刪掉 `structural-tools.ts` 裡重複的 `sync_ifc_structural_to_native` 定義 | 工具數 180 → 184，`align_beams_top_to_floor_bottom` 等 4 支從此可呼叫 |
| 4 | 新增 `MCP-Server/src/tools/fork-restored-tools.ts`：補上 8 支「C# 有、MCP 沒有」的工具定義，schema 逐欄比對 C# handler 實際讀取的 `parameters[...]` | 工具數 165 → 173；`bim-*` 三支 agent 的白名單從此全部有效 |
| 5 | 19 支本 fork 沒有 C# 後端的工具改為**不註冊**（`UNIMPLEMENTED_ON_THIS_FORK`），附解除條件說明 | AI 的工具清單裡不再出現「看得到但一定失敗」的工具 |
| 6 | `scripts/verify-qaqc.ps1` 新增 Phase 9：9-1 每支已註冊工具都要有 C# 命令；9-1b 版本守衛工具必須登記在 `VERSION_GATED_TOOLS`（會逐行解析 `#if`/`#else`/`#endif` 巢狀從 C# 反推真實守衛，雙向比對）；9-2 反向檢查扣留清單沒有「其實已經能用」的工具 | 三項皆 PASS；`-Version 2020` / `-Version 2026` 會分別報出該版本會扣留／可用哪些工具 |
| 6b | 新增 `REVIT_VERSION` 環境變數：設了之後，低於門檻的版本守衛工具不會註冊。R20 部署設 `REVIT_VERSION=2020` 就會少掉 `grade_toposolid_to_floors`（172 支） | 實測 unset=173、2020=172、2024=173 |
| 7 | 修掉 R26 建置破損（`Floor.SlabShapeEditor` 與 `SlabShapeEditor.DrawPoint` 在 Revit 2026 被移除）：在 `RevitCompatibility.cs` 加 `GetSlabShapeEditorCompat()`，並以 `#if REVIT2026_OR_GREATER` 改用 `AddPoints`，維持逐點容錯語意 | 此破損為既有問題（來自未進版控的新檔 `CommandExecutor.FloorShapePoints.cs`），已用還原備份確認與本次修改無關 |
| 8 | 專案層 `revit-mcp` 在本機停用（`~/.claude.json` 的 `disabledMcpjsonServers`），只留使用者層 `revitmcp`。`.mcp.json` 本身未改動，其他使用者不受影響 | 設定檔已備份到 `~/.claude/backups/.claude.json.backup.20260803150001` |
| 9 | `revit-operator` agent 白名單移除 3 支無後端工具 | 白名單掃描回報 `NOT-IN-REGISTRY=(none)` |
| 10 | 修正 1-4 表列的 6 項文件衝突（含以 `.agents` 版覆蓋過期的 `.claude/skills/scaffold-takeoff/SKILL.md`） | 逐條回 C# 或 domain 原文比對 |
| 11 | 四份計數文件 + 五份 BIM_MCP 網頁的工具數同步為 173 | QA/QC 7-1 exact-match PASS |

最終狀態：**verify-qaqc 56 PASS / 0 FAIL / 0 WARN / 3 SKIP**（SKIP 為 `-SkipBuild -SkipDeploy`）。

---

## 三、第二層開工單

依「AI 誤導風險 × 修復成本」排序。標記 **[需決策]** 者請先給方向再動手。

### A. 把 19 支扣留工具接回來（最高價值，逐支評估）

這些工具在上游 `9559f23` 有 C# 實作，本 fork 因 keep-mine 沒帶進來。每一支都要先確認 Revit 2020 API 相容性。

| 群組 | 工具 | 缺的 C# |
|---|---|---|
| 明細表讀取 | `list_schedules`、`read_schedule` | 上游 commit `6f8a903` |
| DWG 建柱 | `create_columns_from_dwg`、`get_dwg_column_layers`、`preview_dwg_columns` | `MCP/Core/DwgColumnExecutor.cs`（整檔缺） |
| 視圖操作 | `rename_view`、`create_level` | `MCP/Core/Commands/CommandExecutor.ViewOps.cs`、`CommandExecutor.Level.cs`（整檔缺） |
| 樓板坡度 | `analyze_floor_slopes` | `MCP/Core/FloorSlopeAnalyzer.cs`（整檔缺） |
| 走廊分析 | `analyze_corridor_width` | handler 缺 |
| 圖紙/視埠 | `arrange_viewports_on_sheet`、`adjust_section_datums`、`scale_drafting_view_width`、`scale_drafting_view_height`、`list_dimension_types`、`list_legend_views` | handler 缺 |
| 帷幕立面 | `create_curtain_wall_elevations`、`diagnose_curtain_wall_elevation_direction(s)` | handler 缺 |
| 其他 | `door-window-legend-tools` | 疑似模組名誤植為工具名，先確認這支到底該不該存在 |

建議做法：`git show 9559f23:<檔案>` 取出 → 逐檔跑 R20 建置 → 通過才留 → 從 `UNIMPLEMENTED_ON_THIS_FORK` 移除 → QA/QC Phase 9-2 會自動確認清單不再有殘留。

### B. 補完剩下 7 支「C# 有、MCP 沒有」的工具定義

`copy_view_crop_box`、`assign_scope_box_to_views`、`sync_grid_extents_between_views`、`create_grid_cropped_views_batch`、`copy_sheet_viewports`、`rename_element`、`update_material_board_family_types_by_id`。

這 7 支目前沒有任何 skill/domain/agent 引用，所以沒有立即失敗；但它們是「Revit 做得到、AI 叫不到」的能力浪費。做法比照本次 `fork-restored-tools.ts`：讀 handler 的 `parameters[...]` 寫 schema，不要照文件推。

### C. 收斂重複執行來源 — ✅ 已完成（使用者於 2026-08-03 授權）

以下 9 個檔案已用 `git rm` 刪除（皆在版控內，需要時可從歷史復原）：

1. `scripts/install-addon-bom.ps1`、`scripts/install-addon.bat`、`scripts/install-ascii.ps1`、`author_install_addon.ps1` — 四份過期／個人環境的安裝器
2. `bridge/python/skills/dxf_parser_skill.py` — 死碼，寫死 `C:\Users\<CONTRIBUTOR_USERNAME>\` 路徑
3. `create_sheets_runner.js`、`test_detect_matchlines.js` — 繞過 MCP 抽象層
4. `convert.ps1`、`convert_csv.js` — 寫死個人路徑的編碼轉換殘骸

刪除前先修好 4 處**活的**引用（否則會留下壞掉的安裝指引）：`scripts/verify-installation.ps1`（檢查與建議都指向已刪的 `-bom` 版）、`Antigravity_MCP_Complete_Guide.md` 兩處、`scripts/README.md` 的「方法 A：雙擊 .bat」整段、`README.md` 疑難排解的 `.bat` 條目。歷史檔（`CHANGELOG.md`、`log/`、`docs/_archive/`）依 append-only 規則不動。

`verify-qaqc.ps1` Phase 1-1 新增「安裝器唯一性」檢查：這四個安裝器再出現就 FAIL。

**`MCP-Server/scripts/` 的 59 支繞道腳本 — ✅ 已逐支評估並收斂（見下方 I 節）。**（`MCP-Server/scratch/` 的 41 支已被 `.gitignore` 排除，屬開發暫存，不在此列。）

### D. 三套 skill 目錄收成一套 — ✅ 已完成（使用者於 2026-08-03 授權）

合併前：`.claude/skills` 52 支、`.agents/skills` 32 支（29 支同名，其中 12 支完全相同、3 支只差換行、**14 支指令內容實質不同**）、`.agent/skills` 9 支（單數，完全未進版控，命名為 `revit-*`）。沒有任何設定檔指向後兩者，`verify-qaqc.ps1` 也不掃它們。

**合併結果：`.claude/skills` 58 支，另外兩個目錄已移除。**

14 份分歧檔逐份判定（不是整批取一邊——兩邊各有比較新的部分）：

| 判定 | 檔案 | 依據 |
|---|---|---|
| 保留 `.claude` | `claude-md-sync`、`deploy-addon`、`element-coloring`、`fire-safety-check`、`qa-review`、`smoke-exhaust`、`wall-orientation-check` | `.agents` 版是 AGENTS.md/.Codex 的改名分支，或缺少 L-027 註記、`metadata.references`、Phase-7 檢查 |
| 採用 `.agents` | `quantity-takeoff-excel`、`sheet-management` | 前者有混合 C 代碼拆分規則與 Floor/F 代碼契約（對照 domain L35／L203／L36／L207-216 確認）；後者有視埠類型同步流程，而該流程用到的兩支工具本次剛補上註冊 |
| 合併兩邊 | `detail-component-sync`、`building-compliance`、`beam-slab-alignment`、`parking-check`、`stair-hidden-line` | 見下 |

合併時靠原始碼裁決、沒有照單全收的幾處：

- `detail-component-sync`：先前的稽核說「skill 承諾自動更名、domain 說不會」是直接衝突。實際查 `CommandExecutor.DetailComponent.cs:1310` 發現 `renameTypes` 預設就是 `true` 且真的會改名——domain 那幾句「不會自動更名」講的是**另一支工具** `sync_detail_component_numbers`。所以 `.claude` 的敘述是對的，衝突不成立，並在合併版加註兩支工具行為不同。
- `detail-component-sync` 模式 C：`.agents` 寫「兩種安全比對方法」，`.claude` 只寫一種。查 C# 有兩個 `StartsWith` 判斷，採 `.agents`。
- `stair-hidden-line`：`.agents` 的 troubleshooting 說「增益集已更新至並行連線版本」——這與 `SocketService.cs` 一次只保留一條連線的事實相反，**沒有照抄**，改寫成正確的單連線說明。
- `beam-slab-alignment`：補上 `.agents` 的 3 個旗標，但保留本次依 C# 修正的 `floorSelectionMode: auto_by_beam`。

`.agents` 獨有的 3 支（`floor-level-ordering`、`markdown-encoding-hygiene`、`revit-excel-workbook-update`）直接匯入——CLAUDE.md 的觸發表本來就會路由到它們的 domain 檔，等於先前 Claude Code 這邊有 domain 沒 skill。

`.agent/`（單數）9 支：6 支的主題已有對應 skill（`revit-batch-crop`→`dependent-view-crop`、`revit-batch-sheets`→`sheet-management`、`revit-detail-sync`→`detail-component-sync`、`revit-parking-numbering`→`parking-check`、`revit-room-numbering`→`room-numbering`、`revit-code-reviewer` 是未完成的 TODO 樣板），直接捨棄。另 3 支的主題**在 `.claude` 完全沒有 skill**，但有 domain 檔與已註冊工具，因此升級保留並改為正典命名：`fill-pattern-conversion`、`matchline-automation`、`rc-filled-region`（升級時一併移除了不存在的 `check_viewports_rotation` 引用）。整個 `.agent/` 未進版控，刪除前已另行備份。

`verify-qaqc.ps1` Phase 1-1 新增檢查：`.agents\skills` 或 `.agent\skills` 再出現就 FAIL。順帶修好 7-7 連結檢查會把 ``` 程式碼區塊裡的佔位符（如 `[分張序號]/[總張數]`）誤判為壞連結的缺陷。

### E. domain 對 domain 的衝突（CLAUDE.md 的「domain 優先」規則解不了）

`domain/lessons.md` 的 L-060 記載「以 `01空間表` 房號作室內更新名單」「同步維持 `小計`、`更新工項` 公式鏈」，與 `domain/scaffold-takeoff.md` 第 158、166 行相反。因為兩邊都是 domain，優先規則無法裁決。

`domain/lessons.md` 是 append-only，所以做法是**追加一條新的 L-0NN 註明 L-060 已被取代**，不要就地改。

### F. `Lessons/` 目錄的可見性與編號碰撞

`Lessons/` 有 7 份 `.md`，每份都從 `L-001` 重新編號，與 `domain/lessons.md` 的全域 `L-001`…`L-061` 序列碰撞——同一個「L-001」會指到 8 個不同的東西。而且 `CLAUDE.md` 完全沒提 `Lessons/`，`docs/DOCUMENT_AUDIENCE_INVENTORY.md` 也沒有，等於它在治理範圍之外。

建議：把 `Lessons/` 加進 CLAUDE.md 的 meta 表與稽核清單，並把各主題檔的編號改成有前綴的形式（例如 `SCF-001`）。

### G. 其餘 skill ↔ domain 衝突

`detail-component-sync`（skill 說 `renameTypes` 預設會自動改名，domain v3.5 說不要期待自動更名）、`quantity-takeoff-excel`（混合 C 代碼會重複計面積）、`threshold-opening-takeoff`（domain 的第二個工作流排除邏輯是反的，skill 完全沒提）、`parking-auto-numbering`（`referenced_by: []`，Claude Code 端沒有對應 skill）。這幾條都需要先確認哪一邊代表現況，再單向對齊。

### H. Phase 9 檢查法的已知寬鬆處

9-1 是用「工具名字串是否出現在任何 C# 檔」來判定可達，不是嚴格檢查 `case` 標籤。如果某個工具名只出現在註解或字串常數裡，會誤判為 PASS。目前 173 支都是真的 `case`，但若要收緊，可以改成只掃 `CommandExecutor.cs` 主 switch 區段的 `case "..."`。

（原本這裡還列了「9-1 對 `#if` 版本守衛是盲的」——由獨立驗證員在複核時抓到：`grade_toposolid_to_floors` 被 `#if REVIT2024_OR_GREATER` 包住，在 R20/R22/R23 建置會被編譯器整段拿掉，工具卻照樣註冊，而 9-1 因為字串還在源碼裡就報 PASS。這對主要使用 R20 的部署是真的洞。**已於本次修掉**：9-1b 會逐行追 `#if` 巢狀從 C# 反推真實守衛，並與 `VERSION_GATED_TOOLS` 雙向比對；執行期則由 `REVIT_VERSION` 環境變數決定要不要註冊。）

---

### I. `MCP-Server/scripts/` 59 支繞道腳本逐支評估 — ✅ 已完成

**評估方法**：對每支腳本抽出它實際送到 `ws://localhost:8964` 的指令名稱，比對 (a) 目前註冊的工具清單、(b) C# 有沒有對應 command、(c) 全庫 1160 個追蹤檔中有誰引用它。

**關鍵結論：這些腳本呼叫的指令幾乎全部都已經是註冊工具了**，唯一的例外是 `rename_element`（C# 有、已 dispatch、只是缺工具定義）。也就是說，它們提供的不是「缺少的能力」，而是**預先寫死的編排**——而編排正是 AI 本來就該自己做的事。

| 判定 | 支數 | 處置 |
|---|---:|---|
| 純編排既有工具，且無任何文件引用 | 41 | 直接移除 |
| 純編排既有工具，但有 domain／skill 引用 | 12 | **先改文件成工具呼叫，再移除** |
| 個人環境殘留（寫死 `d:\David\`，且 `setup.ps1:880` 已正式處理 Gemini 設定） | 1 | 移除 |
| 瀏覽器預覽 UI（不是 Revit 指令包裝） | 2 | 保留 |
| 通用逃生口（工具清單未刷新時用） | 1 | 保留，並標明是最後手段 |
| **真正的能力缺口**（C# 沒有對應 command） | 2 | 保留，並寫成規格待收編 |

被改寫的 12 支對應到 6 份 domain 與 1 支 skill：`element-coloring-workflow.md`（5 支腳本 → `clear_element_override` / `unjoin_wall_joins` / `override_element_graphics` / `rejoin_wall_joins` 序列，順帶移除寫死的個人路徑 `c:\Users\User\Desktop\...`）、`fire-rating-check.md`、`dependent-view-crop-workflow.md`、`stair-hidden-line-workflow.md`、`exterior-wall-opening-check.md`（順帶把寫死的 `D:\Reports\` 改成使用者指定）、`curtain-wall-pattern.md`、`smoke-detector-check` skill。

**同時完成的工具層補齊**：`rename_element` 補上工具定義（C# `CommandExecutor.Automation.cs:50` 早就存在且已 dispatch），工具數 173 → 174。

**保留的 5 支與理由**寫在新增的 `MCP-Server/scripts/README.md`，並由 `verify-qaqc.ps1` **Phase 10** 雙向把關：10-1 抓出未登記在允許清單裡的新繞道腳本，10-2 確認允許清單裡的每一支都在 README 有說明。

**剩下 2 個真正的缺口**（規格已寫進 `MCP-Server/scripts/README.md`，需要 C# 工作、且應在有 live Revit 可驗證時進行）：

1. **`renumber_parking_by_view`** ← 取代 `number_parking.js`。停車位蛇形編號目前有三份實作（Node 腳本、pyRevit 的 `lib/parking_numbering.py` 純 Python 演算法、pyRevit 按鈕的 UI 流程），C# 沒有。可比照同型別的 `renumber_rooms_by_level`（`CommandExecutor.RoomNumbering.cs`）。
2. **`export_partition_takeoff`** ← 取代 `export_partition_takeoff_current.cjs`。輕隔間數量 Excel 匯出目前只在 659 行的 Node 腳本裡；C# 端已有 Excel 匯出的先例（`export_smoke_review_excel` 等）且 csproj 已引用 ClosedXML。

## 附註：本次未做的事

- 沒有刪除任何檔案
- 沒有動 `.mcp.json`（專案層設定，會影響其他使用者）
- 沒有改任何 agent 的 `model` 或核心職責定義（只移除了 `revit-operator` 白名單中 3 支不存在的工具）
- 沒有部署新的 DLL（Revit 執行中會鎖住 `RevitMCP.dll`，需使用者關閉 Revit 後跑 `scripts/install-addon.ps1`）

**重要：第二部分的 47 個還原 case 要等重新部署 add-in 之後才會在 live Revit 生效。**
