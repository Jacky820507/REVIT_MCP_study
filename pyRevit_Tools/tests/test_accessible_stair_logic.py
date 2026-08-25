# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import accessible_stair_logic as logic


def stair(stair_id=1, **overrides):
    """A stair that passes 304.1 cleanly, so each test breaks one thing."""
    record = {
        'id': stair_id,
        'name': u'ST-1',
        'type_name': u'RC 樓梯',
        'base_level_id': 10,
        'top_level_id': 20,
        'base_elevation_mm': 0.0,
        'top_elevation_mm': 3200.0,
        'multistory_id': -1,
        'multistory_level_ids': [],
        'riser_mm': 155.0,
        'tread_mm': 280.0,
        'min_run_width_mm': 1400.0,
        'run_styles': [u'Straight'],
        'risers_present': True,
        'designated': False,
        'designation_value': u'',
        'building': u'A棟',
        'centre_x_mm': 0.0,
        'centre_y_mm': 0.0,
    }
    record.update(overrides)
    return record


class GeometryTests(unittest.TestCase):
    def test_a_compliant_stair_has_nothing_to_report(self):
        fails, reviews = logic.stair_failures(stair())
        self.assertEqual([], fails)
        self.assertEqual([], reviews)

    def test_riser_over_16cm_fails_the_general_rule(self):
        fails, unused = logic.stair_failures(stair(riser_mm=165.0,
                                                   tread_mm=280.0))
        self.assertIn(logic.FAIL_RISER, fails)

    def test_tread_under_26cm_fails_the_general_rule(self):
        fails, unused = logic.stair_failures(stair(riser_mm=150.0,
                                                   tread_mm=250.0))
        self.assertIn(logic.FAIL_TREAD, fails)

    def test_18cm_riser_fails_304_1_but_passes_304_4(self):
        """The distinction the domain file had collapsed.

        304.4's 18/24 pair applies only to 公寓大廈; reading it as the general
        rule passes a stair the law fails.
        """
        record = stair(riser_mm=180.0, tread_mm=245.0)
        general, unused = logic.stair_failures(record, logic.RULE_GENERAL)
        self.assertIn(logic.FAIL_RISER, general)
        self.assertIn(logic.FAIL_TREAD, general)
        apartment, unused = logic.stair_failures(record, logic.RULE_APARTMENT)
        self.assertEqual([], apartment)

    def test_two_r_plus_t_below_the_range_fails(self):
        # 2*130 + 260 = 520 < 550, though R and T are each within limits.
        fails, unused = logic.stair_failures(stair(riser_mm=130.0,
                                                   tread_mm=260.0))
        self.assertIn(logic.FAIL_FORMULA, fails)
        self.assertNotIn(logic.FAIL_RISER, fails)
        self.assertNotIn(logic.FAIL_TREAD, fails)

    def test_two_r_plus_t_above_the_range_fails(self):
        # 2*160 + 340 = 660 > 650.
        fails, unused = logic.stair_failures(stair(riser_mm=160.0,
                                                   tread_mm=340.0))
        self.assertIn(logic.FAIL_FORMULA, fails)

    def test_exactly_on_the_limits_passes(self):
        # 2*160 + 260 = 580, inside 550~650.
        fails, reviews = logic.stair_failures(stair(riser_mm=160.0,
                                                    tread_mm=260.0))
        self.assertEqual([], fails)
        self.assertEqual([], reviews)

    def test_open_riser_stair_fails(self):
        fails, unused = logic.stair_failures(stair(risers_present=False))
        self.assertIn(logic.FAIL_OPEN_RISER, fails)

    def test_unreadable_riser_flag_is_not_treated_as_open(self):
        fails, unused = logic.stair_failures(stair(risers_present=None))
        self.assertNotIn(logic.FAIL_OPEN_RISER, fails)

    def test_spiral_run_is_reviewed_not_failed(self):
        fails, reviews = logic.stair_failures(stair(run_styles=[u'Spiral']))
        self.assertEqual([], fails)
        self.assertIn(logic.REVIEW_RUN_STYLE, reviews)

    def test_winder_run_is_reviewed(self):
        unused, reviews = logic.stair_failures(
            stair(run_styles=[u'Straight', u'Winder']))
        self.assertIn(logic.REVIEW_RUN_STYLE, reviews)

    def test_missing_dimensions_are_reviewed_not_passed(self):
        fails, reviews = logic.stair_failures(stair(riser_mm=None,
                                                    tread_mm=None))
        self.assertEqual([], fails)
        self.assertIn(logic.REVIEW_NO_DIMENSION, reviews)

    def test_zero_dimensions_are_reviewed(self):
        unused, reviews = logic.stair_failures(stair(riser_mm=0.0))
        self.assertIn(logic.REVIEW_NO_DIMENSION, reviews)


class ChainTests(unittest.TestCase):
    def test_a_lone_stair_is_its_own_chain(self):
        chains = logic.build_chains([stair(1)])
        self.assertEqual(1, len(chains))
        self.assertEqual([1], chains[0]['ids'])

    def test_stacked_stairs_join_into_one_chain(self):
        lower = stair(1, base_level_id=10, top_level_id=20)
        upper = stair(2, base_level_id=20, top_level_id=30,
                      base_elevation_mm=3200.0, top_elevation_mm=6400.0)
        chains = logic.build_chains([lower, upper])
        self.assertEqual(1, len(chains))
        self.assertEqual([1, 2], chains[0]['ids'])
        self.assertAlmostEqual(0.0, chains[0]['bottom_mm'], 6)
        self.assertAlmostEqual(6400.0, chains[0]['top_mm'], 6)

    def test_separate_stairwells_do_not_merge_just_because_levels_line_up(self):
        """The failure that would silently halve the 直通樓梯 count."""
        lower = stair(1, base_level_id=10, top_level_id=20,
                      centre_x_mm=0.0, centre_y_mm=0.0)
        far = stair(2, base_level_id=20, top_level_id=30,
                    centre_x_mm=40000.0, centre_y_mm=0.0)
        chains = logic.build_chains([lower, far])
        self.assertEqual(2, len(chains))

    def test_stairs_in_different_buildings_never_merge(self):
        lower = stair(1, base_level_id=10, top_level_id=20, building=u'A棟')
        upper = stair(2, base_level_id=20, top_level_id=30, building=u'B棟')
        chains = logic.build_chains([lower, upper])
        self.assertEqual(2, len(chains))

    def test_multistory_group_wins_over_distance(self):
        """Revit already said these are one stair; do not second-guess it."""
        first = stair(1, multistory_id=99, centre_x_mm=0.0)
        second = stair(2, multistory_id=99, centre_x_mm=99000.0,
                       base_level_id=77, top_level_id=88)
        chains = logic.build_chains([first, second])
        self.assertEqual(1, len(chains))
        self.assertEqual([1, 2], chains[0]['ids'])

    def test_chain_collects_every_level_it_touches(self):
        lower = stair(1, base_level_id=10, top_level_id=20)
        upper = stair(2, base_level_id=20, top_level_id=30,
                      base_elevation_mm=3200.0)
        chain = logic.build_chains([lower, upper])[0]
        self.assertEqual(set([10, 20, 30]), set(chain['level_ids']))

    def test_multistory_placement_levels_count_as_touched(self):
        record = stair(1, multistory_id=5, multistory_level_ids=[10, 20, 30, 40])
        chain = logic.build_chains([record])[0]
        self.assertIn(40, chain['level_ids'])

    def test_three_storeys_chain_together(self):
        records = [
            stair(1, base_level_id=10, top_level_id=20,
                  base_elevation_mm=0.0, top_elevation_mm=3200.0),
            stair(2, base_level_id=20, top_level_id=30,
                  base_elevation_mm=3200.0, top_elevation_mm=6400.0),
            stair(3, base_level_id=30, top_level_id=40,
                  base_elevation_mm=6400.0, top_elevation_mm=9600.0),
        ]
        chains = logic.build_chains(records)
        self.assertEqual(1, len(chains))
        self.assertEqual([1, 2, 3], chains[0]['ids'])


class RefugeTests(unittest.TestCase):
    def test_chain_touching_the_refuge_level_serves_it(self):
        chain = logic.build_chains([stair(1, base_level_id=10,
                                          top_level_id=20)])[0]
        self.assertTrue(logic.serves_refuge(chain, 10))

    def test_chain_above_the_refuge_level_does_not(self):
        chain = logic.build_chains([stair(1, base_level_id=20,
                                          top_level_id=30)])[0]
        self.assertFalse(logic.serves_refuge(chain, 10))

    def test_no_refuge_level_declared_means_do_not_exclude_anything(self):
        chain = logic.build_chains([stair(1)])[0]
        self.assertTrue(logic.serves_refuge(chain, None))


class ChainVerdictTests(unittest.TestCase):
    def test_uniform_chain_passes(self):
        records = [stair(1, base_level_id=10, top_level_id=20),
                   stair(2, base_level_id=20, top_level_id=30,
                         base_elevation_mm=3200.0)]
        chain = logic.evaluate_chain(logic.build_chains(records)[0])
        self.assertEqual(logic.VERDICT_OK, chain['verdict'])

    def test_riser_drift_between_flights_fails_uniformity(self):
        """304.1 says 級高及級深應統一 — across the whole stair, not per flight."""
        records = [stair(1, base_level_id=10, top_level_id=20, riser_mm=155.0),
                   stair(2, base_level_id=20, top_level_id=30, riser_mm=158.0,
                         base_elevation_mm=3200.0)]
        chain = logic.evaluate_chain(logic.build_chains(records)[0])
        self.assertEqual(logic.VERDICT_FAIL, chain['verdict'])
        self.assertIn(logic.FAIL_NOT_UNIFORM, chain['failures'])

    def test_one_bad_flight_condemns_the_chain(self):
        records = [stair(1, base_level_id=10, top_level_id=20),
                   stair(2, base_level_id=20, top_level_id=30,
                         base_elevation_mm=3200.0, risers_present=False)]
        chain = logic.evaluate_chain(logic.build_chains(records)[0])
        self.assertEqual(logic.VERDICT_FAIL, chain['verdict'])

    def test_review_does_not_become_a_pass(self):
        chain = logic.evaluate_chain(
            logic.build_chains([stair(1, run_styles=[u'Spiral'])])[0])
        self.assertEqual(logic.VERDICT_REVIEW, chain['verdict'])

    def test_a_hard_failure_outranks_a_review(self):
        chain = logic.evaluate_chain(logic.build_chains(
            [stair(1, run_styles=[u'Spiral'], riser_mm=200.0)])[0])
        self.assertEqual(logic.VERDICT_FAIL, chain['verdict'])

    def test_designation_on_any_flight_marks_the_chain(self):
        records = [stair(1, base_level_id=10, top_level_id=20),
                   stair(2, base_level_id=20, top_level_id=30,
                         base_elevation_mm=3200.0, designated=True,
                         designation_value=u'A')]
        chain = logic.evaluate_chain(logic.build_chains(records)[0])
        self.assertTrue(chain['designated'])
        self.assertEqual([u'A'], chain['designation_values'])

    def test_chain_reports_the_worst_riser_and_narrowest_run(self):
        records = [stair(1, base_level_id=10, top_level_id=20,
                         riser_mm=155.0, min_run_width_mm=1400.0),
                   stair(2, base_level_id=20, top_level_id=30,
                         base_elevation_mm=3200.0, riser_mm=155.0,
                         min_run_width_mm=1150.0)]
        chain = logic.evaluate_chain(logic.build_chains(records)[0])
        self.assertAlmostEqual(1150.0, chain['min_run_width_mm'], 6)


class BuildingVerdictTests(unittest.TestCase):
    def test_one_qualifying_accessible_stair_passes(self):
        records = [stair(1, designated=True, designation_value=u'A'),
                   stair(2, centre_x_mm=30000.0)]
        result = logic.evaluate(records, refuge_level_id=10)
        self.assertEqual(1, len(result['buildings']))
        self.assertEqual(logic.BUILDING_PASS,
                         result['buildings'][0]['outcome'])

    def test_no_accessible_stair_at_all_fails(self):
        result = logic.evaluate([stair(1), stair(2, centre_x_mm=30000.0)],
                                refuge_level_id=10)
        self.assertEqual(logic.BUILDING_FAIL,
                         result['buildings'][0]['outcome'])

    def test_a_mislabelled_stair_does_not_satisfy_the_quota(self):
        """The false pass this whole module exists to prevent.

        It carries the project's 無障礙 marker but has 20cm risers, so it is a
        mislabelled ordinary stair and the building still has none.
        """
        records = [stair(1, designated=True, designation_value=u'A',
                         riser_mm=200.0, tread_mm=240.0)]
        result = logic.evaluate(records, refuge_level_id=10)
        entry = result['buildings'][0]
        self.assertEqual(logic.BUILDING_FAIL, entry['outcome'])
        self.assertEqual(0, len(entry['qualified']))
        self.assertEqual(1, len(entry['designated_failing']))
        self.assertEqual([1], result['failed_ids'])

    def test_the_same_stair_passes_under_the_apartment_rule(self):
        records = [stair(1, designated=True, riser_mm=180.0, tread_mm=245.0)]
        general = logic.evaluate(records, logic.RULE_GENERAL,
                                 refuge_level_id=10)
        self.assertEqual(logic.BUILDING_FAIL,
                         general['buildings'][0]['outcome'])
        apartment = logic.evaluate(records, logic.RULE_APARTMENT,
                                   refuge_level_id=10)
        self.assertEqual(logic.BUILDING_PASS,
                         apartment['buildings'][0]['outcome'])

    def test_only_an_unresolved_candidate_is_undecided_not_failed(self):
        records = [stair(1, designated=True, run_styles=[u'Spiral'])]
        result = logic.evaluate(records, refuge_level_id=10)
        self.assertEqual(logic.BUILDING_UNDECIDED,
                         result['buildings'][0]['outcome'])

    def test_a_qualifying_stair_outweighs_a_mislabelled_one(self):
        records = [stair(1, designated=True, riser_mm=200.0, tread_mm=240.0),
                   stair(2, designated=True, centre_x_mm=30000.0)]
        result = logic.evaluate(records, refuge_level_id=10)
        entry = result['buildings'][0]
        self.assertEqual(logic.BUILDING_PASS, entry['outcome'])
        # Still surfaced: the quota is met, but that stair is still wrong.
        self.assertEqual(1, len(entry['designated_failing']))

    def test_stairs_that_miss_the_refuge_level_are_excluded(self):
        records = [stair(1, base_level_id=20, top_level_id=30,
                         designated=True)]
        result = logic.evaluate(records, refuge_level_id=10)
        entry = result['buildings'][0]
        self.assertEqual(logic.BUILDING_NO_STAIR, entry['outcome'])
        self.assertEqual(1, len(entry['not_direct']))

    def test_each_building_is_judged_on_its_own(self):
        records = [stair(1, building=u'A棟', designated=True),
                   stair(2, building=u'B棟', centre_x_mm=30000.0)]
        result = logic.evaluate(records, refuge_level_id=10)
        outcomes = dict((entry['building'], entry['outcome'])
                        for entry in result['buildings'])
        self.assertEqual(logic.BUILDING_PASS, outcomes[u'A棟'])
        self.assertEqual(logic.BUILDING_FAIL, outcomes[u'B棟'])

    def test_undesignated_but_compliant_stairs_are_offered_as_candidates(self):
        result = logic.evaluate([stair(1)], refuge_level_id=10)
        entry = result['buildings'][0]
        self.assertEqual(1, len(entry['candidates']))

    def test_candidates_are_not_listed_once_the_quota_is_met(self):
        records = [stair(1, designated=True),
                   stair(2, centre_x_mm=30000.0)]
        result = logic.evaluate(records, refuge_level_id=10)
        entry = result['buildings'][0]
        self.assertEqual(logic.BUILDING_PASS, entry['outcome'])
        self.assertEqual(1, len(entry['candidates']))
        self.assertNotIn(u'可考慮指定為無障礙樓梯',
                         logic.report_lines(result))

    def test_evaluate_stamps_serves_refuge_on_every_chain(self):
        """The button reads this key straight off the chain to fill a column."""
        records = [stair(1, base_level_id=10, top_level_id=20),
                   stair(2, base_level_id=20, top_level_id=30,
                         centre_x_mm=30000.0)]
        result = logic.evaluate(records, refuge_level_id=10)
        flags = dict((chain['ids'][0], chain['serves_refuge'])
                     for chain in result['chains'])
        self.assertTrue(flags[1])
        self.assertFalse(flags[2])

    def test_no_stairs_at_all_yields_no_buildings(self):
        result = logic.evaluate([], refuge_level_id=10)
        self.assertEqual([], result['buildings'])
        self.assertFalse(logic.has_problem(result))


class ReportTests(unittest.TestCase):
    def test_report_quotes_the_article_and_the_rule_applied(self):
        text = logic.report_lines(logic.evaluate([stair(1, designated=True)],
                                                 refuge_level_id=10))
        self.assertIn(u'167-2', text)
        self.assertIn(u'304.1', text)

    def test_report_names_the_apartment_rule_when_chosen(self):
        text = logic.report_lines(logic.evaluate(
            [stair(1, designated=True)], logic.RULE_APARTMENT,
            refuge_level_id=10))
        self.assertIn(u'304.4', text)

    def test_report_calls_out_a_mislabelled_stair(self):
        result = logic.evaluate(
            [stair(1, designated=True, riser_mm=200.0, tread_mm=240.0)],
            refuge_level_id=10)
        text = logic.report_lines(result)
        self.assertIn(u'已標示為無障礙但尺寸不符', text)
        self.assertIn(logic.FAIL_RISER, text)

    def test_report_says_what_it_did_not_check(self):
        text = logic.report_lines(logic.evaluate([stair(1)],
                                                 refuge_level_id=10))
        self.assertIn(u'扶手', text)

    def test_has_problem_is_false_only_on_a_clean_pass(self):
        clean = logic.evaluate([stair(1, designated=True)],
                               refuge_level_id=10)
        self.assertFalse(logic.has_problem(clean))
        dirty = logic.evaluate(
            [stair(1, designated=True),
             stair(2, designated=True, centre_x_mm=30000.0, riser_mm=200.0)],
            refuge_level_id=10)
        self.assertTrue(logic.has_problem(dirty))


if __name__ == '__main__':
    unittest.main()
