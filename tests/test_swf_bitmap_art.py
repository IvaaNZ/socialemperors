"""Check translated button artwork stays inside its original SWF bitmap slots."""

from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import swf_bitmap_art
from swf_bitmap_art import BITMAP_DIMENSIONS, BITMAP_RENDER_DIMENSIONS, load_bitmap_art, localize_bitmap_art
from swf_hd_art import HD_BITMAP_IDS, upgrade_shape_bitmap_fill
from swf_localization import localize_swf
from test_swf_localization import flattened_tags


class SwfBitmapArtTests(unittest.TestCase):
    def test_packaged_artwork_matches_logical_and_render_dimensions_and_pixel_format(self):
        for character_id, (width, height) in BITMAP_DIMENSIONS.items():
            with self.subTest(character_id=character_id):
                png = (swf_bitmap_art.ARTWORK_DIR / f'pt-BR-{character_id}.png').read_bytes()
                self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack_from('>II', png, 16), (width, height))
                original_pack = (swf_bitmap_art.ARTWORK_DIR / f'pt-BR-{character_id}.argb.zlib').read_bytes()
                self.assertEqual(len(zlib.decompress(original_pack)), width * height * 4)
                width, height = BITMAP_RENDER_DIMENSIONS[character_id]
                if character_id in HD_BITMAP_IDS:
                    png = (swf_bitmap_art.ARTWORK_DIR / f'pt-BR-{character_id}-hd.png').read_bytes()
                    self.assertEqual(struct.unpack_from('>II', png, 16), (width, height))
                self.assertEqual(len(zlib.decompress(load_bitmap_art(character_id))), width * height * 4)

    def test_only_allowlisted_bitmap_pixel_streams_change(self):
        original = Path('assets/flash/SocialEmpires0926bsec.swf').read_bytes()
        localized = localize_swf(original)
        source_tags = flattened_tags(original)
        localized_tags = flattened_tags(localized)
        self.assertEqual([code for code, _ in source_tags], [code for code, _ in localized_tags])
        changed_bitmaps = set()
        for (code, source), (_, translated) in zip(source_tags, localized_tags):
            if code == 36 and source != translated:
                character_id, bitmap_format, width, height = struct.unpack_from('<HBHH', source)
                self.assertIn(character_id, BITMAP_DIMENSIONS)
                self.assertEqual(source[:3], translated[:3])
                self.assertEqual(bitmap_format, 5)
                render_width, render_height = BITMAP_RENDER_DIMENSIONS[character_id]
                self.assertEqual(struct.unpack_from('<HH', translated, 3), (render_width, render_height))
                self.assertEqual(len(zlib.decompress(translated[7:])), render_width * render_height * 4)
                changed_bitmaps.add(character_id)
            elif code in (2, 22, 32, 83):
                self.assertEqual(translated, upgrade_shape_bitmap_fill(source, code))
            elif code not in (11, 33, 37):
                # Bytecode, fonts, all other bitmaps, placements and sprite
                # identifiers remain identical despite translated display text.
                self.assertEqual(source, translated)
        self.assertEqual(changed_bitmaps, set(BITMAP_DIMENSIONS))
        self.assertEqual(original, Path('assets/flash/SocialEmpires0926bsec.swf').read_bytes())

    def test_unknown_bitmaps_and_explicit_text_catalog_keep_original_images(self):
        unknown = struct.pack('<HBHH', 123, 5, 1, 1) + b'unchanged pixels'
        self.assertIs(localize_bitmap_art(unknown), unknown)
        original = Path('assets/flash/SocialEmpires0926bsec.swf').read_bytes()
        localized = localize_swf(original, {})
        self.assertEqual(flattened_tags(original), flattened_tags(localized))

    def test_wrong_dimensions_and_invalid_pixels_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'original SWF bitmap layout'):
            localize_bitmap_art(struct.pack('<HBHH', 220, 5, 1, 1))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(swf_bitmap_art, 'ARTWORK_DIR', Path(directory)):
                packed = Path(directory) / 'pt-BR-220-hd.argb.zlib'
                packed.write_bytes(zlib.compress(b'\0' * 4))
                with self.assertRaisesRegex(ValueError, 'artwork size'):
                    load_bitmap_art(220)
                width, height = BITMAP_RENDER_DIMENSIONS[220]
                packed.write_bytes(zlib.compress(b'\x00\xff\x00\x00' * (width * height)))
                with self.assertRaisesRegex(ValueError, 'premultiplied ARGB'):
                    load_bitmap_art(220)

    def test_spanish_buttons_have_their_own_art_and_share_identical_words(self):
        for character_id in (220, 3967):
            with self.subTest(character_id=character_id):
                spanish = load_bitmap_art(character_id, 'es')
                self.assertNotEqual(spanish, load_bitmap_art(character_id, 'pt-BR'))
                width, height = BITMAP_RENDER_DIMENSIONS[character_id]
                self.assertEqual(len(zlib.decompress(spanish)), width * height * 4)
        # "Construir" and "ALIADO" are the same words in Spanish.
        for character_id in (31, 3948):
            with self.subTest(character_id=character_id):
                self.assertEqual(load_bitmap_art(character_id, 'es'), load_bitmap_art(character_id, 'pt-BR'))

    def test_spanish_movie_replaces_its_own_drawn_english_buttons(self):
        from swf_bitmap_art import LANGUAGE_BITMAP_DIMENSIONS
        original = Path('assets/flash/SocialEmpires0926bsec.swf').read_bytes()
        spanish_only = LANGUAGE_BITMAP_DIMENSIONS['es']

        def bitmaps(data):
            found = {}
            for code, payload in flattened_tags(data):
                if code in (6, 35, 36) and len(payload) >= 2:
                    found[struct.unpack_from('<H', payload)[0]] = (code, payload)
            return found

        source = bitmaps(original)
        spanish = bitmaps(localize_swf(original, language='es'))
        portuguese = bitmaps(localize_swf(original, language='pt-BR'))
        for character_id, (width, height) in spanish_only.items():
            with self.subTest(character_id=character_id):
                code, payload = spanish[character_id]
                self.assertEqual(code, 36)
                self.assertEqual(struct.unpack_from('<BHH', payload, 2), (5, width, height))
                self.assertNotEqual(payload, source[character_id][1])
                # Portuguese keeps the original English art for these buttons.
                self.assertEqual(portuguese[character_id], source[character_id])


if __name__ == '__main__':
    unittest.main()
