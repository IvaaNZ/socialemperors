"""Readable game lettering and a cleaner team window (SE_READABLE_UI, on by default).

Asked by the owner: white lettering is hard to read over light art, and in the
team selection window a unit whose last copy was chosen ("x0") stayed on the
list. The game only greys such a thumbnail out with a colour filter
(ThumbUnit.deactivate tweens a colorMatrixFilter), which Ruffle's WebGL
renderer does not draw. This edit adds:

  * ThumbUnit.deactivate / activate: the thumbnail is hidden (visible =
    false) when it runs out and shown again when a chosen copy goes back;
  * Base.__outlineText(event): a capture listener on the stage for
    Event.ADDED_TO_STAGE (every display object that appears): a TextField
    whose text is white (textColor 0xFFFFFF) and has no filters gets a black
    outline (GlowFilter 0x000000, alpha 1, blur 2 x 2, strength 8), the look
    of the game's own outlined labels. Inside its own try/catch;
  * Base.__registerOutline(), called first in Base.init: adds that listener
    when the stage is there.
  * IsoInteractiveElement.highlight: hovering an item shows its name card
    (InfoPopup) except for defense structures (category_id 2: castles, walls,
    towers), which only showed a life bar. The one byte of that comparison
    becomes -1, a category no item has: every item shows its name. This is
    the only original instruction changed (its operand), inside the game's
    own try/catch.
"""

import struct
import zlib

from swf_abc import Abc, AbcError, disassemble, u30
from swf_duel_bridge import DO_ABC, assemble, prepend, used_multiname
from swf_range_overlay import OPCODE_BY_NAME, _add_int, _qname

OUTLINE_METHOD = '__outlineText'
REGISTER_METHOD = '__registerOutline'
WHITE = 0xFFFFFF
DEFENSE_CATEGORY = 2  # castles, walls, towers: the game showed them no name card
NO_CATEGORY = 0xFF  # pushbyte -1
OUTLINE = {'color': 0x000000, 'alpha': 1, 'blur': 2, 'strength': 8}

NAMES = {
    'TextField': 'flash.text', 'GlowFilter': 'flash.filters', 'Event': 'flash.events',
    'ADDED_TO_STAGE': '', 'target': '', 'textColor': '', 'filters': '', 'length': '', 'addEventListener': '',
    'visible': '',
}


def make_text_readable_in_abc(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == OUTLINE_METHOD for t in base['traits']):
        raise AbcError('The readable text edit is already present')
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    get_stage = used_multiname(abc, abc.method_of('PopupManager', 'openPopupQuestsManager'), 'callproperty', 'getStage')
    white = _add_int(abc, WHITE)
    reference = abc.body_of(abc.method_of('Base', 'DebugUnitTiles'))

    def method(name, params, program, max_stack, local_count):
        code, labels = assemble([('getlocal0',), ('pushscope',), ('label:', 'try')] + program + [
            ('label:', 'try_end'),
            ('jump', 'done'),
            ('label:', 'catch'),
            ('getlocal0',), ('pushscope',),  # a handler starts with an empty scope stack
            ('pop',),
            ('label:', 'done'),
            ('returnvoid',),
        ])
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

    # Base.__outlineText(event): white text that appears gets a black outline.
    outline = method(OUTLINE_METHOD, 1, [
        ('getlocal1',), ('getproperty', n['target']), ('coerce_a',), ('setlocal2',),
        ('getlocal2',), ('getlex', n['TextField']), ('istypelate',), ('iffalse', 'done'),
        ('getlocal2',), ('getproperty', n['textColor']), ('pushint', white), ('bitand',), ('pushint', white), ('ifne', 'done'),
        ('getlocal2',), ('getproperty', n['filters']), ('getproperty', n['length']), ('pushbyte', 0), ('ifne', 'done'),
        ('getlocal2',),
        ('findpropstrict', n['GlowFilter']), ('pushbyte', OUTLINE['color']), ('pushbyte', OUTLINE['alpha']),
        ('pushbyte', OUTLINE['blur']), ('pushbyte', OUTLINE['blur']), ('pushbyte', OUTLINE['strength']),
        ('constructprop', n['GlowFilter'], 5), ('newarray', 1), ('setproperty', n['filters']),
    ], 8, 3)

    # Base.__registerOutline(): listen on the stage, in the capture phase (ADDED_TO_STAGE does not bubble).
    register = method(REGISTER_METHOD, 0, [
        ('getlocal0',), ('callproperty', get_stage, 0), ('coerce_a',), ('setlocal1',),
        ('getlocal1',), ('iffalse', 'done'),
        ('getlocal1',), ('getlex', n['Event']), ('getproperty', n['ADDED_TO_STAGE']), ('getlocal0',), ('getproperty', outline),
        ('pushtrue',), ('callpropvoid', n['addEventListener'], 3),
    ], 5, 2)
    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(register) + u30(0))
    body['max_stack'] = max(body['max_stack'], 1)

    # IsoInteractiveElement.highlight: the name card (InfoPopup) for every item, defense structures included.
    body = abc.body_of(abc.method_of('IsoInteractiveElement', 'highlight'))
    ops = disassemble(abc, body['code'])
    spots = [ops[k + 1][0] for k in range(len(ops) - 2)
             if ops[k][1] == 'getproperty' and str(ops[k][2]) == 'category_id'
             and ops[k + 1][1] == 'pushbyte' and str(ops[k + 1][2]) == str(DEFENSE_CATEGORY) and ops[k + 2][1] == 'equals']
    if len(spots) != 1:
        raise AbcError('Expected one defense category check in IsoInteractiveElement.highlight')
    code = bytearray(body['code'])
    code[spots[0] + 1] = NO_CATEGORY  # pushbyte operand: no item has category -1
    body['code'] = bytes(code)

    # ThumbUnit: hidden while none is left to choose.
    for name, shown in (('deactivate', False), ('activate', True)):
        body = abc.body_of(abc.method_of('ThumbUnit', name))
        code, _ = assemble([('getlocal0',), ('pushtrue' if shown else 'pushfalse',), ('setproperty', n['visible'])])
        prepend(body, code)
        body['max_stack'] = max(body['max_stack'], 2)
    return abc


def make_text_readable(data):
    """Return the movie with the readable text edit added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + make_text_readable_in_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
