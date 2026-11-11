"""Check the Monday button lettering images and the daily bonus tick placement."""

from pathlib import Path
import struct
import unittest
import zlib

from swf_hd_art import read_matrix
from swf_layout_fixes import DAILY_POPUP_SPRITE, ORIGINAL_TICK_Y, TICK_SHIFT_Y
from swf_localization import decode_swf, iter_tags, localize_swf
from swf_vector_art import VECTOR_ART, bitmap_rect_shape, bitmap_size, load_vector_art, read_bounds

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def top_level(data):
    body, header = decode_swf(data)
    return list(iter_tags(body, header))


def sprite_ticks(data):
    for code, payload, _ in top_level(data):
        if code == 39 and struct.unpack_from('<H', payload)[0] == DAILY_POPUP_SPRITE:
            ticks = {}
            for inner, place, _ in iter_tags(payload[4:]):
                if inner == 26 and place[0] == 0x26 and struct.unpack_from('<H', place, 3)[0] == 485:
                    matrix, end = read_matrix(place, 5)
                    ticks[place[end:].rstrip(b'\0')] = matrix
            return ticks
    raise AssertionError('Daily popup sprite not found')


class VectorArtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = MOVIE.read_bytes()
        cls.spanish = localize_swf(cls.original, language='es')
        cls.portuguese = localize_swf(cls.original, language='pt-BR')

    def test_packaged_images_match_their_shape_bounds(self):
        for shape_id, (_, bounds) in VECTOR_ART['es'].items():
            with self.subTest(shape_id=shape_id):
                width, height = bitmap_size(bounds)
                self.assertEqual(len(zlib.decompress(load_vector_art(shape_id, 'es'))), width * height * 4)

    def test_rectangle_shape_round_trips_its_bounds(self):
        for shape_id, (bitmap_id, bounds) in VECTOR_ART['es'].items():
            with self.subTest(shape_id=shape_id):
                payload = bitmap_rect_shape(shape_id, bitmap_id, bounds)
                self.assertEqual(read_bounds(payload), bounds)

    def test_spanish_movie_defines_each_bitmap_before_its_shape(self):
        new_ids = {bitmap_id for bitmap_id, _ in VECTOR_ART['es'].values()}
        source_ids = {struct.unpack_from('<H', payload)[0] for _, payload, _ in top_level(self.original) if len(payload) >= 2}
        self.assertFalse(new_ids & source_ids)
        defined = set()
        replaced = {}
        for code, payload, _ in top_level(self.spanish):
            if code == 36 and struct.unpack_from('<H', payload)[0] in new_ids:
                defined.add(struct.unpack_from('<H', payload)[0])
            if code in (2, 22, 32, 83):
                shape_id = struct.unpack_from('<H', payload)[0]
                if shape_id in VECTOR_ART['es']:
                    bitmap_id, bounds = VECTOR_ART['es'][shape_id]
                    self.assertEqual(code, 32)
                    self.assertIn(bitmap_id, defined)
                    self.assertEqual(read_bounds(payload), bounds)
                    replaced[shape_id] = payload
        self.assertEqual(set(replaced), set(VECTOR_ART['es']))

    def test_portuguese_keeps_the_original_shapes(self):
        source = {struct.unpack_from('<H', p)[0]: p for c, p, _ in top_level(self.original) if c in (2, 22, 32, 83)}
        localized = {struct.unpack_from('<H', p)[0]: p for c, p, _ in top_level(self.portuguese) if c in (2, 22, 32, 83)}
        for shape_id in VECTOR_ART['es']:
            self.assertEqual(localized[shape_id], source[shape_id])

    def test_daily_ticks_move_up_in_both_languages_only(self):
        source = sprite_ticks(self.original)
        self.assertEqual({name: matrix[5] for name, matrix in source.items()}, ORIGINAL_TICK_Y)
        for movie in (self.spanish, self.portuguese):
            moved = sprite_ticks(movie)
            for name, matrix in source.items():
                self.assertEqual(moved[name][:5], matrix[:5])
                self.assertEqual(moved[name][5], matrix[5] + TICK_SHIFT_Y)


if __name__ == '__main__':
    unittest.main()
