"""Check real game translations without changing the legacy simulation data."""

from collections import Counter
import copy
import json
from pathlib import Path
import re
import unittest

from get_game_config import get_game_config, get_name_from_item_id
from localization import (
    DISPLAY_FIELDS, SUPPORTED_LOCALES, load_catalog, localize_game_config,
    normalize_locale, walk_display_fields,
)
from swf_localization import load_swf_catalog


class LocalizationTests(unittest.TestCase):
    def test_complete_desktop_catalog_preserves_substitutions_and_markup(self):
        original = get_game_config()
        for locale in SUPPORTED_LOCALES:
            catalog = load_catalog(locale)
            self._assert_complete_catalog(locale, catalog, original)

    def _assert_complete_catalog(self, locale, catalog, original):
        for section, fields in DISPLAY_FIELDS.items():
            with self.subTest(locale=locale, section=section):
                for _, key, source in walk_display_fields(original[section], fields):
                    if not source:
                        continue
                    self.assertIn(source, catalog, (section, key, source))
                    translated = catalog[source]
                    self.assertEqual(
                        Counter(re.findall(r'#\d+#', source)),
                        Counter(re.findall(r'#\d+#', translated)),
                        source,
                    )
                    self.assertEqual(
                        Counter(re.findall(r'<[^>]+>', source)),
                        Counter(re.findall(r'<[^>]+>', translated)),
                        source,
                    )
                    if key == 'workers':
                        self.assertEqual(source.count(','), translated.count(','))

    def test_only_presentation_fields_change_and_english_engine_stays_intact(self):
        original = get_game_config()
        localized = get_game_config('pt-BR')
        self.assertIsNot(original, localized)
        self.assertEqual(get_name_from_item_id(1), 'House I')
        self.assertEqual(localized['items'][0]['name'], 'Casa I')
        self.assertEqual(localized['localization_strings'][0]['text'], 'Boas-vindas ao seu império!')
        self.assertEqual(original['localization_strings'][0]['text'], 'Welcome to your Empire!')
        # Replacing text in both copies must produce identical mechanics,
        # technical identifiers, asset paths, array shapes and patch nesting.
        mechanics = []
        for config in (original, localized):
            stripped = copy.deepcopy(config)
            for section, fields in DISPLAY_FIELDS.items():
                for entry, key, _ in walk_display_fields(stripped[section], fields):
                    entry[key] = '<display text>'
            mechanics.append(stripped)
        self.assertEqual(mechanics[0], mechanics[1])

    def test_supported_locale_aliases_and_unknown_mod_text_fall_back(self):
        for alias in ('pt', 'pt-br', 'pt_BR', 'pt-BR'):
            self.assertIs(get_game_config(alias), get_game_config('pt-BR'))
        self.assertIs(get_game_config('unsupported'), get_game_config())
        custom = {'items': [{'name': 'New Mod Unit', 'id': 900000, 'cost': 12}]}
        self.assertEqual(localize_game_config(custom), custom)
        # Localization returns independent data even for new mod fields.
        self.assertIsNot(localize_game_config(custom)['items'], custom['items'])

    def test_spanish_catalogs_mirror_portuguese_sources(self):
        for portuguese_file in sorted((Path(__file__).resolve().parent.parent / 'config' / 'locales').glob('pt-BR-*.json')):
            spanish_file = portuguese_file.with_name(portuguese_file.name.replace('pt-BR-', 'es-'))
            with self.subTest(catalog=spanish_file.name):
                portuguese = json.loads(portuguese_file.read_text(encoding='utf-8'))
                spanish = json.loads(spanish_file.read_text(encoding='utf-8'))
                self.assertEqual(list(spanish), list(portuguese))
                for source, translated in spanish.items():
                    self.assertTrue(translated, source)
                    for pattern in (r'#\d+#', r'<[^>]+>'):
                        self.assertEqual(Counter(re.findall(pattern, source)), Counter(re.findall(pattern, translated)), source)

    def test_spanish_locale_aliases_and_localized_text(self):
        for alias in ('es', 'ES', 'es-AR', 'es_419'):
            self.assertEqual(normalize_locale(alias), 'es')
            self.assertIs(get_game_config(alias), get_game_config('es'))
        spanish = get_game_config('es')
        self.assertEqual(spanish['items'][0]['name'], 'Casa I')
        self.assertEqual(spanish['localization_strings'][0]['text'], '¡Bienvenido a tu imperio!')
        self.assertEqual(get_name_from_item_id(1), 'House I')
        self.assertEqual(load_swf_catalog('es')['Next'], 'Siguiente')
        self.assertEqual(load_swf_catalog('en'), {})

    def test_client_text_ids_missing_from_the_2012_config_are_restored(self):
        # The client asks for these ids by number; without them its buttons stay blank.
        def flat(items):
            for item in items:
                if isinstance(item, list):
                    yield from flat(item)
                else:
                    yield item
        texts = {entry['id']: entry['text'] for entry in flat(get_game_config('es')['localization_strings'])}
        self.assertEqual(texts[1548], 'Usar')
        self.assertEqual(texts[1549], 'Vender')
        self.assertEqual(texts[1560], 'Todo')
        self.assertEqual(texts[1561], 'Más dinero')
        entries = list(flat(get_game_config()['localization_strings']))
        self.assertEqual({entry['id']: entry['name'] for entry in entries}[1548], 'POPUP_STORAGE_USE')
        self.assertEqual(len(entries), len({entry['id'] for entry in entries}), 'text ids must stay unique')

    def test_quest_battle_names_are_translated_without_changing_the_files(self):
        from quests import get_quest_map
        quest, status = get_quest_map('100000020', 'es')
        self.assertEqual(status, 200)
        self.assertEqual(quest['playerInfo']['name'], 'Aventura Troll')
        self.assertIn('Aventura', [game_map.get('n') for game_map in quest['privateState']['maps']])
        original, _ = get_quest_map('100000020')
        self.assertEqual(original['playerInfo']['name'], 'Troll Quest')


if __name__ == '__main__':
    unittest.main()
