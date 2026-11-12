"""Clan chat and alliances (clans.py), with a fake clock."""

from pathlib import Path
import tempfile
import unittest

from clans import CHAT_INTERVAL_SECONDS, CHAT_KEEP, CHAT_LENGTH, ClanError, ClanStore


class Clock:
    def __init__(self):
        self.now = 90_000.0

    def __call__(self):
        return self.now


class SocialTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.clock = Clock()
        self.store = ClanStore(Path(directory.name) / 'clans.sqlite3', self.clock)
        # Alfa: master 1, assist 2, member 3. Beta: master 10, member 11. Gama: master 20.
        self.a = self.make(1, 'Alfa', 'ALF', 2, 3)
        self.store.set_role(1, 2, 'assist')
        self.b = self.make(10, 'Beta', 'BET', 11)
        self.c = self.make(20, 'Gama', 'GAM')

    def make(self, master, name, tag, *members):
        clan = self.store.create(master, name, tag)
        for member in members:
            self.store.request_join(member, clan['id'])
            request = next(r for r in self.store.requests_for(clan['id']) if r['account_id'] == member)
            self.store.answer_request(master, request['id'], True)
        return clan['id']

    def code(self, action, *args):
        with self.assertRaises(ClanError) as raised:
            action(*args)
        return raised.exception.code

    def say(self, account_id, text, channel='clan', name=None):
        self.clock.now += CHAT_INTERVAL_SECONDS
        return self.store.post_message(account_id, channel, text, name or f'P{account_id}')

    def allied(self):
        alliance = self.store.propose_alliance(1, self.b)
        return self.store.answer_alliance(10, alliance['id'], True)


class ChatTests(SocialTestCase):
    def test_clan_channel_is_private_to_the_clan(self):
        self.say(3, '  hola   clan ')
        self.say(11, 'hola beta')
        self.assertEqual([m['text'] for m in self.store.messages(1, 'clan')], ['hola clan'])
        self.assertEqual([m['text'] for m in self.store.messages(10, 'clan')], ['hola beta'])
        self.assertEqual(self.code(self.store.messages, 99, 'clan'), 'not_in_clan')
        self.assertEqual(self.code(self.store.messages, 1, 'other'), 'forbidden')

    def test_length_empty_and_rate_limit(self):
        self.assertEqual(self.code(self.store.post_message, 1, 'clan', '   ', 'A'), 'bad_message')
        self.assertEqual(self.code(self.store.post_message, 1, 'clan', 'x' * (CHAT_LENGTH + 1), 'A'), 'bad_message')
        self.store.post_message(1, 'clan', 'x' * CHAT_LENGTH, 'A')
        self.assertEqual(self.code(self.store.post_message, 1, 'clan', 'otra', 'A'), 'chat_too_fast')
        self.clock.now += CHAT_INTERVAL_SECONDS
        self.store.post_message(1, 'clan', 'otra', 'A')

    def test_only_the_last_messages_are_kept_and_after_reads_new_ones(self):
        for i in range(CHAT_KEEP + 5):
            last = self.say(1, f'm{i}')
        messages = self.store.messages(2, 'clan')
        self.assertEqual((len(messages), messages[0]['text'], messages[-1]['text']), (CHAT_KEEP, 'm5', f'm{CHAT_KEEP + 4}'))
        self.assertEqual(self.store.messages(2, 'clan', after=last), [])
        self.assertEqual(messages[-1]['tag'], 'ALF')

    def test_who_may_delete(self):
        own = self.say(3, 'mío')
        other = self.say(1, 'del líder')
        flags = {m['text']: m['can_delete'] for m in self.store.messages(3, 'clan')}
        self.assertEqual(flags, {'mío': True, 'del líder': False})
        self.assertEqual(self.code(self.store.delete_message, 3, other), 'forbidden')  # a member, someone else's
        self.assertEqual(self.code(self.store.delete_message, 10, own), 'forbidden')  # another clan
        self.store.delete_message(2, own)  # an Assist of the clan
        self.store.delete_message(1, other)  # the author
        self.assertEqual(self.store.messages(1, 'clan'), [])
        self.assertEqual(self.code(self.store.delete_message, 1, other), 'gone')


class AllianceTests(SocialTestCase):
    def test_only_guild_masters_propose_and_answer(self):
        self.assertEqual(self.code(self.store.propose_alliance, 2, self.b), 'forbidden')  # an Assist
        self.assertEqual(self.code(self.store.propose_alliance, 1, self.a), 'own_clan')
        alliance = self.store.propose_alliance(1, self.b)
        self.assertEqual(alliance['status'], 'pending')
        self.assertEqual(self.code(self.store.answer_alliance, 11, alliance['id'], True), 'forbidden')
        self.assertEqual(self.code(self.store.answer_alliance, 1, alliance['id'], True), 'forbidden')  # the proposer
        self.assertEqual(self.store.answer_alliance(10, alliance['id'], True)['status'], 'active')

    def test_one_alliance_per_clan(self):
        self.store.propose_alliance(1, self.b)  # pending already counts
        self.assertEqual(self.code(self.store.propose_alliance, 1, self.c), 'alliance_busy')
        self.assertEqual(self.code(self.store.propose_alliance, 20, self.b), 'target_alliance_busy')
        self.assertEqual(self.code(self.store.propose_alliance, 20, self.a), 'target_alliance_busy')

    def test_decline_cancel_and_end(self):
        alliance = self.store.propose_alliance(1, self.b)
        self.assertEqual(self.store.answer_alliance(10, alliance['id'], False)['status'], 'declined')
        alliance = self.store.propose_alliance(1, self.b)
        self.assertEqual(self.code(self.store.end_alliance, 10, alliance['id']), 'forbidden')  # only the proposer cancels
        self.assertEqual(self.store.end_alliance(1, alliance['id'])['status'], 'cancelled')
        active = self.allied()
        self.assertEqual(self.code(self.store.end_alliance, 20, active['id']), 'forbidden')
        self.assertEqual(self.store.end_alliance(10, active['id'])['status'], 'ended')  # either Guild Master
        self.assertIsNone(self.store.alliance(self.a))
        self.store.propose_alliance(20, self.a)  # free again

    def test_allies_cannot_challenge_each_other(self):
        self.allied()
        self.assertEqual(self.code(self.store.challenge, 1, self.b, 3), 'allied')
        self.assertEqual(self.code(self.store.challenge, 10, self.a, 3), 'allied')
        self.store.challenge(1, self.c, 3)  # others, yes

    def test_shared_alliance_channel(self):
        self.assertEqual(self.code(self.store.messages, 1, 'alliance'), 'no_alliance')
        self.store.propose_alliance(1, self.b)
        self.assertEqual(self.code(self.store.post_message, 1, 'alliance', 'hola', 'A'), 'no_alliance')  # still pending
        alliance = self.store.alliance(self.a)
        self.store.answer_alliance(10, alliance['id'], True)
        self.say(3, 'hola aliados', 'alliance')
        reply = self.say(11, 'hola Alfa', 'alliance')
        self.assertEqual([(m['text'], m['tag']) for m in self.store.messages(10, 'alliance')],
                         [('hola aliados', 'ALF'), ('hola Alfa', 'BET')])
        self.assertEqual(self.code(self.store.messages, 20, 'alliance'), 'no_alliance')
        self.assertEqual(self.code(self.store.delete_message, 2, reply), 'forbidden')  # an Assist of Alfa, a Beta message
        self.store.delete_message(10, reply)  # Beta's Guild Master
        self.store.end_alliance(1, alliance['id'])
        self.assertEqual(self.code(self.store.messages, 3, 'alliance'), 'no_alliance')

    def test_a_dissolved_clan_ends_its_alliance(self):
        self.allied()
        self.store.dissolve(10)
        self.assertIsNone(self.store.alliance(self.a))
        pending = self.store.propose_alliance(1, self.c)
        self.store.dissolve(20)
        self.assertIsNone(self.store.alliance(self.a))
        self.assertNotEqual(pending['status'], 'active')


if __name__ == '__main__':
    unittest.main()
