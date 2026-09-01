# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""``pdf_diff_runner`` 的純函式測試。

不測 subprocess 本身（那要真的有 Python 與 pymupdf，屬於端對端範圍），
只測「找哪一支直譯器、用什麼順序、失敗時講不講得清楚」——issue #93 的
教訓正是這一段：多版本環境下錯誤訊息不夠清楚，使用者無從判斷是沒裝、
還是裝在別支。所以診斷訊息的內容本身值得測。
"""

import json
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import pdf_diff_runner as runner


class WorkerPathTests(unittest.TestCase):
    def test_the_worker_sits_next_to_the_runner(self):
        """兩個檔案都在 lib/，跟著 extension 的 junction 走，不必另外部署。"""
        self.assertTrue(os.path.exists(runner.worker_path()),
                        runner.worker_path())

    def test_it_points_at_the_worker_module(self):
        self.assertTrue(runner.worker_path().endswith('pdf_diff_worker.py'))


class PythonCandidateTests(unittest.TestCase):
    def test_an_explicit_override_comes_first(self):
        """使用者已經明講了用哪一支，不要自作聰明先試別的。"""
        candidates = runner.python_candidates(
            {runner.PYTHON_ENV_VAR: r'C:\Py\python.exe'})
        self.assertEqual([r'C:\Py\python.exe'], candidates[0])

    def test_the_windows_launcher_is_tried_before_bare_python(self):
        """PATH 上的 ``python`` 常被 Microsoft Store 的殼或 conda shim 佔住。"""
        candidates = runner.python_candidates({})
        self.assertEqual(['py', '-3'], candidates[0])
        self.assertLess(candidates.index(['py', '-3']),
                        candidates.index(['python']))

    def test_no_override_means_no_override_entry(self):
        candidates = runner.python_candidates({})
        self.assertNotIn(1, [len(c) for c in candidates[:1]])

    def test_common_install_paths_are_a_last_resort(self):
        candidates = runner.python_candidates({'LOCALAPPDATA': r'C:\Users\x'})
        joined = [' '.join(c) for c in candidates]
        self.assertLess(joined.index('python'),
                        min(i for i, c in enumerate(joined)
                            if 'Programs' in c))

    def test_it_works_without_localappdata(self):
        """非 Windows 或環境被清乾淨時不該爆掉。"""
        self.assertTrue(runner.python_candidates({}))


class BuildOptionsTests(unittest.TestCase):
    def test_the_three_required_keys_are_always_present(self):
        options = runner.build_options('a.pdf', 'b.pdf', 'out.json')
        self.assertEqual('a.pdf', options['pdfA'])
        self.assertEqual('b.pdf', options['pdfB'])
        self.assertEqual('out.json', options['outputPath'])

    def test_overrides_are_passed_through(self):
        options = runner.build_options('a.pdf', 'b.pdf', 'out.json',
                                       {'threshold': 6.0})
        self.assertEqual(6.0, options['threshold'])

    def test_none_overrides_are_dropped_so_the_worker_keeps_its_default(self):
        """把預設值複製到 runner 這邊，日後改一邊忘記改另一邊，
        就會出現「調了參數沒反應」。"""
        options = runner.build_options('a.pdf', 'b.pdf', 'out.json',
                                       {'threshold': None})
        self.assertNotIn('threshold', options)

    def test_the_options_survive_a_json_round_trip(self):
        options = runner.build_options('a.pdf', 'b.pdf', 'out.json',
                                       {'gridCols': 12})
        self.assertEqual(options, json.loads(json.dumps(options)))


class InterpretFailureTests(unittest.TestCase):
    def test_the_workers_own_error_is_preferred(self):
        """worker 知道是哪一支 Python、缺什麼套件，比 stderr 有價值得多。"""
        message = runner.interpret_failure(
            1, json.dumps({'error': '無法匯入 PyMuPDF',
                           'python': r'C:\Py311\python.exe'}), '', [])
        self.assertIn('無法匯入 PyMuPDF', message)
        self.assertIn(r'C:\Py311\python.exe', message)

    def test_it_falls_back_to_stderr_when_stdout_is_not_json(self):
        message = runner.interpret_failure(1, 'not json', 'boom', [])
        self.assertIn('boom', message)

    def test_it_says_something_even_with_no_output_at_all(self):
        """沒有輸出是最糟的情況，也是最需要講清楚的情況。"""
        message = runner.interpret_failure(-1, '', '', [])
        self.assertIn('沒有輸出', message)

    def test_the_interpreters_tried_are_listed(self):
        message = runner.interpret_failure(1, '', 'x', [['py', '-3'],
                                                        ['python']])
        self.assertIn('py -3', message)

    def test_the_install_command_is_spelled_out(self):
        """訊息要能照著做，不是只說『失敗了』。"""
        message = runner.interpret_failure(1, '', 'x', [])
        self.assertIn('pip install pymupdf', message)

    def test_the_override_variable_is_named(self):
        message = runner.interpret_failure(1, '', 'x', [])
        self.assertIn(runner.PYTHON_ENV_VAR, message)

    def test_the_exit_code_is_reported(self):
        self.assertIn('99', runner.interpret_failure(99, '', 'x', []))


if __name__ == '__main__':
    unittest.main()
