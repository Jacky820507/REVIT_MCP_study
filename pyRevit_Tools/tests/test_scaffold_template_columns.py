# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""把 ``scaffold_excel`` 的範本欄位對照表釘死在它們該有的字母上。

## 為什麼需要這一支

``scaffold_excel`` 會把公式寫進**使用者自己的工項活頁簿**（小計／其他面積／
更新工項三張分頁）。那些分頁的欄位順序不是我們排的，所以程式裡用的是欄號
（``Cells(sr, 6)``）。但同一個欄位在公式裡又要以字母出現（``'小計'!F12``），
以前那個字母是手寫的——寫入寫一次、``_validate_written_workbook`` 再寫一次、
警告訊息又寫一次，一個欄位三個各自維護的地方。

2026-08-31 把字母改成由對照表導出（``_sheet_ref``）。這樣做的等價性是可證的：
``_sheet_ref`` 就是 ``'{}!{}{}'.format(_quote_sheet(s), _col_letter(c), r)``，
所以只要 ``_col_letter(對照表[key])`` 等於原本那個字母，產出的字串就一模一樣。
**這支測試就是那個證明義務。** 對照表被改動、或者哪天範本真的換了欄位，這裡會先
失敗，而不是等到公式指到隔壁欄才在使用者的活頁簿上發現。
"""

import os
import unittest

import revit_stub


class ScaffoldTemplateColumnTests(unittest.TestCase):
    def setUp(self):
        self._ctx = revit_stub.install(answers={})
        self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.module = revit_stub.load_lib('scaffold_excel')

    def letter(self, number):
        return self.module._col_letter(number)

    # -- 三張範本分頁 ------------------------------------------------------

    def test_subtotal_columns_keep_their_letters(self):
        expected = {'code': 'B', 'name': 'C', 'unit': 'E',
                    'rounded_qty': 'F', 'source': 'G', 'quantity': 'H'}
        actual = dict((key, self.letter(number))
                      for key, number in self.module.SUBTOTAL_COLS.items())
        self.assertEqual(expected, actual)

    def test_other_area_columns_keep_their_letters(self):
        expected = {'code': 'B', 'name': 'C', 'level': 'D', 'count': 'E',
                    'length': 'F', 'height': 'H', 'subtotal': 'I',
                    'total': 'P'}
        actual = dict((key, self.letter(number))
                      for key, number in self.module.OTHER_COLS.items())
        self.assertEqual(expected, actual)

    def test_update_item_columns_keep_their_letters(self):
        expected = {'name': 'B', 'unit': 'C', 'rounded_qty': 'D',
                    'source': 'E', 'quantity': 'F'}
        actual = dict((key, self.letter(number))
                      for key, number in self.module.UPDATE_COLS.items())
        self.assertEqual(expected, actual)

    # -- 我們自己的稽核表 --------------------------------------------------

    def test_the_audit_quantity_column_is_the_one_others_reference(self):
        """其他面積分頁的公式指向稽核表的「數量」欄，以前寫死成 B。"""
        self.assertEqual(
            'B', self.letter(self.module.AUDIT_SUMMARY.number('quantity')))

    def test_room_audit_last_col_is_derived_not_hand_counted(self):
        """ROOM_AUDIT_LAST_COL 以前是手寫的 23，必須等於欄位數。"""
        self.assertEqual(len(self.module.ROOM_AUDIT_COLUMNS),
                         self.module.ROOM_AUDIT_LAST_COL)
        self.assertEqual(23, self.module.ROOM_AUDIT_LAST_COL,
                         '欄位數變了要一併確認範本與樓層小計的位置')

    # -- _sheet_ref 本身 ---------------------------------------------------

    def test_sheet_ref_builds_a_quoted_cross_sheet_address(self):
        ref = self.module._sheet_ref(u'小計',
                                     self.module.SUBTOTAL_COLS['quantity'], 12)
        self.assertEqual(u"'小計'!H12", ref)

    def test_the_level_summary_column_stays_clear_of_the_room_audit(self):
        """樓層小計必須留在逐房明細右邊，中間空兩欄；重疊會蓋掉來源證據。"""
        self.assertGreater(self.module.LEVEL_SUMMARY_LEVEL_COL,
                           self.module.ROOM_AUDIT_LAST_COL + 1)


class ParkingTemplateColumnTests(unittest.TestCase):
    """停車位那顆的「其他數量」分頁同樣有三重表示，對照表一樣要釘住。"""

    def setUp(self):
        self._ctx = revit_stub.install(answers={})
        self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.module = revit_stub.load_lib('parking_excel')

    def test_quantity_columns_keep_their_letters(self):
        self.assertEqual('F', self.module._col(self.module.OTHER_COUNT_COL))
        self.assertEqual('G', self.module._col(self.module.OTHER_WHEEL_COL))

    def test_addr_builds_the_message_address(self):
        self.assertEqual(
            u'其他數量!F12',
            self.module._addr(self.module.OTHER_SHEET,
                              self.module.OTHER_COUNT_COL, 12))

    def test_the_two_columns_are_adjacent(self):
        """F 是數量、G 是輪檔倍率，訊息裡以 F/G 成對出現；相鄰是前提。"""
        self.assertEqual(self.module.OTHER_COUNT_COL + 1,
                         self.module.OTHER_WHEEL_COL)


class NoHandWrittenAddressesTests(unittest.TestCase):
    """**整個 extension** 都不該再出現手寫的 Excel 欄位字母。

    2026-08-31 掃完的結果是 0。欄位字母一律由 ``sheet_layout``（我們自己排版的
    表）或欄位對照表（使用者範本的分頁）產生；真正恆定的位址——工作表原點 A1
    ——以 ``# sheet-layout: ignore`` 標註豁免，docstring 內的說明文字不算。

    這條是**事前禁止**：只要沒有人手寫字母，「欄位一搬動、公式安靜指到隔壁欄」
    那類 bug 就寫不出來。其他測試裡「字母對不對得上表頭」的斷言是事後偵測，
    兩者並存。
    """

    SKIP = ('__pycache__', '.backup', '.disabled')

    def source_files(self):
        root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', 'MCP_Tools.extension'))
        for folder, _dirs, files in os.walk(root):
            if any(mark in folder for mark in self.SKIP):
                continue
            for name in files:
                if name.endswith('.py'):
                    yield os.path.join(folder, name)

    def test_the_whole_extension_is_clean(self):
        import takeoff_harness as harness
        offenders = {}
        for path in self.source_files():
            found = harness.hand_written_addresses(path)
            if found:
                offenders[os.path.basename(path)] = found
        self.assertEqual(
            {}, offenders,
            '這些檔案還在手寫欄位字母，改用 sheet_layout／欄位對照表：\n'
            + '\n'.join('{0}:\n  {1}'.format(k, '\n  '.join(v))
                        for k, v in sorted(offenders.items())))


if __name__ == '__main__':
    unittest.main()
