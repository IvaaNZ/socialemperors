import unittest
from pathlib import Path

from swf_abc import Abc, AbcError, disassemble
from swf_coop import (COOP_UNITS, add_coop, add_coop_to_abc, add_quest_teams, add_quest_teams_to_abc)
from swf_duel_bridge import DO_ABC
from swf_localization import decode_swf, iter_tags

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    return next(Abc(payload[payload.index(b'\0', 4) + 1:]) for code, payload, _ in iter_tags(body, header_length)
                if code == DO_ABC)


class QuestTeams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = abc_of(MOVIE.read_bytes())
        cls.abc = abc_of(add_quest_teams(MOVIE.read_bytes()))

    def go_to_island(self, abc):
        return disassemble(abc, abc.body_of(abc.method_of('PopupQuestsManager', 'goToIsland'))['code'])

    def test_every_island_goes_to_the_team_selection(self):
        before, after = self.go_to_island(self.original), self.go_to_island(self.abc)
        self.assertIn('QUESTS_WITH_TEAMS', [str(op[2]) for op in before if len(op) > 2])
        self.assertNotIn('QUESTS_WITH_TEAMS', [str(op[2]) for op in after if len(op) > 2])
        at = next(i for i, o in enumerate(before) if len(o) > 2 and str(o[2]) == 'QUESTS_WITH_TEAMS')
        start = before[at - 1][0]  # getlex Config
        jump = next(op for op in after if op[0] == start)
        self.assertEqual(jump[1], 'jump')
        branch = next(o for o in before[at:] if o[1] == 'ifne')
        self.assertEqual(str(jump[2]), str(branch[2]))  # the selection branch, as before when the island was listed
        self.assertEqual(len(self.abc.body_of(self.abc.method_of('PopupQuestsManager', 'goToIsland'))['code']),
                         len(self.original.body_of(self.original.method_of('PopupQuestsManager', 'goToIsland'))['code']))

    def test_it_is_done_once(self):
        with self.assertRaises(AbcError):
            add_quest_teams_to_abc(self.abc)


class Coop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_coop(add_quest_teams(MOVIE.read_bytes())))

    def ops(self, cls, method):
        return disassemble(self.abc, self.abc.body_of(self.abc.method_of(cls, method))['code'])

    def test_the_page_is_asked_before_going_to_an_island(self):
        first = self.ops('PopupQuestsManager', 'goToIsland')[:5]
        self.assertEqual([op[1] for op in first], ['getlocal0', 'getlocal1', 'callproperty', 'iffalse', 'returnvoid'])
        self.assertIn('__seAsk', str(first[2][2]))
        self.assertIn("'seCoopChoose'", [str(op[2]) for op in self.ops('PopupQuestsManager', '__seAsk') if len(op) > 2])

    def test_a_clan_team_goes_to_the_page_and_takes_at_most_ten(self):
        taken = [str(op[2]) for op in self.ops('PopupQuestsManager', '__seTaken') if len(op) > 2]
        self.assertIn("'seCoopPicked'", taken)
        self.assertIn('closeTeamWindow 0', taken)
        limit = self.ops('SelectionTeamWindow', '__seLimit')
        self.assertIn(str(COOP_UNITS), [str(op[2]) for op in limit if op[1] == 'pushbyte'])
        self.assertIn('__seLimit', str(self.ops('SelectionTeamWindow', 'onThumbUnitClick')[1][2]))

    def test_the_page_can_answer_and_open_a_guests_team(self):
        pick = [str(op[2]) for op in self.ops('Base', '__seCoopPick') if len(op) > 2]
        self.assertIn('SELECTION_MODE_QUEST', pick)
        register = [str(op[2]) for op in self.ops('Base', '__registerCoop') if len(op) > 2]
        self.assertIn("'seCoopGo'", register)
        self.assertIn("'seCoopPick'", register)

    def test_the_raid_sets_sail_with_the_games_own_loading(self):
        sail = [str(op[2]) for op in self.ops('Base', '__seCoopSail') if len(op) > 2]
        self.assertIn('questIDtoLoad', sail)
        self.assertIn('loadQuestMapWithSelectedArmy 1', sail)  # it counts the list of unit ids first

    def test_the_guests_units_are_listed_and_ordered_without_the_hosts_selection(self):
        units = [str(op[2]) for op in self.ops('Base', '__seCoopUnits') if len(op) > 2]
        for name in ('arPlayerIsoFightingElements', 'IsoUnit', 'localToGlobal 1', 'iID', 'iHealth', 'maxLife'):
            self.assertIn(name, units)
        order = [str(op[2]) for op in self.ops('Base', '__seCoopOrder') if len(op) > 2]
        for name in ('globalToLocal 1', 'PixelToTile 2', 'getNearestEnemy 4', 'IA_Attack 1', 'IA_Move 2'):
            self.assertIn(name, order)
        self.assertNotIn('seleccionarElemento 1', order)
        register = [str(op[2]) for op in self.ops('Base', '__registerCoop') if len(op) > 2]
        for callback in ("'seCoopSail'", "'seCoopUnits'", "'seCoopOrder'"):
            self.assertIn(callback, register)

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_coop_to_abc(self.abc)


if __name__ == '__main__':
    unittest.main()
