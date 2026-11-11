"""Portuguese display text for the legacy client, independent of engine data.

Only explicitly listed presentation fields are localized. Image filenames,
script names, resource codes, unit IDs, prices and other rules remain intact.
Uncatalogued text from a new mod falls back to its original wording.
"""

import copy
import json
from pathlib import Path

from bundle import CONFIG_DIR


DISPLAY_FIELDS = {
    'localization_strings': frozenset({'text'}),
    'categories': frozenset({'name'}),
    'items': frozenset({'name', 'achievement_desc'}),
    'missions': frozenset({'title', 'description', 'hint'}),
    'levels': frozenset({'name'}),
    'honor_levels': frozenset({'rank'}),
    'neighbor_assists': frozenset({'task', 'action', 'notification'}),
    'findable_items': frozenset({'title', 'description'}),
    'magics': frozenset({'name', 'description'}),
    'social_items': frozenset({'workers'}),
    'tournament_type': frozenset({'name'}),
    'level_up_tips': frozenset({'text'}),
}


# Languages with translated game catalogs. English is the game's own source text.
SUPPORTED_LOCALES = ('pt-BR', 'es')
# Languages a player can choose (portal and game), in selector order.
PLAYER_LANGUAGES = ('es', 'pt-BR', 'en')
# Each language is named in itself in the language selector.
LANGUAGE_NAMES = {'es': 'Español', 'pt-BR': 'Português', 'en': 'English'}
# Flag images in templates/img/flags/ (Brazilian Portuguese, neutral Spanish, English).
LANGUAGE_FLAGS = {'es': 'es.svg', 'pt-BR': 'br.svg', 'en': 'us.svg'}
# Specific item names take precedence over short generic UI wording.
CATALOG_PARTS = ('core', 'interface', 'extended', 'collections', 'missions', 'auxiliary', 'items')


def normalize_locale(language):
    normalized = str(language).lower().replace('_', '-')
    if normalized in {'pt', 'pt-br'}:
        return 'pt-BR'
    if normalized == 'es' or normalized.startswith('es-'):
        return 'es'
    return 'en'


def load_catalog(language='pt-BR'):
    """Load source-text keys so config patches retain their original IDs."""
    locale = normalize_locale(language)
    if locale not in SUPPORTED_LOCALES:
        return {}
    catalog = {}
    for filename in (f'{locale}-{part}.json' for part in CATALOG_PARTS):
        with (Path(CONFIG_DIR) / 'locales' / filename).open(encoding='utf-8') as stream:
            catalog.update(json.load(stream))
    return catalog


def walk_display_fields(value, fields):
    """Yield writable text fields, including the legacy nested patch arrays."""
    if isinstance(value, list):
        for item in value:
            yield from walk_display_fields(item, fields)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in fields and isinstance(item, str):
                yield value, key, item
            elif isinstance(item, (dict, list)):
                yield from walk_display_fields(item, fields)


def localize_game_config(config, language='pt-BR'):
    localized = copy.deepcopy(config)
    catalog = load_catalog(language)
    for section, fields in DISPLAY_FIELDS.items():
        for entry, key, source in walk_display_fields(localized.get(section), fields):
            entry[key] = catalog.get(source, source)
    return localized
