"""Draw each unit's attack area in battles (blue: yours, red: enemies).

The game has no attack-area display, so the derived movie adds one method to
the main game class `Base`, `__drawRanges`, called at the start of every frame
update (`Base.UpdateGame2`). Following the game's own debug drawer
(`Base.DebugUnitTiles`), it walks `Base.Iso.vIsoElements` and draws on one
Shape inside `buildingLayer`, moved every frame right below the lowest unit it
draws: the ground (large tiles and land expansions) is that layer's first
children and the game re-sorts the rest, so this keeps the drawing above the
ground and below those units:

  * your units that are selected (they carry the selection pedestal,
    `iconoSeleccionado`): blue area;
  * enemy units with one of your selected units within their reach plus
    NEAR_TILES (measured from the units' current positions): red area;
  * in battles (attacks, adventures, survival, tournaments), enemy towers
    and castles — buildings with attack and range — always show their red
    area, so you can see the ground they cover.

The area is the game's own range test (`BBox.intersectsRange`): a square of
iAttackRange tiles around the unit's tile, which on the isometric ground is a
rhombus of half-width range x EI_TILE_WIDTH_PIXELS and half-height range x
EI_TILE_HEIGHT_PIXELS. A Shape is not interactive and sits below every unit,
so clicks still reach units and the ground.

Every name the new code uses is an existing public multiname of the game; the
edit only appends to the constant pool, adds one slot and one method to Base,
and prepends one call to UpdateGame2. It runs after the audited byte patches.
"""

import struct
import zlib

from swf_abc import Abc, AbcError, OPCODES, PACKAGE_NAMESPACE, s24, u30

BLUE = 0x2F80ED
RED = 0xE53935
LINE_ALPHA = 0.85
FILL_ALPHA = 0.14
LINE_WIDTH = 2
NEAR_TILES = 3
BATTLE_MODES = (3, 6)  # Constants.GAME_MODE_ASSAULT .. GAME_MODE_TOURNAMENT (campaign, survival between)
SHAPE_SLOT = '__rangeShape'
DRAW_METHOD = '__drawRanges'
DO_ABC = 82

# Public names the new code needs -> (expected multiname index in the pinned game, namespace).
NAMES = {
    'buildingLayer': '', 'Base': 'core', 'Iso': '', 'vIsoElements': '', 'IsoFightingElement': 'core.isoengine',
    'IsoUnit': 'core.isoengine', 'eContainer': '', 'PlayerID': '', 'Constants': 'core', 'PLAYER_ENEMY': '',
    'PLAYER_SELF': '', 'x': '', 'y': '', 'buildingReference': '', 'Config': 'core', 'EI_TILE_WIDTH_PIXELS': '',
    'EI_TILE_HEIGHT_PIXELS': '', 'addChildAt': '', 'iconoSeleccionado': '', 'iAttackRange': '',
    'Main': '', 'gameMode': '', 'uiAttack': '',
    'graphics': '', 'clear': '', 'lineStyle': '', 'beginFill': '', 'endFill': '', 'moveTo': '', 'lineTo': '',
    'Shape': 'flash.display', 'parent': '', 'length': '', 'getChildIndex': '', 'setChildIndex': '',
    'numChildren': '', 'addChild': '',
}
BUILTIN_PUSH = ('push', 'http://adobe.com/AS3/2006/builtin')

OPCODE_BY_NAME = {name: code for code, (name, _) in OPCODES.items()}


def _qname(abc, name, package):
    """Index of an existing public QName (namespace kind package) for name."""
    for index, entry in enumerate(abc.multinames, 1):
        if entry[0] == 0x07 and abc.string(entry[2]) == name:
            kind, ns_name = abc.namespaces[entry[1] - 1]
            if kind in (PACKAGE_NAMESPACE, 0x08) and abc.string(ns_name) == package:
                return index
    raise AbcError(f'Public name {package}.{name} not found in the game code')


def _add_int(abc, value):
    encoded = u30(value)
    if encoded in abc.ints:
        return abc.ints.index(encoded) + 1
    abc.ints.append(encoded)
    return len(abc.ints)


def _add_double(abc, value):
    encoded = struct.pack('<d', value)
    if encoded in abc.doubles:
        return abc.doubles.index(encoded) + 1
    abc.doubles.append(encoded)
    return len(abc.doubles)


def assemble(program):
    """Encode [('op', operands...) | ('label:', name)] with branch labels resolved."""
    branch_ops = {'jump', 'iftrue', 'iffalse', 'ifeq', 'ifne', 'iflt', 'ifle', 'ifgt', 'ifge',
                  'ifnlt', 'ifnle', 'ifngt', 'ifnge', 'ifstricteq', 'ifstrictne'}

    def encode(item, labels, position):
        name, *operands = item
        code = bytes([OPCODE_BY_NAME[name]])
        if name in branch_ops:
            target = labels.get(operands[0], position + 4)
            return code + s24(target - (position + 4))
        kinds = OPCODES[OPCODE_BY_NAME[name]][1]
        for kind, value in zip(kinds, operands):
            code += bytes([value]) if kind == 'u8' else u30(value)
        return code

    labels = {}
    for _ in range(2):  # branch encodings have a fixed size, so two passes settle every offset
        position, out = 0, bytearray()
        for item in program:
            if item[0] == 'label:':
                labels[item[1]] = position
                continue
            encoded = encode(item, labels, position)
            out += encoded
            position += len(encoded)
    return bytes(out)


def _filters(n, el, skip):
    """Jump to `skip` unless local `el` is a placed fighting unit outside buildings."""
    tag = f'ok_{skip}_{el}'
    return [
        ('getlocal', el), ('getlex', n['IsoFightingElement']), ('istypelate',), ('iffalse', skip),
        ('getlocal', el), ('getlex', n['IsoUnit']), ('istypelate',), ('iffalse', tag),
        ('getlocal', el), ('getproperty', n['eContainer']), ('pushnull',), ('ifne', skip),
        ('label:', tag),
        ('getlocal', el), ('getproperty', n['buildingReference']), ('pushnull',), ('ifeq', skip),
    ]


def _loop(collection_ops, obj, idx, el, body, tag):
    """for each (el in collection) { body }  (body may jump to 'next_' + tag)."""
    return ([('pushbyte', 0), ('setlocal', idx)] + collection_ops +
            [('coerce_a',), ('setlocal', obj), ('jump', 'next_' + tag),
             ('label:', 'body_' + tag), ('label',),
             ('getlocal', obj), ('getlocal', idx), ('nextvalue',), ('coerce_a',), ('setlocal', el)]
            + body +
            [('label:', 'next_' + tag), ('hasnext2', obj, idx), ('iftrue', 'body_' + tag),
             ('label:', 'done_' + tag), ('kill', obj), ('kill', idx)])


def build_draw_method(abc, slot):
    """Bytecode of Base.__drawRanges (see the module docstring)."""
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    push = _qname(abc, *BUILTIN_PUSH)
    blue, red = _add_int(abc, BLUE), _add_int(abc, RED)
    line_alpha, fill_alpha = _add_double(abc, LINE_ALPHA), _add_double(abc, FILL_ALPHA)
    # locals: 1 layer, 2 shape, 3 tile width, 4 tile height, 5 selected units,
    # 6 element, 7/8 loop index/object, 9 show, 10 colour, 11 range, 12 selected element,
    # 13/14 inner loop index/object, 15 dx, 16 dy, 17 graphics, 18 cx, 19 cy, 20 half width, 21 half height,
    # 22 child index, 23 lowest child index among the units drawn (-1: none),
    # 24 game mode, 25 in a battle
    elements = [('getlex', n['Base']), ('getproperty', n['Iso']), ('getproperty', n['vIsoElements'])]
    selected_body = _filters(n, 6, 'next_sel') + [
        ('getlocal', 6), ('getproperty', n['PlayerID']), ('getlex', n['Constants']), ('getproperty', n['PLAYER_SELF']),
        ('ifne', 'next_sel'),
        ('getlocal', 6), ('getproperty', n['iconoSeleccionado']), ('pushnull',), ('ifeq', 'next_sel'),
        ('getlocal', 5), ('getlocal', 6), ('callpropvoid', push, 1),
    ]
    # Distance on the isometric ground from the current pixel positions (units that
    # move keep their starting tile in buildingReference): |dx|/W + |dy|/H tiles,
    # the same rhombus the area is drawn with.
    near_body = []
    for axis, local, size in (('x', 15, 3), ('y', 16, 4)):
        near_body += [
            ('getlocal', 12), ('getproperty', n[axis]), ('getlocal', 6), ('getproperty', n[axis]),
            ('subtract',), ('getlocal', size), ('divide',), ('setlocal', local),
            ('getlocal', local), ('pushbyte', 0), ('ifnlt', f'pos_{axis}'),
            ('getlocal', local), ('negate',), ('setlocal', local),
            ('label:', f'pos_{axis}'),
        ]
    near_body += [
        ('getlocal', 15), ('getlocal', 16), ('add',), ('getlocal', 11), ('ifgt', 'next_near'),
        ('pushtrue',), ('setlocal', 9), ('jump', 'done_near'),
    ]

    def point(dx_op, dy_op):
        ops = [('getlocal', 17), ('getlocal', 18)]
        if dx_op:
            ops += [('getlocal', 20), (dx_op,)]
        ops += [('getlocal', 19)]
        if dy_op:
            ops += [('getlocal', 21), (dy_op,)]
        return ops

    draw_body = _filters(n, 6, 'next_draw') + [
        ('pushfalse',), ('setlocal', 9),
        ('getlocal', 6), ('getproperty', n['PlayerID']), ('getlex', n['Constants']), ('getproperty', n['PLAYER_SELF']),
        ('ifne', 'enemy'),
        ('getlocal', 6), ('getproperty', n['iconoSeleccionado']), ('pushnull',), ('equals',), ('not',), ('setlocal', 9),
        ('pushint', blue), ('setlocal', 10), ('jump', 'check'),
        ('label:', 'enemy'),
        ('getlocal', 6), ('getproperty', n['PlayerID']), ('getlex', n['Constants']), ('getproperty', n['PLAYER_ENEMY']),
        ('ifne', 'next_draw'),
        ('pushint', red), ('setlocal', 10),
        # In battles, enemy towers and castles (buildings that attack) always show their area.
        ('getlocal', 25), ('iffalse', 'near_check'),
        ('getlocal', 6), ('getlex', n['IsoUnit']), ('istypelate',), ('iftrue', 'near_check'),
        ('getlocal', 6), ('getproperty', n['uiAttack']), ('pushbyte', 0), ('ifngt', 'near_check'),
        ('getlocal', 6), ('getproperty', n['iAttackRange']), ('pushbyte', 0), ('ifngt', 'near_check'),
        ('pushtrue',), ('setlocal', 9), ('jump', 'check'),
        ('label:', 'near_check'),
        ('getlocal', 6), ('getproperty', n['iAttackRange']), ('pushbyte', NEAR_TILES), ('add',), ('setlocal', 11),
    ] + _loop([('getlocal', 5)], 14, 13, 12, near_body, 'near') + [
        ('label:', 'check'),
        ('getlocal', 9), ('iffalse', 'next_draw'),
        ('getlocal', 6), ('getproperty', n['iAttackRange']), ('setlocal', 11),
        ('getlocal', 11), ('pushbyte', 1), ('ifnlt', 'range_ok'), ('pushbyte', 1), ('setlocal', 11),
        ('label:', 'range_ok'),
        ('getlocal', 11), ('getlocal', 3), ('multiply',), ('setlocal', 20),
        ('getlocal', 11), ('getlocal', 4), ('multiply',), ('setlocal', 21),
        ('getlocal', 6), ('getproperty', n['x']), ('setlocal', 18),
        ('getlocal', 6), ('getproperty', n['y']), ('setlocal', 19),
        ('getlocal', 2), ('getproperty', n['graphics']), ('coerce_a',), ('setlocal', 17),
        # Track the lowest display index among the units drawn.
        ('getlocal', 6), ('getproperty', n['parent']), ('getlocal', 1), ('ifstrictne', 'no_index'),
        ('getlocal', 1), ('getlocal', 6), ('callproperty', n['getChildIndex'], 1), ('setlocal', 22),
        ('getlocal', 23), ('pushbyte', 0), ('iflt', 'take_index'),
        ('getlocal', 22), ('getlocal', 23), ('ifnlt', 'no_index'),
        ('label:', 'take_index'),
        ('getlocal', 22), ('setlocal', 23),
        ('label:', 'no_index'),
        ('getlocal', 17), ('pushbyte', LINE_WIDTH), ('getlocal', 10), ('pushdouble', line_alpha), ('callpropvoid', n['lineStyle'], 3),
        ('getlocal', 17), ('getlocal', 10), ('pushdouble', fill_alpha), ('callpropvoid', n['beginFill'], 2),
    ] + point(None, 'subtract') + [('callpropvoid', n['moveTo'], 2)] \
      + point('add', None) + [('callpropvoid', n['lineTo'], 2)] \
      + point(None, 'add') + [('callpropvoid', n['lineTo'], 2)] \
      + point('subtract', None) + [('callpropvoid', n['lineTo'], 2)] \
      + point(None, 'subtract') + [('callpropvoid', n['lineTo'], 2)] \
      + [('getlocal', 17), ('callpropvoid', n['endFill'], 0)]

    program = [
        ('getlocal0',), ('pushscope',),
        ('getlocal0',), ('getproperty', n['buildingLayer']), ('coerce_a',), ('setlocal', 1),
        ('getlocal', 1), ('pushnull',), ('ifeq', 'end'),
        ('getlocal0',), ('getproperty', slot), ('coerce_a',), ('setlocal', 2),
        ('getlocal', 2), ('pushnull',), ('ifeq', 'make'),
        ('getlocal', 2), ('getproperty', n['parent']), ('getlocal', 1), ('ifstricteq', 'placed'),
        ('label:', 'make'),
        ('findpropstrict', n['Shape']), ('constructprop', n['Shape'], 0), ('coerce_a',), ('setlocal', 2),
        ('getlocal', 1), ('getlocal', 2), ('pushbyte', 0), ('callpropvoid', n['addChildAt'], 2),
        ('getlocal0',), ('getlocal', 2), ('setproperty', slot),
        ('label:', 'placed'),
        ('getlocal', 2), ('getproperty', n['graphics']), ('callpropvoid', n['clear'], 0),
        ('getlex', n['Config']), ('getproperty', n['EI_TILE_WIDTH_PIXELS']), ('setlocal', 3),
        ('getlex', n['Config']), ('getproperty', n['EI_TILE_HEIGHT_PIXELS']), ('setlocal', 4),
        ('newarray', 0), ('setlocal', 5),
        # Battle = attack, adventure, survival or tournament (game modes 3 to 6).
        ('pushfalse',), ('setlocal', 25),
        ('getlex', n['Base']), ('getproperty', n['Main']), ('getproperty', n['gameMode']), ('setlocal', 24),
        ('getlocal', 24), ('pushbyte', BATTLE_MODES[0]), ('iflt', 'not_battle'),
        ('getlocal', 24), ('pushbyte', BATTLE_MODES[1]), ('ifgt', 'not_battle'),
        ('pushtrue',), ('setlocal', 25),
        ('label:', 'not_battle'),
    ] + _loop(elements, 8, 7, 6, selected_body, 'sel') + [
        ('getlocal', 5), ('getproperty', n['length']), ('pushbyte', 0), ('ifne', 'has_selection'),
        ('getlocal', 25), ('iffalse', 'end'),
        ('label:', 'has_selection'),
        ('pushbyte', -1 & 0xFF), ('setlocal', 23),
    ] + _loop(elements, 8, 7, 6, draw_body, 'draw') + [
        # Put the shape right below the lowest unit drawn: above the ground, below the units.
        ('getlocal', 23), ('pushbyte', 0), ('iflt', 'end'),
        ('getlocal', 1), ('getlocal', 2), ('callproperty', n['getChildIndex'], 1), ('setlocal', 22),
        ('getlocal', 22), ('getlocal', 23), ('ifgt', 'move_down'),
        ('getlocal', 22), ('getlocal', 23), ('pushbyte', 1), ('subtract',), ('ifeq', 'end'),
        ('getlocal', 1), ('getlocal', 2), ('getlocal', 23), ('pushbyte', 1), ('subtract',),
        ('callpropvoid', n['setChildIndex'], 2), ('jump', 'end'),
        ('label:', 'move_down'),
        ('getlocal', 1), ('getlocal', 2), ('getlocal', 23), ('callpropvoid', n['setChildIndex'], 2),
        ('label:', 'end'), ('returnvoid',),
    ]
    return assemble(program)


def _public_trait_name(abc, name):
    return abc.add_qname('', name)


def add_range_overlay_to_abc(abc):
    """Add Base.__rangeShape, Base.__drawRanges and the call in UpdateGame2."""
    base_index = abc.class_index('Base')
    base = abc.instances[base_index]
    if any(abc.multiname_name(t['name']) == DRAW_METHOD for t in base['traits']):
        raise AbcError('The range overlay is already present')
    update = abc.body_of(abc.method_of('Base', 'UpdateGame2'))
    reference = abc.body_of(abc.method_of('Base', 'DebugUnitTiles'))
    slot = _public_trait_name(abc, SHAPE_SLOT)
    base['traits'].append({'name': slot, 'kind': 0, 'data': [0, 0, 0], 'metadata': None})
    code = build_draw_method(abc, slot)
    method_index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [], 'name': abc.add_string(DRAW_METHOD), 'flags': 0,
                        'options': None, 'param_names': None})
    abc.bodies.append({'method': method_index, 'max_stack': 8, 'local_count': 26,
                       'init_scope_depth': reference['init_scope_depth'],
                       'max_scope_depth': reference['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [], 'traits': []})
    draw = _public_trait_name(abc, DRAW_METHOD)
    base['traits'].append({'name': draw, 'kind': 1, 'data': [0, method_index], 'metadata': None})
    call = bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(draw) + u30(0)
    update['code'] = call + update['code']
    for exception in update['exceptions']:
        for position in range(3):  # from, to, target are absolute code offsets
            exception[position] += len(call)
    update['max_stack'] = max(update['max_stack'], 1)
    return abc


def add_range_overlay(data):
    """Return the movie with the attack-area overlay added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            abc = Abc(payload[offset:])
            payload = payload[:offset] + add_range_overlay_to_abc(abc).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
