# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import tempfile
import unittest
import zipfile


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import code_integrity_excel as excel
import xlsx_xml


def _row(scope, element_id, name, parameter, storage='String', current='',
         proposed=None, exists=True, readonly=False, status='EMPTY'):
    if proposed is None:
        proposed = current
    return {
        'scope': scope,
        'element_id': element_id,
        'element_name': name,
        'parameter_name': parameter,
        'storage': storage,
        'current': current,
        'proposed': proposed,
        'exists': exists,
        'readonly': readonly,
        'value_status': status,
    }


def _write_xlsx(path, sheets):
    package = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
    try:
        for name, content in xlsx_xml.workbook_parts(sheets):
            package.writestr(name, content.encode('utf-8'))
    finally:
        package.close()


class CodeIntegrityExcelTests(unittest.TestCase):
    def setUp(self):
        # CI may provide a writable scratch directory; normal users fall
        # back to the operating system temporary directory.
        scratch = os.environ.get('CODEX_TEST_TMP') or tempfile.gettempdir()
        self.tempdir = tempfile.mkdtemp(
            prefix='.code-integrity-excel-', dir=scratch)

    def tearDown(self):
        for root, dirs, files in os.walk(self.tempdir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.tempdir)

    def _make_workbook(self, project_rows, area_rows=None, audit=None):
        sheets, metadata = excel.build_workbook(
            project_rows, area_rows or [], audit or {
                'AuditRunId': 'audit-1',
                'CheckedAtUtc': '2026-08-19T00:00:00Z',
                'Findings': [],
            }, 'demo.rvt', '2020')
        path = os.path.join(self.tempdir, 'integrity.xlsx')
        _write_xlsx(path, sheets)
        return path, sheets, metadata

    def test_export_round_trip_produces_importable_change(self):
        project = [_row('ProjectInformation', 0, 'Project Information',
                         'Law_法定建蔽率%', 'Integer', '', '60%', True)]
        area = [_row('Areas', 123, 'A-01', 'Law_建管-用途類組',
                     'String', '', 'G-2', True)]
        path, unused_sheets, unused_metadata = self._make_workbook(project, area)

        result = excel.import_workbook(
            path, project, area,
            expected_model_title='demo.rvt', expected_revit_version='2020')

        self.assertEqual([], result['errors'])
        self.assertEqual([], result['warnings'])
        self.assertEqual(2, len(result['changes']))
        self.assertEqual('60%', result['changes'][0]['value'])
        self.assertEqual('G-2', result['changes'][1]['value'])
        self.assertEqual(2, excel.merge_changes(project + area,
                                                  result['changes']))
        self.assertEqual('60%', project[0]['proposed'])

    def test_identity_column_change_is_blocked(self):
        project = [_row('ProjectInformation', 0, 'Project Information',
                         'Law_法定建蔽率%', 'Integer', '', '60%', True)]
        path, sheets, unused_metadata = self._make_workbook(project)
        project_sheet = sheets[1][1]
        project_sheet[1][4] = 'Law_被竄改參數'
        _write_xlsx(path, sheets)

        result = excel.import_workbook(path, project, [])

        self.assertTrue(result['errors'])
        self.assertFalse(result['changes'])
        self.assertTrue(any('參數名稱' in item for item in result['errors']))

    def test_duplicate_key_is_blocked(self):
        project = [_row('ProjectInformation', 0, 'Project Information',
                         'Law_法定建蔽率%', 'Integer', '', '60%', True)]
        path, sheets, unused_metadata = self._make_workbook(project)
        sheets[1][1].append(list(sheets[1][1][1]))
        _write_xlsx(path, sheets)

        result = excel.import_workbook(path, project, [])

        self.assertTrue(result['errors'])
        self.assertTrue(any('Key 重複' in item for item in result['errors']))

    def test_formula_and_bad_integer_are_blocked(self):
        project = [_row('ProjectInformation', 0, 'Project Information',
                         'Law_法定建蔽率%', 'Integer', '', '60%', True)]
        path, sheets, unused_metadata = self._make_workbook(project)
        proposed_column = excel.INPUT_HEADERS.index(excel.PROPOSED_HEADER)
        sheets[1][1][1][proposed_column] = '=30+30'
        _write_xlsx(path, sheets)
        formula_result = excel.import_workbook(path, project, [])
        self.assertTrue(any('公式' in item for item in formula_result['errors']))

        sheets[1][1][1][proposed_column] = '六十'
        _write_xlsx(path, sheets)
        integer_result = excel.import_workbook(path, project, [])
        self.assertTrue(any('整數欄位' in item
                            for item in integer_result['errors']))

    def test_wrong_model_is_warning_but_key_matching_remains_allowed(self):
        project = [_row('ProjectInformation', 0, 'Project Information',
                         'Law_法定建蔽率%', 'Integer', '', '60%', True)]
        path, unused_sheets, unused_metadata = self._make_workbook(project)

        result = excel.import_workbook(
            path, project, [], expected_model_title='another.rvt',
            expected_revit_version='2024')

        self.assertFalse(result['errors'])
        self.assertEqual(1, len(result['changes']))
        self.assertEqual(2, len(result['warnings']))

    def test_missing_sheet_is_blocked(self):
        project = [_row('ProjectInformation', 0, 'Project Information',
                         'Law_法定建蔽率%', 'Integer', '', '60%', True)]
        path, sheets, unused_metadata = self._make_workbook(project)
        _write_xlsx(path, [sheets[0], sheets[1], sheets[3]])

        result = excel.import_workbook(path, project, [])

        self.assertTrue(result['errors'])
        self.assertIn('Area輸入', result['errors'][0])

    def test_empty_proposed_value_does_not_clear_model(self):
        project = [_row('ProjectInformation', 0, 'Project Information',
                         'Law_法定建蔽率%', 'Integer', '50%', '', True)]
        path, unused_sheets, unused_metadata = self._make_workbook(project)

        result = excel.import_workbook(path, project, [])

        self.assertFalse(result['errors'])
        self.assertFalse(result['changes'])


if __name__ == '__main__':
    unittest.main()
