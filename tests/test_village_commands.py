import os
import unittest
from unittest.mock import patch

from constants import Constant
from get_game_config import get_game_config
from village_commands import (VillageCommandError, apply_social_command, apply_village_command, grant_level_mana, grant_missed_level_mana,
                              market_price)

CONFIG = get_game_config()
GLOBALS = CONFIG['globals']


def village(level=40):
    return {'playerInfo': {'cash': 100},
            'maps': [{'coins': 50000, 'wood': 1000, 'stone': 1000, 'food': 1000, 'level': level, 'xp': 0, 'resourcesTraded': {},
                      'increasedPopulation': 0, 'items': []}],
            'privateState': {'mana': 0, 'magics': {}, 'unlockedEarlyBuildings': {}, 'gifts': [0, 0, 0, 2]}}


def spell(spell_id=2):
    return next(entry for entry in CONFIG['magics'] if entry['id'] == spell_id)


class Magic(unittest.TestCase):
    def test_learning_a_spell_charges_its_price_and_brings_its_mana(self):
        save = village()
        fire = spell(2)
        apply_village_command(save, Constant.CMD_BUY_MAGIC, [2, 0, 1], CONFIG)
        self.assertEqual(save['playerInfo']['cash'], 100 - fire['cash'])
        self.assertEqual((save['privateState']['magics'], save['privateState']['mana']), ({'2': 0}, fire['mana']))
        save = village()
        apply_village_command(save, Constant.CMD_BUY_MAGIC, [2, 0, 0], CONFIG)
        self.assertEqual((save['maps'][0]['coins'], save['playerInfo']['cash']), (50000 - fire['gold'], 100))

    def test_casting_costs_mana_and_counts_uses(self):
        save = village()
        save['privateState'].update(mana=12, magics={'2': 0})
        apply_village_command(save, Constant.CMD_USE_MAGIC, [2], CONFIG)
        apply_village_command(save, Constant.CMD_USE_MAGIC, [2], CONFIG)
        self.assertEqual((save['privateState']['mana'], save['privateState']['magics']), (12 - 2 * spell(2)['mana'], {'2': 2}))
        apply_village_command(save, Constant.CMD_USE_MAGIC, [2], CONFIG)
        self.assertEqual(save['privateState']['mana'], 0)  # never below zero
        with self.assertRaises(VillageCommandError):
            apply_village_command(save, Constant.CMD_USE_MAGIC, [999], CONFIG)

    def test_buying_mana_with_cash_or_gold(self):
        save = village()
        apply_village_command(save, Constant.CMD_BUY_MANA, [0, 1], CONFIG)
        apply_village_command(save, Constant.CMD_BUY_MANA, [0, 0], CONFIG)
        self.assertEqual(save['privateState']['mana'], 2 * GLOBALS['MANA_PER_PURCHASE'])
        self.assertEqual(save['playerInfo']['cash'], 100 - GLOBALS['COST_MANA_CASH'])
        self.assertEqual(save['maps'][0]['coins'], 50000 - GLOBALS['COST_MANA_GOLD'])

    def test_level_up_mana_from_the_games_start_level(self):
        start, per_level = GLOBALS['START_LEVEL_MANA_REWARD'], GLOBALS['MANA_REWARD_PER_LEVEL']
        save = village(level=start - 2)
        self.assertEqual(grant_level_mana(save, start - 2, start - 1, GLOBALS), 0)
        self.assertEqual(grant_level_mana(save, start - 1, start + 1, GLOBALS), 2 * per_level)
        self.assertEqual(save['privateState']['manaRewardLevel'], start + 1)

    def test_players_already_past_those_levels_get_their_mana_once(self):
        start, per_level = GLOBALS['START_LEVEL_MANA_REWARD'], GLOBALS['MANA_REWARD_PER_LEVEL']
        save = village(level=99)
        self.assertEqual(grant_missed_level_mana(save, GLOBALS), (99 - start + 1) * per_level)
        self.assertEqual(grant_missed_level_mana(save, GLOBALS), 0)
        self.assertEqual(save['privateState']['mana'], (99 - start + 1) * per_level)


class Market(unittest.TestCase):
    def test_buying_raises_the_price_and_selling_pays_three_quarters(self):
        save = village()
        first = market_price(GLOBALS, 'w', 1000, 0, False)
        self.assertEqual(first, GLOBALS['MARKET_BASE_COSTS']['w'] * 10)
        apply_village_command(save, Constant.CMD_TRADE_RESOURCE, [0, 'w', 0, 1000], CONFIG)
        town = save['maps'][0]
        self.assertEqual((town['wood'], town['coins'], town['resourcesTraded']), (2000, 50000 - first, {'w': 1}))
        second = market_price(GLOBALS, 'w', 1000, 1, False)
        self.assertGreater(second, first)
        sale = market_price(GLOBALS, 'w', 1000, 1, True)
        self.assertEqual(sale, round(second * GLOBALS['MARKET_SELL_PERCENTAGE']))
        apply_village_command(save, Constant.CMD_TRADE_RESOURCE, [0, 'w', 1, 1000], CONFIG)
        self.assertEqual((town['wood'], town['coins'], town['resourcesTraded']), (1000, 50000 - first + sale, {'w': 0}))
        with self.assertRaises(VillageCommandError):
            apply_village_command(save, Constant.CMD_TRADE_RESOURCE, [0, 'x', 0, 10], CONFIG)

    def test_twenty_trades_per_market_period_and_the_fields_the_game_reads(self):
        from village_commands import MARKET_MAX_NUM_TRADES, fill_map_defaults
        save = village()
        self.assertTrue(fill_map_defaults(save))
        self.assertEqual((save['maps'][0]['numTradesDone'], save['maps'][0]['timestampLastTrade']), (0, 0))
        self.assertFalse(fill_map_defaults(save))
        start = 10 ** 9
        for _ in range(MARKET_MAX_NUM_TRADES):
            apply_village_command(save, Constant.CMD_TRADE_RESOURCE, [0, 'f', 1, 10], CONFIG, start)
        self.assertEqual(save['maps'][0]['timestampLastTrade'], start)
        with self.assertRaises(VillageCommandError):
            apply_village_command(save, Constant.CMD_TRADE_RESOURCE, [0, 'f', 1, 10], CONFIG, start + 60)
        later = start + GLOBALS['MARKET_PERIOD_HOURS'] * 3600 + 1
        apply_village_command(save, Constant.CMD_TRADE_RESOURCE, [0, 'f', 1, 10], CONFIG, later)
        self.assertEqual((save['maps'][0]['numTradesDone'], save['maps'][0]['timestampLastTrade']), (1, later))

    def test_the_price_step_stays_within_the_games_limits(self):
        save = village()
        save['maps'][0]['resourcesTraded'] = {'f': -GLOBALS['MARKET_MAX_DECREMENTS']}
        apply_village_command(save, Constant.CMD_TRADE_RESOURCE, [0, 'f', 1, 100], CONFIG)
        self.assertEqual(save['maps'][0]['resourcesTraded']['f'], -GLOBALS['MARKET_MAX_DECREMENTS'])


class BuildingsAndPopulation(unittest.TestCase):
    def test_an_early_unlock_costs_a_third_of_the_level_in_cash(self):
        item = next(entry for entry in CONFIG['items'] if int(entry.get('min_level') or 0) == 10)
        save = village()
        apply_village_command(save, Constant.CMD_UNLOCK_BUILDING, [str(item['id'])], CONFIG)
        self.assertEqual(save['playerInfo']['cash'], 100 - 4)
        self.assertEqual(save['privateState']['unlockedEarlyBuildings'], {str(item['id']): True})

    def test_population_increase(self):
        save = village()
        apply_village_command(save, Constant.CMD_INCREASE_POPULATION, [0], CONFIG)
        self.assertEqual(save['maps'][0]['increasedPopulation'], 1)


class Dispatcher(unittest.TestCase):
    def run_command(self, save, cmd, args):
        import command
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', cmd, args)

    def test_stored_items_are_placed_and_sold_like_gifts(self):
        save = village()
        self.run_command(save, Constant.CMD_PLACE_STORED_ITEM, [3, 10, 12, 0, 0])
        self.assertEqual(save['privateState']['gifts'], [0, 0, 0, 1])
        from get_game_config import get_attribute_from_item_id
        self.assertEqual(save['maps'][0]['xp'], int(get_attribute_from_item_id(3, 'xp') or 0))  # as the game shows
        self.assertEqual(save['maps'][0]['items'][0][:3], [3, 10, 12])
        self.run_command(save, Constant.CMD_SELL_STORED, [3, 0])
        self.assertEqual(save['privateState']['gifts'], [])
        self.run_command(save, Constant.CMD_SELL_STORED, [3, 0])  # nothing left: no error, nothing changes
        self.assertEqual(save['privateState']['gifts'], [])

    def test_a_rejected_command_leaves_the_save_and_off_ignores_them(self):
        save = village()
        self.run_command(save, Constant.CMD_USE_MAGIC, [999])
        self.assertEqual(save['privateState']['magics'], {})
        self.run_command(save, Constant.CMD_BUY_MANA, [0, 1])
        self.assertEqual(save['privateState']['mana'], GLOBALS['MANA_PER_PURCHASE'])
        with patch.dict(os.environ, {'SE_VILLAGE_COMMANDS': 'off'}):
            self.run_command(save, Constant.CMD_BUY_MANA, [0, 1])
            self.run_command(save, Constant.CMD_PLACE_STORED_ITEM, [3, 1, 1, 0, 0])
        self.assertEqual(save['privateState']['mana'], GLOBALS['MANA_PER_PURCHASE'])
        self.assertEqual(save['privateState']['gifts'], [0, 0, 0, 2])

    def test_a_unit_paid_with_cash_is_placed_charged_and_gives_xp(self):
        import command
        unit = next(entry for entry in CONFIG['items'] if int(entry.get('cost_unit_cash') or 0) > 0
                    and entry.get('type') == 'u' and int(entry.get('xp') or 0) > 0)
        save = village()
        save['playerInfo']['cash'] = 1000
        save['maps'][0]['xp'] = 0
        with patch.object(command, 'session', return_value=save), patch.object(command, 'save_session'):
            command.command('u', {'ts': 0, 'first_number': 0, 'accessToken': '', 'tries': 0, 'publishActions': 0,
                                  'commands': [{'cmd': Constant.CMD_BUY_UNIT_WITH_CASH, 'args': [unit['id'], 30, 31, 0, 0]}]})
        self.assertEqual(save['playerInfo']['cash'], 1000 - int(unit['cost_unit_cash']))
        self.assertEqual(save['maps'][0]['xp'], int(unit['xp']))
        self.assertEqual(save['maps'][0]['items'][0][:3], [int(unit['id']), 30, 31])

    def test_a_hero_bought_without_an_altar_goes_to_the_storage_only(self):
        import command
        unit = next(entry for entry in CONFIG['items'] if int(entry.get('cost_unit_cash') or 0) > 0 and entry.get('type') == 'u')
        save = village()
        save['playerInfo']['cash'] = 1000
        with patch.object(command, 'session', return_value=save), patch.object(command, 'save_session'):
            command.command('u', {'ts': 0, 'first_number': 0, 'accessToken': '', 'tries': 0, 'publishActions': 0,
                                  'commands': [{'cmd': Constant.CMD_STORE_ADD_ITEMS, 'args': [f"[{unit['id']}]"]},
                                               {'cmd': Constant.CMD_BUY_UNIT_WITH_CASH, 'args': [unit['id'], 400, 300, 0, 0]}]})
        self.assertEqual(save['maps'][0]['items'], [])
        self.assertEqual(save['privateState']['gifts'][int(unit['id'])], 1)
        self.assertEqual(save['playerInfo']['cash'], 1000 - int(unit['cost_unit_cash']))
        self.assertEqual(command._STORED_IN_BATCH, {})

    def test_a_social_building_waits_for_its_paid_workers_and_then_opens(self):
        save = village()
        self.run_command(save, Constant.CMD_BUY, [23, 58, 50, 0, 0, 0, 1, 'b'])  # Market: 3 workers, 2 cash each
        market = save['maps'][0]['items'][-1]
        self.assertEqual(market[:3], [23, 58, 50])
        self.assertEqual(market[7], {'si': []})
        for _ in range(3):
            self.run_command(save, Constant.CMD_BUY_SI_HELP, [58, 50, 0, 23])
        self.run_command(save, Constant.CMD_BUY_SI_HELP, [58, 50, 0, 23, 1])  # given by the game: free
        self.assertEqual(save['playerInfo']['cash'], 100 - 3 * 2)
        self.assertEqual(market[7], {'si': [0, 0, 0, 0]})
        self.run_command(save, Constant.CMD_FINISH_SI, [58, 50, 0, 23])
        self.assertEqual(market[7], {})

    def test_buildings_the_game_gives_and_ordinary_ones_open_at_once(self):
        save = village()
        self.run_command(save, Constant.CMD_BUY, [224, 40, 40, 0, 0, 1, 1, 'b'])  # a harbor the game places for free
        self.run_command(save, Constant.CMD_BUY, [38, 44, 44, 0, 0, 0, 1, 'b'])  # Barracks I: not social
        self.assertEqual([len(item) for item in save['maps'][0]['items']], [6, 6])
        with self.assertRaises(VillageCommandError):
            apply_social_command(save, Constant.CMD_FINISH_SI, [1, 1, 0, 23], CONFIG)

    def test_a_resurrected_hero_is_placed(self):
        save = village()
        save['privateState']['potion'] = 2
        self.run_command(save, Constant.CMD_RESURRECT_HERO, [600, 12, 13, 0, '1'])
        self.assertEqual(save['maps'][0]['items'][-1][:3], [600, 12, 13])
        self.assertEqual(save['privateState']['potion'], 1)

    def test_level_up_gives_mana_once(self):
        start = GLOBALS['START_LEVEL_MANA_REWARD']
        save = village(level=start)
        save['maps'][0]['xp'] = 10 ** 9
        self.run_command(save, Constant.CMD_RT_LEVEL_UP, [start + 1])
        self.run_command(save, Constant.CMD_RT_LEVEL_UP, [start + 1])
        self.assertEqual(save['privateState']['mana'], GLOBALS['MANA_REWARD_PER_LEVEL'])


if __name__ == '__main__':
    unittest.main()


class UnitWarehouse(unittest.TestCase):
    UNIT = 3  # any unit id: the warehouse keeps ids and counts

    def warehouse_village(self):
        from village_commands import fill_map_defaults
        save = village()
        fill_map_defaults(save)
        save['maps'][0]['items'] = [[self.UNIT, 10, 12, 0, 0, 0], [self.UNIT, 11, 12, 0, 0, 0]]
        return save

    def run_command(self, save, cmd, args):
        import command
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', cmd, args)

    def test_old_saves_get_the_starting_capacity_the_game_reads(self):
        from village_commands import WAREHOUSE_START_CAPACITY
        save = self.warehouse_village()
        self.assertEqual(save['maps'][0]['warehouseAditionalCapacitySingle'], WAREHOUSE_START_CAPACITY)
        self.assertEqual(save['maps'][0]['warehousedUnits'], {})
        self.assertEqual(save['maps'][0]['resourceAlliesMarket'], 'n')  # the allies' market asks for a resource

    def test_units_go_in_and_come_back_out(self):
        save = self.warehouse_village()
        self.run_command(save, Constant.CMD_ADD_UNIT_WAREHOUSE, [10, 12, 0, self.UNIT])
        self.run_command(save, Constant.CMD_ADD_UNIT_WAREHOUSE, [11, 12, 0, self.UNIT])
        self.assertEqual(save['maps'][0]['items'], [])
        self.assertEqual(save['maps'][0]['warehousedUnits'], {str(self.UNIT): 2})
        self.run_command(save, Constant.CMD_PLACE_WAREHOUSED_ITEM, [self.UNIT, 20, 21, 0, 0])
        self.assertEqual(save['maps'][0]['warehousedUnits'], {str(self.UNIT): 1})
        self.assertEqual(save['maps'][0]['items'][0][:3], [self.UNIT, 20, 21])

    def test_nothing_is_duplicated_or_lost(self):
        save = self.warehouse_village()
        self.run_command(save, Constant.CMD_ADD_UNIT_WAREHOUSE, [30, 30, 0, self.UNIT])  # no unit there
        self.run_command(save, Constant.CMD_PLACE_WAREHOUSED_ITEM, [self.UNIT, 20, 21, 0, 0])  # none inside
        self.assertEqual(len(save['maps'][0]['items']), 2)
        self.assertEqual(save['maps'][0]['warehousedUnits'], {})
        save['maps'][0]['warehouseAditionalCapacitySingle'] = 1
        self.run_command(save, Constant.CMD_ADD_UNIT_WAREHOUSE, [10, 12, 0, self.UNIT])
        self.run_command(save, Constant.CMD_ADD_UNIT_WAREHOUSE, [11, 12, 0, self.UNIT])  # full
        self.assertEqual(len(save['maps'][0]['items']), 1)
        self.assertEqual(save['maps'][0]['warehousedUnits'], {str(self.UNIT): 1})

    def test_one_more_place_costs_cash_up_to_the_maximum(self):
        save = self.warehouse_village()
        self.run_command(save, Constant.CMD_BUY_WAREHOUSE_CAPACITY_NEW, [0])
        self.assertEqual(save['maps'][0]['warehouseAditionalCapacitySingle'], 21)
        self.assertEqual(save['playerInfo']['cash'], 100 - GLOBALS['WAREHOUSE_CAPACITY_INCREASE_PRICE_SINGLE'])
        save['maps'][0]['warehouseAditionalCapacitySingle'] = GLOBALS['WAREHOUSE_MAX_CAPACITY']
        self.run_command(save, Constant.CMD_BUY_WAREHOUSE_CAPACITY_NEW, [0])
        self.assertEqual(save['maps'][0]['warehouseAditionalCapacitySingle'], GLOBALS['WAREHOUSE_MAX_CAPACITY'])

    def test_storing_the_warehouse_moves_its_units_to_the_storage(self):
        save = self.warehouse_village()
        self.run_command(save, Constant.CMD_ADD_UNIT_WAREHOUSE, [10, 12, 0, self.UNIT])
        self.run_command(save, Constant.CMD_RESET_WAREHOUSE, [0])
        self.assertEqual(save['maps'][0]['warehousedUnits'], {})
        self.assertEqual(save['privateState']['gifts'], [0, 0, 0, 3])


class GiftXp(unittest.TestCase):
    def test_placing_a_gift_gives_its_xp_once(self):
        import command
        from get_game_config import get_attribute_from_item_id
        save = village()
        save['privateState']['gifts'] = [0] * 655 + [1]
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', Constant.CMD_PLACE_GIFT, [655, 53, 58, 0, 0])
            command.do_command('u', Constant.CMD_PLACE_GIFT, [655, 54, 58, 0, 0])  # none left: no more xp
        self.assertEqual(save['maps'][0]['xp'], int(get_attribute_from_item_id(655, 'xp')))


class Weather(unittest.TestCase):
    def test_unlocking_costs_cash_once_and_applying_needs_it_unlocked(self):
        save = village()
        with self.assertRaises(VillageCommandError):
            apply_village_command(save, Constant.CMD_SET_SKIN, [0, '4'], CONFIG)
        apply_village_command(save, Constant.CMD_UNLOCK_SKIN, ['4'], CONFIG)
        apply_village_command(save, Constant.CMD_UNLOCK_SKIN, ['4'], CONFIG)  # already: no second charge
        self.assertEqual(save['playerInfo']['cash'], 100 - GLOBALS['COST_UNLOCK_SKIN'])
        self.assertEqual(save['privateState']['unlockedSkins'], {'4': 'true'})  # the game compares with "true"
        apply_village_command(save, Constant.CMD_SET_SKIN, [0, '4'], CONFIG)
        self.assertEqual(save['maps'][0]['skin'], 4)
        apply_village_command(save, Constant.CMD_SET_SKIN, [0, '0'], CONFIG)  # the default is always there
        self.assertEqual(save['maps'][0]['skin'], 0)
        with self.assertRaises(VillageCommandError):
            apply_village_command(save, Constant.CMD_UNLOCK_SKIN, ['3'], CONFIG)  # no such weather

    def test_the_original_list_form_is_read(self):
        save = village()
        save['privateState']['unlockedSkins'] = [True]
        apply_village_command(save, Constant.CMD_UNLOCK_SKIN, ['1'], CONFIG)
        self.assertEqual(save['privateState']['unlockedSkins'], {'1': 'true'})


class Collections(unittest.TestCase):
    def run_command(self, save, cmd, args):
        import command
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', cmd, args)

    def test_pieces_are_kept_and_a_full_collection_is_traded_for_its_reward(self):
        save = village()
        for piece in (1, 2, 3, 4, 5, 5):
            self.run_command(save, Constant.CMD_ADD_COLLECTABLE, [3, piece])
        self.assertEqual(save['privateState']['collections'][3], [0, 1, 1, 1, 1, 2])
        self.run_command(save, Constant.CMD_FINISH_COLLECTION, [3])
        self.assertEqual(save['privateState']['collections'][3], [1, 0, 0, 0, 0, 1])
        reward = GLOBALS['COLLECTION_REWARDS'][3]
        self.assertEqual(save['privateState']['gifts'][reward], 1)
        self.assertEqual(save['privateState']['collectionsCompleted'], [3])
        self.run_command(save, Constant.CMD_FINISH_COLLECTION, [3])  # pieces missing now: nothing
        self.assertEqual(save['privateState']['gifts'][reward], 1)

    def test_buying_costs_one_less_per_owned_piece_and_only_once(self):
        from village_commands import PRIZE_COLLECTIONS_CASH
        save = village()
        self.run_command(save, Constant.CMD_ADD_COLLECTABLE, [2, 1])
        self.run_command(save, Constant.CMD_ADD_COLLECTABLE, [2, 4])
        self.run_command(save, Constant.CMD_FINISH_COLLECTION, [2, 1, 3])
        self.assertEqual(save['playerInfo']['cash'], 100 - (PRIZE_COLLECTIONS_CASH[2] - 2))
        self.assertEqual(save['privateState']['collections'][2], [1, 0, 0, 0, 0, 0])
        self.run_command(save, Constant.CMD_FINISH_COLLECTION, [2, 1, 3])  # already traded in
        self.assertEqual(save['playerInfo']['cash'], 100 - (PRIZE_COLLECTIONS_CASH[2] - 2))

    def test_fixed_price_minimum_one_and_unknown_collections(self):
        from village_commands import collection_price
        self.assertEqual(collection_price([0, 1, 1, 1, 1, 1], 10), 15)
        self.assertEqual(collection_price([0, 1, 1, 1, 1, 1], 1), 1)
        save = village()
        self.run_command(save, Constant.CMD_ADD_COLLECTABLE, [99, 1])
        self.run_command(save, Constant.CMD_ADD_COLLECTABLE, [1, 6])
        self.assertNotIn('collections', {k: v for k, v in save['privateState'].items() if v})

    def test_a_unit_collection_rewards_once(self):
        save = village()
        self.run_command(save, Constant.CMD_UNIT_COLLECTION_COMPLETED, [1])
        self.run_command(save, Constant.CMD_UNIT_COLLECTION_COMPLETED, [1])
        self.assertEqual(save['privateState']['unitCollectionsCompleted'], [1])
        self.assertEqual(save['playerInfo']['cash'], 101)
        self.assertEqual(save['privateState']['gifts'], [0, 0, 0, 2])  # the cash is the whole reward

    def test_activate_keeps_the_chosen_production(self):
        save = village()
        save['maps'][0]['items'] = [[3, 10, 12, 0, 0, 0]]
        self.run_command(save, Constant.CMD_ACTIVATE, [10, 12, 0, 3, 2])
        self.assertEqual(save['maps'][0]['items'][0][7], {'cp': 2})
        self.assertGreater(save['maps'][0]['items'][0][4], 0)  # the chosen production starts now
        self.run_command(save, Constant.CMD_ACTIVATE, [10, 12, 0, 3, 0])
        self.assertEqual(save['maps'][0]['items'][0][7], {'cp': 0})


class ObtainedUnits(unittest.TestCase):
    COW = 504

    def run_command(self, save, cmd, args):
        import command
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', cmd, args)

    def test_units_the_player_gets_are_remembered_but_not_the_enemy_camp(self):
        save = village()
        save['privateState']['boughtUnits'] = []
        self.run_command(save, Constant.CMD_BUY, [529, 86, 86, 0, 0, 1, 1, 'u'])  # the camp's free troll
        self.assertEqual(save['privateState']['boughtUnits'], [])
        self.run_command(save, Constant.CMD_BUY, [self.COW, 10, 10, 0, 0, 0, 1, 'u'])
        self.assertEqual(save['privateState']['boughtUnits'], [self.COW])
        save['privateState']['gifts'] = [0] * 557 + [1]
        self.run_command(save, Constant.CMD_PLACE_GIFT, [557, 11, 11, 0, 0])
        self.assertEqual(save['privateState']['boughtUnits'], [self.COW, 557])


class MapMissions(unittest.TestCase):
    def run_command(self, save, cmd, args):
        import command
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', cmd, args)

    def test_the_mission_state_is_kept(self):
        save = village()
        self.run_command(save, Constant.CMD_SET_QUEST_VAR, [0, 'spawned', 'true'])
        self.run_command(save, Constant.CMD_SET_QUEST_VAR, [0, 'boss', '[3,4]'])
        self.run_command(save, Constant.CMD_SET_QUEST_VAR, [0, 'cash', '999'])  # not a mission variable
        self.assertEqual(save['maps'][0]['currentQuestVars'], {'spawned': True, 'boss': [3, 4]})

    def test_a_treasure_gives_its_reward_and_moves_to_the_next_mission(self):
        save = village()
        self.run_command(save, Constant.CMD_COLLECT_TREASURE, [750, 100, 4, 0, 0, 0])
        town = save['maps'][0]
        self.assertEqual((town['coins'], town['xp'], town['idCurrentTreasure']), (50750, 100, 4))
        self.assertGreater(town['timestampLastTreasure'], 0)
        self.run_command(save, Constant.CMD_COLLECT_TREASURE, [0, 0, 5, 0, 0, 0])  # the game corrects the mission
        self.assertEqual((town['coins'], town['idCurrentTreasure']), (50750, 5))
        self.run_command(save, Constant.CMD_COLLECT_TREASURE, [99999, 0, 6, 0, 0, 0])  # more than a treasure gives
        self.assertEqual((town['coins'], town['idCurrentTreasure']), (50750, 5))

    def test_help_city_missions_and_the_allies_market(self):
        save = village()
        save['maps'][0]['items'] = [[3, 10, 12, 0, 10000, 0, [], {'hc': {'u77': False}}]]
        self.run_command(save, Constant.CMD_ACCEPT_COLLECT_HELP, [10, 12, 0, 3, 77])
        item = save['maps'][0]['items'][0]
        self.assertEqual((item[4], item[7]['hc']), (10000 - GLOBALS['COLLECT_HELP_SECONDS'], {'u77': True}))
        self.run_command(save, Constant.CMD_PERFORM_CITY_QUEST, [10, 12, 0, 8])
        self.assertGreater(item[4], 10000)
        item[4] = 5
        self.run_command(save, Constant.CMD_SET_RESOURCE_ALLIES, ['w', 10, 12, 0, 3])
        self.run_command(save, Constant.CMD_SET_RESOURCE_ALLIES, ['x', 10, 12, 0, 3])
        self.assertEqual(save['maps'][0]['resourceAlliesMarket'], 'w')
        self.assertGreater(item[4], 5)  # the market's time starts again


class CollectTimer(unittest.TestCase):
    def test_collecting_starts_the_building_again(self):
        import command
        save = village()
        coliseum = 53
        save['maps'][0]['items'] = [[coliseum, 43, 58, 0, 1000, 0]]
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', Constant.CMD_COLLECT, [43, 58, 0, coliseum, 0, 1, 0])
        self.assertGreater(save['maps'][0]['items'][0][4], 1000)  # not ready again after a reload


    def test_a_mill_gives_what_the_player_chose(self):
        import command
        save = village()
        mill = 5
        for choice, food in ((1, 125), (4, 750)):
            save['maps'][0]['food'] = 0
            save['maps'][0]['items'] = [[mill, 10, 10, 0, 1000, 0, [500], {'cp': choice}]]
            with patch.object(command, 'session', return_value=save):
                command.do_command('u', Constant.CMD_COLLECT, [10, 10, 0, mill, 1, 1, 0])
            self.assertEqual(save['maps'][0]['food'], food)


class QuestStars(unittest.TestCase):
    def run_command(self, save, cmd, args):
        import command
        with patch.object(command, 'session', return_value=save):
            command.do_command('u', cmd, args)

    @staticmethod
    def result(win, difficulty, quest='100000041'):
        import json
        return json.dumps({'map': 0, 'resources': {'g': 0, 'x': 0}, 'units': [], 'win': win, 'duration': 60,
                           'voluntary_end': 0, 'quest_id': quest, 'difficulty': difficulty})

    def test_winning_an_island_unlocks_its_next_star_and_keeps_the_best(self):
        save = village()
        save['privateState']['unlockedQuestIndex'] = 0
        save['privateState']['questsRank'] = '{}'  # how new villages store it
        self.run_command(save, Constant.CMD_END_QUEST, [self.result(1, 1)])
        self.assertEqual(save['privateState']['questsRank'], {'100000041': 1})
        self.run_command(save, Constant.CMD_END_QUEST, [self.result(0, 2)])  # a defeat changes nothing
        self.run_command(save, Constant.CMD_END_QUEST, [self.result(1, 3)])
        self.run_command(save, Constant.CMD_END_QUEST, [self.result(1, 1)])  # the best stays
        self.assertEqual(save['privateState']['questsRank'], {'100000041': 3})

    def test_only_a_win_opens_the_next_island_of_the_route(self):
        save = village()
        save['privateState']['unlockedQuestIndex'] = 0
        self.run_command(save, Constant.CMD_END_QUEST, [self.result(0, 1, quest='100000006')])
        self.assertEqual(save['privateState']['unlockedQuestIndex'], 0)  # a defeat opens nothing
        self.run_command(save, Constant.CMD_END_QUEST, [self.result(1, 1, quest='100000006')])
        self.assertEqual(save['privateState']['unlockedQuestIndex'], 3)  # island 2 of the route, the next is 3
        self.run_command(save, Constant.CMD_END_QUEST, [self.result(1, 1, quest='100000003')])
        self.assertEqual(save['privateState']['unlockedQuestIndex'], 3)  # an earlier island does not go back
