"""The "Clan" and "Retar clan" buttons inside the game, in its icon panel at the right (SE_CLANS=on only).

The game builds a column of icons at the right of its interface
(GuiManager.createViralButtons, the IconPanel `_viralButtonPanel`) once the
player is in the empire, never on the loading screen. That is where the
Facebook "more achievements" hand used to appear. This edit adds:

  * GuiManager.__addClanButton(): two icons added to that panel with
    IconPanel.addIcon(icon, click, null), so the game lines them up with its
    other icons (the Monday chest, for
    example). Each icon is a Sprite holding a Loader with its art
    (templates/img/clan_button_<language>.png and
    clan_challenge_button_<language>.png, served by the site; drawn by
    tools/make_clan_button.py). The panel stacks icons ICON_SIZE apart; the
    second one draws its art one slot up and to the left, so "Retar clan"
    sits beside "Clan" instead of over the zoom bar. Inside its own
    try/catch: it can never break the interface. No tooltip: the art already
    says "Clan" / "Retar clan", and the panel draws a tooltip to the left of
    its icon, where it covered "Retar clan" (a click there went to "Clan") and
    put the tooltip of "Retar clan" one slot below, out of sight;
  * GuiManager.__clanClick(event) and __clanChallengeClick(event): first a
    "rollOut" on the clicked icon (the window opens over the game, which would
    otherwise keep the icon enlarged by the hover), then
    ExternalInterface.call('seOpenClan'[, 'rivals']) when ExternalInterface
    is available; the page (templates/js/clan_overlay.js) opens the clan
    window, on the "Retar clan" tab for the second button. Also inside
    their own try/catch;
  * a call to __addClanButton at the end of createViralButtons (inserted
    before its final returnvoid, which the method's branches jump to, so it
    runs on every path);
  * the panel's height for icons, MAX_HEIGHT (the game's 200, two icons):
    three icons, so the Monday chest never hides one of ours. That operand of
    the IconPanel construction is the only original instruction changed
    (same size).

Like the duel bridge, the edit appends to the constant pool, adds traits and
methods and inserts code; it runs in the movie pipeline only with clans on.
"""

import struct
import zlib

from swf_abc import Abc, AbcError, OPCODES, Reader, u30
from swf_duel_bridge import DO_ABC, assemble, used_multiname
from swf_range_overlay import OPCODE_BY_NAME, _qname

CLAN_BUTTON_URL = '/img/clan_button_es.png'  # art per language: tools/make_clan_button.py
CHALLENGE_BUTTON_URL = '/img/clan_challenge_button_es.png'
CALLBACK = 'seOpenClan'
CHALLENGE_TAB = 'rivals'
ADD_METHOD = '__addClanButton'
CLICK_METHOD = '__clanClick'
CHALLENGE_CLICK_METHOD = '__clanChallengeClick'
ICON_SIZE = 100           # the game's IconPanel(100, SIDE_RIGHT, 200): icons 100 apart
GAME_MAX_HEIGHT = 200
MAX_HEIGHT = 300          # three icons
# Where each art sits inside its icon (the panel's icons hang to the left of and below their origin).
ART_X, ART_Y = -62, 6
CHALLENGE_ART_X, CHALLENGE_ART_Y = -134, 6 - ICON_SIZE  # one slot up, left of the "Clan" art

NAMES = {
    'Sprite': 'flash.display', 'Loader': 'flash.display', 'URLRequest': 'flash.net',
    'ExternalInterface': 'flash.external', 'available': '', 'call': '', 'x': '', 'y': '', 'load': '', 'addChild': '',
    'MouseEvent': 'flash.events', 'currentTarget': '', 'dispatchEvent': '',
}


def _instructions(code):
    """(offset, name, first operand) for each instruction."""
    r = Reader(code)
    out = []
    while r.pos < len(code):
        offset = r.pos
        op_name, kinds = OPCODES[r.u8()]
        first = None
        for position, kind in enumerate(kinds):
            if kind == 'u8':
                value = r.u8()
            elif kind == 's24':
                value = r.s24()
            elif kind == 'switch':
                value = r.s24()
                for _ in range(r.u30() + 1):
                    r.s24()
            else:
                value = r.u30()
            if position == 0:
                first = value
        out.append((offset, op_name, first))
    return out


def _signed_short(value):
    return value & 0xFFFF if value < 0 else value


def add_clan_button_to_abc(abc, image_url=CLAN_BUTTON_URL, challenge_image_url=CHALLENGE_BUTTON_URL):
    gui = abc.instances[abc.class_index('GuiManager')]
    if any(abc.multiname_name(t['name']) == ADD_METHOD for t in gui['traits']):
        raise AbcError('The clan button is already present')
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    create = abc.method_of('GuiManager', 'createViralButtons')
    panel = used_multiname(abc, create, 'getproperty', '_viralButtonPanel')
    add_icon = used_multiname(abc, create, 'callpropvoid', 'addIcon')
    s = {text: abc.add_string(text) for text in (image_url, challenge_image_url, CALLBACK, CHALLENGE_TAB, 'rollOut')}
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

    def click(name, arguments):
        """GuiManager.<name>(event): ask the page to open the clan window."""
        pushes = [('pushstring', s[text]) for text in arguments]
        code, labels = assemble([
            ('getlocal0',), ('pushscope',),
            ('label:', 'try'),
            # The window opens over the game, which never sees the mouse leave the icon: end its hover now.
            ('getlocal1',), ('getproperty', n['currentTarget']), ('findpropstrict', n['MouseEvent']), ('pushstring', s['rollOut']),
            ('constructprop', n['MouseEvent'], 1), ('callpropvoid', n['dispatchEvent'], 1),
            ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
            ('getlex', n['ExternalInterface']), ('pushstring', s[CALLBACK]),
        ] + pushes + [('callpropvoid', n['call'], 1 + len(arguments))] + guarded_end)
        return method(name, 1, code, labels, 3 + len(arguments), 2)

    clan_click = click(CLICK_METHOD, [])
    challenge_click = click(CHALLENGE_CLICK_METHOD, [CHALLENGE_TAB])

    def icon(url, x, y, handler):
        """Push nothing; leaves the icon added to the panel (locals 1 and 2 are scratch)."""
        return [
            ('findpropstrict', n['Sprite']), ('constructprop', n['Sprite'], 0), ('coerce_a',), ('setlocal1',),
            ('findpropstrict', n['Loader']), ('constructprop', n['Loader'], 0), ('coerce_a',), ('setlocal2',),
            ('getlocal2',), ('pushshort', _signed_short(x)), ('setproperty', n['x']),
            ('getlocal2',), ('pushshort', _signed_short(y)), ('setproperty', n['y']),
            ('getlocal2',), ('findpropstrict', n['URLRequest']), ('pushstring', s[url]),
            ('constructprop', n['URLRequest'], 1), ('callpropvoid', n['load'], 1),
            ('getlocal1',), ('getlocal2',), ('callpropvoid', n['addChild'], 1),
            ('getlocal0',), ('getproperty', panel), ('getlocal1',), ('getlocal0',), ('getproperty', handler),
            ('pushnull',), ('callpropvoid', add_icon, 3),  # no tooltip
        ]

    # GuiManager.__addClanButton(): both icons in the game's panel.
    code, labels = assemble([('getlocal0',), ('pushscope',), ('label:', 'try')]
                            + icon(image_url, ART_X, ART_Y, clan_click)
                            + icon(challenge_image_url, CHALLENGE_ART_X, CHALLENGE_ART_Y, challenge_click)
                            + guarded_end)
    add_name = method(ADD_METHOD, 0, code, labels, 5, 3)

    # createViralButtons: room for three icons, and the call right before the final returnvoid.
    body = abc.body_of(create)
    code = bytearray(body['code'])
    heights = [offset for offset, name, value in _instructions(bytes(code)) if name == 'pushshort' and value == GAME_MAX_HEIGHT]
    if len(heights) != 1:
        raise AbcError('IconPanel height not found in createViralButtons')
    old, new = u30(GAME_MAX_HEIGHT), u30(MAX_HEIGHT)
    if len(old) != len(new):
        raise AbcError('The new panel height must keep the instruction size')
    code[heights[0] + 1:heights[0] + 1 + len(new)] = new
    instructions = _instructions(bytes(code))
    at, last_name, _ = instructions[-1]
    if last_name != 'returnvoid':
        raise AbcError('createViralButtons does not end with returnvoid')
    call = bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(add_name) + u30(0)
    body['code'] = bytes(code[:at]) + call + bytes(code[at:])
    for exception in body['exceptions']:  # ranges after the insertion point move with the code
        for position in range(3):
            if exception[position] > at:
                exception[position] += len(call)
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_clan_button(data, image_url=CLAN_BUTTON_URL, challenge_image_url=CHALLENGE_BUTTON_URL):
    """Return the movie with the clan buttons added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            abc = Abc(payload[offset:])
            payload = payload[:offset] + add_clan_button_to_abc(abc, image_url, challenge_image_url).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
