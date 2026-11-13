"""The game's music and sound buttons keep their choice (SE_SOUND_FIX, on by default).

The game keeps its music and sound effects choice in a local SharedObject
(Base.Main.settings: data.music, data.sfx) but never calls flush(): Flash
wrote it when the page closed, Ruffle does not, so after a reload (or the
next visit) the game played music and sounds again although the player had
turned them off. Also, GuiManager.toggleMusic starts the music before it sets
data.music = true, and SoundManager.startBGMusic refuses to play while
data.music is false: turning the music back on stayed silent until the next
map change. This edit adds, without changing any original instruction:

  * GuiManager.__soundSave(): settings.flush(), inside its own try/catch
    (blocked browser storage just keeps the choice for this visit), called
    right before the final returnvoid of toggleMusic and toggleSound;
  * GuiManager.__musicFirst(): when the music is off (musicOn false), sets
    settings.data.music = true; called first in toggleMusic, so the music
    the button starts actually plays.
"""

import struct
import zlib

from swf_abc import Abc, AbcError, u30
from swf_duel_bridge import DO_ABC, assemble, prepend, used_multiname
from swf_range_overlay import OPCODE_BY_NAME
from swf_unit_abilities import _insert_before_final_return

SAVE_METHOD = '__soundSave'
MUSIC_METHOD = '__musicFirst'


def fix_sound_settings_in_abc(abc):
    gui = abc.instances[abc.class_index('GuiManager')]
    if any(abc.multiname_name(t['name']) == SAVE_METHOD for t in gui['traits']):
        raise AbcError('The sound settings fix is already present')
    toggle_music = abc.method_of('GuiManager', 'toggleMusic')
    toggle_sound = abc.method_of('GuiManager', 'toggleSound')
    m = {
        'Base': used_multiname(abc, toggle_music, 'getlex', 'Base'),
        'Main': used_multiname(abc, toggle_music, 'getproperty', 'Main'),
        'settings': used_multiname(abc, toggle_music, 'getproperty', 'settings'),
        'data': used_multiname(abc, toggle_music, 'getproperty', 'data'),
        'music': used_multiname(abc, toggle_music, 'setproperty', 'music'),
        'musicOn': used_multiname(abc, toggle_music, 'getproperty', 'musicOn'),
    }
    flush = abc.add_qname('', 'flush')
    reference = abc.body_of(toggle_music)

    def method(name, program, max_stack):
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
        abc.methods.append({'return_type': 0, 'param_types': [], 'name': abc.add_string(name), 'flags': 0,
                            'options': None, 'param_names': None})
        abc.bodies.append({'method': index, 'max_stack': max_stack, 'local_count': 1,
                           'init_scope_depth': reference['init_scope_depth'],
                           'max_scope_depth': reference['init_scope_depth'] + 1,
                           'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                           'traits': []})
        qname = abc.add_qname('', name)
        gui['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})
        return qname

    settings = [('getlex', m['Base']), ('getproperty', m['Main']), ('getproperty', m['settings'])]
    save = method(SAVE_METHOD, settings + [('callpropvoid', flush, 0)], 2)
    music_first = method(MUSIC_METHOD, [
        ('getlocal0',), ('getproperty', m['musicOn']), ('iftrue', 'done'),
    ] + settings + [('getproperty', m['data']), ('pushtrue',), ('setproperty', m['music'])], 3)

    def call(name):
        return bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(name) + u30(0)

    for method_index in (toggle_music, toggle_sound):
        body = abc.body_of(method_index)
        _insert_before_final_return(body, call(save))
        body['max_stack'] = max(body['max_stack'], 1)
    body = abc.body_of(toggle_music)
    prepend(body, call(music_first))
    return abc


def fix_sound_settings(data):
    """Return the movie with the sound settings fix added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + fix_sound_settings_in_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
