# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""從 pyRevit（IronPython 2.7）呼叫 CPython 3 的 ``pdf_diff_worker``。

本 repo 之前沒有任何「pyRevit 按鈕呼叫外部 Python」的前例——C# 端的
``DwgBeamExecutor`` 只是 ``FileName = "python"`` 靠 PATH 碰運氣，而 issue #93
記錄的正是那樣做的後果：多版本環境下「裝了但叫到另一支」跟「沒裝」的症狀
一模一樣，使用者無從判斷。所以這個模組的重點不是「跑起來」，是**跑不起來時
講得出到底發生什麼事**。

雙執行環境：
- IronPython 2.7（pyRevit 按鈕）→ 走 ``System.Diagnostics.Process``，
  對編碼與隱藏視窗的控制比 IronPython 的 ``subprocess`` 可靠。
- CPython 3（pytest）→ 走 ``subprocess``，讓純函式部分能離線測試。
"""

import json
import os
import tempfile


WORKER_NAME = 'pdf_diff_worker.py'

# 明確指定直譯器的逃生口。多版本環境下這是唯一能一槍解決的辦法，
# 所以它排在所有自動偵測之前。
PYTHON_ENV_VAR = 'REVITMCP_PDF_PYTHON'


def worker_path():
    """worker 就在本模組旁邊——兩個檔案都在 ``lib/``，跟著 junction 走。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        WORKER_NAME)


def python_candidates(environ=None):
    """回傳要依序嘗試的直譯器命令，每一筆是一個參數 list。

    順序有意義：

    1. 環境變數指定的——使用者已經明講了，不要自作聰明。
    2. ``py -3``——Windows 官方啟動器，比 PATH 上的 ``python`` 可靠，
       因為後者常常被 Microsoft Store 的殼或 conda 的 shim 佔住。
    3. ``python`` / ``python3``——PATH 上的。
    4. 常見安裝路徑——PATH 沒設好時的最後手段。

    做成純函式（吃 ``environ`` 參數而不是直接讀 ``os.environ``）是為了
    能測順序，不必真的動到環境。
    """
    environ = environ if environ is not None else os.environ
    candidates = []

    override = environ.get(PYTHON_ENV_VAR)
    if override:
        candidates.append([override])

    candidates.append(['py', '-3'])
    candidates.append(['python'])
    candidates.append(['python3'])

    local = environ.get('LOCALAPPDATA')
    if local:
        base = os.path.join(local, 'Programs', 'Python')
        for minor in range(13, 6, -1):
            candidates.append(
                [os.path.join(base, 'Python3{}'.format(minor), 'python.exe')])

    return candidates


def build_options(pdf_a, pdf_b, output_path, overrides=None):
    """組出 worker 的 args JSON。

    只放呼叫端明確給的值，其餘一律讓 worker 用它自己的預設——把預設值
    複製到這裡，日後改一邊忘記改另一邊，就會出現「調了參數沒反應」。
    """
    options = {'pdfA': pdf_a, 'pdfB': pdf_b, 'outputPath': output_path}
    for key, value in (overrides or {}).items():
        if value is not None:
            options[key] = value
    return options


def interpret_failure(exit_code, stdout, stderr, tried):
    """把 worker 的失敗轉成使用者看得懂、照著做得到的訊息。

    worker 自己回報的 ``error`` 欄位最有價值（它知道是哪一支 Python、
    缺什麼套件），所以優先使用；解析不出來才退回原始輸出。
    """
    detail = None
    if stdout:
        try:
            payload = json.loads(stdout)
            detail = payload.get('error')
            if payload.get('python'):
                detail = u'{}\n（實際執行的是 {}）'.format(
                    detail, payload.get('python'))
        except (ValueError, AttributeError):
            detail = None

    if not detail:
        detail = (stderr or stdout or u'(沒有輸出)').strip()

    lines = [u'PDF 比對失敗（exit code {}）'.format(exit_code), u'', detail]
    if tried:
        lines.append(u'')
        lines.append(u'嘗試過的直譯器：{}'.format(
            u'、'.join(u' '.join(c) for c in tried)))
    lines.append(u'')
    lines.append(u'若是缺套件，請在該支 Python 執行：pip install pymupdf')
    lines.append(u'若是叫到錯的 Python，可設環境變數 {} 指定路徑。'.format(
        PYTHON_ENV_VAR))
    return u'\n'.join(lines)


def _run_process(command, timeout_seconds):
    """執行外部命令，回傳 ``(exit_code, stdout, stderr)``。

    IronPython 走 .NET 的 Process：可以明確指定 UTF-8 讀取輸出，也能真的
    把主控台視窗藏起來（``subprocess`` 在 IronPython 下有時會閃一個黑框）。
    """
    try:
        from System.Diagnostics import Process, ProcessStartInfo
        from System.Text import Encoding
    except ImportError:
        return _run_process_subprocess(command, timeout_seconds)

    info = ProcessStartInfo()
    info.FileName = command[0]
    info.Arguments = ' '.join(_quote(a) for a in command[1:])
    info.UseShellExecute = False
    info.CreateNoWindow = True
    info.RedirectStandardOutput = True
    info.RedirectStandardError = True
    info.StandardOutputEncoding = Encoding.UTF8
    info.StandardErrorEncoding = Encoding.UTF8

    process = Process()
    process.StartInfo = info
    process.Start()
    stdout = process.StandardOutput.ReadToEnd()
    stderr = process.StandardError.ReadToEnd()
    if not process.WaitForExit(int(timeout_seconds * 1000)):
        try:
            process.Kill()
        except Exception:
            pass
        return (-1, stdout, u'逾時（超過 {} 秒）'.format(timeout_seconds))
    return (process.ExitCode, stdout, stderr)


def _run_process_subprocess(command, timeout_seconds):
    """CPython 3 的路徑，只在測試環境走到。"""
    import subprocess
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    out, err = process.communicate()
    decode = lambda b: b.decode('utf-8', 'replace') if b else ''
    return (process.returncode, decode(out), decode(err))


def _quote(argument):
    text = u'{}'.format(argument)
    if ' ' in text and not text.startswith('"'):
        return u'"{}"'.format(text)
    return text


def probe_python(command, timeout_seconds=20):
    """確認這一支直譯器能匯入 fitz。

    只確認「跑得起來」是不夠的——真正的失敗模式是「Python 有，但那一支
    沒裝 pymupdf」。不先探測就直接跑，使用者會等完整趟比對才拿到錯誤。
    """
    probe = list(command) + ['-c', 'import fitz']
    try:
        code, _, _ = _run_process(probe, timeout_seconds)
        return code == 0
    except Exception:
        return False


def resolve_python(environ=None):
    """找出第一支「跑得起來且有 pymupdf」的直譯器。

    回傳 ``(command, tried)``；全部失敗時 command 為 None，``tried`` 讓
    錯誤訊息能列出到底試過哪些。
    """
    tried = []
    for candidate in python_candidates(environ):
        if len(candidate) == 1 and os.path.sep in candidate[0]:
            if not os.path.exists(candidate[0]):
                continue
        tried.append(candidate)
        if probe_python(candidate):
            return (candidate, tried)
    return (None, tried)


def run_worker(pdf_a, pdf_b, overrides=None, timeout_seconds=900,
               environ=None):
    """跑一趟比對，回傳 worker 的結果 dict。

    失敗時丟 :class:`RuntimeError`，訊息已經是可以直接顯示給使用者的內容。

    結果走**檔案**而不是 stdout：百頁圖說的 JSON 可能上看數 MB，
    管線緩衝區塞爆會造成 deadlock，而且那種當掉看起來就像「程式沒反應」。
    """
    command, tried = resolve_python(environ)
    if command is None:
        raise RuntimeError(
            u'找不到可用的 Python 3（需要安裝 pymupdf）。\n\n'
            u'嘗試過：{}\n\n'
            u'請安裝 Python 3 並執行 pip install pymupdf，\n'
            u'或設環境變數 {} 指向正確的 python.exe。'.format(
                u'、'.join(u' '.join(c) for c in tried) or u'(無)',
                PYTHON_ENV_VAR))

    handle, args_path = tempfile.mkstemp(suffix='.json', prefix='pdfdiff_args_')
    os.close(handle)
    handle, result_path = tempfile.mkstemp(suffix='.json',
                                           prefix='pdfdiff_result_')
    os.close(handle)

    try:
        options = build_options(pdf_a, pdf_b, result_path, overrides)
        stream = open(args_path, 'wb')
        try:
            stream.write(json.dumps(options).encode('utf-8'))
        finally:
            stream.close()

        code, stdout, stderr = _run_process(
            list(command) + [worker_path(), args_path], timeout_seconds)
        if code != 0:
            raise RuntimeError(interpret_failure(code, stdout, stderr, tried))

        stream = open(result_path, 'rb')
        try:
            return json.loads(stream.read().decode('utf-8'))
        finally:
            stream.close()
    finally:
        for path in (args_path, result_path):
            try:
                os.remove(path)
            except OSError:
                pass
