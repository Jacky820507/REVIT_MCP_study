# -*- coding: utf-8 -*-
"""RevitMCP DLL 橋接層 — pyRevit 按鈕直呼已載入的 RevitMCP.dll。

原理：pyRevit 腳本跑在 Revit 行程內的 UI 執行緒（API context），
可直接建構 RevitMCP 的 CommandExecutor 並呼叫 ExecuteCommand，
與 MCP Server 走同一套 C# 演算法——零重寫、不經 WebSocket、
不佔用 8964 連線，MCP 服務未啟動也能用。

需求：RevitMCP add-in 已安裝並載入（scripts/install-addon.ps1）。
"""

import json
import math
import os

import clr
from pyrevit import forms, HOST_APP

_executor = None
_json_api = None


class MCPBridgeError(Exception):
    """RevitMCP 命令執行失敗。"""
    pass


# IronPython 2.7 的 ``json.dumps`` 在某些 Revit 執行環境會先把 unicode
# 當成 ASCII ``str``，即使呼叫端要求 ensure_ascii，也可能在這一步就丟
# UnicodeEncodeError。這條橋接的參數常含圖紙名稱、備註與 ``[自動]``，所以
# 不能讓編碼行為取決於目前 Revit 行程載入的 Python runtime。
try:
    _TEXT_TYPE = unicode
except NameError:  # pragma: no cover - CPython 3 的相容分支
    _TEXT_TYPE = str

try:
    _STRING_TYPES = (basestring,)
except NameError:  # pragma: no cover - CPython 3 的相容分支
    _STRING_TYPES = (str, bytes)

try:
    _INTEGER_TYPES = (int, long)
except NameError:  # pragma: no cover - CPython 3 的相容分支
    _INTEGER_TYPES = (int,)


def _to_unicode(value):
    """把橋接參數內的文字轉成 unicode，不讓 Python 2 默認用 ASCII 解碼。"""
    if isinstance(value, _TEXT_TYPE):
        return value

    # Python 2 的 bytes 是 str；Python 3 則是獨立的 bytes 型別。UTF-8 是
    # pyRevit/PDF 差異資料的唯一合理來源編碼，失敗時用 latin-1 保留每個
    # byte，仍交由下方的 JSON escape 處理，不在送出前再次觸發 ASCII 錯誤。
    try:
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                return value.decode('latin-1')
    except NameError:  # pragma: no cover - 舊版 Python 沒有 bytes 名稱
        pass

    try:
        return unicode(value)
    except NameError:  # pragma: no cover - CPython 3
        return str(value)


def _escape_json_string(value):
    """回傳只含 ASCII 的 JSON 字串 literal。"""
    value = _to_unicode(value)
    escaped = []
    for char in value:
        code = ord(char)
        if char == u'"':
            escaped.append(u'\\"')
        elif char == u'\\':
            escaped.append(u'\\\\')
        elif char == u'\b':
            escaped.append(u'\\b')
        elif code == 0x0c:
            # 用 unicode escape 避免 pyRevit 的 Python 3 語法掃描器把
            # ``\\f`` 誤認成 f-string 前綴；JSON 解析結果完全相同。
            escaped.append(u'\\u000c')
        elif char == u'\n':
            escaped.append(u'\\n')
        elif char == u'\r':
            escaped.append(u'\\r')
        elif char == u'\t':
            escaped.append(u'\\t')
        elif code < 0x20:
            escaped.append(u'\\u%04x' % code)
        elif code < 0x80:
            escaped.append(char)
        elif code <= 0xffff:
            escaped.append(u'\\u%04x' % code)
        else:
            # 寬版 unicode 可能直接迭代出 BMP 以外的 code point；JSON
            # escape 用 UTF-16 surrogate pair，Newtonsoft.Json 可正確還原。
            code -= 0x10000
            high = 0xd800 + (code >> 10)
            low = 0xdc00 + (code & 0x3ff)
            escaped.append(u'\\u%04x\\u%04x' % (high, low))
    return u'"' + u''.join(escaped) + u'"'


def _json_dumps_for_bridge(value):
    """序列化給 RevitMCP 的參數，保證結果只含 ASCII 字元。

    參數格式目前是 dict/list/字串/數值的 JSON 子集。手動產生 escape 後，
    IronPython 不需要把中文先轉成 ASCII ``str``；反序列化仍由同一份
    Newtonsoft.Json（``JObject.Parse``）處理，因此中文內容不會遺失。
    """
    if value is None:
        return u'null'
    if value is True:
        return u'true'
    if value is False:
        return u'false'
    if isinstance(value, _INTEGER_TYPES):
        return u'%d' % value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return u'null'
        return _to_unicode(repr(value))
    if isinstance(value, (list, tuple)):
        return u'[' + u','.join(
            _json_dumps_for_bridge(item) for item in value) + u']'
    if isinstance(value, dict):
        pairs = []
        for key, item in value.items():
            pairs.append(_escape_json_string(key) + u':' +
                         _json_dumps_for_bridge(item))
        return u'{' + u','.join(pairs) + u'}'
    if isinstance(value, _STRING_TYPES):
        return _escape_json_string(value)

    # 維持 json.dumps 對未知型別的失敗語意，避免把 Revit 物件默默轉成
    # 不可預期的文字並送進 C#。
    raise TypeError('Object of type {} is not JSON serializable'.format(
        type(value).__name__))


def _ensure_assembly():
    """確認 RevitMCP.dll 可用；未載入時嘗試從 Add-ins 目錄載入。"""
    try:
        clr.AddReference('RevitMCP')
        return
    except Exception:
        pass

    appdata = os.environ.get('APPDATA', '')
    version = HOST_APP.version
    dll = os.path.join(appdata, 'Autodesk', 'Revit', 'Addins',
                       str(version), 'RevitMCP', 'RevitMCP.dll')
    if os.path.exists(dll):
        clr.AddReferenceToFileAndPath(dll)
        return

    forms.alert(
        '找不到 RevitMCP.dll（Revit {}）。\n\n'
        '請先安裝 RevitMCP add-in：\n'
        '  scripts\\install-addon.ps1\n\n'
        '安裝後重啟 Revit 再使用本按鈕。'.format(version),
        title='MCP 橋接', exitscript=True)


def _get_executor():
    global _executor
    if _executor is None:
        _ensure_assembly()
        from RevitMCP.Core import CommandExecutor
        _executor = CommandExecutor(HOST_APP.uiapp)
    return _executor


def _get_json_api():
    """取得「RevitMCP.dll 實際綁定的那一份」Newtonsoft.Json 的 JObject.Parse
    與 JsonConvert.SerializeObject。

    ⚠️ 不能用 clr.AddReference('Newtonsoft.Json')：pyRevit 環境可能載入
    不同版本的 Newtonsoft.Json，Python 端建出的 JObject 在 C# 端
    `request.Parameters as JObject` 跨組件轉型會失敗、整包參數靜默變空
    （症狀：帶參數的按鈕一律報 Parameter 'xxx' is required）。
    """
    global _json_api
    if _json_api is None:
        import System
        from System.Reflection import Assembly
        from RevitMCP.Core import CommandExecutor

        mcp_asm = clr.GetClrType(CommandExecutor).Assembly
        newtonsoft_name = None
        for ref in mcp_asm.GetReferencedAssemblies():
            if ref.Name == 'Newtonsoft.Json':
                newtonsoft_name = ref
                break
        if newtonsoft_name is None:
            raise MCPBridgeError(u'RevitMCP.dll 未參考 Newtonsoft.Json，橋接無法建構參數')
        newtonsoft = Assembly.Load(newtonsoft_name)

        str_type = clr.GetClrType(System.String)
        obj_type = clr.GetClrType(System.Object)
        parse = newtonsoft.GetType('Newtonsoft.Json.Linq.JObject') \
                          .GetMethod('Parse', System.Array[System.Type]([str_type]))
        serialize = newtonsoft.GetType('Newtonsoft.Json.JsonConvert') \
                              .GetMethod('SerializeObject', System.Array[System.Type]([obj_type]))
        _json_api = (parse, serialize)
    return _json_api


def run(command, params=None):
    """執行一個 RevitMCP 命令，回傳 Data（dict/list/純值）。

    失敗時丟出 MCPBridgeError，訊息為 C# 端的 Error 字串。
    """
    _ensure_assembly()
    import System
    from RevitMCP.Models import RevitCommandRequest
    parse, serialize = _get_json_api()

    req = RevitCommandRequest()
    req.CommandName = command
    # 先產生只含 ASCII 的 JSON，再明確包成 System.String；這避開
    # IronPython 2.7 將 unicode 參數隱式轉成 ASCII 的問題。
    parameters_json = System.String(_json_dumps_for_bridge(params or {}))
    req.Parameters = parse.Invoke(
        None, System.Array[System.Object]([parameters_json]))
    req.RequestId = 'pyrevit-button'

    resp = _get_executor().ExecuteCommand(req)
    if not resp.Success:
        raise MCPBridgeError(u'{}: {}'.format(command, resp.Error))
    if resp.Data is None:
        return None
    return json.loads(serialize.Invoke(
        None, System.Array[System.Object]([resp.Data])))


def brief(data, max_lines=18):
    """把結果的頂層純值欄位整理成人可讀摘要（供 alert 顯示）。"""
    if data is None:
        return u'(無回傳資料)'
    if not isinstance(data, dict):
        return u'{}'.format(data)
    lines = []
    for key in data:
        value = data[key]
        if isinstance(value, (list, dict)):
            lines.append(u'{}: {} 筆'.format(key, len(value)))
        else:
            lines.append(u'{}: {}'.format(key, value))
        if len(lines) >= max_lines:
            lines.append(u'…')
            break
    return u'\n'.join(lines)


def dry_run_then_apply(command, preview_params, apply_params, title,
                       summarize=None):
    """通用「dry-run → 確認視窗 → 套用」流程。

    summarize(data) 可自訂預覽文字；預設用 brief()。
    使用者取消時回傳 None，套用後回傳最終結果 dict。
    """
    preview = run(command, preview_params)
    text = (summarize or brief)(preview)
    if not forms.alert(
            u'【dry-run 預覽】\n\n{}\n\n確定要套用嗎？'.format(text),
            title=title, yes=True, no=True):
        return None
    result = run(command, apply_params)
    forms.alert(u'【已套用】\n\n{}'.format((summarize or brief)(result)),
                title=title)
    return result


def show_error(err, title=u'MCP 橋接'):
    forms.alert(u'執行失敗：\n\n{}'.format(err), title=title)
