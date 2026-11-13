"""The "PvP" button and the game's own team selection for raids and duels (SE_PVP=on only).

This edit adds, without changing any original instruction:

  * the "PvP" icon in the game's right panel, below the "Clan" one
    (swf_clan_button.add_panel_button_to_abc): a click calls
    ExternalInterface 'seOpenPvp'; the page (templates/js/pvp_overlay.js)
    opens or closes the PvP window (rivals, raids, duels);
  * Base.__selectTeam(): opens the game's team selection window
    (SelectionTeamWindow, the one adventures use before sailing to an
    island) over the village, centred in the popup layer like the game's
    popups, in its tournament mode (the window lists units only in its own
    modes; this one leaves out TOURNAMENT_UNITS_NOT_ALLOWED, like the arena)
    with its close button shown again (that mode hides it). The window
    remembers the last team (privateState.teams.tournament, saved by the
    game's set_attack_team command). Returns false when the village is not
    on screen (loading, an adventure, the arena) or a selection is open;
  * Base.__teamAccepted() / Base.__teamClosed(): the window's `accepted` and
    `closeMe` signals. Both remove the window; accepted calls
    ExternalInterface 'seTeamSelected' with the chosen unit ids (the window's
    selectedArmy: up to 20, 0 for an empty slot), closed calls it with null;
  * Base.__registerPvp(), called first in Base.init:
    ExternalInterface.addCallback('selectTeam', __selectTeam).

Every new method runs inside its own try/catch: an error closes nothing and
breaks nothing (the page treats a failed call as "no selection").
"""

import struct
import zlib

from swf_abc import Abc, AbcError, u30
from swf_clan_button import add_panel_button_to_abc
from swf_duel_bridge import DO_ABC, assemble, instance_method_using, prepend, used_multiname
from swf_range_overlay import OPCODE_BY_NAME, _qname

PVP_BUTTON_URL = '/img/pvp_button_es.png'  # art per language: tools/make_pvp_button.py
OPEN_CALLBACK = 'seOpenPvp'
SELECT_CALLBACK = 'selectTeam'
SELECTED_CALL = 'seTeamSelected'
SELECT_METHOD = '__selectTeam'
ACCEPTED_METHOD = '__teamAccepted'
CLOSED_METHOD = '__teamClosed'
REGISTER_METHOD = '__registerPvp'
WINDOW_SLOT = '__teamWindow'
GAME_MODE_NORMAL = 1

NAMES = {
    'ExternalInterface': 'flash.external', 'available': '', 'call': '', 'addCallback': '',
    'gameMode': '', 'x': '', 'y': '', 'parent': '', 'removeChild': '', 'addChild': '', 'visible': '',
}


def add_pvp_to_abc(abc, image_url=PVP_BUTTON_URL):
    base = abc.instances[abc.class_index('Base')]
    if any(abc.multiname_name(t['name']) == SELECT_METHOD for t in base['traits']):
        raise AbcError('The PvP team selection is already present')
    add_panel_button_to_abc(abc, image_url, OPEN_CALLBACK, '__addPvpButton', '__pvpClick')

    n = {name: _qname(abc, name, package) for name, package in NAMES.items()}
    go_to_island = abc.method_of('PopupQuestsManager', 'goToIsland')
    team_selected = abc.method_of('PopupQuestsManager', 'questTeamSelected')
    close_team = abc.method_of('PopupQuestsManager', 'closeTeamWindow')
    open_quests = abc.method_of('PopupManager', 'openPopupQuestsManager')
    m = {
        'Base': used_multiname(abc, go_to_island, 'getlex', 'Base'),
        'Iso': used_multiname(abc, go_to_island, 'getproperty', 'Iso'),
        'refreshTotalPlayerUnits': used_multiname(abc, go_to_island, 'callpropvoid', 'refreshTotalPlayerUnits'),
        'SelectionTeamWindow': used_multiname(abc, go_to_island, 'findpropstrict', 'SelectionTeamWindow'),
        'accepted': used_multiname(abc, go_to_island, 'getproperty', 'accepted'),
        'closeMe': used_multiname(abc, go_to_island, 'getproperty', 'closeMe'),
        'add': used_multiname(abc, go_to_island, 'callpropvoid', 'add'),
        'init': used_multiname(abc, go_to_island, 'callpropvoid', 'init'),
        'selectedArmy': used_multiname(abc, team_selected, 'getproperty', 'selectedArmy'),
        'removeAll': used_multiname(abc, close_team, 'callpropvoid', 'removeAll'),
        'Main': used_multiname(abc, open_quests, 'getproperty', 'Main'),
        'getStage': used_multiname(abc, open_quests, 'callproperty', 'getStage'),
        'stageWidth': used_multiname(abc, open_quests, 'getproperty', 'stageWidth'),
        'stageHeight': used_multiname(abc, open_quests, 'getproperty', 'stageHeight'),
        'PopUp': used_multiname(abc, abc.method_of('PopupQuestsManager', 'goToIsland'), 'getproperty', 'PopUp'),
        'popupLayer': used_multiname(abc, open_quests, 'getproperty', 'popupLayer'),
        'SELECTION_MODE_TOURNAMENT': used_multiname(abc, abc.method_of('SelectionTeamWindow', 'init'), 'getlex',
                                                    'SELECTION_MODE_TOURNAMENT'),
        'btnClose': used_multiname(abc, abc.method_of('SelectionTeamWindow', 'init'), 'getlex', 'btnClose'),
    }
    map_ready = instance_method_using(abc, 'Base', 'getproperty', 'mapaInicializado')
    s = {text: abc.add_string(text) for text in (SELECT_CALLBACK, SELECTED_CALL)}
    reference = abc.body_of(abc.method_of('Base', 'DebugUnitTiles'))

    window = abc.add_qname('', WINDOW_SLOT)  # the open selection window (untyped slot)
    base['traits'].append({'name': window, 'kind': 0, 'data': [0, 0, 0], 'metadata': None})

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

    def guarded(program, on_error):
        return [('getlocal0',), ('pushscope',), ('label:', 'try')] + program + [
            ('label:', 'try_end'),
            ('jump', 'done'),
            ('label:', 'catch'),
            ('getlocal0',), ('pushscope',),  # a handler starts with an empty scope stack
            ('pop',),
        ] + on_error + [('label:', 'done')]

    # Remove the window (local 1) and forget it; its signals stop calling us.
    finish = [
        ('getlocal0',), ('getproperty', window), ('coerce_a',), ('setlocal1',),
        ('getlocal0',), ('pushnull',), ('setproperty', window),
        ('getlocal1',), ('iffalse', 'gone'),
        ('getlocal1',), ('getproperty', m['accepted']), ('callpropvoid', m['removeAll'], 0),
        ('getlocal1',), ('getproperty', m['closeMe']), ('callpropvoid', m['removeAll'], 0),
        ('getlocal1',), ('getproperty', n['parent']), ('iffalse', 'gone'),
        ('getlocal1',), ('getproperty', n['parent']), ('getlocal1',), ('callpropvoid', n['removeChild'], 1),
        ('label:', 'gone'),
    ]
    tell_page = [('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
                 ('getlex', n['ExternalInterface']), ('pushstring', s[SELECTED_CALL])]

    # Base.__teamAccepted(): the chosen unit ids to the page.
    accepted = method(ACCEPTED_METHOD, 0, guarded([
        ('getlocal0',), ('getproperty', window), ('coerce_a',), ('setlocal2',),
        ('getlocal2',), ('iffalse', 'done'),
        ('getlocal2',), ('getproperty', m['selectedArmy']), ('coerce_a',), ('setlocal2',),
    ] + finish + tell_page + [('getlocal2',), ('callpropvoid', n['call'], 2)], []) + [('returnvoid',)], 4, 3)

    # Base.__teamClosed(): no selection.
    closed = method(CLOSED_METHOD, 0, guarded(finish + tell_page + [('pushnull',), ('callpropvoid', n['call'], 2)], [])
                    + [('returnvoid',)], 4, 2)

    # Base.__selectTeam(): Boolean -- open the game's team selection window over the village.
    stage_half = lambda size: [('getlex', m['Base']), ('getproperty', m['Main']), ('callproperty', m['getStage'], 0),  # noqa: E731
                               ('getproperty', m[size]), ('pushbyte', 2), ('divide',)]
    select = method(SELECT_METHOD, 0, guarded([
        ('getlocal0',), ('getproperty', map_ready), ('iffalse', 'no'),
        ('getlocal0',), ('getproperty', n['gameMode']), ('pushbyte', GAME_MODE_NORMAL), ('ifne', 'no'),
        ('getlocal0',), ('getproperty', window), ('iftrue', 'no'),
        ('getlex', m['Base']), ('getproperty', m['Iso']), ('callpropvoid', m['refreshTotalPlayerUnits'], 0),
        ('findpropstrict', m['SelectionTeamWindow']), ('constructprop', m['SelectionTeamWindow'], 0), ('coerce_a',), ('setlocal1',),
        ('getlocal0',), ('getlocal1',), ('setproperty', window),
        ('getlocal1',), ('getproperty', m['accepted']), ('getlocal0',), ('getproperty', abc.add_qname('', ACCEPTED_METHOD)),
        ('callpropvoid', m['add'], 1),
        ('getlocal1',), ('getproperty', m['closeMe']), ('getlocal0',), ('getproperty', abc.add_qname('', CLOSED_METHOD)),
        ('callpropvoid', m['add'], 1),
        # The window lists units only in its own modes; the tournament one also leaves out the units the arena refuses.
        ('getlocal1',), ('getlex', m['SelectionTeamWindow']), ('getproperty', m['SELECTION_MODE_TOURNAMENT']),
        ('pushnull',), ('pushbyte', 0), ('callpropvoid', m['init'], 3),
        ('getlocal1',), ('getproperty', m['btnClose']), ('pushtrue',), ('setproperty', n['visible']),  # hidden in that mode
        ('getlocal1',)] + stage_half('stageWidth') + [('setproperty', n['x']),
        ('getlocal1',)] + stage_half('stageHeight') + [('setproperty', n['y']),
        ('getlex', m['Base']), ('getproperty', m['PopUp']), ('getproperty', m['popupLayer']), ('getlocal1',),
        ('callpropvoid', n['addChild'], 1),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'),
        ('pushfalse',), ('returnvalue',),
    ], [('getlocal0',), ('pushnull',), ('setproperty', window)]) + [('pushfalse',), ('returnvalue',)], 6, 2)

    # Base.__registerPvp(): the page's way in.
    register = method(REGISTER_METHOD, 0, guarded([
        ('getlex', n['ExternalInterface']), ('getproperty', n['available']), ('iffalse', 'done'),
        ('getlex', n['ExternalInterface']), ('pushstring', s[SELECT_CALLBACK]), ('getlocal0',), ('getproperty', select),
        ('callpropvoid', n['addCallback'], 2),
    ], []) + [('returnvoid',)], 4, 1)
    del accepted, closed

    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([OPCODE_BY_NAME['getlocal0'], OPCODE_BY_NAME['callpropvoid']]) + u30(register) + u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    return abc


def add_pvp(data, image_url=PVP_BUTTON_URL):
    """Return the movie with the PvP button and team selection added to its DoABC block."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + add_pvp_to_abc(Abc(payload[offset:]), image_url).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
