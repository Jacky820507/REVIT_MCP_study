# pyRevit_Tools — Revit 內建按鈕擴充（pyRevit extension）

本資料夾與專案主系統的關係是「**並列、互補、非取代**」。獨立於 `scripts/` 與 `MCP/` 而存在，原因如下。

## 兩個 Tab、兩種實作路線

| Tab | 實作路線 | 依賴 |
|-----|---------|------|
| `MCP_Schedules.tab` | **純 Python**：直接呼叫 `Autodesk.Revit.DB` API | 只需 pyRevit |
| `MCP_Macros.tab`（MCP 巨集 🦞） | **DLL 橋接**：透過 `lib/mcp_bridge.py` 直呼已載入的 `RevitMCP.dll` 的 `CommandExecutor` | pyRevit + RevitMCP add-in 已安裝 |

### DLL 橋接原理（`lib/mcp_bridge.py`）

pyRevit 腳本跑在 Revit 行程內的 UI 執行緒（API context），可以直接建構
`RevitMCP.Core.CommandExecutor` 並呼叫 `ExecuteCommand`——與 AI 對話走的是
**同一套 C# 演算法**：

- **零重寫**：降樑貼齊、IFC 同步等大型演算法不用翻成 Python
- **不經 WebSocket**：不佔用 8964 連線，MCP 服務未啟動也能用
- **同步演進**：C# command 修好 bug，按鈕自動受益

```python
import mcp_bridge as mcp
data = mcp.run('renumber_rooms_by_level',
               {'level': '2FL', 'startNumber': '201', 'dryRun': True})
```

## MCP 巨集按鈕清單（14 顆）

| Panel | 按鈕 | 後端命令 | UI 形式 |
|-------|------|----------|---------|
| 結構 | 降樑貼齊 | `align_beams_top_to_floor_bottom` | dry-run→確認→套用 |
| 結構 | 柱頂貼齊 | `align_columns_top_to_floor_bottom` | dry-run→確認→套用 |
| 結構 | IFC結構同步 | `get_linked_models` + `sync_ifc_structural_to_native` | 選連結模型→dry-run→套用 |
| 編號 | 房間編號 | `get_all_levels` + `renumber_rooms_by_level` | 選樓層＋起始編號→dry-run→套用 |
| 編號 | 圖紙重編號 | `auto_renumber_sheets`（支援 dryRun） | dry-run 預覽→套用 |
| 編號 | 詳圖編號同步 | `sync_detail_component_numbers` | 確認→執行 |
| 算量 | 高隔間分析 | `analyze_tall_partition_rooms` | 一鍵＋輸出視窗報告 |
| 算量 | 室內施工架 | `calculate_room_scaffold_perimeters` | 一鍵＋輸出視窗報告 |
| 算量 | 室外施工架 | `calculate_exterior_wall_scaffold_perimeter` | 一鍵＋輸出視窗報告 |
| 檢核 | 防火上色 | `query_elements` + 批次 `override_element_graphics` | 輸入參數名→批次上色＋分布統計 |
| 檢核 | 碰撞偵測 | `detect_clashes` + `colorize_clashes` + `export_clash_report` | 偵測→選擇性上色→選擇性匯出 CSV |
| 視覺化 | 清除上色 | `clear_element_override` | 清除所選元素的覆寫 |
| 視覺化 | 樓梯隱藏線 | `trace_stair_geometry` + `create_detail_lines` | 剖面一鍵＋選線型 |
| 視覺化 | 關於 🦞 | — | 系統說明（含龍蝦） |

> 輕隔間 CSV 算量（`export_partition_takeoff_current.cjs`）主流程在 Node 腳本，
> 仍走 MCP 工作流；按鈕版以「高隔間分析」提供 C# 端的同域功能。

## 為什麼獨立在 root（不是 `scripts/`、不是 `MCP/`）

| 候選位置 | 為什麼不適合 |
|---------|------------|
| `scripts/` | 是 Add-in **安裝/部署 PowerShell/Bash 腳本**（build、deploy、port release）。pyRevit pushbutton 是「Revit 內 user-facing 按鈕」，執行環境與用戶完全不同 |
| `MCP/` | 是 **C# .NET Revit Add-in 源碼**（單一 `RevitMCP.csproj` 多版本 build）。pyRevit 用 Python+IronPython，技術棧不一致 |
| **root**（現狀）| pyRevit 載入 extension 用「user folder symlink → 此目錄」的標準慣例。`.extension/.tab/.panel/.pushbutton` 是 pyRevit 強制目錄結構，搬位置會破壞 pyRevit 發現邏輯 |

## 與 MCP 主系統的關係

- **非 MCP tools**：本目錄的功能 *不是* 透過 `MCP-Server/src/tools/` 開放給 AI Client 的 tool。Claude / Gemini 看不到、也叫不到它
- **MCP 巨集 = 同後端的人工入口**：AI 走「stdio → MCP Server → WebSocket → CommandExecutor」，按鈕走「pyRevit → DLL 橋接 → CommandExecutor」，殊途同歸
- **備援**：當 MCP Server 沒開（離線、不想開 AI），設計師仍可用按鈕跑同一套演算法
- **被 domain 文件引用**：`domain/dependent-view-crop-workflow.md` 提到「AI 可參考此程式碼邏輯，引導使用者自行建立 Python 腳本」

## 部署方式

pyRevit 標準作法（使用者一次性設定）：

1. 安裝 pyRevit（<https://github.com/eirannejad/pyRevit>）
2. pyRevit CLI：`pyrevit extend ui MCP_Tools <絕對路徑>/pyRevit_Tools/MCP_Tools.extension`
   - 已安裝過的話：pyRevit 設定 → Reload，或 `pyrevit extensions update MCP_Tools`
3. 重啟 Revit，會看到「MCP_Schedules」與「MCP_Macros」兩個 tab
4. `MCP_Macros` 需要 RevitMCP add-in 已安裝（`scripts/install-addon.ps1`）；
   未安裝時按鈕會跳出安裝指引，不會靜默失敗

## 測試 Checklist（首次部署後逐顆點檢）

- [ ] 關於 🦞 — 彈出說明視窗（不需 add-in，驗證 extension 載入）
- [ ] 房間編號 — 選樓層→起始編號→dry-run 清單正確→套用後房間編號更新
- [ ] 圖紙重編號 — dry-run 顯示 PlannedMoves；無 `-1` 圖紙時顯示「沒有發現」
- [ ] 降樑貼齊 / 柱頂貼齊 — dry-run 統計合理→套用
- [ ] IFC結構同步 — 列出連結模型；無連結模型時提示
- [ ] 高隔間分析 / 室內外施工架 — 輸出視窗出現報告
- [ ] 防火上色 — 輸入參數名→牆依時效上色、alert 顯示分布
- [ ] 碰撞偵測 — 偵測→上色→匯出 CSV
- [ ] 清除上色 — 選取元素後清除；未選取時提示
- [ ] 樓梯隱藏線 — 剖面視圖中畫出虛線；非剖面視圖時提示

## 維護

- 新增更多 pushbutton：依 pyRevit `.tab/.panel/.pushbutton/script.py` 慣例擴充；
  用 `mcp_bridge.run(command, params)` 呼叫任何 `CommandExecutor` 已有的 case
- 寫入型命令一律走 `mcp_bridge.dry_run_then_apply()` 的「預覽→確認→套用」模式
- 若功能成熟到值得整合進 MCP tools，再決定是否包成對應 tool 並寫 C# command
