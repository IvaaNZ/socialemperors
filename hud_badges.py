"""The art of the "Clan", "PvP" and "Pase" buttons in the game's icon panel (SE_HUD_BADGES).

Off: the old shields (templates/img/clan_button_<lang>.png, pvp_button_<lang>.png, season_pass_button_<lang>.png).
On: the new "cristal" badges (templates/img/hud_badge_<kind>_<lang>.png, drawn by tools/make_hud_badges.py): a dark
rounded square with a ring in the button's colour and a shield inside. Clan blue with a tower, PvP red with crossed
swords, Pase purple with a crown. Same size as the old art (60 x 72), so the movie edits do not change.
"""

import os
from pathlib import Path

OLD_PREFIX = {'clan': 'clan_button', 'pvp': 'pvp_button', 'pass': 'season_pass_button'}
NEW_PREFIX = {'clan': 'hud_badge_clan', 'pvp': 'hud_badge_pvp', 'pass': 'hud_badge_pass'}


def hud_badges_enabled():
    return os.environ.get('SE_HUD_BADGES', 'off').strip().lower() in ('on', '1', 'true', 'yes')


def hud_group_enabled():
    """SE_HUD_GROUP: the Clan, PvP and Pase buttons fold into one "Modos" button on the page (templates/js/game.js)."""
    return os.environ.get('SE_HUD_GROUP', 'off').strip().lower() in ('on', '1', 'true', 'yes')


def button_art(kind, locale, img_dir, enabled=None):
    """The URL of a button's art for a language; falls back to Spanish, and to the old art if a new file is missing."""
    if enabled is None:
        enabled = hud_badges_enabled()
    img_dir = Path(img_dir)
    prefixes = ([NEW_PREFIX[kind]] if enabled else []) + [OLD_PREFIX[kind]]
    for prefix in prefixes:
        for name in (f'{prefix}_{locale}.png', f'{prefix}_es.png'):
            if (img_dir / name).exists():
                return '/img/' + name
    return f'/img/{OLD_PREFIX[kind]}_es.png'


# The "Modos" row (SE_HUD_GROUP): each button's page callback (the same the game's button calls) and its name.
GROUP_CALLBACKS = {'clan': 'seOpenClan', 'pvp': 'seOpenPvp', 'pass': 'seOpenSeasonPass'}
GROUP_LABELS = {'clan': {'es': 'Clan', 'en': 'Clan', 'pt-BR': 'Clã'}, 'pvp': {'es': 'PvP', 'en': 'PvP', 'pt-BR': 'PvP'},
                'pass': {'es': 'Pase', 'en': 'Pass', 'pt-BR': 'Passe'}}


def group_buttons(locale, img_dir, kinds):
    """The row's buttons, in order (Clan, PvP, Pase), for the features that are on (`kinds`)."""
    return [{'kind': kind, 'url': button_art(kind, locale, img_dir), 'callback': GROUP_CALLBACKS[kind],
             'label': GROUP_LABELS[kind].get(locale, GROUP_LABELS[kind]['es'])}
            for kind in ('clan', 'pvp', 'pass') if kind in kinds]
