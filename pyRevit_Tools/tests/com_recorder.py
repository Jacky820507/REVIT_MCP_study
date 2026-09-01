# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""記錄 Excel COM 呼叫序列，供「golden 回歸」比對用。

## 為什麼需要這一支

像 ``scaffold_excel`` 這種直接操作 Excel COM 物件（``ws.Range(...).Font.Name = ...``、
``ws.Cells(row, col).Formula = ...``）的模組，寫出來的東西沒有檔案可以比對——
不像 ``write_xlsx`` 那種自己組 zip，這裡整條路都是 COM 呼叫本身。

這支的辦法：把「對工作表下了哪些指令」全部記下來，每一次屬性存取／設定、每一次
方法呼叫都變成一行文字。重構前後跑同一份 fixture、比對序列——序列不變，代表
寫進使用者活頁簿的東西沒有變。``NoHandWrittenAddressesTests`` 那類重構
（把手寫的 ``Cells(row, 6)`` 換成 ``Cells(row, SUBTOTAL_COLS['quantity'])``）
就是靠這個證明沒有動到實際行為。

## 用法

    journal = []
    recorder = CommandRecorder(journal)
    module._ensure_audit_sheet(recorder)
    # journal 現在是一串 'CALL ws.Range(...)' / 'SET ws.Cells(...).Value2 = ...'

日期／時間這類每次跑都不同的值，用 ``normalize()`` 換成固定佔位字串，
golden 才不會因為「現在幾點」而假性失敗。
"""

import re


__all__ = ['CommandRecorder', 'normalize']


_TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')


def normalize(value):
    """把易變的值（時間戳）換成固定字串，其餘原樣返回。"""
    if isinstance(value, CommandRecorder):
        return '<rec {0}>'.format(object.__getattribute__(value, '_path'))
    if isinstance(value, type(u'')) and _TIMESTAMP.match(value):
        return '<TIMESTAMP>'
    return value


class CommandRecorder(object):
    """記錄所有屬性存取／設定與方法呼叫的假 COM 物件。

    每個屬性存取都回傳一個新的 ``CommandRecorder``（路徑往下疊），呼叫則把完整
    呼叫式寫進共用的 journal 清單。用 ``object.__setattr__``／``__getattr__`` 是因為
    這個物件本身要偽裝成任意深度的 COM 物件圖，不能真的定義那些屬性。
    """

    def __init__(self, journal, path='obj'):
        object.__setattr__(self, '_journal', journal)
        object.__setattr__(self, '_path', path)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return CommandRecorder(self._journal,
                               '{0}.{1}'.format(self._path, name))

    def __setattr__(self, name, value):
        self._journal.append('SET {0}.{1} = {2!r}'.format(
            self._path, name, normalize(value)))

    def __call__(self, *args, **kwargs):
        arg_text = ', '.join(
            [repr(normalize(a)) for a in args] +
            ['{0}={1!r}'.format(k, normalize(v))
             for k, v in sorted(kwargs.items())])
        call_path = '{0}({1})'.format(self._path, arg_text)
        self._journal.append('CALL {0}'.format(call_path))
        return CommandRecorder(self._journal, call_path)
