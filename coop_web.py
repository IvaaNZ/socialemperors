"""The clan raid's room in the game page (SE_COOP=on, with clans; COOP_PLAN.md phase 1).

Routes (JSON, for templates/js/coop_overlay.js):
  * GET  /coop/api/state: the player's clan, open room (players, their state and team size, who is online),
    invitations waiting for an answer, and the clan's members to invite;
  * POST /coop/api/action (CSRF): create (quest, team), invite (room, account), respond (room, accept),
    team (room, team), leave (room).
Every change reaches the room's players live through the duel connection: 'coop_invite' to an invited player,
'coop_update' to the others (their pages read the state again).
"""

import json

from flask import abort, g, jsonify, request, session, url_for

from auth import validate_csrf
from coop import (CLAN_REWARD, DIFFICULTY_STEP, MAX_PLAYERS, PRESTIGE_GROUP, PRESTIGE_SOLO, SOLO_REWARD, TEAM_UNITS,
                  CoopError, CoopStore)
import os

from duels_web import is_unit_death
from portal_i18n import translate as _


SIGNAL_LIMIT = 20000  # characters of one connection message (an offer with its network details fits)


def ice_servers():
    """The STUN servers the browsers use to find each other (SE_COOP_STUN, comma separated; 'off': none, which
    only connects players on the same network). A STUN server sees the players' network addresses, nothing else."""
    value = os.environ.get('SE_COOP_STUN', 'stun:stun.l.google.com:19302').strip()
    if value.lower() in ('', 'off', 'none'):
        return []
    return [{'urls': [url.strip() for url in value.split(',') if url.strip()]}]


def overlay_texts():
    """Texts of the choice and the room, in the viewer's language (Portuguese source)."""
    return {
        'choose_title': _('Como você quer jogar esta aventura?'),
        'solo': _('Solitário'), 'solo_detail': _('Você joga sozinho, com até 20 unidades.'),
        'clan': _('Com o clã'),
        'clan_detail': _('Até 3 membros do seu clã jogam juntos, com até 10 unidades cada um.'),
        'cancel': _('Cancelar'), 'close': _('Fechar'),
        'no_clan': _('Você precisa estar em um clã para jogar com o clã.'),
        'room_title': _('Incursão do clã'), 'adventure': _('Aventura'),
        'players': _('Jogadores ({count}/{max})'), 'members': _('Convidar membros do clã'),
        'nobody': _('Nenhum outro membro do seu clã está conectado agora.'),
        'host': _('Anfitrião'), 'invited': _('Convidado'), 'accepted': _('Aceitou'),
        'units': _('{count} unidades prontas'), 'choosing': _('Escolhendo unidades…'),
        'online': _('Conectado'), 'offline': _('Desconectado'), 'invite': _('Convidar'),
        'sail': _('Zarpar'), 'sail_soon': _('Zarpar juntos chega na próxima etapa.'),
        'waiting': _('Esperando que todos escolham suas unidades.'),
        'waiting_host': _('Esperando que o anfitrião zarpe.'),
        'sailing_host': _('A incursão está em curso: suas tropas e as do clã estão na ilha.'),
        'sailing_guest': _('{name} está jogando a ilha com as tropas de todos. Em breve você poderá assistir ao vivo.'),
        'end_raid': _('Terminar a incursão'), 'no_island': _('Abra o mapa de aventuras e escolha a ilha de novo.'),
        'watching': _('Assistindo ao vivo a ilha de {name}'), 'connecting': _('Conectando com a ilha de {name}…'),
        'no_video': _('Não foi possível ver a ilha ao vivo. A incursão continua.'),
        'retry': _('Tentar de novo'),
        'command_hint': _('Toque uma das suas unidades para escolhê-la; depois toque o mapa para movê-la ou um inimigo para atacar.'),
        'all_units': _('Todas as minhas unidades'), 'my_units': _('Minhas unidades: {count}'),
        'none_alive': _('Suas unidades caíram. Continue assistindo à incursão.'),
        'raid_won': _('Vitória na incursão do clã!'), 'raid_lost': _('A incursão do clã terminou sem vitória.'),
        'raid_share': _('Cada jogador recebe {gold} de ouro e {xp} de XP.'),
        'raid_prestige': _('O clã ganha {points} de prestígio.'),
        'close_room': _('Fechar a sala'), 'leave': _('Sair da sala'),
        'invite_title': _('{name} convida você para uma incursão do clã'),
        'invite_detail': _('Leve até 10 unidades da sua aldeia.'),
        'accept': _('Aceitar'), 'decline': _('Recusar'), 'pick': _('Escolher minhas unidades'),
        'change_team': _('Trocar minhas unidades'), 'room_closed': _('A sala da incursão foi fechada.'),
        'not_village': _('Volte para a sua aldeia para escolher as unidades.'),
        'errors': {
            'team': _('Escolha entre 1 e 10 unidades.'), 'busy': _('Você já está em outra incursão.'),
            'full': _('A incursão já tem 3 jogadores.'), 'clan': _('Só membros do seu clã podem entrar.'),
            'already': _('Esse jogador já está na sala.'), 'gone': _('A sala não existe mais.'),
            'forbidden': _('Não foi possível fazer isso.'), 'quest': _('Ilha desconhecida.'),
            'not_ready': _('Todos precisam escolher suas unidades.'),
        },
    }


def scaled_end_quest(item, factor):
    """An end_quest command with its gold and experience times factor (the island's reward), and its data."""
    data = json.loads(item['args'][0])
    resources = data.get('resources', {})
    for key in ('g', 'x'):
        resources[key] = int(int(resources.get(key, 0)) * factor)
    return dict(item, args=[json.dumps(data)] + list(item['args'][1:])), data


def install_coop(app, accounts, data_dir, village_lock=None, village_session=None, save_village=None):
    """Register the room's routes (SE_COOP=on with SE_CLANS=on)."""
    clans = app.extensions.get('clans')
    if clans is None:
        return None
    store = CoopStore(data_dir / 'coop.sqlite3')
    app.extensions['coop'] = store

    def current_player():
        account = g.get('account')
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        if session.get('USERID') != account['village_id']:
            return None
        return account

    def api_player():
        account = current_player()
        if not account:
            abort(403, description='Sua conta não está aprovada.')
        return account

    def hub():
        return app.extensions.get('duels')

    def online(account_id):
        live = hub()
        return bool(live and live.is_online(account_id))

    def names():
        return {row['id']: row['name'] for row in accounts().list_accounts()}

    def notify(room, skip=None, invited=None):
        live = hub()
        if live is None or not room:
            return
        for player in room['players']:
            if player['account_id'] == skip:
                continue
            if player['account_id'] == invited:
                live.send_to(invited, {'type': 'coop_invite', 'room': room['id']})
            elif room['status'] == 'sailing' and player['state'] == 'accepted':
                live.send_to(player['account_id'], {'type': 'coop_sail', 'room': room['id']})
            elif player['state'] in ('host', 'accepted', 'invited'):
                live.send_to(player['account_id'], {'type': 'coop_update', 'room': room['id']})

    def room_view(room, me, everyone):
        players = [p for p in room['players'] if p['state'] in ('host', 'invited', 'accepted')]
        return {
            'id': room['id'], 'quest': room['quest_id'], 'host': room['host_id'], 'is_host': room['host_id'] == me,
            'status': room['status'], 'can_sail': store.ready_to_sail(room), 'max': MAX_PLAYERS,
            'players': [{'id': p['account_id'], 'name': everyone.get(p['account_id'], '?'), 'state': p['state'],
                         'units': len(p['team']) if p['team'] else 0, 'team': p['team'] or [],
                         'online': online(p['account_id'])}
                        for p in players],
        }

    def state(account):
        me = account['id']
        everyone = names()
        membership = clans.membership(me)
        clan = None
        members = []
        if membership:
            clan = {'id': membership['clan_id'], 'tag': membership['clan']['tag'], 'name': membership['clan']['name']}
            roster = clans.clan(membership['clan_id']) or {'members': []}
            members = [{'id': m['account_id'], 'name': everyone.get(m['account_id'], '?'), 'online': online(m['account_id'])}
                       for m in roster['members'] if m['account_id'] != me]
            members.sort(key=lambda m: (not m['online'], m['name'].lower()))
        room = store.room_of(me)
        invites = [{'room': r['id'], 'host': everyone.get(r['host_id'], '?'), 'quest': r['quest_id']}
                   for r in store.invites_of(me)]
        return {'me': me, 'clan': clan, 'members': members, 'invites': invites,
                'room': room_view(room, me, everyone) if room else None, 'team_units': TEAM_UNITS}

    @app.get('/coop/api/state', endpoint='coop_api_state')
    def coop_api_state():
        return jsonify(state(api_player()))

    @app.post('/coop/api/action', endpoint='coop_api_action')
    def coop_api_action():
        account = api_player()
        validate_csrf()
        form = request.form
        action = form.get('action', '')
        me = account['id']

        def number(field):
            try:
                return int(form.get(field, ''))
            except ValueError:
                raise CoopError('forbidden') from None

        def team():
            try:
                return json.loads(form.get('team', ''))
            except ValueError:
                raise CoopError('team') from None

        try:
            if action == 'create':
                membership = clans.membership(me)
                if not membership:
                    raise CoopError('clan')
                room = store.create(me, membership['clan_id'], form.get('quest', ''), team())
            elif action == 'invite':
                guest = number('account')
                membership = clans.membership(guest)
                room = store.invite(me, number('room'), guest, membership['clan_id'] if membership else None)
                notify(room, skip=me, invited=guest)
            elif action == 'respond':
                room = store.respond(me, number('room'), form.get('accept') == '1')
                notify(room, skip=me)
            elif action == 'team':
                room = store.set_team(me, number('room'), team())
                notify(room, skip=me)
            elif action == 'leave':
                room = store.leave(me, number('room'))
                notify(room, skip=me)
            elif action == 'sail':
                room = store.sail(me, number('room'))
                notify(room, skip=me)
                return jsonify({'ok': True, 'state': state(account), 'quest': room['quest_id'], 'army': store.army(room)})
            else:
                raise CoopError('forbidden')
        except CoopError as error:
            return jsonify({'ok': False, 'error': error.code, 'state': state(account)}), 400
        return jsonify({'ok': True, 'state': state(account)})

    @app.post('/coop/api/signal', endpoint='coop_api_signal')
    def coop_api_signal():
        """The video's connection messages (WebRTC offer, answer, network candidates, a guest's "join") between
        two players of the same raid at sea, relayed live; the video itself goes from browser to browser."""
        account = api_player()
        validate_csrf()
        live = hub()
        if live is None:
            return jsonify({'ok': False, 'error': 'live'}), 400
        payload_text = request.form.get('payload', '')
        if len(payload_text) > SIGNAL_LIMIT:
            return jsonify({'ok': False, 'error': 'forbidden'}), 400
        try:
            target = int(request.form.get('to', ''))
            payload = json.loads(payload_text)
        except ValueError:
            return jsonify({'ok': False, 'error': 'forbidden'}), 400
        room = store.sailing_room_of(account['id'])
        members = {p['account_id'] for p in room['players'] if p['state'] in ('host', 'accepted')} if room else set()
        if not isinstance(payload, dict) or account['id'] not in members or target not in members or target == account['id']:
            return jsonify({'ok': False, 'error': 'gone'}), 400
        live.send_to(target, {'type': 'coop_signal', 'room': room['id'], 'from': account['id'], 'payload': payload})
        return jsonify({'ok': True})

    def village_of(account_id):
        account = accounts().get(account_id)
        return account['village_id'] if account else None

    def credit(village_id, gold, xp):
        """A guest's share of the island, into its home village."""
        if not village_id or village_lock is None:
            return
        with village_lock:
            save = village_session(village_id)
            home = save['maps'][0]
            home['coins'] = int(home.get('coins', 0)) + gold
            home['xp'] = int(home.get('xp', 0)) + xp
            save_village(village_id)

    def lose_unit(village_id, unit_id):
        """A unit lost in a raid leaves its owner's village: one of that kind on the home map."""
        if not village_id or village_lock is None:
            return False
        with village_lock:
            save = village_session(village_id)
            items = save['maps'][0]['items']
            for item in items:
                if item and int(item[0]) == unit_id:
                    items.remove(item)
                    save_village(village_id)
                    return True
        return False

    def end_raid(room, data, players):
        """The host's island ended: each player's share, the clan's prestige, the guests told."""
        win = int(data.get('win', 0)) == 1
        gold = int(data.get('resources', {}).get('g', 0))
        xp = int(data.get('resources', {}).get('x', 0))
        for player in players:
            if player['state'] == 'accepted':
                credit(village_of(player['account_id']), gold, xp)
            store.village_changed(village_of(player['account_id']))  # their open games reload
        prestige = None
        if win and len(players) >= 2:
            prestige = clans.add_prestige(room['clan_id'], PRESTIGE_GROUP)
        store.finish(room['id'])
        live = hub()
        if live is not None:
            for player in players:
                live.send_to(player['account_id'], {'type': 'coop_end', 'room': room['id'], 'win': win, 'gold': gold,
                                                    'xp': xp, 'prestige': PRESTIGE_GROUP if prestige is not None else 0})
        print(f" [coop] raid {room['id']} ended: win={win}, {gold} gold and {xp} XP each for {len(players)} players")

    def filter_commands(userid, commands):
        """The game's commands, before the village applies them:
          * the host of a raid at sea: unit deaths dropped (they mix every player's units; the host's page reports
            each loss to its owner, coop_api_death), and the island's end gives each player CLAN_REWARD of it;
          * anyone else: an island ended alone gives SOLO_REWARD of it, and prestige to the player's clan if won.
        The guests' games are in their own villages: their deaths count as always."""
        account_id = next((row['id'] for row in accounts().list_accounts() if row.get('village_id') == userid), None)
        room = store.sailing_room_of(account_id) if account_id is not None else None
        hosting = room is not None and room['host_id'] == account_id
        kept = []
        for item in commands:
            if hosting and is_unit_death(item):
                print(f" [coop] raid command dropped for {userid}: {item.get('cmd')}({item.get('args')})")
                continue
            if item.get('cmd') == 'end_quest' and item.get('args'):
                try:
                    if hosting:
                        item, data = scaled_end_quest(item, CLAN_REWARD)
                        players = [p for p in room['players'] if p['state'] in ('host', 'accepted') and p['team']]
                        end_raid(room, data, players)
                    else:
                        item, data = scaled_end_quest(item, SOLO_REWARD)
                        membership = clans.membership(account_id) if account_id is not None else None
                        if int(data.get('win', 0)) == 1 and membership:
                            clans.add_prestige(membership['clan_id'], PRESTIGE_SOLO)
                except (ValueError, TypeError, KeyError, IndexError) as error:
                    print(f" [coop] end_quest left as it was for {userid}: {error}")
            kept.append(item)
        return kept

    @app.post('/coop/api/death', endpoint='coop_api_death')
    def coop_api_death():
        """The host's page: a unit of the raid died; it leaves its owner's village (once)."""
        account = api_player()
        validate_csrf()
        try:
            room_id, handle = int(request.form.get('room', '')), int(request.form.get('handle', ''))
            owner, unit = int(request.form.get('owner', '')), int(request.form.get('unit', ''))
            first = store.record_death(account['id'], room_id, handle, owner, unit)
        except (ValueError, CoopError):
            return jsonify({'ok': False}), 400
        removed = lose_unit(village_of(owner), unit) if first else False
        print(f" [coop] raid {room_id}: unit {unit} of player {owner} died" + (' (left its village)' if removed else ''))
        return jsonify({'ok': True, 'removed': removed})

    app.extensions['coop_command_filter'] = filter_commands

    @app.context_processor
    def coop_context():
        if not current_player():
            return {}
        return {'coop_overlay': {'state': url_for('coop_api_state'), 'action': url_for('coop_api_action'),
                                 'signal': url_for('coop_api_signal'), 'ice': ice_servers(),
                                 'death': url_for('coop_api_death'), 'difficulty': DIFFICULTY_STEP,
                                 'texts': overlay_texts()}}

    return store
