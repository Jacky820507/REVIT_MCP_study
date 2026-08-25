# -*- coding: utf-8 -*-
import ast
import os
import sys
import unittest
import xml.etree.ElementTree as ET


HERE = os.path.dirname(__file__)
LIB = os.path.abspath(os.path.join(
    HERE, '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import takeoff_entry
import takeoff_entry_logic as logic


class SourceKeyTests(unittest.TestCase):
    def test_key_shapes_and_round_trip(self):
        self.assertEqual('host', logic.HOST_SOURCE)
        self.assertEqual('link:7', logic.link_source_key(7))
        self.assertEqual('host:12', logic.level_key('host', 12))
        self.assertEqual(
            'link:7:12', logic.level_key('link:7', 12))
        self.assertEqual(
            ('host', 12), logic.parse_level_key('host:12'))
        self.assertEqual(
            ('link:7', 12), logic.parse_level_key('link:7:12'))

    def test_link_7_never_matches_link_70(self):
        selected = ['link:70:3', 'link:7:8']
        self.assertEqual(
            set([8]), logic.level_ids_for_source('link:7', selected))
        self.assertEqual(
            set([3]), logic.level_ids_for_source('link:70', selected))

    def test_no_keys_for_one_source_means_all_for_that_source(self):
        selected = ['host:4', 'link:70:9']
        self.assertEqual(
            set([4]), logic.level_ids_for_source('host', selected))
        self.assertIsNone(
            logic.level_ids_for_source('link:7', selected))
        self.assertEqual(
            set([9]), logic.level_ids_for_source('link:70', selected))
        self.assertIsNone(
            logic.level_ids_for_source('link:7', []))

    def test_prune_is_exact_and_preserves_order(self):
        selected = [
            'link:70:1', 'link:7:2', 'host:3',
            'link:7:2', 'link:8:4']
        self.assertEqual(
            ['link:7:2', 'host:3'],
            logic.prune_level_keys(
                selected, True, [7],
                ['host:3', 'link:7:2', 'link:70:1']))
        self.assertEqual(
            ['link:70:1'],
            logic.prune_level_keys(selected, False, [70]))

    def test_bad_keys_fail_closed(self):
        for key in (
                'host', 'host:1:2', 'link:7', 'link:7:1:2',
                'link:seventy:1', 'other:1'):
            with self.assertRaises(ValueError):
                logic.parse_level_key(key)

    def test_duplicate_display_labels_include_identity(self):
        self.assertEqual(
            ['Campus [id 7]', 'Campus [id 70]', 'Unique'],
            logic.disambiguate_labels([
                (7, 'Campus'), (70, 'Campus'), (8, 'Unique')]))


class _FakeId(object):
    def __init__(self, value):
        self.IntegerValue = value


class _FakeDocument(object):
    def __init__(self, title):
        self.Title = title


class _FakeLink(object):
    def __init__(self, element_id, name, link_doc):
        self.Id = _FakeId(element_id)
        self.Name = name
        self._link_doc = link_doc

    def GetLinkDocument(self):
        return self._link_doc


class _FakeLevel(object):
    def __init__(self, element_id, name, elevation=0.0):
        self.Id = _FakeId(element_id)
        self.Name = name
        self.Elevation = elevation


class IterSourcesTests(unittest.TestCase):
    def setUp(self):
        self.original_all_links = takeoff_entry._all_link_instances

    def tearDown(self):
        takeoff_entry._all_link_instances = self.original_all_links

    def test_iter_sources_contract_and_per_source_all(self):
        host = _FakeDocument('Host A')
        link_doc = _FakeDocument('Campus')
        link = _FakeLink(7, 'Campus instance', link_doc)
        takeoff_entry._all_link_instances = lambda unused_doc: [link]
        options = {
            'include_host': True,
            'selected_link_ids': [7],
            'selected_level_keys': ['host:4'],
            'workbook_path': None,
        }
        rows = list(takeoff_entry.iter_sources(host, options))
        self.assertEqual(2, len(rows))
        self.assertEqual(
            ('host', 'Host - Host A', host, set([4]), None),
            rows[0])
        self.assertEqual('link:7', rows[1][0])
        self.assertEqual('Campus', rows[1][1])
        self.assertIs(link_doc, rows[1][2])
        self.assertIsNone(rows[1][3])
        self.assertEqual(7, rows[1][4])

    def test_unloaded_selected_link_is_clear_error(self):
        host = _FakeDocument('Host A')
        link = _FakeLink(70, 'Shell link', None)
        takeoff_entry._all_link_instances = lambda unused_doc: [link]
        with self.assertRaises(Exception) as context:
            list(takeoff_entry.iter_sources(host, {
                'include_host': False,
                'selected_link_ids': [70],
                'selected_level_keys': [],
            }))
        message = str(context.exception).lower()
        self.assertIn('unloaded', message)
        self.assertIn('70', message)

    def test_missing_selected_link_is_clear_error(self):
        host = _FakeDocument('Host A')
        takeoff_entry._all_link_instances = lambda unused_doc: []
        with self.assertRaises(Exception) as context:
            list(takeoff_entry.iter_sources(host, {
                'include_host': False,
                'selected_link_ids': [7],
                'selected_level_keys': [],
            }))
        self.assertIn('not found', str(context.exception).lower())


class LevelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.original_loaded_links = takeoff_entry._loaded_link_records
        self.original_levels = takeoff_entry._levels_in_document

    def tearDown(self):
        takeoff_entry._loaded_link_records = self.original_loaded_links
        takeoff_entry._levels_in_document = self.original_levels

    def test_same_display_label_across_sources_stays_unambiguous(self):
        host = _FakeDocument('Campus')
        linked = _FakeDocument('Linked')
        # Deliberately collide with the host's rendered source label.
        takeoff_entry._loaded_link_records = lambda unused_doc: [{
            'id': 7,
            'label': 'Host - Campus',
            'doc': linked,
        }]
        takeoff_entry._levels_in_document = lambda unused_doc: [
            _FakeLevel(1, 'L1')]
        rows = takeoff_entry._level_records(host, True, [7])
        self.assertEqual(['host:1', 'link:7:1'], [
            row['key'] for row in rows])
        self.assertEqual(2, len(set(row['label'] for row in rows)))
        self.assertIn('host:1', rows[0]['label'])
        self.assertIn('link:7:1', rows[1]['label'])


class RuntimeFileTests(unittest.TestCase):
    def test_xaml_parses_and_has_browse_clear_copy(self):
        path = os.path.join(LIB, 'TakeoffEntry.xaml')
        root = ET.parse(path).getroot()
        xml = ET.tostring(root, encoding='unicode')
        self.assertIn('browseButton', xml)
        self.assertIn('clearButton', xml)
        self.assertIn(
            '未選主要 Excel：匯出獨立、含公式的活頁簿。',
            xml)
        self.assertIn('連結模型（勾選納入）', xml)
        self.assertIn('各來源樓層（勾選限制）', xml)
        self.assertNotIn('SelectionMode="Extended"', xml)
        self.assertNotIn('ListBox', xml)
        self.assertIn('ItemsControl', xml)

    def test_link_and_level_sources_are_driven_by_checkboxes(self):
        path = os.path.join(LIB, 'takeoff_entry.py')
        with open(path, 'r', encoding='utf-8') as stream:
            text = stream.read()
        self.assertIn('from System.Windows.Controls import CheckBox', text)
        self.assertIn('self.link_checks', text)
        self.assertIn('self.level_checks', text)
        self.assertIn('if bool(check_box.IsChecked)', text)
        self.assertIn('check_box.Checked += handler', text)
        self.assertIn('check_box.Unchecked += handler', text)
        self.assertNotIn('self.linkList.SelectionChanged', text)
        self.assertNotIn('self.levelList.SelectionChanged', text)

    def test_runtime_python_files_parse_without_importing_pyrevit(self):
        for name in ('takeoff_entry_logic.py', 'takeoff_entry.py'):
            path = os.path.join(LIB, name)
            with open(path, 'rb') as stream:
                ast.parse(stream.read(), filename=path)
        # The runtime module keeps pyRevit as a lazy, function-local import;
        # importing it in CPython must not require or bind a pyRevit module.
        self.assertNotIn('pyrevit', takeoff_entry.__dict__)
        self.assertTrue(callable(takeoff_entry.choose_options))
        self.assertTrue(callable(takeoff_entry.iter_sources))


if __name__ == '__main__':
    unittest.main()
