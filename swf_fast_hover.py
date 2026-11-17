"""Hovering the village without stalling the game (SE_FAST_HOVER).

Every building listens for MOUSE_MOVE (IsoInteractiveElement: overItem) and, to know whether the pointer is over
the building's picture or over its transparent corners, IsoInteractiveElement.getPixel(x, y) makes a new
BitmapData the building's size, draws the building into it, reads one pixel (getPixel32) and throws it away, on
every move of the mouse. The Flash Player did that on the processor; Ruffle draws on the graphics card and must
wait for the pixel to come back (WebGL getBufferSubData): measured on the owner's village, 37% of the time while
dragging the map, the game down to about 10 frames a second.

This edit gives getPixel a new body that keeps the last drawn picture (IsoInteractiveElement.__sePxBmp, static,
with the building it shows, __sePxOf, and its vertical shift, __sePxShift) and reads the pixel from it while the
pointer stays on that building; it draws again only for another building or when the building moved. The answer
is the same as before: units (IsoUnit), buildings with a collect icon (iconCollect) or a hurry-up icon
(iconsHurryUp) answer 1 (over them) without drawing, as in the game. An error answers 0 (not over).
"""

import struct
import zlib

from swf_abc import AbcError
from swf_duel_bridge import DO_ABC, assemble
from swf_hud import _used_names

SLOTS = ('__sePxBmp', '__sePxOf', '__sePxShift')


def add_fast_hover_to_abc(abc):
    index = abc.class_index('IsoInteractiveElement')
    statics = abc.classes[index][1]
    if any(abc.multiname_name(t['name']) == SLOTS[0] for t in statics):
        raise AbcError('The fast hover is already present')
    body = abc.body_of(abc.method_of('IsoInteractiveElement', 'getPixel'))
    m = _used_names(abc, {
        ('getlex', 'IsoUnit'), ('getlex', 'IsoInteractiveElement'), ('getproperty', 'iconCollect'),
        ('getproperty', 'iconsHurryUp'), ('getproperty', 'length'), ('getproperty', 'bmd'), ('getproperty', 'height'),
        ('getproperty', 'width'), ('getlex', 'Math'), ('getproperty', 'ghostBuilding'), ('getproperty', 'y'),
        ('callproperty', 'abs'), ('findpropstrict', 'Matrix'), ('constructprop', 'Matrix'),
        ('callpropvoid', 'translate'), ('findpropstrict', 'BitmapData'), ('constructprop', 'BitmapData'),
        ('callpropvoid', 'draw'), ('callproperty', 'getPixel32'), ('callpropvoid', 'dispose')})
    slot = {}
    for name in SLOTS:
        slot[name] = abc.add_qname('', name)
        statics.append({'name': slot[name], 'kind': 0, 'data': [0, 0, 0], 'metadata': None})

    cls = [('getlex', m[('getlex', 'IsoInteractiveElement')])]
    ghost = [('getlocal0',), ('getproperty', m[('getproperty', 'ghostBuilding')])]
    # Locals: 1-2 x, y (the picture's pixel), 3 the shift, 4 the matrix, 5 the new picture.
    program = [
        ('getlocal0',), ('pushscope',), ('label:', 'try'),
        ('getlocal0',), ('getlex', m[('getlex', 'IsoUnit')]), ('istypelate',), ('iffalse', 'notUnit'),
        ('pushbyte', 1), ('returnvalue',), ('label:', 'notUnit'),
        ('getlocal0',), ('getproperty', m[('getproperty', 'iconCollect')]), ('pushnull',), ('ifeq', 'noCollect'),
        ('pushbyte', 1), ('returnvalue',), ('label:', 'noCollect'),
        ('getlocal0',), ('getproperty', m[('getproperty', 'iconsHurryUp')]), ('getproperty', m[('getproperty', 'length')]),
        ('pushbyte', 0), ('ifngt', 'noHurry'),
        ('pushbyte', 1), ('returnvalue',), ('label:', 'noHurry'),
        # the shift the game draws the building with: bmd.height - |ghostBuilding.y|
        ('getlocal0',), ('getproperty', m[('getproperty', 'bmd')]), ('getproperty', m[('getproperty', 'height')]),
        ('getlex', m[('getlex', 'Math')])] + ghost + [('getproperty', m[('getproperty', 'y')]),
        ('callproperty', m[('callproperty', 'abs')], 1), ('subtract',), ('convert_i',), ('setlocal3',)]
    # the kept picture still shows this building as it is placed
    program += cls + [('getproperty', slot['__sePxBmp']), ('iffalse', 'redraw')]
    program += cls + [('getproperty', slot['__sePxOf'])] + ghost + [('ifstrictne', 'redraw')]
    program += cls + [('getproperty', slot['__sePxShift']), ('getlocal3',), ('ifstrictne', 'redraw'),
                      ('jump', 'read'),
                      ('label:', 'redraw')]
    program += cls + [('getproperty', slot['__sePxBmp']), ('iffalse', 'fresh')]
    program += cls + [('getproperty', slot['__sePxBmp']), ('callpropvoid', m[('callpropvoid', 'dispose')], 0),
                      ('label:', 'fresh'),
                      ('findpropstrict', m[('findpropstrict', 'Matrix')]), ('constructprop', m[('constructprop', 'Matrix')], 0),
                      ('setlocal', 4),
                      ('getlocal', 4), ('pushbyte', 0), ('getlocal3',), ('callpropvoid', m[('callpropvoid', 'translate')], 2),
                      ('findpropstrict', m[('findpropstrict', 'BitmapData')])] + ghost + [
        ('getproperty', m[('getproperty', 'width')])] + ghost + [('getproperty', m[('getproperty', 'height')]),
        ('pushtrue',), ('pushbyte', 0), ('constructprop', m[('constructprop', 'BitmapData')], 4), ('setlocal', 5),
        ('getlocal', 5)] + ghost + [('getlocal', 4), ('callpropvoid', m[('callpropvoid', 'draw')], 2)]
    program += cls + [('getlocal', 5), ('setproperty', slot['__sePxBmp'])]
    program += cls + ghost + [('setproperty', slot['__sePxOf'])]
    program += cls + [('getlocal3',), ('setproperty', slot['__sePxShift']),
                      ('label:', 'read')]
    program += cls + [('getproperty', slot['__sePxBmp']), ('getlocal1',), ('getlocal2',),
                      ('callproperty', m[('callproperty', 'getPixel32')], 2), ('convert_u',), ('returnvalue',),
                      ('label:', 'try_end'),
                      ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushbyte', 0), ('returnvalue',)]
    code, labels = assemble(program)
    body['code'] = code
    body['max_stack'] = max(body['max_stack'], 8)
    body['local_count'] = max(body['local_count'], 6)
    body['max_scope_depth'] = max(body['max_scope_depth'], body['init_scope_depth'] + 1)
    body['exceptions'] = [[labels['try'], labels['try_end'], labels['catch'], 0, 0]]
    return abc


def add_fast_hover(data):
    """Return the movie with IsoInteractiveElement.getPixel keeping its last picture."""
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_fast_hover_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
