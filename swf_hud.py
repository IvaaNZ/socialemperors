"""The game's side of the improved HUD (point 26 of block E, SE_HUD): the page reads the player's numbers and draws
its own resource bar, so the game's own top ribbon is hidden.

This edit adds, without changing any original instruction:

  * Base.__hudState(): an Object with the player's gold, wood, food, stone and cash (Base.Player.iGold, iWood, iFood,
    iStone, iCash), level and experience (iLevel, iExperience, uiExpMin, uiExpMax), population (iPopulationCurrent,
    iPopulationMax), the name and population the game shows (experienceBar's nameText and visitorsText) and
    Base.Main.gameMode (1: the player's own village) and how many of the game's windows are open
    (Base.PopUp.popupLayer.numChildren: the page dims its bar over them). null while the game is loading;
  * Base.__hudHide(): hides the game's top ribbon pieces the page replaces (GuiMC's coinText, woodText, foodText,
    stoneText, dollarText, addCashButton, parteArribaGui (the ribbon's background), GuiManager.fondoBotonDollar, and
    everything inside experienceBar but the World globe);
  * Base.__hudCash(): a mouse press on the hidden "+ cash" button (addCashButton listens to MOUSE_DOWN), so the
    page's button does the same;
  * Base.__hudButtons(): where the bottom bar's buttons (BAR_BUTTONS, in GuiMC.bgBar), the bar itself and the side
    pieces (SIDE_BUTTONS) are on the stage, and whether they show: the page writes the buttons' names under them;
  * Base.__hudShow(name, visible, x, y): one of SIDE_BUTTONS shown or hidden (the page's "More" button groups
    them) and, unless x is NaN, moved so its top left corner is at (x, y) of the stage (below the "More" button);
  * Base.__hudPlace(name, x, y): one of PLACED (the World globe, the Clan / PvP / Pass column, the spell book)
    moved to (x, y) of the stage: the page lays them out against the window's edges;
  * Base.__registerHud(), called first in Base.init: ExternalInterface callbacks 'seHudState', 'seHudHide',
    'seHudCash', 'seHudButtons', 'seHudShow' and 'seHudPlace' (the page, templates/js/game.js, polls the
    state and calls the others).

Every name is taken from an instruction the game already uses. Each method runs inside its own try/catch: an error
leaves the game as it is (the page then keeps the game's own ribbon).
"""

import struct
import zlib

from swf_abc import AbcError, OPCODES, Reader, u30
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_range_overlay import OPCODE_BY_NAME, _qname

STATE_METHOD, HIDE_METHOD, CASH_METHOD, REGISTER_METHOD = '__hudState', '__hudHide', '__hudCash', '__registerHud'
BUTTONS_METHOD, SHOW_METHOD, PLACE_METHOD = '__hudButtons', '__hudShow', '__hudPlace'
CALLBACKS = {'seHudState': STATE_METHOD, 'seHudHide': HIDE_METHOD, 'seHudCash': CASH_METHOD,
             'seHudButtons': BUTTONS_METHOD, 'seHudShow': SHOW_METHOD, 'seHudPlace': PLACE_METHOD}
# Pieces the page moves (seHudPlace): the World globe (its ExperienceMeterMC moves with it, child 9 of it is the
# globe), the Clan, PvP and Pass column (GuiManager.__seButtonPanel, swf_clan_button.py: absent with clans off) and
# the spell book (GuiManager.magicBox).
PLACED = ('globe', 'clanPanel', 'magicBox')
GLOBE_CHILD = 9
CLAN_PANEL_SLOT = '__seButtonPanel'
# The bottom bar's buttons (children of GuiMC.bgBar) the page names, and the bar itself.
BAR_BUTTONS = ('normalMouse', 'storeButton', 'gamesButton', 'herramientaCuadrado', 'achievementsButton', 'giftButton')
# GuiManager's side buttons the page's "More" button may hide and show again (seHudShow takes only these).
# options_panel: the gear, music, sound, full-screen and pause buttons; _viralButtonPanel: the "Prize" box.
SIDE_BUTTONS = ('options_panel', '_viralButtonPanel')
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
         'MouseEvent': 'flash.events', 'dispatchEvent': '', 'getChildAt': '', 'text': '', 'numChildren': '', 'getBounds': '', 'stage': '',
         'x': '', 'y': '', 'width': '', 'height': ''}
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
                    if position == 0 and op_name in ('getproperty', 'getlex', 'findpropstrict', 'constructprop',
                                                     'callproperty', 'callpropvoid', 'setproperty'):
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
        raise AbcError(f'Names not found in the game code: {sorted(missing)}')
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
    wanted |= {('getproperty', 'PopUp'), ('getproperty', 'popupLayer'), ('getproperty', 'bgBar')}
    wanted |= {('getproperty', name) for name in BAR_BUTTONS + SIDE_BUTTONS + ('magicBox',)}
    m = _used_names(abc, wanted)
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    s = {text: abc.add_string(text) for text in
         [key for key, _ in STATE_FIELDS + TEXT_FIELDS] + ['mode', 'windows', 'mouseDown', 'x', 'y', 'w', 'h', 'v', 'on', 'bgBar']
         + list(CALLBACKS) + list(BAR_BUTTONS + SIDE_BUTTONS + PLACED) + [CLAN_PANEL_SLOT]}
    clan_panel = abc.add_qname('', CLAN_PANEL_SLOT)
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
                ('pushstring', s['windows']), ('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'PopUp')]),
                ('getproperty', m[('getproperty', 'popupLayer')]), ('getproperty', n['numChildren']),
                ('newobject', len(STATE_FIELDS) + len(TEXT_FIELDS) + 2), ('returnvalue',),
                ('label:', 'try_end'),
                ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushnull',), ('returnvalue',)]
    state = method(STATE_METHOD, 0, program, 2 * (len(STATE_FIELDS) + len(TEXT_FIELDS)) + 8, 1)

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

    def path(name):
        if name == 'globe':
            return gui + [('getproperty', m[('getproperty', 'experienceBar')]), ('pushbyte', GLOBE_CHILD),
                          ('callproperty', n['getChildAt'], 1)]
        if name == 'clanPanel':
            return gui + [('getproperty', clan_panel)]
        if name == 'bgBar':
            return gui + [('getproperty', m[('getproperty', 'bgBar')])]
        if name in BAR_BUTTONS:
            return gui + [('getproperty', m[('getproperty', 'bgBar')]), ('getproperty', m[('getproperty', name)])]
        return gui + [('getproperty', m[('getproperty', name)])]

    # Base.__hudButtons(): {name: {x, y, w, h (bounds on the stage), v (visible), on (on the stage)} or null}.
    names = ('bgBar',) + BAR_BUTTONS + SIDE_BUTTONS + PLACED
    program = [('getlocal0',), ('pushscope',), ('label:', 'try')]

    def present(name, missing):
        # GuiManager has no __seButtonPanel without the clan patch: asking for it would throw.
        if name != 'clanPanel':
            return []
        return [('pushstring', s[CLAN_PANEL_SLOT])] + gui + [('in',), ('iffalse', missing)]

    for number, name in enumerate(names):
        bounds = [('getlocal1',), ('getlocal1',), ('getproperty', n['stage']), ('callproperty', n['getBounds'], 1)]
        program += [('pushstring', s[name])] + present(name, f'null{number}') + path(name) + [
            ('setlocal1',), ('getlocal1',), ('iffalse', f'null{number}'),
            ('pushstring', s['x'])] + bounds + [('getproperty', n['x']),
            ('pushstring', s['y'])] + bounds + [('getproperty', n['y']),
            ('pushstring', s['w'])] + bounds + [('getproperty', n['width']),
            ('pushstring', s['h'])] + bounds + [('getproperty', n['height']),
            ('pushstring', s['v']), ('getlocal1',), ('getproperty', n['visible']),
            ('pushstring', s['on']), ('getlocal1',), ('getproperty', n['stage']), ('pushnull',), ('equals',), ('not',),
            ('newobject', 6), ('jump', f'next{number}'),
            ('label:', f'null{number}'), ('pushnull',),
            ('label:', f'next{number}')]
    program += [('newobject', len(names)), ('returnvalue',),
                ('label:', 'try_end'),
                ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushnull',), ('returnvalue',)]
    buttons = method(BUTTONS_METHOD, 0, program, 2 * len(names) + 16, 2)

    # Base.__hudShow(name, visible, x, y): locals 1 to 4 the arguments, 5 the piece.
    def moved(axis, local):
        bounds = [('getlocal', 5), ('getlocal', 5), ('getproperty', n['stage']), ('callproperty', n['getBounds'], 1)]
        return [('getlocal', 5), ('getlocal', 5), ('getproperty', n[axis]), ('getlocal', local)] + bounds + [
            ('getproperty', n[axis]), ('subtract',), ('add',), ('setproperty', n[axis])]

    program = []
    for number, name in enumerate(SIDE_BUTTONS):
        program += [('getlocal1',), ('pushstring', s[name]), ('ifne', f'skip{number}')] + path(name) + [
            ('setlocal', 5), ('getlocal', 5), ('getlocal2',), ('convert_b',), ('setproperty', n['visible']),
            # x is NaN (not equal to itself): only shown or hidden. Off the stage: no place to compare with.
            ('getlocal3',), ('getlocal3',), ('ifne', f'skip{number}'),
            ('getlocal', 5), ('getproperty', n['stage']), ('iffalse', f'skip{number}')] + moved('x', 3) + moved('y', 4) + [
            ('label:', f'skip{number}')]
    show = method(SHOW_METHOD, 4, guarded(program), 8, 6)

    # Base.__hudPlace(name, x, y): one of PLACED moved so the top left corner of its reference (the globe for the
    # globe's meter) is at (x, y) of the stage; an axis that is NaN stays. Locals: 1-3 the arguments, 4 what moves,
    # 5 the reference.
    def place_axis(axis, local, skip):
        bounds = [('getlocal', 5), ('getlocal', 5), ('getproperty', n['stage']), ('callproperty', n['getBounds'], 1)]
        return [('getlocal', local), ('getlocal', local), ('ifne', skip),
                ('getlocal', 4), ('getlocal', 4), ('getproperty', n[axis]), ('getlocal', local)] + bounds + [
            ('getproperty', n[axis]), ('subtract',), ('add',), ('setproperty', n[axis]), ('label:', skip)]

    program = []
    for number, name in enumerate(PLACED):
        mover = gui + [('getproperty', m[('getproperty', 'experienceBar')])] if name == 'globe' else path(name)
        program += [('getlocal1',), ('pushstring', s[name]), ('ifne', f'skip{number}')] + present(name, f'skip{number}')
        program += mover + [('setlocal', 4)] + path(name) + [
            ('setlocal', 5), ('getlocal', 5), ('iffalse', f'skip{number}'),
            ('getlocal', 5), ('getproperty', n['stage']), ('iffalse', f'skip{number}')]
        program += place_axis('x', 2, f'keepx{number}') + place_axis('y', 3, f'keepy{number}')
        program += [('label:', f'skip{number}')]
    place = method(PLACE_METHOD, 3, guarded(program), 8, 6)

    # Base.__registerHud(): the page's way in.
    program = [('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done')]
    for callback, target in ((s['seHudState'], state), (s['seHudHide'], hide), (s['seHudCash'], cash),
                             (s['seHudButtons'], buttons), (s['seHudShow'], show), (s['seHudPlace'], place)):
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
