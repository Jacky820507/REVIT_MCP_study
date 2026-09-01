# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""離線驅動 pyRevit 按鈕 ``main()`` 用的假 Revit／pyrevit／.NET 邊界。

## 為什麼需要這一支

到 2026-08-31 為止，``tests\\`` 底下 56 支測試、1543 個案例全綠，但其中**只有兩支
真的把按鈕模組載進來執行**（``test_pdf_diff_window`` 與 ``test_takeoff_direct_publish``，
而後者載的是 ``lib\\`` 的純函式庫，不是按鈕本身）。以 ``RcVolumeExcel`` 為例，
``test_rc_volume.py`` 從頭到尾只 import ``rc_volume_logic``——那支 1636 行的
``script.py`` 一行都沒跑過。

所以下面這一整段沒有任何測試覆蓋：

* ``main()`` 自己的流程（問答順序、取消時該不該提早 return、守衛條件）
* ``collect_data`` 回傳的六元組怎麼拆、怎麼往下傳（**餵錯參數就是曾經出過事的那次**：
  sheet 2 要的是整支牆 ``rc_walls``，不是分攤後的 ``grouped_by_room``）
* ``write_xlsx`` 真的產出的檔案（zip 結構、分頁數、重複 entry）
* ``report()`` 讀 ``stats`` 的每一個 key（少一個就是 KeyError，而且是在
  Excel 已經寫完之後才炸，使用者會以為匯出失敗）

這些全部發生在「假設 Revit 存在」的那一層，用純函式測試碰不到。這支的工作就是
把 Revit／pyrevit／.NET 這三道牆換成可控的假貨，讓上面那些程式碼可以在 CPython 3
底下**照原樣執行**。

## 設計上的三個刻意選擇

1. **``ScriptedForms`` 是嚴格的**：問到沒有預先排答案的對話框就丟
   ``UnscriptedPrompt``，而不是回 ``None``。回 ``None`` 會讓 ``main()`` 安靜地
   提早 return，測試照樣綠燈——那正好是我們要抓的那種失敗。

2. **假的 ``ZipArchive`` 背後是真的 ``zipfile``**：產出的 ``.xlsx`` 是可以真的打開、
   真的解析的檔案，測試才能對 sheet XML 下斷言。同名 entry 寫兩次會直接丟例外
   （真實世界的症狀是 Excel 開檔時跳「需要修復」）。

3. **``load_button`` 只拆掉檔尾那一行 ``main()``**，其餘原始碼原封不動 compile。
   pyRevit 的按鈕是「import 即執行」，不拆就沒辦法在呼叫前置換 ``collect_data``。
   拆之前會先用 AST 確認那行**確實存在且只有一行**——所以「有人不小心刪掉進入點」
   這件事本身也被測到了。

## 這支測不到什麼

* **真實幾何**：``collect_data`` 裡的 ``FilteredElementCollector``、Solid 布林運算、
  Room 邊界都沒有被模擬。要驅動 ``main()`` 就得在這個接縫餵 fixture。這是刻意的
  範圍切割，不是疏漏——那一層要靠 Revit 內的實測。
* **IronPython 與 CPython 的行為差異**：那是 ``verify_ironpython.ps1``
  與 ``ironpython-guard-hook.ps1`` 的守備範圍。
* **.NET 數值格式化的細節**：``String.Format('{0}', 0.1)`` 在 .NET 與 Python 下
  字面值可能不同。表格內的數字多半已經先過 ``fixed()`` 變成字串，但若哪天有原始
  float 直接進儲存格，這支不會抓到。
* **版面外觀**：字體、框線、欄寬只驗得到 XML 有沒有寫進去，驗不到好不好看。
"""

import ast
import contextlib
import io
import os
import re
import sys
import types
import zipfile


__all__ = [
    'UnscriptedPrompt',
    'ScriptExit',
    'DuplicateZipEntry',
    'FakeDocument',
    'FakeOutput',
    'ScriptedForms',
    'install',
    'load_button',
    'LIB',
    'BUTTON_ROOT',
]


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LIB = os.path.join(ROOT, 'MCP_Tools.extension', 'lib')
BUTTON_ROOT = os.path.join(ROOT, 'MCP_Tools.extension', 'MCP_Macros.tab')

_MISSING = object()


class UnscriptedPrompt(AssertionError):
    """按鈕問了一個測試沒有預先排答案的對話框。

    這是斷言失敗而不是一般例外：代表 ``main()`` 的問答流程跟測試的假設對不上，
    通常是有人加了新對話框、或把既有對話框的順序換掉了。
    """


class ScriptExit(SystemExit):
    """對應 ``forms.alert(..., exitscript=True)`` 與 ``script.exit()``。

    **必須繼承 SystemExit 而不是 Exception**：pyRevit 這兩個動作底層都是
    ``sys.exit()``，所以腳本裡的 ``except Exception`` 不會攔到它。若這裡用
    Exception，像 ``SpaceTableUpdate`` 那種「整段流程包在模組層 try 裡」的腳本
    就會把正常的中止當成錯誤回報，測出來的結論是錯的。
    """


class DuplicateZipEntry(AssertionError):
    """同一個 zip entry 名稱被寫了兩次——xlsx 這樣做 Excel 會要求修復。"""


# ---------------------------------------------------------------------------
# .NET：System / System.IO / System.IO.Compression / System.Text
# ---------------------------------------------------------------------------

class _String(object):
    """只實作按鈕真正用到的 ``String.Format('{0}', value)``。"""

    _PLACEHOLDER = re.compile(r'\{(\d+)\}')

    @staticmethod
    def Format(template, *args):
        def replace(match):
            value = args[int(match.group(1))]
            # .NET 的 String.Format 對 null 給空字串，不是 'None'
            return '' if value is None else '{0}'.format(value)

        return _String._PLACEHOLDER.sub(replace, template)


class _Bytes(object):
    """.NET ``byte[]`` 的替身：只需要 ``Length`` 與切片。"""

    def __init__(self, data):
        self._data = data

    @property
    def Length(self):
        return len(self._data)

    def __len__(self):
        return len(self._data)

    def __getitem__(self, item):
        return self._data[item]

    def raw(self, offset=0, count=None):
        end = len(self._data) if count is None else offset + count
        return self._data[offset:end]


class _EncodingObject(object):
    """``Encoding.UTF8``：既能傳給 StreamWriter，也能自己 GetBytes。

    lib\\ 底下有兩種寫 zip entry 的寫法——按鈕多半走
    ``StreamWriter(stream, Encoding.UTF8).Write(text)``，
    ``tall_partition_excel`` 走 ``Encoding.UTF8.GetBytes(text)`` 再
    ``stream.Write(data, 0, data.Length)``。兩條都要支援。
    """

    def __init__(self, codec):
        self.codec = codec
        self.WebName = codec

    def GetBytes(self, text):
        return _Bytes(text.encode(self.codec))

    def GetString(self, data):
        raw = data.raw() if isinstance(data, _Bytes) else bytes(data)
        return raw.decode(self.codec)


class _Encoding(object):
    UTF8 = _EncodingObject('utf-8')
    Unicode = _EncodingObject('utf-16')
    Default = _EncodingObject('utf-8')


class _FileMode(object):
    Create = 'Create'
    CreateNew = 'CreateNew'
    Open = 'Open'
    OpenOrCreate = 'OpenOrCreate'


class _FileAccess(object):
    Read = 'Read'
    Write = 'Write'
    ReadWrite = 'ReadWrite'


class _ZipArchiveMode(object):
    Create = 'Create'
    Read = 'Read'
    Update = 'Update'


class _FileStream(object):
    def __init__(self, path, mode=None, access=None):
        self.Name = path
        self.path = path
        self.mode = mode
        self.access = access
        self.closed = False

    def Close(self):
        self.closed = True

    def Dispose(self):
        self.Close()


class _EntryStream(object):
    """``entry.Open()`` 回傳的串流；內容累積在記憶體，關閉時才落地。"""

    def __init__(self, entry):
        self._entry = entry
        self._parts = []          # 一律存 bytes，兩條寫法才能混用
        self._committed = False

    def _guard(self):
        if self._committed:
            raise AssertionError(
                'entry "{0}" 已經關閉還在寫入'.format(self._entry.name))

    def _append(self, text, codec='utf-8'):
        self._guard()
        self._parts.append(text.encode(codec))

    def Write(self, data, offset=0, count=None):
        """``stream.Write(byte[], offset, count)``。"""
        self._guard()
        if isinstance(data, _Bytes):
            self._parts.append(data.raw(offset, count))
        else:
            raw = bytes(bytearray(data))
            end = len(raw) if count is None else offset + count
            self._parts.append(raw[offset:end])

    def commit(self):
        if self._committed:
            return
        self._committed = True
        self._entry.archive._store(self._entry.name, b''.join(self._parts))

    def Close(self):
        self.commit()

    def Dispose(self):
        self.commit()


class _ZipEntry(object):
    def __init__(self, archive, name):
        self.archive = archive
        self.name = name

    def Open(self):
        return _EntryStream(self)


class _StreamWriter(object):
    def __init__(self, stream, encoding=None):
        self._stream = stream
        self.encoding = encoding or _Encoding.UTF8
        self._codec = getattr(self.encoding, 'codec', 'utf-8')

    def Write(self, text):
        self._stream._append(text, self._codec)

    def WriteLine(self, text=''):
        self._stream._append(text + '\n', self._codec)

    def Flush(self):
        pass

    def Close(self):
        self._stream.commit()

    def Dispose(self):
        self.Close()


class _ZipArchive(object):
    """背後是真的 ``zipfile``，所以產出的檔案真的能被解析。"""

    def __init__(self, stream, mode=None):
        self.path = stream.path
        self.mode = mode
        self.entry_names = []
        self._zip = zipfile.ZipFile(stream.path, 'w', zipfile.ZIP_DEFLATED)
        self._disposed = False

    def CreateEntry(self, name, *_args):
        return _ZipEntry(self, name)

    def _store(self, name, data):
        if name in self.entry_names:
            raise DuplicateZipEntry(
                'zip entry "{0}" 被寫了兩次'.format(name))
        self.entry_names.append(name)
        self._zip.writestr(name, data)

    def Dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._zip.close()

    def Close(self):
        self.Dispose()


# ---------------------------------------------------------------------------
# Revit API：任何名稱都自動生出一個類別
# ---------------------------------------------------------------------------

class _AutoValue(object):
    """列舉成員之類的佔位值；只需要能被比較與印出來。"""

    def __init__(self, path):
        self._path = path

    def __repr__(self):
        return '<revit-stub {0}>'.format(self._path)


class _AutoMeta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        value = _AutoValue('{0}.{1}'.format(cls.__name__, name))
        setattr(cls, name, value)
        return value


_AutoBase = _AutoMeta('_AutoBase', (object,), {})


class _AutoModule(types.ModuleType):
    """``from Autodesk.Revit.DB import Anything`` 一律給得出東西。"""

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        cls = _AutoMeta(str(name), (_AutoBase,), {})
        setattr(self, name, cls)
        return cls


# ---------------------------------------------------------------------------
# pyrevit
# ---------------------------------------------------------------------------

class FakeDocument(object):
    def __init__(self, path_name='', title='Untitled.rvt'):
        self.PathName = path_name
        self.Title = title


class FakeOutput(object):
    """``script.get_output()``：把印出來的東西留著給測試檢查。"""

    def __init__(self):
        self.lines = []

    def print_md(self, text):
        self.lines.append(text)

    def print_html(self, text):
        self.lines.append(text)

    def set_title(self, title):
        pass

    def close_others(self, *args, **kwargs):
        pass

    @property
    def text(self):
        return '\n'.join(self.lines)


class ScriptedForms(object):
    """預先排好答案的 ``pyrevit.forms``。

    ``answers`` 的 key 是提問種類，value 是答案；value 給 list 就代表「第 n 次
    問這種問題時回第 n 個答案」，list 用完再問就是錯誤。問到沒排的種類一律丟
    ``UnscriptedPrompt``——安靜地回 ``None`` 會讓 ``main()`` 提早 return，
    測試反而全綠。
    """

    # WPFWindow 在 FakeWPFWindow 定義之後才綁上去（見本類別下方）

    def __init__(self, answers=None):
        self._answers = dict(answers or {})
        self.calls = []
        self.alerts = []

    # -- 內部 --------------------------------------------------------------

    def _take(self, kind, **info):
        self.calls.append((kind, info))
        if kind not in self._answers:
            raise UnscriptedPrompt(
                '按鈕問了「{0}」，但測試沒有為它準備答案。'
                '已問過的順序：{1}'.format(
                    kind, [call[0] for call in self.calls]))
        value = self._answers[kind]
        if isinstance(value, list):
            if not value:
                raise UnscriptedPrompt(
                    '「{0}」被問了第 {1} 次，但只準備了 {1} 個答案以下'.format(
                        kind, len([c for c in self.calls if c[0] == kind])))
            return value.pop(0)
        return value

    @property
    def prompt_sequence(self):
        return [call[0] for call in self.calls]

    # -- pyrevit.forms 介面 -------------------------------------------------

    def ask_for_string(self, default=None, prompt=None, title=None, **kwargs):
        return self._take('ask_for_string', default=default, prompt=prompt,
                          title=title)

    def alert(self, msg, title=None, sub_msg=None, expanded=None,
              footer='', ok=True, cancel=False, yes=False, no=False,
              retry=False, exitscript=False, **kwargs):
        # alert 有兩種身分：純通知，以及 yes/no 問句。只有後者需要答案。
        if yes or no or cancel or retry:
            return self._take('alert_yes_no', message=msg, title=title)
        self.calls.append(('alert', {'message': msg, 'title': title}))
        self.alerts.append(msg)
        if exitscript:
            raise ScriptExit(msg)
        return None

    def save_file(self, file_ext=None, default_name=None, title=None,
                  **kwargs):
        return self._take('save_file', file_ext=file_ext,
                          default_name=default_name, title=title)

    def pick_file(self, *args, **kwargs):
        return self._take('pick_file')

    def select_file(self, *args, **kwargs):
        return self._take('select_file')

    @property
    def SelectFromList(self):
        """pyrevit 的用法是 ``forms.SelectFromList.show(...)``，不是直接呼叫。"""
        return _SelectFromList(self)

    def ask_for_one_item(self, *args, **kwargs):
        return self._take('ask_for_one_item')

    def ProgressBar(self, *args, **kwargs):
        return _NullProgressBar()


class _SelectFromList(object):
    """``forms.SelectFromList.show(options, ...)`` 的替身。

    答案排在 ``answers['select_from_list']``；沒排就丟 UnscriptedPrompt，
    跟其他對話框一樣，不會安靜地回 None 讓流程默默結束。
    """

    def __init__(self, forms_stub):
        self._forms = forms_stub

    def show(self, context=None, **kwargs):
        return self._forms._take('select_from_list', options=context,
                                 title=kwargs.get('title'))


class FakeWPFWindow(object):
    """``pyrevit.forms.WPFWindow`` 的最小替身，只夠讓模組載入與建構。

    ``lib\\`` 底下幾支會 ``class XxxWindow(forms.WPFWindow)``，光是 import 就需要
    這個基底類別存在。這裡**不解析 XAML**，所以 XAML 裡具名元件不會變成屬性——
    要真的驅動一個視窗的互動，得像 ``test_pdf_diff_window`` 那樣做一套會強制
    單一父層規則的假 WPF，那是另一件事。這支只負責讓「不開視窗的那條路」跑得動。
    """

    def __init__(self, xaml_source=None, literal_string=False, **kwargs):
        self.xaml_source = xaml_source
        self.literal_string = literal_string
        self.shown = 0
        self.closed = False
        self.DialogResult = None

    def show_dialog(self, *args, **kwargs):
        self.shown += 1
        return self.DialogResult

    def show(self, *args, **kwargs):
        self.shown += 1

    def Close(self, *args, **kwargs):
        self.closed = True

    def hide(self, *args, **kwargs):
        pass

    def set_image_source(self, *args, **kwargs):
        pass


# 有幾支 lib 模組會拿它當視窗基底類別（class XxxWindow(forms.WPFWindow)）
ScriptedForms.WPFWindow = FakeWPFWindow


class _NullProgressBar(object):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update_progress(self, *args, **kwargs):
        pass

    @property
    def cancelled(self):
        return False


class _FakeRevit(object):
    def __init__(self, doc):
        self.doc = doc
        self.uidoc = None
        self.docs = [doc]


class _FakeScript(object):
    def __init__(self, output):
        self._output = output

    def get_output(self):
        return self._output

    def get_config(self, *args, **kwargs):
        return _AutoValue('script.config')

    def save_config(self, *args, **kwargs):
        pass

    def get_script_path(self):
        return ''

    def exit(self):
        raise ScriptExit('script.exit()')


# ---------------------------------------------------------------------------
# 安裝／還原
# ---------------------------------------------------------------------------

class Stubs(object):
    def __init__(self, doc, forms, output):
        self.doc = doc
        self.forms = forms
        self.output = output


def _build_modules(doc, forms, output):
    clr = types.ModuleType(str('clr'))
    clr.AddReference = lambda *args, **kwargs: None
    clr.AddReferenceByName = lambda *args, **kwargs: None
    clr.Reference = lambda *args, **kwargs: None

    autodesk = types.ModuleType(str('Autodesk'))
    revit_ns = types.ModuleType(str('Autodesk.Revit'))
    db = _AutoModule(str('Autodesk.Revit.DB'))
    ui = _AutoModule(str('Autodesk.Revit.UI'))
    structure = _AutoModule(str('Autodesk.Revit.DB.Structure'))
    revit_ns.DB = db
    revit_ns.UI = ui
    db.Structure = structure
    autodesk.Revit = revit_ns

    # System 用 _AutoModule：lib\ 底下走 Excel COM 的模組會 import Activator、
    # Marshal、Runtime.InteropServices 之類的東西，逐一列舉列不完也沒必要——
    # 真正要模擬行為的那幾個在下面明確蓋掉。
    system = _AutoModule(str('System'))
    system.String = _String
    system.Object = object
    system.Exception = Exception

    system_io = _AutoModule(str('System.IO'))
    system_io.FileStream = _FileStream
    system_io.FileMode = _FileMode
    system_io.FileAccess = _FileAccess
    system_io.StreamWriter = _StreamWriter

    interop = _AutoModule(str('System.Runtime.InteropServices'))
    runtime = _AutoModule(str('System.Runtime'))
    runtime.InteropServices = interop

    windows = _AutoModule(str('System.Windows'))
    win_controls = _AutoModule(str('System.Windows.Controls'))
    win_media = _AutoModule(str('System.Windows.Media'))
    win_input = _AutoModule(str('System.Windows.Input'))
    windows.Controls = win_controls
    windows.Media = win_media
    windows.Input = win_input

    compression = types.ModuleType(str('System.IO.Compression'))
    compression.ZipArchive = _ZipArchive
    compression.ZipArchiveMode = _ZipArchiveMode

    system_text = types.ModuleType(str('System.Text'))
    system_text.Encoding = _Encoding

    system_collections = types.ModuleType(str('System.Collections'))
    generic = _AutoModule(str('System.Collections.Generic'))
    system_collections.Generic = generic

    system.IO = system_io
    system.Text = system_text
    system.Collections = system_collections
    system.Runtime = runtime
    system.Windows = windows
    system_io.Compression = compression

    pyrevit = types.ModuleType(str('pyrevit'))
    pyrevit.forms = forms
    pyrevit.revit = _FakeRevit(doc)
    pyrevit.script = _FakeScript(output)
    # pyrevit 對外也轉出 DB／UI 這兩個別名（from pyrevit import DB），
    # lib\ 底下的模組多半走這條而不是 from Autodesk.Revit.DB import ...
    pyrevit.DB = db
    pyrevit.UI = ui
    pyrevit.HOST_APP = _AutoValue('pyrevit.HOST_APP')
    pyrevit.EXEC_PARAMS = _AutoValue('pyrevit.EXEC_PARAMS')

    return {
        'clr': clr,
        'Autodesk': autodesk,
        'Autodesk.Revit': revit_ns,
        'Autodesk.Revit.DB': db,
        'Autodesk.Revit.DB.Structure': structure,
        'Autodesk.Revit.UI': ui,
        'System': system,
        'System.IO': system_io,
        'System.IO.Compression': compression,
        'System.Text': system_text,
        'System.Collections': system_collections,
        'System.Collections.Generic': generic,
        'System.Runtime': runtime,
        'System.Runtime.InteropServices': interop,
        'System.Windows': windows,
        'System.Windows.Controls': win_controls,
        'System.Windows.Media': win_media,
        'System.Windows.Input': win_input,
        'pyrevit': pyrevit,
        'pyrevit.forms': forms,
        'pyrevit.revit': pyrevit.revit,
        'pyrevit.script': pyrevit.script,
    }


@contextlib.contextmanager
def install(document=None, answers=None):
    """把假的 Revit／pyrevit／.NET 掛進 ``sys.modules``，離開時原樣還原。"""
    doc = document if document is not None else FakeDocument()
    forms = ScriptedForms(answers)
    output = FakeOutput()

    modules = _build_modules(doc, forms, output)
    saved = {}
    for name, module in modules.items():
        saved[name] = sys.modules.get(name, _MISSING)
        sys.modules[name] = module

    path_added = LIB not in sys.path
    if path_added:
        sys.path.insert(0, LIB)

    # lib\ 底下有些模組（例如 scaffold_height）自己就 import Revit。它們在假貨
    # 生效時被載入，模組層會留下對假類別的參照——放著不管，下一支測試 import
    # 同一個名字時拿到的就是被汙染的版本，而且症狀完全不像是這裡造成的。
    # 所以「在 install 期間才第一次載入、且來自 lib\」的模組，離開時一併清掉。
    before = set(sys.modules)

    try:
        yield Stubs(doc, forms, output)
    finally:
        for name in set(sys.modules) - before:
            module = sys.modules.get(name)
            origin = getattr(module, '__file__', None) or ''
            if origin and os.path.dirname(os.path.abspath(origin)) == LIB:
                sys.modules.pop(name, None)
        for name, previous in saved.items():
            if previous is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        if path_added and LIB in sys.path:
            sys.path.remove(LIB)


# ---------------------------------------------------------------------------
# 載入按鈕
# ---------------------------------------------------------------------------

def _is_bare_call(node, name):
    return (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == name)


def _entrypoint_nodes(body, name):
    """模組層的進入點；兩種寫法都算數。

    多數按鈕檔尾就是一行 ``main()``；地坪那顆把它包在 ``try/except`` 裡好把例外
    轉成對話框。兩種都要認得，否則會誤判成「這顆按鈕沒有進入點」。
    """
    found = []
    for node in body:
        if _is_bare_call(node, name):
            found.append((node, body))
        elif isinstance(node, ast.Try):
            for inner in node.body:
                if _is_bare_call(inner, name):
                    found.append((inner, node.body))
    return found


def button_path(panel, button, filename='script.py'):
    return os.path.join(BUTTON_ROOT, panel, button + '.pushbutton', filename)


def lib_path(name):
    return os.path.join(LIB, name + '.py')


def run_script(script_path, extra_globals=None, module_name=None):
    """把一支 ``script.py`` 從頭到尾執行一次——模組層本身就是它的進入點。

    ``SpaceTableUpdate`` 這種按鈕沒有 ``main()``：整段流程寫在模組層的一個
    ``try`` 區塊裡，而且靠呼叫端**預先把 ``_MCP_EMBEDDED_RESULT`` 塞進 globals**
    來回傳結果（``ScaffoldRooms`` 就是這樣 ``execfile`` 它的）。所以驅動它＝執行它，
    ``load_button`` 那套「拆掉檔尾的 main()」在這裡不適用。

    回傳執行後的命名空間，方便檢查模組層留下的東西。
    """
    with io.open(script_path, encoding='utf-8') as handle:
        source = handle.read()
    namespace = {
        '__file__': script_path,
        '__name__': module_name or '__mcp_embedded__',
    }
    namespace.update(extra_globals or {})
    exec(compile(source, script_path, 'exec'), namespace)
    return namespace


def install_module(name, module):
    """把一個假模組塞進 ``sys.modules``，回傳還原用的 callable。

    用在「要換掉的東西必須在被 import 之前就位」的情況——例如
    ``run_script`` 執行的腳本會 ``import mcp_bridge``，等它跑完才 patch 就太遲了。
    """
    previous = sys.modules.get(name, _MISSING)
    sys.modules[name] = module

    def restore():
        if previous is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return restore


def load_lib(name, path=None):
    """在假 Revit 生效的情況下載入 ``lib\\`` 底下的一支模組。

    薄殼按鈕（停車位、施工架、門窗表、機房門檻、高隔間）本體只有 10～30 行，
    真正的邏輯在 ``lib\\<x>.py`` 的 ``run()`` 裡。那種按鈕沒有 ``main()`` 可以
    拆，要驅動的是 lib 模組的 ``run()``——這支就是拿它的。

    刻意**不** import 進 ``sys.modules``：每次呼叫都給一份新的模組物件，測試改了
    它的屬性也不會外溢到別支測試。（``install()`` 離開時也會把 install 期間才載入
    的 lib 模組清掉，兩層保險。）
    """
    # path 可覆寫，讓突變測試能載入改過的副本（正常使用不用傳）
    path = path or lib_path(name)
    if not os.path.exists(path):
        raise AssertionError('找不到 {0}（{1}）'.format(name, path))
    with io.open(path, encoding='utf-8') as handle:
        source = handle.read()
    module = types.ModuleType(str(name))
    module.__file__ = path
    exec(compile(source, path, 'exec'), module.__dict__)
    return module


def load_button(script_path, module_name=None, entrypoint='main'):
    """載入按鈕模組，但**不執行**檔尾那行進入點呼叫。

    pyRevit 的按鈕是 import 即執行，所以要在呼叫 ``main()`` 之前置換
    ``collect_data`` 之類的接縫，就必須把那一行先拆掉。拆之前會確認它確實存在
    且只有一行——「有人把進入點刪了」或「進入點被呼叫兩次」都會在這裡失敗。

    回傳的模組其餘部分（imports、常數、模組層的 ``doc = revit.doc``）都照原樣
    執行過，行號也維持不變，traceback 指得回原始碼的正確行。
    """
    with io.open(script_path, encoding='utf-8') as handle:
        source = handle.read()

    tree = ast.parse(source, script_path)
    calls = _entrypoint_nodes(tree.body, entrypoint)
    if len(calls) != 1:
        raise AssertionError(
            '{0} 的模組層應該正好有一個 `{1}()` 進入點，實際找到 {2} 個'.format(
                os.path.basename(script_path), entrypoint, len(calls)))

    node, container = calls[0]
    entry_line = node.lineno
    container[:] = [item for item in container if item is not node]
    # try 的 body 不能空著；拆掉唯一那行之後補一個 pass
    if not container:
        container.append(ast.Pass(lineno=entry_line, col_offset=0))
    ast.fix_missing_locations(tree)

    module = types.ModuleType(str(
        module_name or os.path.basename(os.path.dirname(script_path))))
    module.__file__ = script_path
    module.__dict__['__entrypoint_line__'] = entry_line
    exec(compile(tree, script_path, 'exec'), module.__dict__)
    return module
