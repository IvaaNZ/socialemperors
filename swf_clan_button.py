"""The "Clan" button inside the game, in its icon panel at the right (SE_CLANS=on only).

The game builds a column of icons at the right of its interface
(GuiManager.createViralButtons, the IconPanel `_viralButtonPanel`) once the
player is in the empire, never on the loading screen. That is where the
Facebook "more achievements" hand used to appear. This edit adds, without
changing any original instruction:

  * GuiManager.__addClanButton(): one icon added to that panel with
    IconPanel.addIcon(icon, __clanClick, null), so the game lines it up with
    its other icons (the Monday chest, for example; the panel shows two).
    The icon is a Sprite holding a Loader with its art
    (templates/img/clan_button_<language>.png, served by the site; drawn by
    tools/make_clan_button.py). Inside its own try/catch: it can never break
    the interface. No tooltip: the art already says "Clan", and the panel
    draws its tooltips to the left of the icon, over the game;
  * GuiManager.__clanClick(event): first a "rollOut" on the icon (the window
    opens over the game, which would otherwise keep the icon enlarged by the
    hover), then ExternalInterface.call('seOpenClan') when ExternalInterface
    is available; the page (templates/js/clan_overlay.js) opens or closes the
    clan window, where the "Retar clan" tab is. Also inside its own try/catch;
  * a call to __addClanButton at the end of createViralButtons (inserted
    before its final returnvoid, which the method's branches jump to, so it
    runs on every path).

Like the duel bridge, the edit appends to the constant pool, adds traits and
methods and inserts code; it runs in the movie pipeline only with clans on.
"""

import struct
import zlib

from swf_abc import Abc, AbcError, OPCODES, Reader, u30
from swf_duel_bridge import DO_ABC, assemble, used_multiname
from swf_range_overlay import OPCODE_BY_NAME, _qname

CLAN_BUTTON_URL = '/img/clan_button_es.png'  # art per language: tools/make_clan_button.py
CALLBACK = 'seOpenClan'
ADD_METHOD = '__addClanButton'
CLICK_METHOD = '__clanClick'
# Where the art sits inside the icon (the panel's icons hang to the left of and below their origin).
ART_X, ART_Y = -62, 6
# The game's panel (GuiManager.createViralButtons: new IconPanel(100, SIDE_RIGHT, 200) at x 760, y -380) shows only
# floor(200 / 100) = 2 icons and does not draw the rest: on Mondays its chest took a place and "PvP" was not shown,
# and a third button never would be. Our buttons go to a panel of their own (GuiManager.__seButtonPanel), the same
# kind, just left of the game's one (the game's zoom bar is below it), with room for OWN_PANEL_ICONS icons.
OWN_PANEL_SLOT = '__seButtonPanel'
OWN_PANEL_METHOD = '__seButtons'
OWN_PANEL_ICONS = 3
OWN_PANEL_X = 690
OWN_PANEL_Y = -380

NAMES = {
    'Sprite': 'flash.display', 'Loader': 'flash.display', 'URLRequest': 'flash.net',
    'ExternalInterface': 'flash.external', 'available': '', 'call': '', 'x': '', 'y': '', 'load': '', 'addChild': '',
    'MouseEvent': 'flash.events', 'currentTarget': '', 'dispatchEvent': '',
}


def _last_instruction(code):
    """(offset, name) of a method's last instruction."""
    r = Reader(code)
    last = (None, None)
    while r.pos < len(code):
        offset = r.pos
        op_name, kinds = OPCODES[r.u8()]
        for kind in kinds:
            if kind == 'u8':
                r.u8()
            elif kind == 's24':
                r.s24()
            elif kind == 'switch':
                r.s24()
                for _ in range(r.u30() + 1):
                    r.s24()
            else:
                r.u30()
        last = (offset, op_name)
    return last


def _signed_short(value):
    return value & 0xFFFF if value < 0 else value


def add_clan_button_to_abc(abc, image_url=CLAN_BUTTON_URL):
    return add_panel_button_to_abc(abc, image_url, CALLBACK, ADD_METHOD, CLICK_METHOD)


def _own_panel_method(abc, gui, create, method):
    """GuiManager.__seButtons(): our panel, made the first time it is asked for (once, for every button)."""
    for trait in gui['traits']:
        if abc.multiname_name(trait['name']) == OWN_PANEL_METHOD:
            return trait['name']
    slot = abc.add_qname('', OWN_PANEL_SLOT)
    gui['traits'].append({'name': slot, 'kind': 0, 'data': [0, 0, 0], 'metadata': None})
    m = {
        'IconPanel': used_multiname(abc, create, 'findpropstrict', 'IconPanel'),
        'IconPanelLex': used_multiname(abc, create, 'getlex', 'IconPanel'),
        'SIDE_RIGHT': used_multiname(abc, create, 'getproperty', 'SIDE_RIGHT'),
        'x': used_multiname(abc, create, 'setproperty', 'x'),
        'y': used_multiname(abc, create, 'setproperty', 'y'),
        'addChildAt': used_multiname(abc, create, 'callpropvoid', 'addChildAt'),
        'addChildAtLookup': used_multiname(abc, create, 'findpropstrict', 'addChildAt'),
    }
    code, labels = assemble([
        ('getlocal0',), ('pushscope',),
        ('getlocal0',), ('getproperty', slot), ('dup',), ('iftrue', 'have'),
        ('pop',),
        ('getlocal0',), ('findpropstrict', m['IconPanel']), ('pushbyte', 100), ('getlex', m['IconPanelLex']),
        ('getproperty', m['SIDE_RIGHT']), ('pushshort', 100 * OWN_PANEL_ICONS),
        ('constructprop', m['IconPanel'], 3), ('initproperty', slot),
        ('getlocal0',), ('getproperty', slot), ('pushshort', OWN_PANEL_X), ('setproperty', m['x']),
        ('getlocal0',), ('getproperty', slot), ('pushshort', _signed_short(OWN_PANEL_Y)), ('setproperty', m['y']),
        ('findpropstrict', m['addChildAtLookup']), ('getlocal0',), ('getproperty', slot), ('pushbyte', 0),
        ('callpropvoid', m['addChildAt'], 2),
        ('getlocal0',), ('getproperty', slot),
        ('label:', 'have'),
        ('returnvalue',),
    ])
    reference = abc.body_of(create)
    index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [], 'name': abc.add_string(OWN_PANEL_METHOD), 'flags': 0,
                        'options': None, 'param_names': None})
    abc.bodies.append({'method': index, 'max_stack': 6, 'local_count': 1,
                       'init_scope_depth': reference['init_scope_depth'],
                       'max_scope_depth': reference['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [], 'traits': []})
    qname = abc.add_qname('', OWN_PANEL_METHOD)
    gui['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})
    return qname


def add_panel_button_to_abc(abc, image_url, callback, add_method, click_method):
    """An icon in our own panel (next to the game's right panel) that calls ExternalInterface `callback` on a click
    (the clan, PvP and season pass buttons).

    Each button's call goes right before createViralButtons' final returnvoid: a button added later sits below.
    """
    gui = abc.instances[abc.class_index('GuiManager')]
    if any(abc.multiname_name(t['name']) == add_method for t in gui['traits']):
        raise AbcError(f'{add_method} is already present')
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    create = abc.method_of('GuiManager', 'createViralButtons')
    own_panel = _own_panel_method(abc, gui, create, None)
    add_icon = used_multiname(abc, create, 'callpropvoid', 'addIcon')
    s = {text: abc.add_string(text) for text in (image_url, callback, 'rollOut')}
    reference = abc.body_of(create)

    def method(name, params, code, labels, max_stack, local_count):
        index = len(abc.methods)
        abc.methods.append({'return_type': 0, 'param_types': [0] * params, 'name': abc.add_string(name), 'flags': 0,
                            'options': None, 'param_names': None})
        abc.bodies.append({'method': index, 'max_stack': max_stack, 'local_count': local_count,
                           'init_scope_depth': reference['init_scope_depth'],
                           'max_scope_depth': reference['init_scope_depth'] + 1,
                           'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                           'traits': []})
        qname = abc.add_qname('', name)
        gui['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})
        return qname

    guarded_end = [
        ('label:', 'try_end'),
        ('jump', 'done'),
        ('label:', 'catch'),
        ('getlocal0',), ('pushscope',),  # a handler starts with an empty scope stack
        ('pop',),
        ('label:', 'done'),
        ('returnvoid',),
    ]

    # GuiManager.<click_method>(event): ask the page to open its window.
    code, labels = assemble([
        ('getlocal0',), ('pushscope',),
        ('label:', 'try'),
        # The window opens over the game, which never sees the mouse leave the icon: end its hover now.
        ('getlocal1',), ('getproperty', n['currentTarget']), ('findpropstrict', n['MouseEvent']), ('pushstring', s['rollOut']),
        ('constructprop', n['MouseEvent'], 1), ('callpropvoid', n['dispatchEvent'], 1),
        ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
        ('getlex', n['ExternalInterface']), ('pushstring', s[callback]), ('callpropvoid', n['call'], 1),
    ] + guarded_end)
    clan_click = method(click_method, 1, code, labels, 3, 2)

    # GuiManager.<add_method>(): the icon (a Sprite with the loaded art) in the game's panel.
    code, labels = assemble([
        ('getlocal0',), ('pushscope',),
        ('label:', 'try'),
        ('findpropstrict', n['Sprite']), ('constructprop', n['Sprite'], 0), ('coerce_a',), ('setlocal1',),
        ('findpropstrict', n['Loader']), ('constructprop', n['Loader'], 0), ('coerce_a',), ('setlocal2',),
        ('getlocal2',), ('pushshort', _signed_short(ART_X)), ('setproperty', n['x']),
        ('getlocal2',), ('pushshort', _signed_short(ART_Y)), ('setproperty', n['y']),
        ('getlocal2',), ('findpropstrict', n['URLRequest']), ('pushstring', s[image_url]),
        ('constructprop', n['URLRequest'], 1), ('callpropvoid', n['load'], 1),
        ('getlocal1',), ('getlocal2',), ('callpropvoid', n['addChild'], 1),
        ('getlocal0',), ('callproperty', own_panel, 0), ('getlocal1',), ('getlocal0',), ('getproperty', clan_click),
        ('pushnull',), ('callpropvoid', add_icon, 3),  # no tooltip
    ] + guarded_end)
    add_name = method(add_method, 0, code, labels, 5, 3)

    # createViralButtons: the call right before its final returnvoid.
    body = abc.body_of(create)
    at, last_name = _last_instruction(body['code'])
    if last_name != 'returnvoid':
        raise AbcError('createViralButtons does not end with returnvoid')
    call = bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(add_name) + u30(0)
    body['code'] = body['code'][:at] + call + body['code'][at:]
    for exception in body['exceptions']:  # ranges after the insertion point move with the code
        for position in range(3):
            if exception[position] > at:
                exception[position] += len(call)
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_clan_button(data, image_url=CLAN_BUTTON_URL):
    """Return the movie with the clan button added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            abc = Abc(payload[offset:])
            payload = payload[:offset] + add_clan_button_to_abc(abc, image_url).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
