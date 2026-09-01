# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""真的執行「施工架 Excel」的 ``lib\\scaffold_excel.run()``。

## 為什麼另開一支

室外框式（``ScaffoldExterior``）與室內（``ScaffoldRooms``）兩顆薄殼按鈕共用同一個
``scaffold_excel.run(mode, ...)``，本體加起來不到 90 行，邏輯全在 lib 裡。

``run()`` 有兩個接縫：

* **取數**：``_collect_exterior_takeoff()`` / ``_collect_room_takeoff(options)``
  ——後面是 Revit + MCP。
* **寫檔**：``_excel_open()`` / ``_excel_close()`` ——後面是 Excel COM。

這支把兩個都換掉。COM 那條路用 ``FakeExcel``（假的活頁簿物件模型）驅動，能驗到
「備份有沒有先做」「唯讀時有沒有擋下來」這類真的出過事的環節。

## 這支測不到什麼

真正的 Excel 行為（公式重算、範本相容性）。``_collect_*`` 內部的 Revit 幾何與
MCP 橋接。其餘限制見 ``revit_stub`` 的模組 docstring。
"""

import os
import shutil
import tempfile
import unittest

import takeoff_harness as harness


LIB = 'scaffold_excel'


class ScaffoldRunWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='scaffold-')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def make_run(self, answers=None, patches=None):
        return harness.LibRun(LIB, self.tmpdir, answers or {},
                              patches=patches or {})

    # -- 不碰 Excel 的幾條路 ------------------------------------------------

    def test_unknown_mode_alerts_and_does_nothing(self):
        """模式打錯要當場講；沉默地什麼都不做最難查。"""
        with self.make_run() as run:
            run.run('typo')
            self.assertTrue(run.stub.forms.alerts)
            self.assertIn('未知施工架模式', run.stub.forms.alerts[0])
            self.assertEqual([], os.listdir(self.tmpdir))

    def test_cancelling_the_exterior_source_picker_stops_early(self):
        """取數階段回 None（使用者取消）之後，不該再去問存檔或開 Excel。"""
        calls = []

        def patches(module):
            return {'_collect_exterior_takeoff': lambda: calls.append(1),
                    '_excel_open': self._explode('不該開 Excel')}

        with self.make_run(patches=patches) as run:
            run.run('exterior')
            self.assertEqual([], run.stub.forms.alerts)
            self.assertEqual([], run.prompts)

    def test_no_workbook_path_stops_before_opening_excel(self):
        """室外模式沒給路徑又沒選檔就結束，不能帶著 None 往下走。"""
        def patches(module):
            return {'_collect_exterior_takeoff': lambda: {'quantity': 12.0},
                    '_excel_open': self._explode('不該開 Excel')}

        with self.make_run(answers={'pick_file': None},
                           patches=patches) as run:
            run.run('exterior')
            self.assertEqual(['pick_file'], run.prompts)

    def test_a_bridge_error_is_reported_not_swallowed(self):
        """MCP 橋接失敗要走 show_error，不能被最外層的 except 吃成通用訊息。"""
        shown = []

        def patches(module):
            def boom():
                raise module.mcp.MCPBridgeError('Revit 沒有回應')
            return {'_collect_exterior_takeoff': boom,
                    'mcp.show_error': lambda error, title: shown.append(
                        (u'{0}'.format(error), title))}

        with self.make_run(patches=patches) as run:
            run.run('exterior')
        self.assertEqual(1, len(shown))
        self.assertIn('沒有回應', shown[0][0])

    def test_an_unexpected_error_becomes_a_readable_alert(self):
        """非預期例外要轉成對話框，不能讓 Revit 直接跳 traceback。"""
        def patches(module):
            return {'_collect_exterior_takeoff': self._explode('磁碟滿了')}

        with self.make_run(patches=patches) as run:
            run.run('exterior')
            self.assertTrue(run.stub.forms.alerts)
            self.assertIn('執行失敗', run.stub.forms.alerts[-1])
            self.assertIn('磁碟滿了', run.stub.forms.alerts[-1])

    # -- Excel COM 那條路 --------------------------------------------------
    #
    # 這裡換掉的是「寫 Excel 的那幾支 helper」，不是活頁簿物件本身：留下來受測的
    # 是 run() 自己的**編排順序**——備份有沒有在任何寫入之前做、確認對話框有沒有
    # 真的把關、唯讀有沒有擋下來。那幾支 helper 各自的正確性不在這支的範圍。

    def com_patches(self, module, journal, takeoff=None,
                    read_only=False, item_rows=None):
        takeoff = takeoff if takeoff is not None else {'quantity': 128.5}

        class FakeWorkbook(object):
            ReadOnly = read_only

        def excel_open(path, read_only_flag):
            journal.append(('open', os.path.basename(path), read_only_flag))
            return object(), FakeWorkbook()

        def excel_close(excel, wb, save):
            journal.append(('close', save))

        def record(name, result=None):
            def call(*args, **kwargs):
                journal.append((name,))
                return result
            return call

        return {
            '_collect_exterior_takeoff': lambda: takeoff,
            '_excel_open': excel_open,
            '_excel_close': excel_close,
            '_validate_template': record('validate'),
            '_read_old_totals': record('read_old', {}),
            '_ensure_audit_sheet': record('audit_sheet', object()),
            '_write_exterior_audit': record('write_audit'),
            '_ensure_item_rows': record(
                'item_rows',
                item_rows if item_rows is not None
                else {'created_finish': False}),
            '_link_other_area': record('link'),
            '_calculate_workbook': record('calculate'),
            '_validate_written_workbook': record('validate_written'),
            '_exterior_confirm_text': lambda *a, **k: u'確認要寫入嗎？',
        }

    def workbook_file(self):
        path = os.path.join(self.tmpdir, '主要.xlsx')
        with open(path, 'wb') as handle:
            handle.write(b'original')
        return path

    def test_the_backup_is_taken_before_anything_is_written(self):
        """備份必須早於任何寫入。順序反了，出錯時使用者的活頁簿就沒有退路。"""
        path = self.workbook_file()
        journal = []
        with self.make_run(
                answers={'alert_yes_no': True},
                patches=lambda m: self.com_patches(m, journal)) as run:
            run.run('exterior', excel_path=path)

        names = [item[0] for item in journal]
        self.assertIn('write_audit', names, '沒有走到寫入')
        backups = [f for f in os.listdir(self.tmpdir) if f != '主要.xlsx']
        self.assertEqual(1, len(backups), '應該正好留下一份備份')
        # 備份是 copy2 出來的，內容要是「寫入之前」那一份
        with open(os.path.join(self.tmpdir, backups[0]), 'rb') as handle:
            self.assertEqual(b'original', handle.read())
        # 第二次 open（可寫）必須排在寫入動作之前，且備份更早
        second_open = [i for i, item in enumerate(journal)
                       if item[0] == 'open' and item[2] is False][0]
        self.assertLess(second_open, names.index('write_audit'))

    def test_declining_the_confirmation_writes_nothing_and_makes_no_backup(self):
        path = self.workbook_file()
        journal = []
        with self.make_run(
                answers={'alert_yes_no': False},
                patches=lambda m: self.com_patches(m, journal)) as run:
            run.run('exterior', excel_path=path)

        names = [item[0] for item in journal]
        self.assertNotIn('write_audit', names, '使用者按了否還是寫進去了')
        self.assertEqual(['主要.xlsx'], os.listdir(self.tmpdir),
                         '按否之後不該留下備份')

    def test_a_read_only_workbook_is_refused_with_a_readable_message(self):
        path = self.workbook_file()
        journal = []
        with self.make_run(
                answers={'alert_yes_no': True},
                patches=lambda m: self.com_patches(m, journal,
                                                   read_only=True)) as run:
            run.run('exterior', excel_path=path)
            alerts = run.stub.forms.alerts

        self.assertTrue(alerts)
        self.assertIn('唯讀', alerts[-1])
        self.assertNotIn('write_audit', [item[0] for item in journal])
        # 失敗也要把 COM 收乾淨
        self.assertEqual(len([i for i in journal if i[0] == 'open']),
                         len([i for i in journal if i[0] == 'close']),
                         '開了幾次就要關幾次，否則 Excel 行程會留著')

    def test_an_existing_backup_is_not_duplicated(self):
        """室內施工架那顆會把先前建立的備份傳進來，不該再備份一次。"""
        path = self.workbook_file()
        journal = []
        with self.make_run(
                answers={'alert_yes_no': True},
                patches=lambda m: self.com_patches(m, journal)) as run:
            run.run('exterior', excel_path=path,
                    existing_backup=os.path.join(self.tmpdir, '先前.bak'))

        self.assertEqual(['主要.xlsx'], os.listdir(self.tmpdir),
                         '已經有備份了還是又備份了一份')

    def test_the_summary_alert_reports_the_quantity(self):
        path = self.workbook_file()
        journal = []
        with self.make_run(
                answers={'alert_yes_no': True},
                patches=lambda m: self.com_patches(
                    m, journal, takeoff={'quantity': 128.5})) as run:
            run.run('exterior', excel_path=path)
            alerts = run.stub.forms.alerts

        self.assertTrue(alerts)
        self.assertIn('更新完成', alerts[-1])
        self.assertIn('128.5', alerts[-1])

    # -- 小工具 ------------------------------------------------------------

    @staticmethod
    def _explode(message):
        def boom(*args, **kwargs):
            raise Exception(message)
        return boom


if __name__ == '__main__':
    unittest.main()
