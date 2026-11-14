import datetime
import os
import unittest
from unittest.mock import patch

from constants import Constant
from darts import DAYS_AHEAD, DAYS_BACK, apply_darts_command, daily_darts_items, prize_sets, with_daily_darts
from get_game_config import get_game_config

TODAY = datetime.date(2026, 11, 14)


def texts(config):
    return {entry['name']: entry['text'] for entry in config['localization_strings']
            if isinstance(entry, dict) and entry['name'] in ('DARTS_COME_BACK', 'TITLE_DESCRIPTION_DARTS')}


class DailyDartsConfig(unittest.TestCase):
    def test_the_original_prizes_are_weekly_and_end_in_2012(self):
        entries = get_game_config('en')['darts_items']
        self.assertEqual(len(prize_sets(get_game_config('en'))), 32)
        self.assertEqual(entries[-1]['items'], [])  # today the game finds no prizes at all
        self.assertTrue(entries[-1]['start_date'].startswith('2012-09-09'))

    def test_one_board_per_day_around_today_with_the_games_own_prizes(self):
        sets = prize_sets(get_game_config('en'))
        entries = daily_darts_items(TODAY, sets)
        self.assertEqual(len(entries), DAYS_BACK + DAYS_AHEAD + 1)
        dates = [entry['start_date'] for entry in entries]
        self.assertIn('2026-11-14 00:00:00', dates)
        self.assertIn('2026-11-15 00:00:00', dates)  # "next": the countdown runs to tomorrow
        self.assertEqual(dates, sorted(dates))
        today, tomorrow = entries[DAYS_BACK], entries[DAYS_BACK + 1]
        self.assertEqual(today['start_date'], '2026-11-14 00:00:00')
        self.assertNotEqual(today['items'], tomorrow['items'])
        self.assertTrue(all(len(entry['items']) == 6 and entry['extra_item'] for entry in entries))
        known = {tuple(prizes['items']) for prizes in sets}
        self.assertTrue(all(tuple(entry['items']) in known for entry in entries))

    def test_the_config_gets_daily_boards_and_texts_without_changing_the_cached_one(self):
        for language, come_back, description in (
                ('es', '¡Vuelve mañana para ver premios nuevos!', '¡Cada día hay premios nuevos!'),
                ('en', 'Come back tomorrow for new prizes!', 'New prizes are introduced every day!'),
                ('pt-BR', 'Volte amanhã para novos prêmios!', 'Novos prêmios chegam todo dia!')):
            with self.subTest(language=language):
                original = get_game_config(language)
                before = (original['darts_items'], texts(original))
                config = with_daily_darts(original, TODAY)
                self.assertEqual(config['darts_items'][DAYS_BACK]['start_date'], '2026-11-14 00:00:00')
                self.assertEqual(texts(config)['DARTS_COME_BACK'], come_back)
                self.assertIn(description, texts(config)['TITLE_DESCRIPTION_DARTS'])
                self.assertEqual((original['darts_items'], texts(original)), before)

    def test_off_leaves_the_config_as_it_was(self):
        original = get_game_config('es')
        with patch.dict(os.environ, {'SE_DAILY_DARTS': 'off'}):
            self.assertIs(with_daily_darts(original, TODAY), original)


class DartsCommands(unittest.TestCase):
    def save(self):
        return {'playerInfo': {'cash': 100},
                'privateState': {'timeStampDartsReset': 0, 'timeStampDartsNewFree': 0, 'dartsBalloonsShot': [3],
                                 'dartsRandomSeed': 0, 'dartsHasFree': False, 'dartsGotExtra': True, 'gifts': [0, 0]}}

    def test_a_new_board_starts_clean_with_a_free_dart(self):
        save = self.save()
        apply_darts_command(save, Constant.CMD_DARTS_RESET, [4321], 1000)
        state = save['privateState']
        self.assertEqual((state['timeStampDartsReset'], state['timeStampDartsNewFree'], state['dartsBalloonsShot'],
                          state['dartsRandomSeed'], state['dartsHasFree'], state['dartsGotExtra']),
                         (1000, 1000, [], 4321, True, False))

    def test_free_dart_then_a_paid_one_and_the_prizes_go_to_storage(self):
        save = self.save()
        apply_darts_command(save, Constant.CMD_DARTS_NEW_FREE, [], 2000)
        self.assertTrue(save['privateState']['dartsHasFree'])
        apply_darts_command(save, Constant.CMD_DARTS_SHOOT_BALLOON, [7, 0, 0], 2001)
        self.assertEqual((save['playerInfo']['cash'], save['privateState']['dartsHasFree']), (100, False))
        apply_darts_command(save, Constant.CMD_DARTS_SHOOT_BALLOON, [12, 1, 1], 2002, dart_cost=20)
        self.assertEqual(save['playerInfo']['cash'], 80)
        self.assertEqual(save['privateState']['dartsBalloonsShot'], [3, 7, 12])
        self.assertTrue(save['privateState']['dartsGotExtra'])
        apply_darts_command(save, Constant.CMD_STORE_ADD_ITEMS, ['[5]'], 2003)
        apply_darts_command(save, Constant.CMD_STORE_ADD_ITEMS, ['[5]'], 2004)
        self.assertEqual(save['privateState']['gifts'][5], 2)

    def test_the_command_handler_runs_them_only_when_on(self):
        import command
        save = self.save()
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', Constant.CMD_DARTS_SHOOT_BALLOON, [9, 1, 0])
            self.assertEqual(save['privateState']['dartsBalloonsShot'], [3, 9])
            self.assertEqual(save['playerInfo']['cash'], 100 - get_game_config()['globals']['DART_COST_CASH'])
            with patch.dict(os.environ, {'SE_DAILY_DARTS': 'off'}):
                command.do_command('u', Constant.CMD_DARTS_SHOOT_BALLOON, [10, 1, 0])
            self.assertEqual(save['privateState']['dartsBalloonsShot'], [3, 9])


if __name__ == '__main__':
    unittest.main()
