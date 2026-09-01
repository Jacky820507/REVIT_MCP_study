# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""``pdf_diff_worker`` 的純函式測試。

這一套測試的重心是**負向測試**：不該報差異的時候真的沒報。
向量比對這種工具失敗的方式從來不是「找不到差異」，而是「整頁都亮起來」，
所以每一道防線（座標量化、全域平移、格網門檻）都要有一個對應的
「假差異被吃掉了」的案例。只測「真差異抓得到」會漏掉全部的實際故障模式。

本檔不需要安裝 PyMuPDF——worker 把 ``fitz`` 的匯入關在 ``_require_fitz()`` 裡，
就是為了讓這些參數能離線反覆調校。
"""

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import pdf_diff_worker as worker


def span(text, x0, y0, x1=None, y1=None):
    if x1 is None:
        x1 = x0 + 10.0
    if y1 is None:
        y1 = y0 + 8.0
    return {'text': text, 'bbox': (x0, y0, x1, y1)}


def line(x0, y0, x1, y1):
    """一條線段，格式比照 :func:`pdf_diff_worker.extract_drawings` 的輸出。"""
    return {'items': [('l', (x0, y0), (x1, y1))]}


class NormalizeTextTests(unittest.TestCase):
    def test_fullwidth_digits_equal_halfwidth(self):
        """圖說裡全形半形混用是常態，不統一會製造整批假差異。"""
        self.assertEqual(worker.normalize_text('ＣＨ＝３００'),
                         worker.normalize_text('CH=300'))

    def test_runs_of_whitespace_collapse(self):
        """不同 PDF 引擎切 span 的位置不同，塞進來的空白數量也不同。"""
        self.assertEqual('CH = 300', worker.normalize_text('CH  =\t300 '))

    def test_case_is_not_folded(self):
        """大小寫若真的不同就是差異，不該被吃掉。"""
        self.assertNotEqual(worker.normalize_text('ch'),
                            worker.normalize_text('CH'))

    def test_none_is_empty(self):
        self.assertEqual('', worker.normalize_text(None))


class EstimatePageOffsetTests(unittest.TestCase):
    def test_a_whole_page_shift_is_recovered(self):
        a = [span('T{}'.format(i), i * 20.0, 100.0) for i in range(10)]
        b = [span('T{}'.format(i), i * 20.0 + 7.0, 103.0) for i in range(10)]
        dx, dy = worker.estimate_page_offset(a, b)
        self.assertAlmostEqual(7.0, dx, places=6)
        self.assertAlmostEqual(3.0, dy, places=6)

    def test_a_few_moved_anchors_do_not_drag_the_estimate(self):
        """用中位數而非平均：少數真的被移動過的文字不能把整頁推歪。"""
        a = [span('T{}'.format(i), i * 20.0, 100.0) for i in range(10)]
        b = [span('T{}'.format(i), i * 20.0 + 5.0, 100.0) for i in range(8)]
        b.append(span('T8', 8 * 20.0 + 900.0, 100.0))
        b.append(span('T9', 9 * 20.0 + 900.0, 100.0))
        dx, _ = worker.estimate_page_offset(a, b)
        self.assertAlmostEqual(5.0, dx, places=6)

    def test_too_few_anchors_gives_no_shift(self):
        """寧可不對齊，也不要用三四個點亂推一個平移量。"""
        a = [span('T{}'.format(i), i * 20.0, 100.0) for i in range(3)]
        b = [span('T{}'.format(i), i * 20.0 + 50.0, 100.0) for i in range(3)]
        self.assertEqual((0.0, 0.0), worker.estimate_page_offset(a, b))

    def test_repeated_text_is_not_used_as_an_anchor(self):
        """重複出現的文字配對會亂跳，只會製造噪音。"""
        a = [span('1', 10.0, 10.0), span('1', 900.0, 900.0)]
        b = [span('1', 500.0, 500.0), span('1', 20.0, 20.0)]
        self.assertEqual((0.0, 0.0), worker.estimate_page_offset(a, b))


class DiffTextSpansTests(unittest.TestCase):
    def test_identical_pages_produce_no_diff(self):
        spans = [span('CH=300', 10.0, 10.0), span('RC', 50.0, 50.0)]
        self.assertEqual([], worker.diff_text_spans(spans, list(spans)))

    def test_same_text_within_tolerance_is_not_a_move(self):
        """次像素抖動不是變更。"""
        a = [span('CH=300', 10.0, 10.0)]
        b = [span('CH=300', 11.0, 10.0)]
        self.assertEqual([], worker.diff_text_spans(a, b, move_tol=2.0))

    def test_a_value_edited_in_place_is_reported_as_a_change(self):
        """圖說變更絕大多數長這樣，這是最有價值的一種輸出。"""
        diffs = worker.diff_text_spans([span('CH=300', 10.0, 10.0)],
                                       [span('CH=320', 10.0, 10.0)])
        self.assertEqual(1, len(diffs))
        self.assertEqual('text-change', diffs[0]['kind'])
        self.assertEqual('CH=300', diffs[0]['before'])
        self.assertEqual('CH=320', diffs[0]['after'])

    def test_text_only_in_the_old_version_is_a_delete(self):
        diffs = worker.diff_text_spans([span('RFI-106', 10.0, 10.0)], [])
        self.assertEqual(['text-delete'], [d['kind'] for d in diffs])

    def test_text_only_in_the_new_version_is_an_add(self):
        diffs = worker.diff_text_spans([], [span('RFI-106', 10.0, 10.0)])
        self.assertEqual(['text-add'], [d['kind'] for d in diffs])

    def test_same_text_far_away_is_a_move(self):
        diffs = worker.diff_text_spans([span('N1', 10.0, 10.0)],
                                       [span('N1', 400.0, 400.0)])
        self.assertEqual(['text-move'], [d['kind'] for d in diffs])

    def test_a_change_is_anchored_at_the_new_position(self):
        """區域要圈在新版的位置上，使用者才找得到要看的地方。"""
        diffs = worker.diff_text_spans([span('A', 10.0, 10.0)],
                                       [span('B', 11.0, 10.0)])
        self.assertEqual('text-change', diffs[0]['kind'])
        self.assertAlmostEqual(16.0, diffs[0]['point'][0], places=6)

    def test_repeated_label_elsewhere_does_not_steal_in_place_change(self):
        old = [span('D3', 10.0, 10.0), span('D3', 100.0, 10.0)]
        new = [span('D4a', 10.0, 10.0), span('D3', 100.0, 10.0)]
        diffs = worker.diff_text_spans(old, new)
        self.assertEqual(1, len(diffs))
        self.assertEqual('text-change', diffs[0]['kind'])
        self.assertEqual('D3', diffs[0]['before'])
        self.assertEqual('D4a', diffs[0]['after'])
        self.assertEqual(worker.span_center(new[0]['bbox']), diffs[0]['point'])

    def test_repeated_door_numbers_keep_the_changed_instance_location(self):
        old = [span('184', 20.0, 20.0), span('184', 200.0, 20.0)]
        new = [span('185', 20.0, 20.0), span('184', 200.0, 20.0)]
        diffs = worker.diff_text_spans(old, new)
        self.assertEqual(1, len(diffs))
        self.assertEqual('text-change', diffs[0]['kind'])
        self.assertEqual(worker.span_center(new[0]['bbox']), diffs[0]['point'])
        self.assertGreaterEqual(diffs[0]['similarity'], 0.6)

    def test_overlaid_text_uses_content_similarity_to_disambiguate(self):
        old = [span('D3', 10.0, 10.0)]
        new = [span('F60A', 10.0, 10.0), span('D4a', 10.5, 10.0)]
        diffs = worker.diff_text_spans(old, new)
        changes = [item for item in diffs if item['kind'] == 'text-change']
        self.assertEqual(1, len(changes))
        self.assertEqual('D4a', changes[0]['after'])

    def test_locally_shifted_companion_label_does_not_steal_change(self):
        old = [span('D3', 10.0, 10.0), span('F60A', 10.0, 15.0)]
        new = [span('D4a', 10.0, 16.0), span('F60A', 10.0, 21.0)]
        diffs = worker.diff_text_spans(old, new)
        changes = [item for item in diffs if item['kind'] == 'text-change']
        self.assertEqual(1, len(changes))
        self.assertEqual(('D3', 'D4a'),
                         (changes[0]['before'], changes[0]['after']))


class FingerprintTests(unittest.TestCase):
    def keys(self, fingerprints):
        return [item[0] for item in fingerprints]

    def test_sub_quantum_jitter_produces_the_same_fingerprint(self):
        """第一道防線：同一條線在兩版 PDF 的座標微差不該成案。"""
        a = worker.fingerprint_drawings([line(10.0, 10.0, 50.0, 10.0)], 0.5)
        b = worker.fingerprint_drawings([line(10.1, 9.95, 50.05, 10.1)], 0.5)
        self.assertEqual(self.keys(a), self.keys(b))

    def test_a_real_move_changes_the_fingerprint(self):
        a = worker.fingerprint_drawings([line(10.0, 10.0, 50.0, 10.0)], 0.5)
        b = worker.fingerprint_drawings([line(10.0, 30.0, 50.0, 30.0)], 0.5)
        self.assertNotEqual(self.keys(a), self.keys(b))

    def test_colour_and_width_are_not_part_of_the_fingerprint(self):
        """圖層顏色微調不是圖面變更。"""
        path_a = {'items': [('l', (0.0, 0.0), (10.0, 0.0))],
                  'color': (1, 0, 0), 'width': 0.5}
        path_b = {'items': [('l', (0.0, 0.0), (10.0, 0.0))],
                  'color': (0, 0, 1), 'width': 2.0}
        self.assertEqual(self.keys(worker.fingerprint_drawings([path_a])),
                         self.keys(worker.fingerprint_drawings([path_b])))

    def test_a_rectangle_item_is_fingerprinted(self):
        fps = worker.fingerprint_drawings(
            [{'items': [('re', (0.0, 0.0, 20.0, 10.0))]}], 0.5)
        self.assertEqual(1, len(fps))
        self.assertEqual('re', fps[0][0][0])
        self.assertEqual((0.0, 0.0, 20.0, 10.0), fps[0][3])

    def test_rectangle_orientation_metadata_is_not_a_coordinate(self):
        fps = worker.fingerprint_drawings(
            [{'items': [('re', (300.0, 200.0, 500.0, 400.0), 1.0)]}],
            0.5)
        self.assertEqual((300.0, 200.0, 500.0, 400.0), fps[0][3])

    def test_rectangle_orientation_does_not_create_a_difference(self):
        positive = worker.fingerprint_drawings(
            [{'items': [('re', (300.0, 200.0, 500.0, 400.0), 1.0)]}])
        negative = worker.fingerprint_drawings(
            [{'items': [('re', (300.0, 200.0, 500.0, 400.0), -1.0)]}])
        self.assertEqual([], worker.diff_geometry(positive, negative))

    # 註：不要寫「primary 與 alternate 的標籤必須不同」這種測試。兩者的
    # 標籤值落在同一組格點上，重合是常態；真正不同的是分桶邊界。該驗的
    # 行為由下面這條與 AlignmentTests 的跨界那條涵蓋。

    def test_a_genuine_half_point_shift_is_not_merged_by_either_grid(self):
        """第二張格網不能寬鬆到把真的位移也吃掉。"""
        a = worker.fingerprint_drawings([line(60.0, 10.0, 100.0, 10.0)], 0.5)
        b = worker.fingerprint_drawings([line(60.5, 10.0, 100.5, 10.0)], 0.5)
        self.assertNotEqual([], worker.diff_geometry(a, b))


class AlignmentTests(unittest.TestCase):
    """第二道防線。

    這一組取代了先前一條「挑好數值剛好會過」的假綠燈測試。真實案例
    （PyMuPDF 產出的 A1 圖說，整頁平移 7.3pt）當時完全過不了：平移套用在
    **已量化**的座標上，同一條線的端點在 A 是 2124.0、在 B 是 2123.5。
    所以這裡不挑數值，改成掃一整批偏移量與座標，逐一斷言零差異。
    """

    OFFSETS = (0.0, 0.01, 0.24, 0.25, 0.26, 0.5, 1.0, 3.9, 7.3,
               7.300048828125, 12.5, 33.333, 100.75)

    def _grid(self, dx=0.0, dy=0.0):
        """一批座標刻意包含量化格線上與格線附近的值。"""
        drawings = []
        for x in (60.0, 60.25, 100.0, 2123.93701171875, 1553.779541015625):
            for y in (60.0, 60.24, 60.26, 1553.779541015625):
                drawings.append(line(x + dx, y + dy, x + dx + 40.0, y + dy))
        return drawings

    def test_a_pure_translation_leaves_no_geometry_diff(self):
        for offset in self.OFFSETS:
            base = worker.fingerprint_drawings(self._grid(), 0.5)
            moved = worker.fingerprint_drawings(
                self._grid(offset, offset / 2.0), 0.5, offset, offset / 2.0)
            self.assertEqual(
                [], worker.diff_geometry(base, moved),
                'offset {} 產生了假差異'.format(offset))

    def test_the_real_world_regression_case(self):
        """實測那條線的真實座標與真實偏移量，寫死進來當回歸測試。"""
        dx, dy = 7.300048828125, 3.900024414062
        a = worker.fingerprint_drawings(
            [line(60.0, 60.0, 2123.93701171875, 60.0)], 0.5)
        b = worker.fingerprint_drawings(
            [line(60.0 + dx, 60.0 + dy,
                  2123.93701171875 + dx, 60.0 + dy)], 0.5, dx, dy)
        self.assertEqual([], worker.diff_geometry(a, b))

    def test_a_genuine_change_survives_the_alignment(self):
        """對齊不能把真差異一起吃掉。"""
        base = worker.fingerprint_drawings(self._grid(), 0.5)
        moved_drawings = self._grid(7.3, 3.9)
        moved_drawings.append(line(500.0, 500.0, 600.0, 500.0))
        moved = worker.fingerprint_drawings(moved_drawings, 0.5, 7.3, 3.9)
        self.assertEqual(['geom-add'],
                         [d['kind'] for d in worker.diff_geometry(base, moved)])

    def test_coordinates_straddling_a_quantum_boundary_still_match(self):
        """``60.24`` 與 ``60.26`` 在原格網會被分到 60.0 與 60.5，
        半格格網會把它們合併回來。"""
        a = worker.fingerprint_drawings([line(60.24, 10.0, 100.0, 10.0)], 0.5)
        b = worker.fingerprint_drawings([line(60.26, 10.0, 100.0, 10.0)], 0.5)
        self.assertEqual([], worker.diff_geometry(a, b))


class DiffGeometryTests(unittest.TestCase):
    def test_identical_geometry_produces_no_diff(self):
        fps = worker.fingerprint_drawings([line(0.0, 0.0, 10.0, 0.0)])
        self.assertEqual([], worker.diff_geometry(fps, list(fps)))

    def test_an_added_line_is_reported(self):
        a = worker.fingerprint_drawings([line(0.0, 0.0, 10.0, 0.0)])
        b = worker.fingerprint_drawings([line(0.0, 0.0, 10.0, 0.0),
                                         line(0.0, 20.0, 10.0, 20.0)])
        diffs = worker.diff_geometry(a, b)
        self.assertEqual(['geom-add'], [d['kind'] for d in diffs])
        self.assertEqual((0.0, 20.0, 10.0, 20.0), diffs[0]['bbox'])

    def test_duplicate_removal_is_detected(self):
        """用 multiset 而非 set：畫兩次跟畫一次是不同的。"""
        twice = worker.fingerprint_drawings([line(0.0, 0.0, 10.0, 0.0),
                                             line(0.0, 0.0, 10.0, 0.0)])
        once = worker.fingerprint_drawings([line(0.0, 0.0, 10.0, 0.0)])
        self.assertEqual(['geom-delete'],
                         [d['kind'] for d in worker.diff_geometry(twice, once)])


class ColumnLabelTests(unittest.TestCase):
    def test_the_first_columns_are_single_letters(self):
        self.assertEqual('A', worker.column_label(0))
        self.assertEqual('F', worker.column_label(5))
        self.assertEqual('Z', worker.column_label(25))

    def test_it_rolls_over_like_a_spreadsheet(self):
        self.assertEqual('AA', worker.column_label(26))
        self.assertEqual('AB', worker.column_label(27))


class ClusterToGridTests(unittest.TestCase):
    def _geom(self, x, y):
        return {'kind': 'geom-add', 'point': (x, y)}

    def _text(self, x, y):
        return {'kind': 'text-change', 'point': (x, y),
                'before': 'a', 'after': 'b'}

    def test_an_isolated_geometry_diff_does_not_become_a_region(self):
        """第三道防線：單點差異不成案，成片才算。"""
        regions = worker.cluster_to_grid(
            [self._geom(50.0, 50.0)], 1200.0, 900.0, threshold=2.0)
        self.assertEqual([], regions)

    def test_a_dense_cluster_becomes_a_region(self):
        diffs = [self._geom(50.0 + i, 50.0) for i in range(6)]
        regions = worker.cluster_to_grid(diffs, 1200.0, 900.0, threshold=2.0)
        self.assertEqual(1, len(regions))
        self.assertEqual(6, regions[0]['geomCount'])

    def test_a_single_text_change_outweighs_a_single_line(self):
        """文字變更比線條變更重要得多，門檻上要反映這件事。"""
        self.assertEqual([], worker.cluster_to_grid(
            [self._geom(50.0, 50.0)], 1200.0, 900.0, threshold=2.0))
        self.assertEqual(1, len(worker.cluster_to_grid(
            [self._text(50.0, 50.0)], 1200.0, 900.0, threshold=2.0)))

    def test_adjacent_hot_cells_merge_into_one_region(self):
        cell_w = 1200.0 / 12
        diffs = []
        for cell in range(3):
            for i in range(6):
                diffs.append(self._geom(cell * cell_w + 10.0 + i, 50.0))
        regions = worker.cluster_to_grid(diffs, 1200.0, 900.0, threshold=2.0)
        self.assertEqual(1, len(regions))
        self.assertEqual('A1:C1', regions[0]['gridLabel'])

    def test_distant_clusters_stay_separate(self):
        diffs = [self._text(50.0, 50.0), self._text(1150.0, 850.0)]
        regions = worker.cluster_to_grid(diffs, 1200.0, 900.0, threshold=2.0)
        self.assertEqual(2, len(regions))

    def test_a_single_cell_region_has_no_range_in_its_label(self):
        regions = worker.cluster_to_grid(
            [self._text(50.0, 50.0)], 1200.0, 900.0, threshold=2.0)
        self.assertEqual('A1', regions[0]['gridLabel'])

    def test_the_bbox_covers_the_whole_hot_cell(self):
        """框要圈住整格，不能只圈到差異點——雲形本來就是粗略圈選。"""
        regions = worker.cluster_to_grid(
            [self._text(50.0, 50.0)], 1200.0, 900.0, cols=12, rows=9,
            threshold=2.0)
        self.assertEqual((0.0, 0.0, 100.0, 100.0), regions[0]['bbox'])

    def test_regions_are_ranked_by_score(self):
        diffs = [self._text(50.0, 50.0)]
        diffs.extend(self._text(1150.0, 850.0) for _ in range(5))
        regions = worker.cluster_to_grid(diffs, 1200.0, 900.0, threshold=2.0)
        self.assertGreater(regions[0]['score'], regions[1]['score'])

    def test_text_changes_are_sampled_before_geometry(self):
        """``CH=300 -> CH=320`` 一眼看懂，``geom-add`` 只能說「多了幾條線」。"""
        diffs = [self._geom(50.0, 50.0) for _ in range(8)]
        diffs.append(self._text(50.0, 50.0))
        regions = worker.cluster_to_grid(diffs, 1200.0, 900.0, threshold=2.0)
        self.assertEqual('text-change', regions[0]['samples'][0]['kind'])

    def test_a_point_on_the_far_edge_is_clamped_into_the_grid(self):
        regions = worker.cluster_to_grid(
            [self._text(1200.0, 900.0)], 1200.0, 900.0, cols=12, rows=9,
            threshold=2.0)
        self.assertEqual('L9', regions[0]['gridLabel'])

    def test_a_degenerate_page_yields_nothing_instead_of_dividing_by_zero(self):
        self.assertEqual([], worker.cluster_to_grid(
            [self._text(1.0, 1.0)], 0.0, 900.0))


class ExtractSheetNumberTests(unittest.TestCase):
    def test_it_finds_a_sheet_number_in_the_title_block(self):
        spans = [span('A-101', 1150.0, 880.0)]
        best, candidates = worker.extract_sheet_number(spans, 1200.0, 900.0)
        self.assertEqual('A-101', best)
        self.assertEqual(['A-101'], candidates)

    def test_text_outside_the_title_block_is_ignored(self):
        """圖面正中央出現的 ``A-101`` 是索引記號，不是這張圖的圖號。"""
        spans = [span('A-101', 100.0, 100.0)]
        best, _ = worker.extract_sheet_number(spans, 1200.0, 900.0)
        self.assertIsNone(best)

    def test_the_candidate_nearest_the_corner_wins(self):
        spans = [span('A-101', 900.0, 700.0), span('A-999', 1190.0, 890.0)]
        best, candidates = worker.extract_sheet_number(spans, 1200.0, 900.0)
        self.assertEqual('A-999', best)
        self.assertEqual(['A-999', 'A-101'], candidates)

    def test_the_pattern_is_a_parameter_not_a_constant(self):
        """圖號格式是每個案子自己的事，寫死等於只服務第一個案子。

        台灣圖說常用中文前綴（建／結／電／給排水），預設的
        ``^[A-Z]...`` 一個都接不到——這正是 pattern 必須可換的理由。
        """
        spans = [span('建-101', 1150.0, 880.0)]
        self.assertIsNone(
            worker.extract_sheet_number(spans, 1200.0, 900.0)[0])
        best, _ = worker.extract_sheet_number(
            spans, 1200.0, 900.0, pattern='^[一-鿿]{1,3}-?\\d{1,4}$')
        self.assertEqual('建-101', best)

    def test_the_region_is_a_parameter_too(self):
        spans = [span('A-101', 60.0, 30.0)]
        best, _ = worker.extract_sheet_number(
            spans, 1200.0, 900.0, region=(0.0, 0.0, 0.2, 0.2))
        self.assertEqual('A-101', best)

    def test_a_broken_pattern_does_not_crash_the_run(self):
        """regex 由使用者輸入，打錯不該讓整批比對死掉。"""
        best, candidates = worker.extract_sheet_number(
            [span('A-101', 1150.0, 880.0)], 1200.0, 900.0, pattern='[')
        self.assertIsNone(best)
        self.assertEqual([], candidates)

    def test_duplicates_are_collapsed_in_the_candidate_list(self):
        spans = [span('A-101', 1150.0, 880.0), span('A-101', 1100.0, 870.0)]
        _, candidates = worker.extract_sheet_number(spans, 1200.0, 900.0)
        self.assertEqual(['A-101'], candidates)


class PairPagesTests(unittest.TestCase):
    def page(self, number, sheet):
        return {'pageNumber': number, 'sheetNumber': sheet,
                'sheetNumberCandidates': [], 'kind': 'vector'}

    def test_pages_pair_on_sheet_number_not_page_order(self):
        """新版插了一張圖，後面全部的頁序就對不上了。"""
        a = [self.page(1, 'A-101'), self.page(2, 'A-102')]
        b = [self.page(1, 'A-000'), self.page(2, 'A-101'),
             self.page(3, 'A-102')]
        matched, only_a, only_b = worker.pair_pages(a, b)
        self.assertEqual([('A-101', 'A-101'), ('A-102', 'A-102')],
                         [(x['sheetNumber'], y['sheetNumber'])
                          for x, y in matched])
        self.assertEqual([], only_a)
        self.assertEqual(['A-000'], [p['sheetNumber'] for p in only_b])

    def test_a_removed_sheet_shows_up_in_only_a(self):
        matched, only_a, only_b = worker.pair_pages(
            [self.page(1, 'A-101')], [])
        self.assertEqual([], matched)
        self.assertEqual(['A-101'], [p['sheetNumber'] for p in only_a])

    def test_pages_without_a_sheet_number_are_never_silently_paired(self):
        """抽不到圖號就交給人決定，不要亂配。"""
        matched, only_a, only_b = worker.pair_pages(
            [self.page(1, None)], [self.page(1, None)])
        self.assertEqual([], matched)
        self.assertEqual(1, len(only_a))
        self.assertEqual(1, len(only_b))


class DetectPageKindTests(unittest.TestCase):
    def test_a_page_with_text_is_vector(self):
        self.assertEqual('vector', worker.detect_page_kind(
            [span('A', 0.0, 0.0)], []))

    def test_an_empty_page_is_reported_as_scanned(self):
        """**絕不允許**把「沒有向量文字層」默默走完流程回報成「沒有差異」。"""
        self.assertEqual('scanned', worker.detect_page_kind([], []))

    def test_geometry_without_text_is_flagged_too(self):
        self.assertEqual('no-text', worker.detect_page_kind(
            [], [line(0.0, 0.0, 1.0, 1.0)]))


class RevisionCloudFilterTests(unittest.TestCase):
    def cubic_path(self, start, end, path_type='s'):
        """一個獨立 stroked cubic path，模擬 PDF 裡的一瓣雲。"""
        return {
            'type': path_type,
            'fill': None,
            'items': [('c', start, start, end, end)],
        }

    def cloud(self, size=16.0):
        points = [
            (0.0, 0.0), (size / 2.0, -size / 4.0),
            (size, 0.0), (size * 1.25, size / 2.0),
            (size, size), (size / 2.0, size * 1.25),
            (0.0, size), (-size / 4.0, size / 2.0),
        ]
        return [self.cubic_path(points[i], points[(i + 1) % len(points)])
                for i in range(len(points))]

    def test_an_individual_circle_path_is_not_removed(self):
        circle = {
            'type': 's',
            'fill': None,
            'items': [
                ('c', (0.0, 0.0), (1.0, 0.0), (2.0, 1.0), (2.0, 2.0)),
                ('c', (2.0, 2.0), (2.0, 3.0), (1.0, 4.0), (0.0, 4.0)),
                ('c', (0.0, 4.0), (-1.0, 4.0), (-2.0, 3.0), (-2.0, 2.0)),
                ('c', (-2.0, 2.0), (-2.0, 1.0), (-1.0, 0.0), (0.0, 0.0)),
            ],
        }
        self.assertEqual([], worker.detect_revision_clouds([circle]))
        kept, stats = worker.filter_revision_clouds([circle])
        self.assertEqual([circle], kept)
        self.assertEqual(0, stats['pathCount'])

    def test_a_closed_multi_path_cloud_is_removed(self):
        drawings = self.cloud()
        clouds = worker.detect_revision_clouds(drawings)
        self.assertEqual(1, len(clouds))
        self.assertEqual(8, clouds[0]['pathCount'])
        filtered, stats = worker.filter_revision_clouds(drawings)
        self.assertEqual([], filtered)
        self.assertEqual(8, stats['pathCount'])

    def test_a_small_multi_path_symbol_is_not_removed(self):
        drawings = self.cloud(size=4.0)
        self.assertEqual([], worker.detect_revision_clouds(drawings))
        filtered, stats = worker.filter_revision_clouds(drawings)
        self.assertEqual(drawings, filtered)
        self.assertEqual(0, stats['pathCount'])

    def test_old_only_cloud_does_not_become_a_geometry_diff(self):
        def page(number, drawings):
            return {
                'pageNumber': number,
                'pageWidthPt': 1200.0,
                'pageHeightPt': 900.0,
                'kind': 'vector',
                'sheetNumber': 'A-101',
                'sheetNumberCandidates': ['A-101'],
                'spans': [span('T{}'.format(i), i * 30.0, 100.0)
                          for i in range(12)],
                'drawings': drawings,
            }

        old_drawings = [line(100.0, 200.0, 200.0, 200.0)]
        old_drawings.extend(self.cloud(size=16.0))
        new_drawings = [line(100.0, 200.0, 200.0, 200.0)]
        result = worker.compare_page(page(1, old_drawings),
                                     page(1, new_drawings), {})
        self.assertEqual(0, result['totalDiffs'])
        self.assertEqual(1, result['revisionCloudsA'])
        self.assertEqual(0, result['revisionCloudsB'])
        self.assertTrue(any('既有修訂雲' in warning
                            for warning in result['warnings']))

    def test_old_cloud_annotation_text_is_masked_too(self):
        def page(number, drawings, text_value):
            return {
                'pageNumber': number,
                'pageWidthPt': 1200.0,
                'pageHeightPt': 900.0,
                'kind': 'vector',
                'sheetNumber': 'A-101',
                'sheetNumberCandidates': ['A-101'],
                'spans': ([span('ANCHOR{}'.format(i), i * 30.0, 100.0)
                           for i in range(12)] +
                          ([span(text_value, 8.0, 8.0)]
                           if text_value is not None else [])),
                'drawings': drawings,
            }

        old_drawings = self.cloud(size=16.0)
        result = worker.compare_page(
            page(1, old_drawings, '8-9'),
            page(1, [], '6-7'), {})
        self.assertEqual(0, result['totalDiffs'])
        self.assertEqual(1, result['revisionCloudMaskedDiffs'])

    def test_real_identifier_change_inside_old_cloud_survives(self):
        """舊雲內的門窗／詳圖識別碼變更仍要被圈出。"""
        def page(number, drawings, text_value):
            return {
                'pageNumber': number,
                'pageWidthPt': 1200.0,
                'pageHeightPt': 900.0,
                'kind': 'vector',
                'sheetNumber': 'A-101',
                'sheetNumberCandidates': ['A-101'],
                'spans': ([span('ANCHOR{}'.format(i), i * 30.0, 100.0)
                           for i in range(12)] +
                          ([span(text_value, 8.0, 8.0)]
                           if text_value is not None else [])),
                'drawings': drawings,
            }

        old_drawings = self.cloud(size=16.0)
        result = worker.compare_page(
            page(1, old_drawings, 'C5'),
            page(1, [], 'C8'), {})
        self.assertGreater(result['totalDiffs'], 0)
        self.assertEqual(0, result['revisionCloudMaskedDiffs'])

    def test_new_detail_range_inside_old_cloud_survives(self):
        """新增的 1-5 詳圖索引不能被當成舊版次泡泡遮掉。"""
        def page(number, drawings, text_value):
            return {
                'pageNumber': number, 'pageWidthPt': 1200.0,
                'pageHeightPt': 900.0, 'kind': 'vector',
                'sheetNumber': 'A-101', 'sheetNumberCandidates': ['A-101'],
                'spans': ([span('ANCHOR{}'.format(i), i * 30.0, 100.0)
                           for i in range(12)] +
                          ([span(text_value, 8.0, 8.0)]
                           if text_value is not None else [])),
                'drawings': drawings,
            }

        old_drawings = self.cloud(size=16.0)
        result = worker.compare_page(
            page(1, old_drawings, None),
            page(1, [], '1-5'), {})
        self.assertGreater(result['totalDiffs'], 0)
        self.assertEqual(0, result['revisionCloudMaskedDiffs'])

    def test_real_geometry_inside_an_old_cloud_is_not_masked(self):
        def page(number, drawings):
            return {
                'pageNumber': number, 'pageWidthPt': 1200.0,
                'pageHeightPt': 900.0, 'kind': 'vector',
                'sheetNumber': 'A-101', 'sheetNumberCandidates': ['A-101'],
                'spans': [span('ANCHOR{}'.format(i), i * 30.0, 100.0)
                          for i in range(12)],
                'drawings': drawings,
            }

        old_drawings = self.cloud(size=40.0)
        old_drawings.append(line(8.0, 8.0, 20.0, 8.0))
        new_drawings = [line(8.0, 8.0, 28.0, 8.0)]
        result = worker.compare_page(page(1, old_drawings),
                                     page(1, new_drawings), {})
        self.assertGreater(result['totalDiffs'], 0)
        self.assertGreater(len(result['smartRegions']), 0)


class ComparePageTests(unittest.TestCase):
    """端對端（不含 fitz）：整頁位移 + 一處真變更，只該報那一處。"""

    def _page(self, number, dx=0.0, dy=0.0, value='CH=300'):
        spans = [span('T{}'.format(i), 100.0 + i * 40.0 + dx, 100.0 + dy)
                 for i in range(12)]
        spans.append(span(value, 600.0 + dx, 500.0 + dy))
        drawings = [line(x * 30.0 + dx, 200.0 + dy, x * 30.0 + dx, 400.0 + dy)
                    for x in range(30)]
        return {'pageNumber': number, 'pageWidthPt': 1200.0,
                'pageHeightPt': 900.0, 'kind': 'vector',
                'sheetNumber': 'A-101', 'sheetNumberCandidates': ['A-101'],
                'spans': spans, 'drawings': drawings}

    def test_a_shifted_but_unchanged_page_reports_nothing(self):
        result = worker.compare_page(self._page(1),
                                     self._page(1, dx=9.0, dy=4.0), {})
        self.assertEqual(0, result['totalDiffs'])
        self.assertEqual([], result['regions'])

    def test_one_edited_value_on_a_shifted_page_is_the_only_finding(self):
        result = worker.compare_page(
            self._page(1),
            self._page(1, dx=9.0, dy=4.0, value='CH=320'), {})
        self.assertEqual(1, len(result['regions']))
        self.assertEqual('text-change', result['regions'][0]['samples'][0]['kind'])
        self.assertEqual('CH=300', result['regions'][0]['samples'][0]['before'])
        self.assertEqual('CH=320', result['regions'][0]['samples'][0]['after'])

    def test_a_scanned_page_carries_a_warning(self):
        a = self._page(1)
        b = self._page(1)
        b['kind'] = 'scanned'
        result = worker.compare_page(a, b, {})
        self.assertTrue(result['warnings'])
        self.assertIn('向量', result['warnings'][0])

    def test_a_huge_offset_warns_about_a_wrong_pairing(self):
        result = worker.compare_page(self._page(1),
                                     self._page(1, dx=400.0), {})
        self.assertTrue(any('位移' in w for w in result['warnings']))


if __name__ == '__main__':
    unittest.main()


class ClusterDiffsTests(unittest.TestCase):
    """鄰近分群 + 最大空隙切開。

    取代了原本「固定格網 + 連通合併」的做法。那個做法是 all-or-nothing：
    格子連成一串就滾雪球，實測一份真實圖說產出一個涵蓋 **100% 頁面** 的區域
    ——準確，但圈成雲等於沒圈。這一組測試盯的就是「近的要併、遠的要分、
    大的要在空隙處切開、切不動要誠實承認」。
    """

    W = 1200.0
    H = 900.0

    def text(self, x, y):
        return {'kind': 'text-change', 'point': (x, y),
                'before': 'a', 'after': 'b'}

    def geom(self, x, y):
        return {'kind': 'geom-add', 'point': (x, y)}

    def test_nearby_diffs_become_one_region(self):
        """『很近的部分直接圈成一個區域』——這是這個演算法的存在理由。"""
        diffs = [self.text(100.0 + i * 3.0, 100.0) for i in range(4)]
        regions = worker.cluster_diffs(diffs, self.W, self.H)
        self.assertEqual(1, len(regions))
        self.assertEqual(4, regions[0]['textCount'])

    def test_far_apart_diffs_stay_separate(self):
        diffs = [self.text(50.0, 50.0), self.text(60.0, 50.0),
                 self.text(1100.0, 850.0), self.text(1110.0, 850.0)]
        self.assertEqual(2, len(worker.cluster_diffs(diffs, self.W, self.H)))

    def test_two_dense_clumps_with_a_gap_do_not_merge(self):
        """中間有空白就是兩堆，不該因為格子相鄰被併成一塊。"""
        diffs = [self.text(100.0 + i * 2.0, 400.0) for i in range(6)]
        diffs += [self.text(700.0 + i * 2.0, 400.0) for i in range(6)]
        regions = worker.cluster_diffs(diffs, self.W, self.H)
        self.assertEqual(2, len(regions))

    def test_a_sprawling_group_is_split_at_the_largest_gap(self):
        """兩團之間有大空隙、但被一串點連起來時，要切在空隙處。"""
        left = [self.text(50.0 + i * 20.0, 100.0) for i in range(10)]
        right = [self.text(900.0 + i * 20.0, 100.0) for i in range(10)]
        regions = worker.cluster_diffs(left + right, self.W, self.H,
                                       eps_fraction=1.0)
        self.assertEqual(2, len(regions))
        for region in regions:
            self.assertFalse(region['oversized'])

    def test_the_split_lands_in_the_empty_space_not_at_the_median(self):
        """切在中位數會把一團連續的東西硬切兩半，產生兩個都不自然的框。"""
        left = [self.text(50.0 + i * 10.0, 100.0) for i in range(3)]
        right = [self.text(1000.0 + i * 10.0, 100.0) for i in range(12)]
        regions = worker.cluster_diffs(left + right, self.W, self.H,
                                       eps_fraction=1.0)
        sizes = sorted(r['textCount'] for r in regions)
        self.assertEqual([3, 12], sizes)

    def test_a_uniformly_dense_area_is_reported_oversized_not_fake_split(self):
        """實測第 2 頁：新版多了 7204 條線且分佈均勻，找不到空隙。
        硬切成幾個小框會讓人以為只有那幾處要看——那比誠實承認更糟。"""
        diffs = [self.geom(50.0 + i * 4.0, 50.0 + (i % 200) * 4.0)
                 for i in range(400)]
        regions = worker.cluster_diffs(diffs, self.W, self.H,
                                       eps_fraction=1.0)
        self.assertEqual(1, len(regions))
        self.assertTrue(regions[0]['oversized'])

    def test_smart_mode_force_splits_a_dense_area_into_local_regions(self):
        diffs = [self.geom(50.0 + i * 4.0, 50.0 + (i % 200) * 4.0)
                 for i in range(400)]
        regions = worker.cluster_diffs(
            diffs, self.W, self.H, eps_fraction=1.0,
            max_span_fraction=0.10, force_split_dense=True)
        self.assertGreater(len(regions), 1)

    def test_oversized_diagnostic_does_not_swallow_local_text_region(self):
        regions = [
            {'gridLabel': 'A1:I6', 'bbox': (0.0, 0.0, 1200.0, 900.0),
             'score': 1000.0, 'textCount': 0, 'geomCount': 1000,
             'pageFraction': 1.0, 'oversized': True, 'samples': []},
            {'gridLabel': 'F4', 'bbox': (500.0, 400.0, 520.0, 420.0),
             'score': 3.0, 'textCount': 1, 'geomCount': 0,
             'pageFraction': 0.001, 'oversized': False,
             'samples': [{'kind': 'text-change',
                          'before': '184', 'after': '185'}]},
        ]
        merged = worker.merge_overlapping_regions(regions, self.W, self.H)
        self.assertEqual(2, len(merged))

    def test_region_bbox_uses_the_changed_primitive_not_its_empty_center(self):
        diffs = [{'kind': 'geom-add', 'point': (500.0, 450.0),
                  'bbox': (100.0, 100.0, 900.0, 800.0)} for _ in range(3)]
        regions = worker.cluster_diffs(diffs, self.W, self.H)
        self.assertEqual((100.0, 100.0, 900.0, 800.0), regions[0]['bbox'])

    def test_overlapping_add_delete_regions_merge_into_one_cloud(self):
        regions = [
            {'gridLabel': 'F4', 'bbox': (100.0, 100.0, 200.0, 180.0),
             'score': 4.5, 'textCount': 0, 'geomCount': 3,
             'pageFraction': 0.01, 'oversized': False, 'samples': []},
            {'gridLabel': 'F4', 'bbox': (110.0, 120.0, 210.0, 200.0),
             'score': 4.5, 'textCount': 0, 'geomCount': 3,
             'pageFraction': 0.01, 'oversized': False, 'samples': []},
        ]
        merged = worker.merge_overlapping_regions(
            regions, self.W, self.H, min_overlap_fraction=0.45)
        self.assertEqual(1, len(merged))
        self.assertEqual((100.0, 100.0, 210.0, 200.0), merged[0]['bbox'])

    def test_merged_region_keeps_text_samples_ahead_of_geometry(self):
        regions = [
            {'gridLabel': 'F4', 'bbox': (100.0, 100.0, 200.0, 180.0),
             'score': 3.0, 'textCount': 0, 'geomCount': 2,
             'pageFraction': 0.01, 'oversized': False,
             'samples': [{'kind': 'geom-add'}]},
            {'gridLabel': 'F4', 'bbox': (110.0, 120.0, 210.0, 200.0),
             'score': 3.0, 'textCount': 1, 'geomCount': 0,
             'pageFraction': 0.01, 'oversized': False,
             'samples': [{'kind': 'text-add', 'after': '設備基座'}]},
        ]
        merged = worker.merge_overlapping_regions(regions, self.W, self.H)
        self.assertEqual('text-add', merged[0]['samples'][0]['kind'])

    def test_small_text_box_inside_large_geometry_box_does_not_expand(self):
        regions = [
            {'gridLabel': 'F4', 'bbox': (100.0, 100.0, 500.0, 500.0),
             'score': 30.0, 'textCount': 0, 'geomCount': 20,
             'pageFraction': 0.15, 'oversized': False, 'samples': []},
            {'gridLabel': 'F4', 'bbox': (200.0, 200.0, 220.0, 220.0),
             'score': 3.0, 'textCount': 1, 'geomCount': 0,
             'pageFraction': 0.001, 'oversized': False,
             'samples': [{'kind': 'text-change'}]},
        ]
        merged = worker.merge_overlapping_regions(
            regions, self.W, self.H, min_overlap_fraction=0.45)
        self.assertEqual(2, len(merged))

    def test_a_region_below_the_threshold_is_dropped(self):
        self.assertEqual([], worker.cluster_diffs(
            [self.geom(100.0, 100.0)], self.W, self.H, threshold=3.0))

    def test_regions_are_ranked_by_score(self):
        diffs = [self.text(100.0, 100.0)]
        diffs += [self.text(900.0 + i * 2.0, 800.0) for i in range(5)]
        regions = worker.cluster_diffs(diffs, self.W, self.H)
        self.assertGreater(regions[0]['score'], regions[1]['score'])

    def test_the_grid_label_still_describes_where_it_is(self):
        """格號是使用者講得出口的定位語言，換演算法不能把它弄丟。"""
        regions = worker.cluster_diffs(
            [self.text(50.0, 50.0), self.text(56.0, 50.0)], self.W, self.H)
        self.assertEqual('A1', regions[0]['gridLabel'])

    def test_the_bbox_hugs_the_diffs_not_the_grid(self):
        """框貼著差異點，不再被格網撐大——這正是雲變小的原因。"""
        regions = worker.cluster_diffs(
            [self.text(100.0, 200.0), self.text(112.0, 206.0)],
            self.W, self.H)
        self.assertEqual((100.0, 200.0, 112.0, 206.0), regions[0]['bbox'])

    def test_finer_text_tolerance_keeps_stacked_notes_separate(self):
        """上下相鄰的文字註記不可被寬鬆容差串成一個過高的框。"""
        diffs = [self.text(590.0, 360.0), self.text(590.0, 363.0),
                 self.text(588.0, 401.0), self.text(582.0, 412.0)]
        regions = worker.cluster_diffs(
            diffs, self.W, self.H, eps_fraction=0.015)
        self.assertEqual(2, len(regions))
        self.assertEqual((590.0, 360.0, 590.0, 363.0),
                         regions[0]['bbox'])

    def test_an_empty_input_yields_nothing(self):
        self.assertEqual([], worker.cluster_diffs([], self.W, self.H))

    def test_a_degenerate_page_does_not_divide_by_zero(self):
        self.assertEqual([], worker.cluster_diffs(
            [self.text(1.0, 1.0)], 0.0, self.H))


class DropDiffsInRegionTests(unittest.TestCase):
    def diff(self, x, y):
        return {'kind': 'text-change', 'point': (x, y),
                'before': 'B版', 'after': 'C(working)'}

    def test_title_block_diffs_are_dropped(self):
        """實測 14 頁全部出現 `B版` -> `C(working)`：那是『這份圖說改版了』，
        不是『這個位置的圖面改了』。"""
        kept = worker.drop_diffs_in_region(
            [self.diff(1150.0, 880.0)], 1200.0, 900.0, (0.7, 0.75, 1.0, 1.0))
        self.assertEqual([], kept)

    def test_diffs_outside_the_region_survive(self):
        kept = worker.drop_diffs_in_region(
            [self.diff(100.0, 100.0)], 1200.0, 900.0, (0.7, 0.75, 1.0, 1.0))
        self.assertEqual(1, len(kept))

    def test_no_region_means_no_filtering(self):
        kept = worker.drop_diffs_in_region(
            [self.diff(1150.0, 880.0)], 1200.0, 900.0, None)
        self.assertEqual(1, len(kept))

    def test_revision_filter_drops_only_revision_stamp_text(self):
        kept = worker.drop_title_block_revision_diffs(
            [self.diff(1150.0, 880.0)], 1200.0, 900.0,
            (0.7, 0.75, 1.0, 1.0))
        self.assertEqual([], kept)

    def test_revision_filter_keeps_door_window_number_in_same_corner(self):
        number_diff = {
            'kind': 'text-change', 'point': (950.0, 800.0),
            'before': '184', 'after': '185'}
        kept = worker.drop_title_block_revision_diffs(
            [number_diff], 1200.0, 900.0, (0.7, 0.75, 1.0, 1.0))
        self.assertEqual([number_diff], kept)

    def test_revision_filter_keeps_geometry_in_same_corner(self):
        geom_diff = {'kind': 'geom-add', 'point': (950.0, 800.0)}
        kept = worker.drop_title_block_revision_diffs(
            [geom_diff], 1200.0, 900.0, (0.7, 0.75, 1.0, 1.0))
        self.assertEqual([geom_diff], kept)


class RegionIdentityTests(unittest.TestCase):
    """同一頁**可以**出現 gridLabel 與 score 都相同的多個區域。

    這條測試是為了鎖住一個曾經造成 Revit 行程終止的假設。UI 一度拿
    ``(gridLabel, score)`` 當快取 key，實測使用者的圖說第 1 頁有兩個區域
    都叫 ``J4`` 且分數都是 9.0、第 2 頁有 6 組撞號，結果同一張 WPF 卡片被
    掛兩次 →「指定的 Visual 已經是另一個 Visual 的子項目」→ Revit 終止。
    更糟的是它同時讓兩個區域共用一個勾選框，**靜默送出錯誤的雲集合**。

    格號是「粗略定位」不是「唯一識別」——同一格裡本來就可能有兩堆分開的
    差異。要唯一識別一個區域，只能用物件識別或 bbox。
    """

    W = 1200.0
    H = 900.0

    def text(self, x, y):
        return {'kind': 'text-change', 'point': (x, y),
                'before': 'a', 'after': 'b'}

    def test_two_regions_can_share_a_grid_label_and_score(self):
        cell_w = self.W / worker.DEFAULT_GRID_COLS
        cell_h = self.H / worker.DEFAULT_GRID_ROWS
        # 同一格內的兩堆，中間隔開到不會被鄰近分群併起來
        diffs = [self.text(cell_w * 0.10, cell_h * 0.10),
                 self.text(cell_w * 0.12, cell_h * 0.10),
                 self.text(cell_w * 0.88, cell_h * 0.90),
                 self.text(cell_w * 0.90, cell_h * 0.90)]
        regions = worker.cluster_diffs(diffs, self.W, self.H,
                                       eps_fraction=0.004)
        self.assertEqual(2, len(regions))
        self.assertEqual(regions[0]['gridLabel'], regions[1]['gridLabel'])
        self.assertEqual(regions[0]['score'], regions[1]['score'])

    def test_their_bounding_boxes_still_differ(self):
        """bbox 才是唯一的——UI 若要一個可序列化的 key，用它。"""
        cell_w = self.W / worker.DEFAULT_GRID_COLS
        cell_h = self.H / worker.DEFAULT_GRID_ROWS
        diffs = [self.text(cell_w * 0.10, cell_h * 0.10),
                 self.text(cell_w * 0.12, cell_h * 0.10),
                 self.text(cell_w * 0.88, cell_h * 0.90),
                 self.text(cell_w * 0.90, cell_h * 0.90)]
        regions = worker.cluster_diffs(diffs, self.W, self.H,
                                       eps_fraction=0.004)
        self.assertNotEqual(regions[0]['bbox'], regions[1]['bbox'])


class SmartGeometryTests(unittest.TestCase):
    W = 1200.0
    H = 900.0

    def geom(self, x, y, bbox=None):
        diff = {'kind': 'geom-add', 'point': (x, y)}
        if bbox is not None:
            diff['bbox'] = bbox
        return diff

    def test_hotspots_keep_dense_block_and_drop_sparse_cell(self):
        diffs = [self.geom(250.0 + i, 250.0 + i)
                 for i in range(10)]
        diffs.extend(self.geom(850.0 + i, 750.0) for i in range(3))
        regions = worker.cluster_geometry_hotspots(
            diffs, self.W, self.H, ratio=0.45, min_diffs=8)
        self.assertEqual(1, len(regions))
        self.assertEqual(10, regions[0]['geomCount'])
        self.assertEqual('geometryHotspot', regions[0]['diagnostic'])

    def test_hotspot_bbox_uses_real_geometry_not_whole_grid_cell(self):
        diffs = [self.geom(250.0 + i * 0.5, 250.0 + i * 0.5,
                           (248.0 + i * 0.5, 249.0 + i * 0.5,
                            264.0 + i * 0.5, 266.0 + i * 0.5))
                 for i in range(8)]
        regions = worker.cluster_geometry_hotspots(
            diffs, self.W, self.H, ratio=0.45, min_diffs=8)
        self.assertEqual((248.0, 249.0, 267.5, 269.5),
                         regions[0]['bbox'])

    def test_oversized_long_primitive_is_clipped_to_hot_cells(self):
        diffs = [self.geom(250.0 + i * 0.5, 250.0 + i * 0.5,
                           (0.0, 0.0, 1100.0, 800.0))
                 for i in range(8)]
        regions = worker.cluster_geometry_hotspots(
            diffs, self.W, self.H, ratio=0.45, min_diffs=8,
            max_fraction=0.15)
        self.assertEqual(1, len(regions))
        self.assertTrue(regions[0].get('hotspotGridClipped'))
        self.assertFalse(regions[0]['oversized'])

    def test_nearby_text_is_attached_to_the_same_hotspot(self):
        hotspot = {
            'gridLabel': 'F4', 'bbox': (100.0, 100.0, 200.0, 200.0),
            'score': 12.0, 'textCount': 0, 'geomCount': 8,
            'pageFraction': 0.01, 'oversized': False,
            'samples': [{'kind': 'geom-add'}],
            'diagnostic': 'geometryHotspot',
        }
        text_region = {
            'gridLabel': 'F4', 'bbox': (205.0, 120.0, 215.0, 135.0),
            'score': 3.0, 'textCount': 1, 'geomCount': 0,
            'pageFraction': 0.001, 'oversized': False,
            'samples': [{'kind': 'text-add', 'after': 'B109'}],
        }
        merged = worker.attach_text_regions_to_hotspots(
            [hotspot], [text_region], self.W, self.H)
        self.assertEqual(1, len(merged))
        self.assertEqual(1, merged[0]['textCount'])
        self.assertEqual((100.0, 100.0, 215.0, 200.0), merged[0]['bbox'])
        self.assertEqual('text-add', merged[0]['samples'][0]['kind'])

    def test_tiny_thin_residual_is_dropped_but_long_line_survives(self):
        regions = [
            {'bbox': (10.0, 10.0, 20.0, 20.0), 'geomCount': 8},
            {'bbox': (30.0, 30.0, 120.0, 32.0), 'geomCount': 12},
            {'bbox': (40.0, 40.0, 60.0, 60.0), 'geomCount': 8},
        ]
        kept = worker.filter_tiny_geometry_regions(regions)
        self.assertEqual(1, len(kept))
        self.assertEqual((40.0, 40.0, 60.0, 60.0), kept[0]['bbox'])

    def test_elevation_regions_keep_a_broad_dense_building_area(self):
        diffs = [self.geom(300.0 + i, 300.0 + i)
                 for i in range(55)]
        diffs.extend(self.geom(400.0 + i, 300.0 + i)
                     for i in range(55))
        diffs.extend(self.geom(800.0 + i, 600.0)
                     for i in range(6))
        page = {'sheetName': '立面圖(一)', 'sheetNumber': 'ARD-D03001'}
        self.assertTrue(worker._is_elevation_sheet(page))
        regions = worker.cluster_elevation_geometry_regions(
            diffs, self.W, self.H, threshold=50)
        self.assertEqual(1, len(regions))
        self.assertEqual('elevationWideChange', regions[0]['diagnostic'])
        self.assertGreater(regions[0]['pageFraction'], 0.01)

    def test_non_elevation_sheet_does_not_use_elevation_classifier(self):
        self.assertFalse(worker._is_elevation_sheet(
            {'sheetName': '剖面圖', 'sheetNumber': 'ARD-D04001'}))


class SmartTextSignalTests(unittest.TestCase):
    def span(self, text, x, y, size=6.0):
        return {'text': text, 'bbox': (x, y, x + 8.0, y + 8.0),
                'size': size}

    def test_repeated_numbers_are_not_high_signal_additions(self):
        self.assertFalse(worker._smart_text_is_high_signal(
            '181', 8.0, {'181': 2}))
        self.assertTrue(worker._smart_text_is_high_signal(
            '181', 8.0, {'181': 1}))

    def test_note_prefix_is_layout_noise(self):
        self.assertEqual('layout', worker._smart_text_role(
            '註：詳細高程詳機電設備圖'))

    def test_high_churn_keeps_content_change_not_placeholder_reflow(self):
        diffs = [
            {'kind': 'text-change', 'point': (10.0, 10.0),
             'before': '-', 'after': 'B1', 'similarity': 0.0},
            {'kind': 'text-change', 'point': (20.0, 20.0),
             'before': 'D3', 'after': 'D4a', 'similarity': 0.5},
            {'kind': 'text-add', 'point': (30.0, 30.0),
             'before': None, 'after': 'D5'},
        ]
        spans = [self.span('D3', 10.0, 10.0),
                 self.span('D4a', 20.0, 20.0),
                 self.span('D5', 30.0, 30.0)]
        kept = worker._smart_text_candidates(
            diffs, spans, spans, high_churn=True)
        self.assertEqual(1, len(kept))
        self.assertEqual('D3', kept[0]['before'])
        self.assertEqual('D4a', kept[0]['after'])

    def test_smart_title_filter_drops_sheet_title_but_keeps_number(self):
        cjk = {'kind': 'text-add', 'point': (1000.0, 800.0),
               'before': None, 'after': '統流開發股份有限公司'}
        sheet = {'kind': 'text-delete', 'point': (1050.0, 810.0),
                 'before': '0721B-ARD-D06001', 'after': None}
        number = {'kind': 'text-change', 'point': (950.0, 800.0),
                  'before': '184', 'after': '185'}
        kept = worker.drop_smart_title_block_layout_diffs(
            [cjk, sheet, number], 1200.0, 900.0,
            (0.70, 0.75, 1.0, 1.0), ['ARD-D06001'])
        self.assertEqual([number], kept)
