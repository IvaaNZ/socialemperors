"""The "Pase" button inside the game, in its icon panel at the right (SE_SEASON_PASS=on only).

The same kind of icon as the "Clan" and "PvP" buttons (swf_clan_button.add_panel_button_to_abc): added after
them, so it sits below. A click calls ExternalInterface 'seOpenSeasonPass'; the page
(templates/js/season_pass_overlay.js) opens or closes the season pass window. The art is
templates/img/season_pass_button_<language>.png (tools/make_season_pass_button.py). Every new method runs inside
its own try/catch: it can never break the interface.
"""

import struct
import zlib

from swf_abc import Abc, AbcError
from swf_clan_button import add_panel_button_to_abc
from swf_duel_bridge import DO_ABC

SEASON_PASS_BUTTON_URL = '/img/season_pass_button_es.png'
CALLBACK = 'seOpenSeasonPass'


def add_season_pass_button_to_abc(abc, image_url=SEASON_PASS_BUTTON_URL):
    return add_panel_button_to_abc(abc, image_url, CALLBACK, '__addSeasonPassButton', '__seasonPassClick')


def add_season_pass_button(data, image_url=SEASON_PASS_BUTTON_URL):
    """Return the movie with the season pass button added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_season_pass_button_to_abc(Abc(payload[offset:]), image_url).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
