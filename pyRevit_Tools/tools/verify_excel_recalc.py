# -*- coding: utf-8 -*-
"""驗證六顆按鈕的公式，在真正的試算表引擎打開並重新計算之後，真的算得出數字。

## 為什麼需要這一支

到目前為止的每一層驗證——``test_golden_regression.py``、``mutation_check.py``、
``NoHandWrittenAddressesTests``——都只讀 xlsx 裡 ``<f>`` 公式字串本身，**從來
沒有真的打開過**。我們自己的 ``write_xlsx``／``takeoff_standalone`` 從不寫
``<v>`` 快取值（只有 ``<f>``），所以 ``openpyxl(data_only=True)`` 讀回來的公式
儲存格永遠是 ``None``——語法正確不代表 Excel／LibreOffice 真的算得出正確答案：
跨分頁參照打錯分頁名、``SUM`` 範圍畫錯、循環參照……這些語法上完全合法，只有
真的算過一次才會現形。

## 用法

    python tools/verify_excel_recalc.py

需要機器上有 LibreOffice。找不到 ``soffice`` 就優雅跳過並印出安裝提示，
不阻擋——跟現有 PostToolUse hook 們「工具不在就 fail open」的慣例一致
（見 ``pyrevit-compile-gate-hook.ps1`` 對 ``python`` 不在 PATH 時的處理）。
可以用 ``LIBREOFFICE_PATH`` 環境變數指定 ``soffice`` 執行檔的位置。

## 做了什麼

對六顆已 SheetLayout 化的按鈕，各自：

1. 用 ``golden_fixtures.TAKEOFF_BUTTON_FILES`` 同一套 fixture 產生真正的
   ``.xlsx``（跟 golden regression 用的是同一份 fixture 定義，不是另外造的）。
2. 呼叫 ``soffice --headless --convert-to xlsx`` 讓 LibreOffice 打開、重新
   計算、另存——輸出檔案裡的公式儲存格現在有真正算出來的 ``<v>``。
3. 用 ``openpyxl`` 讀回每一個公式儲存格，確認不是 ``None``、不是 Excel 錯誤碼
   （``#REF!``/``#VALUE!``/``#DIV/0!``/…）——證明公式鏈沒有斷。
4. 對 RcVolumeExcel（唯一有獨立 Python 算法可以對照的一顆，
   ``summary_total_volume``）額外比對總計數值跟 Python 端算出來的是否一致
   （容許浮點誤差）——證明不只是「算得出東西」，而是「算對」。

其餘五顆目前只做「公式鏈沒斷」的檢查，沒有逐顆補獨立算法核對總數；那是
後續要不要加的問題，不是這支做不到，只是還沒有人替它們寫第二套算法。

## 一個誠實的免責聲明

2026-09-01 寫這支的當下，這台機器沒有安裝 LibreOffice，所以「打開 → 重算 →
讀回」那條路完全沒有機會實際跑過一次，只驗證過「偵測不到就跳過」那條路。
邏輯照著 LibreOffice headless 轉檔的標準用法寫（``--convert-to`` 同格式轉檔
會觸發完整的開檔 → 重算 → 存檔，這是 LibreOffice 文件記載的行為，我們自己
的 ``CeilingTakeoff``/``FloorTakeoff``/``RcVolumeExcel``/``takeoff_standalone``
也已經在寫 ``fullCalcOnLoad="1"`` 依賴同一個機制），但沒有在真的 LibreOffice
上跑過，不能保證第一次執行就完全順利——尤其是 soffice 的啟動時間、profile
鎖檔（同時開著 LibreOffice GUI 會擋住 headless 呼叫）這類環境問題，只能在
真的有 LibreOffice 的機器上才會浮現。第一次在有 LibreOffice 的機器上跑，
建議先看過完整輸出再信任結果。
"""
from __future__ import unicode_literals

import io
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(ROOT, 'tests')
sys.path.insert(0, TESTS_DIR)

ERROR_TOKENS = ('#REF!', '#VALUE!', '#DIV/0!', '#NAME?', '#NULL!', '#NUM!',
               '#N/A')

# 除了 PATH，也試這幾個常見安裝位置——soffice 通常不會被加進 PATH。
_COMMON_PATHS = (
    r'C:\Program Files\LibreOffice\program\soffice.exe',
    r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
    '/Applications/LibreOffice.app/Contents/MacOS/soffice',
    '/usr/bin/soffice',
    '/usr/lib/libreoffice/program/soffice',
    '/opt/libreoffice/program/soffice',
)


def find_soffice():
    override = os.environ.get('LIBREOFFICE_PATH')
    if override and os.path.isfile(override):
        return override
    found = shutil.which('soffice') or shutil.which('soffice.exe') \
        or shutil.which('soffice.bin')
    if found:
        return found
    for path in _COMMON_PATHS:
        if os.path.isfile(path):
            return path
    return None


def recalc_via_libreoffice(soffice, input_path, out_dir, timeout=120):
    """跑一次 ``soffice --headless --convert-to xlsx``，回傳重算後的檔案路徑。

    同格式轉檔（xlsx -> xlsx）沒有捷徑可以跳過——這正是我們要的：逼
    LibreOffice 真的打開、算過、再存一次，而不是原封不動複製。
    """
    cmd = [soffice, '--headless', '--norestore', '--convert-to', 'xlsx',
          '--outdir', out_dir, input_path]
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    output = result.stdout.decode('utf-8', 'replace')
    if result.returncode != 0:
        raise RuntimeError(
            'soffice 轉檔失敗（exit {0}）：\n{1}'.format(
                result.returncode, output))
    out_name = os.path.splitext(os.path.basename(input_path))[0] + '.xlsx'
    out_path = os.path.join(out_dir, out_name)
    if not os.path.exists(out_path):
        raise RuntimeError(
            'soffice 沒有產出預期的檔案：{0}\nsoffice 輸出：\n{1}'.format(
                out_path, output))
    return out_path


def formula_cells_are_healthy(path):
    """讀回每個分頁，回傳 ``(壞掉的儲存格清單, 檢查過的公式儲存格數)``。"""
    import openpyxl
    values_wb = openpyxl.load_workbook(path, data_only=True)
    formula_wb = openpyxl.load_workbook(path, data_only=False)
    bad = []
    checked = 0
    for sheet_name in formula_wb.sheetnames:
        formula_ws = formula_wb[sheet_name]
        values_ws = values_wb[sheet_name]
        for row in formula_ws.iter_rows():
            for cell in row:
                text = cell.value
                if not isinstance(text, str) or not text.startswith('='):
                    continue
                checked += 1
                value = values_ws[cell.coordinate].value
                if value is None:
                    bad.append('{0}!{1}：重算後仍是空值（{2}）'.format(
                        sheet_name, cell.coordinate, text))
                elif isinstance(value, str) and any(
                        token in value for token in ERROR_TOKENS):
                    bad.append('{0}!{1}：{2}（{3}）'.format(
                        sheet_name, cell.coordinate, value, text))
    return bad, checked


def _check_grand_total(name, recalculated_path, expected):
    """對有獨立 Python 算法可以對照的按鈕，額外比對總計數值本身。

    RcVolumeExcel 的「總計」不是單一儲存格——它是每種牆型各一欄的
    ``=SUM(...)``，真正的總量要把總計列上這些欄位全部加起來，跟
    ``summary_total_volume()`` 做的事一樣。所以這裡找到總計列之後，
    掃過那一整列、把看得懂的數字全部加總，而不是猜某個固定的欄位位移。
    """
    import openpyxl
    wb = openpyxl.load_workbook(recalculated_path, data_only=True)
    ws = wb.worksheets[0]
    for row in ws.iter_rows():
        label_cell = row[expected['label_col'] - 1]
        if label_cell.value != expected['label']:
            continue
        total = 0.0
        found_any = False
        for cell in row[expected['first_total_col'] - 1:]:
            if isinstance(cell.value, (int, float)):
                total += float(cell.value)
                found_any = True
        if not found_any:
            return False, '{0} 找到總計列但一個數字都沒讀到'.format(name)
        if abs(total - expected['value']) > 1e-3:
            return False, '{0} 總計應為 {1}，LibreOffice 算出 {2}'.format(
                name, expected['value'], total)
        return True, '{0} 總計核對通過（{1}）'.format(name, total)
    return False, '{0} 在重算後的分頁裡找不到總計列「{1}」'.format(
        name, expected['label'])


def _rc_volume_expected_total():
    """RcVolumeExcel 的 golden fixture 用同一份輸入，獨立算一次總量，
    不透過任何 Excel 公式——這是唯一真正獨立的對照組。"""
    import test_rc_volume_main_wiring as mod
    import revit_stub

    with revit_stub.install(answers={}) as stub:
        module = revit_stub.load_button(mod.BUTTON, 'rc_volume_oracle')
        rooms, grouped_by_room, unassigned, wall_type_cols, _walls, _stats = (
            mod.make_fixture(module))
        total = module.summary_total_volume(rooms, grouped_by_room,
                                            unassigned)
        # 總計列從第一種牆型欄開始才有數字（FIXED_REPORT_COLS 之前是空的
        # 「RC 體積總計」標籤與其他固定欄）；1 基欄號給 openpyxl 用。
        first_total_col = module.FIXED_REPORT_COLS + 1
    return {'label': module.SUMMARY_LABEL, 'label_col': 1,
           'first_total_col': first_total_col, 'value': total}


def main():
    soffice = find_soffice()
    if not soffice:
        print('SKIPPED：這台機器找不到 LibreOffice（soffice）。')
        print('  設定 LIBREOFFICE_PATH 環境變數指到 soffice.exe，或安裝：')
        print('  https://www.libreoffice.org/download/download/')
        print('  （這條路完全沒被跳過就不算驗證過；見本檔 docstring 的免責聲明。）')
        return 0

    print('使用 LibreOffice：{0}'.format(soffice))
    print('=' * 78)

    import golden_fixtures as gf

    work_root = tempfile.mkdtemp(prefix='excel-recalc-')
    all_ok = True
    try:
        for name in sorted(gf.TAKEOFF_BUTTON_FILES):
            print('--- {0} ---'.format(name))
            try:
                source_path = gf.TAKEOFF_BUTTON_FILES[name]()
            except Exception as error:
                print('  FAIL  無法產生輸入檔案：{0}'.format(error))
                all_ok = False
                continue

            out_dir = os.path.join(work_root, name)
            os.makedirs(out_dir)
            try:
                recalculated = recalc_via_libreoffice(
                    soffice, source_path, out_dir)
            except Exception as error:
                print('  FAIL  {0}'.format(error))
                all_ok = False
                continue

            try:
                bad, checked = formula_cells_are_healthy(recalculated)
            except Exception as error:
                # openpyxl 讀不動重算後的檔案本身就是個異常訊號（不該發生，
                # 但發生了也不該讓這支工具當掉、連其他五顆的結果都看不到）。
                print('  FAIL  重算後的檔案讀取失敗：{0}'.format(error))
                all_ok = False
                continue
            if bad:
                all_ok = False
                print('  FAIL  {0}/{1} 個公式儲存格異常：'.format(
                    len(bad), checked))
                for item in bad[:10]:
                    print('        {0}'.format(item))
                if len(bad) > 10:
                    print('        ...（還有 {0} 個）'.format(len(bad) - 10))
            else:
                print('  PASS  {0} 個公式儲存格全部算出正常值'.format(checked))

            if name == 'rc_volume_excel':
                try:
                    expected = _rc_volume_expected_total()
                    ok, message = _check_grand_total(
                        name, recalculated, expected)
                except Exception as error:
                    ok, message = False, '總計核對時發生例外：{0}'.format(error)
                print('  {0}  {1}'.format('PASS' if ok else 'FAIL', message))
                all_ok = all_ok and ok
    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    print('=' * 78)
    print('全部通過' if all_ok else '有項目沒通過，見上面標 FAIL 的地方')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
