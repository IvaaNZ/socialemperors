"""The game's side of the full-window view and the smooth zoom (block E, SE_VIEW).

The page (templates/js/game.js) makes the game's stage as big as the browser window, no longer a 760 x 600 picture
with green bands at its sides, and zooms the map continuously with the mouse wheel or two fingers. This edit adds,
without changing any original instruction:

  * Base.__seView(): an Object with the map's zoom (Base.currentZoom), its limits (MIN_ZOOM, MAX_ZOOM), the
    stage's size (stageWidth, stageHeight), the game's frame counter (Base.numIteraciones, one a frame: the
    page measures the frame rate with it) and whether the tutorial runs (tut, Base.Main.tutorialMode: the page
    keeps the 760 x 600 picture then); null while the game is loading;
  * Base.__seFit(center): lays the interface out for the stage's present size with the game's own full-screen
    layout (GuiManager.fullscreen, the one the Facebook game used: the bottom bar centred, the side buttons on the
    edges), after undoing a previous one (GuiManager.normalscreen); hides the zoom slider on the right
    (GuiManager.zoomSlider); and, when `center`, centres the map on the buildings (Base.centerBuildings);
  * Base.__seZoom(zoom, x, y, fast): the map's zoom set to `zoom` (the page keeps it within the limits) with the map
    point under (x, y) of the stage left where it was. `fast` skips the buildings' re-smoothing (Base.setZoom's own
    second argument) for the frames of a zoom in progress; the last call, not fast, re-smooths them and keeps the
    zoom in the game's settings (GuiManager.setZoom). Nothing happens in the tutorial, with the map locked or while
    placing a building, like the game's own zoom (Base.zoomMap);
  * Base.__seMove(dx, dy): the map moved by the game's own Base.moveMap (two fingers drag it while they zoom);
  * Base.__seShift(dx, dy): the game's open windows moved by (dx, dy): the page keeps them centred when the stage's
    size changes (a phone turned with a window open left it out of sight);
  * Base.__registerView(), called first in Base.init: ExternalInterface callbacks seView, seFit, seZoom, seMove and
    seShift;
  * GuiManager.onFullscreenChange returns at once (SE_FULLSCREEN_FIX, on unless turned off). The game's own
    fullscreen button puts the whole page in fullscreen (templates/js/game.js), but Ruffle still tells the game of
    a FULL_SCREEN and then a NORMAL display state, and for each one the game laid its interface out again for its
    760 x 600 picture (GuiManager.fullscreen / normalscreen, the stage's scale mode back to EXACT_FIT): the bottom
    bar slid to the left and the missions' king ended over the friends' bar, and the page, which only lays the
    interface out again when the stage's size changes, left it so. The page already lays it out for every size.

Every name is taken from an instruction the game already uses; each method runs inside a try/catch.
"""

import struct
import zlib

from swf_abc import AbcError, u30
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_hud import _used_names
from swf_range_overlay import OPCODE_BY_NAME, _qname

VIEW_METHOD, FIT_METHOD, ZOOM_METHOD, MOVE_METHOD, SHIFT_METHOD, REGISTER_METHOD = (
    '__seView', '__seFit', '__seZoom', '__seMove', '__seShift', '__registerView')
CALLBACKS = (('seView', VIEW_METHOD), ('seFit', FIT_METHOD), ('seZoom', ZOOM_METHOD), ('seMove', MOVE_METHOD),
             ('seShift', SHIFT_METHOD))
NAMES = {'ExternalInterface': 'flash.external', 'available': '', 'addCallback': '', 'visible': '', 'x': '', 'y': '',
         'Point': 'flash.geom', 'globalToLocal': '', 'localToGlobal': '', 'stageWidth': '', 'stageHeight': '',
         'numChildren': '', 'getChildAt': ''}


def add_view_to_abc(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == VIEW_METHOD for t in base['traits']):
        raise AbcError('The view bridge is already present')
    wanted = {('getlex', 'Base'), ('getproperty', 'Main'), ('getproperty', 'Gui'), ('getproperty', 'currentZoom'),
              ('getproperty', 'MIN_ZOOM'), ('getproperty', 'MAX_ZOOM'), ('callproperty', 'getStage'),
              ('callpropvoid', 'normalscreen'), ('callpropvoid', 'fullscreen'), ('getproperty', 'zoomSlider'),
              ('callpropvoid', 'centerBuildings'), ('getproperty', 'buildingLayer'), ('callpropvoid', 'setZoom'),
              ('callpropvoid', 'moveMap'), ('getproperty', 'tutorialMode'), ('getproperty', 'mapLocked'),
              ('getproperty', 'addingBuildings'), ('getproperty', 'PopUp'), ('getproperty', 'popupLayer'),
              ('getproperty', 'numIteraciones')}
    m = _used_names(abc, wanted)
    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    s = {text: abc.add_string(text) for text in ['zoom', 'zMin', 'zMax', 'sw', 'sh', 'frames', 'tut'] + [c for c, _ in CALLBACKS]}
    reference = abc.body_of(abc.method_of('Base', 'DebugUnitTiles'))

    def method(name, params, program, max_stack, local_count, value=False):
        if value:
            program = [('getlocal0',), ('pushscope',), ('label:', 'try')] + program + [
                ('label:', 'try_end'),
                ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushnull',), ('returnvalue',)]
        else:
            program = [('getlocal0',), ('pushscope',), ('label:', 'try')] + program + [
                ('label:', 'try_end'), ('jump', 'done'),
                ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',),
                ('label:', 'done'), ('returnvoid',)]
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

    gui = [('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Gui')])]
    stage = [('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Main')]),
             ('callproperty', m[('callproperty', 'getStage')], 0)]

    # Base.__seView(): {zoom, zMin, zMax, sw, sh}
    program = [('pushstring', s['zoom']), ('getlocal0',), ('getproperty', m[('getproperty', 'currentZoom')]),
               ('pushstring', s['zMin']), ('getlocal0',), ('getproperty', m[('getproperty', 'MIN_ZOOM')]),
               ('pushstring', s['zMax']), ('getlocal0',), ('getproperty', m[('getproperty', 'MAX_ZOOM')]),
               ('pushstring', s['sw'])] + stage + [('getproperty', n['stageWidth']),
               ('pushstring', s['sh'])] + stage + [('getproperty', n['stageHeight']),
               # The game's own frame counter (Base.UpdateGame adds one a frame): the page measures the frame rate.
               ('pushstring', s['frames']), ('getlocal0',), ('getproperty', m[('getproperty', 'numIteraciones')]),
               # In the tutorial (Base.Main.tutorialMode) the page keeps the 760 x 600 picture: its arrow, dark
               # background and boxes sit at fixed places of that picture.
               ('pushstring', s['tut']), ('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Main')]),
               ('getproperty', m[('getproperty', 'tutorialMode')]),
               ('newobject', 7), ('returnvalue',)]
    view = method(VIEW_METHOD, 0, program, 18, 1, value=True)

    # Base.__seFit(center)
    program = (gui + [('getproperty', n['x']), ('pushbyte', 0), ('ifne', 'normal')]
               + gui + [('getproperty', n['y']), ('pushshort', 525), ('ifeq', 'laid')]
               + [('label:', 'normal')] + gui + [('callpropvoid', m[('callpropvoid', 'normalscreen')], 0)]
               + [('label:', 'laid')] + gui + [('callpropvoid', m[('callpropvoid', 'fullscreen')], 0)]
               + gui + [('getproperty', m[('getproperty', 'zoomSlider')]), ('pushfalse',), ('setproperty', n['visible'])]
               + [('getlocal1',), ('iffalse', 'done'),
                  ('getlocal0',), ('callpropvoid', m[('callpropvoid', 'centerBuildings')], 0)])
    fit = method(FIT_METHOD, 1, program, 3, 2)

    # Base.__seZoom(zoom, x, y, fast); local 5: the anchor point in the map layer's own coordinates.
    layer = [('getlocal0',), ('getproperty', m[('getproperty', 'buildingLayer')])]
    program = ([('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'Main')]),
                ('getproperty', m[('getproperty', 'tutorialMode')]), ('iftrue', 'done'),
                ('getlocal0',), ('getproperty', m[('getproperty', 'mapLocked')]), ('iftrue', 'done'),
                ('getlocal0',), ('getproperty', m[('getproperty', 'addingBuildings')]), ('iftrue', 'done')]
               + layer + [('findpropstrict', n['Point']), ('getlocal2',), ('getlocal3',),
                          ('constructprop', n['Point'], 2), ('callproperty', n['globalToLocal'], 1), ('setlocal', 5),
                          ('getlocal0',), ('getlocal1',), ('getlocal', 4),
                          ('callpropvoid', m[('callpropvoid', 'setZoom')], 2),
                          ('getlocal', 4), ('iftrue', 'kept')]
               + gui + [('getlocal1',), ('callpropvoid', m[('callpropvoid', 'setZoom')], 1),
                        ('label:', 'kept')]
               + layer + [('getlocal', 5), ('callproperty', n['localToGlobal'], 1), ('setlocal', 5),
                          ('getlocal0',),
                          ('getlocal2',), ('getlocal', 5), ('getproperty', n['x']), ('subtract',),
                          ('getlocal3',), ('getlocal', 5), ('getproperty', n['y']), ('subtract',),
                          ('callpropvoid', m[('callpropvoid', 'moveMap')], 2)])
    zoom = method(ZOOM_METHOD, 4, program, 5, 6)

    # Base.__seMove(dx, dy)
    program = [('getlocal0',), ('getlocal1',), ('getlocal2',), ('callpropvoid', m[('callpropvoid', 'moveMap')], 2)]
    move = method(MOVE_METHOD, 2, program, 3, 3)

    # Base.__seShift(dx, dy): the game's open windows (Base.PopUp.popupLayer's children) moved by (dx, dy). The game
    # places each one on the stage's centre when it opens and never again: when the stage's size changes (a phone
    # turned, the window resized), the page moves them by half the change so they stay centred. A child at (0, 0)
    # (the tutorial's dark background, the alert windows, which place themselves) stays. Locals: 1-2 the arguments,
    # 3 the layer, 4 the index, 5 the window.
    program = [('getlex', m[('getlex', 'Base')]), ('getproperty', m[('getproperty', 'PopUp')]),
               ('getproperty', m[('getproperty', 'popupLayer')]), ('setlocal3',),
               ('pushbyte', 0), ('setlocal', 4),
               ('label:', 'loop'), ('label',),
               ('getlocal', 4), ('getlocal3',), ('getproperty', n['numChildren']), ('ifnlt', 'end'),
               ('getlocal3',), ('getlocal', 4), ('callproperty', n['getChildAt'], 1), ('setlocal', 5),
               ('getlocal', 5), ('getproperty', n['x']), ('pushbyte', 0), ('ifne', 'move'),
               ('getlocal', 5), ('getproperty', n['y']), ('pushbyte', 0), ('ifeq', 'next'),
               ('label:', 'move'),
               ('getlocal', 5), ('getlocal', 5), ('getproperty', n['x']), ('getlocal1',), ('add',),
               ('setproperty', n['x']),
               ('getlocal', 5), ('getlocal', 5), ('getproperty', n['y']), ('getlocal2',), ('add',),
               ('setproperty', n['y']),
               ('label:', 'next'), ('getlocal', 4), ('increment_i',), ('setlocal', 4), ('jump', 'loop'),
               ('label:', 'end')]
    shift = method(SHIFT_METHOD, 2, program, 4, 6)

    # Base.__registerView()
    program = [('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done')]
    for (callback, _), target in zip(CALLBACKS, (view, fit, zoom, move, shift)):
        program += [('getlex', n['ExternalInterface']), ('pushstring', s[callback]), ('getlocal0',),
                    ('getproperty', target), ('callpropvoid', n['addCallback'], 2)]
    register = method(REGISTER_METHOD, 0, program, 4, 1)

    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(register) + u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    if fullscreen_fix_enabled():  # the page lays the interface out for every size: the game's own relayout goes
        prepend(abc.body_of(abc.method_of('GuiManager', 'onFullscreenChange')), bytes([OPCODE_BY_NAME['returnvoid']]))
    return abc


def fullscreen_fix_enabled():
    import os
    return os.environ.get('SE_FULLSCREEN_FIX', 'on').strip().lower() in ('on', '1', 'true', 'yes')


def add_view(data):
    """Return the movie with the view bridge added to its DoABC block."""
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_view_to_abc(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
