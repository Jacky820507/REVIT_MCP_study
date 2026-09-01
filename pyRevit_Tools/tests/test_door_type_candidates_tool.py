# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import io
import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
COMMAND_PATH = os.path.join(
    ROOT, 'MCP', 'Core', 'Commands',
    'CommandExecutor.AgileDoorTypeCandidates.cs')
DOOR_WALL_PATH = os.path.join(
    ROOT, 'MCP', 'Core', 'Commands',
    'CommandExecutor.AgileBimDoorWall.cs')
TOOL_PATH = os.path.join(ROOT, 'MCP-Server', 'src', 'tools', 'room-tools.ts')


def read_text(path):
    with io.open(path, 'r', encoding='utf-8') as source_file:
        return source_file.read()


class DoorTypeCandidateToolTests(unittest.TestCase):
    def test_command_is_registered_as_read_only_preview(self):
        source = read_text(COMMAND_PATH)
        self.assertIn('PreviewDoorTypeCandidates', source)
        self.assertIn('ReadOnly = true', source)
        self.assertIn('targetTypeId', source)
        self.assertIn('ValidateAgileDoorTypeCandidates', source)

    def test_candidate_preview_is_type_scoped_and_reports_room_pairs(self):
        source = read_text(COMMAND_PATH)
        self.assertIn('GroupAgileOpenings(openings, "type")', source)
        self.assertIn('BuildAgileDoorRoomPairs', source)
        self.assertIn('InstanceCount', source)
        self.assertIn('CurrentPerformance', source)
        self.assertIn('TargetPerformance', source)

    def test_door_specification_preview_does_not_collect_windows(self):
        source = read_text(DOOR_WALL_PATH)
        self.assertIn(
            'doc, parameters, false, includeCurtain, maxDoors, true', source)
        self.assertIn('bool includeWindows = !doorsOnly', source)

    def test_mcp_schema_exposes_target_type_id_and_performance_parameters(self):
        source = read_text(TOOL_PATH)
        self.assertIn('name: "preview_door_type_candidates"', source)
        self.assertIn('targetTypeId: { type: "number" }', source)
        self.assertIn('performanceParameters', source)
        self.assertIn('required: ["rules"]', source)


if __name__ == '__main__':
    unittest.main()
