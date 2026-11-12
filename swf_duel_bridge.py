"""Let the duel page start a battle in the game's tournament arena (SE_DUELS=on only).

The game already has the whole tournament battle (TournamentManager,
TournamentIA, MapInitializer.spawnTournament): the player's army on the left,
the rival's army on the right driven by the game's AI, the start and finish
services, and the result window. What it lacks is a way in without the old
tournament menus, and a score that means "percentage of the enemy army
destroyed". This edit adds, without changing any original instruction:

  * Base.__startDuel(duelId, typeId, enemyId, enemyName, army, enemyArmy,
    playerName):
    when the home village is loaded (Base.mapaInicializado, gameMode NORMAL),
    turns off the pending start-up popups (Base.deferredPopupQuestInfo and
    Base.showNews: PopupManager.checkForNextStartPopup would open them over the
    arena when the tournament loading window closes), fills TournamentManager's
    data (with players[0].user_name, shown in the
    battle header), enemy and both armies the way the
    tournament results window does (TournamentResultTabMatches.startMatch)
    and calls TournamentManager.loadTournament(); returns true, or false when
    the game is not ready yet (the page tries again);
  * Base.__registerDuel(), called first in Base.init: inside its own
    try/catch, so it can never break the game start,
    ExternalInterface.addCallback('startDuel', __startDuel) when
    ExternalInterface is available (the page enables it only with duels on);
  * a static slot TournamentManager.__duelAlive, set at the start of
    TournamentIA.end to the enemy units still alive
    (countArrayItems(arUnits), the same count the game's own score uses);
  * at the start of TournamentManager.end(victory, score), when that slot is
    set: score.value = 100 x (enemyArmy.length - alive) / enemyArmy.length.
    finish_tournament_match.php then sends it as attacker_points.

Like the range overlay, the edit appends to the constant pool, adds traits and
one method, and prepends code to three methods (shifting their exception
ranges). It runs last in the movie pipeline.
"""

import struct
import zlib

from swf_abc import Abc, AbcError, OPCODES, Reader, s24, u30
from swf_range_overlay import OPCODE_BY_NAME, _qname

DO_ABC = 82
CALLBACK = 'startDuel'
START_METHOD = '__startDuel'
REGISTER_METHOD = '__registerDuel'
ALIVE_SLOT = '__duelAlive'
GAME_MODE_NORMAL = 1

BRANCH_OPS = {'jump', 'iftrue', 'iffalse', 'ifeq', 'ifne', 'iflt', 'ifle', 'ifgt', 'ifge',
              'ifnlt', 'ifnle', 'ifngt', 'ifnge', 'ifstricteq', 'ifstrictne'}

# Public names the new code uses -> package.
NAMES = {
    'TournamentManager': 'managers', 'setTournamentData': '', 'enemyData': '', 'playerArmy': '', 'enemyArmy': '',
    'loadTournament': '', 'ExternalInterface': 'flash.external', 'available': '', 'addCallback': '',
    'length': '', 'gameMode': '', 'deferredPopupQuestInfo': '', 'showNews': '',
}


def assemble(program):
    """Encode [('op', operands...) | ('label:', name)]; returns (code, label offsets)."""
    def encode(item, labels, position):
        name, *operands = item
        code = bytes([OPCODE_BY_NAME[name]])
        if name in BRANCH_OPS:
            return code + s24(labels.get(operands[0], position + 4) - (position + 4))
        for kind, value in zip(OPCODES[OPCODE_BY_NAME[name]][1], operands):
            code += bytes([value]) if kind == 'u8' else u30(value)
        return code

    labels = {}
    for _ in range(2):  # branch encodings have a fixed size: two passes settle every offset
        position, out = 0, bytearray()
        for item in program:
            if item[0] == 'label:':
                labels[item[1]] = position
                continue
            encoded = encode(item, labels, position)
            out += encoded
            position += len(encoded)
    return bytes(out), labels


def used_multiname(abc, method_index, opname, name):
    """Multiname index an existing instruction of a method uses for `name`."""
    code = abc.body_of(method_index)['code']
    r = Reader(code)
    while r.pos < len(code):
        op_name, kinds = OPCODES[r.u8()]
        for position, kind in enumerate(kinds):
            if kind == 'u8':
                r.u8()
            elif kind == 's24':
                r.s24()
            elif kind == 'switch':
                r.s24()
                for _ in range(r.u30() + 1):
                    r.s24()
            else:
                value = r.u30()
                if kind == 'mn' and position == 0 and op_name == opname and abc.multiname_name(value) == name:
                    return value
    raise AbcError(f'{opname} {name} not found in method {method_index}')


def static_method(abc, class_name, method_name):
    for trait in abc.classes[abc.class_index(class_name)][1]:
        if trait['kind'] & 0x0F in (1, 2, 3) and abc.multiname_name(trait['name']) == method_name:
            return trait['data'][1]
    raise AbcError(f'{class_name}.{method_name} (static) not found')


def instance_method_using(abc, class_name, opname, name):
    """Any instance method of a class whose code has `opname name`, with that multiname."""
    for trait in abc.instances[abc.class_index(class_name)]['traits']:
        if trait['kind'] & 0x0F in (1, 2, 3):
            try:
                return used_multiname(abc, trait['data'][1], opname, name)
            except AbcError:
                continue
    raise AbcError(f'No {class_name} method uses {opname} {name}')


def prepend(body, code, exceptions=()):
    """Put code before a method body, shifting its exception ranges; new handlers go first."""
    for exception in body['exceptions']:
        for position in range(3):  # from, to, target are absolute code offsets
            exception[position] += len(code)
    body['exceptions'] = [list(exception) for exception in exceptions] + body['exceptions']
    body['code'] = code + body['code']


def add_duel_bridge_to_abc(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == START_METHOD for t in base['traits']):
        raise AbcError('The duel bridge is already present')
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    ia_end = abc.method_of('TournamentIA', 'end')
    manager_end = static_method(abc, 'TournamentManager', 'end')
    ar_units = used_multiname(abc, ia_end, 'getlex', 'arUnits')
    count_items = used_multiname(abc, ia_end, 'callproperty', 'countArrayItems')
    value = used_multiname(abc, ia_end, 'setproperty', 'value')
    map_ready = instance_method_using(abc, 'Base', 'getproperty', 'mapaInicializado')
    s = {text: abc.add_string(text) for text in ('tournament', 'tournament_id', 'tournament_type_id', 'players', 'user_name', 'name', 'id', CALLBACK)}

    # TournamentManager.__duelAlive (static, untyped: undefined until a battle ends).
    alive = abc.add_qname('', ALIVE_SLOT)
    abc.classes[abc.class_index('TournamentManager')][1].append({'name': alive, 'kind': 0, 'data': [0, 0, 0], 'metadata': None})

    # TournamentIA.end: remember how many enemy units are still alive.
    code, _ = assemble([
        ('getlex', n['TournamentManager']), ('getlocal0',), ('getlocal0',), ('getproperty', ar_units),
        ('callproperty', count_items, 1), ('setproperty', alive),
    ])
    body = abc.body_of(ia_end)
    prepend(body, code)
    body['max_stack'] = max(body['max_stack'], 4)

    # TournamentManager.end(victory, score): score = percentage of the enemy army destroyed.
    code, _ = assemble([
        ('getlex', n['TournamentManager']), ('getproperty', alive), ('pushundefined',), ('ifstricteq', 'keep'),
        ('getlocal2',), ('pushbyte', 100),
        ('getlex', n['TournamentManager']), ('getproperty', n['enemyArmy']), ('getproperty', n['length']),
        ('getlex', n['TournamentManager']), ('getproperty', alive), ('subtract',), ('multiply',),
        ('getlex', n['TournamentManager']), ('getproperty', n['enemyArmy']), ('getproperty', n['length']),
        ('divide',), ('setproperty', value),
        ('getlex', n['TournamentManager']), ('pushundefined',), ('setproperty', alive),
        ('label:', 'keep'),
    ])
    body = abc.body_of(manager_end)
    prepend(body, code)
    body['max_stack'] = max(body['max_stack'], 5)

    # Base.__startDuel(duelId, typeId, enemyId, enemyName, army, enemyArmy, playerName): Boolean
    reference = abc.body_of(abc.method_of('Base', 'DebugUnitTiles'))
    code, _ = assemble([
        ('getlocal0',), ('pushscope',),
        ('getlocal0',), ('getproperty', map_ready), ('iffalse', 'not_ready'),
        ('getlocal0',), ('getproperty', n['gameMode']), ('pushbyte', GAME_MODE_NORMAL), ('ifne', 'not_ready'),
        # The start-up popup chain (news, map quest info) must not open over the arena.
        ('getlocal0',), ('pushfalse',), ('setproperty', n['deferredPopupQuestInfo']),
        ('getlocal0',), ('pushfalse',), ('setproperty', n['showNews']),
        ('getlex', n['TournamentManager']),
        ('pushstring', s['tournament']),
        ('pushstring', s['tournament_id']), ('getlocal1',), ('pushstring', s['tournament_type_id']), ('getlocal2',),
        ('pushstring', s['players']), ('pushstring', s['user_name']), ('getlocal', 7), ('newobject', 1), ('newarray', 1),
        ('newobject', 3), ('newobject', 1), ('callpropvoid', n['setTournamentData'], 1),
        ('getlex', n['TournamentManager']),
        ('pushstring', s['name']), ('getlocal', 4), ('pushstring', s['id']), ('getlocal3',), ('newobject', 2),
        ('setproperty', n['enemyData']),
        ('getlex', n['TournamentManager']), ('getlocal', 5), ('setproperty', n['playerArmy']),
        ('getlex', n['TournamentManager']), ('getlocal', 6), ('setproperty', n['enemyArmy']),
        ('getlex', n['TournamentManager']), ('callpropvoid', n['loadTournament'], 0),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'not_ready'),
        ('pushfalse',), ('returnvalue',),
    ])
    method_index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [0] * 7, 'name': abc.add_string(START_METHOD), 'flags': 0,
                        'options': None, 'param_names': None})
    abc.bodies.append({'method': method_index, 'max_stack': 10, 'local_count': 8,
                       'init_scope_depth': reference['init_scope_depth'],
                       'max_scope_depth': reference['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [], 'traits': []})
    start = abc.add_qname('', START_METHOD)
    base['traits'].append({'name': start, 'kind': 1, 'data': [0, method_index], 'metadata': None})

    # Base.__registerDuel(): register the callback; any error is caught here, in its own
    # method (a handler added to Base.init itself fails Ruffle's verifier next to its activation).
    code, labels = assemble([
        ('getlocal0',), ('pushscope',),
        ('label:', 'try'),
        ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
        ('getlex', n['ExternalInterface']), ('pushstring', s[CALLBACK]), ('getlocal0',), ('getproperty', start),
        ('callpropvoid', n['addCallback'], 2),
        ('label:', 'try_end'),
        ('jump', 'done'),
        ('label:', 'catch'),
        ('getlocal0',), ('pushscope',),  # a handler starts with an empty scope stack
        ('pop',),
        ('label:', 'done'),
        ('returnvoid',),
    ])
    register_index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [], 'name': abc.add_string(REGISTER_METHOD), 'flags': 0,
                        'options': None, 'param_names': None})
    abc.bodies.append({'method': register_index, 'max_stack': 4, 'local_count': 1,
                       'init_scope_depth': reference['init_scope_depth'],
                       'max_scope_depth': reference['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                       'traits': []})
    register = abc.add_qname('', REGISTER_METHOD)
    base['traits'].append({'name': register, 'kind': 1, 'data': [0, register_index], 'metadata': None})

    # Base.init: call it first (like the range overlay's call in UpdateGame2).
    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(register) + u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_duel_bridge(data):
    """Return the movie with the duel bridge added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            abc = Abc(payload[offset:])
            payload = payload[:offset] + add_duel_bridge_to_abc(abc).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
