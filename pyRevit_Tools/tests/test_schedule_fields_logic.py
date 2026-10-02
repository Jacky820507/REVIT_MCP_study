# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import schedule_fields_logic as logic


def _state():
    used = [logic.entry('a', u'樓層', field_id=1),
            logic.entry('b', u'編號', field_id=2),
            logic.entry('c', u'備註', field_id=3),
            logic.entry(logic.fixed_key(4), u'面積比', fixed=True, field_id=4)]
    available = [logic.entry('a', u'樓層'), logic.entry('d', u'名稱'),
                 logic.entry('e', u'周長')]
    return logic.new_state(used, available)


class StateTests(unittest.TestCase):
    def test_pool_excludes_used_keys(self):
        self.assertEqual(sorted(logic.keys_of(_state()['pool'])), ['d', 'e'])

    def test_add_inserts_at_position(self):
        state = logic.add(_state(), ['e'], at=1)
        self.assertEqual(logic.keys_of(state['used'])[:3], ['a', 'e', 'b'])
        self.assertEqual(logic.keys_of(state['pool']), ['d'])

    def test_remove_then_add_back_is_no_change(self):
        original = _state()
        state = logic.remove(original, ['b'])
        state = logic.add(state, ['b'], at=1)
        change = logic.diff(original['used'], state['used'])
        self.assertFalse(change['changed'])
        self.assertEqual(state['used'][1]['field_id'], 2)

    def test_move_block_up_stops_at_edge(self):
        state = logic.move(_state(), ['a', 'c'], -1)
        self.assertEqual(logic.keys_of(state['used'])[:3], ['a', 'c', 'b'])

    def test_move_down(self):
        state = logic.move(_state(), ['a'], 1)
        self.assertEqual(logic.keys_of(state['used'])[:2], ['b', 'a'])

    def test_move_to_top(self):
        state = logic.move_to_edge(_state(), ['c'], True)
        self.assertEqual(logic.keys_of(state['used'])[0], 'c')

    def test_input_state_not_mutated(self):
        original = _state()
        logic.set_heading(original, 'a', u'X')
        self.assertEqual(original['used'][0]['heading'], u'樓層')


class DiffTests(unittest.TestCase):
    def test_append_only_is_not_reorder(self):
        original = _state()
        state = logic.add(original, ['d'])
        change = logic.diff(original['used'], state['used'])
        self.assertEqual(logic.keys_of(change['added']), ['d'])
        self.assertFalse(change['reordered'])

    def test_insert_in_middle_needs_reorder(self):
        original = _state()
        change = logic.diff(original['used'],
                            logic.add(original, ['d'], at=0)['used'])
        self.assertTrue(change['reordered'])

    def test_remove_and_rename(self):
        original = _state()
        state = logic.set_heading(logic.remove(original, ['c']), 'a', u'FL')
        change = logic.diff(original['used'], state['used'])
        self.assertEqual(logic.keys_of(change['removed']), ['c'])
        self.assertEqual(change['renamed'][0][1:], (u'樓層', u'FL'))
        self.assertFalse(change['reordered'])
        self.assertTrue(logic.summary_lines(change))


class HiddenTests(unittest.TestCase):
    def test_batch_hide_and_unhide(self):
        original = _state()
        state = logic.set_hidden(original, ['a', 'b'], True)
        change = logic.diff(original['used'], state['used'])
        self.assertEqual([i['key'] for i, o, n in change['hidden']], ['a', 'b'])
        self.assertTrue(change['changed'])
        back = logic.set_hidden(state, ['a', 'b'], False)
        self.assertFalse(logic.diff(original['used'], back['used'])['changed'])

    def test_display_name_shows_source(self):
        item = logic.entry('k', u'材質', source=u'類型')
        self.assertEqual(logic.display_name(item), u'材質（類型）')


class CopyTests(unittest.TestCase):
    def test_copy_maps_by_key_and_reports_missing(self):
        source = logic.set_heading(_state(), 'b', u'No.')['used']
        target = logic.new_state(
            [logic.entry('d', u'名稱', field_id=9)],
            [logic.entry('a', u'樓層'), logic.entry('b', u'編號')])
        state, missing = logic.copy_layout(source, target)
        self.assertEqual(logic.keys_of(state['used']), ['a', 'b'])
        self.assertEqual(state['used'][1]['heading'], u'No.')
        self.assertEqual(missing, [u'備註', u'面積比'])
        self.assertEqual(logic.keys_of(state['pool']), ['d'])
        self.assertEqual(state['pool'][0]['field_id'], 9)


class LabelTests(unittest.TestCase):
    def test_label_marks(self):
        item = logic.entry('k', u'名稱', heading=u'N', hidden=True)
        self.assertIn(u'「N」', logic.label(item))
        self.assertIn(u'＋新增', logic.label(item))
        self.assertTrue(logic.matches(item, u'名'))
        self.assertFalse(logic.matches(item, u'名 X'))


if __name__ == '__main__':
    unittest.main()
