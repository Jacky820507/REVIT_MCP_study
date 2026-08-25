---
name: excel-button
description: "Use as the entry point when a pyRevit Excel takeoff button is broken, exports wrong numbers, or a fix needs verifying - for example 踢腳按鈕壞了, 隔間牆數量不對, Excel 匯出報錯, or 匯出的公式變成 #REF!. Identifies which Takeoff button is involved, routes by backend (OpenXML direct write vs Excel COM in-place update), and enforces the offline regression gates before handing back."
---

# Excel takeoff button triage

Single entry point for "an Excel export button is broken". This skill deliberately contains **no repair
procedures of its own** — it identifies the failing button, picks the backend path, delegates to the
skill that owns that repair, then enforces regression gates that repeated real regressions have proven
necessary.

If the task is "build a new button" rather than "fix a broken one", go straight to `pyrevit-button-dev`.

## Step 1 - Identify the button and its logic module

Buttons live in `pyRevit_Tools/MCP_Tools.extension/MCP_Macros.tab/Takeoff.panel/` (plus
`Revision.panel/ExportExcel.pushbutton`). Pure logic sits in `MCP_Tools.extension/lib/`.

| Button | Chinese name | Main logic |
|---|---|---|
| `Baseboard` | 踢腳 | self-contained in `script.py` + `takeoff_direct_publish` |
| `PartitionTakeoff` | 隔間牆 | self-contained in `script.py` |
| `TallPartitionExcel` | 高隔間 | `lib/tall_partition_excel.py`, `tall_partition_logic.py` |
| `InteriorWallPaint` | 內牆粉刷 | self-contained in `script.py` |
| `CeilingTakeoff` / `FloorTakeoff` | 天花 / 地坪 | self-contained in `script.py` |
| `RcVolumeExcel` | RC 體積 | `lib/rc_volume_logic.py` |
| `ParkingExcel` | 停車 | `lib/parking_excel.py`, `parking_excel_logic.py`, `parking_numbering.py` |
| `DoorWindowExcel` | 門窗 | `lib/door_window_excel.py`, `door_window_excel_logic.py`, `door_window_window.py` |
| `MachineRoomThresholdExcel` | 機房門檻 | `lib/machine_room_threshold_excel.py`, `machine_room_threshold_logic.py` |
| `ScaffoldExterior` / `ScaffoldRooms` | 鷹架 | `lib/scaffold_excel.py`, `scaffold_height.py`, `scaffold_height_logic.py` |
| `SpaceTableUpdate` | 空間表 | self-contained, heavy Excel COM |

Shared services: `lib/takeoff_entry.py` (the level/link picker dialog and `iter_sources()`),
`lib/takeoff_excel_styles.py` (OOXML fonts/fills/borders), `lib/takeoff_direct_publish.py` (safe
publish into the user's workbook), `lib/takeoff_standalone.py` (dependency-free OOXML writer),
`lib/room_takeoff_sources_logic.py` (room-number normalization and sort keys).

## Step 2 - Triage the backend, because it decides the whole repair path

Most Takeoff buttons can take **either** path within a single run, decided by whether the user picked a
target workbook in the entry dialog. Establish which one actually ran before theorising.

- **Fork A - OpenXML direct write.** No target workbook chosen; the button writes a fresh `.xlsx` by
  zipping OOXML strings (`write_xlsx` in the button, or `takeoff_standalone.write_standard_workbook`).
  Excel is never launched. Faults here are string/formula/style generation bugs.
- **Fork B - Excel COM in-place update.** A target workbook was chosen;
  `takeoff_direct_publish.publish_generated_workbook()` opens the user's real workbook via COM and
  overwrites cells while preserving layout, merges and column widths. Faults here are row-matching,
  formula rebasing, `#REF!`, backup and COM-lifetime bugs. **For Fork B, follow
  `revit-excel-workbook-update` — it owns that procedure.**

## Step 3 - Classify the fault before editing

1. **IronPython syntax / runtime** - traceback names a construct or module. Follow
   `pyrevit-ironpython-compat`. These scripts run on IronPython 2.7.12; a passing CPython check is a
   false green (L-065).
2. **Formula or column drift** - numbers land in the wrong column, subtotals point at the wrong row,
   or `#REF!` appears. Read the global `sheet-formula-governance` skill, then see Step 5 gates 3-4.
3. **Wiring** - the button calls the wrong `lib` entry point. `tests/test_update_button_wiring.py`
   asserts these bindings by text comparison.
4. **Revit data boundary** - counts wrong but the workbook is intact. This is a schedule/collector
   boundary question, not an Excel one; see `revit-excel-workbook-update` guardrails on schedule
   boundaries, grouped elements and linked models.

## Step 4 - Repair

Delegate by fork and fault class as above. Keep pure logic in `lib/` so it stays unit-testable, and keep
`script.py` thin.

## Step 5 - Regression gates, all of them, in order

A fix is not done until these pass. Every one of these exists because a real regression got through.

1. **Unit tests** - covers formula rebasing, style output and button wiring:
   ```
   python -m unittest discover pyRevit_Tools/tests
   ```
   Runs under CPython 3 with no Revit. `test_takeoff_direct_publish.py` already guards
   the historical subtotal-rebase and material-column-index regressions.

2. **IronPython gate** - compiles every `.py` with the real IronPython 2.7 engine and scans for Python-3
   constructs:
   ```
   .\pyRevit_Tools\tools\verify_ironpython.ps1
   ```
   Do not substitute the IPY342 engine. Use `-SkipCompile` for a syntax-only scan when the engine is
   unavailable, and say so in the report.

3. **Hardcoded column sweep** - run before and after the change and diff the two outputs. Only the file
   being fixed may differ; any other file appearing in the diff is a cross-workbook regression:
   ```
   grep -rnE --include=*.py --exclude-dir=__pycache__ --exclude-dir=*.backup-* \
     '\$[A-Z]{1,2}\$?[0-9{]|[=(,:][A-Z]{1,2}\{[0-9]*\}|\.Cells\([^),]*, *[0-9]+\)|^[A-Z_]*(COL|ROW)[A-Z_]* *= *[0-9]+' \
     pyRevit_Tools/MCP_Tools.extension
   ```
   Baseline as of 2026-08-10 is **243 matches across 16 files**, in four shapes: absolute `$X` refs
   inside SUMIF/SUMIFS templates (`scaffold_excel.py` marks several "never move"), column letters baked
   into format strings, COM `.Cells(row, <literal>)`, and module-level `*_COL` / `*_ROW` constants whose
   values differ per button. `lib/scaffold_excel.py` alone holds 133 of the 243 — treat it as the
   highest-risk file in the tree. Prefer the existing `excel_col(index)` helper over new literals.

4. **Semantic formula mutation gate** - test a title-row insertion, appended data row, moved total row,
   and reordered material/type column. Verify each total range exactly covers the current data region,
   and scan the whole workbook for formulas still pointing at an old labelled total row. A successful
   recalculation or numeric cached value is not enough.

5. **Fork B only** - after save and recalculate, verify the workbook for `#REF!`, `#VALUE!`, `#NAME?`
   and `#DIV/0!`, and confirm the timestamped backup exists.

6. **Fork A / optional Fork B read-back** - for `.xlsx`, run the shared OfficeCLI gate after the
   writer has closed the file:
   ```powershell
   .\pyRevit_Tools\tools\verify-officecli-xlsx.ps1 .\path\to\output.xlsx
   ```
   It validates the OpenXML package, reports sheet/formula/error counts, catches formula evaluation
   and missing-reference issues, and can render HTML for checking fonts, merges, widths and borders:
   ```powershell
   .\pyRevit_Tools\tools\verify-officecli-xlsx.ps1 .\path\to\output.xlsx `
     -RenderHtml -RenderPath .\tmp\output.officecli.html
   ```
   Treat formula issues as failures. Treat layout warnings as warnings unless the task explicitly
   requires `-FailOnLayoutWarnings`. OfficeCLI is an offline QA reader here; it must not replace the
   Excel COM path for legacy `.xls` or for preserving a user's live desktop workbook style.

## Step 6 - Report

State: files changed; which buttons share the modules touched; which gates ran and their results; and
explicitly whether live Revit testing is still outstanding. Offline gates cannot prove end-to-end
correctness — only clicking the button against a real model can.

## Guardrails

- **`.pyc` timestamps prove nothing about stale button code.** pyRevit runs these buttons on
  IronPython 2.7.12, which writes no `.pyc`. Every `__pycache__/*.cpython-3XX.pyc` in the tree is a
  CPython artifact from running the unit tests. Do not use pyc-vs-py comparison as evidence that a
  button is running old code. If a change appears not to take effect, suspect the pyRevit reload or
  engine cache instead, and clear `%APPDATA%\pyRevit\<revit_year>` and `%APPDATA%\pyRevit\Cache`
  (L-062).
- **`AppData\Roaming\pyRevit\Extensions\MCP_Tools.extension` is a junction into this repo**, not a
  deployed copy. Editing through either path edits the repo, so "the deployed copy is stale" is never
  the explanation.
- **Exclude `*.backup-*` directories from every grep.** `Baseboard.pushbutton.backup-20260709-踢腳邊界段前`
  holds a complete old `script.py` that pyRevit does not load but grep will happily match.
- **`lib/` must stay Python 2/3 dual-compatible.** Those modules are imported both by IronPython 2.7 at
  runtime and by the CPython 3 unit tests.
- **There are no `.xltx` templates.** The "templates" are the user's live working workbooks at the repo
  root (`污水處理廠工項-*.xls`, `綜合大樓工項-*.xls`, `物流中心工項-*.xls`). Always take a timestamped
  backup before any Fork B write.
- **Do not fix one workbook by hardcoding.** The recurring failure mode is a fix that repairs the
  workbook in front of you and silently breaks a sibling generator that shares the module.

## Reference

- `revit-excel-workbook-update` skill - owns the Fork B in-place update procedure
- `pyrevit-ironpython-compat` skill - IronPython 2.7 subset and the verification gate
- `pyrevit-button-dev` skill - bundle/ribbon/cache issues and new button creation
- `quantity-takeoff-excel` skill - the formula baselines per takeoff category
- global `sheet-formula-governance` skill - semantic anchors, structural audit, and mutation tests
- `domain/lessons.md`
