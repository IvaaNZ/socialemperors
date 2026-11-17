"""Performance mode (SE_PERF_MODE): the village's buildings stop their decorative animations.

The owner's village has about 3000 clips on its map, 741 of them animated; Ruffle advances every one of them on
every frame, on one core (about 71% of the time measured). This edit adds:

  * Base.__sePerf(): every MovieClip with more than one frame inside the map's buildings (the IsoBuilding
    children of Base.buildingLayer) stops (MovieClip.stop). Nothing else is touched: the units (IsoUnit, the
    dragons and heroes too) wait for their animations to reach a frame to hit (checkAttackFrame and the like), and
    so do spells (MagicParticle) and blasts; the buildings' own states use gotoAndStop (the wall's gate,
    IsoBuilding.abrirCerrarMuralla), which still works. Returns {clips, stopped} (how many clips it looked at and
    how many it stopped). The page calls it every few seconds while the player has the mode on and is in the own
    village (about 5 ms on the owner's village); turning the mode off reloads the page;
  * Base.__registerPerf(), called first in Base.init: the ExternalInterface callback 'sePerf'.

Every name is taken from an instruction the game already uses; the method runs inside a try/catch.
"""

import struct
import zlib

from swf_abc import AbcError, u30
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_hud import _used_names
from swf_range_overlay import OPCODE_BY_NAME, _qname

PERF_METHOD, REGISTER_METHOD = '__sePerf', '__registerPerf'
CALLBACK = 'sePerf'


def add_perf_mode_to_abc(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == PERF_METHOD for t in base['traits']):
        raise AbcError('The performance mode is already present')
    m = _used_names(abc, {('getlex', 'MovieClip'), ('getlex', 'DisplayObjectContainer'), ('getlex', 'IsoUnit'),
                          ('getlex', 'IsoBuilding'),
                          ('callpropvoid', 'stop'), ('getproperty', 'totalFrames'), ('callproperty', 'pop'),
                          ('callpropvoid', 'push'), ('getproperty', 'length'), ('getproperty', 'buildingLayer')})
    n = {name: _qname(abc, name, package) for name, package in
         {'ExternalInterface': 'flash.external', 'available': '', 'addCallback': '', 'numChildren': '',
          'getChildAt': ''}.items()}
    s = {text: abc.add_string(text) for text in ('clips', 'stopped', CALLBACK)}
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

    # Base.__sePerf(): the map layer's buildings (IsoBuilding), then a walk inside them with a stack (an Array).
    # Locals: 1 stack, 2 node, 3 index, 4 clips, 5 stopped, 6 the map layer.
    program = [('getlocal0',), ('pushscope',), ('label:', 'try'),
               ('newarray', 0), ('setlocal1',),
               ('pushbyte', 0), ('setlocal', 4), ('pushbyte', 0), ('setlocal', 5),
               ('getlocal0',), ('getproperty', m[('getproperty', 'buildingLayer')]), ('setlocal', 6),
               ('pushbyte', 0), ('setlocal3',),
               ('label:', 'top'), ('label',),
               ('getlocal3',), ('getlocal', 6), ('getproperty', n['numChildren']), ('ifnlt', 'loop'),
               ('getlocal', 6), ('getlocal3',), ('callproperty', n['getChildAt'], 1), ('setlocal2',),
               ('getlocal2',), ('getlex', m[('getlex', 'IsoBuilding')]), ('istypelate',), ('iffalse', 'nextTop'),
               ('getlocal1',), ('getlocal2',), ('callpropvoid', m[('callpropvoid', 'push')], 1),
               ('label:', 'nextTop'),
               ('getlocal3',), ('increment_i',), ('setlocal3',), ('jump', 'top'),
               ('label:', 'loop'), ('label',),
               ('getlocal1',), ('getproperty', m[('getproperty', 'length')]), ('pushbyte', 0), ('ifngt', 'end'),
               ('getlocal1',), ('callproperty', m[('callproperty', 'pop')], 0), ('setlocal2',),
               # a unit and everything it holds keep playing
               ('getlocal2',), ('getlex', m[('getlex', 'IsoUnit')]), ('istypelate',), ('iftrue', 'loop'),
               ('getlocal2',), ('getlex', m[('getlex', 'MovieClip')]), ('istypelate',), ('iffalse', 'container'),
               ('getlocal', 4), ('increment_i',), ('setlocal', 4),
               ('getlocal2',), ('getproperty', m[('getproperty', 'totalFrames')]), ('pushbyte', 1),
               ('ifngt', 'container'),
               ('getlocal2',), ('callpropvoid', m[('callpropvoid', 'stop')], 0),
               ('getlocal', 5), ('increment_i',), ('setlocal', 5),
               ('label:', 'container'),
               ('getlocal2',), ('getlex', m[('getlex', 'DisplayObjectContainer')]), ('istypelate',), ('iffalse', 'loop'),
               ('pushbyte', 0), ('setlocal3',),
               ('label:', 'inner'), ('label',),
               ('getlocal3',), ('getlocal2',), ('getproperty', n['numChildren']), ('ifnlt', 'loop'),
               ('getlocal1',), ('getlocal2',), ('getlocal3',), ('callproperty', n['getChildAt'], 1),
               ('callpropvoid', m[('callpropvoid', 'push')], 1),
               ('getlocal3',), ('increment_i',), ('setlocal3',), ('jump', 'inner'),
               ('label:', 'end'),
               ('pushstring', s['clips']), ('getlocal', 4), ('pushstring', s['stopped']), ('getlocal', 5),
               ('newobject', 2), ('returnvalue',),
               ('label:', 'try_end'),
               ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushnull',), ('returnvalue',)]
    perf = method(PERF_METHOD, 0, program, 6, 7)

    program = [('getlocal0',), ('pushscope',), ('label:', 'try'),
               ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
               ('getlex', n['ExternalInterface']), ('pushstring', s[CALLBACK]), ('getlocal0',),
               ('getproperty', perf), ('callpropvoid', n['addCallback'], 2),
               ('label:', 'try_end'), ('jump', 'done'),
               ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',),
               ('label:', 'done'), ('returnvoid',)]
    register = method(REGISTER_METHOD, 0, program, 4, 1)

    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(register) + u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_perf_mode(data):
    """Return the movie with the performance mode's bridge added to its DoABC block."""
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_perf_mode_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
