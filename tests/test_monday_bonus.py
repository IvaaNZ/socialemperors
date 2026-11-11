"""Monday bonus chest: one server-validated reward per Monday, kept across reloads."""

import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import command
from constants import Constant
from economy import MAX_CASH
from get_game_config import get_game_config
from monday_bonus import MondayBonusError, claim_monday_bonus, is_monday_bonus_available

MONDAY = int(datetime(2026, 11, 9, 12, 0).timestamp())
MONDAY_EVENING = int(datetime(2026, 11, 9, 22, 0).timestamp())
TUESDAY = int(datetime(2026, 11, 10, 12, 0).timestamp())
NEXT_MONDAY = int(datetime(2026, 11, 16, 9, 0).timestamp())


class MondayBonusTests(unittest.TestCase):
    def setUp(self):
        self.save = json.loads(Path('villages/initial.json').read_text(encoding='utf-8'))
        self.save['privateState'].pop('timeStampMondayBonus', None)
        self.save['privateState']['gifts'] = []
        self.save['playerInfo']['cash'] = 10
        self.save['maps'][0]['coins'] = 100
        globals_ = get_game_config()['globals']
        self.rewards = {reward['type']: reward['value'] for reward in globals_['MONDAY_BONUS_REWARDS']}
        self.units = [int(unit) for unit in globals_['MONDAY_BONUS_UNITS']]

    def test_gold_cash_and_unit_rewards_use_the_config(self):
        claim_monday_bonus(self.save, ['g', self.rewards['g']], MONDAY)
        self.assertEqual(self.save['maps'][0]['coins'], 100 + self.rewards['g'])
        self.assertEqual(self.save['privateState']['timeStampMondayBonus'], MONDAY)

        claim_monday_bonus(self.save, ['c', str(self.rewards['c'])], NEXT_MONDAY)
        self.assertEqual(self.save['playerInfo']['cash'], 10 + self.rewards['c'])

        unit = self.units[0]
        claim_monday_bonus(self.save, ['u', str(unit)], NEXT_MONDAY + 7 * 86400)
        self.assertEqual(self.save['privateState']['gifts'][unit], 1)

    def test_only_once_per_monday_and_never_on_other_days(self):
        self.assertFalse(is_monday_bonus_available(self.save, TUESDAY))
        with self.assertRaises(MondayBonusError):
            claim_monday_bonus(self.save, ['g', self.rewards['g']], TUESDAY)
        self.assertTrue(is_monday_bonus_available(self.save, MONDAY))
        claim_monday_bonus(self.save, ['g', self.rewards['g']], MONDAY)
        self.assertFalse(is_monday_bonus_available(self.save, MONDAY_EVENING))
        with self.assertRaises(MondayBonusError):
            claim_monday_bonus(self.save, ['c', self.rewards['c']], MONDAY_EVENING)
        self.assertTrue(is_monday_bonus_available(self.save, NEXT_MONDAY))

    def test_client_cannot_choose_amounts_or_units(self):
        for args in (['g', 999999], ['c', 500], ['u', 1], ['x', 1], ['g'], 'g', ['u', 'abc'], ['c', True]):
            with self.subTest(args=args):
                with self.assertRaises(MondayBonusError):
                    claim_monday_bonus(self.save, args, MONDAY)
        self.assertNotIn('timeStampMondayBonus', self.save['privateState'])
        self.assertEqual(self.save['maps'][0]['coins'], 100)
        self.assertEqual(self.save['playerInfo']['cash'], 10)

    def test_cash_respects_the_private_balance_limit(self):
        self.save['playerInfo']['cash'] = MAX_CASH - 1
        claim_monday_bonus(self.save, ['c', self.rewards['c']], MONDAY)
        self.assertEqual(self.save['playerInfo']['cash'], MAX_CASH)

    def test_weekly_reward_command_is_handled_and_saved_state_survives(self):
        with patch.object(command, 'session', return_value=self.save), \
                patch.object(command, 'timestamp_now', return_value=MONDAY), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            command.do_command('fixture', Constant.CMD_COLLECT_MONDAY_BONUS, ['g', self.rewards['g']])
            command.do_command('fixture', Constant.CMD_COLLECT_MONDAY_BONUS, ['g', self.rewards['g']])
        self.assertNotIn('Unhandled command', output.getvalue())
        self.assertIn('Monday bonus rejected', output.getvalue())
        self.assertEqual(self.save['maps'][0]['coins'], 100 + self.rewards['g'])
        self.assertEqual(self.save['privateState']['timeStampMondayBonus'], MONDAY)


if __name__ == '__main__':
    unittest.main()
