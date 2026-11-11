"""Small placement fixes for translated layouts in the derived game movie.

Daily bonus popup (PopupNewDailyMC, sprite 2135): the green ticks of the days
already collected (mcVist_1..5) sit over the bottom of each day's prize label.
"250 gold" mostly survived that in English, but the translated "250 de oro"
loses its last word. The ticks move up so they cover the prize icon instead,
which still marks the day as collected and leaves the label readable.
Only those five PlaceObject2 matrices change; everything else keeps its bytes.
"""

import struct

from swf_hd_art import encode_matrix, read_matrix

DAILY_POPUP_SPRITE = 2135
GREEN_TICK = 485
TICK_NAMES = tuple(f'mcVist_{day}'.encode() for day in range(1, 6))
TICK_SHIFT_Y = -500  # twips (25 px)
# Original translations, used to reject an unknown movie instead of guessing.
ORIGINAL_TICK_Y = {b'mcVist_1': 387, b'mcVist_2': 452, b'mcVist_3': 387, b'mcVist_4': 387, b'mcVist_5': 387}
PLACE_OBJECT2 = 26
HAS_MATRIX_CHARACTER_NAME = 0x26


def _move_tick(payload):
    """Return the PlaceObject2 payload with the tick raised, or None if not a tick."""
    if payload[0] != HAS_MATRIX_CHARACTER_NAME or struct.unpack_from('<H', payload, 3)[0] != GREEN_TICK:
        return None
    matrix, end = read_matrix(payload, 5)
    name = payload[end:].rstrip(b'\0')
    if name not in TICK_NAMES or payload[end:] != name + b'\0':
        return None
    if matrix[5] != ORIGINAL_TICK_Y[name]:
        raise ValueError(f'Unexpected original position for {name.decode()}')
    moved = matrix[:5] + (matrix[5] + TICK_SHIFT_Y,)
    return payload[:5] + encode_matrix(moved) + payload[end:]


def fix_sprite_layout(sprite_payload, rewrite):
    """Apply placement fixes to one DefineSprite payload (ID + frames + tags).

    `rewrite(code, payload)` encodes a tag the way the caller's stream does.
    """
    from swf_localization import iter_tags
    if struct.unpack_from('<H', sprite_payload)[0] != DAILY_POPUP_SPRITE:
        return sprite_payload
    tags = []
    moved = 0
    for code, payload, long_length in iter_tags(sprite_payload[4:]):
        if code == PLACE_OBJECT2:
            fixed = _move_tick(payload)
            if fixed is not None:
                payload = fixed
                moved += 1
        tags.append(rewrite(code, payload, long_length))
    if moved != len(TICK_NAMES):
        raise ValueError('Daily bonus popup ticks do not match the pinned movie')
    return sprite_payload[:4] + b''.join(tags)
