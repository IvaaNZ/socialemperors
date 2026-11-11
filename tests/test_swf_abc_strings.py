"""Check the bytecode title translation keeps the audited game movie intact."""

from pathlib import Path
import unittest

from swf_abc_strings import ABC_STRING_TRANSLATIONS, localize_abc_strings, replace_abc_strings
from swf_localization import decode_swf, iter_tags, localize_swf
from swf_private_economy import patch_private_economy
from swf_tutorial import patch_tutorial

MOVIE = Path('assets/flash/SocialEmpires0926bsec.swf')


def abc_block(data):
    body, header_length = decode_swf(data)
    blocks = [payload[payload.index(b'\0', 4) + 1:] for code, payload, _ in iter_tags(body, header_length) if code == 82]
    assert len(blocks) == 1
    return blocks[0]


class SwfAbcStringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original = MOVIE.read_bytes()
        cls.patched = {language: patch_tutorial(patch_private_economy(localize_swf(original, language=language)))
                       for language in ('pt-BR', 'es')}

    def test_lore_title_is_translated_after_the_audited_patches(self):
        for language, patched in self.patched.items():
            with self.subTest(language=language):
                translated = abc_block(localize_abc_strings(patched, language))
                for english, local in ABC_STRING_TRANSLATIONS[language].items():
                    self.assertNotIn(english.encode('utf-8'), translated)
                    self.assertIn(local.encode('utf-8'), translated)

    def test_only_the_string_pool_entry_changes(self):
        source = abc_block(self.patched['es'])
        translated = abc_block(localize_abc_strings(self.patched['es'], 'es'))
        delta = len('Dioses y Colosos') - len('Gods & Colossus')
        self.assertEqual(len(translated), len(source) + delta)
        start = source.index(b'Gods & Colossus')
        # Only the one-byte U30 length before the string differs ahead of it.
        self.assertEqual(translated[:start - 1], source[:start - 1])
        self.assertEqual((source[start - 1], translated[start - 1]), (15, 16))
        self.assertEqual(translated[start + len('Gods & Colossus') + delta:], source[start + len('Gods & Colossus'):])

    def test_unknown_language_and_missing_constant(self):
        self.assertIs(localize_abc_strings(self.patched['es'], 'en'), self.patched['es'])
        with self.assertRaises(ValueError):
            replace_abc_strings(abc_block(self.patched['es']), {'No such constant': 'x'})


if __name__ == '__main__':
    unittest.main()
