# MCP 巨集 Excel 系列 — 上游知識貢獻草案

目標 repo：`shuotao/REVIT_MCP_study`
狀態：**草案，尚未提 PR**（依 `hj-pr-proposal` 紀律，等作者確認後才進入 fork → push → PR）
盤點日期：2026-08-05

---

## 1. 為什麼要特別小心（issue #87 的教訓）

上游 [issue #87](https://github.com/shuotao/REVIT_MCP_study/issues/87) 的根因是：
**貢獻的 domain SOP 引用了 9 個 helper 方法，但這些方法在 fork 的任何分支都找不到定義**
（只有被呼叫、沒有本體）。維護者為了讓程式能編譯，只好依「呼叫點合約 + repo 既有同族程式 + domain 規格」
逐一**重建**，其中 `TrySetColumnTopAttachment` 的目標參數名是用猜的、
`CollectGeometryFloorBottomHitsAtPoint` 因測試模型偵測不到柱而無法 runtime 驗證。

> 該 issue 後續已由本 fork 的 `fix/issue-87-ifc-helper-reconcile` 分支修正並 cherry-pick 進上游（PR #101）結案，
> 但**成因必須避免重演**。

**成因的一般化**：知識層（domain / skill）描述的方法，引用了只存在於本機／fork 的實作。
維護者讀到文件裡的名字，會合理假設那是 repo 內可呼叫的東西。

**本次的風險比 #87 更高**：這 14 個 Excel 按鈕裡有 12 個是**純 pyRevit 實作**，
程式碼在 `MCP_Macros.tab` 與 `lib/*.py`，而上游 `pyRevit_Tools/` 只有 2 個檔案
（`MCP_Schedules.tab/.../CreateSchedules.pushbutton/script.py` 與 `README.md`）——
**整個 `MCP_Macros.tab` 在上游不存在**。若照搬本地文件，會一次引入十幾個不存在的模組名。

**本草案採取的防護**（見第 4 節驗證結果）：

1. 移除所有指向 fork-only 路徑的參照（`pyRevit_Tools/...`、`lib/*.py`、`tests/test_*`、`.pushbutton`）。
2. 每份 domain 加入「**實作可達性**」表格，明確寫出哪一段有 MCP 工具、哪一段**沒有**。
3. `related:` frontmatter 只指向「上游已有」或「本 PR 一起提交」的檔案，不留懸空連結。
4. 上游沒有 `Lessons/` 目錄，經驗一律折進 `domain/lessons.md`（append-only）。

---

## 2. 14 個 Excel 按鈕的知識層對應

| # | 按鈕（面板） | 對應 domain | 上游狀態 | 本次處理 |
|---|---|---|---|---|
| 1 | 釋疑 Excel（Revision） | — | 依賴 `export_revision_excel`，**上游 TS/C# 皆無** | ❌ 不納入，見第 5 節 |
| 2 | 踢腳 Excel（Takeoff） | `quantity-takeoff-excel.md` | v1.0 已在上游 | 🔄 升級 v1.1 |
| 3 | 天花 Excel | `quantity-takeoff-excel.md` | v1.0 已在上游 | 🔄 升級 v1.1（新增天花材料／跨房裁切規則） |
| 4 | 門窗表 Excel | `quantity-takeoff-excel.md` | **上游完全沒有此段** | 🔄 升級 v1.1（新增「門窗數量回填」整節） |
| 5 | 地坪 Excel | `quantity-takeoff-excel.md` | v1.0 已在上游 | 🔄 升級 v1.1（新增多代碼＝施工層規則） |
| 6 | 內牆粉刷 Excel | `quantity-takeoff-excel.md` | v1.0 已在上游 | 🔄 升級 v1.1 |
| 7 | 機房門檻 Excel | `threshold-opening-takeoff.md` | 已在上游 | ⏸ 本地有改良（+76/-4），列為後續 PR |
| 8 | 停車位 Excel | `revit-excel-workbook-update.md` | **上游無** | ✅ 新增 |
| 9 | 輕隔間 Excel | `revit-partition-takeoff.md` | 已在上游 | ⏸ 本地有改良（+30/-9），列為後續 PR |
| 10 | RC 體積 Excel | `quantity-takeoff-excel.md` | **上游無此段** | 🔄 升級 v1.1（新增 RC 體積 QA 段） |
| 11 | 室外施工架 Excel | `scaffold-takeoff.md` | 已在上游 | ⏸ 本地有改良（+83/-10），列為後續 PR |
| 12 | 室內施工架 Excel | `scaffold-takeoff.md` | 已在上游 | ⏸ 同上 |
| 13 | 空間表 Excel | `room-space-table-sync.md` | **上游無** | ✅ 新增 |
| 14 | 高隔間分析 Excel | `tall-partition-index-workflow.md` | 已在上游 | ⏸ 本地有改良（+27/-2），列為後續 PR |

跨按鈕共用（不綁單一按鈕，但 14 個都會用到）：

| domain | 上游狀態 | 本次處理 |
|---|---|---|
| `revit-excel-workbook-update.md` — 更新既有活頁簿的安全契約 | **上游無** | ✅ 新增 |
| `floor-level-ordering.md` — 樓層正規化與排序通則 | **上游無** | ✅ 新增 |
| `user-specified-runtime-parameters.md` — 檔名／門檻值不得寫死 | **上游無** | ✅ 新增（`room-space-table-sync.md` 會引用它，不一起提會留懸空連結） |

---

## 3. 本草案的檔案清單

```text
domain/revit-excel-workbook-update.md          新增
domain/room-space-table-sync.md                新增
domain/floor-level-ordering.md                 新增
domain/user-specified-runtime-parameters.md    新增
domain/quantity-takeoff-excel.md               更新 v1.0 → v1.1（136 行 → 313 行）
domain/lessons.md                              append L-031 ~ L-037（見 lessons-append.md）
.claude/skills/revit-excel-workbook-update/    新增（含 references/excel-update-subagent.md）
.claude/skills/floor-level-ordering/           新增（含 agents/openai.yaml）
```

`skills/` 目錄在本草案中平放，實際提交時需放回 `.claude/skills/<name>/SKILL.md`。
上游已有 `quantity-takeoff-excel/agents/openai.yaml`、`scaffold-takeoff/agents/openai.yaml`，
故 `agents/` 與 `references/` 附屬檔案符合既有慣例。

---

## 4. 工具可達性驗證結果（#87 防護）

驗證方法：從上游 `main` 抽出全部工具註冊名（`MCP-Server/src/tools/*.ts`，162 個）
與 C# dispatch case（`MCP/Core/**/*.cs`，198 個），再比對本草案每份文件引用的識別字。

**引用到的 MCP 工具，全部在上游存在且 TS + C# 皆齊全：**

| 工具 | 上游 TS 註冊 | 上游 C# handler |
|---|:--:|:--:|
| `calculate_room_scaffold_perimeters` | ✅ | ✅ |
| `get_all_sheets` | ✅ | ✅ |

**明確標記為「上游沒有對應工具」的能力**（已寫進各 domain 的「實作可達性」段落，不假裝存在）：

- 寫入／就地更新既有 Excel 活頁簿 — 無 MCP 工具，需外部腳本（Excel COM）。
- 釋疑 Excel 匯出（`export_revision_excel`）— 上游 TS 與 C# 皆無此工具。

**殘留 fork-only 參照**：0。移除的包含兩類——路徑參照（`pyRevit_Tools/...`、`lib/*.py`、`tests/test_*`）
與**裸按鈕識別字**（`PartitionTakeoff`、`RcVolumeExcel`、`DoorWindowExcel` 等）。
後者容易漏掉：它不含路徑符號，grep 路徑樣式抓不到，但維護者一樣會拿去搜尋然後找不到——
與 #87 的失敗模式相同。原本的「現有實作入口」表已改寫為「涵蓋的數量類型」，
描述計算方法而非點名不存在的按鈕。

**懸空 `related:` 連結**：0（14 個被引用的檔案全部落在「上游已有」或「本 PR 內」）。

> 順帶回報給維護者（非本 PR 範圍，屬 code）：上游 `remap_room_finish_codes` 與
> `sync_room_ceiling_finish_from_ceilings` 在 `MCP-Server/src/tools/room-tools.ts` 有註冊，
> 但 `MCP/` 內找不到對應的 C# dispatch case。若屬實，這兩個工具會是「叫得到但只會拋錯」的狀態。
> 建議另開 Issue 確認，不要夾在知識層 PR 裡。

---

## 5. 「能不能轉化為 RevitMCP 所用」

分兩層回答：

**知識層 — 可以，就是本草案。** 這些流程的判斷規則（邊界怎麼取、開口怎麼扣、
淨高證據順序、活頁簿寫入契約、樓層排序）與執行層無關，換成 MCP 工具鏈一樣成立。
取數那一半（房間、明細表、幾何）上游既有工具已經走得通。

**工具層 — 不能走 fork PR。** 上游 `CONTRIBUTING.md` 明定：
fork PR 僅限知識貢獻（`domain/` + skills），程式碼由維護者管理，
「如果您有程式碼相關的建議，請開 Issue 討論，不要直接提交程式碼 PR」。

因此以下三件事**應該開 Issue、不應塞進 PR**：

1. 把「更新既有 Excel 活頁簿」工具化成 Revit 端命令 + MCP 工具（這是 14 個按鈕共用的缺口）。
2. `export_revision_excel` 是否要進上游。
3. 上述兩個「有 TS 註冊但查不到 C# handler」的工具。

這正是 #87 留下的分工線：**知識走 PR，實作走 Issue**——文件不要替不存在的實作背書。

---

## 6. 建議的提交方式

建議拆兩批，降低 review 難度：

- **第一批（本草案）**：4 個新 domain + `quantity-takeoff-excel.md` v1.1 + 2 個新 skill + lessons L-031~L-037。
  彼此有 `related` 依賴，適合一起提。
  - branch：`add/excel-takeoff-knowledge`
  - 標題：`[Domain] 新增 Excel 數量計算知識層（活頁簿更新契約／空間表同步／樓層排序）`
- **第二批（後續）**：5 個既有上游 domain 的改良差異
  （`threshold-opening-takeoff` / `revit-partition-takeoff` / `scaffold-takeoff` / `tall-partition-index-workflow` / `parking-space-review`）。
  - 這批是「改既有檔」，與第一批的「加新檔」混在一起會讓 diff 難讀。

## 7. 提 PR 前仍需確認的事

1. **`lessons-append.md` 的編號**：本次盤點時上游最後一條是 `[L-030]`。開 PR 前需重新確認，若上游已新增條目要順延。
2. **第一批 / 第二批要不要合併**：若作者偏好一次收完，可合併，但 diff 會明顯變大。
3. **`user-specified-runtime-parameters.md` 是否納入**：它偏「文件撰寫規範」而非 BIM SOP，
   但 `room-space-table-sync.md` 會引用它。若作者不想收，需改寫該引用而非留懸空連結。
4. ~~案例數字的揭露程度~~ — **已處理**。所有真實專案識別資訊已改為假設性舉例：
   房號（`F101`→`R-101` 等）、門窗型號（`D3-180x220`→`D2-160x210`、`SD10-…`→`SD1-…`）、
   TypeMark／族群編號、連結模型車位編號（`611`/`682`→`701`/`702`）、
   分頁名（`01空間表`→`空間表`、`施工架計算`→`數量明細`、`其他面積`→`面積彙總表`）、
   棟別代碼（`D-1F`→`B-1F`）、面積數值（`155.614`→`150.00`）。
   「實測／本案／本專案」等宣稱已改為假設語氣或移除，驗證統計改為不帶具體筆數的描述。
   保留的是計算方法與失敗模式本身——每個案例的教學重點都沒有被削弱。
5. **本地 `main` 落後上游 92 個 commit**：提 PR 前應先同步，避免基於過期基準產生假衝突。
