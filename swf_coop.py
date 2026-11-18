"""Adventures alone or with the clan (point 28; COOP_PLAN.md, phase 1).

Two edits:

* add_quest_teams (SE_QUEST_TEAMS): every adventure island opens the game's team selection ("Elige tu
  equipo", SelectionTeamWindow, 20 places) before sailing. The game did it only for the five islands of
  Config.QUESTS_WITH_TEAMS and took the whole army to the others: PopupQuestsManager.goToIsland's test of that list
  becomes a jump to the selection branch (the same bytes' length, the rest padded with nop).

* add_coop (SE_COOP): the choice between Solitario and Clan, and the team of a clan raid.
  - PopupQuestsManager.goToIsland(island) first calls PopupQuestsManager.__seAsk(island): unless the page has
    already answered (__seGo), the island is kept (__seIsland), the manager too (Base.__seQuests) and the page is
    asked (ExternalInterface 'seCoopChoose'); when it answers true the game waits for it.
  - Base.__seCoopGo(clan): the page's answer: the manager goes to the kept island again; with clan, the team window
    takes at most COOP_UNITS units and the chosen team goes to the page instead of sailing.
  - SelectionTeamWindow.onThumbUnitClick first calls SelectionTeamWindow.__seLimit(): in a clan choice its places
    shrink to COOP_UNITS (_totalThumbsSelected, the game's own limit).
  - PopupQuestsManager.questTeamSelected first calls PopupQuestsManager.__seTaken(): in a clan choice the island's
    id and the chosen units (the window's selectedArmy: unit ids, 0 for an empty place) go to the page
    (ExternalInterface 'seCoopPicked') and the window closes; nothing sails. closeTeamWindow first calls
    PopupQuestsManager.__seClosed(): a clan choice closed without a team tells the page (null).
  - Base.__seCoopPick(): a guest's team: the same window in its adventure mode over the village, at most
    COOP_UNITS units; its answer goes to the page the same way ('seCoopPicked' with no island).
  - Base.__seCoopSail(quest, army): the clan raid sets sail (phase 2): the kept manager loads the island with
    every player's units (PopupQuestsManager.loadQuestMapWithSelectedArmy, as after the team window).
  - Base.__seCoopUnits() (phase 4): the player's units alive on the island, each with a handle (its place in
    Base.__seUnits, kept for the raid), its unit id, where it is on the stage and its life: the page shows each
    guest its own units;
  - Base.__seCoopOrder(handles, x, y) (phase 4): those units attack the enemy at (x, y) of the stage (the game's
    own search, IsoEngine.getNearestEnemy, two tiles around Utils.PixelToTile of the point) or walk there
    (IsoUnit.IA_Attack / IA_Move, as the computer's units are moved); the host's own selection is not touched;
  - Base.__registerCoop(), called first in Base.init: ExternalInterface callbacks 'seCoopGo', 'seCoopPick',
    'seCoopSail', 'seCoopUnits' and 'seCoopOrder'.

Every new method runs inside a try/catch: an error falls back to the game's own way (Solitario).
"""

import struct
import zlib

from swf_abc import AbcError, disassemble
from swf_duel_bridge import DO_ABC, assemble, prepend
from swf_hud import _used_names
from swf_range_overlay import OPCODE_BY_NAME, _qname

COOP_UNITS = 10
CHOOSE_CALL, PICKED_CALL = 'seCoopChoose', 'seCoopPicked'
GO_CALLBACK, PICK_CALLBACK, SAIL_CALLBACK = 'seCoopGo', 'seCoopPick', 'seCoopSail'
UNITS_CALLBACK, ORDER_CALLBACK = 'seCoopUnits', 'seCoopOrder'
GAME_MODE_NORMAL = 1


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


def _patch_movie(data, edit):
    from swf_abc import Abc
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            payload = payload[:offset] + edit(Abc(payload[offset:])).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)


# ---------------------------------------------------------------------------------------------- every island's team

def add_quest_teams_to_abc(abc):
    body = abc.body_of(abc.method_of('PopupQuestsManager', 'goToIsland'))
    ops = disassemble(abc, body['code'])
    at = next((i for i, op in enumerate(ops) if op[1] == 'getproperty' and str(op[2]) == 'QUESTS_WITH_TEAMS'), None)
    if at is None:
        raise AbcError('The adventure teams are already on every island, or the game changed')
    start = ops[at - 1][0]  # getlex Config
    branch = next(op for op in ops[at:at + 8] if op[1] == 'ifne')  # indexOf(...) != -1: the selection branch
    target = int(str(branch[2]).lstrip('->'))
    end = ops[ops.index(branch) + 1][0]
    if ops[at - 1][1] != 'getlex' or not start < end <= target:
        raise AbcError('Unexpected goToIsland')
    jump = bytes([OPCODE_BY_NAME['jump']]) + struct.pack('<i', target - (start + 4))[:3]
    code = bytearray(body['code'])
    code[start:end] = jump + bytes([OPCODE_BY_NAME['nop']]) * (end - start - 4)
    body['code'] = bytes(code)
    return abc


def add_quest_teams(data):
    """Return the movie whose adventure islands all open the team selection."""
    return _patch_movie(data, add_quest_teams_to_abc)


# ---------------------------------------------------------------------------------------------- Solitario or Clan

def add_coop_to_abc(abc):
    base_index = abc.class_index('Base')
    base = abc.instances[base_index]
    if any(abc.multiname_name(t['name']) == '__seCoopGo' for t in base['traits']):
        raise AbcError('The adventure choice is already present')
    m = _used_names(abc, {
        ('getlex', 'Base'), ('getproperty', 'Iso'), ('callpropvoid', 'refreshTotalPlayerUnits'),
        ('findpropstrict', 'SelectionTeamWindow'), ('constructprop', 'SelectionTeamWindow'),
        ('getlex', 'SelectionTeamWindow'), ('getproperty', 'SELECTION_MODE_QUEST'), ('getproperty', 'accepted'),
        ('getproperty', 'closeMe'), ('callpropvoid', 'add'), ('callpropvoid', 'init'), ('callpropvoid', 'removeAll'),
        ('getproperty', 'selectedArmy'), ('getproperty', 'questIDtoLoad'), ('getproperty', '_selectionTeamWindow'),
        ('callpropvoid', 'closeTeamWindow'), ('callpropvoid', 'goToIsland'), ('getproperty', '_totalThumbsSelected'),
        ('getlex', 'btnClose'), ('getproperty', 'Main'), ('callproperty', 'getStage'),
        ('getproperty', 'stageWidth'), ('getproperty', 'stageHeight'), ('getproperty', 'PopUp'),
        ('getproperty', 'popupLayer'), ('getproperty', 'mapaInicializado'), ('getproperty', 'gameMode'),
        ('callpropvoid', 'loadQuestMapWithSelectedArmy')})
    n = {name: _qname(abc, name, package) for name, package in {
        'ExternalInterface': 'flash.external', 'available': '', 'call': '', 'addCallback': '', 'x': '', 'y': '',
        'parent': '', 'removeChild': '', 'addChild': '', 'visible': ''}.items()}
    s = {text: abc.add_string(text) for text in (CHOOSE_CALL, PICKED_CALL, GO_CALLBACK, PICK_CALLBACK, SAIL_CALLBACK,
                                                  UNITS_CALLBACK, ORDER_CALLBACK)}
    g = lambda name: ('getproperty', m[('getproperty', name)])  # noqa: E731
    lex_base = ('getlex', m[('getlex', 'Base')])

    def slot(traits, name):
        qname = abc.add_qname('', name)
        traits.append({'name': qname, 'kind': 0, 'data': [0, 0, 0], 'metadata': None})
        return qname

    base_static = abc.classes[base_index][1]
    quests_slot, clan_slot = slot(base_static, '__seQuests'), slot(base_static, '__seClan')
    window_slot = slot(base['traits'], '__seCoopWindow')
    manager = abc.instances[abc.class_index('PopupQuestsManager')]
    go_slot, island_slot = slot(manager['traits'], '__seGo'), slot(manager['traits'], '__seIsland')
    team_window = abc.instances[abc.class_index('SelectionTeamWindow')]

    def method(owner_class, name, params, program, max_stack, local_count, value, error_text=False):
        reference = abc.body_of(abc.method_of(owner_class, 'DebugUnitTiles' if owner_class == 'Base' else
                                              {'PopupQuestsManager': 'closeTeamWindow',
                                               'SelectionTeamWindow': 'clickOK'}[owner_class]))
        if error_text:  # the error itself goes back to the page, as text
            tail = [('label:', 'try_end'), ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('convert_s',),
                    ('returnvalue',)]
        else:
            tail = ([('label:', 'try_end'), ('label:', 'catch'), ('getlocal0',), ('pushscope',), ('pop',)]
                    + ([('pushfalse',), ('returnvalue',)] if value else [('returnvoid',)]))
        code, labels = assemble([('getlocal0',), ('pushscope',), ('label:', 'try')] + program + tail)
        index = len(abc.methods)
        abc.methods.append({'return_type': 0, 'param_types': [0] * params, 'name': abc.add_string(name), 'flags': 0,
                            'options': None, 'param_names': None})
        abc.bodies.append({'method': index, 'max_stack': max_stack, 'local_count': local_count,
                           'init_scope_depth': reference['init_scope_depth'],
                           'max_scope_depth': reference['init_scope_depth'] + 1,
                           'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                           'traits': []})
        qname = abc.add_qname('', name)
        abc.instances[abc.class_index(owner_class)]['traits'].append(
            {'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})
        return qname

    page = [('getlex', n['ExternalInterface']), ('getproperty', n['available'])]
    call_page = [('getlex', n['ExternalInterface'])]

    # PopupQuestsManager.__seAsk(island): Boolean -- true: the page chooses first.
    ask = method('PopupQuestsManager', '__seAsk', 1, [
        ('getlocal0',), ('getproperty', go_slot), ('iffalse', 'first'),
        ('getlocal0',), ('pushfalse',), ('setproperty', go_slot), ('pushfalse',), ('returnvalue',),
        ('label:', 'first')] + page + [('iffalse', 'own'),
        lex_base, ('getlocal0',), ('setproperty', quests_slot),
        ('getlocal0',), ('getlocal1',), ('setproperty', island_slot)] + call_page + [
        ('pushstring', s[CHOOSE_CALL]), ('callproperty', n['call'], 1), ('pushtrue',), ('strictequals',), ('returnvalue',),
        ('label:', 'own'), ('pushfalse',), ('returnvalue',)], 4, 2, True)

    # PopupQuestsManager.__seTaken(): Boolean -- true: a clan team went to the page; nothing sails.
    taken = method('PopupQuestsManager', '__seTaken', 0, [
        lex_base, ('getproperty', clan_slot), ('iffalse', 'no'),
        lex_base, ('pushfalse',), ('setproperty', clan_slot)] + page + [('iffalse', 'close')] + call_page + [
        ('pushstring', s[PICKED_CALL]), ('getlocal0',), g('questIDtoLoad'),
        ('getlocal0',), g('_selectionTeamWindow'), g('selectedArmy'), ('callpropvoid', n['call'], 3),
        ('label:', 'close'),
        ('getlocal0',), ('callpropvoid', m[('callpropvoid', 'closeTeamWindow')], 0),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',)], 5, 1, True)

    # PopupQuestsManager.__seClosed(): a clan choice closed without a team.
    closed_quest = method('PopupQuestsManager', '__seClosed', 0, [
        lex_base, ('getproperty', clan_slot), ('iffalse', 'done'),
        lex_base, ('pushfalse',), ('setproperty', clan_slot)] + page + [('iffalse', 'done')] + call_page + [
        ('pushstring', s[PICKED_CALL]), ('getlocal0',), g('questIDtoLoad'), ('pushnull',),
        ('callpropvoid', n['call'], 3),
        ('label:', 'done'), ('returnvoid',)], 5, 1, False)

    # SelectionTeamWindow.__seLimit(): a clan choice takes at most COOP_UNITS units.
    limit = method('SelectionTeamWindow', '__seLimit', 0, [
        lex_base, ('getproperty', clan_slot), ('iffalse', 'done'),
        ('getlocal0',), g('_totalThumbsSelected'), ('pushbyte', COOP_UNITS), ('ifngt', 'done'),
        ('getlocal0',), ('pushbyte', COOP_UNITS), ('setproperty', m[('getproperty', '_totalThumbsSelected')]),
        ('label:', 'done'), ('returnvoid',)], 3, 1, False)

    # Base.__seCoopGo(clan): Boolean -- the page's answer: to the kept island again.
    go = method('Base', '__seCoopGo', 1, [
        lex_base, ('getproperty', quests_slot), ('coerce_a',), ('setlocal2',),
        ('getlocal2',), ('iffalse', 'no'),
        lex_base, ('getlocal1',), ('convert_b',), ('setproperty', clan_slot),
        ('getlocal2',), ('pushtrue',), ('setproperty', go_slot),
        ('getlocal2',), ('getlocal2',), ('getproperty', island_slot),
        ('callpropvoid', m[('callpropvoid', 'goToIsland')], 1),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',)], 4, 3, True)

    # A guest's team: the window over the village (as swf_pvp's __selectTeam, in the adventure mode).
    finish = [('getlocal0',), ('getproperty', window_slot), ('coerce_a',), ('setlocal1',),
              ('getlocal0',), ('pushnull',), ('setproperty', window_slot),
              lex_base, ('pushfalse',), ('setproperty', clan_slot),
              ('getlocal1',), ('iffalse', 'gone'),
              ('getlocal1',), g('accepted'), ('callpropvoid', m[('callpropvoid', 'removeAll')], 0),
              ('getlocal1',), g('closeMe'), ('callpropvoid', m[('callpropvoid', 'removeAll')], 0),
              ('getlocal1',), ('getproperty', n['parent']), ('iffalse', 'gone'),
              ('getlocal1',), ('getproperty', n['parent']), ('getlocal1',), ('callpropvoid', n['removeChild'], 1),
              ('label:', 'gone')]
    picked = method('Base', '__seCoopAccepted', 0, [
        ('getlocal0',), ('getproperty', window_slot), ('coerce_a',), ('setlocal2',),
        ('getlocal2',), ('iffalse', 'done'),
        ('getlocal2',), g('selectedArmy'), ('coerce_a',), ('setlocal2',)] + finish + page + [('iffalse', 'done')]
        + call_page + [('pushstring', s[PICKED_CALL]), ('pushnull',), ('getlocal2',), ('callpropvoid', n['call'], 3),
        ('label:', 'done'), ('returnvoid',)], 5, 3, False)
    dropped = method('Base', '__seCoopClosed', 0, finish + page + [('iffalse', 'done')] + call_page + [
        ('pushstring', s[PICKED_CALL]), ('pushnull',), ('pushnull',), ('callpropvoid', n['call'], 3),
        ('label:', 'done'), ('returnvoid',)], 5, 2, False)
    half = lambda size: [lex_base, g('Main'), ('callproperty', m[('callproperty', 'getStage')], 0),  # noqa: E731
                         g(size), ('pushbyte', 2), ('divide',)]
    pick = method('Base', '__seCoopPick', 0, [
        ('getlocal0',), g('mapaInicializado'), ('iffalse', 'no'),
        ('getlocal0',), g('gameMode'), ('pushbyte', GAME_MODE_NORMAL), ('ifne', 'no'),
        ('getlocal0',), ('getproperty', window_slot), ('iftrue', 'no'),
        lex_base, ('pushtrue',), ('setproperty', clan_slot),
        lex_base, g('Iso'), ('callpropvoid', m[('callpropvoid', 'refreshTotalPlayerUnits')], 0),
        ('findpropstrict', m[('findpropstrict', 'SelectionTeamWindow')]),
        ('constructprop', m[('constructprop', 'SelectionTeamWindow')], 0), ('coerce_a',), ('setlocal1',),
        ('getlocal0',), ('getlocal1',), ('setproperty', window_slot),
        ('getlocal1',), g('accepted'), ('getlocal0',), ('getproperty', picked), ('callpropvoid', m[('callpropvoid', 'add')], 1),
        ('getlocal1',), g('closeMe'), ('getlocal0',), ('getproperty', dropped), ('callpropvoid', m[('callpropvoid', 'add')], 1),
        ('getlocal1',), ('getlex', m[('getlex', 'SelectionTeamWindow')]), g('SELECTION_MODE_QUEST'),
        ('pushnull',), ('pushbyte', 1), ('callpropvoid', m[('callpropvoid', 'init')], 3),
        ('getlocal1',), ('getproperty', m[('getlex', 'btnClose')]), ('pushtrue',), ('setproperty', n['visible']),
        ('getlocal1',)] + half('stageWidth') + [('setproperty', n['x']),
        ('getlocal1',)] + half('stageHeight') + [('setproperty', n['y']),
        lex_base, g('PopUp'), g('popupLayer'), ('getlocal1',), ('callpropvoid', n['addChild'], 1),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',)], 6, 2, True)

    # Base.__seCoopSail(quest, army): true, false (no island kept) or the game's error as text -- the clan raid
    # sets sail: the kept manager loads the island with every player's units, as after its team window
    # (questIDtoLoad, then loadQuestMapWithSelectedArmy: it counts the list of unit ids and loads the island).
    sail = method('Base', '__seCoopSail', 2, [
        lex_base, ('getproperty', quests_slot), ('coerce_a',), ('setlocal3',),
        ('getlocal3',), ('iffalse', 'no'),
        ('getlocal3',), ('getlocal1',), ('setproperty', m[('getproperty', 'questIDtoLoad')]),
        ('getlocal3',), ('getlocal2',), ('callpropvoid', m[('callpropvoid', 'loadQuestMapWithSelectedArmy')], 1),
        ('pushtrue',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',)], 4, 4, True, error_text=True)

    # ---- phase 4: the guests' units, seen and ordered from the host's game.
    u = _used_names(abc, {
        ('callproperty', 'PixelToTile'), ('getlex', 'Utils'), ('getproperty', 'buildingLayer'),
        ('callproperty', 'globalToLocal'), ('callproperty', 'localToGlobal'), ('callproperty', 'getNearestEnemy'),
        ('getproperty', 'arPlayerIsoFightingElements'), ('getlex', 'IsoUnit'), ('getproperty', 'bDead'),
        ('getproperty', 'iID'), ('getproperty', 'iHealth'), ('getproperty', 'maxLife'),
        ('callpropvoid', 'IA_Attack'), ('callpropvoid', 'IA_Move'), ('setproperty', 'TargetElement'),
        ('callproperty', 'indexOf'), ('callpropvoid', 'push'), ('getproperty', 'length'), ('getproperty', 'tx'),
        ('getproperty', 'ty'), ('getproperty', '<late>'), ('findpropstrict', 'Point'), ('constructprop', 'Point')})
    gp = lambda name: ('getproperty', u[('getproperty', name)])  # noqa: E731
    late = gp('<late>')
    units_slot = slot(base_static, '__seUnits')  # the raid's units in the order they were first seen: their handles
    for text in ('h', 'id', 'x', 'y', 'hp', 'max'):
        s[text] = abc.add_string(text)
    point = [('findpropstrict', u[('findpropstrict', 'Point')])]
    new_point = lambda: point + [('pushbyte', 0), ('pushbyte', 0), ('constructprop', u[('constructprop', 'Point')], 2)]  # noqa: E731

    # Base.__seCoopUnits(): [{h, id, x, y (stage), hp, max}] of the player's units alive on the island.
    # Locals: 1 list, 2 index, 3 unit, 4 handle, 5 stage point, 6 result.
    units = method('Base', '__seCoopUnits', 0, [
        lex_base, ('getproperty', units_slot), ('iftrue', 'kept'),
        lex_base, ('newarray', 0), ('setproperty', units_slot),
        ('label:', 'kept'),
        ('newarray', 0), ('setlocal', 6),
        lex_base, g('Iso'), gp('arPlayerIsoFightingElements'), ('setlocal1',),
        ('pushbyte', 0), ('setlocal2',),
        ('label:', 'loop'), ('label',),
        ('getlocal2',), ('getlocal1',), gp('length'), ('ifnlt', 'end'),
        ('getlocal1',), ('getlocal2',), late, ('setlocal3',),
        ('getlocal3',), ('getlex', u[('getlex', 'IsoUnit')]), ('istypelate',), ('iffalse', 'next'),
        ('getlocal3',), gp('bDead'), ('iftrue', 'next'),
        lex_base, ('getproperty', units_slot), ('getlocal3',), ('callproperty', u[('callproperty', 'indexOf')], 1),
        ('convert_i',), ('setlocal', 4),
        ('getlocal', 4), ('pushbyte', 0), ('ifge', 'known'),
        lex_base, ('getproperty', units_slot), gp('length'), ('convert_i',), ('setlocal', 4),
        lex_base, ('getproperty', units_slot), ('getlocal3',), ('callpropvoid', u[('callpropvoid', 'push')], 1),
        ('label:', 'known'),
        ('getlocal3',)] + new_point() + [('callproperty', u[('callproperty', 'localToGlobal')], 1), ('setlocal', 5),
        ('getlocal', 6),
        ('pushstring', s['h']), ('getlocal', 4),
        ('pushstring', s['id']), ('getlocal3',), gp('iID'),
        ('pushstring', s['x']), ('getlocal', 5), ('getproperty', n['x']),
        ('pushstring', s['y']), ('getlocal', 5), ('getproperty', n['y']),
        ('pushstring', s['hp']), ('getlocal3',), gp('iHealth'),
        ('pushstring', s['max']), ('getlocal3',), gp('maxLife'),
        ('newobject', 6), ('callpropvoid', u[('callpropvoid', 'push')], 1),
        ('label:', 'next'), ('getlocal2',), ('increment_i',), ('setlocal2',), ('jump', 'loop'),
        ('label:', 'end'), ('getlocal', 6), ('returnvalue',)], 16, 7, True)

    # Base.__seCoopOrder(handles, x, y): the units of those handles attack the enemy at (x, y) of the stage, or
    # walk there. Locals: 1 handles, 2-3 the point, 4 tile, 5 target, 6 index, 7 unit, 8 layer point.
    order = method('Base', '__seCoopOrder', 3, [
        lex_base, ('getproperty', units_slot), ('iffalse', 'no'),
        ('getlocal0',), gp('buildingLayer'),
        ('findpropstrict', u[('findpropstrict', 'Point')]), ('getlocal2',), ('getlocal3',),
        ('constructprop', u[('constructprop', 'Point')], 2),
        ('callproperty', u[('callproperty', 'globalToLocal')], 1), ('setlocal', 8),
        ('getlex', u[('getlex', 'Utils')]), ('getlocal', 8), ('getproperty', n['x']), ('getlocal', 8), ('getproperty', n['y']),
        ('callproperty', u[('callproperty', 'PixelToTile')], 2), ('setlocal', 4),
        # an enemy on (or right beside) that tile: the game's own search, from the player's side
        lex_base, g('Iso'), ('getlocal', 4), gp('tx'), ('getlocal', 4), gp('ty'), ('pushfalse',), ('pushbyte', 2),
        ('callproperty', u[('callproperty', 'getNearestEnemy')], 4), ('setlocal', 5),
        ('pushbyte', 0), ('setlocal', 6),
        ('label:', 'loop'), ('label',),
        ('getlocal', 6), ('getlocal1',), gp('length'), ('ifnlt', 'done'),
        lex_base, ('getproperty', units_slot), ('getlocal1',), ('getlocal', 6), late, late, ('setlocal', 7),
        ('getlocal', 7), ('iffalse', 'next'),
        ('getlocal', 7), gp('bDead'), ('iftrue', 'next'),
        ('getlocal', 5), ('iffalse', 'walk'),
        ('getlocal', 7), ('getlocal', 5), ('setproperty', u[('setproperty', 'TargetElement')]),
        ('getlocal', 7), ('getlocal', 5), ('callpropvoid', u[('callpropvoid', 'IA_Attack')], 1), ('jump', 'next'),
        ('label:', 'walk'),
        ('getlocal', 7), ('pushnull',), ('setproperty', u[('setproperty', 'TargetElement')]),
        ('getlocal', 7), ('getlocal', 4), gp('tx'), ('getlocal', 4), gp('ty'),
        ('callpropvoid', u[('callpropvoid', 'IA_Move')], 2),
        ('label:', 'next'), ('getlocal', 6), ('increment_i',), ('setlocal', 6), ('jump', 'loop'),
        ('label:', 'done'), ('pushtrue',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',)], 8, 9, True, error_text=True)

    register = method('Base', '__registerCoop', 0, page + [('iffalse', 'done')] + [
        ('getlex', n['ExternalInterface']), ('pushstring', s[UNITS_CALLBACK]), ('getlocal0',), ('getproperty', units),
        ('callpropvoid', n['addCallback'], 2),
        ('getlex', n['ExternalInterface']), ('pushstring', s[ORDER_CALLBACK]), ('getlocal0',), ('getproperty', order),
        ('callpropvoid', n['addCallback'], 2),
        ('getlex', n['ExternalInterface']), ('pushstring', s[SAIL_CALLBACK]), ('getlocal0',), ('getproperty', sail),
        ('callpropvoid', n['addCallback'], 2),
        ('getlex', n['ExternalInterface']), ('pushstring', s[GO_CALLBACK]), ('getlocal0',), ('getproperty', go),
        ('callpropvoid', n['addCallback'], 2),
        ('getlex', n['ExternalInterface']), ('pushstring', s[PICK_CALLBACK]), ('getlocal0',), ('getproperty', pick),
        ('callpropvoid', n['addCallback'], 2),
        ('label:', 'done'), ('returnvoid',)], 4, 1, False)

    op = OPCODE_BY_NAME
    skip_return = bytes([op['iffalse']]) + struct.pack('<i', 1)[:3] + bytes([op['returnvoid']])
    body = abc.body_of(abc.method_of('PopupQuestsManager', 'goToIsland'))
    prepend(body, bytes([op['getlocal0'], op['getlocal1'], op['callproperty']]) + _u30(ask) + _u30(1) + skip_return)
    body['max_stack'] = max(body['max_stack'], 2)
    body = abc.body_of(abc.method_of('PopupQuestsManager', 'questTeamSelected'))
    prepend(body, bytes([op['getlocal0'], op['callproperty']]) + _u30(taken) + _u30(0) + skip_return)
    body['max_stack'] = max(body['max_stack'], 1)
    body = abc.body_of(abc.method_of('PopupQuestsManager', 'closeTeamWindow'))
    prepend(body, bytes([op['getlocal0'], op['callpropvoid']]) + _u30(closed_quest) + _u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    body = abc.body_of(abc.method_of('SelectionTeamWindow', 'onThumbUnitClick'))
    prepend(body, bytes([op['getlocal0'], op['callpropvoid']]) + _u30(limit) + _u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    body = abc.body_of(abc.method_of('Base', 'init'))
    prepend(body, bytes([op['getlocal0'], op['callpropvoid']]) + _u30(register) + _u30(0))
    body['max_stack'] = max(body['max_stack'], 1)
    del team_window
    return abc


def add_coop(data):
    """Return the movie with the Solitario / Clan choice before an adventure."""
    return _patch_movie(data, add_coop_to_abc)
