# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""用欄位名稱寫公式，欄位字母交給程式在最後一刻算出來。

## 為什麼有這支

數量計算表的公式現在長這樣：

    row[16] = '=P{0}*G{0}'.format(r)
    row[18] = '=Q{0}-R{0}'.format(r)

索引 ``16`` 與字母 ``P``、``G`` 是**兩套各自維護的真相**，靠人記得同步。中間插一欄，
索引全部位移、字母一個都不會動——公式不會壞掉、不會報錯，只是從此指向隔壁那一欄。
「污水處理廠那本活頁簿的 ``$V``」就是這麼來的。

這支把欄位字母收回程式手上。你只寫名字：

    row[L.index('gross_volume')] = L.formula(r, '{net_area}*{thickness}')

``{net_area}`` 在寫檔那一刻才解析成 ``P6``。要插一欄就改 ``COLUMNS`` 清單一行，
所有公式自動重解。**同一份原始碼裡不該再出現第二個手寫的欄位字母。**

想法來自 open-sheet（`packages/core/src/formula`）：references, not addresses。
那邊是 TypeScript 的運算式樹，這裡是 IronPython 2.7 跑得動的最小版本——只做
「名字 → 位址」這一段，不做求值。

## 用法

    L = SheetLayout(['room_no', 'room_name', 'length', 'height', 'area'],
                    first_data_row=6)

    L.col('area')            -> 'E'
    L.cell('area', 6)        -> 'E6'
    L.rng('area', 6, 20)     -> 'E6:E20'
    L.formula(6, '{length}*{height}')          -> '=C6*D6'
    L.formula(6, '{area}-{area@1}')            -> '=E6-E7'      （下一列）
    L.sum_of('area', 6, 20)                    -> '=SUM(E6:E20)'

    row = L.blank_row()
    L.put(row, 'area', L.formula(6, '{length}*{height}'))

動態欄（例如每種牆型一欄）用 ``with_columns`` 接在固定欄後面：

    full = L.with_columns(wall_type_cols)
    full.cell(wall_type_cols[0], 6)

打錯名字會當場丟 ``UnknownColumn``，訊息裡列出有哪些欄位可用——不會安靜地
算出一個看起來很像對的位址。

## 不做什麼

不求值、不管樣式、不管合併儲存格。它只回字串，寫進哪一格仍然是呼叫端的事。
"""

import re


__all__ = ['SheetLayout', 'UnknownColumn', 'column_letter']


_TOKEN = re.compile(r'\{([^{}]+)\}')


class UnknownColumn(KeyError):
    """公式或存取用到了這張表沒有的欄位名稱。"""


def column_letter(index):
    """0 基欄位索引 → Excel 欄位字母（0 → 'A'，25 → 'Z'，26 → 'AA'）。"""
    if index < 0:
        raise ValueError('欄位索引不能是負數：{0}'.format(index))
    result = ''
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


class SheetLayout(object):
    """一張表的欄位順序，以及由它導出的所有位址。"""

    def __init__(self, columns, first_data_row=1, name=''):
        keys = list(columns)
        seen = {}
        for position, key in enumerate(keys):
            if key in seen:
                raise ValueError(
                    '欄位名稱重複：「{0}」同時在第 {1} 與第 {2} 欄'.format(
                        key, seen[key] + 1, position + 1))
            seen[key] = position
        self._keys = keys
        self._index = seen
        self.first_data_row = first_data_row
        self.name = name

    # -- 基本 --------------------------------------------------------------

    def __len__(self):
        return len(self._keys)

    @property
    def width(self):
        return len(self._keys)

    @property
    def keys(self):
        return list(self._keys)

    def has(self, key):
        return key in self._index

    def index(self, key):
        """0 基欄位索引。"""
        try:
            return self._index[key]
        except KeyError:
            raise UnknownColumn(self._unknown_message(key))

    def _unknown_message(self, key):
        return (
            '{0}沒有「{1}」這一欄。可用的欄位：{2}'.format(
                '「{0}」'.format(self.name) if self.name else '這張表',
                key, '、'.join(self._keys)))

    # -- 位址 --------------------------------------------------------------

    def col(self, key):
        return column_letter(self.index(key))

    def number(self, key):
        """1 基欄號，給 Excel COM 的 ``ws.Cells(row, col)`` 用。"""
        return self.index(key) + 1

    def cell(self, key, row):
        return '{0}{1}'.format(self.col(key), row)

    def rng(self, key, first_row, last_row):
        col = self.col(key)
        return '{0}{1}:{0}{2}'.format(col, first_row, last_row)

    def rect(self, first_key, last_key, first_row, last_row=None):
        """矩形範圍，例如 ``rect('item', 'updated_at', 3, 6)`` → ``'A3:E6'``。"""
        if last_row is None:
            last_row = first_row
        return '{0}{1}:{2}{3}'.format(self.col(first_key), first_row,
                                      self.col(last_key), last_row)

    # -- 列 ----------------------------------------------------------------

    def blank_row(self):
        return [''] * self.width

    def put(self, row, key, value):
        row[self.index(key)] = value
        return row

    def get(self, row, key):
        return row[self.index(key)]

    def row_from(self, mapping):
        """用 ``{'欄位名': 值}`` 組一列，缺的欄位留空。"""
        row = self.blank_row()
        for key, value in mapping.items():
            self.put(row, key, value)
        return row

    # -- 公式 --------------------------------------------------------------

    def formula(self, row, template):
        """把 ``{欄位名}`` 換成該列的位址，回傳前面帶 ``=`` 的公式字串。

        ``{key}``        本列的那一格
        ``{key@n}``      往下第 n 列的那一格（``@-1`` 就是上一列）
        ``{key:a:b}``    a 到 b 列的範圍
        """
        return '=' + self.expr(row, template)

    def expr(self, row, template):
        """同 ``formula``，但不加 ``=``；用在要串進更大一段字串的時候。"""

        def replace(match):
            token = match.group(1)
            if ':' in token:
                key, first, last = token.split(':', 2)
                return self.rng(key.strip(), first.strip(), last.strip())
            if '@' in token:
                key, offset = token.split('@', 1)
                return self.cell(key.strip(), row + int(offset))
            return self.cell(token.strip(), row)

        return _TOKEN.sub(replace, template)

    def sum_of(self, key, first_row, last_row):
        return '=SUM({0})'.format(self.rng(key, first_row, last_row))

    # -- 動態欄 ------------------------------------------------------------

    def with_columns(self, extra):
        """在固定欄後面接上動態欄（每種牆型一欄之類），回傳新的 layout。"""
        return SheetLayout(self._keys + list(extra),
                           first_data_row=self.first_data_row,
                           name=self.name)
