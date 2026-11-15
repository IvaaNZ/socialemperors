"""Day and night on the village (SE_DAY_NIGHT, on by default): the page tints the map by Argentina's hour.

Point 23 of block E. The owner chose a visual cycle that follows the real hour in Argentina, with rain or snow
by season (the particles are drawn by the page, templates/js/game.js). This edit adds, without changing any
original instruction:

  * Base.__setDayLight(red, green, blue): sets the colour of the world layer (Base.buildingLayer, the Sprite
    Base.init creates for the map, its buildings and units; Base.Iso is the engine, not a display object) to
    new ColorTransform(red, green, blue, 1). The game's HUD and windows are other layers and keep their colours.
    Returns false when there is no layer yet;
  * Base.__registerDayLight(), called first in Base.init:
    ExternalInterface.addCallback('seSetDayLight', __setDayLight).

Both run inside their own try/catch: an error leaves the map as it is.
"""

import struct
import zlib

from swf_abc import Abc, AbcError, u30
from swf_duel_bridge import DO_ABC, assemble, prepend, used_multiname
from swf_range_overlay import OPCODE_BY_NAME, _qname

CALLBACK = 'seSetDayLight'
SET_METHOD = '__setDayLight'
REGISTER_METHOD = '__registerDayLight'
NAMES = {'ExternalInterface': 'flash.external', 'available': '', 'addCallback': '',
         'ColorTransform': 'flash.geom', 'transform': '', 'colorTransform': ''}


def add_daylight_to_abc(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == SET_METHOD for t in base['traits']):
        raise AbcError('The day and night tint is already present')
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    layer = used_multiname(abc, abc.method_of('Base', 'init'), 'getproperty', 'buildingLayer')
    callback = abc.add_string(CALLBACK)
    reference = abc.body_of(abc.method_of('Base', 'DebugUnitTiles'))

    def method(name, params, program, max_stack, local_count):
        code, labels = assemble(program)
        index = len(abc.methods)
        abc.methods.append({'return_type': 0, 'param_types': [0] * params, 'name': abc.add_string(name), 'flags': 0,
                            'options': None, 'param_names': None})
        abc.bodies.append({'method': index, 'max_stack': max_stack, 'local_count': local_count,
                           'init_scope_depth': reference['init_scope_depth'],
                           'max_scope_depth': reference['init_scope_depth'] + 1,
                           'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                           'traits': []})
        qname = abc.add_qname('', name)
        base['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})
        return qname

    def guarded(program):
        return [('getlocal0',), ('pushscope',), ('label:', 'try')] + program + [
            ('label:', 'try_end'),
            ('jump', 'done'),
            ('label:', 'catch'),
            ('getlocal0',), ('pushscope',),  # a handler starts with an empty scope stack
            ('pop',),
            ('label:', 'done'),
        ]

    # Base.__setDayLight(red, green, blue): Boolean -- locals 1-3 the multipliers, 4 the map, 5 the colour.
    set_light = method(SET_METHOD, 3, guarded([
        ('getlocal0',), ('getproperty', layer), ('coerce_a',), ('setlocal', 4),
        ('getlocal', 4), ('iffalse', 'no'),
        ('findpropstrict', n['ColorTransform']), ('getlocal1',), ('getlocal2',), ('getlocal3',), ('pushbyte', 1),
        ('constructprop', n['ColorTransform'], 4), ('coerce_a',), ('setlocal', 5),
        ('getlocal', 4), ('getproperty', n['transform']), ('getlocal', 5), ('setproperty', n['colorTransform']),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'),
    ]) + [('pushfalse',), ('returnvalue',)], 6, 6)

    # Base.__registerDayLight(): the page's way in.
    register = method(REGISTER_METHOD, 0, guarded([
        ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
        ('getlex', n['ExternalInterface']), ('pushstring', callback), ('getlocal0',), ('getproperty', set_light),
        ('callpropvoid', n['addCallback'], 2),
    ]) + [('returnvoid',)], 4, 1)

    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(register) + u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_daylight(data):
    """Return the movie with the day and night tint added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_daylight_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
