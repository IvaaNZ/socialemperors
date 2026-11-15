import json
import types
import unittest
from unittest.mock import patch

import world
from constants import Constant
from get_game_config import get_game_config

CONFIG = get_game_config()
NOW = 10 ** 9


def village(coins=100000, cash=100, tutorial=1):
    return {'playerInfo': {'cash': cash, 'completed_tutorial': tutorial, 'map_names': ['Reino']},
            'maps': [{'coins': coins, 'xp': 0, 'level': 30, 'race': 'h'}],
            'privateState': {'gifts': []}}


class World(unittest.TestCase):
    def setUp(self):
        self.saves = {'a': village(), 'b': village(), 'c': village()}
        self.saved = []
        fake = types.SimpleNamespace(session=lambda userid: self.saves.get(userid),
                                     save_session=lambda userid: self.saved.append(userid))
        for p in (patch.object(world, '_sessions', return_value=fake),
                  patch.object(world, '_eligible', lambda: set(self.saves))):
            p.start()
            self.addCleanup(p.stop)

    def run_world(self, userid, cmd, args, now=NOW):
        return world.apply_world_command(userid, self.saves[userid], cmd, args, CONFIG, now)

    @staticmethod
    def result(victim, win=1, gold=5000, xp=300, lost=5000, townhall=0):
        return json.dumps({'attacker': {}, 'victim': {'user_id': victim}, 'resources': {'g': gold, 'x': xp},
                           'townhall_gold': townhall,
                           'resources_victim': {'g': lost}, 'attacker_units': [], 'victim_units': [], 'win': win})

    def position(self, userid):
        return self.saves[userid]['privateState']['worldPosition']

    def test_players_share_an_island_and_empty_territories_stay_open(self):
        data = world.continent('a')
        self.assertEqual(len(data['continent']), 8)
        players = [entry['user_id'] for entry in data['continent'] if 'user_id' in entry]
        self.assertEqual(sorted(players), ['a', 'b', 'c'])
        self.assertEqual(data['continent'][0]['nivel'], world.MAX_LEVEL)

    def test_players_who_did_not_finish_the_tutorial_or_reach_level_6_are_not_shown(self):
        self.saves['c']['playerInfo']['completed_tutorial'] = 0
        self.saves['d'] = village()
        self.saves['d']['maps'][0]['level'] = world.EXPLORER_LEVEL - 1
        players = [entry['user_id'] for entry in world.continent('a')['continent'] if 'user_id' in entry]
        self.assertEqual(sorted(players), ['a', 'b'])

    def test_an_attack_takes_capped_gold_from_the_victim_and_both_keep_it(self):
        world.continent('a')
        self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['b'])
        self.run_world('a', Constant.CMD_END_ATTACK, [self.result('b', gold=999999, lost=999999)])
        loot = 100000 * world.LOOT_PERCENT // 100
        self.assertEqual(self.saves['b']['maps'][0]['coins'], 100000 - loot)
        self.assertEqual(self.saves['a']['maps'][0]['coins'], 100000 + CONFIG['globals']['MAX_GOLD_ASSAULT'])
        self.assertEqual(self.saves['a']['maps'][0]['xp'], 300)
        received = self.saves['b']['privateState']['attacksReceived'][-1]
        self.assertTrue(received['viewPending'])
        # PopupAssaultHistory reads the battle from "description", with the other player as "oponent"
        self.assertEqual(received['description']['oponent']['user_id'], 'a')
        self.assertEqual(received['description']['resources_victim'], {'g': loot})
        self.assertEqual((received['description']['win'], received['attackerWon']), (0, True))  # the victim lost
        self.assertEqual(self.saves['a']['privateState']['attacksSent'][-1]['description']['oponent']['name'], 'Reino')
        self.assertIn('b', self.saved)
        self.assertEqual(self.saves['a']['maps'][0]['universAttackWin'], [self.position('b')])

    def test_a_result_needs_its_attack_and_a_retreat_costs_the_victim_nothing(self):
        world.continent('a')
        with self.assertRaises(world.WorldError):
            self.run_world('a', Constant.CMD_END_ATTACK, [self.result('b')])
        self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['c'])
        self.run_world('a', Constant.CMD_END_ATTACK, [self.result('c', win=0, gold=350, lost=0)])
        # the gold of what was destroyed, as the game shows; the victim keeps its gold
        self.assertEqual((self.saves['a']['maps'][0]['coins'], self.saves['c']['maps'][0]['coins']), (100350, 100000))

    def test_attack_limits_packs_and_the_same_player(self):
        self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['b'])
        with self.assertRaises(world.WorldError):  # the same player within 4 hours
            self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['b'], NOW + 60)
        self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['c'], NOW + 60)
        self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['x'], NOW + 120)
        with self.assertRaises(world.WorldError):  # 3 every 6 hours
            self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['y'], NOW + 180)
        self.run_world('a', Constant.CMD_BUY_ATTACKS_PACK, [''])
        self.assertEqual(self.saves['a']['playerInfo']['cash'], 100 - world.COST_BUY_ATTACK)
        self.run_world('a', Constant.CMD_ATTACK_PLAYER, ['y'], NOW + 180)
        self.assertEqual(self.saves['a']['privateState']['attacksPack'], world.ATTACKS_PACK_SIZE - 1)

    def test_a_victim_who_just_lost_is_protected(self):
        world.continent('a')
        for attacker in ('a', 'c'):
            self.run_world(attacker, Constant.CMD_ATTACK_PLAYER, ['b'])
            self.run_world(attacker, Constant.CMD_END_ATTACK, [self.result('b')])
        self.assertEqual(self.saves['b']['maps'][0]['coins'], 100000 - 5000)

    def test_seven_territories_move_to_the_next_island_and_its_reward_is_given_once(self):
        world.continent('a')
        others = {self.position('b'), self.position('c'), self.position('a')}
        for position in [p for p in range(8) if p not in others]:
            self.run_world('a', Constant.CMD_PVP_BUY_TERRITORY, [position])
        for victim in ('b', 'c'):
            self.run_world('a', Constant.CMD_ATTACK_PLAYER, [victim])
            self.run_world('a', Constant.CMD_END_ATTACK, [self.result(victim, gold=0, lost=0)])
        state = self.saves['a']['privateState']
        self.assertEqual((state['worldLevel'], state['worldChange']), (world.MAX_LEVEL - 1, 1))
        self.assertEqual(self.saves['a']['maps'][0]['universAttackWin'], [])
        reward = next(r for r in CONFIG['level_ranking_reward'] if r['level'] == 49)
        args = [49, reward['cash'], json.dumps(reward['units'])]
        self.run_world('a', Constant.CMD_APPLY_REWARDS_RANKING, args)
        with self.assertRaises(world.WorldError):  # only once
            self.run_world('a', Constant.CMD_APPLY_REWARDS_RANKING, args)
        with self.assertRaises(world.WorldError):  # an island not reached yet
            self.run_world('a', Constant.CMD_APPLY_REWARDS_RANKING, [48, 1, '{}'])

    def test_a_players_territory_is_bought_without_loot_but_not_twice_nor_ones_own(self):
        world.continent('a')
        self.run_world('a', Constant.CMD_PVP_BUY_TERRITORY, [self.position('b')])
        self.assertEqual(self.saves['a']['playerInfo']['cash'], 100 - 5)
        self.assertEqual(self.saves['b']['maps'][0]['coins'], 100000)
        for position in (self.position('b'), self.position('a')):
            with self.assertRaises(world.WorldError):
                self.run_world('a', Constant.CMD_PVP_BUY_TERRITORY, [position])

    def test_spyings_history_and_relocation(self):
        for i in range(3):
            self.run_world('a', Constant.CMD_SPY, ['b'], NOW + i)
        with self.assertRaises(world.WorldError):
            self.run_world('a', Constant.CMD_SPY, ['b'], NOW + 10)
        self.saves['a']['privateState']['attacksReceived'] = [{'viewPending': True}]
        self.run_world('a', Constant.CMD_CLEAN_ATTACKS, [])
        self.assertNotIn('viewPending', self.saves['a']['privateState']['attacksReceived'][0])
        world.continent('a')
        self.saves['a']['maps'][0]['universAttackWin'] = [3]
        self.run_world('a', Constant.CMD_RESET_POSITION_UNIVERSE, [])
        self.assertEqual(self.saves['a']['maps'][0]['universAttackWin'], [])
