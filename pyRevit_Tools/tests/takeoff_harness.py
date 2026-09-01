# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Takeoff 按鈕共用的離線驅動外殼與「不分按鈕都該成立」的合約測試。

## 為什麼抽出來

``Takeoff.panel`` 底下會產 Excel 的按鈕（輕隔間、踢腳、RC體積、天花、內牆粉刷、
地坪）長得幾乎一樣：

    options = takeoff_entry.choose_options(...)   # 取消 → 提早 return
    ... = collect_selected_sources(host_doc, options)   # 唯一碰 Revit 的地方
    rows   = make_rows(...)
    values = build_sheet_values(...)
    if options['workbook_path']:  發佈進既有活頁簿
    else:                         forms.save_file() → write_xlsx()
    output.print_md(...) 一長串報告，最後 forms.alert()

既然形狀一樣，會出的事也一樣：欄位字母寫死、報告讀到不存在的 stats key、
取消之後沒有提早 return、發佈失敗沒有攔。所以斷言寫一次就好，每顆按鈕只要提供
「``collect_*`` 該回什麼」這份 fixture。

## 分工

* ``TakeoffRun``：裝好假 Revit、載入按鈕、置換 ``choose_options`` 與 ``collect_*``
  這兩個接縫，然後呼叫真正的 ``main()``。
* ``WorkbookContract``：每顆按鈕都繼承的合約案例。子類別只要填 ``BUTTON``、
  ``SEAM``、``make_fixture()`` 這幾個 class 層的鉤子。
* ``read_sheets`` 等：把產出的 ``.xlsx`` 讀回來的小工具。

## 這裡測不到什麼

``collect_selected_sources`` 內部（Revit 幾何、連結模型、樓層過濾）在 fixture 的
另一邊。發佈進既有活頁簿那條路要 Excel COM，這裡只測它「失敗時有沒有好好收場」，
測不到它成功時寫出來的東西。其餘限制見 ``revit_stub`` 的模組 docstring。
"""

import io
import os
import re
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
import zipfile

import revit_stub


NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
SUM_RANGE = re.compile(r'^SUM\(([A-Z]+)\d+:([A-Z]+)\d+\)$')
CELL_REF = re.compile(r'^([A-Z]+)(\d+)$')

SENTINEL = object()


# ---------------------------------------------------------------------------
# 讀回產出的 xlsx
# ---------------------------------------------------------------------------

def read_sheets(path):
    """把每個分頁讀成 ``{'A1': {'v': ..., 'f': ..., 't': ...}}``。"""
    sheets = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist()
                       if name.startswith('xl/worksheets/sheet'))
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            cells = {}
            for cell in root.iter(NS + 'c'):
                formula = cell.find(NS + 'f')
                value = cell.find(NS + 'v')
                text = cell.find(NS + 'is/' + NS + 't')
                cells[cell.get('r')] = {
                    'f': formula.text if formula is not None else None,
                    'v': value.text if value is not None else None,
                    't': text.text if text is not None else None,
                }
            sheets.append(cells)
    return sheets


def column_of(ref):
    return CELL_REF.match(ref).group(1)


def row_of(ref):
    return int(CELL_REF.match(ref).group(2))


def cells_in_row(sheet, row):
    return dict((ref, cell) for ref, cell in sheet.items()
                if row_of(ref) == row)


def display(cell):
    for key in ('t', 'v', 'f'):
        if cell.get(key) is not None:
            return cell[key]
    return ''


def find_row_containing(sheet, text):
    for ref, cell in sheet.items():
        if display(cell) == text:
            return row_of(ref)
    return None


def column_for_header(sheet, header_row, title):
    for ref, cell in sheet.items():
        if row_of(ref) == header_row and display(cell) == title:
            return column_of(ref)
    raise AssertionError('第 {0} 列的表頭找不到「{1}」'.format(header_row, title))


# ---------------------------------------------------------------------------
# 執行外殼
# ---------------------------------------------------------------------------

class PublishFailed(Exception):
    """佔位用；實際會被換成按鈕自己的 WorkbookPublishError。"""


class TakeoffRun(object):
    """跑一次某顆 Takeoff 按鈕的 ``main()``。

    ``seam`` 是那顆按鈕唯一碰 Revit 的函式名稱（``collect_selected_sources``
    或 ``collect_data``）；它會被換成回傳 ``fixture`` 的假貨，並記錄被呼叫幾次
    ——「使用者已經取消了卻還去掃模型」就是靠這個計數抓的。
    """

    def __init__(self, button, tmpdir, answers, seam=None, fixture=None,
                 options=SENTINEL, document=None, patches=None):
        self.button = button
        self.tmpdir = tmpdir
        self.answers = answers
        self.seam = seam
        self._fixture = fixture
        self._options = options
        self.document = document
        # 除了主接縫之外，還會碰 Revit 或本機檔案的零星函式（讀材料 CSV、
        # 掃族群符號、跳材料選單）也要換掉，否則 main() 走不到寫檔那一步。
        # 可以給 dict，也可以給「吃 module 回 dict」的函式。
        self._patches = patches or {}
        self.module = None
        self.stub = None
        self.seam_calls = []
        self.option_calls = []
        self.fixture_value = None
        # (物件, 屬性名, 原值) — 離開時逐一還原，見 __enter__ 裡的說明
        self._restore = []

    def __enter__(self):
        document = self.document or revit_stub.FakeDocument(
            path_name=os.path.join(self.tmpdir, '示範專案.rvt'))
        self._ctx = revit_stub.install(document=document, answers=self.answers)
        self.stub = self._ctx.__enter__()
        self.module = revit_stub.load_button(
            self.button, 'takeoff_' + os.path.basename(
                os.path.dirname(self.button)).replace('.', '_'))

        options = self._options
        if options is SENTINEL:
            options = {'workbook_path': None}
        calls = self.option_calls

        def fake_choose_options(host_doc, title, **kwargs):
            calls.append((title, kwargs))
            return options

        if hasattr(self.module, 'takeoff_entry'):
            entry = self.module.takeoff_entry
            self._restore.append(
                (entry, 'choose_options',
                 getattr(entry, 'choose_options', SENTINEL)))
            entry.choose_options = fake_choose_options

        if self.seam:
            fixture = self._fixture
            if fixture is None:
                fixture = self.make_default_fixture(self.module)
            elif callable(fixture):
                fixture = fixture(self.module)
            self.fixture_value = fixture
            seam_calls = self.seam_calls

            def fake_seam(*args, **kwargs):
                seam_calls.append((args, kwargs))
                return fixture

            setattr(self.module, self.seam, fake_seam)

        patches = self._patches
        if callable(patches):
            patches = patches(self.module) or {}
        for name, value in patches.items():
            # 支援 'takeoff_entry.iter_sources' 這種點路徑，好換掉按鈕匯入的
            # lib 模組上的函式。
            #
            # 這種 patch 一定要還原：``takeoff_entry`` 是共用的 lib 模組，別支
            # 測試（test_takeoff_entry）自己也 import 了同一個物件。不還原的
            # 話單獨跑每支都綠，整套跑就會有三個案例莫名其妙失敗，而且症狀完全
            # 指不回這裡。2026-08-31 實際踩過一次。
            target = self.module
            parts = name.split('.')
            for part in parts[:-1]:
                target = getattr(target, part, None)
                if target is None:
                    break
            if target is None or not hasattr(target, parts[-1]):
                raise AssertionError(
                    '要置換的 {0} 在 {1} 裡不存在——名字改了或函式被移走了'
                    .format(name, os.path.basename(
                        os.path.dirname(self.button))))
            self._restore.append(
                (target, parts[-1], getattr(target, parts[-1], SENTINEL)))
            setattr(target, parts[-1], value)
        return self

    def __exit__(self, *exc):
        for target, attr, previous in reversed(self._restore):
            if previous is SENTINEL:
                try:
                    delattr(target, attr)
                except AttributeError:
                    pass
            else:
                setattr(target, attr, previous)
        self._restore = []
        return self._ctx.__exit__(*exc)

    def make_default_fixture(self, module):
        raise NotImplementedError

    def run(self):
        self.module.main()
        return self

    # -- 便利存取 ----------------------------------------------------------

    @property
    def printed(self):
        return self.stub.output.text

    @property
    def prompts(self):
        return self.stub.forms.prompt_sequence


# ---------------------------------------------------------------------------
# 合約案例
# ---------------------------------------------------------------------------

class WorkbookContract(object):
    """每顆會產 Excel 的 Takeoff 按鈕都該通過的案例。

    子類別要提供：

    ``BUTTON``      按鈕 ``script.py`` 的完整路徑
    ``SEAM``        唯一碰 Revit 的函式名稱
    ``SHEET_COUNT`` 產出的分頁數
    ``DONE_MARK``   報告開頭那句話裡一定會出現的字串
    ``make_fixture(module)``  ``SEAM`` 該回傳什麼
    ``answers()``   對話框答案（預設只有存檔路徑）

    可覆寫 ``HAS_PUBLISH_BRANCH`` 關掉「發佈失敗」那一案。
    """

    BUTTON = None
    SEAM = None
    SHEET_COUNT = 1
    DONE_MARK = ''
    HAS_PUBLISH_BRANCH = True
    OUT_NAME = '輸出.xlsx'

    def make_fixture(self, module):
        raise NotImplementedError

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='takeoff-')
        self.outpath = os.path.join(self.tmpdir, self.OUT_NAME)
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def answers(self, save_to=SENTINEL):
        return {
            'save_file': self.outpath if save_to is SENTINEL else save_to,
        }

    def extra_patches(self, module):
        """主接縫以外還要換掉的東西；子類別按需要覆寫。"""
        return {}

    def make_run(self, answers=None, options=SENTINEL, fixture=SENTINEL):
        return TakeoffRun(
            self.BUTTON, self.tmpdir,
            self.answers() if answers is None else answers,
            seam=self.SEAM,
            fixture=(self.make_fixture if fixture is SENTINEL else fixture),
            options=options,
            patches=self.extra_patches)

    # -- 端對端 ------------------------------------------------------------

    def test_main_writes_a_parsable_workbook(self):
        with self.make_run() as run:
            run.run()
        self.assertTrue(os.path.exists(self.outpath), '按鈕沒有寫出檔案')
        self.assertTrue(zipfile.is_zipfile(self.outpath))
        with zipfile.ZipFile(self.outpath) as archive:
            names = archive.namelist()
        self.assertEqual(sorted(set(names)), sorted(names),
                         'xlsx 內有重複的 part，Excel 開檔會要求修復')
        self.assertEqual(self.SHEET_COUNT, len(read_sheets(self.outpath)))

    def test_missing_extension_is_appended(self):
        bare = os.path.join(self.tmpdir, '沒有副檔名')
        with self.make_run(answers=self.answers(save_to=bare)) as run:
            run.run()
        self.assertTrue(os.path.exists(bare + '.xlsx'))
        self.assertFalse(os.path.exists(bare))

    def test_report_runs_to_the_end(self):
        """report 段落把 stats 讀完；少一個 key 就是寫完檔之後才炸的 KeyError。"""
        with self.make_run() as run:
            run.run()
            printed = run.printed
        self.assertIn(self.DONE_MARK, printed)
        self.assertIn(self.outpath, printed, '報告要指出檔案寫到哪裡')

    # -- 提早 return ------------------------------------------------------

    def test_cancelling_the_options_dialog_stops_before_touching_revit(self):
        with self.make_run(options=None) as run:
            run.run()
            self.assertEqual([], run.seam_calls,
                             '使用者已取消，不該再去掃模型')
        self.assertFalse(os.path.exists(self.outpath))

    def test_cancelling_the_save_dialog_writes_no_file(self):
        # 只檢查「我指定的那個路徑不存在」不夠：沒有提早 return 的話，程式可能
        # 改寫到別的地方去，那個斷言照樣通過。所以連「有沒有印出報告」一起看
        # ——main() 若真的提早 return，一行 print_md 都不會有。
        with self.make_run(answers=self.answers(save_to=None)) as run:
            run.run()
            self.assertEqual('', run.printed,
                             '使用者取消了存檔，卻還是跑完並印出報告')
        self.assertFalse(os.path.exists(self.outpath))
        self.assertEqual([], os.listdir(self.tmpdir), '取消後不該留下任何檔案')

    def test_no_dialog_is_left_unanswered(self):
        """ScriptedForms 對沒排答案的提問會丟例外，所以跑完就代表流程沒漂移。"""
        with self.make_run() as run:
            run.run()
            self.assertIn('save_file', run.prompts)
            self.assertEqual('alert', run.prompts[-1],
                             '最後要有一個完成通知')

    # -- 發佈進既有活頁簿那條路 --------------------------------------------

    def test_publish_failure_alerts_instead_of_crashing(self):
        if not self.HAS_PUBLISH_BRANCH:
            self.skipTest('這顆按鈕沒有發佈分支')
        workbook = os.path.join(self.tmpdir, '主要.xlsx')
        with self.make_run(answers={},
                           options={'workbook_path': workbook}) as run:
            error = run.module.takeoff_direct_publish.WorkbookPublishError

            def boom(*args, **kwargs):
                raise error('分頁被鎖住')

            run.module.takeoff_direct_publish.publish_generated_workbook = boom
            run.run()
            self.assertTrue(run.stub.forms.alerts, '失敗時要跳提示')
            self.assertIn('分頁被鎖住', run.stub.forms.alerts[-1])
            self.assertEqual('', run.printed,
                             '發佈失敗還印出完成報告，等於謊報成功')

    # -- 欄位字母寫死 ------------------------------------------------------

    def test_grand_total_row_sums_its_own_column(self):
        """總計列的每個 SUM 都必須加自己那一欄——這是 $V 那次的形狀。"""
        with self.make_run() as run:
            run.run()
            label = run.module.SUMMARY_LABEL

        checked = 0
        for sheet in read_sheets(self.outpath):
            total_row = find_row_containing(sheet, label)
            if total_row is None:
                continue
            for ref, cell in cells_in_row(sheet, total_row).items():
                match = SUM_RANGE.match(cell['f'] or '')
                if not match:
                    continue
                checked += 1
                self.assertEqual(
                    column_of(ref), match.group(1),
                    '{0} 的公式 =SUM({1}...) 沒有加自己那一欄'.format(
                        ref, match.group(1)))
                self.assertEqual(match.group(1), match.group(2))
        self.assertGreaterEqual(checked, 1, '總計列沒有 SUM 公式，斷言沒生效')


# ---------------------------------------------------------------------------
# 驅動 lib 層的 run()
# ---------------------------------------------------------------------------

class LibRun(object):
    """跑一次 ``lib\\<name>.py`` 的 ``run()``。

    薄殼按鈕（停車位、施工架、門窗表、機房門檻、高隔間）本體只有 10～30 行，
    真正的邏輯在 lib 模組的 ``run()`` 裡，沒有 ``main()`` 可以拆。這支負責：
    裝好假 Revit、載入那支 lib、把指定的接縫換掉、呼叫 ``run()``。

    ``patches`` 支援 'mcp.run' 這種點路徑，用來換掉 lib 模組自己 import 進來的
    其他 lib（``mcp`` 是共用模組，別支測試也會 import 同一個物件）。**離開時一律
    還原**——不還原的話單獨跑每支都綠、整套跑才炸，而且症狀指不回這裡。
    """

    def __init__(self, lib_name, tmpdir, answers, patches=None, document=None,
                 lib_source=None):
        self.lib_name = lib_name
        # 突變測試會傳一份改過的副本路徑進來；正常使用留 None
        self.lib_source = lib_source
        self.tmpdir = tmpdir
        self.answers = answers
        self._patches = patches or {}
        self.document = document
        self.module = None
        self.stub = None
        self._restore = []

    def __enter__(self):
        document = self.document or revit_stub.FakeDocument(
            path_name=os.path.join(self.tmpdir, '示範專案.rvt'))
        self._ctx = revit_stub.install(document=document, answers=self.answers)
        self.stub = self._ctx.__enter__()
        self.module = revit_stub.load_lib(self.lib_name, self.lib_source)

        patches = self._patches
        if callable(patches):
            patches = patches(self.module) or {}
        for name, value in patches.items():
            target = self.module
            parts = name.split('.')
            for part in parts[:-1]:
                target = getattr(target, part, None)
                if target is None:
                    break
            if target is None or not hasattr(target, parts[-1]):
                raise AssertionError(
                    '要置換的 {0} 在 {1} 裡不存在——名字改了或函式被移走了'
                    .format(name, self.lib_name))
            self._restore.append(
                (target, parts[-1], getattr(target, parts[-1], SENTINEL)))
            setattr(target, parts[-1], value)
        return self

    def __exit__(self, *exc):
        for target, attr, previous in reversed(self._restore):
            if previous is SENTINEL:
                try:
                    delattr(target, attr)
                except AttributeError:
                    pass
            else:
                setattr(target, attr, previous)
        self._restore = []
        return self._ctx.__exit__(*exc)

    def run(self, *args, **kwargs):
        self.module.run(*args, **kwargs)
        return self

    @property
    def printed(self):
        return self.stub.output.text

    @property
    def prompts(self):
        return self.stub.forms.prompt_sequence


# ---------------------------------------------------------------------------
# 手寫欄位字母的檢查
# ---------------------------------------------------------------------------

# 兩大類：
#   1. 欄位字母後面緊接 format 佔位符——'=E{0}*F{0}'、'=IF(Q{}="是",ROUND(I{}...'
#      2026-08-31：原本只比對 '=' 後緊接字母，漏掉了 'IF(Q{}' 這種包在函式裡的，
#      而那正好是 scaffold_excel 寫進使用者活頁簿的公式。
#   2. 字面範圍——'A1:S1'、'A3:E6'
#      注意樣式要夠窄：'B{0}'.format(...) 是樓層代號（B1F/R2/F3），不是欄位；
#      "A{1}" 出現在 topLeftCell 這種屬性裡也不是。所以只認「緊接在 Excel 公式
#      的運算子後面」的字母，引號後面的一律不算。
#   3. 完全寫死的跨分頁位址——"'公式摘要'!B3"。沒有 format 佔位符，所以前兩條
#      都抓不到；2026-08-31 在 machine_room_threshold_logic 實際漏掉過一個。
ADDRESS_PATTERNS = (
    re.compile(r'''(?<=[=(,!&:+\-*/])[A-Z]{1,2}\{\d*\}'''),
    re.compile(r'''['"][A-Z]{1,2}\d+:'''),
    re.compile(r'''!\$?[A-Z]{1,2}\$?\d'''),
)


def hand_written_addresses(path):
    """回傳原始碼裡還在手寫欄位字母的行（``行號:內容``）。

    欄位字母只該由 ``sheet_layout.SheetLayout`` 產生。上面那些「字母對不對得上
    表頭」的斷言是**事後偵測**；這一條是**事前禁止**——沒有人手寫字母，那類
    bug 就寫不出來。註解裡出現不算（改寫過程的說明常常會引用舊寫法）。
    """
    with io.open(path, encoding='utf-8') as handle:
        lines = handle.read().splitlines()
    offenders = []
    in_doc = False
    doc_delim = None
    for number, line in enumerate(lines, start=1):
        # 逃生閥：真正恆定的位址（例如工作表 dimension 的 A1）標註後豁免。
        # 阻擋式的檢查一定要留一個，否則遇到誤判就只能把整條規則關掉。
        if 'sheet-layout: ignore' in line:
            continue

        # docstring 要整段跳過：說明文字裡引用位址（「以前這裡寫死 =P{0}*G{0}」、
        # 「使用者的活頁簿長 =SUM(內牆!M16:M484)」）是正常的。
        # 收尾只認同一種三引號——只算奇偶的話，'''被寫在 """ 內文裡就會卡住，
        # 整個檔案不再被掃描而且沒有任何徵兆（ironpython-guard 踩過同一個坑）。
        stripped = line.strip()
        if in_doc:
            if doc_delim in line:
                in_doc = False
                doc_delim = None
            continue
        if stripped.startswith('#'):
            continue
        for delim in ('"""', "'''"):
            if stripped.startswith(delim) or stripped.startswith('u' + delim) \
                    or stripped.startswith('r' + delim):
                body = stripped.split(delim, 1)[1]
                if delim not in body:      # 單行 docstring 直接跳過就好
                    in_doc = True
                    doc_delim = delim
                break
        if in_doc:
            continue
        if any(stripped.startswith(prefix)
               for prefix in ('"""', "'''", 'u"""', "u'''")):
            continue

        code = line.split('#', 1)[0]
        for pattern in ADDRESS_PATTERNS:
            if pattern.search(code):
                offenders.append('{0}:{1}'.format(number, line.strip()))
                break
    return offenders


class NoHandWrittenAddresses(object):
    """混進按鈕的測試類別，就會檢查該顆的原始碼沒有手寫欄位字母。"""

    BUTTON = None

    def test_source_has_no_hand_written_column_letters(self):
        offenders = hand_written_addresses(self.BUTTON)
        self.assertEqual(
            [], offenders,
            '這幾行還在手寫欄位字母，改用 SheetLayout：\n'
            + '\n'.join(offenders))


def load_case(module_globals):
    """讓 unittest 只收子類別，不要把 mixin 本身當測試收走。"""
    return [value for value in module_globals.values()
            if isinstance(value, type)
            and issubclass(value, unittest.TestCase)]
