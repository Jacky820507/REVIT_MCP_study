# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import mcp_window_logic as logic


OPTIONS = [(u'甲', 'a'), (u'乙', 'b'), (u'丙', 'c')]


class FieldTests(unittest.TestCase):
    def test_a_choice_carries_its_options_and_default(self):
        field = logic.choice('mode', u'模式', OPTIONS, default='b')
        self.assertEqual(logic.CHOICE, field['kind'])
        self.assertEqual('b', field['default'])
        self.assertEqual(3, len(field['options']))

    def test_a_multichoice_defaults_to_optional(self):
        """一個都不勾是一個真的答案（例如「以上皆不符合」）。
        連珠對話框做不到這件事，這正是換成視窗的收穫，不要退回必填。"""
        field = logic.multichoice('flags', u'條件', OPTIONS)
        self.assertFalse(field['required'])

    def test_a_choice_defaults_to_required(self):
        self.assertTrue(logic.choice('mode', u'模式', OPTIONS)['required'])

    def test_sections_and_notes_produce_no_value(self):
        fields = [logic.section(u'範圍'), logic.note(u'說明'),
                  logic.choice('mode', u'模式', OPTIONS)]
        self.assertEqual(['mode'],
                         [f['key'] for f in logic.input_fields(fields)])

    def test_defaults_reads_the_spec(self):
        fields = [logic.choice('mode', u'模式', OPTIONS, default='c'),
                  logic.multichoice('flags', u'條件', OPTIONS, default=['a']),
                  logic.number('size', u'大小', default=250),
                  logic.text('name', u'名稱', default=u'預設'),
                  logic.boolean('flag', u'開關', default=True)]
        values = logic.defaults(fields)
        self.assertEqual('c', values['mode'])
        self.assertEqual(['a'], values['flags'])
        self.assertEqual(250, values['size'])
        self.assertEqual(u'預設', values['name'])
        self.assertTrue(values['flag'])

    def test_the_default_list_is_copied_not_shared(self):
        """兩個視窗共用同一個 list 會讓第一個的勾選污染第二個。"""
        shared = ['a']
        fields = [logic.multichoice('flags', u'條件', OPTIONS, default=shared)]
        values = logic.defaults(fields)
        values['flags'].append('b')
        self.assertEqual(['a'], shared)


class DuplicateKeyTests(unittest.TestCase):
    def test_a_repeated_key_is_reported(self):
        """後面的欄位會靜默蓋掉前面的——跑起來完全正常，只是答案錯了。"""
        fields = [logic.choice('mode', u'甲', OPTIONS),
                  logic.text('mode', u'乙')]
        self.assertEqual(['mode'], logic.duplicate_keys(fields))

    def test_distinct_keys_are_clean(self):
        fields = [logic.choice('a', u'甲', OPTIONS), logic.text('b', u'乙')]
        self.assertEqual([], logic.duplicate_keys(fields))

    def test_a_key_repeated_three_times_is_listed_once(self):
        fields = [logic.text('k', u'1'), logic.text('k', u'2'),
                  logic.text('k', u'3')]
        self.assertEqual(['k'], logic.duplicate_keys(fields))


class EnabledWhenTests(unittest.TestCase):
    def test_a_field_without_a_condition_is_always_enabled(self):
        self.assertTrue(logic.is_enabled(logic.text('a', u'甲'), {}))

    def test_a_matching_value_enables(self):
        field = logic.text('door', u'門', enabled_when=('mode', 'doors'))
        self.assertTrue(logic.is_enabled(field, {'mode': 'doors'}))
        self.assertFalse(logic.is_enabled(field, {'mode': 'stairs'}))

    def test_a_set_of_wanted_values_enables_on_any(self):
        field = logic.text('x', u'甲',
                           enabled_when=('mode', ('a', 'b')))
        self.assertTrue(logic.is_enabled(field, {'mode': 'b'}))
        self.assertFalse(logic.is_enabled(field, {'mode': 'c'}))

    def test_a_missing_driver_key_disables(self):
        field = logic.text('x', u'甲', enabled_when=('mode', 'a'))
        self.assertFalse(logic.is_enabled(field, {}))


class NumberTests(unittest.TestCase):
    def _field(self, **extra):
        return logic.number('size', u'格點', default=250, unit=u'mm', **extra)

    def test_a_plain_number_parses(self):
        value, error, note = logic.parse_number(u'300', self._field())
        self.assertEqual(300.0, value)
        self.assertEqual(u'', error)
        self.assertEqual(u'', note)

    def test_junk_is_rejected_by_name(self):
        value, error, unused = logic.parse_number(u'abc', self._field())
        self.assertIsNone(value)
        self.assertIn(u'格點', error)
        self.assertIn(u'abc', error)

    def test_a_value_over_the_maximum_is_clamped_and_explained(self):
        """把它夾回上限並說明，比丟一句「超出範圍」再叫人重打有用——
        後者只是把工具已經知道的事藏起來。"""
        value, error, note = logic.parse_number(u'1000',
                                                self._field(maximum=600))
        self.assertEqual(600.0, value)
        self.assertEqual(u'', error)
        self.assertIn(u'600', note)

    def test_a_value_under_the_minimum_is_clamped(self):
        value, unused, note = logic.parse_number(u'1', self._field(minimum=50))
        self.assertEqual(50.0, value)
        self.assertIn(u'50', note)

    def test_exactly_on_a_bound_is_not_clamped(self):
        value, unused, note = logic.parse_number(
            u'600', self._field(minimum=50, maximum=600))
        self.assertEqual(600.0, value)
        self.assertEqual(u'', note)

    def test_thousands_separators_survive(self):
        value, unused, unused2 = logic.parse_number(u'1,200', self._field())
        self.assertEqual(1200.0, value)

    def test_an_integer_field_rounds(self):
        value, unused, unused2 = logic.parse_number(
            u'3.6', self._field(integer=True))
        self.assertEqual(4, value)

    def test_blank_is_an_error_only_when_required(self):
        value, error, unused = logic.parse_number(u'  ', self._field())
        self.assertIn(u'格點', error)
        value, error, unused = logic.parse_number(
            u'  ', self._field(required=False))
        self.assertIsNone(value)
        self.assertEqual(u'', error)


class ValidateTests(unittest.TestCase):
    def test_a_clean_form_reports_nothing(self):
        fields = [logic.choice('mode', u'模式', OPTIONS, default='a')]
        errors, notes = logic.validate(fields, {'mode': 'a'})
        self.assertEqual({}, errors)
        self.assertEqual([], notes)

    def test_a_required_choice_left_empty_fails(self):
        fields = [logic.choice('mode', u'模式', OPTIONS)]
        errors, unused = logic.validate(fields, {'mode': None})
        self.assertIn('mode', errors)
        self.assertIn(u'模式', errors['mode'])

    def test_a_required_multichoice_left_empty_fails(self):
        fields = [logic.multichoice('flags', u'條件', OPTIONS, required=True)]
        errors, unused = logic.validate(fields, {'flags': []})
        self.assertIn('flags', errors)

    def test_an_optional_multichoice_left_empty_passes(self):
        fields = [logic.multichoice('flags', u'條件', OPTIONS)]
        errors, unused = logic.validate(fields, {'flags': []})
        self.assertEqual({}, errors)

    def test_a_disabled_field_is_not_validated(self):
        """看不到、改不了的欄位不該擋住執行鈕——使用者根本不知道要去哪裡改。"""
        fields = [logic.choice('mode', u'模式', OPTIONS, default='a'),
                  logic.text('door', u'門', required=True,
                             enabled_when=('mode', 'b'))]
        errors, unused = logic.validate(fields, {'mode': 'a', 'door': u''})
        self.assertEqual({}, errors)

    def test_an_enabled_dependent_field_is_validated(self):
        fields = [logic.choice('mode', u'模式', OPTIONS, default='b'),
                  logic.text('door', u'門', required=True,
                             enabled_when=('mode', 'b'))]
        errors, unused = logic.validate(fields, {'mode': 'b', 'door': u''})
        self.assertIn('door', errors)

    def test_validate_writes_the_parsed_number_back(self):
        fields = [logic.number('size', u'格點', default=250, maximum=600)]
        values = {'size': u'1000'}
        errors, notes = logic.validate(fields, values)
        self.assertEqual({}, errors)
        self.assertEqual(600.0, values['size'])
        self.assertEqual(1, len(notes))

    def test_a_bad_number_does_not_overwrite_the_value(self):
        fields = [logic.number('size', u'格點')]
        values = {'size': u'abc'}
        errors, unused = logic.validate(fields, values)
        self.assertIn('size', errors)
        self.assertEqual(u'abc', values['size'])

    def test_several_bad_fields_are_all_reported(self):
        """一次只講一個錯，使用者就得按 N 次執行鈕才知道全部的問題。"""
        fields = [logic.number('size', u'格點'),
                  logic.text('name', u'名稱', required=True)]
        errors, unused = logic.validate(fields, {'size': u'x', 'name': u''})
        self.assertEqual(2, len(errors))


class KeywordTests(unittest.TestCase):
    def test_half_and_full_width_commas_both_split(self):
        self.assertEqual([u'甲', u'乙', u'丙'],
                         logic.split_keywords(u'甲,乙，丙'))

    def test_the_enumeration_comma_splits_too(self):
        self.assertEqual([u'甲', u'乙'], logic.split_keywords(u'甲、乙'))

    def test_blanks_are_dropped_and_edges_trimmed(self):
        self.assertEqual([u'甲', u'乙'], logic.split_keywords(u' 甲 ,, 乙 ,'))

    def test_an_empty_string_gives_no_keywords(self):
        self.assertEqual([], logic.split_keywords(u''))
        self.assertEqual([], logic.split_keywords(None))


class OptionTests(unittest.TestCase):
    def test_a_value_round_trips_through_its_label(self):
        self.assertEqual('b', logic.value_for_label(OPTIONS, u'乙'))
        self.assertEqual(u'乙', logic.label_for_value(OPTIONS, 'b'))

    def test_an_unknown_label_gives_none(self):
        self.assertIsNone(logic.value_for_label(OPTIONS, u'丁'))

    def test_duplicate_labels_are_made_unique(self):
        """顯示文字重複時，依文字回查值會取到錯的那一個。"""
        options = [(u'甲', 1), (u'甲', 2), (u'甲', 3)]
        unique = logic.unique_labels(options)
        labels = [label for label, unused in unique]
        self.assertEqual(3, len(set(labels)))
        self.assertEqual([1, 2, 3], [value for unused, value in unique])

    def test_uniquifying_keeps_the_visible_name(self):
        options = [(u'一樓', 1), (u'一樓', 2)]
        labels = [label for label, unused in logic.unique_labels(options)]
        for label in labels:
            self.assertEqual(u'一樓', label.strip())


class ResultTests(unittest.TestCase):
    def test_a_short_table_is_not_truncated(self):
        rows, note = logic.truncate_rows([[1], [2]])
        self.assertEqual(2, len(rows))
        self.assertEqual(u'', note)

    def test_a_long_table_is_truncated_and_says_so(self):
        """只顯示前 200 列而不吭聲，會讓人以為那就是全部。"""
        rows, note = logic.truncate_rows([[n] for n in range(500)])
        self.assertEqual(logic.MAX_RESULT_ROWS, len(rows))
        self.assertIn(u'500', note)
        self.assertIn(u'輸出視窗', note)

    def test_exactly_at_the_limit_is_not_truncated(self):
        rows, note = logic.truncate_rows(
            [[n] for n in range(logic.MAX_RESULT_ROWS)])
        self.assertEqual(u'', note)

    def test_a_result_keeps_its_parts_separate(self):
        item = logic.result([u'摘要'], [u'欄'], [[u'值']])
        self.assertEqual([u'摘要'], item['summary'])
        self.assertEqual([u'欄'], item['columns'])
        self.assertEqual([[u'值']], item['rows'])


class SpecTests(unittest.TestCase):
    def test_a_spec_keeps_its_badge(self):
        item = logic.spec(u'標題', [], badge=logic.BADGE_DELETE)
        self.assertEqual(logic.BADGE_DELETE, item['badge'])

    def test_an_unknown_badge_falls_back_to_readonly(self):
        """徽章說的是「這顆按鈕會不會動到模型」。拼錯就默默變成
        「會刪除」是不能接受的，所以未知值一律退回最保守的那個。"""
        item = logic.spec(u'標題', [], badge=u'亂寫')
        self.assertEqual(logic.BADGE_READONLY, item['badge'])

    def test_the_run_label_defaults_to_something_neutral(self):
        self.assertEqual(u'執行', logic.spec(u'標題', [])['run_label'])



class MatchesFilterTests(unittest.TestCase):
    def test_empty_query_matches_everything(self):
        self.assertTrue(logic.matches_filter(u'廢水坑B平面圖', u''))
        self.assertTrue(logic.matches_filter(u'廢水坑B平面圖', u'   '))
        self.assertTrue(logic.matches_filter(u'廢水坑B平面圖', None))

    def test_all_terms_must_match_in_any_order(self):
        label = u'物流中心 一層排水平面圖(分圖)　[B-FN]　#8943376'
        self.assertTrue(logic.matches_filter(label, u'排水 一層'))
        self.assertTrue(logic.matches_filter(label, u'一層　排水'))
        self.assertFalse(logic.matches_filter(label, u'排水 二層'))

    def test_case_insensitive(self):
        self.assertTrue(logic.matches_filter(u'EL+178.9 B-FN', u'el+178 b-fn'))

    def test_multichoice_filter_flag_defaults_to_auto(self):
        self.assertIsNone(logic.multichoice('k', u'x', OPTIONS)['filter'])
        self.assertFalse(
            logic.multichoice('k', u'x', OPTIONS, filter=False)['filter'])


class RangeIndicesTests(unittest.TestCase):
    def test_forward_and_backward_ranges_match(self):
        visible = [True] * 6
        self.assertEqual(logic.range_indices(1, 4, visible), [1, 2, 3, 4])
        self.assertEqual(logic.range_indices(4, 1, visible), [1, 2, 3, 4])

    def test_filtered_out_items_are_excluded(self):
        visible = [True, False, True, False, True]
        self.assertEqual(logic.range_indices(0, 4, visible), [0, 2, 4])

    def test_no_anchor_or_out_of_range_is_empty(self):
        self.assertEqual(logic.range_indices(None, 2, [True] * 3), [])
        self.assertEqual(logic.range_indices(0, 9, [True] * 3), [])


if __name__ == '__main__':
    unittest.main()
