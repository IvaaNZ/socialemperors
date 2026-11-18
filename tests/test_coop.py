import tempfile
import unittest
from pathlib import Path

from coop import MAX_PLAYERS, ROOM_IDLE_SECONDS, TEAM_UNITS, CoopError, CoopStore, clean_team


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class CleanTeam(unittest.TestCase):
    def test_the_games_empty_places_go_and_at_most_ten_units_stay(self):
        self.assertEqual(clean_team([5, 0, 7, 0]), [5, 7])
        self.assertEqual(len(clean_team(list(range(1, TEAM_UNITS + 1)))), TEAM_UNITS)
        for bad in ([], [0, 0], list(range(1, TEAM_UNITS + 2)), [True], ['5'], [-1], 'x', [1] * 21):
            with self.assertRaises(CoopError):
                clean_team(bad)


class Rooms(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.store = CoopStore(Path(self.folder.name) / 'coop.sqlite3', clock=self.clock)
        self.room = self.store.create(1, 10, '100000001', [5, 0, 6])

    def tearDown(self):
        self.folder.cleanup()

    def states(self, room):
        return {p['account_id']: p['state'] for p in room['players']}

    def test_the_host_opens_one_room_with_a_team(self):
        self.assertEqual(self.store.room_of(1)['id'], self.room['id'])
        self.assertEqual(self.room['players'][0]['team'], [5, 6])
        with self.assertRaises(CoopError) as busy:
            self.store.create(1, 10, '100000002', [5])
        self.assertEqual(busy.exception.code, 'busy')

    def test_only_the_host_invites_and_only_members_of_the_clan(self):
        with self.assertRaises(CoopError):
            self.store.invite(2, self.room['id'], 3, 10)
        with self.assertRaises(CoopError) as other_clan:
            self.store.invite(1, self.room['id'], 3, 11)
        self.assertEqual(other_clan.exception.code, 'clan')
        room = self.store.invite(1, self.room['id'], 2, 10)
        self.assertEqual(self.states(room)[2], 'invited')
        self.assertEqual([r['id'] for r in self.store.invites_of(2)], [self.room['id']])

    def test_three_players_at_most(self):
        self.store.invite(1, self.room['id'], 2, 10)
        self.store.invite(1, self.room['id'], 3, 10)
        with self.assertRaises(CoopError) as full:
            self.store.invite(1, self.room['id'], 4, 10)
        self.assertEqual(full.exception.code, 'full')
        self.assertEqual(MAX_PLAYERS, 3)

    def test_a_guest_accepts_chooses_and_the_room_can_sail(self):
        self.store.invite(1, self.room['id'], 2, 10)
        room = self.store.respond(2, self.room['id'], True)
        self.assertFalse(self.store.ready_to_sail(room))  # the guest has no team yet
        room = self.store.set_team(2, self.room['id'], [9, 9, 0])
        self.assertTrue(self.store.ready_to_sail(room))
        self.assertEqual(self.store.room_of(2)['id'], self.room['id'])
        self.assertEqual(self.store.invites_of(2), [])

    def test_declining_or_leaving_frees_the_place_and_the_host_leaving_closes_it(self):
        self.store.invite(1, self.room['id'], 2, 10)
        room = self.store.respond(2, self.room['id'], False)
        self.assertEqual(self.states(room)[2], 'declined')
        self.store.invite(1, self.room['id'], 2, 10)
        self.store.respond(2, self.room['id'], True)
        room = self.store.leave(2, self.room['id'])
        self.assertEqual(self.states(room)[2], 'left')
        room = self.store.leave(1, self.room['id'])
        self.assertEqual(room['status'], 'cancelled')
        self.assertIsNone(self.store.room_of(1))

    def test_a_player_in_a_room_cannot_join_another(self):
        other = self.store.create(2, 10, '100000002', [7])
        self.store.invite(1, self.room['id'], 2, 10)
        with self.assertRaises(CoopError) as busy:
            self.store.respond(2, self.room['id'], True)
        self.assertEqual(busy.exception.code, 'busy')
        self.assertEqual(self.store.room_of(2)['id'], other['id'])

    def test_only_the_host_sails_when_everyone_is_ready_and_the_army_is_everyones(self):
        self.store.invite(1, self.room['id'], 2, 10)
        self.store.invite(1, self.room['id'], 3, 10)
        self.store.respond(2, self.room['id'], True)
        with self.assertRaises(CoopError) as not_ready:
            self.store.sail(1, self.room['id'])
        self.assertEqual(not_ready.exception.code, 'not_ready')
        self.store.set_team(2, self.room['id'], [9, 0, 8])
        with self.assertRaises(CoopError):
            self.store.sail(2, self.room['id'])
        room = self.store.sail(1, self.room['id'])
        self.assertEqual(room['status'], 'sailing')
        self.assertEqual(self.states(room)[3], 'declined')  # nobody answered: the invitation lapsed
        self.assertEqual(CoopStore.army(room), [5, 6, 9, 8])  # the host's units first
        self.assertEqual(self.store.sailing_room_of(2)['id'], self.room['id'])
        with self.assertRaises(CoopError):
            self.store.create(2, 10, '100000002', [1])  # at sea: no other raid
        room = self.store.leave(1, self.room['id'])
        self.assertEqual(room['status'], 'done')
        self.assertIsNone(self.store.sailing_room_of(2))

    def sailing(self):
        self.store.invite(1, self.room['id'], 2, 10)
        self.store.respond(2, self.room['id'], True)
        self.store.set_team(2, self.room['id'], [9, 9])
        return self.store.sail(1, self.room['id'])

    def test_each_death_counts_once_for_its_owner_and_never_more_than_it_brought(self):
        self.sailing()
        self.assertTrue(self.store.record_death(1, self.room['id'], 7, 2, 9))
        self.assertFalse(self.store.record_death(1, self.room['id'], 7, 2, 9))  # the same unit again
        self.assertTrue(self.store.record_death(1, self.room['id'], 8, 2, 9))
        with self.assertRaises(CoopError):
            self.store.record_death(1, self.room['id'], 9, 2, 9)  # it brought two
        with self.assertRaises(CoopError):
            self.store.record_death(1, self.room['id'], 10, 2, 5)  # not in its team
        with self.assertRaises(CoopError):
            self.store.record_death(2, self.room['id'], 11, 1, 5)  # only the host reports
        self.assertEqual([d['handle'] for d in self.store.deaths(self.room['id'])], [7, 8])

    def test_the_end_closes_the_raid_and_the_villages_reload(self):
        self.sailing()
        self.assertEqual(self.store.revision('village-2'), '')
        self.store.village_changed('village-2')
        self.store.village_changed('village-2')
        self.assertEqual(self.store.revision('village-2'), 'coop2')
        self.assertEqual(self.store.finish(self.room['id'])['status'], 'done')
        self.assertIsNone(self.store.finish(self.room['id']))
        self.assertIsNone(self.store.sailing_room_of(2))

    def test_a_room_left_alone_closes(self):
        self.clock.now += ROOM_IDLE_SECONDS + 1
        self.assertIsNone(self.store.room_of(1))
        self.assertEqual(self.store.room(self.room['id'])['status'], 'cancelled')


class Rewards(unittest.TestCase):
    def test_the_islands_gold_and_xp_are_scaled_and_the_rest_kept(self):
        import json

        from coop import CLAN_REWARD, SOLO_REWARD
        from coop_web import scaled_end_quest
        item = {'cmd': 'end_quest', 'args': [json.dumps({'map': 0, 'resources': {'g': 1000, 'x': 300}, 'win': 1,
                                                          'quest_id': '100000006', 'difficulty': 1})]}
        clan, data = scaled_end_quest(item, CLAN_REWARD)
        self.assertEqual(data['resources'], {'g': 700, 'x': 210})
        self.assertEqual(json.loads(clan['args'][0])['quest_id'], '100000006')
        solo, data = scaled_end_quest(item, SOLO_REWARD)
        self.assertEqual(data['resources'], {'g': 1200, 'x': 360})
        self.assertEqual(json.loads(item['args'][0])['resources']['g'], 1000)  # the original command is untouched


class Prestige(unittest.TestCase):
    def test_a_clan_gathers_prestige(self):
        from clans import ClanStore
        with tempfile.TemporaryDirectory() as folder:
            store = ClanStore(Path(folder) / 'clans.sqlite3')
            clan = store.create(1, 'Huevitos', 'PRO')
            self.assertEqual(store.add_prestige(clan['id'], 5), 5)
            self.assertEqual(store.add_prestige(clan['id'], 15), 20)
            self.assertIsNone(store.add_prestige(999, 5))


class IceServers(unittest.TestCase):
    def test_the_stun_servers_come_from_server_env_and_off_means_none(self):
        import os
        from unittest import mock

        from coop_web import ice_servers
        with mock.patch.dict(os.environ, {'SE_COOP_STUN': 'stun:a.example:3478, stun:b.example:3478'}):
            self.assertEqual(ice_servers(), [{'urls': ['stun:a.example:3478', 'stun:b.example:3478']}])
        with mock.patch.dict(os.environ, {'SE_COOP_STUN': 'off'}):
            self.assertEqual(ice_servers(), [])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SE_COOP_STUN', None)
            self.assertEqual(len(ice_servers()), 1)


if __name__ == '__main__':
    unittest.main()
