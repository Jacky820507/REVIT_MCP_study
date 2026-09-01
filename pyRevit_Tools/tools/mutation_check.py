# -*- coding: utf-8 -*-
"""突變測試：把已知事故打回原始碼，確認測試套件真的會咬人。

## 這支測的是「測試」，不是「程式碼」

``tools\\verify_buttons.ps1`` 跑的是「現在的程式碼有沒有通過測試」。這支反過來：
「如果程式碼被改壞成某個已知形狀，測試會不會發現」。兩者都需要——綠燈不代表
測試真的守著什麼，只有故意打壞過一次、看它變紅，才算證明過。

每一條 ``MUTATIONS`` 都是這個專案真的出過、或這輪重構過程中特別在意的事故形狀
（``$V`` 欄號 off-by-one、取消存檔沒有提早 return、確認對話框被繞過……）。
新增一種按鈕或 lib 模組時，順手在這裡補一條對應的突變，這支測試的價值才不會
隨時間流失。

## 兩種突變方式

* ``kind='button'``：換掉 ``sys.modules[modname].BUTTON`` 指到的路徑，讓
  ``harness.TakeoffRun``／``ButtonRun`` 載入被打壞的臨時副本。
* ``kind='lib'``：patch ``takeoff_harness.LibRun.__init__``，讓它載入 lib 的
  臨時副本，而不是原始檔案。

兩者跑完都會把臨時檔案刪掉、把 patch 還原——不會在磁碟或記憶體留下痕跡。

## 用法

    python tools/mutation_check.py            # 跑全部
    python tools/mutation_check.py --verbose   # 連 SKIP 的原因也印

跟 ``verify_buttons.ps1`` 不同，這支**不是**每次部署前都要跑的東西——它比較慢
（每條突變都要重新 import 一次測試模組、跑一次 unittest），而且它驗證的是測試
套件本身的品質，不是這次改動有沒有問題。建議在：新增一顆按鈕的 wiring 測試之後、
或懷疑某個測試「看起來測了但其實測不到」的時候，手動跑一次。
"""
from __future__ import unicode_literals

import argparse
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(ROOT, 'MCP_Tools.extension', 'lib')
TESTS_DIR = os.path.join(ROOT, 'tests')
sys.path.insert(0, TESTS_DIR)


# ---------------------------------------------------------------------------
# 按鈕層突變：換掉 mod.BUTTON / case.BUTTON 指到的檔案
# ---------------------------------------------------------------------------

# (kind, 測試模組, 測試類別, 標籤, 原文, 替換, 按鈕別名對照或 None)
#
# RcVolumeExcel 的測試類別跟其他五顆不同（歷史因素：它是第一顆移轉的，命名
# 沒有跟後面五顆統一），所以少數幾條需要 alias 到不同的 (類別, 方法) 組合。
_RCVOL_ALIAS = {
    'test_grand_total_row_sums_its_own_column':
        ('HardcodedColumnTests', 'test_grand_total_rows_sum_their_own_column'),
    'test_cancelling_the_save_dialog_writes_no_file':
        ('MainWiringTests', 'test_cancelling_the_save_dialog_writes_no_file'),
}

BUTTON_CASES = [
    ('RcVolumeExcel', 'test_rc_volume_main_wiring', 'MainWiringTests'),
    ('PartitionTakeoff', 'test_partition_takeoff_wiring',
     'PartitionTakeoffWiringTests'),
    ('Baseboard', 'test_baseboard_wiring', 'BaseboardWiringTests'),
    ('InteriorWallPaint', 'test_interior_wall_paint_wiring',
     'InteriorWallPaintWiringTests'),
    ('CeilingTakeoff', 'test_ceiling_takeoff_wiring',
     'CeilingTakeoffWiringTests'),
    ('FloorTakeoff', 'test_floor_takeoff_wiring', 'FloorTakeoffWiringTests'),
]

BUTTON_MUTATIONS = [
    ('總計欄 off-by-one（$V 形狀）：SUM 公式的欄號多加了 1',
     'excel_col(FIXED_REPORT_COLS + index + 1)',
     'excel_col(FIXED_REPORT_COLS + index)',
     'test_grand_total_row_sums_its_own_column'),
    ('取消存檔對話框後沒有提早 return，繼續往下寫檔',
     'if not outpath:\n            return',
     "if not outpath:\n"
     "            outpath = os.path.join(os.environ['TEMP'], 'leak.xlsx')",
     'test_cancelling_the_save_dialog_writes_no_file'),
    ('發佈進既有活頁簿失敗，卻還是印出「完成」報告',
     'WorkbookPublishError as exc:',
     'WorkbookPublishError as exc:\n'
     '            outpath = workbook_path\n'
     '        except ZeroDivisionError as exc:',
     'test_publish_failure_alerts_instead_of_crashing'),
]


def _button_source_path(modname):
    module = __import__(modname)
    return module, module.BUTTON


def _run_button_mutations():
    results = []
    for button, modname, casename in BUTTON_CASES:
        module, original_path = _button_source_path(modname)
        source = io.open(original_path, encoding='utf-8').read()
        for label, old, new, target_method in BUTTON_MUTATIONS:
            if old not in source:
                results.append(('SKIP', button, label,
                               '找不到要替換的原文——這顆按鈕沒有這個形狀'))
                continue
            cls_name, method_name = casename, target_method
            if button == 'RcVolumeExcel':
                if target_method not in _RCVOL_ALIAS:
                    continue
                cls_name, method_name = _RCVOL_ALIAS[target_method]
            case_cls = getattr(module, cls_name, None)
            if case_cls is None or not hasattr(case_cls, method_name):
                results.append(('SKIP', button, label,
                               '{0}.{1} 不存在'.format(cls_name, method_name)))
                continue

            mutated = source.replace(old, new, 1)
            fd, path = tempfile.mkstemp(suffix='.py', prefix='mut-')
            os.close(fd)
            io.open(path, 'w', encoding='utf-8').write(mutated)
            module.BUTTON = path
            case_cls.BUTTON = path
            try:
                suite = unittest.TestLoader().loadTestsFromName(
                    '{0}.{1}'.format(cls_name, method_name), module)
                res = unittest.TextTestRunner(
                    stream=io.StringIO(), verbosity=0).run(suite)
                caught = not res.wasSuccessful()
            finally:
                module.BUTTON = original_path
                case_cls.BUTTON = original_path
                os.remove(path)
            results.append(('CAUGHT' if caught else 'MISSED', button, label,
                           ''))
    return results


# ---------------------------------------------------------------------------
# lib 層突變：patch LibRun.__init__ 載入被打壞的臨時副本
# ---------------------------------------------------------------------------

LIB_MUTATIONS = [
    ('test_scaffold_excel_run_wiring', 'ScaffoldRunWiringTests',
     'scaffold_excel', '備份改到寫入之後才做（出錯時使用者的活頁簿沒有退路）',
     '        backup = existing_backup or _backup_path(path)\n'
     '        if not existing_backup:\n'
     '            shutil.copy2(path, backup)\n',
     '        backup = existing_backup or _backup_path(path)\n'),
    ('test_scaffold_excel_run_wiring', 'ScaffoldRunWiringTests',
     'scaffold_excel', '確認對話框的回答被忽略',
     '        if not confirmed:\n            return\n', ''),
    ('test_scaffold_excel_run_wiring', 'ScaffoldRunWiringTests',
     'scaffold_excel', '唯讀檢查被拿掉',
     '            if wb.ReadOnly:\n', '            if False:\n'),
    ('test_scaffold_excel_run_wiring', 'ScaffoldRunWiringTests',
     'scaffold_excel', 'existing_backup 被忽略、重複備份',
     '        if not existing_backup:\n'
     '            shutil.copy2(path, backup)',
     '        shutil.copy2(path, backup)'),
    ('test_tall_partition_run_wiring', 'TallPartitionRunWiringTests',
     'tall_partition_excel', '沒有符合條件的牆也照樣寫檔',
     "    if not shaped['wall_count']:", '    if False:'),
    ('test_tall_partition_run_wiring', 'TallPartitionRunWiringTests',
     'tall_partition_excel', '取消存檔後沒有提早 return',
     '    if not path:\n        return\n',
     "    if not path:\n"
     "        path = os.path.join(os.environ['TEMP'], 'leak.xlsx')\n"),
    ('test_tall_partition_run_wiring', 'TallPartitionRunWiringTests',
     'tall_partition_excel', 'MCP 參數少帶門檻值',
     "'minWallHeightMm': THRESHOLD_MM,", "'minWallHeightMm': 0,"),
    ('test_machine_room_threshold_run_wiring',
     'MachineRoomThresholdRunWiringTests', 'machine_room_threshold_excel',
     '確認對話框的回答被忽略',
     '    if not confirmed:\n        return\n', ''),
    ('test_machine_room_threshold_run_wiring',
     'MachineRoomThresholdRunWiringTests', 'machine_room_threshold_excel',
     '備份路徑沒有傳給 update_workbook',
     "            result['path'], result['inspection'], result['summary'], "
     'backup,',
     "            result['path'], result['inspection'], result['summary'], "
     "'',"),
    ('test_machine_room_threshold_run_wiring',
     'MachineRoomThresholdRunWiringTests', 'machine_room_threshold_excel',
     '取消存檔後沒有提早 return',
     '        if not path:\n            return\n',
     "        if not path:\n"
     "            path = os.path.join(os.environ['TEMP'], 'leak.xlsx')\n"),
    ('test_parking_excel_run_wiring', 'ParkingRunWiringTests',
     'parking_excel', '確認對話框的回答被忽略',
     '        if not confirmed:\n            return\n', ''),
    ('test_parking_excel_run_wiring', 'ParkingRunWiringTests',
     'parking_excel', '輪檔倍率沒有傳下去',
     "            result['multiplier'],\n", '            1.0,\n'),
    ('test_door_window_run_wiring', 'DoorWindowRunWiringTests',
     'door_window_window', '確認對話框的回答被忽略',
     '    if not confirmed:\n        return\n', ''),
    ('test_door_window_run_wiring', 'DoorWindowRunWiringTests',
     'door_window_window', 'plan 沒有傳給 update_workbook',
     "core.update_workbook(result['path'], plan, backup)",
     "core.update_workbook(result['path'], {'updates': []}, backup)"),
]


def _run_lib_mutations():
    import takeoff_harness as harness

    results = []
    for modname, casename, lib, label, old, new in LIB_MUTATIONS:
        src_path = os.path.join(LIB_DIR, lib + '.py')
        source = io.open(src_path, encoding='utf-8').read()
        if old not in source:
            results.append(('SKIP', lib, label,
                           '找不到要替換的原文——這支 lib 沒有這個形狀'))
            continue

        fd, path = tempfile.mkstemp(suffix='.py', prefix='mlib-')
        os.close(fd)
        io.open(path, 'w', encoding='utf-8').write(source.replace(old, new, 1))

        module = __import__(modname)
        case_cls = getattr(module, casename)
        original_init = harness.LibRun.__init__

        def patched_init(self, lib_name, tmpdir, answers, patches=None,
                         document=None, lib_source=None, _path=path,
                         _orig=original_init):
            _orig(self, lib_name, tmpdir, answers, patches, document, _path)

        harness.LibRun.__init__ = patched_init
        try:
            suite = unittest.TestLoader().loadTestsFromTestCase(case_cls)
            res = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
            caught = not res.wasSuccessful()
        finally:
            harness.LibRun.__init__ = original_init
            os.remove(path)
        results.append(('CAUGHT' if caught else 'MISSED', lib, label, ''))
    return results


# ---------------------------------------------------------------------------
# 報告
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose', action='store_true',
                        help='連 SKIP 的原因也印出來')
    args = parser.parse_args()

    all_results = _run_button_mutations() + _run_lib_mutations()

    caught = sum(1 for r in all_results if r[0] == 'CAUGHT')
    missed = [r for r in all_results if r[0] == 'MISSED']
    skipped = [r for r in all_results if r[0] == 'SKIP']
    scored = caught + len(missed)

    print('=' * 78)
    for status, target, label, detail in all_results:
        if status == 'SKIP' and not args.verbose:
            continue
        line = '{0:8}{1:24} {2}'.format(status, target, label)
        if detail and args.verbose:
            line += '  ({0})'.format(detail)
        print(line)
    print('=' * 78)
    print('{0}/{1} 突變被抓到'.format(caught, scored) +
         ('，{0} 條跳過（--verbose 看原因）'.format(len(skipped))
          if skipped and not args.verbose else ''))

    if missed:
        print('')
        print('這些測試對已知的錯誤形狀是瞎的，補上對應的斷言：')
        for _status, target, label, _detail in missed:
            print('  - [{0}] {1}'.format(target, label))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
