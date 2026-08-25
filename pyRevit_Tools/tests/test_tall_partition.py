# -*- coding: utf-8 -*-
import os
import sys
import unittest


LIB = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'MCP_Tools.extension', 'lib'))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import tall_partition_logic as logic


def wall(wall_id, type_name, height, level='B-1F', rooms=(), length=10.0):
    return {
        'WallId': wall_id,
        'TypeName': type_name,
        'Level': level,
        'HeightMm': height,
        'HeightBasis': 'Parameter',
        'WallLengthM': length,
        'UniqueWallAreaM2': round(length * height / 1000.0, 2),
        'AdjacentRoomCount': len(rooms),
        'IsSharedBetweenTargetRooms': len(rooms) >= 2,
        'Rooms': list(rooms),
    }


def side(room_id, number, name, level='B-1F', boundary=5.0, area=35.0):
    return {
        'RoomId': room_id, 'Number': number, 'Name': name, 'Level': level,
        'BoundaryLengthM': boundary, 'RoomSideAreaM2': area,
    }


SAMPLE = {
    'Success': True,
    'Criteria': {
        'Levels': ['auto'], 'AutoDetectLevels': True,
        'WallTypeContains': 'TYPE', 'MinWallHeightMm': 6000,
        'ExcludeRoomNameContains': ['管道', '樓梯'],
        'IncludeSingleRoomBoundaryWalls': True, 'RoomRaySampleGrid': 3,
    },
    'Summary': {
        'RoomsScanned': 40, 'RoomsExcluded': 6, 'TallPartitionWalls': 3,
        'UniqueWallLengthM': 30.0, 'UniqueWallAreaM2': 210.0,
    },
    'Rooms': [
        {'RoomId': 101, 'Number': 'B101', 'Name': '倉儲區', 'Level': 'B-1F',
         'AreaM2': 250.5,
         'RoomClearHeightByRay': {'MinHeightMm': 7200.0,
                                  'MaxHeightMm': 7400.0,
                                  'AverageHeightMm': 7300.0}},
        {'RoomId': 102, 'Number': 'B102', 'Name': '작업장', 'Level': 'B-1F',
         'AreaM2': 120.0, 'RoomClearHeightByRay': None},
        {'RoomId': 103, 'Number': 'B103', 'Name': '庫板室', 'Level': 'B-1F',
         'AreaM2': 60.0, 'RoomClearHeightByRay': None},
    ],
    'Walls': [
        wall(9001, 'TYPE-A 輕隔間', 6500.0,
             rooms=[side(101, 'B101', '倉儲區'), side(102, 'B102', '작업장')]),
        wall(9002, 'TYPE-B 輕隔間', 8200.0, rooms=[side(101, 'B101', '倉儲區')]),
        wall(9003, 'Type-F 岩棉庫板', 9000.0,
             rooms=[side(103, 'B103', '庫板室')]),
    ],
    'ExcludedRooms': [
        {'RoomId': 900, 'Number': 'B900', 'Name': '管道間', 'Level': 'B-1F'},
    ],
    'Warnings': ['某牆缺高度參數，改用 BoundingBox'],
}


class TallPartitionLogicTests(unittest.TestCase):
    def test_wall_type_exclusion_is_normalized(self):
        rules = logic.DEFAULT_EXCLUDE_WALL_TYPES
        self.assertTrue(logic.wall_type_excluded('Type-F 岩棉庫板', rules))
        self.assertTrue(logic.wall_type_excluded('type-f岩棉庫板', rules))
        self.assertTrue(
            logic.wall_type_excluded('Type-F 岩棉庫板(柱封版)', rules))
        self.assertFalse(logic.wall_type_excluded('TYPE-A 輕隔間', rules))
        self.assertFalse(logic.wall_type_excluded('', rules))

    def test_excluded_wall_also_removes_its_only_room(self):
        """B103 qualified solely through the Type-F wall, so it must drop."""
        shaped = logic.build_workbook_data(SAMPLE)
        self.assertEqual(2, shaped['wall_count'])
        self.assertEqual(1, shaped['excluded_wall_count'])
        self.assertEqual(2, shaped['room_count'])
        room_numbers = [row[1] for row in shaped['room_values'][1:]]
        self.assertEqual(['B101', 'B102'], room_numbers)
        self.assertNotIn('B103', room_numbers)

    def test_shared_wall_counts_for_both_rooms(self):
        shaped = logic.build_workbook_data(SAMPLE)
        rows = {row[1]: row for row in shaped['room_values'][1:]}
        # B101 touches both kept walls, B102 only the shared one.
        self.assertEqual(2, rows['B101'][5])
        self.assertEqual(1, rows['B101'][6])
        self.assertEqual(1, rows['B102'][5])
        self.assertEqual(1, rows['B102'][6])
        self.assertEqual('9001, 9002', rows['B101'][12])

    def test_walls_sorted_tallest_first_within_level(self):
        shaped = logic.build_workbook_data(SAMPLE)
        heights = [row[3] for row in shaped['wall_values'][1:]]
        self.assertEqual([8200.0, 6500.0], heights)
        self.assertEqual(list(logic.WALL_HEADERS), shaped['wall_values'][0])

    def test_wall_row_names_both_rooms(self):
        shaped = logic.build_workbook_data(SAMPLE)
        shared = [row for row in shaped['wall_values'][1:] if row[1] == 9001][0]
        self.assertEqual(2, shared[7])
        self.assertEqual('是', shared[8])
        self.assertIn('B101 倉儲區', shared[9])
        self.assertIn('B102', shared[9])

    def test_room_row_carries_clear_height_and_area(self):
        shaped = logic.build_workbook_data(SAMPLE)
        rows = {row[1]: row for row in shaped['room_values'][1:]}
        self.assertEqual(250.5, rows['B101'][4])
        self.assertEqual(7200.0, rows['B101'][9])
        self.assertEqual(7300.0, rows['B101'][11])
        # A room without ray evidence leaves the height columns empty.
        self.assertIsNone(rows['B102'][9])

    def test_criteria_sheet_reports_both_exclusion_kinds(self):
        shaped = logic.build_workbook_data(SAMPLE)
        flat = ['{}|{}'.format(row[0], row[1])
                for row in shaped['criteria_values']]
        joined = '\n'.join(flat)
        self.assertIn('高度門檻(mm)|6000', joined)
        self.assertIn('Type-F 岩棉庫板', joined)
        self.assertIn('因牆型被排除的牆數|1', joined)
        self.assertIn('受影響房間數|2', joined)
        self.assertIn('管道間', joined)
        self.assertIn('某牆缺高度參數', joined)

    def test_no_exclusions_keeps_everything(self):
        shaped = logic.build_workbook_data(SAMPLE, exclusions=())
        self.assertEqual(3, shaped['wall_count'])
        self.assertEqual(3, shaped['room_count'])
        self.assertEqual(0, shaped['excluded_wall_count'])

    def test_empty_result_does_not_crash(self):
        shaped = logic.build_workbook_data(
            {'Success': True, 'Rooms': [], 'Walls': []})
        self.assertEqual(0, shaped['wall_count'])
        self.assertEqual(0, shaped['room_count'])
        self.assertEqual(1, len(shaped['wall_values']))
        self.assertEqual([], shaped['levels'])

    def test_summary_message_mentions_scope(self):
        shaped = logic.build_workbook_data(SAMPLE)
        message = logic.summary_message(shaped, 6000)
        self.assertIn('2 面', message)
        self.assertIn('2 間', message)
        self.assertIn('B-1F', message)
        self.assertIn('8200 mm', message)
        self.assertIn('依牆型排除：1 面', message)


if __name__ == '__main__':
    unittest.main()
