"""Translate the web portal and server messages from their Portuguese source.

Portuguese remains the source language of templates and Python messages, so
existing behaviour is unchanged when no catalog exists for the active locale.
Catalog keys are the exact Portuguese text. A key containing ``{name}``
placeholders also matches messages built with dynamic values; matched values
are translated in turn, so labels such as ``dinheiro`` stay consistent.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from bundle import CONFIG_DIR
from localization import normalize_locale


SOURCE_LOCALE = 'pt-BR'
_PLACEHOLDER = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')
_active_locale = SOURCE_LOCALE


def portal_catalog_path(locale):
    return Path(CONFIG_DIR) / 'locales' / f'{locale}-portal.json'


@lru_cache(maxsize=None)
def load_portal_catalog(locale):
    """Return (exact entries, placeholder patterns) for a locale."""
    path = portal_catalog_path(locale)
    if locale == SOURCE_LOCALE or not path.exists():
        return {}, ()
    with path.open(encoding='utf-8') as stream:
        catalog = json.load(stream)
    patterns = []
    for source, translated in catalog.items():
        if not _PLACEHOLDER.search(source):
            continue
        regex = ''.join(
            f'(?P<{part}>.+?)' if index % 2 else re.escape(part)
            for index, part in enumerate(_PLACEHOLDER.split(source))
        )
        patterns.append((re.compile(f'^{regex}$', re.S), translated))
    return catalog, tuple(patterns)


def set_portal_language(language):
    global _active_locale
    locale = normalize_locale(language)
    _active_locale = SOURCE_LOCALE if locale == 'en' else locale


def portal_language():
    return _active_locale


def translate(text, **values):
    """Translate Portuguese portal text, then fill optional named values."""
    if not isinstance(text, str) or not text:
        return text
    catalog, patterns = load_portal_catalog(_active_locale)
    translated = catalog.get(text)
    if translated is None:
        translated = text
        for pattern, template in patterns:
            match = pattern.match(text)
            if match:
                translated = template.format(**{name: translate(value) for name, value in match.groupdict().items()})
                break
    return translated.format(**values) if values else translated


def translations_for(texts):
    """Return only the entries a client script needs for the active locale."""
    return {text: translate(text) for text in texts if translate(text) != text}
