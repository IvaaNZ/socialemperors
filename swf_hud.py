"""The game's side of the improved HUD (point 26 of block E, SE_HUD): the page reads the player's numbers and draws
its own resource bar, so the game's own top ribbon is hidden.

This edit adds, without changing any original instruction:

  * Base.__hudState(): an Object with the player's gold, wood, food, stone and cash (Base.Player.iGold, iWood, iFood,
    iStone, iCash), level and experience (iLevel, iExperience, uiExpMin, uiExpMax), population (iPopulationCurrent,
    iPopulationMax), the name and population the game shows (experienceBar's nameText and visitorsText) and
    Base.Main.gameMode (1: the player's own village). null while the game is loading;
  * Base.__hudHide(): hides the game's top ribbon pieces the page replaces (GuiMC's coinText, woodText, foodText,
    stoneText, dollarText, addCashButton, parteArribaGui (the ribbon's background), GuiManager.fondoBotonDollar, and
    everything inside experienceBar but the World globe);
  * Base.__hudCash(): a mouse press on the hidden "+ cash" button (addCashButton listens to MOUSE_DOWN), so the
    page's button does the same;
  * Base.__registerHud(), called first in Base.init: ExternalInterface callbacks 'seHudState', 'seHudHide' and
    'seHudCash' (the page, templates/js/game.js, polls the state and calls the others).

Every name is taken from an instruction the game already uses. Each method runs inside its own try/catch: an error
leaves the game as it is (the page then keeps the game's own ribbon).
"""

import struct
import zlib

from swf_abc import AbcError, OPCODES, Reader, u30
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_range_overlay import OPCODE_BY_NAME, _qname

STATE_METHOD, HIDE_METHOD, CASH_METHOD, REGISTER_METHOD = '__hudState', '__hudHide', '__hudCash', '__registerHud'
CALLBACKS = {'seHudState': STATE_METHOD, 'seHudHide': HIDE_METHOD, 'seHudCash': CASH_METHOD}
STATE_FIELDS = (('g', 'iGold'), ('w', 'iWood'), ('f', 'iFood'), ('s', 'iStone'), ('c', 'iCash'), ('lvl', 'iLevel'),
                ('xp', 'iExperience'), ('xpMin', 'uiExpMin'), ('xpMax', 'uiExpMax'), ('pop', 'iPopulationCurrent'),
                ('popMax', 'iPopulationMax'))
HIDDEN = ('coinText', 'woodText', 'foodText', 'stoneText', 'dollarText', 'addCashButton', 'parteArribaGui',
          'fondoBotonDollar')
# ExperienceMeterMC (GuiMC.experienceBar) holds, in its display list: the population text (0), the name's plate (1),
# the empire's name (2), the level star, experience bar, its mask and text (3 to 8) and the World globe (9). All but
# the globe go: their plates were part of the hidden ribbon, so the page draws the name and population itself
# (read here from nameText and visitorsText, which the game also fills for a neighbour or an enemy).
EXPERIENCE_PARTS = range(0, 9)
NAMES = {'ExternalInterface': 'flash.external', 'available': '', 'addCallback': '', 'visible': '',
         'MouseEvent': 'flash.events', 'dispatchEvent': '', 'getChildAt': '', 'text': ''}
TEXT_FIELDS = (('name', 'nameText'), ('popText', 'visitorsText'))


def _used_names(abc, wanted):
    """{(op, name): multiname index} of instructions the game already has, for the names in `wanted`."""
    found = {}
    for body in abc.bodies:
        code = body['code']
        r = Reader(code)
        while r.pos < len(code) and len(found) < len(wanted):
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
                    if position == 0 and op_name in ('getproperty', 'getlex', 'findpropstrict', 'constructprop'):
                        try:
                            name = abc.multiname_name(value)
                        except (AbcError, IndexError, KeyError):
                            continue
                        key = (op_name, name)
                        if key in wanted and key not in found:
                            found[key] = value
        if len(found) == len(wanted):
            break
    missing = set(wanted) - set(found)
    if missing:
        raise AbcError(f'HUD names not found in the game code: {sorted(missing)}')
    return found


def add_hud_to_abc(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == STATE_METHOD for t in base['traits']):
        raise AbcError('The HUD bridge is already present')
    wanted = {('getlex', 'Base'), ('getproperty', 'Player'), ('getproperty', 'Main'), ('getproperty', 'gameMode'),
              ('getproperty', 'Gui')}
    wanted |= {('getproperty', field) for _, field in STATE_FIELDS}
    wanted |= {('getproperty', name) for name in HIDDEN + ('experienceBar',)}
    wanted |= {('getproperty', field) for _, field in TEXT_FIELDS}
    m = _used_names(abc, wanted)
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    s = {text: abc.add_string(text) for text in
         [key for key, _ in STATE_FIELDS + TEXT_FIELDS] + ['mode', 'mouseDown'] + list(CALLBACKS)}
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

    def player(field):
        return [('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Player')]),
                ('getproperty', m[('getproperty', field)])]

    # Base.__hudState(): Object, or null.
    program = [('getlocal0',), ('pushscope',), ('label:', 'try')]
    for key, field in STATE_FIELDS:
        program += [('pushstring', s[key])] + player(field)
    for key, field in TEXT_FIELDS:
        program += [('pushstring', s[key]), ('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Gui')]),
                    ('getproperty', m[('getproperty', 'experienceBar')]), ('getproperty', m[('getproperty', field)]),
                    ('getproperty', n['text'])]
    program += [('pushstring', s['mode']), ('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Main')]),
                ('getproperty', m[('getproperty', 'gameMode')]),
                ('newobject', len(STATE_FIELDS) + len(TEXT_FIELDS) + 1), ('returnvalue',),
                ('label:', 'try_end'),
                ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushnull',), ('returnvalue',)]
    state = method(STATE_METHOD, 0, program, 2 * (len(STATE_FIELDS) + len(TEXT_FIELDS)) + 6, 1)

    def guarded(body):
        return [('getlocal0',), ('pushscope',), ('label:', 'try')] + body + [
            ('label:', 'try_end'), ('jump', 'done'),
            ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',),
            ('label:', 'done'), ('returnvoid',)]

    gui = [('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Gui')])]
    # Base.__hudHide(): the replaced pieces stop drawing (the page's bar is drawn in their place).
    program = []
    for name in HIDDEN:
        program += gui + [('getproperty', m[('getproperty', name)]), ('pushfalse',), ('setproperty', n['visible'])]
    for index in EXPERIENCE_PARTS:
        program += gui + [('getproperty', m[('getproperty', 'experienceBar')]), ('pushbyte', index),
                          ('callproperty', n['getChildAt'], 1), ('pushfalse',), ('setproperty', n['visible'])]
    hide = method(HIDE_METHOD, 0, guarded(program), 4, 1)

    # Base.__hudCash(): the "+ cash" button's own click.
    program = gui + [('getproperty', m[('getproperty', 'addCashButton')]),
                     ('findpropstrict', n['MouseEvent']), ('pushstring', s['mouseDown']), ('constructprop', n['MouseEvent'], 1),
                     ('callpropvoid', n['dispatchEvent'], 1)]
    cash = method(CASH_METHOD, 0, guarded(program), 5, 1)

    # Base.__registerHud(): the page's way in.
    program = [('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done')]
    for callback, target in ((s['seHudState'], state), (s['seHudHide'], hide), (s['seHudCash'], cash)):
        program += [('getlex', n['ExternalInterface']), ('pushstring', callback), ('getlocal0',),
                    ('getproperty', target), ('callpropvoid', n['addCallback'], 2)]
    register = method(REGISTER_METHOD, 0, guarded(program), 4, 1)

    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(register) + u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_hud(data):
    """Return the movie with the HUD bridge added to its DoABC block."""
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_hud_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
