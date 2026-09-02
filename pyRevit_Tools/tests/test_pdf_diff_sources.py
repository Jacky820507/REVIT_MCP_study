# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""``pdf_diff_sources`` 的成本上限與正確性。

## 為什麼要測「呼叫幾次」

這一層是「圖說差異修訂雲」與「放置修訂雲標籤」兩顆按鈕在按下去的第一秒
同步做的事，所以它的複雜度就是使用者感受到的等待時間。實測回報是幾千張
圖紙的專案「跑很久然後 Revit 直接當掉」。

成因不是任何一個函式寫錯，是三個「每張圖紙都做一次」的全案子操作：
每張圖紙開一個 view-scoped ``FilteredElementCollector``、每張圖紙走訪一次
整份參數表、每次取 ElementId 都丟一次 AttributeError。三個都是只有在大案子
才看得出來的，單張圖紙的功能測試永遠是綠的。

所以這裡測的是**次數**：假的 Revit 會記錄每一次 collector 建構與每一次
``element.Parameters`` 走訪，然後斷言那些次數不隨圖紙數成長。純功能斷言
擋不住有人「順手」把快取拿掉。

## 這支測不到什麼

真實 Revit API 的絕對速度、WPF 的繪製成本，以及 IronPython 與 CPython 的
行為差異。那些分別靠 ``verify_ironpython.ps1``、``test_pdf_diff_window.py``
與實機測試。
"""

import os
import sys
import types
import unittest

from importlib.util import spec_from_file_location, module_from_spec


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SOURCES = os.path.join(ROOT, 'MCP_Tools.extension', 'lib',
                       'pdf_diff_sources.py')


# ---- 假的 Revit API ------------------------------------------------------

class Recorder(object):
    """記錄「做了幾次」，不是「做了什麼」。"""

    def __init__(self):
        self.collectors = []       # 每次 FilteredElementCollector 建構
        self.parameter_walks = []  # 每次 element.Parameters 走訪


class ElementId(object):
    InvalidElementId = None

    def __init__(self, value):
        self._value = int(value)

    @property
    def IntegerValue(self):
        return self._value

    def __eq__(self, other):
        return isinstance(other, ElementId) and other._value == self._value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(('ElementId', self._value))

    def __repr__(self):
        return '<ElementId {}>'.format(self._value)


ElementId.InvalidElementId = ElementId(-1)


class ModernElementId(object):
    """Revit 2024+ 的形狀：只有 ``Value``，沒有 ``IntegerValue``。"""

    def __init__(self, value):
        self.Value = int(value)


class _Definition(object):
    def __init__(self, name):
        self.Name = name


class _Parameter(object):
    def __init__(self, name, value):
        self.Definition = _Definition(name)
        self._value = value

    def AsString(self):
        return self._value

    def AsValueString(self):
        return self._value


class _Element(object):
    def __init__(self, element_id, recorder, parameters=None, name=u''):
        self.Id = ElementId(element_id)
        self.Name = name
        self._recorder = recorder
        self._parameters = [_Parameter(key, value)
                            for key, value in (parameters or [])]

    @property
    def Parameters(self):
        # 走訪整份參數表是這一層最貴的操作，所以每一次都記下來。
        self._recorder.parameter_walks.append(self)
        return list(self._parameters)

    def LookupParameter(self, name):
        for parameter in self._parameters:
            if parameter.Definition.Name == name:
                return parameter
        return None


class _BoundingBoxUVPoint(object):
    def __init__(self, u, v):
        self.U = u
        self.V = v


class _BoundingBoxUV(object):
    def __init__(self, min_u, min_v, max_u, max_v):
        self.Min = _BoundingBoxUVPoint(min_u, min_v)
        self.Max = _BoundingBoxUVPoint(max_u, max_v)


class ViewSheet(_Element):
    def __init__(self, element_id, recorder, number, name, parameters=None):
        _Element.__init__(self, element_id, recorder, parameters, name)
        self.SheetNumber = number
        self.IsTemplate = False
        self.Outline = _BoundingBoxUV(0.0, 0.0, 1.377, 0.974)


class FamilyInstance(_Element):
    def __init__(self, element_id, recorder, owner_id, type_id,
                 parameters=None):
        _Element.__init__(self, element_id, recorder, parameters)
        self.OwnerViewId = ElementId(owner_id)
        self._type_id = ElementId(type_id)

    def GetTypeId(self):
        return self._type_id


class ElementType(_Element):
    pass


class RevisionCloud(object):
    def __init__(self, element_id, owner_id):
        self.Id = ElementId(element_id)
        self.OwnerViewId = ElementId(owner_id)


class FakeDocument(object):
    def __init__(self, recorder):
        self.recorder = recorder
        self.sheets = []
        self.title_blocks = []
        self.title_block_types = {}
        self.clouds = []

    def GetElement(self, element_id):
        return self.title_block_types.get(element_id.IntegerValue)


class FilteredElementCollector(object):
    """只支援這一層真正用到的鏈式呼叫。"""

    def __init__(self, doc, view_id=None):
        doc.recorder.collectors.append(view_id)
        self._doc = doc
        self._view_id = view_id
        self._kind = None

    def OfClass(self, cls):
        if cls is ViewSheet:
            self._kind = 'sheets'
        elif cls is RevisionCloud:
            self._kind = 'clouds'
        return self

    def OfCategory(self, category):
        if category == 'OST_TitleBlocks':
            self._kind = 'title_blocks'
        return self

    def WhereElementIsNotElementType(self):
        return self

    def WhereElementIsElementType(self):
        return self

    def ToElements(self):
        if self._kind == 'sheets':
            return list(self._doc.sheets)
        if self._kind == 'title_blocks':
            blocks = list(self._doc.title_blocks)
            if self._view_id is not None:
                # view-scoped collector 真的只回那個視圖裡的元素。假的也要
                # 照做，否則「舊寫法其實是對的」會被誤判成資料錯誤。
                blocks = [block for block in blocks
                          if block.OwnerViewId == self._view_id]
            return blocks
        if self._kind == 'clouds':
            return list(self._doc.clouds)
        return []


def _install_revit_stub():
    db = types.ModuleType('Autodesk.Revit.DB')
    db.ElementId = ElementId
    db.ViewSheet = ViewSheet
    db.RevisionCloud = RevisionCloud
    db.FamilySymbol = ElementType
    db.Revision = object
    db.FilteredElementCollector = FilteredElementCollector
    db.BuiltInCategory = types.SimpleNamespace(
        OST_TitleBlocks='OST_TitleBlocks',
        OST_RevisionCloudTags='OST_RevisionCloudTags')

    class _Element_(object):
        Name = property(lambda self: u'')

    db.Element = _Element_

    revit = types.ModuleType('Autodesk.Revit')
    revit.DB = db
    autodesk = types.ModuleType('Autodesk')
    autodesk.Revit = revit

    sys.modules['Autodesk'] = autodesk
    sys.modules['Autodesk.Revit'] = revit
    sys.modules['Autodesk.Revit.DB'] = db


def _load_sources():
    """從檔案路徑載入真的模組。

    不能用 ``import pdf_diff_sources``：``test_pdf_diff_window`` 會把一個
    同名的假模組塞進 ``sys.modules``，測試順序不同就會拿到不同的東西。
    """
    _install_revit_stub()
    spec = spec_from_file_location('pdf_diff_sources_under_test', SOURCES)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sources = _load_sources()


# ---- 測資 ----------------------------------------------------------------

TITLE_BLOCK_TYPE_ID = 9001


def build_document(sheet_count, dwg_on='title_block', recorder=None):
    """一份有 ``sheet_count`` 張圖紙、每張一個同型圖框的文件。

    ``dwg_on`` 決定 DWG NO. 欄位掛在哪裡——實務上三個位置都出現過，而
    「掛在哪裡」不該影響掃描成本。
    """
    recorder = recorder or Recorder()
    doc = FakeDocument(recorder)

    # 圖框類型：整個類型共用同一組參數值，所以值也可以快取。
    doc.title_block_types[TITLE_BLOCK_TYPE_ID] = ElementType(
        TITLE_BLOCK_TYPE_ID, recorder,
        [(u'圖框版本', u'2026-01'), (u'廠商', u'HJ')])

    for index in range(sheet_count):
        sheet_id = 1000 + index
        number = u'A2-{:03d}'.format(index)
        dwg = u'DWG-{:04d}'.format(index)
        sheet_params = [(u'審核', u'王'), (u'比例', u'1/100')]
        block_params = [(u'客戶', u'某某'), (u'日期', u'2026-09-01')]
        if dwg_on == 'sheet':
            sheet_params.append((u'DWG NO.', dwg))
        else:
            block_params.append((u'DWG NO.', dwg))

        doc.sheets.append(ViewSheet(sheet_id, recorder, number,
                                    u'平面圖 {}'.format(index), sheet_params))
        doc.title_blocks.append(FamilyInstance(
            2000 + index, recorder, sheet_id, TITLE_BLOCK_TYPE_ID,
            block_params))
    return doc, recorder


# ---- 測試 ----------------------------------------------------------------

class CorrectnessTests(unittest.TestCase):
    """先確認快取沒有把「這張圖紙的值」記成「所有圖紙的值」。"""

    def test_each_sheet_keeps_its_own_dwg_number(self):
        doc, unused = build_document(5)
        rows = sources.sheet_records(doc)
        self.assertEqual(5, len(rows))
        self.assertEqual([u'DWG-0000', u'DWG-0001', u'DWG-0002',
                          u'DWG-0003', u'DWG-0004'],
                         [row['DwgNumber'] for row in rows])

    def test_dwg_number_is_found_on_the_sheet_too(self):
        doc, unused = build_document(3, dwg_on='sheet')
        rows = sources.sheet_records(doc)
        self.assertEqual([u'DWG-0000', u'DWG-0001', u'DWG-0002'],
                         [row['DwgNumber'] for row in rows])

    def test_outline_and_ids_come_through(self):
        doc, unused = build_document(1)
        row = sources.sheet_records(doc)[0]
        self.assertEqual(1000, row['ElementId'])
        self.assertEqual(4, len(row['Outline']))
        self.assertEqual(0.0, row['Outline'][0])

    def test_sheet_ids_filter_narrows_the_result(self):
        doc, unused = build_document(50)
        rows = sources.sheet_records(doc, sheet_ids=[1003, 1007])
        self.assertEqual([1003, 1007], sorted(row['ElementId']
                                              for row in rows))

    def test_an_empty_sheet_ids_filter_returns_nothing(self):
        """空集合是「沒有圖紙符合」，不是「不篩選」。"""
        doc, unused = build_document(5)
        self.assertEqual([], sources.sheet_records(doc, sheet_ids=[]))


class CostTests(unittest.TestCase):
    """成本不可以隨圖紙數成長。"""

    def test_title_blocks_are_collected_once_not_once_per_sheet(self):
        """舊寫法每張圖紙開一個 view-scoped collector。"""
        doc, recorder = build_document(200)
        sources.sheet_records(doc)
        self.assertLessEqual(
            len(recorder.collectors), 3,
            u'collector 次數是 {}，看起來又變成每張圖紙開一個'.format(
                len(recorder.collectors)))
        self.assertEqual([None] * len(recorder.collectors),
                         recorder.collectors,
                         u'不應該再有 view-scoped collector')

    def test_parameter_tables_are_walked_per_kind_not_per_sheet(self):
        """同一種元素的參數定義是固定的，只需要探勘一次。"""
        doc, recorder = build_document(200)
        sources.sheet_records(doc)
        self.assertLessEqual(
            len(recorder.parameter_walks), 3,
            u'走訪參數表 {} 次；200 張圖紙只該有「圖紙／圖框 instance／'
            u'圖框 type」三種各一次'.format(len(recorder.parameter_walks)))

    def test_cost_does_not_grow_with_sheet_count(self):
        """20 張與 500 張要花一樣多次數，這才是「不隨規模成長」。"""
        small_doc, small = build_document(20)
        sources.sheet_records(small_doc)
        big_doc, big = build_document(500)
        sources.sheet_records(big_doc)
        self.assertEqual(len(small.collectors), len(big.collectors))
        self.assertEqual(len(small.parameter_walks),
                         len(big.parameter_walks))

    def test_filtering_by_sheet_ids_does_not_walk_the_rest(self):
        doc, recorder = build_document(500)
        sources.sheet_records(doc, sheet_ids=[1100])
        self.assertLessEqual(len(recorder.parameter_walks), 3)


class CloudScopeTests(unittest.TestCase):
    """「先找雲、再找圖紙」用到的兩支便宜查詢。"""

    def test_clouds_are_grouped_by_owner(self):
        doc, unused = build_document(3)
        doc.clouds = [RevisionCloud(1, 1000), RevisionCloud(2, 1000),
                      RevisionCloud(3, 1002), RevisionCloud(4, 7777)]
        grouped = sources.revision_clouds_by_owner(doc)
        self.assertEqual(2, len(grouped[1000]))
        self.assertEqual(1, len(grouped[1002]))
        self.assertIn(7777, grouped, u'非圖紙的 owner 也要回報，由按鈕決定怎麼算')

    def test_all_sheet_ids_does_not_read_parameters(self):
        """這支的重點就是「便宜」——讀參數就失去意義了。"""
        doc, recorder = build_document(300)
        ids = sources.all_sheet_ids(doc)
        self.assertEqual(300, len(ids))
        self.assertEqual([], recorder.parameter_walks)


class ElementIdAccessorTests(unittest.TestCase):
    """``ElementId.Value`` 只有 Revit 2024+ 有；不能每次都靠丟例外去試。"""

    def setUp(self):
        self._saved = sources._ID_ACCESSOR
        sources._ID_ACCESSOR = None

    def tearDown(self):
        sources._ID_ACCESSOR = self._saved

    def test_reads_integer_value_on_older_revit(self):
        self.assertEqual(42, sources._id_value(ElementId(42)))
        self.assertEqual('IntegerValue', sources._ID_ACCESSOR)

    def test_reads_value_on_newer_revit(self):
        self.assertEqual(42, sources._id_value(ModernElementId(42)))
        self.assertEqual('Value', sources._ID_ACCESSOR)

    def test_a_cached_accessor_recovers_when_it_stops_working(self):
        """快取錯了要能自己換回來，而不是整批回傳 0。"""
        sources._ID_ACCESSOR = 'IntegerValue'
        self.assertEqual(7, sources._id_value(ModernElementId(7)))
        self.assertEqual('Value', sources._ID_ACCESSOR)

    def test_none_is_zero_not_an_exception(self):
        self.assertEqual(0, sources._id_value(None))


if __name__ == '__main__':
    unittest.main()
