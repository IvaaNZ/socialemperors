"""Mission reward scaling and PvP strength fixes (balance.py)."""

import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import balance
import command
from balance import apply_mission_rewards, pvp_unit_power, scaled_mission_reward
from constants import Constant
from get_game_config import get_game_config, get_item_from_id


class MissionRewardTests(unittest.TestCase):
    def test_early_rewards_stay_and_late_ones_keep_pace_with_unit_prices(self):
        self.assertEqual([scaled_mission_reward(value) for value in (10, 12, 20)], [10, 12, 20])
        self.assertEqual(scaled_mission_reward(454), 4990)
        values = [scaled_mission_reward(value) for value in range(10, 455, 2)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(scaled_mission_reward(0), 0)
        self.assertEqual(scaled_mission_reward('x'), 0)

    def test_config_is_balanced_once_and_keeps_its_structure(self):
        config = {'missions': [{'id': '2', 'reward': '10'}, {'id': '227', 'reward': '454'}, {'id': '9', 'reward': 200}]}
        original_keys = [sorted(mission) for mission in config['missions']]
        self.assertEqual(apply_mission_rewards(config), 2)
        self.assertEqual([mission['reward'] for mission in config['missions']], ['10', '4990', 590])
        self.assertEqual([sorted(mission) for mission in config['missions']], original_keys)
        self.assertEqual(sorted(config), ['missions'])
        self.assertEqual(apply_mission_rewards(config), 0)  # never scaled twice
        self.assertEqual(config['missions'][1]['reward'], '4990')

    def test_served_config_and_server_payment_use_the_balanced_reward(self):
        missions = {str(mission['id']): mission for mission in get_game_config()['missions']}
        self.assertEqual(int(missions['227']['reward']), 4990)
        self.assertEqual(int(missions['2']['reward']), 10)
        spanish = {str(mission['id']): mission for mission in get_game_config('es')['missions']}
        self.assertEqual(spanish['227']['reward'], missions['227']['reward'])
        save = json.loads(Path('villages/initial.json').read_text(encoding='utf-8'))
        coins = save['maps'][0]['coins']
        with patch.object(command, 'session', return_value=save), contextlib.redirect_stdout(io.StringIO()):
            command.do_command('fixture', Constant.CMD_REWARD_MISSION, [0, 227])
        self.assertEqual(save['maps'][0]['coins'], coins + 4990)


class PvpPowerTests(unittest.TestCase):
    def test_formula_is_unchanged_for_ordinary_troops(self):
        for unit_id, power in ((509, 125), (2157, 3025), (806, 2295)):
            with self.subTest(unit_id=unit_id):
                self.assertEqual(pvp_unit_power(get_item_from_id(unit_id)), power)

    def test_kamikaze_and_siege_units_are_no_longer_overrated(self):
        self.assertEqual(pvp_unit_power(get_item_from_id(575)), 705)    # Kamikaze, was 5205
        self.assertEqual(pvp_unit_power(get_item_from_id(686)), 880)    # Infernal Kamikaze, was 6055
        self.assertEqual(pvp_unit_power(get_item_from_id(521)), 355)    # Catapult, was 655
        self.assertEqual(pvp_unit_power(get_item_from_id(522)), 455)    # Cannon, was 855
        self.assertEqual(pvp_unit_power(get_item_from_id(2012)), 955)   # Imperial Elf Catapult, was 1605
        self.assertEqual(pvp_unit_power(get_item_from_id(2074)), 7505)  # Orc Battering Ram, was 10005

    def test_raid_strength_uses_the_balanced_formula(self):
        import pvp
        unit = copy.deepcopy(get_item_from_id(575))
        self.assertEqual(pvp._power(unit), balance.pvp_unit_power(unit))


if __name__ == '__main__':
    unittest.main()
