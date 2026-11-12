"""Clan rules (clans.py): roles, permissions, requests, limits and waits, with a fake clock."""

from pathlib import Path
import tempfile
import unittest

from clans import (MAX_ASSISTS, MAX_MEMBERS, MAX_OPEN_REQUESTS, REJOIN_SECONDS, REQUEST_SECONDS, ClanError, ClanStore,
                   clean_name, clean_tag, name_key)


class Clock:
    def __init__(self):
        self.now = 10_000.0

    def __call__(self):
        return self.now


class ClanTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.clock = Clock()
        self.store = ClanStore(Path(directory.name) / 'clans.sqlite3', self.clock)

    def code(self, action, *args):
        with self.assertRaises(ClanError) as raised:
            action(*args)
        return raised.exception.code

    def clan_with(self, master, *members):
        clan = self.store.create(master, f'Clan {master}', f'C{master}')
        for member in members:
            self.store.request_join(member, clan['id'])
            request = next(r for r in self.store.requests_for(clan['id']) if r['account_id'] == member)
            self.store.answer_request(master, request['id'], True)
        return clan

    def role(self, account_id):
        member = self.store.membership(account_id)
        return member and member['role']


class NameTests(unittest.TestCase):
    def test_names_and_tags(self):
        self.assertEqual(clean_name('  Los   Ñandúes '), 'Los Ñandúes')
        self.assertEqual(clean_tag(' tuk '), 'TUK')
        for bad in ('ab', 'x' * 25, '<script>', '!!!', ''):
            with self.subTest(name=bad), self.assertRaises(ClanError):
                clean_name(bad)
        for bad in ('A', 'TOOLONG', 'A B', 'ÑU', ''):
            with self.subTest(tag=bad), self.assertRaises(ClanError):
                clean_tag(bad)
        self.assertEqual(name_key('Los Ñandúes'), name_key('los nandues'))


class CreateAndJoinTests(ClanTestCase):
    def test_create_makes_the_founder_guild_master_and_names_are_unique(self):
        clan = self.store.create(1, 'Los Ñandúes', 'nan', 'Hola')
        self.assertEqual((clan['tag'], clan['description'], self.role(1)), ('NAN', 'Hola', 'master'))
        self.assertEqual(self.code(self.store.create, 2, 'los nandues', 'OTRO'), 'name_taken')
        self.assertEqual(self.code(self.store.create, 2, 'Otro clan', 'NAN'), 'tag_taken')
        self.assertEqual(self.code(self.store.create, 1, 'Segundo', 'SEG'), 'already_in_clan')

    def test_request_and_approval(self):
        clan = self.store.create(1, 'Clan Uno', 'UNO')
        self.store.request_join(2, clan['id'])
        self.assertEqual(self.code(self.store.request_join, 2, clan['id']), 'already_requested')
        request = self.store.requests_for(clan['id'])[0]
        self.assertEqual(self.code(self.store.answer_request, 3, request['id'], True), 'forbidden')  # not in the clan
        self.assertEqual(self.store.answer_request(1, request['id'], True), 2)
        self.assertEqual(self.role(2), 'member')
        self.assertEqual(self.store.requests_for(clan['id']), [])
        self.assertEqual(self.code(self.store.request_join, 2, clan['id']), 'already_in_clan')

    def test_accepting_clears_the_other_requests_and_a_taken_player_is_gone(self):
        first, second = self.store.create(1, 'Clan Uno', 'UNO'), self.store.create(5, 'Clan Dos', 'DOS')
        self.store.request_join(2, first['id'])
        self.store.request_join(2, second['id'])
        self.store.answer_request(1, self.store.requests_for(first['id'])[0]['id'], True)
        self.assertEqual(self.store.requests_for(second['id']), [])
        self.store.request_join(3, first['id'])
        self.store.request_join(3, second['id'])
        late = self.store.requests_for(second['id'])[0]
        self.store.answer_request(1, self.store.requests_for(first['id'])[0]['id'], True)
        self.assertEqual(self.code(self.store.answer_request, 5, late['id'], True), 'gone')

    def test_requests_are_limited_cancellable_and_expire(self):
        clans = [self.store.create(10 + i, f'Clan {i}', f'C{i}') for i in range(MAX_OPEN_REQUESTS + 1)]
        for clan in clans[:MAX_OPEN_REQUESTS]:
            self.store.request_join(2, clan['id'])
        self.assertEqual(self.code(self.store.request_join, 2, clans[-1]['id']), 'too_many_requests')
        self.store.cancel_request(2, clans[0]['id'])
        self.assertEqual(self.code(self.store.cancel_request, 2, clans[0]['id']), 'gone')
        self.store.request_join(2, clans[-1]['id'])
        self.clock.now += REQUEST_SECONDS
        self.assertEqual(self.store.requests_of(2), [])  # expired
        self.store.request_join(2, clans[0]['id'])
        self.assertEqual(len(self.store.requests_of(2)), 1)

    def test_rejected_requests_and_the_member_limit(self):
        clan = self.clan_with(1, *range(2, MAX_MEMBERS + 1))
        self.assertEqual(len(self.store.clan(clan['id'])['members']), MAX_MEMBERS)
        self.assertEqual(self.code(self.store.request_join, 500, clan['id']), 'clan_full')
        self.store.kick(1, 2)
        self.store.request_join(500, clan['id'])
        self.store.request_join(501, self.store.create(600, 'Otro', 'OTR')['id'])
        request = self.store.requests_for(clan['id'])[0]
        self.assertIsNone(self.store.answer_request(1, request['id'], False))
        self.assertIsNone(self.role(500))


class RoleTests(ClanTestCase):
    def test_assists_manage_plain_members_only(self):
        self.clan_with(1, 2, 3, 4)
        self.store.set_role(1, 2, 'assist')
        self.assertEqual(self.role(2), 'assist')
        self.store.set_role(1, 3, 'assist')
        self.assertEqual(self.code(self.store.kick, 2, 3), 'forbidden')  # an Assist cannot remove another Assist
        self.assertEqual(self.code(self.store.kick, 2, 1), 'forbidden')  # ... nor the Guild Master
        self.assertEqual(self.code(self.store.set_role, 2, 4, 'assist'), 'forbidden')  # only the Guild Master names Assists
        self.assertEqual(self.code(self.store.edit, 2, 'nuevo'), 'forbidden')
        self.assertEqual(self.code(self.store.dissolve, 2), 'forbidden')
        self.assertEqual(self.code(self.store.transfer, 2, 4), 'forbidden')
        self.store.kick(2, 4)
        self.assertIsNone(self.role(4))
        self.store.kick(1, 3)  # the Guild Master removes anyone
        self.assertIsNone(self.role(3))

    def test_assists_can_answer_requests_and_plain_members_cannot(self):
        clan = self.clan_with(1, 2, 3)
        self.store.set_role(1, 2, 'assist')
        self.store.request_join(7, clan['id'])
        self.store.request_join(8, clan['id'])
        first, second = self.store.requests_for(clan['id'])
        self.assertEqual(self.code(self.store.answer_request, 3, first['id'], True), 'forbidden')
        self.assertEqual(self.code(self.store.kick, 3, 2), 'forbidden')
        self.store.answer_request(2, first['id'], True)
        self.store.answer_request(2, second['id'], False)
        self.assertEqual((self.role(7), self.role(8)), ('member', None))

    def test_at_most_three_assists(self):
        self.clan_with(1, *range(2, 2 + MAX_ASSISTS + 1))
        for member in range(2, 2 + MAX_ASSISTS):
            self.store.set_role(1, member, 'assist')
        self.assertEqual(self.code(self.store.set_role, 1, 2 + MAX_ASSISTS, 'assist'), 'too_many_assists')
        self.store.set_role(1, 2, 'member')
        self.store.set_role(1, 2 + MAX_ASSISTS, 'assist')
        self.assertEqual(self.role(2 + MAX_ASSISTS), 'assist')
        self.assertEqual(self.code(self.store.set_role, 1, 1, 'member'), 'forbidden')  # the master's own role
        self.assertEqual(self.code(self.store.set_role, 1, 3, 'master'), 'forbidden')

    def test_transfer_and_leaving(self):
        self.clan_with(1, 2, 3)
        self.assertEqual(self.code(self.store.leave, 1), 'transfer_first')
        self.store.transfer(1, 2)
        self.assertEqual((self.role(1), self.role(2)), ('member', 'master'))
        self.assertEqual(self.store.leave(1), 'left')
        self.assertEqual(self.code(self.store.leave, 1), 'not_in_clan')
        self.assertEqual(self.code(self.store.transfer, 3, 2), 'forbidden')

    def test_last_guild_master_leaving_dissolves_the_clan(self):
        clan = self.store.create(1, 'Solo', 'SOL')
        self.store.request_join(5, clan['id'])
        self.assertEqual(self.store.leave(1), 'dissolved')
        self.assertIsNone(self.store.clan(clan['id']))
        self.assertEqual(self.store.requests_of(5), [])
        self.store.create(1, 'Solo', 'SOL')  # a dissolved clan imposes no wait and frees its name

    def test_dissolve_and_admin_dissolve(self):
        clan = self.clan_with(1, 2)
        self.store.dissolve(1)
        self.assertIsNone(self.store.clan(clan['id']))
        self.assertEqual((self.role(1), self.role(2)), (None, None))
        self.assertEqual(self.store.rejoin_wait(2), 0)
        clan = self.clan_with(1, 2)
        self.assertEqual(self.code(self.store.admin_dissolve, clan['id'], 99, 'Admin', '  '), 'reason_required')
        self.store.admin_dissolve(clan['id'], 99, 'Admin', 'Nombre ofensivo')
        entry = self.store.log()[0]
        self.assertEqual((entry['action'], entry['actor_name'], entry['detail']), ('dissolve', 'Admin', 'Nombre ofensivo'))
        self.assertEqual(self.code(self.store.admin_dissolve, clan['id'], 99, 'Admin', 'x'), 'no_clan')


class SettingsAndRecruitmentTests(ClanTestCase):
    def test_guild_master_edits_emblem_motto_announcement_and_recruitment(self):
        clan = self.clan_with(1, 2)
        self.store.set_role(1, 2, 'assist')
        self.assertEqual(self.code(self.store.settings, 2, 3, '', '', 1, 10, 'es'), 'forbidden')  # an Assist cannot
        updated = self.store.settings(1, '7', 'Los mejores', 'Línea 1\r\n\r\n\r\nLínea 2', 'on', '25', 'es')
        self.assertEqual((updated['emblem'], updated['description'], updated['announcement'], updated['recruit_open'],
                          updated['recruit_min_level'], updated['recruit_language']),
                         (7, 'Los mejores', 'Línea 1\n\nLínea 2', 1, 25, 'es'))
        for bad in ((0, 1, 'es'), (13, 1, 'es'), (1, 0, 'es'), (1, 100, 'es'), (1, 1, 'fr'), ('x', 1, 'es')):
            with self.subTest(bad=bad):
                self.assertEqual(self.code(self.store.settings, 1, bad[0], '', '', 0, bad[1], bad[2]), 'bad_settings')
        self.assertEqual(self.code(self.store.settings, 1, 1, '', 'x' * 501, 0, 1, 'all'), 'bad_announcement')
        self.assertEqual(self.store.clan(clan['id'])['emblem'], 7)

    def test_open_clans_take_eligible_players_at_once(self):
        clan = self.store.create(1, 'Abiertos', 'ABI', emblem=4)
        self.assertEqual(self.store.clan(clan['id'])['emblem'], 4)
        self.assertEqual(self.code(self.store.join, 2, clan['id'], 30), 'not_open')
        self.store.settings(1, 4, '', '', 1, 20, 'all')
        self.assertEqual(self.code(self.store.join, 2, clan['id'], 19), 'level_too_low')
        self.store.request_join(2, self.store.create(9, 'Otro', 'OTR')['id'])
        self.store.join(2, clan['id'], 20)
        self.assertEqual(self.role(2), 'member')
        self.assertEqual(self.store.requests_of(2), [])  # joining clears the other requests
        self.assertEqual(self.store.log(clan['id'])[0]['action'], 'join')
        self.assertEqual(self.code(self.store.request_join, 3, clan['id'], 5), 'level_too_low')  # requests too
        self.store.request_join(3, clan['id'], 25)

    def test_an_old_database_gets_the_new_columns(self):
        import sqlite3
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'old.sqlite3'
        connection = sqlite3.connect(path)
        connection.executescript(
            "CREATE TABLE clans (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,"
            " tag TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL, created_at REAL NOT NULL);"
            "INSERT INTO clans (name, name_key, tag, created_by, created_at) VALUES ('Viejo', 'viejo', 'VIE', 1, 1.0);")
        connection.commit()
        connection.close()
        store = ClanStore(path, self.clock)
        clan = store.clan(1)
        self.assertEqual((clan['name'], clan['emblem'], clan['announcement'], clan['recruit_open'], clan['recruit_min_level'],
                          clan['recruit_language']), ('Viejo', 1, '', 0, 1, 'all'))
        ClanStore(path, self.clock)  # opening it again changes nothing


class WaitTests(ClanTestCase):
    def test_leaving_or_being_removed_waits_an_hour(self):
        first = self.clan_with(1, 2, 3)
        second = self.store.create(5, 'Clan Dos', 'DOS')
        self.store.leave(2)
        self.assertEqual(self.store.rejoin_wait(2), REJOIN_SECONDS)
        self.assertEqual(self.code(self.store.request_join, 2, second['id']), 'rejoin_wait')
        self.assertEqual(self.code(self.store.create, 2, 'Nuevo', 'NUE'), 'rejoin_wait')
        self.store.kick(1, 3)
        self.assertEqual(self.code(self.store.request_join, 3, first['id']), 'rejoin_wait')
        self.clock.now += REJOIN_SECONDS
        self.store.request_join(2, second['id'])
        self.assertEqual(self.store.rejoin_wait(2), 0)

    def test_everything_is_logged(self):
        clan = self.clan_with(1, 2)
        self.store.set_role(1, 2, 'assist', actor_name='Ana')
        self.store.edit(1, 'Nueva descripción', actor_name='Ana')
        actions = [entry['action'] for entry in self.store.log(clan['id'])]
        self.assertEqual(actions, ['edit', 'promote', 'accept', 'create'])
        self.assertEqual(self.store.clan(clan['id'])['description'], 'Nueva descripción')
        self.assertEqual(self.code(self.store.edit, 1, 'x' * 201), 'bad_description')

    def test_search(self):
        self.store.create(1, 'Los Ñandúes', 'NAN')
        self.store.create(2, 'Dragones', 'DRG')
        self.assertEqual([c['tag'] for c in self.store.clans('nandu')], ['NAN'])
        self.assertEqual([c['tag'] for c in self.store.clans('drg')], ['DRG'])
        self.assertEqual(len(self.store.clans()), 2)
        self.assertEqual(self.store.clans()[0]['member_count'], 1)


if __name__ == '__main__':
    unittest.main()
