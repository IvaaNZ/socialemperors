import json
import random
import unittest
from pathlib import Path

from soul_mixer import BUILDING, LEGACY_DRAGONS, MixerError, SoulMixer, Tables, revision
from swf_abc import AbcError, disassemble
from swf_soul_mixer import CALL, LIMIT_CALL, LIMIT_METHOD, METHOD, add_soul_mixer, add_soul_mixer_to_abc
from tests.test_swf_coop import MOVIE, abc_of

# Made-up units: id -> (rank, seconds)
UNITS = {101: (10, 3600), 102: (20, 7200), 103: (30, 10800), 104: (40, 14400), 105: (50, 18000),
         106: (60, 21600), 107: (70, 25200), 2048: (300, 50000), 900: (410, 90000), 901: (450, 99000)}
ITEMS = {unit: {'id': str(unit), 'type': 'u', 'race': 'h'} for unit in UNITS}
ITEMS.update({525: {'id': '525', 'type': 'u', 'race': 't'}, 501: {'id': '501', 'type': 'u', 'race': 'h'},
              BUILDING: {'id': str(BUILDING), 'type': 'b', 'race': 'h'}})
ITEMS[107]['units_limit'] = '1'


def tables():
    return Tables([(unit, rank, seconds) for unit, (rank, seconds) in UNITS.items()],
                  [(1, 0), (2, 0), (3, 0)], 8)


def village(units, level=30, cash=100, mixer=True):
    items = [[unit, 10 + i, 10, 0, 0, 0] for i, unit in enumerate(units)]
    if mixer:
        items.append([BUILDING, 50, 50, 0, 0, 0, [], {}])
    return {'playerInfo': {'cash': cash}, 'privateState': {'gifts': [0, 0]},
            'maps': [{'race': 'h', 'level': level, 'items': items}]}


class Rules(unittest.TestCase):
    def mixer(self, save, now=1000, seed=1):
        return SoulMixer(save, tables(), ITEMS, now=now, rand=random.Random(seed))

    def test_only_the_players_own_mixable_units_count(self):
        save = village([101, 101, 102, 525, 501])
        self.assertEqual(self.mixer(save).eligible(save['maps'][0]), {101: 2, 102: 1})

    def test_the_result_follows_the_original_roll_and_never_is_a_parent(self):
        save = village([103, 105])
        for seed in range(40):
            preview = self.mixer(save, seed=seed).choose(103, 105)
            # 30 % of 30 + 70 % of 50 = 44, plus 0 to 11: a unit ranked 44 to 55, the parents excluded
            self.assertIn(preview['unit'], (106,))
            self.assertNotIn(preview['unit'], (103, 105))
        top = village([900, 901])
        for seed in range(20):
            self.assertIn(self.mixer(top, seed=seed).choose(900, 901)['unit'], UNITS)  # a random top unit

    def test_two_of_the_same_kind_need_two_of_them(self):
        with self.assertRaises(MixerError) as one:
            self.mixer(village([101])).choose(101, 101)
        self.assertEqual(one.exception.code, 'not_owned')
        self.assertTrue(self.mixer(village([101, 101])).choose(101, 101))

    def test_no_mixer_or_too_low_a_level(self):
        with self.assertRaises(MixerError) as none:
            self.mixer(village([101, 102], mixer=False)).choose(101, 102)
        self.assertEqual(none.exception.code, 'no_mixer')
        with self.assertRaises(MixerError) as low:
            self.mixer(village([101, 102], level=5)).choose(101, 102)
        self.assertEqual((low.exception.code, low.exception.values), ('level', {'level': 8}))

    def test_the_old_dragons_wait_for_level_20(self):
        save = village([2048, 101], level=15)
        self.assertNotIn(2048, self.mixer(save).eligible(save['maps'][0]))
        self.assertIn(2048, LEGACY_DRAGONS)
        save = village([2048, 101], level=20)
        self.assertIn(2048, self.mixer(save).eligible(save['maps'][0]))

    def test_power_ups_move_the_result_up_and_are_paid_at_the_start(self):
        save = village([101, 102], cash=5)
        mixer = self.mixer(save)
        first = mixer.choose(101, 102)['unit']
        mixer.power_up()
        second = mixer.preview()['unit']
        self.assertGreater(UNITS[second][0], UNITS[first][0])
        mixer.power_up()  # 1 + 2 cash so far
        with self.assertRaises(MixerError) as poor:
            mixer.power_up()  # 1 + 2 + 3 = 6 > 5
        self.assertEqual(poor.exception.code, 'cash')
        self.assertEqual(save['playerInfo']['cash'], 5)  # nothing paid yet
        mixer.start()
        self.assertEqual(save['playerInfo']['cash'], 2)

    def test_start_takes_the_two_parents_for_good_and_the_unit_goes_to_the_gifts(self):
        save = village([101, 102, 103])
        mixer = self.mixer(save, now=1000)
        unit = mixer.choose(101, 102)['unit']
        mixer.start()
        ids = [row[0] for row in save['maps'][0]['items']]
        self.assertNotIn(101, ids)
        self.assertNotIn(102, ids)
        self.assertIn(103, ids)
        self.assertEqual(revision(save), 'sm1')
        with self.assertRaises(MixerError) as busy:
            mixer.choose(103, 103)
        self.assertEqual(busy.exception.code, 'busy')
        with self.assertRaises(MixerError) as early:
            mixer.collect()
        self.assertEqual(early.exception.code, 'not_ready')
        later = self.mixer(save, now=1000 + UNITS[unit][1])
        self.assertEqual(later.remaining(), 0)
        self.assertEqual(later.collect(), unit)
        self.assertEqual(save['privateState']['gifts'][unit], 1)
        self.assertIsNone(later.mix())
        self.assertEqual(revision(save), 'sm2')
        with self.assertRaises(MixerError):
            later.collect()  # only once

    def test_finishing_early_costs_a_cash_an_hour_started(self):
        save = village([101, 102], cash=50)
        mixer = self.mixer(save, now=1000)
        unit = mixer.choose(101, 102)['unit']
        mixer.start()
        waiting = self.mixer(save, now=1000 + UNITS[unit][1] - 3601)  # one hour and one second left
        self.assertEqual(waiting.speed_up_price(), 2)
        self.assertEqual(waiting.speed_up(), 2)
        self.assertEqual(save['playerInfo']['cash'], 48)
        self.assertEqual(waiting.remaining(), 0)
        with self.assertRaises(MixerError) as ready:
            waiting.speed_up()
        self.assertEqual(ready.exception.code, 'ready')

    def test_a_parent_that_left_stops_the_start(self):
        save = village([101, 102])
        mixer = self.mixer(save)
        mixer.choose(101, 102)
        save['maps'][0]['items'] = [row for row in save['maps'][0]['items'] if row[0] != 102]
        with self.assertRaises(MixerError) as gone:
            mixer.start()
        self.assertEqual(gone.exception.code, 'parents_gone')
        self.assertIn(101, [row[0] for row in save['maps'][0]['items']])

    def test_the_results_units_limit(self):
        save = village([105, 106, 107])
        mixer = self.mixer(save)
        mixer.choose(105, 106)
        mixer.state['preview']['unit'] = 107  # already has the only one allowed
        with self.assertRaises(MixerError) as limit:
            mixer.start()
        self.assertEqual(limit.exception.code, 'limit')


class TheTablesFile(unittest.TestCase):
    def test_every_unit_of_the_file_is_a_unit_of_the_game(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            from get_game_config import get_game_config
        items = {int(item['id']): item for item in get_game_config()['items']}
        loaded = Tables.load(items)
        data = json.loads(Path('config/soulmixer_wiki.json').read_text(encoding='utf-8'))
        self.assertEqual(len(loaded.units), len(data['units']))
        self.assertEqual(loaded.min_level, 8)
        self.assertEqual(loaded.powerup_price(0), 1)
        self.assertEqual(loaded.powerup_price(99), loaded.powerups[-1][0])


class TheGame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_soul_mixer(MOVIE.read_bytes()))

    def test_selecting_calls_the_page_for_a_soul_mixer(self):
        selection = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', 'seleccionarElemento'))['code'])
        self.assertEqual([op[1] for op in selection[:3]], ['getlocal0', 'getlocal1', 'callpropvoid'])
        self.assertEqual(str(selection[2][2]), METHOD + ' 1')
        method = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', METHOD))['code'])
        names = [str(op[2]) for op in method]
        self.assertIn(repr(CALL), names)
        self.assertIn(str(BUILDING), names)
        self.assertIn('gameMode', names)

    def test_a_second_soul_mixer_is_not_placed(self):
        click = disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', 'mouseUsed'))['code'])
        self.assertEqual([op[1] for op in click[:4]], ['getlocal0', 'callproperty', 'iffalse', 'returnvoid'])
        self.assertEqual(str(click[1][2]), LIMIT_METHOD + ' 0')
        names = [str(op[2]) for op in disassemble(self.abc, self.abc.body_of(self.abc.method_of('Base', LIMIT_METHOD))['code'])]
        for name in ('STATE_CONSTRUCT', 'checkUnitLimit 1', 'removeCursor 0', 'STATE_INQUIRE', 'alert 1', repr(LIMIT_CALL)):
            self.assertIn(name, names)

    def test_it_is_done_once(self):
        with self.assertRaises(AbcError):
            add_soul_mixer_to_abc(self.abc)


if __name__ == '__main__':
    unittest.main()
