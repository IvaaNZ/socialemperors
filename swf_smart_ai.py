"""A smarter combat AI (point 27 of block E, SE_SMART_AI), for both sides.

The game's units and defensive towers attack the nearest enemy (IsoFightingElement.acquireNewTarget ->
IsoEngine.getNearestEnemy -> getNearestTarget: the first valid element, by distance, within range); a unit being
hit only turns on its attacker when that one is twice nearer; allies help only when idle; the wounded fight to the
end. The owner chose (2026-11-17) four improvements, for both sides:

  * Smart targets and smarter towers: IsoEngine.getNearestTarget gets a new body that scores every valid element
    within range, (distance + 1) x a weight, and takes the lowest: healers (the four healer units of the game's own
    TournamentIA.isHealer) x0.4, the badly wounded (under 35% of their life) x0.6, units attacking a building
    x0.6 (defenders and towers protect the village), harmless elements (buildings without attack) x1.6. The
    rest of the search is the game's: the same filter (fCheckNearestTarget by default), the same range, the same
    "not on my own tile" rule and the game's own discount for harmless elements (Config.AGGRO_RANGE). Units,
    towers and the special attacks that pick a target all use it.
  * Help in a group: IA.NearbyAllyAttacked first calls IA.__seHelp(attacker): a unit busy with something harmless
    (no attack) or farther than the attacker turns on the attacker. Units of a collective AI (sieges, tournaments)
    are left to it; so are forced moves and passive units.
  * Retreat of the wounded: IA.BeingAttacked first calls IA.__seRetreat(attacker): a unit of the computer's side
    (not PLAYER_SELF: the player's units obey the player) under 30% of its life falls back once
    (IA.__seRetreated) to its nearest healer or, without one, to the nearest ally farther from the attacker than
    itself, as a forced move (IA.STATE_FORCE_MOVE, the game's own way back home); arriving ends it
    (IA.DestinyReached) and it fights again. Healers and units of a collective AI do not retreat.

Each new piece runs inside a try/catch: an error leaves the game's own behaviour (no target / no help / no
retreat).
"""

import struct
import zlib

from swf_abc import AbcError, OPCODES
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_hud import _used_names
from swf_range_overlay import OPCODE_BY_NAME, _add_double

HELP_METHOD, RETREAT_METHOD, RETREATED_SLOT = '__seHelp', '__seRetreat', '__seRetreated'
HEALERS = ('ID_UNIT_TROLL_HEALER', 'ID_UNIT_CLERIC_HEALER', 'ID_UNIT_ISIS_HEALER', 'ID_UNIT_ANGELICAL_SUPER_HEALER')
WEIGHTS = {'healer': 0.4, 'wounded': 0.6, 'raider': 0.6, 'harmless': 1.6}
WOUNDED, RETREAT = 0.35, 0.3


def _u30(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def add_smart_ai_to_abc(abc):
    ia = abc.instances[abc.class_index('IA')]
    if any(abc.multiname_name(t['name']) == HELP_METHOD for t in ia['traits']):
        raise AbcError('The smart AI is already present')
    m = _used_names(abc, {
        ('getlex', 'Base'), ('getproperty', 'Iso'), ('callproperty', 'distance'), ('getproperty', '<late>'),
        ('getproperty', 'fCheckNearestTarget'), ('getlex', 'Constants'), ('getproperty', 'PLAYER_SELF'),
        ('getproperty', 'PLAYER_ENEMY'), ('getproperty', 'arPlayerIsoFightingElements'),
        ('getproperty', 'arEnemyIsoFightingElements'), ('callproperty', 'bucleNearestUnits'),
        ('getproperty', 'length'), ('getproperty', 'sort'), ('getproperty', 'buildingReference'),
        ('getproperty', 'building'), ('getproperty', 'attack'), ('getlex', 'Config'), ('getproperty', 'AGGRO_RANGE'),
        ('getproperty', 'tx'), ('getproperty', 'ty'), ('getproperty', 'iID'), ('getproperty', 'iHealth'),
        ('getproperty', 'maxLife'), ('getproperty', 'TargetElement'), ('setproperty', 'TargetElement'),
        ('getlex', 'IsoUnit'), ('getlex', 'IsoBuilding'), ('getlex', 'IsoFightingElement'), ('getproperty', 'uiAttack'),
        ('getproperty', 'PlayerID'), ('getproperty', 'bDead'), ('callpropvoid', 'IA_Attack'),
        ('callpropvoid', 'IA_Move'), ('getproperty', 'iCondition'), ('getlex', 'IA'),
        ('getproperty', 'CONDITION_DEFENSIVE'), ('getproperty', 'CONDITION_AGGRESSIVE'), ('getproperty', 'iState'),
        ('setproperty', 'iState'), ('getproperty', 'STATE_FORCE_MOVE'), ('getproperty', 'ciaCollectiveIA'),
        ('getproperty', 'uUnit')} | {('getproperty', name) for name in HEALERS})
    d = {name: _add_double(abc, value) for name, value in WEIGHTS.items()}
    d['woundedAt'] = _add_double(abc, WOUNDED)
    d['retreatAt'] = _add_double(abc, RETREAT)
    g = lambda name: ('getproperty', m[('getproperty', name)])  # noqa: E731
    lex = lambda name: ('getlex', m[('getlex', name)])  # noqa: E731
    late = ('getproperty', m[('getproperty', '<late>')])

    def is_healer(local, yes, no):
        out = []
        for name in HEALERS:
            out += [('getlocal', local), g('iID'), lex('Constants'), g(name), ('ifeq', yes)]
        return out + [('jump', no)]

    def weigh(local_weight, double):
        return [('getlocal', local_weight), ('pushdouble', d[double]), ('multiply',), ('setlocal', local_weight)]

    # ---- IsoEngine.getNearestTarget(x, y, players, range, ownTile, filter): a new body.
    # Locals: 1-6 the arguments, 7 the side, 8 the list, 9 the sorted near ones, 10 index, 11 count, 12 element,
    # 13 its distance, 14 the best, 15 its score, 16 the weight, 17 range squared, 18 scratch.
    body = abc.body_of(abc.method_of('IsoEngine', 'getNearestTarget'))
    p = [('getlocal0',), ('pushscope',), ('label:', 'try'),
         ('getlocal', 6), ('pushnull',), ('ifne', 'filtered'),
         ('getlocal0',), g('fCheckNearestTarget'), ('setlocal', 6),
         ('label:', 'filtered'),
         ('getlocal3',), ('iffalse', 'enemies'),
         lex('Constants'), g('PLAYER_SELF'), ('setlocal', 7),
         ('getlocal0',), g('arPlayerIsoFightingElements'), ('setlocal', 8), ('jump', 'sided'),
         ('label:', 'enemies'),
         lex('Constants'), g('PLAYER_ENEMY'), ('setlocal', 7),
         ('getlocal0',), g('arEnemyIsoFightingElements'), ('setlocal', 8),
         ('label:', 'sided'),
         ('getlocal0',), ('getlocal1',), ('getlocal2',), ('getlocal', 8),
         ('callproperty', m[('callproperty', 'bucleNearestUnits')], 3), ('setlocal', 9),
         ('getlocal', 9), ('iffalse', 'none'),
         ('getlocal', 4), ('getlocal', 4), ('multiply',), ('setlocal', 17),
         ('pushnull',), ('setlocal', 14), ('pushbyte', 0), ('setlocal', 15),
         ('pushbyte', 0), ('setlocal', 10),
         ('getlocal', 9), g('length'), ('setlocal', 11),
         ('label:', 'loop'), ('label',),
         ('getlocal', 10), ('getlocal', 11), ('ifnlt', 'done'),
         ('getlocal', 9), ('getlocal', 10), late, ('setlocal', 12),
         ('getlocal', 12), g('sort'), ('convert_d',), ('setlocal', 13),
         ('pushbyte', 1), ('convert_d',), ('setlocal', 16),
         # the game's own discount for harmless elements, and our weight against them
         ('getlocal', 12), g('buildingReference'), g('building'), g('attack'), ('pushbyte', 0), ('ifne', 'armed'),
         ('getlocal', 13), lex('Config'), g('AGGRO_RANGE'), ('subtract',), ('setlocal', 13)] + weigh(16, 'harmless') + [
         ('label:', 'armed'),
         # sorted by distance: past the range, nothing nearer is left (as in the game)
         ('getlocal', 13), ('getlocal', 17), ('ifnle', 'done'),
         ('getlocal', 6), ('getglobalscope',), ('getlocal', 12), ('getlocal', 7), ('call', 2), ('iffalse', 'next'),
         ('getlocal', 5), ('iftrue', 'placed'),
         ('getlocal1',), ('getlocal', 12), g('buildingReference'), g('tx'), ('equals',), ('iffalse', 'placed'),
         ('getlocal2',), ('getlocal', 12), g('buildingReference'), g('ty'), ('equals',), ('iftrue', 'next'),
         ('label:', 'placed')]
    p += is_healer(12, 'healer', 'notHealer') + [('label:', 'healer')] + weigh(16, 'healer') + [('label:', 'notHealer')]
    p += [('getlocal', 12), g('maxLife'), ('pushbyte', 0), ('ifngt', 'whole'),
          ('getlocal', 12), g('iHealth'), ('getlocal', 12), g('maxLife'), ('pushdouble', d['woundedAt']), ('multiply',),
          ('ifnlt', 'whole')] + weigh(16, 'wounded') + [
          ('label:', 'whole'),
          ('getlocal', 12), lex('IsoUnit'), ('istypelate',), ('iffalse', 'scored'),
          ('getlocal', 12), g('TargetElement'), lex('IsoBuilding'), ('istypelate',), ('iffalse', 'scored')] + weigh(16, 'raider') + [
          ('label:', 'scored'),
          ('getlocal', 13), ('pushbyte', 0), ('ifnlt', 'positive'), ('pushbyte', 0), ('convert_d',), ('setlocal', 13),
          ('label:', 'positive'),
          ('getlocal', 13), ('pushbyte', 1), ('add',), ('getlocal', 16), ('multiply',), ('setlocal', 18),
          ('getlocal', 14), ('iffalse', 'take'),
          ('getlocal', 18), ('getlocal', 15), ('ifnlt', 'next'),
          ('label:', 'take'),
          ('getlocal', 12), ('setlocal', 14), ('getlocal', 18), ('setlocal', 15),
          ('label:', 'next'),
          ('getlocal', 10), ('increment_i',), ('setlocal', 10), ('jump', 'loop'),
          ('label:', 'done'), ('getlocal', 14), ('returnvalue',),
          ('label:', 'none'), ('pushnull',), ('returnvalue',),
          ('label:', 'try_end'),
          ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushnull',), ('returnvalue',)]
    code, labels = assemble(p)
    body['code'] = code
    body['max_stack'] = max(body['max_stack'], 8)
    body['local_count'] = max(body['local_count'], 19)
    body['max_scope_depth'] = max(body['max_scope_depth'], body['init_scope_depth'] + 1)
    body['exceptions'] = [[labels['try'], labels['try_end'], labels['catch'], 0, 0]]
    body['traits'] = []

    # ---- new IA methods
    reference = abc.body_of(abc.method_of('IA', 'Killed'))
    retreated = abc.add_qname('', RETREATED_SLOT)
    ia['traits'].append({'name': retreated, 'kind': 0, 'data': [0, 0, 0], 'metadata': None})

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
        ia['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})
        return qname

    unit = [('getlocal0',), g('uUnit')]

    def distance(a, b):
        return [lex('Base'), g('Iso')] + a + b + [('callproperty', m[('callproperty', 'distance')], 2), ('pushbyte', 0), late]

    def fighting_condition(no):
        return [('getlocal0',), g('iCondition'), lex('IA'), g('CONDITION_DEFENSIVE'), ('ifeq', 'fights'),
                ('getlocal0',), g('iCondition'), lex('IA'), g('CONDITION_AGGRESSIVE'), ('ifne', no),
                ('label:', 'fights')]

    # IA.__seHelp(attacker, ally). Locals: 1 attacker, 2 ally, 3 the unit's target.
    p = [('getlocal0',), ('pushscope',), ('label:', 'try'),
         ('getlocal0',), g('ciaCollectiveIA'), ('pushnull',), ('ifne', 'leave')] + unit + [g('bDead'), ('iftrue', 'leave'),
         ('getlocal0',), g('iState'), lex('IA'), g('STATE_FORCE_MOVE'), ('ifeq', 'leave')] + fighting_condition('leave') + [
         ('getlocal1',), lex('IsoFightingElement'), ('istypelate',), ('iffalse', 'leave'),
         ('getlocal1',), g('bDead'), ('iftrue', 'leave')] + unit + [g('TargetElement'), ('setlocal3',),
         ('getlocal3',), ('pushnull',), ('ifeq', 'leave'),            # idle: the game's own code helps
         ('getlocal3',), ('getlocal1',), ('ifstricteq', 'leave'),
         ('getlocal3',), lex('IsoFightingElement'), ('istypelate',), ('iffalse', 'turn'),
         ('getlocal3',), g('uiAttack'), ('pushbyte', 0), ('ifeq', 'turn')] + distance(unit, [('getlocal1',)]) + distance(unit, [('getlocal3',)]) + [
         ('ifnlt', 'leave'),
         ('label:', 'turn')] + unit + [('getlocal1',), ('setproperty', m[('setproperty', 'TargetElement')])] + unit + [
         ('getlocal1',), ('callpropvoid', m[('callpropvoid', 'IA_Attack')], 1),
         ('label:', 'leave'),
         ('label:', 'try_end'), ('jump', 'done'),
         ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',),
         ('label:', 'done'), ('returnvoid',)]
    help_ = method(HELP_METHOD, 2, p, 8, 4)

    # IA.__seRetreat(attacker): true when the unit falls back. Locals: 1 attacker, 2 list, 3 index, 4 element,
    # 5 its distance, 6 the healer, 7 its distance, 8 the ally, 9 its distance, 10 where to go, 11 the unit's distance
    # from the attacker.
    p = [('getlocal0',), ('pushscope',), ('label:', 'try'),
         ('getlocal0',), g('ciaCollectiveIA'), ('pushnull',), ('ifne', 'no')] + unit + [g('bDead'), ('iftrue', 'no'),
         ('getlocal0',), ('getproperty', retreated), ('iftrue', 'no')] + unit + [
         g('PlayerID'), lex('Constants'), g('PLAYER_SELF'), ('ifeq', 'no')] + fighting_condition('no') + unit + [
         g('maxLife'), ('pushbyte', 0), ('ifngt', 'no')] + unit + [g('iHealth')] + unit + [g('maxLife'),
         ('pushdouble', d['retreatAt']), ('multiply',), ('ifnlt', 'no')] + unit + [('setlocal', 4)]
    p += is_healer(4, 'no', 'notHealer') + [('label:', 'notHealer'),
         ('getlocal1',), lex('IsoFightingElement'), ('istypelate',), ('iffalse', 'noAttacker')] + distance(
         [('getlocal1',)], unit) + [('setlocal', 11), ('jump', 'look'),
         ('label:', 'noAttacker'), ('pushbyte', 0), ('setlocal', 11),
         ('label:', 'look'),
         lex('Base'), g('Iso'), g('arEnemyIsoFightingElements'), ('setlocal2',),
         ('pushnull',), ('setlocal', 6), ('pushnull',), ('setlocal', 8),
         ('pushbyte', 0), ('setlocal', 7), ('pushbyte', 0), ('setlocal', 9),
         ('pushbyte', 0), ('setlocal3',),
         ('label:', 'loop'), ('label',),
         ('getlocal3',), ('getlocal2',), g('length'), ('ifnlt', 'chosen'),
         ('getlocal2',), ('getlocal3',), late, ('setlocal', 4),
         ('getlocal', 4)] + unit + [('ifstricteq', 'next'),
         ('getlocal', 4), lex('IsoUnit'), ('istypelate',), ('iffalse', 'next'),
         ('getlocal', 4), g('bDead'), ('iftrue', 'next')] + distance(unit, [('getlocal', 4)]) + [('setlocal', 5)]
    p += is_healer(4, 'isHealer', 'isAlly') + [
         ('label:', 'isHealer'),
         ('getlocal', 6), ('iffalse', 'takeHealer'), ('getlocal', 5), ('getlocal', 7), ('ifnlt', 'next'),
         ('label:', 'takeHealer'), ('getlocal', 4), ('setlocal', 6), ('getlocal', 5), ('setlocal', 7), ('jump', 'next'),
         ('label:', 'isAlly'),
         ('getlocal1',), lex('IsoFightingElement'), ('istypelate',), ('iffalse', 'next')] + distance(
         [('getlocal1',)], [('getlocal', 4)]) + [('getlocal', 11), ('ifngt', 'next'),
         ('getlocal', 8), ('iffalse', 'takeAlly'), ('getlocal', 5), ('getlocal', 9), ('ifnlt', 'next'),
         ('label:', 'takeAlly'), ('getlocal', 4), ('setlocal', 8), ('getlocal', 5), ('setlocal', 9),
         ('label:', 'next'), ('getlocal3',), ('increment_i',), ('setlocal3',), ('jump', 'loop'),
         ('label:', 'chosen'),
         ('getlocal', 6), ('setlocal', 10), ('getlocal', 7), ('setlocal', 5),
         ('getlocal', 10), ('iftrue', 'go'),
         ('getlocal', 8), ('setlocal', 10), ('getlocal', 9), ('setlocal', 5),
         ('getlocal', 10), ('iffalse', 'no'),
         ('label:', 'go'),
         ('getlocal', 5), ('pushbyte', 2), ('iflt', 'no'),                # already beside it
         ('getlocal0',), ('pushtrue',), ('setproperty', retreated)] + unit + [
         ('pushnull',), ('setproperty', m[('setproperty', 'TargetElement')]),
         ('getlocal0',), lex('IA'), g('STATE_FORCE_MOVE'), ('setproperty', m[('setproperty', 'iState')])] + unit + [
         ('getlocal', 10), g('buildingReference'), g('tx'), ('getlocal', 10), g('buildingReference'), g('ty'),
         ('callpropvoid', m[('callpropvoid', 'IA_Move')], 2),
         ('pushtrue',), ('returnvalue',),
         ('label:', 'no'), ('pushfalse',), ('returnvalue',),
         ('label:', 'try_end'),
         ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushfalse',), ('returnvalue',)]
    retreat = method(RETREAT_METHOD, 1, p, 8, 12)

    op = OPCODE_BY_NAME
    # IA.NearbyAllyAttacked(attacker, ally): first this.__seHelp(attacker, ally).
    nearby = abc.body_of(abc.method_of('IA', 'NearbyAllyAttacked'))
    prepend(nearby, bytes([op['getlocal0'], op['getlocal1'], op['getlocal2'], op['callpropvoid']])
            + _u30(help_) + _u30(2))
    nearby['max_stack'] = max(nearby['max_stack'], 3)
    # IA.BeingAttacked(attacker, ...): if this.__seRetreat(attacker) the unit falls back; nothing else happens.
    attacked = abc.body_of(abc.method_of('IA', 'BeingAttacked'))
    prepend(attacked, bytes([op['getlocal0'], op['getlocal1'], op['callproperty']]) + _u30(retreat) + _u30(1)
            + bytes([op['iffalse']]) + struct.pack('<i', 1)[:3] + bytes([op['returnvoid']]))
    attacked['max_stack'] = max(attacked['max_stack'], 2)
    return abc


def add_smart_ai(data):
    """Return the movie with the smarter combat AI."""
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_smart_ai_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
