"""The "Clan" button inside the game, in the icon panel at the right (SE_CLANS=on only).

The game builds a column of icons at the right of its interface
(GuiManager.createViralButtons, the IconPanel `_viralButtonPanel`) once the
player is in the empire, never on the loading screen. That is where the
Facebook "more achievements" hand used to appear. This edit adds, without
changing any original instruction:

  * GuiManager.__addClanButton(): a Sprite holding a Loader with the button
    art (templates/img/clan_button_<language>.png, served by the site), added to that panel with
    IconPanel.addIcon(icon, __clanClick, tooltip), so the game places it,
    shows the tooltip on hover and lines it up with its other icons (the
    Monday chest, for example). Inside its own try/catch: it can never
    break the interface;
  * GuiManager.__clanClick(event): ExternalInterface.call('seOpenClan') when
    ExternalInterface is available; the page (templates/js/clan_overlay.js)
    opens or closes the clan window. Also inside its own try/catch;
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
ART_X = -62
ART_Y = 6

NAMES = {
    'Sprite': 'flash.display', 'Loader': 'flash.display', 'URLRequest': 'flash.net',
    'ExternalInterface': 'flash.external', 'available': '', 'call': '', 'x': '', 'y': '', 'load': '', 'addChild': '',
}


def _final_returnvoid(code):
    """Offset of the last instruction of a method, which must be returnvoid."""
    r = Reader(code)
    last = None
    while r.pos < len(code):
        last = r.pos
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
        name = op_name
    if last is None or name != 'returnvoid':
        raise AbcError('createViralButtons does not end with returnvoid')
    return last


def _signed_byte(value):
    return value & 0xFF


def add_clan_button_to_abc(abc, tooltip, image_url=CLAN_BUTTON_URL):
    gui = abc.instances[abc.class_index('GuiManager')]
    if any(abc.multiname_name(t['name']) == ADD_METHOD for t in gui['traits']):
        raise AbcError('The clan button is already present')
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    create = abc.method_of('GuiManager', 'createViralButtons')
    panel = used_multiname(abc, create, 'getproperty', '_viralButtonPanel')
    add_icon = used_multiname(abc, create, 'callpropvoid', 'addIcon')
    s = {text: abc.add_string(text) for text in (image_url, CALLBACK, tooltip)}
    reference = abc.body_of(create)
    click_name, add_name = abc.add_qname('', CLICK_METHOD), abc.add_qname('', ADD_METHOD)

    def method(name, params, code, labels, max_stack, local_count):
        index = len(abc.methods)
        abc.methods.append({'return_type': 0, 'param_types': [0] * params, 'name': abc.add_string(name), 'flags': 0,
                            'options': None, 'param_names': None})
        abc.bodies.append({'method': index, 'max_stack': max_stack, 'local_count': local_count,
                           'init_scope_depth': reference['init_scope_depth'],
                           'max_scope_depth': reference['init_scope_depth'] + 1,
                           'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                           'traits': []})
        return index

    guarded_end = [
        ('label:', 'try_end'),
        ('jump', 'done'),
        ('label:', 'catch'),
        ('getlocal0',), ('pushscope',),  # a handler starts with an empty scope stack
        ('pop',),
        ('label:', 'done'),
        ('returnvoid',),
    ]

    # GuiManager.__clanClick(event): ask the page to open the clan window.
    code, labels = assemble([
        ('getlocal0',), ('pushscope',),
        ('label:', 'try'),
        ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
        ('getlex', n['ExternalInterface']), ('pushstring', s[CALLBACK]), ('callpropvoid', n['call'], 1),
    ] + guarded_end)
    click_index = method(CLICK_METHOD, 1, code, labels, 3, 2)
    gui['traits'].append({'name': click_name, 'kind': 1, 'data': [0, click_index], 'metadata': None})

    # GuiManager.__addClanButton(): the icon (a Sprite with the loaded art) in the game's panel.
    code, labels = assemble([
        ('getlocal0',), ('pushscope',),
        ('label:', 'try'),
        ('findpropstrict', n['Sprite']), ('constructprop', n['Sprite'], 0), ('coerce_a',), ('setlocal1',),
        ('findpropstrict', n['Loader']), ('constructprop', n['Loader'], 0), ('coerce_a',), ('setlocal2',),
        ('getlocal2',), ('pushbyte', _signed_byte(ART_X)), ('setproperty', n['x']),
        ('getlocal2',), ('pushbyte', _signed_byte(ART_Y)), ('setproperty', n['y']),
        ('getlocal2',), ('findpropstrict', n['URLRequest']), ('pushstring', s[image_url]),
        ('constructprop', n['URLRequest'], 1), ('callpropvoid', n['load'], 1),
        ('getlocal1',), ('getlocal2',), ('callpropvoid', n['addChild'], 1),
        ('getlocal0',), ('getproperty', panel), ('getlocal1',), ('getlocal0',), ('getproperty', click_name),
        ('pushstring', s[tooltip]), ('callpropvoid', add_icon, 3),
    ] + guarded_end)
    add_index = method(ADD_METHOD, 0, code, labels, 5, 3)
    gui['traits'].append({'name': add_name, 'kind': 1, 'data': [0, add_index], 'metadata': None})

    # createViralButtons: call it right before the final returnvoid (every branch ends there).
    body = abc.body_of(create)
    at = _final_returnvoid(body['code'])
    call = bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(add_name) + u30(0)
    body['code'] = body['code'][:at] + call + body['code'][at:]
    for exception in body['exceptions']:  # ranges after the insertion point move with the code
        for position in range(3):
            if exception[position] > at:
                exception[position] += len(call)
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_clan_button(data, tooltip='Clan', image_url=CLAN_BUTTON_URL):
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
            payload = payload[:offset] + add_clan_button_to_abc(abc, tooltip, image_url).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
