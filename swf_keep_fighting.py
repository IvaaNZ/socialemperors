"""The player's units keep fighting when their enemy dies (SE_KEEP_FIGHTING).

When a unit's target dies, the game calls IA.TargetDead(dead, x, y): a unit of the AGGRESSIVE condition looks for a
new enemy within its aggro range around (x, y) (IsoFightingElement.acquireNewTarget) and attacks it; the DEFENSIVE
and SURVIVE ones drop the target and stand still. The player's units are defensive, so after each kill they
stopped while the rest of the enemies stood beside them. The owner asked (2026-11-20) that they do not stop and
attack the nearest one.

This edit prepends to IA.TargetDead a call to the new IA.__seNextTarget(dead, x, y): for a unit of the player's
side (PlayerID == Constants.PLAYER_SELF), not of a collective AI, whose target was the dead element and not being
moved by the player (IA.STATE_FORCE_MOVE, as the game's own aggressive branch), it looks for a new enemy around
(x, y) within its aggro range or 10 tiles, whichever is larger (acquireNewTarget: the nearest, or with SE_SMART_AI
the best by its weights) and attacks it (IsoUnit.IA_Attack); TargetDead then returns. Without an enemy near, or
for any other unit, the game's own TargetDead runs. Any error runs the game's own too.
"""

import struct
import zlib

from swf_abc import AbcError
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_hud import _used_names
from swf_range_overlay import OPCODE_BY_NAME

NEXT_METHOD = '__seNextTarget'
MIN_RANGE = 10


def keep_fighting_enabled():
    import os
    return os.environ.get('SE_KEEP_FIGHTING', 'off').strip().lower() in ('on', '1', 'true', 'yes')


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


def add_keep_fighting_to_abc(abc):
    ia = abc.instances[abc.class_index('IA')]
    if any(abc.multiname_name(t['name']) == NEXT_METHOD for t in ia['traits']):
        raise AbcError('Keep fighting is already present')
    m = _used_names(abc, {
        ('getproperty', 'uUnit'), ('getproperty', 'PlayerID'), ('getlex', 'Constants'), ('getproperty', 'PLAYER_SELF'),
        ('getproperty', 'ciaCollectiveIA'), ('getproperty', 'TargetElement'), ('setproperty', 'TargetElement'),
        ('getproperty', 'iState'), ('getlex', 'IA'), ('getproperty', 'STATE_FORCE_MOVE'), ('getproperty', 'iAggroRange'),
        ('callpropvoid', 'acquireNewTarget'), ('callpropvoid', 'IA_Attack')})
    g = lambda name: ('getproperty', m[('getproperty', name)])  # noqa: E731
    # Locals: 1 dead, 2 x, 3 y, 4 unit, 5 range.
    program = [
        ('getlocal0',), ('pushscope',), ('label:', 'try'),
        ('getlocal0',), g('uUnit'), ('setlocal', 4),
        ('getlocal', 4), ('iffalse', 'no'),
        ('getlocal', 4), g('PlayerID'), ('getlex', m[('getlex', 'Constants')]), g('PLAYER_SELF'), ('ifne', 'no'),
        ('getlocal0',), g('ciaCollectiveIA'), ('iftrue', 'no'),
        ('getlocal1',), ('getlocal', 4), g('TargetElement'), ('ifne', 'no'),
        ('getlocal0',), g('iState'), ('getlex', m[('getlex', 'IA')]), g('STATE_FORCE_MOVE'), ('ifeq', 'no'),
        ('getlocal0',), g('iAggroRange'), ('setlocal', 5),
        ('getlocal', 5), ('pushbyte', MIN_RANGE), ('ifge', 'ranged'),
        ('pushbyte', MIN_RANGE), ('setlocal', 5),
        ('label:', 'ranged'),
        ('getlocal', 4), ('pushnull',), ('setproperty', m[('setproperty', 'TargetElement')]),
        ('getlocal', 4), ('getlocal2',), ('getlocal3',), ('getlocal', 5),
        ('callpropvoid', m[('callpropvoid', 'acquireNewTarget')], 3),
        ('getlocal', 4), g('TargetElement'), ('iffalse', 'no'),
        ('getlocal', 4), ('getlocal', 4), g('TargetElement'), ('callpropvoid', m[('callpropvoid', 'IA_Attack')], 1),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',),
        ('label:', 'try_end'),
        ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushfalse',), ('returnvalue',)]
    code, labels = assemble(program)
    reference = abc.body_of(abc.method_of('IA', 'Killed'))
    index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [0, 0, 0], 'name': abc.add_string(NEXT_METHOD), 'flags': 0,
                        'options': None, 'param_names': None})
    abc.bodies.append({'method': index, 'max_stack': 5, 'local_count': 6,
                       'init_scope_depth': reference['init_scope_depth'],
                       'max_scope_depth': reference['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                       'traits': []})
    qname = abc.add_qname('', NEXT_METHOD)
    ia['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})

    # IA.TargetDead(dead, x, y): if this.__seNextTarget(dead, x, y) the unit attacks its next enemy; nothing else.
    op = OPCODE_BY_NAME
    body = abc.body_of(abc.method_of('IA', 'TargetDead'))
    prepend(body, bytes([op['getlocal0'], op['getlocal1'], op['getlocal2'], op['getlocal3'], op['callproperty']])
            + _u30(qname) + _u30(3) + bytes([op['iffalse']]) + struct.pack('<i', 1)[:3] + bytes([op['returnvoid']]))
    body['max_stack'] = max(body['max_stack'], 4)
    return abc


def add_keep_fighting(data):
    """Return the movie whose player's units attack the next enemy when theirs dies."""
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_keep_fighting_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
