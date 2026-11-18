"""The Soul Mixer opens its window when the player taps it (SE_SOUL_MIXER=on only).

The game this server runs (0.9.26b, 2012) sells the Soul Mixer (building 1529, config/patch/soulmixer_temp.json)
but has no window for it: tapping it only selected it, like any building. The later version that had the window
is not available, so the window is the page's (templates/js/soul_mixer_overlay.js) and the rules are the server's
(soul_mixer.py). This edit adds, without changing any original instruction:

  * Base.__seSoulMixer(element): when the element the player selected is a Soul Mixer, in the player's own village
    (Base.gameMode is the normal mode, not an attack, an island or a visit), ExternalInterface.call('seOpenSoulMixer')
    asks the page to open the window. Inside its own try/catch: it can never break the selection;
  * a call to it at the start of Base.seleccionarElemento(element), the game's selection of a building or a unit
    (which then shows the usual panel with its name and the move, turn and store buttons, as before);
  * Base.__seSoulMixerLimit(): Boolean -- one Soul Mixer per village (the owner's rule). The game checks units_limit
    (1 for the Soul Mixer, config/patch/soulmixer_temp.json) only for units; this does the same for the Soul Mixer
    while the player places one from the shop (mState STATE_CONSTRUCT), with the game's Iso.checkUnitLimit. When the
    village already has one it does what the game does for a unit over its limit: the cursor and the outline go
    away, the state goes back to STATE_INQUIRE and Base.PopUp.alert says why (the page's text from
    ExternalInterface 'seSoulMixerLimit', or else the game's own AVISO_TOPE_UNIDADES); then it answers true;
  * a call to it at the start of Base.mouseUsed, the game's click on the map: when it answers true the click ends
    there, so nothing is placed or bought.
"""

from swf_coop import _patch_movie, _u30
from swf_duel_bridge import assemble, prepend
from swf_hud import _used_names
from swf_range_overlay import OPCODE_BY_NAME, _qname
from swf_abc import AbcError

SOUL_MIXER = 1529
CALL = 'seOpenSoulMixer'
METHOD = '__seSoulMixer'
LIMIT_CALL = 'seSoulMixerLimit'
LIMIT_METHOD = '__seSoulMixerLimit'
GAME_MODE_NORMAL = 1


def add_soul_mixer_to_abc(abc):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == METHOD for t in base['traits']):
        raise AbcError('The Soul Mixer window is already present')
    m = _used_names(abc, {('getproperty', 'buildingReference'), ('getproperty', 'building'),
                          ('getproperty', 'gameMode'), ('getproperty', 'id')})
    n = {name: _qname(abc, name, package) for name, package in {
        'ExternalInterface': 'flash.external', 'available': '', 'call': ''}.items()}
    call = abc.add_string(CALL)
    g = lambda name: ('getproperty', m[('getproperty', name)])  # noqa: E731

    program = [
        ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
        ('getlocal0',), g('gameMode'), ('pushbyte', GAME_MODE_NORMAL), ('ifne', 'done'),
        ('getlocal1',), ('iffalse', 'done'),
        ('getlocal1',), g('buildingReference'), ('coerce_a',), ('setlocal2',),
        ('getlocal2',), ('iffalse', 'done'),
        ('getlocal2',), g('building'), ('iffalse', 'done'),
        ('getlocal2',), g('building'), g('id'), ('pushshort', SOUL_MIXER), ('ifne', 'done'),
        ('getlex', n['ExternalInterface']), ('pushstring', call), ('callpropvoid', n['call'], 1),
        ('label:', 'done'), ('returnvoid',)]
    reference = abc.body_of(abc.method_of('Base', 'seleccionarElemento'))
    code, labels = assemble([('getlocal0',), ('pushscope',), ('label:', 'try')] + program + [
        ('label:', 'try_end'), ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('returnvoid',)])
    index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [0], 'name': abc.add_string(METHOD), 'flags': 0,
                        'options': None, 'param_names': None})
    abc.bodies.append({'method': index, 'max_stack': 3, 'local_count': 3,
                       'init_scope_depth': reference['init_scope_depth'],
                       'max_scope_depth': reference['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                       'traits': []})
    qname = abc.add_qname('', METHOD)
    base['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})

    op = OPCODE_BY_NAME
    prepend(reference, bytes([op['getlocal0'], op['getlocal1'], op['callpropvoid']]) + _u30(qname) + _u30(1))
    reference['max_stack'] = max(reference['max_stack'], 2)

    # Base.__seSoulMixerLimit(): Boolean -- a second Soul Mixer is not placed.
    u = _used_names(abc, {('getproperty', 'mState'), ('setproperty', 'mState'), ('getlex', 'Constants'),
                          ('getproperty', 'STATE_CONSTRUCT'), ('getproperty', 'STATE_INQUIRE'),
                          ('getproperty', 'selectedBuilding'), ('getlex', 'Iso'), ('callproperty', 'checkUnitLimit'),
                          ('callpropvoid', 'removeCursor'), ('getproperty', 'buildingOutline'),
                          ('setproperty', 'visible'), ('getlex', 'Base'), ('getproperty', 'PopUp'),
                          ('getlex', 'Language'), ('getproperty', 'AVISO_TOPE_UNIDADES'),
                          ('callproperty', 'getLiteral'), ('callpropvoid', 'alert')})
    limit_call = abc.add_string(LIMIT_CALL)
    gu = lambda name: ('getproperty', u[('getproperty', name)])  # noqa: E731
    constants, language = ('getlex', u[('getlex', 'Constants')]), ('getlex', u[('getlex', 'Language')])
    mouse = abc.body_of(abc.method_of('Base', 'mouseUsed'))
    program = [
        ('getlocal0',), gu('mState'), constants, gu('STATE_CONSTRUCT'), ('ifne', 'no'),
        ('getlocal0',), gu('selectedBuilding'), ('coerce_a',), ('setlocal1',),
        ('getlocal1',), ('iffalse', 'no'),
        ('getlocal1',), g('id'), ('pushshort', SOUL_MIXER), ('ifne', 'no'),
        ('getlex', u[('getlex', 'Iso')]), ('pushshort', SOUL_MIXER),
        ('callproperty', u[('callproperty', 'checkUnitLimit')], 1), ('iftrue', 'no'),
        ('getlocal0',), ('callpropvoid', u[('callpropvoid', 'removeCursor')], 0),
        ('getlocal0',), constants, gu('STATE_INQUIRE'), ('setproperty', u[('setproperty', 'mState')]),
        ('getlocal0',), gu('buildingOutline'), ('pushfalse',), ('setproperty', u[('setproperty', 'visible')]),
        ('pushnull',), ('setlocal2',),
        ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'text'),
        ('getlex', n['ExternalInterface']), ('pushstring', limit_call), ('callproperty', n['call'], 1),
        ('coerce_a',), ('setlocal2',),
        ('label:', 'text'),
        ('getlocal2',), ('iftrue', 'alert'),
        language, language, gu('AVISO_TOPE_UNIDADES'), ('callproperty', u[('callproperty', 'getLiteral')], 1),
        ('coerce_a',), ('setlocal2',),
        ('label:', 'alert'),
        ('getlex', u[('getlex', 'Base')]), gu('PopUp'), ('getlocal2',), ('callpropvoid', u[('callpropvoid', 'alert')], 1),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',)]
    code, labels = assemble([('getlocal0',), ('pushscope',), ('label:', 'try')] + program + [
        ('label:', 'try_end'), ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',), ('pushfalse',),
        ('returnvalue',)])
    index = len(abc.methods)
    abc.methods.append({'return_type': 0, 'param_types': [], 'name': abc.add_string(LIMIT_METHOD), 'flags': 0,
                        'options': None, 'param_names': None})
    abc.bodies.append({'method': index, 'max_stack': 4, 'local_count': 3,
                       'init_scope_depth': mouse['init_scope_depth'],
                       'max_scope_depth': mouse['init_scope_depth'] + 1,
                       'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                       'traits': []})
    limit = abc.add_qname('', LIMIT_METHOD)
    base['traits'].append({'name': limit, 'kind': 1, 'data': [0, index], 'metadata': None})
    skip_return = bytes([op['iffalse']]) + (1).to_bytes(3, 'little', signed=True) + bytes([op['returnvoid']])
    prepend(mouse, bytes([op['getlocal0'], op['callproperty']]) + _u30(limit) + _u30(0) + skip_return)
    mouse['max_stack'] = max(mouse['max_stack'], 1)
    return abc


def add_soul_mixer(data):
    """Return the movie whose Soul Mixer opens the page's window when the player taps it."""
    return _patch_movie(data, add_soul_mixer_to_abc)
