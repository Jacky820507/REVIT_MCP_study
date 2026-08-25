---
name: pyrevit-button-dev
description: "Use when creating or fixing pyRevit MCP macro buttons, .pushbutton bundles, bundle.yaml, script.py, XAML UI, or pyRevit ribbon load/availability errors such as active-doc context failures."
---

# pyRevit Button Development

## Lessons Reference

- **L-061**: Do not add unverified `context:` or `availability:` in `bundle.yaml`; use script-level guards instead.
- **L-062**: After removing pyRevit availability metadata, clear `%APPDATA%\pyRevit\<revit_year>` and `%APPDATA%\pyRevit\Cache`; otherwise Revit can keep loading the stale compiled availability DLL.
- **L-063**: Treat `script.py` `__context__` as availability metadata too; use runtime `revit.doc` guards unless the exact context has been live-tested.

## Workflow

1. Read `domain/pyrevit-button-development.md`.
2. Inspect nearby buttons in `pyRevit_Tools/MCP_Tools.extension` before adding a new bundle.
3. Keep `bundle.yaml` to display metadata and avoid `script.py` `__context__` unless the context rule has been live-tested in pyRevit.
4. Put document, view, selection, host-only, and parameter-writability checks inside `script.py`.
5. If a ribbon availability error was seen, close Revit and clear pyRevit caches before asking the user to reopen Revit.
6. Move pure logic into `lib/` when it can be unit-tested. For engine compatibility and how to
   verify it, follow the `pyrevit-ironpython-compat` skill — these scripts run on IronPython
   2.7.12, so CPython checks alone are a false green (L-065).
7. Verify with parse checks and targeted tests. If Revit/pyRevit is unavailable, say the live ribbon click was not tested.

## Reference

- `domain/pyrevit-button-development.md`
- `domain/lessons.md`
- `pyrevit-ironpython-compat` skill — IronPython 2.7 subset and the verification gate
