import tempfile
import unittest
from pathlib import Path

from chat import INTERVAL_SECONDS, KEEP, LENGTH, ChatError, ChatStore, WordFilter


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Chat(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        words = Path(self.folder.name) / 'words.txt'
        words.write_text('# a comment\nboludo\nhijo de puta\n', encoding='utf-8')
        self.clock = Clock()
        self.store = ChatStore(Path(self.folder.name) / 'chat.sqlite3', clock=self.clock, word_filter=WordFilter(words))

    def tearDown(self):
        self.folder.cleanup()

    def post(self, account, text, name='Tuki', tag='PRO', level=99):
        self.clock.now += INTERVAL_SECONDS
        return self.store.post(account, name, tag, level, text)

    def test_a_message_keeps_the_name_the_clan_tag_and_the_level(self):
        row = self.post(1, '  hola   a todos ')
        self.assertEqual((row['name'], row['tag'], row['level'], row['text']), ('Tuki', 'PRO', 99, 'hola a todos'))
        self.assertEqual([m['id'] for m in self.store.recent()], [row['id']])

    def test_empty_long_and_fast_messages_are_refused(self):
        for text, code in (('   ', 'empty'), ('x' * (LENGTH + 1), 'too_long')):
            with self.assertRaises(ChatError) as refused:
                self.post(1, text)
            self.assertEqual(refused.exception.code, code)
        self.post(1, 'uno')
        with self.assertRaises(ChatError) as fast:
            self.store.post(1, 'Tuki', '', 1, 'dos')  # no time passed
        self.assertEqual(fast.exception.code, 'too_fast')
        self.store.post(2, 'Otro', '', 1, 'otro jugador puede')  # the limit is per player

    def test_only_the_last_messages_are_kept(self):
        for n in range(KEEP + 5):
            self.post(1 + n % 3, f'mensaje {n}')
        texts = [m['text'] for m in self.store.recent()]
        self.assertEqual(len(texts), KEEP)
        self.assertEqual(texts[-1], f'mensaje {KEEP + 4}')
        self.assertEqual(texts[0], 'mensaje 5')

    def test_the_owners_words_become_stars_in_any_case_or_accent(self):
        self.assertEqual(self.post(1, 'Sos un BOLÚDO, che')['text'], 'Sos un ***, che')
        self.assertEqual(self.post(1, 'hijo  de puta')['text'], '***')
        self.assertEqual(self.post(1, 'boludos no es la palabra')['text'], 'boludos no es la palabra')

    def test_the_dot_is_red_only_for_what_others_wrote_after_the_last_read(self):
        self.assertFalse(self.store.unread(1))
        mine = self.post(1, 'hola')
        self.assertFalse(self.store.unread(1))  # one's own message
        other = self.post(2, 'hola Tuki')
        self.assertTrue(self.store.unread(1))
        self.assertFalse(self.store.unread(2))
        self.store.mark_read(1, other['id'])
        self.assertFalse(self.store.unread(1))
        self.store.mark_read(1, mine['id'])  # an older id never goes back
        self.assertFalse(self.store.unread(1))
        self.assertTrue(self.store.unread(3))  # never opened it

    def test_an_administrator_deletes_and_mutes(self):
        row = self.post(2, 'algo feo')
        self.store.delete(row['id'], 'Admin')
        self.assertEqual(self.store.recent(), [])
        with self.assertRaises(ChatError):
            self.store.delete(row['id'], 'Admin')
        self.store.mute(2, 'Otro', 'hour', 'Admin', 'spam')
        with self.assertRaises(ChatError) as muted:
            self.post(2, 'hola')
        self.assertEqual(muted.exception.code, 'muted')
        self.clock.now += 3600
        self.post(2, 'ya puedo')
        self.store.mute(2, 'Otro', 'forever', 'Admin')
        with self.assertRaises(ChatError) as forever:
            self.post(2, 'hola')
        self.assertEqual(forever.exception.code, 'muted_forever')
        self.assertEqual([m['account_id'] for m in self.store.mutes()], [2])
        self.store.unmute(2, 'Otro', 'Admin')
        self.post(2, 'de nuevo')
        self.assertEqual([entry['action'] for entry in self.store.log()], ['unmute', 'mute', 'mute', 'delete'])
        with self.assertRaises(ChatError):
            self.store.mute(2, 'Otro', 'year', 'Admin')


if __name__ == '__main__':
    unittest.main()
