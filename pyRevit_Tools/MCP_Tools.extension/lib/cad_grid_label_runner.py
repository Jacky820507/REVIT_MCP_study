# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""從 pyRevit（IronPython 2.7）呼叫 CPython 3 的 ``cad_grid_label_worker``。

找直譯器、藏主控台視窗、UTF-8 讀輸出這些事 ``pdf_diff_runner`` 已經處理過
（而且處理過 issue #93 那種「叫到另一支 Python」的失敗），這裡直接沿用，
只把探測條件從 ``import fitz`` 換成 ``import ezdxf``。

軸號是**加分項**：讀不到時 ``run`` 回傳 ``(None, 原因)``，按鈕退回軸距比對，
不會因此整個失敗。
"""

import json
import os
import tempfile

import pdf_diff_runner as base


WORKER_NAME = 'cad_grid_label_worker.py'
PYTHON_ENV_VAR = 'REVITMCP_CAD_PYTHON'


def worker_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        WORKER_NAME)


def python_candidates(environ=None):
    environ = environ if environ is not None else os.environ
    candidates = []
    override = environ.get(PYTHON_ENV_VAR)
    if override:
        candidates.append([override])
    for candidate in base.python_candidates(environ):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def resolve_python(environ=None):
    tried = []
    for candidate in python_candidates(environ):
        if len(candidate) == 1 and os.path.sep in candidate[0]:
            if not os.path.exists(candidate[0]):
                continue
        tried.append(candidate)
        try:
            code, unused, unused2 = base._run_process(
                list(candidate) + ['-c', 'import ezdxf'], 20)
        except Exception:
            code = -1
        if code == 0:
            return candidate, tried
    return None, tried


def run(files, label_layer, timeout_seconds=600, environ=None):
    """``(result_dict, problem)``。成功時 problem 為空字串。"""
    command, tried = resolve_python(environ)
    if command is None:
        return None, (u'找不到裝有 ezdxf 的 Python 3（試過：{}）。'
                      u'可設環境變數 {} 指定 python.exe。'.format(
                          u'、'.join(u' '.join(c) for c in tried) or u'(無)',
                          PYTHON_ENV_VAR))

    handle, args_path = tempfile.mkstemp(suffix='.json', prefix='cadgrid_args_')
    os.close(handle)
    handle, result_path = tempfile.mkstemp(suffix='.json',
                                           prefix='cadgrid_result_')
    os.close(handle)
    try:
        stream = open(args_path, 'wb')
        try:
            stream.write(json.dumps({'files': list(files),
                                     'labelLayer': label_layer,
                                     'outputPath': result_path})
                         .encode('utf-8'))
        finally:
            stream.close()
        code, stdout, stderr = base._run_process(
            list(command) + [worker_path(), args_path], timeout_seconds)
        if code != 0:
            return None, u'軸號讀取失敗（exit {}）：{}'.format(
                code, (stdout or stderr or u'').strip()[:400])
        stream = open(result_path, 'rb')
        try:
            return json.loads(stream.read().decode('utf-8')), u''
        finally:
            stream.close()
    finally:
        for path in (args_path, result_path):
            try:
                os.remove(path)
            except OSError:
                pass
