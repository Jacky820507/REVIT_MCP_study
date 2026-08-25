---
name: revit-excel-workbook-update
description: Use when creating or fixing Revit/pyRevit buttons that update an existing Excel workbook from Revit schedules or model counts. Covers workbook mapping, formula protection, dry-run preview, backups, Excel COM safety, subtotal/index validation, and grouped Revit element performance pitfalls.
---

# Revit to Excel workbook update

Use this skill when a button updates a user-provided `.xls` or `.xlsx` workbook instead of generating a new report.

## Required references

Read these files before changing code:

1. `domain/revit-excel-workbook-update.md`
2. `domain/lessons.md` (workbook-update entries)

When the task includes parking spaces, also read:

3. `domain/parking-space-review.md`

## Workflow

1. Inspect the workbook contract: sheet names, target item labels, input columns, multiplier columns, formula columns, subtotal/index sheets, hidden rows, and protected formulas.
2. Inspect the Revit source boundary: named schedules, category collectors, selected elements, level names, type names, dimensions, element ids, and duplicate-count risks.
3. Build a dry-run preview before writing. Show source counts, matched workbook rows, old values, proposed values, formulas, warnings, and blocked items.
4. Write only the smallest necessary input cells. Preserve formulas, formatting, row order, sheet names, and cross-sheet links.
5. Create a timestamped backup before modifying a workbook.
6. After save/recalculate, verify changed cells, protected formulas, formula results, subtotal/index links, and Excel errors such as `#REF!`, `#VALUE!`, `#NAME?`, or `#DIV/0!`.
7. Keep pure calculation logic separate from the UI/entry layer so the rules stay unit-testable without Revit or Excel attached.

## Tool availability

This repo provides the **read** half only. Verify before planning:

- Revit-side quantities: `calculate_room_scaffold_perimeters`, `get_rooms_by_level`, `query_schedule_data`, `query_elements_with_filter` — all available.
- **Writing into an existing workbook: no MCP tool exists.** That step must run through an external script (Excel COM or equivalent). Say so explicitly instead of implying a one-call export exists.

If a step in this workflow has no tool behind it, state the limitation rather than describing the call as if it were available.

## Guardrails

- Do not replace an explicit Revit schedule boundary with a broad category fallback unless the user explicitly approves it.
- Match workbook rows by normalized item text and dimension evidence before falling back to fixed row numbers.
- If workbook formulas are part of the contract, validate formula shape before writing adjacent input cells.
- Keep Markdown/domain/lesson files as UTF-8. Do not convert knowledge files to cp950 just because a Windows tool defaults to the system code page.
- When grouped Revit elements are present, do not expand groups or scan every parameter on every grouped instance. First classify by schedule boundary and dimensions, then read expensive text/accessibility parameters only for unresolved items. Report grouped counts in the preview.
- For shared basements or campus projects, consider linked Revit models as optional quantity sources. When reading links, do not compare linked elements with host `LevelId`; use level name/elevation evidence and include the link instance id in duplicate keys.
- When several links contain the same floor, require explicit link-instance selection. Treat host schedules and selected links as separate source boundaries unless the linked model is proven to use the same parameter semantics; a host `Mark/Comments` filter may correspond to parking numbers inside the link.

## Subagent option

For larger workbook-update tasks, use `references/excel-update-subagent.md` as the handoff checklist for an implementation or review subagent.
