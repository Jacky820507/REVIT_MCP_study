---
name: quantity-takeoff-excel
description: "Create or review auditable Revit quantity-takeoff Excel reports for partition walls, baseboards, interior wall finishes, ceilings, room schedules, and scaffolding. Use when the user asks for 數量計算、算量、輕隔間 Excel、踢腳 Excel、內牆粉刷 Excel、天花 Excel、空間表更新 Excel、施工架數量、room perimeter、opening deductions、net height, or wants an existing pyRevit takeoff method reused through RevitMCP."
---

# Revit Quantity Takeoff Excel

Use current-turn Revit data and produce an auditable calculation, not an unexplained total.

## Route The Request

Choose the calculation family before querying data:

| Request | Formula basis |
|---|---|
| Partition wall | wall length × report height - openings hosted by that wall |
| Baseboard | room Finish perimeter - widths of openings hosted by boundary walls |
| Interior wall finish | room Finish perimeter × net height - opening areas hosted by boundary walls |
| Ceiling | room-clipped physical ceiling coverage; mixed Room C codes use Room area minus physical ceiling area for the single remaining code; otherwise room area; material column assigned by Room `天花板塗層` C code |
| Floor finish | Room area for every non-base F construction layer; base materials remain manual |
| Room schedule update | room number/name/Finish perimeter/area, updated in place |
| General interior scaffold | room perimeter × height |
| Stair/elevator finish scaffold | room length × width × height |
| Exterior scaffold | user-verified detail-line or filled-region perimeter × specified height |

Use a more specific skill when one exists, especially `partition-takeoff` or `scaffold-takeoff`. Apply this skill for the shared data, Excel, and validation rules.

## Query Current Revit State

1. Confirm that RevitMCP tools are available and Revit is connected.
2. Re-query the current document, rooms, levels, relevant walls, ceilings, floors, doors, and windows in this turn.
3. Preserve ElementIds and source fields in an intermediate record before creating Excel rows.
4. If the current client cannot call Revit tools, state that limitation. Do not claim to have calculated the open project.

Keep at least these room fields:

```text
RoomId, Number, Name, Level,
BoundaryLoops, BoundaryElementIds, PerimeterM, AreaM2,
PhysicalCeilingAreaM2, QuantityAreaM2, QuantityAreaSource,
FinishCodes, PhysicalFinishCodes, HeightM, HeightSource,
Openings, Warnings
```

## Apply Boundary Rules

Use `GetBoundarySegments(Finish)` for baseboards, wall finishes, and room schedule perimeter. Sum every valid boundary loop and preserve each boundary segment ElementId.

Do not silently substitute Revit `ROOM_PERIMETER`, which may represent a centerline or another boundary convention. Use it only as a labeled fallback when Finish boundary data is unavailable.

List every valid room even when it has no finish code or quantity. A complete room schedule and a material quantity schedule are separate requirements.

## Deduct Openings Only With Evidence

For partition walls, deduct an opening only when `Opening.Host.Id` equals the calculated wall ElementId.

For baseboards and interior wall finishes, deduct an opening only when `Opening.Host.Id` is present in the room's `BoundaryElementIds`. This excludes doors on internal toilet or service partitions that do not form the calculated room boundary.

Never infer host ownership from nearest-wall distance, same level, room coordinates, or bounding-box proximity. Put missing hosts, missing dimensions, and ambiguous room relations into warnings.

Use the Revit door/window type name in Excel, such as `D5a-120x220 cm`; do not replace it with a family name or reconstructed label.

## Resolve Net Height

For interior wall finish and ceiling height QA, follow this evidence chain and retain `HeightSource`:

1. Match actual `OST_Ceilings` to the room using sample points inside the room/ceiling bounding-box intersection.
2. Prefer the ceiling `Height Offset From Level`:

```text
net height = ceiling level elevation + ceiling offset - room base elevation
```

3. If the offset is unavailable, use the matched ceiling geometry bottom as a labeled fallback.
4. If the room has no actual ceiling, use:

```text
net height = upper level elevation - representative upper slab thickness - room base elevation
```

5. Use explicit room/Revit height only as a final labeled fallback.

Keep full level identity when matching ceilings, slabs, and rooms. Do not collapse different building series such as `B-1F` and `D-1F` into one key. For height QA, reject a ceiling above the room's upper slab underside plus tolerance as an upper-level ceiling and use the upper slab underside instead. Do not let that height rejection override ceiling quantity area: atrium or high-ceiling rooms such as F506-F511 can still use the matched physical ceiling area when the physical ceiling is over the room and the Room C code is authoritative.

Keep full precision during calculation. Round only report display values. Never derive a cosmetically precise height by dividing area by perimeter.

For partition walls, use the separate wall-height rules: full-height walls normally reach the upper slab underside; attached, sloped, low, lining, and non-full-height walls retain their validated Revit geometry or wall height.

## Map Finish Codes And Names

Split multi-value B/W/C finish parameters on `+`; treat blank and `-` as no material. Create columns only for codes actually used by room instances.

For ceiling takeoff, Room `天花板塗層` is authoritative for the Excel material C column. First separate vertically overlapping candidates: prefer ceilings whose full base-level identity equals the Room level; only when none exists, use the nearest overhead candidate level for atrium/high-ceiling rooms. Never add ceilings from several floors merely because their XY bounds overlap. For quantity area, use the geometric intersection between each selected `OST_Ceilings` solid and a vertical room prism built from `GetBoundarySegments(Finish)`. Never assign an entire ceiling element's `HOST_AREA_COMPUTED` to every room it overlaps, because one ceiling may span many rooms. If solid clipping fails, use a labeled overlap estimate capped at Room area; fall back to Room area only when no valid physical ceiling is matched. Compare overlapping physical ceiling C-code evidence against the Room C-code set only as QA; evidence may come from Type Mark, material Mark, or type name. Keep the Room-based material column, but warn that the model must be changed when the sets differ. If the Room code is blank while valid ceiling evidence exists, leave the material quantity blank and tell the user to fill the Room parameter; never backfill the material column from the ceiling evidence.

Some projects draw local ceiling materials with view-specific FilledRegions, but these FilledRegions are often presentation graphics that cross room boundaries and make the export slow. Do not scan FilledRegion geometry for ceiling quantity by default. For mixed Room codes such as `C4+C9`, keep separate `code -> area` values. When physical ceilings account for all but exactly one Room C code, assign the remaining code with `remaining code area = Room area - physical ceiling areas`. This is the preferred F140 pattern: C4 comes from the physical ceiling and C9 is the residual Room area. Never write `=C row` into every material column for a mixed ceiling. Keep main-sheet notes concise: preserve full evidence in the audit sheet, and reserve notes for missing Room codes, code mismatches, unresolved splits, or large area discrepancies.

When material names come from a selected material-board family, remove prefixes such as `B1=` or `W2=` and retain the material description. Do not hardcode project-specific family names; query or ask for the family selection.

For floor takeoff, let the user select a family in `OST_GenericModel`, then read Room `樓板塗層` F codes. Multiple non-base F codes can represent screed, waterproofing, and finish layers, so each valid code may reference the same Room area. Do not apply the ceiling split-area rule to floors. If the matched material name contains `基座`, keep that material column blank and add exactly `此房間有基座需自行手動計算填入數值` to the room note.
Only auto-fill a floor code after its selected-family material name is resolved and confirmed not to contain `基座`. Keep unresolved F-code cells blank. Sort room rows with the separate `floor-level-ordering` skill; preserve full Level names until project-wide naming evidence identifies a building prefix.

## Build An Auditable Workbook

- Derive the title and default filename from the current Revit file name.
- Preserve formulas such as `perimeter - SUM(openings)` and `perimeter × height - SUM(opening areas)`.
- Preserve the ceiling template with A=room number, B=room name, C=area, and material columns starting at D. A single-material cell should reference the area column directly, e.g. `=C8`; mixed ceilings use their room-clipped per-code areas instead. Do not add the old manual area-correction column. Add right-side drawing-source and notes columns, and keep the detailed height/code audit sheet without changing Room-code authority.
- Preserve the floor reference layout with A=room number, B=room name, C=area, F material columns starting at D, one blank row after material names, and right-side drawing-source and notes columns. Every non-base F layer references the Room area row; a base column stays blank.
- Add a final merged quantity-total label and `SUM` formulas for each material or wall-type column.
- Build formulas only after the final row order is fixed. Resolve the data header, material/type columns, and total row by semantic labels; do not preserve `3/4/5` or another observed row number as identity.
- Validate every total formula against its own column and the exact emitted data interval. Scan the entire workbook for formulas that reference a managed sheet's old total row, including comparison and update sheets outside `小計`.
- Omit wall/material columns with no actual instances, but keep all room rows.
- Use OpenXML for a new `.xlsx` when possible. Use Excel COM only when an existing `.xls/.xlsx` workbook and its cross-sheet formulas must be updated in place.
- For in-place updates, run dry-run, create a timestamped backup, then write. Preserve stable room identity and existing formula structure.

## Validate Before Delivery

1. Check one room with an internal toilet/service partition opening; it must not be deducted from the outer Finish boundary quantity.
2. Check one room with a real ceiling and one without a ceiling; confirm their height sources differ correctly.
3. Confirm all valid rooms are present, including zero-quantity rooms.
4. Compare detail formulas with material/wall-type totals.
5. Check one ceiling whose physical C evidence differs from Room `天花板塗層`; material quantity must remain in the Room C column and the report must flag the physical ceiling for correction.
6. Check an upper-level overlapping ceiling case; height QA must resolve to the room's upper slab underside rather than the ceiling above, while ceiling quantity area still uses a valid physical ceiling for atrium/high-ceiling rooms such as F506-F511.
7. Check a physical ceiling modeled as one element across multiple rooms and vertically repeated on upper floors, such as F131; the Room must use its same-level candidates, receive only room-clipped coverage, and disclose area source plus vertically rejected candidates.
8. Check a valid physical ceiling with blank Room `天花板塗層`; the main quantity must remain blank and the report must request a Room-parameter correction.
9. Check a mixed ceiling such as F140: Room `C4+C9`, C4 physical ceiling area, and C9 residual area. Confirm areas are split rather than duplicated and main-sheet notes stay focused on actual problems.
10. Scan for `#REF!`, `#VALUE!`, `#NAME?`, and `#DIV/0!`.
10a. Insert one synthetic title row and one synthetic data row, then rebuild or rebase. Confirm the total range and every cross-sheet total reference still follow their labelled rows. Also reorder one material column to verify header-key mapping.
11. Check one floor room with screed plus finish layers; both non-base F columns must reference the same Room area. Check one base material; its cell must remain blank and the manual-calculation note must appear.
12. Check one unresolved F material name; its quantity must remain blank. Check `B-1F`, `B-B1F`, and `B-R1F` ordering against project-wide building-prefix evidence.
13. Report counts for boundary fallbacks, ceiling-area clipping/estimate fallbacks, filled-region views/regions/rooms, height fallbacks, code mismatches, deducted openings, skipped openings, missing sizes, missing hosts, missing heights, floor base rooms, and missing F material names.

Do not report completion when unresolved warnings could materially change the quantity.
