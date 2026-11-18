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
from coop import MAX_PLAYERS, TEAM_UNITS, CoopError, CoopStore
from duels_web import is_unit_death
from portal_i18n import translate as _


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


def install_coop(app, accounts, data_dir):
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
                         'units': len(p['team']) if p['team'] else 0, 'online': online(p['account_id'])}
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

    def filter_commands(userid, commands):
        """During a raid at sea, the host's game reports the deaths of every player's units: none of them may
        leave the host's village. Phase 5 gives each loss to its owner; until then nobody loses units."""
        account_id = next((row['id'] for row in accounts().list_accounts() if row.get('village_id') == userid), None)
        if account_id is None or store.sailing_room_of(account_id) is None:
            return commands
        kept = []
        for item in commands:
            if is_unit_death(item):
                print(f" [coop] raid command dropped for {userid}: {item.get('cmd')}({item.get('args')})")
            else:
                kept.append(item)
        return kept

    app.extensions['coop_command_filter'] = filter_commands

    @app.context_processor
    def coop_context():
        if not current_player():
            return {}
        return {'coop_overlay': {'state': url_for('coop_api_state'), 'action': url_for('coop_api_action'),
                                 'texts': overlay_texts()}}

    return store
