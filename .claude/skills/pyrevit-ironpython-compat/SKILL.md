---
name: pyrevit-ironpython-compat
description: "Keeps pyRevit extension Python runnable on the IronPython 2.7 engine that actually executes it, and verifies edits against that engine instead of CPython. Use before finishing any edit to files under pyRevit_Tools/MCP_Tools.extension — button script.py, lib/*.py, or XAML code-behind — and when diagnosing a runtime TypeError, NameError, ImportError or SyntaxError raised from a pyRevit button. 觸發條件：修改 pyRevit 按鈕、script.py、lib 共用模組、按鈕跳錯誤訊息、IronPython Traceback、TypeError unexpected keyword argument、pyRevit 巨集執行失敗、Py3 語法、離線測試 pyRevit。"
---

# pyRevit IronPython Compatibility

## Which engine actually runs the code

`pyRevit_Tools/MCP_Tools.extension` scripts have **no `#! python3` shebang**, so pyRevit
runs them on its default engine **IPY2712PR = IronPython 2.7.12** — not CPython, and not
the sibling IPY342 (IronPython 3.4.2) that sits in the same folder.

Confirm before assuming: read the first line of the script. A `#! python3` shebang means
the CPython engine; anything else means IronPython 2.7.

This applies to `lib/*.py` too. Shared modules are imported by the buttons, so they run on
the same engine even though they are never clicked directly.

## Lessons Reference

- **L-065**: Verifying pyRevit button code with local CPython is a false green. `max(..., default=)`
  passed every CPython 3.11 unit test and threw `TypeError: max() got an unexpected keyword
  argument (default)` on the first ribbon click. Verify on the engine that runs it.

## Banned on IronPython 2.7

| Construct | Instead |
|---|---|
| `max(seq, default=x)` / `min(...)` | explicit loop, or guard the empty case first |
| f-strings `f"{x}"` | `'{0}'.format(x)` |
| `nonlocal` | a mutable container in the enclosing scope |
| `yield from` | `for item in inner: yield item` |
| zero-arg `super()` | `super(ClassName, self)` |
| type / return annotations | docstring |
| keyword-only args `def f(a, *, b)` | ordinary keyword args |
| `str.casefold()` | `.lower()` |
| `math.isclose()` | `abs(a - b) <= tol` |
| `os.makedirs(path, exist_ok=True)` | check `os.path.isdir` first |
| `subprocess.run` | `subprocess.check_output` / `Popen` |

Division: these files import `unicode_literals` but **not** `division`, so `int / int`
floors. Write a float literal (`/ 2.0`) whenever the result should be fractional.

## Workflow

1. Check the target file's first line to confirm the engine.
2. Write the edit to the 2.7 subset above.
3. Run the gate — it compiles every extension `.py` on the real 2.7.12 engine and greps for
   Python 3 constructs:

   ```powershell
   .\pyRevit_Tools\tools\verify_ironpython.ps1
   ```

4. For logic changes, also exercise the changed functions on that engine rather than
   only on CPython. Load the engine assemblies from
   `%APPDATA%\pyRevit-Master\bin\<netcore|netfx>\engines\IPY2712PR\`
   (`pyRevitLabs.Microsoft.Scripting.dll`, `pyRevitLabs.Microsoft.Dynamic.dll`,
   `pyRevitLabs.IronPython.dll`, `pyRevitLabs.IronPython.Modules.dll`), then
   `[IronPython.Hosting.Python]::CreateEngine()`. Pick `netcore` under PowerShell 7 and
   `netfx` under Windows PowerShell 5.1.

   That host has **no stdlib path**: `import io` fails. Read files with
   `open(path, 'rb').read().decode('utf-8')`. `re` and `math` are available.

5. State plainly that the ribbon click itself was not tested when Revit is unavailable.
   Compiling and unit-testing on the right engine is not the same as running the button.

## Gotchas

- Do not verify on IPY342 to "save time". It accepts `max(default=)` and other Python 3
  builtins that 2.7.12 rejects, so a pass there proves nothing.
- `__pycache__/*.cpython-3xx.pyc` inside a `.pushbutton` folder does **not** prove the
  button runs on CPython; those can be left over from other tooling. The shebang decides.
- When grepping for banned constructs by hand, match case-sensitively. A case-insensitive
  search flags `['f']`, `'F'` and `u'{}F'` as f-strings.

## Reference

- `pyRevit_Tools/tools/verify_ironpython.ps1` — the gate
- `domain/pyrevit-button-development.md` — bundle, availability and ribbon-load rules
- `domain/lessons.md` — L-065
