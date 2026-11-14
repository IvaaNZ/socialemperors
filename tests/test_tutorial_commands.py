"""Exercise native tutorial packets against an isolated in-memory village."""

import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import command
from constants import Constant



def without_collect_time(items):
    """The items without the time they were last collected (collecting now saves it)."""
    return [item[:4] + item[5:] for item in items]

class TutorialCommandTests(unittest.TestCase):
    def setUp(self):
        self.save = json.loads(Path('villages/initial.json').read_text(encoding='utf-8'))
        self.save['playerInfo']['cash'] = 75
        session_patch = patch.object(command, 'session', return_value=self.save)
        writer_patch = patch.object(command, 'save_session')
        self.writer = writer_patch.start()
        session_patch.start()
        self.addCleanup(session_patch.stop)
        self.addCleanup(writer_patch.stop)
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def run_command(self, name, args):
        command.do_command('tutorial-fixture', name, args)

    def harvest_packet(self):
        # This order was observed in the pinned client: cutting reaches step 6,
        # collection credits the tree, HARV removes it, then step 7 follows.
        return {
            'ts': 1792690000, 'first_number': 1, 'accessToken': 'fixture-only',
            'tries': 1, 'publishActions': [],
            'commands': [
                {'cmd': Constant.CMD_COMPLETE_TUTORIAL, 'args': [6]},
                {'cmd': Constant.CMD_COLLECT, 'args': [50, 58, 0, 19, 1, 1, 0]},
                {'cmd': Constant.CMD_SELL, 'args': [50, 58, 19, 0, 0, 'HARV']},
                {'cmd': Constant.CMD_COMPLETE_TUTORIAL, 'args': [7]},
            ],
        }

    def test_real_harvest_order_credits_once_and_replayed_packet_cannot_collect_a_removed_tree(self):
        before = copy.deepcopy(self.save)
        packet = self.harvest_packet()
        command.command('tutorial-fixture', packet)
        actual = self.save['maps'][0]
        self.assertEqual(actual['wood'], before['maps'][0]['wood'] + 20)
        self.assertEqual(actual['xp'], before['maps'][0]['xp'] + 1)
        self.assertFalse(any(item[:3] == [19, 50, 58] for item in actual['items']))
        after_harvest = copy.deepcopy(self.save)

        # Both an identical retry and a late copy with a new timestamp have no
        # tree left to harvest. Other trees remain and must not match by ID only.
        command.command('tutorial-fixture', copy.deepcopy(packet))
        packet['ts'] += 5
        packet['tries'] = 2
        command.command('tutorial-fixture', packet)
        self.assertEqual(self.save, after_harvest)
        self.assertEqual(self.writer.call_count, 3)

    def test_missing_tree_does_not_grant_resources_xp_or_charge_acceleration_cash(self):
        for x, y in ((99, 99), (44, 50), (50, 57)):
            with self.subTest(position=(x, y)):
                before = copy.deepcopy(self.save)
                self.run_command(Constant.CMD_COLLECT, [x, y, 0, 19, 1, 1, 10])
                self.assertEqual(self.save, before)

    def test_missing_tree_on_another_map_cannot_match_the_home_village_tree(self):
        other_map = copy.deepcopy(self.save['maps'][0])
        other_map.update(id=1, items=[], wood=200, xp=40)
        self.save['maps'].append(other_map)
        before = copy.deepcopy(self.save)
        self.run_command(Constant.CMD_COLLECT, [50, 58, 1, 19, 1, 1, 10])
        self.assertEqual(self.save, before)

    def test_valid_tree_collection_keeps_resource_xp_and_acceleration_cost(self):
        before = copy.deepcopy(self.save)
        self.run_command(Constant.CMD_COLLECT, [50, 58, 0, 19, 1, 1, 10])
        self.assertEqual(self.save['maps'][0]['wood'], before['maps'][0]['wood'] + 20)
        self.assertEqual(self.save['maps'][0]['xp'], before['maps'][0]['xp'] + 1)
        self.assertEqual(self.save['playerInfo']['cash'], before['playerInfo']['cash'] - 10)
        self.assertEqual(without_collect_time(self.save['maps'][0]['items']), without_collect_time(before['maps'][0]['items']))

    def test_regular_mill_can_be_collected_again_without_being_removed(self):
        self.save['maps'][0]['items'].append([5, 60, 60, 0, 0, 0, [], {}])
        before = copy.deepcopy(self.save)
        self.run_command(Constant.CMD_COLLECT, [60, 60, 0, 5, 0, 1, 0])
        # The renewable mill stays in place for the next production cycle.
        self.run_command(Constant.CMD_COLLECT, [60, 60, 0, 5, 0, 1, 0])
        self.assertEqual(self.save['maps'][0]['food'], before['maps'][0]['food'] + 500)
        self.assertEqual(self.save['maps'][0]['xp'], before['maps'][0]['xp'] + 18)
        self.assertEqual(without_collect_time(self.save['maps'][0]['items']), without_collect_time(before['maps'][0]['items']))
        self.assertEqual(self.save['playerInfo']['cash'], before['playerInfo']['cash'])

    def test_unoccupied_natural_deposits_do_not_reward_scenery_cleanup(self):
        for index, item_id in enumerate((19, 20, 21, 69, 70, 71, 72, 73, 74, 75, 76)):
            with self.subTest(item_id=item_id):
                x, y = 20 + index, 25
                self.save['maps'][0]['items'].append([item_id, x, y, 0, 1792698297, 0])
                before = copy.deepcopy(self.save)
                self.run_command(Constant.CMD_COLLECT, [x, y, 0, item_id, 0, 1, 10])
                self.assertEqual(self.save, before)

    def test_real_cleanup_command_order_removes_scenery_without_xp_or_resources(self):
        # Observed on reload before any click: natural deposits with no worker
        # emitted collect_new/HARV and later CLEAN_0, causing a jump to level 4.
        targets = ((20, 24, 26), (19, 32, 22), (74, 22, 43), (69, 30, 30))
        commands = []
        for item_id, x, y in targets:
            self.save['maps'][0]['items'].append([item_id, x, y, 0, 1792698297, 0])
            commands.extend((
                {'cmd': Constant.CMD_COLLECT, 'args': [x, y, 0, item_id, 0, 1, 0]},
                {'cmd': Constant.CMD_SELL, 'args': [x, y, item_id, 0, 0, 'HARV']},
                {'cmd': Constant.CMD_SELL, 'args': [x, y, item_id, 0, 1, 'CLEAN_0']},
            ))
        expected = copy.deepcopy(self.save)
        expected['maps'][0]['items'] = [item for item in expected['maps'][0]['items']
                                       if tuple(item[:3]) not in targets]
        command.command('tutorial-fixture', dict(self.harvest_packet(), commands=commands))
        self.assertEqual(self.save, expected)

    def test_worker_harvest_of_stone_and_gold_still_credits_once(self):
        for item_id, resource in ((69, 'stone'), (74, 'coins')):
            with self.subTest(item_id=item_id):
                self.save['maps'][0]['items'].append([item_id, 30, 30, 0, 0, 0])
                before = copy.deepcopy(self.save)
                self.run_command(Constant.CMD_COLLECT, [30, 30, 0, item_id, 1, 1, 0])
                self.assertEqual(self.save['maps'][0][resource], before['maps'][0][resource] + 10)
                self.assertEqual(self.save['maps'][0]['xp'], before['maps'][0]['xp'] + 1)
                self.run_command(Constant.CMD_SELL, [30, 30, item_id, 0, 0, 'HARV'])
                harvested = copy.deepcopy(self.save)
                self.run_command(Constant.CMD_COLLECT, [30, 30, 0, item_id, 1, 1, 0])
                self.assertEqual(self.save, harvested)

    def test_native_finish_records_completion_without_granting_xp_or_resources(self):
        before_map = copy.deepcopy(self.save['maps'])
        before_cash = self.save['playerInfo']['cash']
        self.run_command(Constant.CMD_COMPLETE_TUTORIAL, [31])
        self.assertEqual(self.save['playerInfo']['completed_tutorial'], 1)
        self.assertEqual(self.save['privateState']['startingTutorialStep'], 31)
        self.assertEqual(self.save['privateState']['dragonNestActive'], 1)
        self.assertEqual(self.save['maps'], before_map)
        self.assertEqual(self.save['playerInfo']['cash'], before_cash)
        completed = copy.deepcopy(self.save)
        self.run_command(Constant.CMD_COMPLETE_TUTORIAL, [31])
        self.run_command(Constant.CMD_COMPLETE_TUTORIAL, [3])
        self.assertEqual(self.save, completed)


if __name__ == '__main__':
    unittest.main()
