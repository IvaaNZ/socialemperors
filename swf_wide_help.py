"""The player's units come to help from farther away (SE_WIDE_HELP).

When an element is hit (IsoFightingElement.recibirAtaque), the game calls on its side's units on every tile of the
square rings around it, up to 4 tiles away (IsoFightingElement.CallForHelp -> IA.NearbyAllyAttacked); a unit that
is called turns on the attacker when it is idle (or, with SE_SMART_AI, busy with something harmless or farther
away). The owner asked (2026-11-20) that the player's units 10 tiles away come too: a unit sent to attack a goblin
fought alone while the others, a few steps beyond, stood still. The enemies keep their 4 tiles, so fights against
goblins are not harder. This edit:

  * recibirAtaque: the rings go up to 10 (the `pushbyte 4` before the radius slot becomes `pushbyte 10`);
  * CallForHelp(x, y, attacker): for an element not of the player's side (PlayerID != Constants.PLAYER_SELF), a
    tile more than 4 tiles from it, on either axis, calls nobody, exactly as before;
  * Base.startMovements(tile, units, side), the player's order to the selected units: when the player (side
    PLAYER_SELF) sends them onto an enemy (the tile's element of PLAYER_ENEMY), it first calls the new
    Base.__seRecruit, which returns a copy of the list with the player's idle fighting units (IsoUnit, not dead,
    attack above 0, not a villager, idle as IsoUnit.isIdle says) up to 10 tiles from the first unit sent. They walk and fight
    with it: the troll camps stand far from the village, so a unit sent alone was hit where nobody could hear it.
    The selection itself (Base.Main.hitArray) does not change. Any error returns the list as it was.
"""

import struct
import zlib

from swf_abc import AbcError, disassemble
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_hud import _used_names

GAME_RADIUS, PLAYER_RADIUS = 4, 10
RECRUIT_METHOD = '__seRecruit'


def wide_help_enabled():
    import os
    return os.environ.get('SE_WIDE_HELP', 'off').strip().lower() in ('on', '1', 'true', 'yes')


def add_wide_help_to_abc(abc):
    attacked = abc.body_of(abc.method_of('IsoFightingElement', 'recibirAtaque'))
    ops = disassemble(abc, attacked['code'])
    spots = [first[0] for first, second in zip(ops, ops[1:])
             if first[1:] == ('pushbyte', str(GAME_RADIUS)) and second[1:] == ('setslot', '5')]
    if len(spots) != 1:
        raise AbcError('The help radius of recibirAtaque was not found (or the edit is already present)')
    code = bytearray(attacked['code'])
    code[spots[0] + 1] = PLAYER_RADIUS
    attacked['code'] = bytes(code)

    m = _used_names(abc, {('getproperty', 'PlayerID'), ('getlex', 'Constants'), ('getproperty', 'PLAYER_SELF'),
                          ('getproperty', 'buildingReference'), ('getproperty', 'tx'), ('getproperty', 'ty')})
    g = lambda name: ('getproperty', m[('getproperty', name)])  # noqa: E731
    far = []
    for axis, local in (('tx', 'getlocal1'), ('ty', 'getlocal2')):
        far += [(local,), ('getlocal0',), g('buildingReference'), g(axis), ('subtract',), ('setlocal', 6),
                ('getlocal', 6), ('pushbyte', GAME_RADIUS), ('ifgt', 'far'),
                ('getlocal', 6), ('negate',), ('pushbyte', GAME_RADIUS), ('ifgt', 'far')]
    program = ([('getlocal0',), ('pushscope',),
                ('getlocal0',), g('PlayerID'), ('getlex', m[('getlex', 'Constants')]), g('PLAYER_SELF'),
                ('ifeq', 'near')]
               + far + [('jump', 'near'),
                        ('label:', 'far'), ('popscope',), ('returnvoid',),
                        ('label:', 'near'), ('popscope',)])
    code, _ = assemble(program)
    body = abc.body_of(abc.method_of('IsoFightingElement', 'CallForHelp'))
    prepend(body, code)
    body['local_count'] = max(body['local_count'], 7)
    body['max_stack'] = max(body['max_stack'], 3)
    add_recruit(abc)
    return abc


def add_recruit(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == RECRUIT_METHOD for t in base['traits']):
        raise AbcError('The recruit is already present')
    m = _used_names(abc, {('getlex', 'Base'), ('getproperty', 'Iso'), ('getproperty', 'arPlayerIsoFightingElements'),
                          ('getproperty', 'tileArray'), ('getproperty', '<late>'), ('getproperty', 'mc'),
                          ('getproperty', 'PlayerID'), ('getlex', 'Constants'), ('getproperty', 'PLAYER_SELF'),
                          ('getproperty', 'PLAYER_ENEMY'), ('getproperty', 'length'), ('getlex', 'IsoUnit'),
                          ('getproperty', 'bDead'), ('getproperty', 'uiAttack'), ('getproperty', 'buildingReference'),
                          ('getproperty', 'building'), ('getproperty', 'subcat_functional'),
                          ('getproperty', 'SUBCATFUNC_UNIT_PEASANT'), ('getproperty', 'bMoving'),
                          ('getproperty', 'bMovingToDoAction'), ('getproperty', 'bAttacking'),
                          ('getproperty', 'tx'), ('getproperty', 'ty'), ('callproperty', 'concat'),
                          ('callproperty', 'indexOf'), ('callpropvoid', 'push')})
    n = {'concat': m[('callproperty', 'concat')], 'indexOf': m[('callproperty', 'indexOf')],
         'push': m[('callpropvoid', 'push')]}
    g = lambda name: ('getproperty', m[('getproperty', name)])  # noqa: E731
    late = g('<late>')
    constants = ('getlex', m[('getlex', 'Constants')])
    # Locals: 1 tile, 2 units, 3 side, 4 target, 5 list, 6 index, 7 element, 8 first unit, 9 result, 10 distance.
    near = []
    for axis in ('tx', 'ty'):
        near += [('getlocal', 7), g('buildingReference'), g(axis), ('getlocal', 8), g(axis), ('subtract',),
                 ('setlocal', 10),
                 ('getlocal', 10), ('pushbyte', PLAYER_RADIUS), ('ifgt', 'next'),
                 ('getlocal', 10), ('negate',), ('pushbyte', PLAYER_RADIUS), ('ifgt', 'next')]
    program = [
        ('getlocal0',), ('pushscope',), ('label:', 'try'),
        ('getlocal3',), constants, g('PLAYER_SELF'), ('ifne', 'same'),
        ('getlocal2',), ('iffalse', 'same'),
        ('getlocal2',), g('length'), ('pushbyte', 1), ('iflt', 'same'),
        ('getlocal0',), g('tileArray'), ('getlocal1',), late, ('setlocal', 4),
        ('getlocal', 4), ('iffalse', 'same'),
        ('getlocal', 4), g('mc'), ('iffalse', 'same'),
        ('getlocal', 4), g('mc'), g('PlayerID'), constants, g('PLAYER_ENEMY'), ('ifne', 'same'),
        ('getlocal2',), ('pushbyte', 0), late, ('setlocal', 8),
        ('getlocal2',), ('callproperty', n['concat'], 0), ('setlocal', 9),
        ('getlex', m[('getlex', 'Base')]), g('Iso'), g('arPlayerIsoFightingElements'), ('setlocal', 5),
        ('pushbyte', 0), ('setlocal', 6),
        ('label:', 'loop'), ('label',),
        ('getlocal', 6), ('getlocal', 5), g('length'), ('ifnlt', 'done'),
        ('getlocal', 5), ('getlocal', 6), late, ('setlocal', 7),
        ('getlocal', 7), ('getlex', m[('getlex', 'IsoUnit')]), ('istypelate',), ('iffalse', 'next'),
        ('getlocal', 7), g('bDead'), ('iftrue', 'next'),
        ('getlocal', 7), g('uiAttack'), ('pushbyte', 0), ('ifngt', 'next'),
        ('getlocal', 7), g('buildingReference'), g('building'), g('subcat_functional'),
        constants, g('SUBCATFUNC_UNIT_PEASANT'), ('ifeq', 'next'),
        # idle, as IsoUnit.isIdle: not moving, not walking to a task, not attacking
        ('getlocal', 7), g('bMoving'), ('iftrue', 'next'),
        ('getlocal', 7), g('bMovingToDoAction'), ('iftrue', 'next'),
        ('getlocal', 7), g('bAttacking'), ('iftrue', 'next'),
        ('getlocal', 9), ('getlocal', 7), g('buildingReference'), ('callproperty', n['indexOf'], 1),
        ('pushbyte', 0), ('ifge', 'next'),
    ] + near + [
        ('getlocal', 9), ('getlocal', 7), g('buildingReference'), ('callpropvoid', n['push'], 1),
        ('label:', 'next'), ('getlocal', 6), ('increment_i',), ('setlocal', 6), ('jump', 'loop'),
        ('label:', 'done'), ('getlocal', 9), ('returnvalue',),
        ('label:', 'try_end'),
        ('label:', 'same'), ('getlocal2',), ('returnvalue',),
        ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('getlocal2',), ('returnvalue',)]
    code, labels = assemble(program)
    reference = abc.body_of(abc.method_of('Base', 'DebugUnitTiles'))
    index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [0, 0, 0], 'name': abc.add_string(RECRUIT_METHOD),
                        'flags': 0, 'options': None, 'param_names': None})
    abc.bodies.append({'method': index, 'max_stack': 6, 'local_count': 11,
                       'init_scope_depth': reference['init_scope_depth'],
                       'max_scope_depth': reference['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                       'traits': []})
    recruit = abc.add_qname('', RECRUIT_METHOD)
    base['traits'].append({'name': recruit, 'kind': 1, 'data': [0, index], 'metadata': None})
    # Base.startMovements(tile, units, side): units = this.__seRecruit(tile, units, side) first.
    code, _ = assemble([('getlocal0',), ('getlocal1',), ('getlocal2',), ('getlocal3',),
                        ('callproperty', recruit, 3), ('setlocal2',)])
    body = abc.body_of(abc.method_of('Base', 'startMovements'))
    prepend(body, code)
    body['max_stack'] = max(body['max_stack'], 4)


def add_wide_help(data):
    """Return the movie whose player's units answer calls for help from 10 tiles away."""
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_wide_help_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
