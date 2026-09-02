# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""「放置修訂雲標籤」按鈕在大型專案的取數範圍。

實測回報：幾千張圖紙的專案按下這顆按鈕會跑很久，然後 Revit 直接終止。
三個成因都在「開視窗之前」，而且都是只有在大案子才看得出來的：

1. 先為**全部**圖紙做昂貴的 DWG NO. 欄位掃描，再回頭看哪些有雲。
2. 走訪**全部** ``IndependentTag`` 找修訂雲標籤——大案子裡那是幾萬個門窗
   房間牆標籤，而修訂雲標籤通常只有幾十個。
3. ``_id_value`` 每次都先試 Revit 2024 才有的 ``ElementId.Value``，於是在
   2020–2023 上每呼叫一次就丟一次 AttributeError；上面兩點又讓它被呼叫
   幾十萬次。

這支測的是**掃描範圍**：假的 Revit 記錄「用什麼過濾條件建了 collector」與
「``sheet_records`` 被要求算哪些圖紙」，然後斷言那些範圍是收斂的。功能斷言
擋不住有人把過濾條件放寬回去——那不會改變任何一筆輸出，只會讓它變慢。
"""

import os
import sys
import types
import unittest

from importlib.util import spec_from_file_location, module_from_spec


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BUTTON = os.path.join(ROOT, 'MCP_Tools.extension', 'MCP_Macros.tab',
                      'Revision.panel', 'PlaceRevisionCloudTags.pushbutton')


# ---- 假的 Revit API ------------------------------------------------------

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


ElementId.InvalidElementId = ElementId(-1)


class ModernElementId(object):
    """Revit 2024+ 的形狀：只有 ``Value``。"""

    def __init__(self, value):
        self.Value = int(value)


class RevisionCloud(object):
    def __init__(self, element_id, owner_id):
        self.Id = ElementId(element_id)
        self.OwnerViewId = ElementId(owner_id)


class _TaggedElementId(object):
    def __init__(self, host_id):
        self.HostElementId = ElementId(host_id)


class IndependentTag(object):
    def __init__(self, owner_id, host_id, category):
        self.OwnerViewId = ElementId(owner_id)
        self.TaggedElementId = _TaggedElementId(host_id)
        self.category = category


class FakeDocument(object):
    def __init__(self):
        self.tags = []
        self.collector_filters = []


class FilteredElementCollector(object):
    """記錄「用什麼過濾條件建的」，這正是本測試要斷言的東西。"""

    def __init__(self, doc, view_id=None):
        self._doc = doc
        self._filters = []
        doc.collector_filters.append(self._filters)

    def OfClass(self, cls):
        self._filters.append(('OfClass', getattr(cls, '__name__', cls)))
        return self

    def OfCategory(self, category):
        self._filters.append(('OfCategory', category))
        return self

    def WhereElementIsNotElementType(self):
        return self

    def ToElements(self):
        for kind, value in self._filters:
            if kind == 'OfCategory':
                return [tag for tag in self._doc.tags
                        if tag.category == value]
        return list(self._doc.tags)


def _install_stubs():
    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    db = module('Autodesk.Revit.DB')
    db.ElementId = ElementId
    db.RevisionCloud = RevisionCloud
    db.IndependentTag = IndependentTag
    db.FilteredElementCollector = FilteredElementCollector
    db.BuiltInCategory = types.SimpleNamespace(
        OST_RevisionCloudTags='OST_RevisionCloudTags')
    revit_ns = module('Autodesk.Revit')
    revit_ns.DB = db
    autodesk = module('Autodesk')
    autodesk.Revit = revit_ns

    module('System')
    module('System.Windows', Thickness=lambda *a: tuple(a))

    class CheckBox(object):
        pass

    module('System.Windows.Controls', CheckBox=CheckBox)

    class _ProgressBar(object):
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class WPFWindow(object):
        def __init__(self, xaml_path):
            pass

    alerts = []
    module('pyrevit',
           forms=types.SimpleNamespace(
               WPFWindow=WPFWindow, ProgressBar=_ProgressBar,
               alert=lambda *a, **k: alerts.append(a)),
           revit=types.SimpleNamespace(doc=FakeDocument(), uidoc=None))
    module('pyrevit.forms')

    # 匯入期間 main() 會跑一次；讓它安靜地走完「沒有雲」那條路。
    module('pdf_diff_sources',
           revision_clouds_by_owner=lambda doc: {},
           all_sheet_ids=lambda doc: set(),
           sheet_records=lambda doc, **kwargs: [],
           revision_tag_records=lambda doc: [],
           revision_tag_label=lambda row: u'')
    return alerts


def _load_script():
    _install_stubs()
    path = os.path.join(BUTTON, 'script.py')
    spec = spec_from_file_location('place_revision_cloud_tags_button', path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


class _RecordingSources(object):
    """記錄 ``sheet_records`` 被要求算哪些圖紙。"""

    def __init__(self, cloud_owners, sheet_ids, sheets):
        self._cloud_owners = cloud_owners
        self._sheet_ids = sheet_ids
        self._sheets = sheets
        self.sheet_records_calls = []

    def revision_clouds_by_owner(self, doc):
        return dict(self._cloud_owners)

    def all_sheet_ids(self, doc):
        return set(self._sheet_ids)

    def sheet_records(self, doc, sheet_ids=None):
        wanted = None if sheet_ids is None else set(sheet_ids)
        self.sheet_records_calls.append(wanted)
        if wanted is None:
            return list(self._sheets)
        return [row for row in self._sheets
                if row['ElementId'] in wanted]


def sheet_row(element_id, number):
    return {'SheetNumber': number, 'SheetName': u'圖 {}'.format(number),
            'DwgNumber': None, 'DwgNumberCandidates': [],
            'Outline': (0.0, 0.0, 1.377, 0.974), 'ElementId': element_id}


class ScopeTests(unittest.TestCase):
    """先找雲、再找圖紙——不要為了幾十張圖紙掃描幾千張。"""

    def setUp(self):
        self._saved_sources = script.sources
        self.addCleanup(self._restore)

    def _restore(self):
        script.sources = self._saved_sources

    def _use(self, cloud_owners, sheet_ids, sheets):
        fake = _RecordingSources(cloud_owners, sheet_ids, sheets)
        script.sources = fake
        return fake

    def test_only_cloud_bearing_sheets_are_costed(self):
        """1000 張圖紙、其中 2 張有雲，就只能為那 2 張做欄位掃描。"""
        sheets = [sheet_row(1000 + i, u'A2-{:03d}'.format(i))
                  for i in range(1000)]
        fake = self._use({1003: [RevisionCloud(1, 1003)],
                          1007: [RevisionCloud(2, 1007),
                                 RevisionCloud(3, 1007)]},
                         set(row['ElementId'] for row in sheets), sheets)

        records, unmapped = script._sheet_cloud_records(object())

        self.assertEqual([{1003, 1007}], fake.sheet_records_calls,
                         u'sheet_records 不該被要求算全部圖紙')
        self.assertEqual([1003, 1007], [r['id'] for r in records])
        self.assertEqual([1, 2], [r['cloud_count'] for r in records])
        self.assertEqual(0, unmapped)

    def test_sheets_without_clouds_are_left_out(self):
        """沒有雲的圖紙在這個 UI 上什麼都不能做，列出來只是雜訊。"""
        sheets = [sheet_row(1000, u'A2-000'), sheet_row(1001, u'A2-001')]
        self._use({1001: [RevisionCloud(1, 1001)]},
                  {1000, 1001}, sheets)
        records, unmapped = script._sheet_cloud_records(object())
        self.assertEqual([1001], [r['id'] for r in records])

    def test_clouds_in_views_are_reported_as_out_of_scope(self):
        """視圖裡的雲座標系不同，不能亂標，但要讓使用者知道有幾朵。"""
        sheets = [sheet_row(1000, u'A2-000')]
        self._use({1000: [RevisionCloud(1, 1000)],
                   555: [RevisionCloud(2, 555), RevisionCloud(3, 555)]},
                  {1000}, sheets)
        records, unmapped = script._sheet_cloud_records(object())
        self.assertEqual([1000], [r['id'] for r in records])
        self.assertEqual(2, unmapped)

    def test_no_clouds_means_no_sheet_scan_at_all(self):
        """一朵雲都沒有時，連便宜的圖紙查詢都不必做。"""
        fake = self._use({}, {1000}, [sheet_row(1000, u'A2-000')])
        records, unmapped = script._sheet_cloud_records(object())
        self.assertEqual(([], 0), (records, unmapped))
        self.assertEqual([], fake.sheet_records_calls)

    def test_only_view_clouds_skips_the_sheet_scan_too(self):
        fake = self._use({555: [RevisionCloud(1, 555)]}, {1000},
                         [sheet_row(1000, u'A2-000')])
        records, unmapped = script._sheet_cloud_records(object())
        self.assertEqual([], records)
        self.assertEqual(1, unmapped)
        self.assertEqual([], fake.sheet_records_calls)


class TagScanTests(unittest.TestCase):
    """只掃修訂雲標籤，不掃整份文件的 IndependentTag。"""

    def test_the_collector_filters_by_revision_cloud_tag_category(self):
        doc = FakeDocument()
        doc.tags = [
            IndependentTag(1000, 501, 'OST_RevisionCloudTags'),
            IndependentTag(1000, 502, 'OST_RevisionCloudTags'),
            IndependentTag(1000, 900, 'OST_DoorTags'),
            IndependentTag(2000, 503, 'OST_RevisionCloudTags'),
        ]

        result = script._tagged_cloud_ids_by_sheet(doc, [1000])

        self.assertEqual([[('OfCategory', 'OST_RevisionCloudTags')]],
                         doc.collector_filters,
                         u'不可以再用 OfClass(IndependentTag) 掃全部標籤')
        self.assertEqual({501, 502}, result[1000])
        self.assertNotIn(2000, result)

    def test_an_empty_sheet_list_does_no_work(self):
        doc = FakeDocument()
        doc.tags = [IndependentTag(1000, 501, 'OST_RevisionCloudTags')]
        self.assertEqual({}, script._tagged_cloud_ids_by_sheet(doc, []))
        self.assertEqual([], doc.collector_filters)


class ElementIdAccessorTests(unittest.TestCase):
    """存取器解析一次就好——這支函式在大案子裡會被呼叫幾十萬次。"""

    def setUp(self):
        self._saved = script._ID_ACCESSOR
        script._ID_ACCESSOR = None

    def tearDown(self):
        script._ID_ACCESSOR = self._saved

    def test_older_revit_does_not_pay_for_a_missing_value_property(self):
        self.assertEqual(42, script._id_value(ElementId(42)))
        self.assertEqual('IntegerValue', script._ID_ACCESSOR)

    def test_newer_revit_still_works(self):
        self.assertEqual(42, script._id_value(ModernElementId(42)))
        self.assertEqual('Value', script._ID_ACCESSOR)

    def test_a_cached_accessor_recovers_when_it_stops_working(self):
        script._ID_ACCESSOR = 'IntegerValue'
        self.assertEqual(7, script._id_value(ModernElementId(7)))
        self.assertEqual('Value', script._ID_ACCESSOR)

    def test_none_is_minus_one(self):
        self.assertEqual(-1, script._id_value(None))


class GuardTests(unittest.TestCase):
    """WPF 事件處理常式丟出去的例外會終止 Revit，一律要被攔下來。"""

    def test_guard_turns_an_exception_into_an_alert(self):
        class Fake(object):
            @script._guard
            def handler(self, sender, args):
                raise ValueError('boom')

        Fake().handler(None, None)  # 沒有 _guard 的話這裡會炸到 dispatcher

    def test_guard_passes_the_result_through(self):
        class Fake(object):
            @script._guard
            def handler(self, sender, args):
                return 'ok'

        self.assertEqual('ok', Fake().handler(None, None))


if __name__ == '__main__':
    unittest.main()
