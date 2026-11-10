"""Validate village labels without changing the player's account identity.

The game stores a village's visible name in ``playerInfo.map_names``.  The
separate ``playerInfo.name`` identifies the player and must not be renamed.
Callers that mutate a live village must hold the server's ``village_lock``.
"""

import unicodedata

import sessions
from portal_i18n import translate


MIN_VILLAGE_NAME_LENGTH = 2
MAX_VILLAGE_NAME_LENGTH = 32
DEFAULT_VILLAGE_NAME = 'Meu Império'
LEGACY_DEFAULT_VILLAGE_NAMES = frozenset(('My Empire', 'My empire'))
# Default labels a save may keep from another server language (pt-BR and es).
TRANSLATED_DEFAULT_VILLAGE_NAMES = frozenset(('Meu Império', 'Mi Imperio'))


class VillageNameError(ValueError):
    """A village label or map selection cannot safely be used by the game."""


def validate_village_name(value):
    """Return an NFC name suitable for a plain-text Flash or HTML label.

    Templates must still use their normal output escaping.  Angle brackets are
    rejected because the legacy player can render some labels as Flash HTML.
    """
    if not isinstance(value, str):
        raise VillageNameError('Informe um nome para a sua vila.')
    if any(unicodedata.category(character).startswith('C') or character in '\u2028\u2029' for character in value):
        raise VillageNameError('O nome da vila não pode conter caracteres de controle ou invisíveis.')
    name = unicodedata.normalize('NFC', value).strip()
    if not MIN_VILLAGE_NAME_LENGTH <= len(name) <= MAX_VILLAGE_NAME_LENGTH:
        raise VillageNameError(
            f'O nome da vila deve ter entre {MIN_VILLAGE_NAME_LENGTH} e '
            f'{MAX_VILLAGE_NAME_LENGTH} caracteres.'
        )
    if '<' in name or '>' in name:
        raise VillageNameError('Use um nome sem os símbolos < e >.')
    return name


def _map_name_location(village, map_index=None):
    """Find an existing map name, including saves with string map numbers."""
    if not isinstance(village, dict):
        raise VillageNameError('Vila não encontrada.')
    player = village.get('playerInfo', {})
    maps = village.get('maps', [])
    names = player.get('map_names')
    selection = player.get('default_map', 0) if map_index is None else map_index
    if isinstance(selection, bool) or not isinstance(selection, (int, str)):
        raise VillageNameError('Mapa da vila inválido.')
    try:
        index = int(selection)
    except (ValueError, TypeError):
        raise VillageNameError('Mapa da vila inválido.') from None
    if not isinstance(names, list) or not isinstance(maps, list) or not 0 <= index < min(len(names), len(maps)):
        raise VillageNameError('Mapa da vila inválido.')
    return names, index


def set_village_name(village, value, map_index=None):
    """Set a validated label in an existing village, without saving it.

    This is also the validator for the game's CMD_NAME_MAP command, whose
    command batch already saves after applying its changes.
    """
    name = validate_village_name(value)
    names, index = _map_name_location(village, map_index)
    names[index] = name
    return name


def rename_village(userid, value, map_index=None):
    """Rename and atomically save an owned village under the caller's lock.

    ``userid`` must come from the authenticated account, never a form field.
    The atomic save writer protects the disk file, and restoring the original
    label on failure keeps the live village consistent with that file.
    """
    village = sessions.session(userid)
    name = validate_village_name(value)
    names, index = _map_name_location(village, map_index)
    previous_name = names[index]
    if previous_name == name:
        return name
    names[index] = name
    try:
        sessions.save_session(userid)
    except Exception:
        names[index] = previous_name
        raise
    return name


def normalize_legacy_village_name(userid):
    """Translate only an exact default label of an owned home village.

    Custom names, secondary islands, and the player's name are preserved.
    The caller must hold the same lock used for every game mutation.
    """
    village = sessions.session(userid)
    names, index = _map_name_location(village)
    default_name = translate(DEFAULT_VILLAGE_NAME)
    if names[index] == default_name or names[index] not in LEGACY_DEFAULT_VILLAGE_NAMES | TRANSLATED_DEFAULT_VILLAGE_NAMES:
        return False
    rename_village(userid, default_name)
    return True
