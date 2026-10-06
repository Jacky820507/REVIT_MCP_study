# -*- coding: utf-8 -*-
"""cad_align_logic / cad_grid_label_worker 的離線測試。

座標取自實際案例：Revit C1（垂直，X=86541.31）與 CI（水平，Y=132062.29），
視圖「物流中心 一層排水平面圖(分圖)」、CAD「鮮食中心 一層平面索引圖.dwg」。
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'MCP_Tools.extension', 'lib')
sys.path.insert(0, LIB)

import cad_align_logic as logic  # noqa: E402
import cad_grid_label_worker as worker  # noqa: E402

L = logic.make_line

C1_X = 86541.31
CI_Y = 132062.29


def revit_grid(xs, ys, x_names, y_names):
    grids = []
    for x, name in zip(xs, x_names):
        grids.append(L((x, 40000), (x, 160000), name))
    for y, name in zip(ys, y_names):
        grids.append(L((60000, y), (200000, y), name))
    return grids


def cad_grid(xs, ys, dx, dy, split=False):
    """CAD 軸線 = Revit 軸線平移 (-dx, -dy)。split=True 時每條拆兩段。"""
    lines = []
    for x in xs:
        if split:
            lines.append(L((x - dx, 40000 - dy), (x - dx, 90000 - dy)))
            lines.append(L((x - dx, 90000 - dy), (x - dx, 160000 - dy)))
        else:
            lines.append(L((x - dx, 40000 - dy), (x - dx, 160000 - dy)))
    for y in ys:
        lines.append(L((60000 - dx, y - dy), (200000 - dx, y - dy)))
    # 軸號泡泡的短線與雜訊，不該被當軸線。
    lines.append(L((0, 0), (300, 0)))
    return lines


XS = [C1_X, C1_X + 8400, C1_X + 16800, C1_X + 27000]
YS = [CI_Y - 17000, CI_Y - 8500, CI_Y]
XN = ['C1', 'C2', 'C3', 'C4']
YN = ['CG', 'CH', 'CI']


class FloorCodeTests(unittest.TestCase):
    def test_chinese_and_ascii(self):
        cases = {
            u'物流中心 一層排水平面圖(分圖)': '1F',
            u'鮮食中心 一層平面索引圖': '1F',
            u'鮮食中心 地下一層平面索引圖': 'B1',
            u'鮮食中心 十二層平面': '12F',
            u'鮮食中心 二十層平面': '20F',
            u'3F 平面圖': '3F',
            u'B2F 停車': 'B2',
            u'FL5 plan': '5F',
            u'屋頂層平面': 'RF',
            u'RF 平面': 'RF',
            u'屋突一層': 'R1',
            u'5樓平面': '5F',
        }
        for name, code in cases.items():
            self.assertEqual(logic.floor_code(name), code, name)

    def test_building_prefix_is_not_basement(self):
        # 模型實際的樓層名稱 B-1F 是「B 棟 1F」，不是地下一層。
        self.assertEqual(logic.floor_code(u'B-1F'), None)
        self.assertNotEqual(logic.floor_code(u'B-1F 平面'), 'B1')

    def test_eleven_not_one(self):
        self.assertEqual(logic.floor_code(u'11F 辦公'), '11F')
        self.assertEqual(logic.floor_code(u'十一層'), '11F')

    def test_no_code(self):
        self.assertIsNone(logic.floor_code(u'東向立面'))


class PairingTests(unittest.TestCase):
    def test_pairs_by_floor_ignoring_building(self):
        views = [(0, u'物流中心 一層排水平面圖(分圖)'), (1, u'物流中心 二層平面'),
                 (2, u'物流中心 七層平面')]
        files = [('a', u'鮮食中心 一層平面索引圖.dwg'),
                 ('b', u'鮮食中心 二層平面索引圖.dwg')]
        result = logic.pair_views_to_files(views, files)
        self.assertEqual(result[0]['file'], 'a')
        self.assertEqual(result[1]['file'], 'b')
        self.assertIsNone(result[2]['file'])
        self.assertIn('7F', result[2]['reason'])

    def test_two_files_same_floor_not_guessed(self):
        result = logic.pair_views_to_files(
            [(0, u'一層平面')],
            [('a', u'A 一層.dwg'), ('b', u'B 一層.dwg')])
        self.assertIsNone(result[0]['file'])
        self.assertIn(u'手動', result[0]['reason'])


class LayerTests(unittest.TestCase):
    def test_exact_and_xref(self):
        self.assertTrue(logic.layer_matches('s-grid', 'S-GRID'))
        self.assertTrue(logic.layer_matches(u'底圖$0$S-GRID', 'S-GRID'))
        self.assertTrue(logic.layer_matches(u'底圖|S-GRID', 'S-GRID'))

    def test_label_layer_is_not_grid_layer(self):
        self.assertFalse(logic.layer_matches('S-GRID-IDEN', 'S-GRID'))
        self.assertFalse(worker.layer_matches('S-GRID-IDEN', 'S-GRID'))


class SpacingAlignmentTests(unittest.TestCase):
    def test_irregular_spacing_unique(self):
        dx, dy = 123456.7, -98765.4
        plan = logic.plan_alignment(cad_grid(XS, YS, dx, dy, split=True),
                                    revit_grid(XS, YS, XN, YN))
        self.assertEqual(plan['status'], logic.STATUS_READY, plan)
        self.assertAlmostEqual(plan['translation'][0], dx, places=3)
        self.assertAlmostEqual(plan['translation'][1], dy, places=3)

    def test_equidistant_is_ambiguous_not_guessed(self):
        xs = [C1_X + 8400 * i for i in range(5)]
        ys = [CI_Y - 8400 * i for i in range(4)]
        # CAD 只畫了中間三條：往左或往右一跨都一樣好。
        plan = logic.plan_alignment(
            cad_grid(xs[1:4], ys[1:3], 5000, 7000),
            revit_grid(xs, ys, ['C%d' % i for i in range(5)],
                       ['Y%d' % i for i in range(4)]))
        self.assertEqual(plan['status'], logic.STATUS_AMBIGUOUS)
        self.assertIn(u'軸號', plan['reason'])

    def test_rotated_cad_rejected(self):
        import math
        cad = []
        for line in cad_grid(XS, YS, 0, 0):
            rot = math.radians(2.0)

            def r(p):
                return (p[0] * math.cos(rot) - p[1] * math.sin(rot),
                        p[0] * math.sin(rot) + p[1] * math.cos(rot))
            cad.append(L(r(line['start']), r(line['end'])))
        plan = logic.plan_alignment(cad, revit_grid(XS, YS, XN, YN))
        self.assertEqual(plan['status'], logic.STATUS_FAILED)
        self.assertIn(u'旋轉', plan['reason'])

    def test_no_cad_lines(self):
        plan = logic.plan_alignment([], revit_grid(XS, YS, XN, YN))
        self.assertEqual(plan['status'], logic.STATUS_FAILED)


class LabelAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.xs = [C1_X + 8400 * i for i in range(5)]
        self.ys = [CI_Y - 8400 * i for i in range(4)]
        self.xn = ['C%d' % (i + 1) for i in range(5)]
        self.yn = ['CI', 'CH', 'CG', 'CF']
        self.dx, self.dy = 5000.0, 7000.0

    def labels_for(self, idx_x, idx_y):
        """CAD 座標（平移前）的軸號，放在軸線端點外 800mm。"""
        labels = []
        for i in idx_x:
            labels.append({'text': self.xn[i],
                           'x': self.xs[i] - self.dx,
                           'y': 160000 - self.dy + 800})
        for i in idx_y:
            labels.append({'text': self.yn[i], 'x': 60000 - self.dx - 800,
                           'y': self.ys[i] - self.dy})
        return labels

    def test_labels_resolve_equidistant_ambiguity(self):
        cad = cad_grid(self.xs[1:4], self.ys[1:3], self.dx, self.dy)
        grids = revit_grid(self.xs, self.ys, self.xn, self.yn)
        plan = logic.plan_alignment(cad, grids, self.labels_for([1, 2, 3],
                                                                [1, 2]))
        self.assertEqual(plan['status'], logic.STATUS_READY, plan)
        self.assertAlmostEqual(plan['translation'][0], self.dx, places=3)
        self.assertAlmostEqual(plan['translation'][1], self.dy, places=3)
        self.assertEqual([d['method'] for d in plan['families']],
                         [u'軸號', u'軸號'])

    def test_c1_ci_pair_like_the_real_case(self):
        cad = cad_grid(self.xs, self.ys, self.dx, self.dy)
        grids = revit_grid(self.xs, self.ys, self.xn, self.yn)
        labels = [{'text': u'C1', 'x': C1_X - self.dx,
                   'y': 160000 - self.dy + 600},
                  {'text': u'ＣＩ', 'x': 60000 - self.dx - 600,
                   'y': CI_Y - self.dy}]
        plan = logic.plan_alignment(cad, grids, labels)
        self.assertEqual(plan['status'], logic.STATUS_READY, plan)
        self.assertAlmostEqual(plan['translation'][0], self.dx, places=3)
        self.assertAlmostEqual(plan['translation'][1], self.dy, places=3)

    def test_wrong_label_outvoted_and_reported(self):
        cad = cad_grid(self.xs, self.ys, self.dx, self.dy)
        grids = revit_grid(self.xs, self.ys, self.xn, self.yn)
        labels = self.labels_for([0, 1, 2], [0, 1])
        labels[0]['text'] = 'C5'   # 標錯一個
        plan = logic.plan_alignment(cad, grids, labels)
        self.assertEqual(plan['status'], logic.STATUS_READY)
        self.assertAlmostEqual(plan['translation'][0], self.dx, places=3)
        self.assertIn('C5', plan['families'][0]['detail'] +
                      plan['families'][1]['detail'])

    def test_label_scale_detects_metres(self):
        cad = cad_grid(self.xs, self.ys, 0, 0)
        labels = [{'text': 'C1', 'x': C1_X / 1000.0,
                   'y': (160000 + 800) / 1000.0}]
        scale, hits = logic.choose_label_scale(labels, cad)
        self.assertEqual((scale, hits), (1000.0, 1))

    def test_far_label_ignored(self):
        cad = cad_grid(self.xs, self.ys, 0, 0)
        families = logic.group_families(cad)[:2]
        far = [{'text': 'C1', 'x': 0, 'y': 0}]
        self.assertEqual(logic.assign_labels(far, families), [])


class TranslationTests(unittest.TestCase):
    def test_solve_axis_aligned(self):
        # 垂直軸（角度 90）法向是 (-1, 0)；水平軸（0）法向是 (0, 1)。
        t = logic.solve_translation(90.0, -10.0, 0.0, 20.0)
        self.assertAlmostEqual(t[0], 10.0)
        self.assertAlmostEqual(t[1], 20.0)

    def test_parallel_none(self):
        self.assertIsNone(logic.solve_translation(0.0, 1.0, 0.0, 2.0))


class ReportTests(unittest.TestCase):
    def test_csv_quotes(self):
        text = logic.csv_text([[u'a,b', u'"q"', u'中文']])
        self.assertEqual(text, u'"a,b","""q""",中文\r\n')

    def test_report_rows(self):
        rows = logic.report_rows([{
            'view': 'V', 'file': 'F.dwg', 'code': '1F', 'status': u'已對齊',
            'id': 5, 'plan': {'status': logic.STATUS_READY,
                              'translation': (1.0, 2.0),
                              'families': [{'method': u'軸號', 'detail': 'x'}]}}])
        self.assertEqual(rows[1][5:8], [u'1.00', u'2.00', u'5'])


class LayerSummaryTests(unittest.TestCase):
    def test_empty_geometry_said_plainly(self):
        self.assertIn(u'讀不到', logic.layer_summary_text({}, 'S-GRID'))

    def test_similar_layer_listed_first(self):
        text = logic.layer_summary_text(
            {'A-WALL': (500, 0), 'GRID-LINE': (12, 3), 'TEXT': (0, 40)},
            'S-GRID')
        self.assertTrue(text.index('GRID-LINE') < text.index('A-WALL'), text)
        self.assertIn(u'直線12/其他3', text)

    def test_truncates_long_lists(self):
        summary = dict(('L%02d' % i, (i, 0)) for i in range(30))
        self.assertIn(u'等 30 層', logic.layer_summary_text(summary, 'X',
                                                            limit=5))


class WorkerTests(unittest.TestCase):
    def test_find_oda_picks_latest(self):
        import tempfile
        base = tempfile.mkdtemp()
        for version in ('ODAFileConverter 25.12.0', 'ODAFileConverter 27.9.0'):
            folder = os.path.join(base, version)
            os.makedirs(folder)
            open(os.path.join(folder, 'ODAFileConverter.exe'), 'w').close()
        found = worker.find_oda(
            (os.path.join(base, 'ODAFileConverter*', 'ODAFileConverter.exe'),))
        self.assertIn('27.9.0', found)
        self.assertIsNone(worker.find_oda((os.path.join(base, 'nope*'),)))

    def test_collect_labels_from_dxf(self):
        try:
            import ezdxf
        except ImportError:
            self.skipTest('ezdxf not installed')
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_text('C1', dxfattribs={'layer': 'S-GRID-IDEN',
                                       'insert': (10, 20)})
        msp.add_text('X', dxfattribs={'layer': 'OTHER', 'insert': (0, 0)})
        block = doc.blocks.new('BUBBLE')
        block.add_text('CI', dxfattribs={'layer': 'S-GRID-IDEN',
                                         'insert': (0, 0)})
        msp.add_blockref('BUBBLE', (100, 200))
        labels = worker.collect_labels(msp, 'S-GRID-IDEN')
        found = sorted((l['text'], round(l['x']), round(l['y']))
                       for l in labels)
        self.assertEqual(found, [('C1', 10, 20), ('CI', 100, 200)])


if __name__ == '__main__':
    unittest.main()
