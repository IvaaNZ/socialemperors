"""Keep Arthur's first mission connected to the real farm-land definition."""

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import command
from constants import Constant
from get_game_config import get_attribute_from_mission_id, get_game_config


class TutorialMissionTests(unittest.TestCase):
    def test_only_real_farm_land_mission_one_survives_config_patches(self):
        missions = [mission for mission in get_game_config()['missions'] if int(mission['id']) == 1]
        self.assertEqual(len(missions), 1)
        self.assertEqual(missions[0]['title'], 'Build farm land')
        self.assertEqual(missions[0]['reward'], 10)
        self.assertIn('BUILD menu', missions[0]['description'])
        self.assertIn('farm land near your Town Hall', missions[0]['description'])
        self.assertEqual(get_attribute_from_mission_id(1, 'reward'), 10)
        self.assertTrue(any(int(mission['id']) == 0 for mission in get_game_config()['missions']))

    def test_game_config_response_exposes_the_translated_real_mission_and_reward(self):
        # Exercise the actual response function and JSON serialization in an
        # isolated boot directory; account/key access is covered by access tests.
        with tempfile.TemporaryDirectory(prefix='socialemperors-mission-api-') as directory:
            with patch.dict(os.environ, {
                'SOCIAL_EMPIRES_DATA_DIR': directory,
                'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',  # These tests cover the Portuguese texts.
                'SOCIAL_EMPIRES_SAVES_DIR': str(Path(directory) / 'saves'),
            }), contextlib.redirect_stdout(io.StringIO()):
                import server
            with server.app.test_request_context(
                server.DYNAMIC_GAME_PREFIX + 'get_game_config.php', method='POST',
                data={'USERID': 'fixture', 'user_key': 'fixture', 'language': 'en'},
            ):
                response = server.app.make_response(server.get_game_config_response())
                self.assertEqual(response.status_code, 200)
                config = response.get_json()
        missions = [mission for mission in config['missions'] if int(mission['id']) == 1]
        self.assertEqual(len(missions), 1)
        self.assertEqual(missions[0]['title'], 'Construa uma plantação')
        self.assertIn('CONSTRUIR', missions[0]['description'])
        self.assertIn('perto do Centro da Vila', missions[0]['description'])
        self.assertEqual(missions[0]['reward'], 10)

    def test_reward_mission_one_credits_ten_coins_without_changing_xp_or_other_resources(self):
        village = json.loads(Path('villages/initial.json').read_text(encoding='utf-8'))
        before = copy.deepcopy(village)
        with patch.object(command, 'session', return_value=village), contextlib.redirect_stdout(io.StringIO()):
            command.do_command('fixture', Constant.CMD_REWARD_MISSION, [0, 1])
        expected = copy.deepcopy(before)
        expected['maps'][0]['coins'] += 10
        expected['privateState']['rewardedMissions'].append(1)
        self.assertEqual(village, expected)


if __name__ == '__main__':
    unittest.main()
