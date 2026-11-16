import os
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'WorldEditor'))

import sprites  # noqa: E402
import swf_hd_icons as hd  # noqa: E402
from swf_localization import decode_swf, iter_tags  # noqa: E402

GAME = ROOT / 'assets' / 'flash' / 'SocialEmpires0926bsec.swf'


def tags_of(movie):
    body, header_length = decode_swf(movie)
    return list(iter_tags(body, header_length))


class HdIcons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = GAME.read_bytes()
        cls.patched = hd.apply_hd_icons(cls.original, 'en')
        cls.before = tags_of(cls.original)
        cls.after = tags_of(cls.patched)

    def bitmaps(self, tags):
        return {struct.unpack_from('<H', payload)[0]: (code, payload) for code, payload, _ in tags if code in hd.BITMAP_TAGS}

    def fills(self, tags):
        out = {}
        for code, payload, _ in tags:
            if code in hd.SHAPE_TAGS:
                out[struct.unpack_from('<H', payload)[0]] = [(fill[1], fill[4]) for fill in hd._shape_fill_offsets(payload, code)]
        return out

    def test_only_safe_pictures_are_candidates(self):
        eligible = hd.eligible_bitmaps([(code, payload) for code, payload, _ in self.before])
        exported = set()
        for code, payload, _ in self.before:
            if code == 76:
                count, position = struct.unpack_from('<H', payload)[0], 2
                for _ in range(count):
                    exported.add(struct.unpack_from('<H', payload, position)[0])
                    position = payload.index(b'\0', position + 2) + 1
        self.assertFalse(eligible & exported)
        self.assertFalse(eligible & {31, 220})  # they have their own HD (swf_hd_art)
        self.assertIn(156, eligible)  # the gold ingot

    def test_icons_have_twice_the_pixels_and_their_fills_half_the_step(self):
        before, after = self.bitmaps(self.before), self.bitmaps(self.after)
        self.assertEqual(set(before), set(after))  # no picture added or lost
        data, first = sprites._decode_swf(self.patched)
        changed = [character_id for character_id in before if after[character_id][1] != before[character_id][1]]
        self.assertGreater(len(changed), 200)
        old_data, old_first = sprites._decode_swf(self.original)
        sizes = {}
        for movie_data, movie_first, key in ((old_data, old_first, 'old'), (data, first, 'new')):
            for code, start, length in sprites._tags(movie_data, movie_first, len(movie_data)):
                character_id = struct.unpack_from('<H', movie_data, start)[0] if code in hd.BITMAP_TAGS else None
                if character_id in (156, 329, 782, 783):
                    sizes[(key, character_id)] = sprites._bitmap(code, movie_data, start, length).size
        for character_id in (156, 329, 782, 783):
            old, new = sizes[('old', character_id)], sizes[('new', character_id)]
            self.assertEqual(new, (old[0] * hd.HD_FACTOR, old[1] * hd.HD_FACTOR))
        old_fills, new_fills = self.fills(self.before), self.fills(self.after)
        checked = 0
        for shape_id, fills in old_fills.items():
            for (bitmap, old_matrix), (_, new_matrix) in zip(fills, new_fills[shape_id]):
                if bitmap in changed:
                    for old_value, new_value in zip(old_matrix[:4], new_matrix[:4]):
                        self.assertLessEqual(abs(new_value * hd.HD_FACTOR - old_value), hd.HD_FACTOR)
                    self.assertEqual(old_matrix[4:], new_matrix[4:])  # same place
                    checked += 1
                else:
                    self.assertEqual(old_matrix, new_matrix)
        self.assertGreater(checked, 200)

    def test_translated_pictures_use_their_own_hd(self):
        self.assertEqual(hd.hd_path(147, 'es'), hd.HD_DIR / 'es' / '147.png')
        self.assertEqual(hd.hd_path(147, 'en'), hd.HD_DIR / '147.png')
        self.assertIsNone(hd.hd_path(999999, 'es'))

    def test_the_switch(self):
        previous = os.environ.get('SE_HD_ICONS')
        try:
            os.environ['SE_HD_ICONS'] = 'off'
            self.assertFalse(hd.hd_icons_enabled())
            os.environ['SE_HD_ICONS'] = 'on'
            self.assertTrue(hd.hd_icons_enabled())
        finally:
            if previous is None:
                os.environ.pop('SE_HD_ICONS', None)
            else:
                os.environ['SE_HD_ICONS'] = previous


if __name__ == '__main__':
    unittest.main()
