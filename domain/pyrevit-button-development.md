---
name: pyrevit-button-development
description: "pyRevit MCP 巨集按鈕開發 SOP：建立 .pushbutton 時避免 ribbon 載入失敗、availability context 錯誤、IronPython 相容問題、compiled DLL cache 過期（新增/刪除/改名按鈕觸發），並以 script.py 內部檢查取代脆弱的 bundle context。"
metadata:
  version: "1.1"
  updated: "2026-07-28"
  created: "2026-07-24"
  contributors:
    - "Codex"
    - "Jacky820507"
  references:
    - "pyRevit_Tools/README.md"
  related:
    - parking-auto-numbering.md
    - lessons.md
  referenced_by:
    - pyrevit-button-dev
  tags: [pyRevit, Revit, MCP_Macros, pushbutton, availability, ribbon]
---

# pyRevit MCP 巨集按鈕開發 SOP

## Purpose

建立或修改 `pyRevit_Tools/MCP_Tools.extension` 的按鈕時，優先保證 Revit ribbon 能穩定載入。按鈕即使需要特定條件，例如已開啟專案文件、目前視圖必須是平面圖、必須先選元素，也應在 `script.py` 執行後用清楚訊息阻擋，而不是讓 pyRevit 在 ribbon 載入階段產生 brittle availability command。

## File Layout

新增按鈕使用標準 pyRevit bundle 結構：

```text
pyRevit_Tools/MCP_Tools.extension/
  MCP_Macros.tab/
    <Panel>.panel/
      <ButtonName>.pushbutton/
        script.py
        bundle.yaml
        optional-ui.xaml
```

`bundle.yaml` 只放顯示資訊：

```yaml
title: "按鈕名稱"
tooltip: "按鈕用途與限制"
```

除非已在同一台 Revit + pyRevit 版本實測，`bundle.yaml` 不放 `context:` 或 `availability:`，`script.py` 也不放 `__context__`。本專案曾因 `context: active-doc` 與 `__context__ = 'doc-project'` 讓 pyRevit 產生的 availability command 無法執行，導致 Revit 啟動時顯示「外部工具 - 可用性指令載入失敗」。

## Cache Discipline

pyRevit 會把 ribbon 與 extension metadata 編譯到 `%APPDATA%\pyRevit\<revit_year>` 的 DLL（例如
`pyRevit_2020_<hash>_MCP_Tools.dll`）。這份 DLL 只在 pyRevit 認為 extension 結構有變時才重新編譯，
單純的 `pyRevit reload` 不會觸發重編——它只重讀 `script.py` 內容，不會重建 ribbon 組件清單。

**觸發重編的動作**（不只是 availability 錯誤這一種）：

- 新增或刪除 `.pushbutton` / `.panel` / `.tab` 資料夾。
- 重新命名 `.pushbutton` 資料夾（例如本專案 `TallPartition` → `TallPartitionExcel`）。
- 曾出現「可用性指令載入失敗」，需要清掉舊的 compiled availability command。

新增或刪除按鈕後，若沒清 cache 就直接 Reload，Revit 會用**舊版**編譯出來的 DLL：
新按鈕會報「找不到類別 `mcp_tools_mcp_macros_<panel>_<button>...`」（FullName 解析失敗），
已刪除的按鈕則會繼續出現在 ribbon 上——因為 DLL 裡那個類別根本沒被移除。

### 一個指令完成：`scripts\pyrevit-refresh.ps1`

自 2026-08-18 起，偵測與清除都由這支腳本代勞，不必再手動比對或逐一刪目錄：

```powershell
.\scripts\pyrevit-refresh.ps1
```

它做三件事，而且**不會替你關閉 Revit**：

1. 把已編譯的 DLL 當文字讀，逐一比對磁碟上的 `.pushbutton` 名稱，直接指出**哪幾顆**不在 DLL 裡
   （不是猜測，是下一節那個二進位比對的自動化版本）。
2. cache 是最新的就回報「不需清除」並結束——此時若按鈕仍報錯，代表不是 cache 問題，要往程式碼查。
3. cache 過期時：Revit 還開著就只報告並要求你自行存檔關閉（exit 1）；Revit 已關閉才實際清除，
   優先用 `pyrevit caches clear --all`，失敗才退回手動刪除 `%APPDATA%\pyRevit` 底下的目錄，
   最後驗證沒有殘留的 `MCP_Tools.dll`。

搭配 `.claude/hooks/detect-stale-pyrevit-cache.sh`（PostToolUse）：只要動到
`.pushbutton` / `.panel` 路徑而整體 cache 有缺按鈕，就會在 AI 的 context 注入提醒，
避免「寫完忘了講、使用者點下去才發現」。

> **無法自動化的部分**：清 cache 需要 Revit 完全關閉（DLL 被鎖），清完必須重啟 Revit。
> 這兩步只能由使用者執行——絕不可代為關閉或終止 Revit 行程，那會讓未存檔的模型消失。

處理方式（手動路徑，腳本失效時的備援）：**先完全關閉 Revit**（DLL 被鎖住時無法清除、也無法重建），再清除：

```text
%APPDATA%\pyRevit\2020
%APPDATA%\pyRevit\2024
%APPDATA%\pyRevit\Cache
```

可優先使用 `pyrevit caches clear --all`。若 CLI 因檔案鎖或權限失敗，先確認目標路徑都在 `%APPDATA%\pyRevit` 底下，再用 PowerShell 刪除這些 cache 目錄，並補回 `%APPDATA%\pyRevit\Cache` 空目錄。清完後重新啟動 Revit，讓 pyRevit 重建乾淨 cache。

### 快速確認是不是 cache 問題

Revit 還開著、無法清 cache 時，可以先用二進位字串比對確認舊 DLL 裡有沒有新按鈕的類別名稱，
不用先關 Revit 才能診斷：

```powershell
$dll = (Get-ChildItem "$env:APPDATA\pyRevit" -Recurse -Filter "*MCP_Tools.dll" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
$ascii = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($dll)).ToLower()
Write-Output "DLL: $dll"
$ascii.Contains('doorwindowexcel')   # 新按鈕的資料夾名稱（小寫）
```

`$false` 代表 DLL 是舊的、確定是 cache 問題，不用往程式碼裡找 bug；同一份 DLL 也能反查
已刪除的按鈕名稱是否還在（`$true` 代表 ribbon 上會繼續看到它）。DLL 的 `LastWriteTime`
可以直接跟按鈕資料夾的建立/修改時間比對，落後就代表沒重編過。

## Runtime Guards

需要條件限制時，在 `script.py` 裡處理：

- 需要專案文件：在程式開頭檢查 `revit.doc`，不符合時用 `forms.alert(..., exitscript=True)` 結束。
- 需要平面視圖：檢查 `isinstance(revit.active_view, DB.ViewPlan)`，不符合時用 `forms.alert()` 結束。
- 需要目前模型元素：用 `FilteredElementCollector(revit.doc)` 收集 host document，不收 Revit links。
- 需要選取元素：讀 `revit.get_selection()` 後自行判斷數量與類別。
- 需要可寫參數：先 dry-run 檢查 parameter 存在、非唯讀、型別可寫，再開 Transaction。

## IronPython Compatibility

pyRevit 按鈕仍需符合 IronPython 執行環境：

- 檔案開頭使用 `# -*- coding: utf-8 -*-`。
- 使用 `from __future__ import unicode_literals` 或明確 `u'...'` 字串。
- 避免 f-string、dataclass、pathlib-only 寫法與 Python 3-only 語法。
- 可共用的純排序/計算邏輯放在 `pyRevit_Tools/MCP_Tools.extension/lib/`，並用 CPython unittest 覆蓋。

## Verification Checklist

完成新按鈕前至少檢查：

- `bundle.yaml` 沒有未實測的 `context:` / `availability:`，`script.py` 沒有未實測的 `__context__`。
- `script.py` 可被 AST parse，且沒有 Python 3-only 語法。
- XAML 可被 XML parser 讀取。
- 共享 helper 有單元測試。
- 若曾出現「可用性指令載入失敗」，已清除 `%APPDATA%\pyRevit\<revit_year>` 與 `%APPDATA%\pyRevit\Cache`。
- pyRevit reload 後 ribbon 沒有「可用性指令載入失敗」。
- **新增、刪除或重新命名 `.pushbutton` 資料夾時**，提醒使用者這次需要「關閉 Revit → 清 cache →
  重啟 Revit」，不是單純 Reload 就會生效；否則會看到「完整類別名稱錯誤」或已刪按鈕仍留在 ribbon 上。
- 不能做 live Revit 測試時，最終回報要明確說明尚未實機點擊。

## Reference

- `domain/lessons.md` L-061, L-062, L-063
- `pyRevit_Tools/README.md`

## 按鈕圖示（icon）

**每顆按鈕都必須附 icon**，這是交付的一部分，不要等使用者回頭要。
沒有圖示的 ribbon 只剩文字，一整排長得一樣，實務上找不到要的那顆。

規格：

- 檔名 `icon.png`，放在該 `.pushbutton` 資料夾內（pyRevit 自動抓取，不需寫進 `bundle.yaml`）。
- 96×96、RGBA、背景透明。pyRevit 會自行縮成大小兩種尺寸。
- 產生器：`pyRevit_Tools/tools/make_icons.py`（純標準函式庫寫 PNG，
  不依賴 Pillow 或任何向量工具鏈，確保幾年後仍跑得動）。

新增按鈕時的作法：

1. 在 `make_icons.py` 的 `BUTTONS` 加一筆「按鈕相對路徑 → 圖形函式」。
2. 需要新圖形就加一個 `g_xxx()`；已有的基本圖元有
   `rect`（含圓角）、`outline`、`circle`、`ring`、`arc`、`line`、`polygon`、
   `arrow`、`dashes`。
3. 會輸出 .xlsx 的按鈕用 `excel()` 包起來，右下角會自動加試算表徽章。
4. 重跑 `python pyRevit_Tools/tools/make_icons.py --sheet <path>`，
   **一定要打開那張 contact sheet 目視檢查**——圖元寫錯（例如圓角判定式）
   在程式碼上看不出來，只有看圖才會發現。

配色依 panel 分群，讓整條 ribbon 一眼分得出類別：

| Panel | 顏色 | 用途 |
|---|---|---|
| Takeoff | 藍 | 算量 |
| Numbering | 綠 | 編號 |
| Check | 紅 | 檢核 |
| Visual | 紫 | 視覺 |
| Structure | 石板灰 | 結構 |
| Revision | 琥珀 | 釋疑 |
