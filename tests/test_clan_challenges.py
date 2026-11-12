"""Clan challenges (clans.py): best of N duels between two clans, with a fake clock."""

import itertools
from pathlib import Path
import tempfile
import unittest

from clans import CHALLENGE_ANSWER_SECONDS, ClanError, ClanStore

_duel_ids = itertools.count(1)


class Clock:
    def __init__(self):
        self.now = 50_000.0

    def __call__(self):
        return self.now


def duel(winner, loser, status='done', draw=False):
    return {'id': next(_duel_ids), 'challenger_id': winner, 'defender_id': loser, 'status': status,
            'winner': 'draw' if draw else 'challenger'}


class ChallengeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.clock = Clock()
        self.store = ClanStore(Path(directory.name) / 'clans.sqlite3', self.clock)
        # Clan A: master 1, members 2 and 3. Clan B: master 10, member 11. Clan C: master 20.
        self.a = self.make(1, 'Alfa', 'ALF', 2, 3)
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

    def accepted(self, best_of=3):
        challenge = self.store.challenge(1, self.b, best_of)
        return self.store.answer_challenge(10, challenge['id'], True)

    def test_only_guild_masters_challenge_and_answer(self):
        self.assertEqual(self.code(self.store.challenge, 2, self.b, 3), 'forbidden')  # a member
        self.assertEqual(self.code(self.store.challenge, 1, self.a, 3), 'own_clan')
        for size in (0, 4, 9, 'x', None):
            self.assertEqual(self.code(self.store.challenge, 1, self.b, size), 'bad_size')
        challenge = self.store.challenge(1, self.b, '5')
        self.assertEqual((challenge['status'], challenge['best_of']), ('pending', 5))
        self.assertEqual(self.code(self.store.answer_challenge, 11, challenge['id'], True), 'forbidden')  # B member
        self.assertEqual(self.code(self.store.answer_challenge, 1, challenge['id'], True), 'forbidden')  # the challenger
        self.assertEqual(self.code(self.store.cancel_challenge, 10, challenge['id']), 'forbidden')  # only the challenger cancels
        self.store.cancel_challenge(1, challenge['id'])
        self.assertIsNone(self.store.current_challenge(self.a))

    def test_one_open_challenge_per_clan(self):
        self.store.challenge(1, self.b, 3)
        self.assertEqual(self.code(self.store.challenge, 1, self.c, 3), 'challenge_busy')
        self.assertEqual(self.code(self.store.challenge, 20, self.b, 3), 'target_challenge_busy')
        self.assertEqual(self.code(self.store.challenge, 20, self.a, 3), 'target_challenge_busy')

    def test_a_challenge_expires_after_ten_minutes(self):
        challenge = self.store.challenge(1, self.b, 3)
        self.clock.now += CHALLENGE_ANSWER_SECONDS - 1
        self.assertEqual(self.store.current_challenge(self.b)['expires_in'], 1)
        self.clock.now += 1
        self.assertIsNone(self.store.current_challenge(self.b))
        self.assertEqual(self.code(self.store.answer_challenge, 10, challenge['id'], True), 'gone')
        self.assertEqual(self.store.challenge_history(self.a)[0]['status'], 'expired')
        self.store.challenge(20, self.b, 3)  # free again

    def test_declining(self):
        challenge = self.store.challenge(1, self.b, 3)
        self.assertEqual(self.store.answer_challenge(10, challenge['id'], False)['status'], 'declined')
        self.store.challenge(1, self.b, 3)  # can challenge again at once

    def test_best_of_three_ends_at_two_wins_and_they_can_challenge_again(self):
        challenge = self.accepted(3)
        self.assertEqual(challenge['status'], 'active')
        after = self.store.record_duel(duel(2, 11))  # A wins
        self.assertEqual((after['challenger_wins'], after['defender_wins'], after['status']), (1, 0, 'active'))
        self.store.record_duel(duel(10, 3))  # B wins
        final = self.store.record_duel(duel(1, 10))  # A wins: 2 of 3
        self.assertEqual((final['status'], final['winner_clan'], final['ending'], final['challenger_wins']),
                         ('done', self.a, 'majority', 2))
        self.assertIsNone(self.store.record_duel(duel(2, 10)))  # nothing open any more
        self.assertIsNone(self.store.current_challenge(self.a))
        again = self.store.challenge(10, self.a, 7)  # the same clans, at once, the other way round
        self.assertEqual(again['status'], 'pending')

    def test_what_does_not_count(self):
        challenge = self.accepted(5)
        self.assertIsNone(self.store.record_duel(duel(2, 3)))  # same clan
        self.assertIsNone(self.store.record_duel(duel(2, 20)))  # a third clan
        self.assertIsNone(self.store.record_duel(duel(2, 11, draw=True)))  # a draw
        self.assertIsNone(self.store.record_duel(duel(2, 11, status='review')))
        self.assertIsNone(self.store.record_duel(duel(2, 11, status='void')))
        counted = duel(2, 11)
        self.store.record_duel(counted)
        self.assertIsNone(self.store.record_duel(counted))  # each duel once
        current = self.store.current_challenge(self.a)
        self.assertEqual((current['challenger_wins'], len(current['duels'])), (1, 1))
        self.assertEqual(current['id'], challenge['id'])

    def test_only_members_at_acceptance_count(self):
        self.accepted(3)
        self.store.request_join(12, self.b)
        self.store.answer_request(10, self.store.requests_for(self.b)[0]['id'], True)  # joins B after acceptance
        self.assertIsNone(self.store.record_duel(duel(12, 2)))
        self.store.leave(11)  # left B after acceptance: still on the roster
        self.assertEqual(self.store.record_duel(duel(11, 2))['defender_wins'], 1)

    def test_surrender(self):
        challenge = self.accepted(7)
        self.assertEqual(self.code(self.store.surrender, 2, challenge['id']), 'forbidden')
        self.assertEqual(self.code(self.store.surrender, 20, challenge['id']), 'forbidden')
        done = self.store.surrender(10, challenge['id'])
        self.assertEqual((done['status'], done['winner_clan'], done['ending']), ('done', self.a, 'surrender'))
        self.assertEqual(self.code(self.store.surrender, 1, challenge['id']), 'gone')

    def test_a_clan_dissolved_during_a_challenge_loses_it(self):
        challenge = self.accepted(3)
        self.store.dissolve(10)
        history = self.store.challenge_history(self.a)[0]
        self.assertEqual((history['id'], history['winner_clan'], history['ending'], history['defender_tag']),
                         (challenge['id'], self.a, 'dissolved', 'BET'))
        pending = self.store.challenge(1, self.c, 3)
        self.store.dissolve(20)
        self.assertEqual(self.store.challenge_history(self.a)[0]['status'], 'cancelled')
        self.assertEqual(self.store.challenge_history(self.a)[0]['id'], pending['id'])

    def test_ranking(self):
        self.accepted(3)
        self.store.record_duel(duel(2, 11))
        self.store.record_duel(duel(3, 10))
        challenge = self.store.challenge(20, self.b, 3)
        self.store.answer_challenge(10, challenge['id'], True)
        self.store.surrender(20, challenge['id'])
        ranking = {row['tag']: (row['won'], row['lost'], row['duel_wins']) for row in self.store.ranking()}
        self.assertEqual(ranking, {'ALF': (1, 0, 2), 'BET': (1, 1, 0), 'GAM': (0, 1, 0)})
        self.assertEqual([row['tag'] for row in self.store.ranking()], ['ALF', 'BET', 'GAM'])


if __name__ == '__main__':
    unittest.main()
