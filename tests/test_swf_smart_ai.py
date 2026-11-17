import unittest
from pathlib import Path

from swf_abc import Abc, AbcError, disassemble
from swf_duel_bridge import DO_ABC
from swf_localization import decode_swf, iter_tags
from swf_smart_ai import HEALERS, HELP_METHOD, RETREAT_METHOD, RETREATED_SLOT, add_smart_ai, add_smart_ai_to_abc

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_of(data):
    body, header_length = decode_swf(data)
    return next(Abc(payload[payload.index(b'\0', 4) + 1:]) for code, payload, _ in iter_tags(body, header_length)
                if code == DO_ABC)


class SmartAI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.abc = abc_of(add_smart_ai(MOVIE.read_bytes()))

    def ops(self, cls, method):
        return disassemble(self.abc, self.abc.body_of(self.abc.method_of(cls, method))['code'])

    def names(self, cls, method):
        return [str(op[2]) for op in self.ops(cls, method) if len(op) > 2]

    def test_the_target_search_keeps_the_games_rules_and_weighs_every_candidate(self):
        names = self.names('IsoEngine', 'getNearestTarget')
        for name in ('bucleNearestUnits 3', 'fCheckNearestTarget', 'AGGRO_RANGE', 'iHealth', 'maxLife',
                     'IsoBuilding', 'TargetElement') + HEALERS:
            self.assertIn(name, names)
        self.assertNotIn('sortOn 2', names)  # the near ones come sorted; every one in range is weighed
        self.assertIn('call', [op[1] for op in self.ops('IsoEngine', 'getNearestTarget')])

    def test_allies_help_unless_a_collective_ai_leads_them(self):
        names = self.names('IA', HELP_METHOD)
        for name in ('ciaCollectiveIA', 'STATE_FORCE_MOVE', 'uiAttack', 'distance 2', 'IA_Attack 1'):
            self.assertIn(name, names)
        first = self.ops('IA', 'NearbyAllyAttacked')[:4]
        self.assertEqual(first[3][1], 'callpropvoid')
        self.assertIn(HELP_METHOD, str(first[3][2]))

    def test_only_the_computers_wounded_fall_back_once(self):
        names = self.names('IA', RETREAT_METHOD)
        for name in ('PLAYER_SELF', RETREATED_SLOT, 'iHealth', 'maxLife', 'IA_Move 2', 'STATE_FORCE_MOVE'):
            self.assertIn(name, names)
        first = [op[1] for op in self.ops('IA', 'BeingAttacked')[:5]]
        self.assertEqual(first, ['getlocal0', 'getlocal1', 'callproperty', 'iffalse', 'returnvoid'])

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_smart_ai_to_abc(self.abc)


if __name__ == '__main__':
    unittest.main()
