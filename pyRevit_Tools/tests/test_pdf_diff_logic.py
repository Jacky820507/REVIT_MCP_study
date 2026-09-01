# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""``pdf_diff_logic`` 的測試。

重心在**座標換算的 y 軸翻轉**：PyMuPDF 原點左上、y 向下，Revit 圖紙原點
左下、y 向上。少翻一次，雲會出現在圖紙的另一半——而且因為它「有動」，
肉眼很容易誤以為程式在正常運作。所以這裡的測試刻意用不對稱的位置
（頁面上緣的東西必須落到圖紙上緣），對稱的測資會讓翻轉錯誤矇混過關。
"""

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import pdf_diff_logic as logic


# A1 橫式：841 x 594 mm。PDF 以 point 表示，Revit 以 foot。
A1_PAGE_PT = (2383.94, 1683.78)
A1_SHEET_FT = (0.0, 841.0 / 304.8 * 0.0 + 0.0,
               841.0 / 304.8, 594.0 / 304.8)


_UNSET = object()


def sheet(number=u'A-101', name=u'一樓平面圖', outline=_UNSET):
    # 用 sentinel 而不是 None 當預設值，否則 outline=None 的測資會被
    # 預設值吃掉，「沒有 Outline 的圖紙」那條測試就永遠測不到。
    return {'SheetNumber': number, 'SheetName': name,
            'Outline': A1_SHEET_FT if outline is _UNSET else outline}


def region(label=u'F5', bbox=(100.0, 100.0, 200.0, 200.0),
           samples=None, text_count=0, geom_count=0):
    return {'gridLabel': label, 'bbox': bbox, 'samples': samples or [],
            'textCount': text_count, 'geomCount': geom_count}


class UnitTests(unittest.TestCase):
    def test_millimetres_convert_to_feet(self):
        self.assertAlmostEqual(1.0, logic.mm_to_feet(304.8), places=9)

    def test_the_conversion_round_trips(self):
        self.assertAlmostEqual(123.4, logic.feet_to_mm(
            logic.mm_to_feet(123.4)), places=9)


class MapPdfBboxToSheetTests(unittest.TestCase):
    def test_the_top_of_the_page_maps_to_the_top_of_the_sheet(self):
        """**這是整個模組最重要的一條測試。** PDF 的 y0（上緣，y 向下計）
        必須落到圖紙的 max_v（上緣，y 向上計）。少翻一次就會顛倒。"""
        rect = logic.map_pdf_bbox_to_sheet(
            (0.0, 0.0, 100.0, 100.0), (1000.0, 1000.0), (0.0, 0.0, 10.0, 10.0))
        # 頁面最上面 10% -> 圖紙最上面 10%，也就是 v 落在 9.0 ~ 10.0
        self.assertAlmostEqual(9.0, rect[1], places=6)
        self.assertAlmostEqual(10.0, rect[3], places=6)

    def test_the_bottom_of_the_page_maps_to_the_bottom_of_the_sheet(self):
        rect = logic.map_pdf_bbox_to_sheet(
            (0.0, 900.0, 100.0, 1000.0), (1000.0, 1000.0),
            (0.0, 0.0, 10.0, 10.0))
        self.assertAlmostEqual(0.0, rect[1], places=6)
        self.assertAlmostEqual(1.0, rect[3], places=6)

    def test_the_left_edge_stays_on_the_left(self):
        """x 軸沒有翻轉，如果連 x 也翻了就是把翻轉套錯軸。"""
        rect = logic.map_pdf_bbox_to_sheet(
            (0.0, 0.0, 100.0, 1000.0), (1000.0, 1000.0),
            (0.0, 0.0, 10.0, 10.0))
        self.assertAlmostEqual(0.0, rect[0], places=6)
        self.assertAlmostEqual(1.0, rect[2], places=6)

    def test_the_result_is_always_a_valid_minmax_rectangle(self):
        """翻轉後 v 的大小順序會反過來，必須重新取 min/max。"""
        rect = logic.map_pdf_bbox_to_sheet(
            (10.0, 20.0, 90.0, 80.0), (100.0, 100.0), (0.0, 0.0, 10.0, 10.0))
        self.assertLess(rect[0], rect[2])
        self.assertLess(rect[1], rect[3])

    def test_a_sheet_outline_that_does_not_start_at_zero_is_honoured(self):
        """``sheet.Outline`` 的 Min 不保證是 (0,0)。"""
        rect = logic.map_pdf_bbox_to_sheet(
            (0.0, 0.0, 100.0, 100.0), (1000.0, 1000.0),
            (5.0, 3.0, 15.0, 13.0))
        self.assertAlmostEqual(5.0, rect[0], places=6)
        self.assertAlmostEqual(12.0, rect[1], places=6)

    def test_a_real_a1_sheet_maps_proportionally(self):
        rect = logic.map_pdf_bbox_to_sheet(
            (0.0, 0.0, A1_PAGE_PT[0], A1_PAGE_PT[1]),
            A1_PAGE_PT, A1_SHEET_FT)
        self.assertAlmostEqual(A1_SHEET_FT[0], rect[0], places=6)
        self.assertAlmostEqual(A1_SHEET_FT[2], rect[2], places=6)
        self.assertAlmostEqual(A1_SHEET_FT[3], rect[3], places=6)

    def test_a_zero_sized_page_returns_none_instead_of_dividing_by_zero(self):
        self.assertIsNone(logic.map_pdf_bbox_to_sheet(
            (0.0, 0.0, 1.0, 1.0), (0.0, 100.0), (0.0, 0.0, 1.0, 1.0)))


class CheckAspectMatchTests(unittest.TestCase):
    def test_a_matching_page_and_sheet_pass(self):
        ok, message = logic.check_aspect_match(A1_PAGE_PT, A1_SHEET_FT)
        self.assertTrue(ok)
        self.assertIsNone(message)

    def test_a_portrait_page_on_a_landscape_sheet_is_flagged(self):
        """配錯圖紙時座標仍然算得出來、雲仍然畫得出來，只是全錯。
        長寬比是唯一便宜又有效的偵測。"""
        ok, message = logic.check_aspect_match(
            (A1_PAGE_PT[1], A1_PAGE_PT[0]), A1_SHEET_FT)
        self.assertFalse(ok)
        self.assertIn(u'長寬比', message)

    def test_a_small_discrepancy_is_tolerated(self):
        ok, _ = logic.check_aspect_match(
            (A1_PAGE_PT[0] * 1.005, A1_PAGE_PT[1]), A1_SHEET_FT)
        self.assertTrue(ok)

    def test_a_degenerate_sheet_is_reported_not_crashed(self):
        ok, message = logic.check_aspect_match(A1_PAGE_PT, (0.0, 0.0, 0.0, 0.0))
        self.assertFalse(ok)
        self.assertIn(u'無效', message)


class BuildCloudRectTests(unittest.TestCase):
    def test_padding_expands_the_rectangle_on_every_side(self):
        rect = logic.build_cloud_rect((1.0, 1.0, 2.0, 2.0), padding_mm=304.8,
                                      min_size_mm=0.0)
        self.assertAlmostEqual(0.0, rect[0], places=6)
        self.assertAlmostEqual(3.0, rect[2], places=6)

    def test_a_tiny_region_is_grown_to_the_minimum(self):
        """Revit 的雲由弧組成，框比一個弧小時 ``RevisionCloud.Create`` 會丟例外。
        在這裡撐大，好過在 Revit 端整批一個個失敗。"""
        rect = logic.build_cloud_rect((1.0, 1.0, 1.0001, 1.0001),
                                      padding_mm=0.0, min_size_mm=15.0)
        self.assertAlmostEqual(logic.mm_to_feet(15.0), rect[2] - rect[0],
                               places=6)
        self.assertAlmostEqual(logic.mm_to_feet(15.0), rect[3] - rect[1],
                               places=6)

    def test_growing_keeps_the_region_centred(self):
        """以中心為基準往兩邊撐，位置才不會偏掉。"""
        rect = logic.build_cloud_rect((5.0, 5.0, 5.0, 5.0),
                                      padding_mm=0.0, min_size_mm=15.0)
        self.assertAlmostEqual(5.0, (rect[0] + rect[2]) / 2.0, places=6)
        self.assertAlmostEqual(5.0, (rect[1] + rect[3]) / 2.0, places=6)

    def test_a_large_region_is_left_alone_apart_from_padding(self):
        rect = logic.build_cloud_rect((0.0, 0.0, 5.0, 5.0), padding_mm=0.0,
                                      min_size_mm=15.0)
        self.assertAlmostEqual(5.0, rect[2] - rect[0], places=6)


class ClampToSheetTests(unittest.TestCase):
    def test_a_region_hanging_off_the_edge_is_pulled_back(self):
        """雲畫在圖紙外不會報錯，但會變成掃描釋疑時撿到的幽靈元素。"""
        rect = logic.clamp_to_sheet((-1.0, -1.0, 99.0, 99.0),
                                    (0.0, 0.0, 10.0, 10.0))
        self.assertEqual((0.0, 0.0, 10.0, 10.0), rect)

    def test_a_region_inside_the_sheet_is_untouched(self):
        rect = logic.clamp_to_sheet((1.0, 1.0, 2.0, 2.0),
                                    (0.0, 0.0, 10.0, 10.0))
        self.assertEqual((1.0, 1.0, 2.0, 2.0), rect)


class SheetKeyTests(unittest.TestCase):
    def test_case_and_whitespace_are_normalized(self):
        self.assertEqual(logic.normalize_sheet_key(u'  a-101 '),
                         logic.normalize_sheet_key(u'A-101'))

    def test_separators_survive_the_strict_key(self):
        """``A-101`` 與 ``A101`` 在很多案子裡是兩張不同的圖。"""
        self.assertNotEqual(logic.normalize_sheet_key(u'A-101'),
                            logic.normalize_sheet_key(u'A101'))

    def test_the_loose_key_drops_separators(self):
        self.assertEqual(logic.loose_sheet_key(u'A-101'),
                         logic.loose_sheet_key(u'A 101'))

    def test_none_is_an_empty_key(self):
        self.assertEqual(u'', logic.normalize_sheet_key(None))


class PairSheetsTests(unittest.TestCase):
    def page(self, number):
        return {'sheetNumber': number, 'pageWidthPt': A1_PAGE_PT[0],
                'pageHeightPt': A1_PAGE_PT[1]}

    def test_an_exact_match_is_preferred(self):
        matched, unmatched, unused = logic.pair_sheets(
            [self.page(u'A-101')], [sheet(u'A-101')])
        self.assertEqual(1, len(matched))
        self.assertEqual('exact', matched[0]['match'])
        self.assertEqual([], unmatched)
        self.assertEqual([], unused)

    def test_a_loose_match_is_used_only_as_a_fallback_and_is_labelled(self):
        """寬鬆比對可能配錯，所以要標記讓 UI 提醒使用者確認。"""
        matched, _, _ = logic.pair_sheets(
            [self.page(u'A101')], [sheet(u'A-101')])
        self.assertEqual('loose', matched[0]['match'])

    def test_exact_wins_when_both_are_possible(self):
        """兩張圖紙都「配得上」時，不能讓寬鬆比對搶走嚴格比對的對象。"""
        matched, _, _ = logic.pair_sheets(
            [self.page(u'A-101')], [sheet(u'A101'), sheet(u'A-101')])
        self.assertEqual('exact', matched[0]['match'])
        self.assertEqual(u'A-101', matched[0]['sheet']['SheetNumber'])

    def test_full_pdf_dwg_number_matches_revit_dwg_suffix_before_sheet_number(self):
        """PDF 的專案前綴不能讓它退回配到 A2-01 等錯誤圖紙。"""
        revit_sheet = sheet(u'A2-01')
        revit_sheet['DwgNumber'] = u'ARD-D02001'
        matched, unmatched, _ = logic.pair_sheets(
            [self.page(u'0721B-ARD-D02001')], [revit_sheet])
        self.assertEqual([], unmatched)
        self.assertEqual(u'A2-01', matched[0]['sheet']['SheetNumber'])
        self.assertEqual('DwgNumber', matched[0]['matchField'])

    def test_a_page_with_no_counterpart_is_returned_not_dropped(self):
        matched, unmatched, _ = logic.pair_sheets(
            [self.page(u'A-999')], [sheet(u'A-101')])
        self.assertEqual([], matched)
        self.assertEqual(1, len(unmatched))

    def test_sheets_without_a_page_are_reported(self):
        _, _, unused = logic.pair_sheets([], [sheet(u'A-101')])
        self.assertEqual(1, len(unused))

    def test_a_page_without_a_sheet_number_is_never_silently_paired(self):
        matched, unmatched, _ = logic.pair_sheets(
            [self.page(None)], [sheet(u'A-101')])
        self.assertEqual([], matched)
        self.assertEqual(1, len(unmatched))

    def test_one_sheet_is_not_consumed_twice(self):
        matched, unmatched, _ = logic.pair_sheets(
            [self.page(u'A-101'), self.page(u'A-101')], [sheet(u'A-101')])
        self.assertEqual(1, len(matched))
        self.assertEqual(1, len(unmatched))


class DescribeRegionTests(unittest.TestCase):
    def test_a_value_change_is_spelled_out(self):
        """``CH=300 -> CH=320`` 是使用者真正想看的內容。"""
        text = logic.describe_region(region(
            u'F5:F7',
            samples=[{'kind': 'geom-add'},
                     {'kind': 'text-change', 'before': u'CH=300',
                      'after': u'CH=320'}]))
        self.assertIn(u'CH=300', text)
        self.assertIn(u'CH=320', text)
        self.assertIn(u'F5:F7', text)

    def test_an_added_label_is_described(self):
        text = logic.describe_region(region(
            samples=[{'kind': 'text-add', 'after': u'RFI-106'}]))
        self.assertIn(u'RFI-106', text)
        self.assertIn(u'新增', text)

    def test_a_geometry_only_region_falls_back_to_counts(self):
        text = logic.describe_region(region(
            samples=[{'kind': 'geom-add'}], text_count=0, geom_count=9))
        self.assertIn(u'9', text)

    def test_the_grid_label_is_always_present(self):
        """這行字之後會被 scan_revision_clouds 讀進釋疑 Excel，
        必須能脫離 UI 上下文獨立閱讀。"""
        self.assertIn(u'[F5]', logic.describe_region(region(u'F5')))


class BuildCloudRequestsTests(unittest.TestCase):
    def pairing(self, regions=None, sheet_record=None, page=None):
        return {
            'page': page or {'sheetNumber': u'A-101',
                             'pageWidthPt': A1_PAGE_PT[0],
                             'pageHeightPt': A1_PAGE_PT[1]},
            'sheet': sheet_record or sheet(),
            'regions': regions if regions is not None else [region()],
        }

    def test_a_region_becomes_one_cloud_request(self):
        clouds, skipped = logic.build_cloud_requests([self.pairing()])
        self.assertEqual(1, len(clouds))
        self.assertEqual([], skipped)
        self.assertEqual(u'A-101', clouds[0]['sheetNumber'])
        self.assertIn('rectFt', clouds[0])

    def test_request_carries_sheet_id_and_pdf_dwg_number(self):
        record = sheet(u'A2-01')
        record['ElementId'] = 2468
        record['DwgNumber'] = u'ARD-D02001'
        page = {'sheetNumber': u'0721B-ARD-D02001',
                'pageWidthPt': A1_PAGE_PT[0],
                'pageHeightPt': A1_PAGE_PT[1]}
        clouds, skipped = logic.build_cloud_requests(
            [self.pairing(sheet_record=record, page=page)])
        self.assertEqual([], skipped)
        self.assertEqual(2468, clouds[0]['sheetId'])
        self.assertEqual(u'ARD-D02001', clouds[0]['dwgNumber'])

    def test_request_carries_selected_cloud_orientation_reference(self):
        clouds, skipped = logic.build_cloud_requests(
            [self.pairing()], {'referenceCloudId': 5482660})
        self.assertEqual([], skipped)
        self.assertEqual(5482660, clouds[0]['referenceCloudId'])

    def test_the_rectangle_is_inside_the_sheet(self):
        clouds, _ = logic.build_cloud_requests([self.pairing()])
        rect = clouds[0]['rectFt']
        self.assertGreaterEqual(rect['minU'], A1_SHEET_FT[0])
        self.assertLessEqual(rect['maxV'], A1_SHEET_FT[3])

    def test_a_sheet_without_an_outline_is_skipped_with_a_reason(self):
        """靜默少畫是這種工具最惡劣的失敗方式——使用者會以為那裡沒差異。"""
        clouds, skipped = logic.build_cloud_requests(
            [self.pairing(sheet_record=sheet(outline=None))])
        self.assertEqual([], clouds)
        self.assertEqual(1, len(skipped))
        self.assertIn(u'Outline', skipped[0]['reason'])

    def test_an_aspect_mismatch_attaches_a_warning_but_still_builds(self):
        """要不要接受比例不符是使用者的判斷，不是這裡擅自擋掉。"""
        clouds, _ = logic.build_cloud_requests([self.pairing(
            page={'sheetNumber': u'A-101',
                  'pageWidthPt': A1_PAGE_PT[1],
                  'pageHeightPt': A1_PAGE_PT[0]})])
        self.assertEqual(1, len(clouds))
        self.assertIn('warning', clouds[0])

    def test_a_pairing_with_no_selected_regions_produces_nothing(self):
        clouds, skipped = logic.build_cloud_requests(
            [self.pairing(regions=[])])
        self.assertEqual([], clouds)
        self.assertEqual([], skipped)

    def test_the_comment_carries_the_change_description(self):
        clouds, _ = logic.build_cloud_requests([self.pairing(regions=[
            region(samples=[{'kind': 'text-change', 'before': u'CH=300',
                             'after': u'CH=320'}])])])
        self.assertIn(u'CH=320', clouds[0]['comment'])

    def test_generated_comment_is_compact_but_identifiable(self):
        clouds, _ = logic.build_cloud_requests([self.pairing(regions=[
            region(u'F4:F5', samples=[
                {'kind': 'text-add', 'after': u'D4a'}])])])
        comment = clouds[0]['comment']
        self.assertEqual(u'[自動] F4:F5｜新增：D4a', comment)
        self.assertNotIn(u'PDF:', comment)
        self.assertNotIn(u'Revit:', comment)

    def test_comment_prefers_equipment_name_over_isolated_dimension(self):
        clouds, _ = logic.build_cloud_requests([self.pairing(regions=[
            region(u'E3:F4', samples=[
                {'kind': 'text-change', 'before': u'185',
                 'after': u'195'},
                {'kind': 'text-add', 'after': u'6-7'},
                {'kind': 'text-add', 'after': u'不鏽鋼活動扶手欄杆'}])])])
        self.assertEqual(
            u'[自動] E3:F4｜新增：不鏽鋼活動扶手欄杆',
            clouds[0]['comment'])


class SummarizeTests(unittest.TestCase):
    def test_the_cloud_count_leads(self):
        text = logic.summarize([{'sheetNumber': u'A-101', 'gridLabel': u'F5'}],
                               [])
        self.assertIn(u'1 朵', text)

    def test_skipped_entries_are_shown_before_the_user_confirms(self):
        """使用者按下確認之前就該看到全貌，不是事後才發現少了東西。"""
        text = logic.summarize(
            [], [{'sheetNumber': u'A-101', 'gridLabel': u'F5',
                  'reason': u'圖紙沒有 Outline'}])
        self.assertIn(u'跳過', text)
        self.assertIn(u'Outline', text)

    def test_unpaired_pages_and_sheets_are_reported(self):
        text = logic.summarize([], [], unmatched_pages=[{}, {}],
                               unused_sheets=[{}])
        self.assertIn(u'2 頁', text)
        self.assertIn(u'1 張', text)

    def test_clouds_are_grouped_by_sheet(self):
        text = logic.summarize([
            {'sheetNumber': u'A-101', 'gridLabel': u'F5'},
            {'sheetNumber': u'A-101', 'gridLabel': u'K1'},
            {'sheetNumber': u'A-102', 'gridLabel': u'B2'},
        ], [])
        self.assertIn(u'A-101　2 朵', text)
        self.assertIn(u'A-102　1 朵', text)


if __name__ == '__main__':
    unittest.main()


class FormatFractionPercentTests(unittest.TestCase):
    """IronPython 2.7 專屬地雷的回歸測試。

    **CPython 測不到那個錯**（`'{:.2f}'.format(0)` 在 CPython 完全正常），
    所以這裡斷言的是「送進格式化的一定是 float」這個不變量，以及各種
    falsy 輸入都不會回傳空字串或炸掉。實測災情：面積 0.00% 的區域讓整個
    pyRevit 視窗掛掉，並帶著 Revit 一起「發生嚴重錯誤，應用程式將終止」。
    """

    def test_zero_is_formatted_not_skipped(self):
        """0.0 是 falsy，最自然的 `or 0` 寫法會把它變成 int——就是這個坑。"""
        self.assertEqual(u'0.00%', logic.format_fraction_percent(0.0))

    def test_an_integer_zero_is_coerced_to_float(self):
        self.assertEqual(u'0.00%', logic.format_fraction_percent(0))

    def test_none_is_treated_as_zero(self):
        self.assertEqual(u'0.00%', logic.format_fraction_percent(None))

    def test_a_normal_fraction_reads_as_a_percentage(self):
        self.assertEqual(u'0.72%', logic.format_fraction_percent(0.0072))

    def test_a_whole_page_is_one_hundred_percent(self):
        self.assertEqual(u'100.00%', logic.format_fraction_percent(1.0))

    def test_places_can_be_reduced(self):
        self.assertEqual(u'0.7%', logic.format_fraction_percent(0.0072, 1))
        self.assertEqual(u'1%', logic.format_fraction_percent(0.0072, 0))
