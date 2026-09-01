# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""每次跑測試都重新產生輸出，跟 ``tests\\goldens\\*.json`` 逐格逐公式比對。

## 這支跟其他 wiring 測試的分工

``test_*_wiring.py`` 驗的是「行為對不對」（取消會不會提早 return、備份有沒有先
做、報告有沒有印出完成訊息）；這支驗的是「**輸出跟昨天一模一樣**」——沒有斷言
描述期望值是什麼，golden 檔案本身就是期望值。兩者互補：wiring 測試在改壞行為
時能講出「壞在哪」，這支在改壞任何東西時都能當場攔下來，即使沒有人事先想到
要為那個改動寫斷言。

## 什麼時候這支「應該」失敗

只有一種正常情況：你**刻意**改變了某顆按鈕的輸出（換公式、改欄位、調格式）。
這時先跑 ``python tools\\regen_goldens.py <fixture 名稱>`` 重新產生 golden，
看過 diff 確認是預期的改動，再提交。除此之外失敗都代表某處被改壞了。

golden 檔案本身、產生它們的 ``golden_fixtures.py``、以及這支測試，都是
2026-08-31 那輪 SheetLayout 重構驗證過的固化版本——見各檔案的 docstring。
"""

import io
import json
import os
import re
import unittest

import golden_fixtures as gf


def _load_golden(name):
    path = os.path.join(gf.GOLDEN_DIR, name + '.json')
    with io.open(path, encoding='utf-8') as handle:
        return json.load(handle)


def _normalize(payload):
    """跟 golden 走同一趟 JSON 序列化：tuple 會變成 list，兩邊型別才一致。

    ``_workbook_payload`` 產出的 'cols'/'panes' 是 tuple，golden 檔案存的是
    JSON array（讀回來是 list）。不正規化的話 ``[1, 2] != (1, 2)`` 會讓每一顆
    按鈕都假性失敗，跟真的回歸長一樣的錯誤訊息，混淆視聽。
    """
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


_TIMESTAMP_LIKE = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}')


def _scrub_volatile(text):
    """報告字串裡的暫存路徑／時間戳每次跑都不同，比對前先抹平。"""
    text = re.sub(r'golden-[0-9a-zA-Z_]+', '<TMP>', text)
    text = _TIMESTAMP_LIKE.sub('<TIMESTAMP>', text)
    return text


class TakeoffButtonGoldenTests(unittest.TestCase):
    """六顆已移轉 SheetLayout 的按鈕：儲存格、公式、合併範圍、欄寬、凍結窗格。"""

    def _check(self, name):
        golden = _load_golden(name)
        actual = _normalize(gf.TAKEOFF_BUTTONS[name]())
        self.assertEqual(
            golden['cells'], actual['cells'],
            '{0} 的儲存格輸出跟 golden 不同——不是刻意改動的話，某處被改壞了。'
            '若是刻意改動，跑 python tools/regen_goldens.py {0} 更新 golden。'
            .format(name))
        self.assertEqual(
            golden['xml'], actual['xml'],
            '{0} 的合併範圍／欄寬／凍結窗格跟 golden 不同。'.format(name))

    def test_rc_volume_excel(self):
        self._check('rc_volume_excel')

    def test_partition_takeoff(self):
        self._check('partition_takeoff')

    def test_baseboard(self):
        self._check('baseboard')

    def test_interior_wall_paint(self):
        self._check('interior_wall_paint')

    def test_ceiling_takeoff(self):
        self._check('ceiling_takeoff')

    def test_floor_takeoff(self):
        self._check('floor_takeoff')


class ScaffoldExcelGoldenTests(unittest.TestCase):
    """``scaffold_excel``：COM 指令序列（見 com_recorder.py 為什麼要記指令）
    與獨立匯出表。"""

    def test_com_command_sequence(self):
        golden = _load_golden('scaffold_excel_com')
        actual = _normalize(gf.scaffold_excel_com())
        self.assertEqual(
            golden['journal'], actual['journal'],
            'scaffold_excel 寫進使用者活頁簿的 COM 指令序列跟 golden 不同。')

    def test_standalone_tables(self):
        golden = _load_golden('scaffold_excel_standalone')
        actual = _normalize(gf.scaffold_excel_standalone())
        self.assertEqual(golden, actual)


class LogicModuleGoldenTests(unittest.TestCase):
    """三支 ``*_logic`` 的獨立匯出表（公式字串本身）。"""

    def _check(self, name):
        golden = _load_golden(name)
        actual = _normalize(gf.ALL_FIXTURES[name]())
        self.assertEqual(golden, actual)

    def test_parking_excel_logic(self):
        self._check('parking_excel_logic')

    def test_door_window_excel_logic(self):
        self._check('door_window_excel_logic')

    def test_machine_room_threshold_logic(self):
        self._check('machine_room_threshold_logic')


class GoldenFixturesInventoryTests(unittest.TestCase):
    """防止兩邊漂移：``golden_fixtures.ALL_FIXTURES`` 跟磁碟上的 golden 檔案要
    一一對應——加了新 fixture 忘記產生 golden、或刪了 fixture 忘記清 golden，
    這裡會先講。"""

    def test_every_fixture_has_a_golden_file(self):
        missing = [name for name in gf.ALL_FIXTURES
                  if not os.path.exists(
                      os.path.join(gf.GOLDEN_DIR, name + '.json'))]
        self.assertEqual(
            [], missing,
            '這些 fixture 還沒有 golden 檔案，跑 python tools/regen_goldens.py：\n'
            + '\n'.join(missing))

    def test_every_golden_file_has_a_fixture(self):
        if not os.path.isdir(gf.GOLDEN_DIR):
            return
        on_disk = set(f[:-5] for f in os.listdir(gf.GOLDEN_DIR)
                     if f.endswith('.json'))
        orphans = on_disk - set(gf.ALL_FIXTURES)
        self.assertEqual(
            set(), orphans,
            '這些 golden 檔案沒有對應的 fixture 了，可以刪除：\n'
            + '\n'.join(sorted(orphans)))


if __name__ == '__main__':
    unittest.main()
