# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest
import uuid
import zipfile
from xml.etree import ElementTree


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import takeoff_standalone as standalone


MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


class TakeoffStandaloneTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(
            os.path.dirname(__file__),
            'takeoff-standalone-{}.xlsx'.format(uuid.uuid4().hex))

    def tearDown(self):
        if os.path.isfile(self.path):
            os.remove(self.path)

    def _write(self):
        return standalone.write_standard_workbook(
            self.path,
            [
                {
                    '來源': 'Host',
                    '元素 ID': 101,
                    '數量': 2,
                },
                ['Link A', 202, 3],
            ],
            ['來源', '元素 ID', '數量'],
            [
                ['總數', '=SUM(數量明細!C2:C3)'],
            ],
            ['項目', '公式'],
            [
                ['來源範圍', 'host + link:77'],
            ],
            ['檢查', '結果'],
            '測試算量',
        )

    def test_writes_three_sheet_contract(self):
        result = self._write()
        self.assertEqual(os.path.abspath(self.path), result)
        with zipfile.ZipFile(self.path, 'r') as package:
            workbook = ElementTree.fromstring(
                package.read('xl/workbook.xml'))
            sheets = workbook.find(
                '{{{}}}sheets'.format(MAIN_NS))
            names = [sheet.attrib['name'] for sheet in list(sheets)]
        self.assertEqual(
            ['數量明細', '公式摘要', '稽核'],
            names)

    def test_formula_is_an_excel_formula_not_literal_text(self):
        self._write()
        with zipfile.ZipFile(self.path, 'r') as package:
            summary = ElementTree.fromstring(
                package.read('xl/worksheets/sheet2.xml'))
        formulas = summary.findall('.//{{{}}}f'.format(MAIN_NS))
        self.assertEqual(1, len(formulas))
        self.assertEqual('SUM(數量明細!C2:C3)', formulas[0].text)

    def test_dict_and_sequence_rows_share_header_order(self):
        self._write()
        with zipfile.ZipFile(self.path, 'r') as package:
            detail = ElementTree.fromstring(
                package.read('xl/worksheets/sheet1.xml'))
        cells = dict(
            (cell.attrib['r'], cell)
            for cell in detail.findall('.//{{{}}}c'.format(MAIN_NS)))
        self.assertEqual(
            'Host',
            cells['A2'].find(
                './/{{{}}}t'.format(MAIN_NS)).text)
        self.assertEqual(
            '202',
            cells['B3'].find(
                '{{{}}}v'.format(MAIN_NS)).text)

    def test_rejects_non_xlsx_destination(self):
        with self.assertRaises(ValueError):
            standalone.write_standard_workbook(
                os.path.splitext(self.path)[0] + '.xls',
                [], ['A'], [], ['B'], [], ['C'], 'Bad')

    def test_rejects_wrong_sequence_width(self):
        with self.assertRaises(ValueError):
            standalone.write_standard_workbook(
                self.path,
                [[1]], ['A', 'B'],
                [], ['A'], [], ['A'], 'Bad')

    def test_entry_mode_routes_only_a_nonblank_workbook_to_update(self):
        self.assertEqual(
            standalone.MODE_UPDATE,
            standalone.entry_mode({'workbook_path': 'main.xls'}))
        self.assertEqual(
            standalone.MODE_STANDALONE,
            standalone.entry_mode({'workbook_path': None}))
        self.assertEqual(
            standalone.MODE_STANDALONE,
            standalone.entry_mode({'workbook_path': '   '}))


if __name__ == '__main__':
    unittest.main()
