# -*- coding: utf-8 -*-
"""RevitMCP DLL 橋接層 — pyRevit 按鈕直呼已載入的 RevitMCP.dll。

原理：pyRevit 腳本跑在 Revit 行程內的 UI 執行緒（API context），
可直接建構 RevitMCP 的 CommandExecutor 並呼叫 ExecuteCommand，
與 MCP Server 走同一套 C# 演算法——零重寫、不經 WebSocket、
不佔用 8964 連線，MCP 服務未啟動也能用。

需求：RevitMCP add-in 已安裝並載入（scripts/install-addon.ps1）。
"""

import json
import os

import clr
from pyrevit import forms, HOST_APP

_executor = None
_json_api = None


class MCPBridgeError(Exception):
    """RevitMCP 命令執行失敗。"""
    pass


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
    req.Parameters = parse.Invoke(
        None, System.Array[System.Object]([json.dumps(params or {})]))
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
