"""Web side of the live duels: WebSocket, arena services, pages and texts.

Installed by server.py only when SE_DUELS=on; with duels off nothing here is
imported, so no route, template variable or thread exists.

The WebSocket accepts a connection only from an approved, logged-in player
whose session village matches the account, and only from a page of this same
site (the Origin header must name this host). Each page holds one connection;
the DuelHub (duels.py) keeps them, the challenges and the battles.

Battles use the game's own tournament mode (swf_duel_bridge.py adds the way
in): the game loads the arena map (ARENA_MAP_ID, served here from
config/duels/arena.json or SE_DUEL_ARENA_FILE) and calls two tournament
services, answered here with the signed "hash;payload" format of the game's
ServiceManager:

  * start_tournament_match.php: the player pressed "start" (server clock);
  * finish_tournament_match.php: attacker_points = percentage of the enemy
    army destroyed (the bridge makes the game send that).

Units killed in the arena call the game's "kill"/"sell" commands with the
player's town, but CommandManager.addCommand only queues commands in the
NORMAL game mode, so the game never sends them from the arena. As a second
guard, while a player is in the battle (from the start service to the report
or the deadline) any unit-death command of that village is dropped.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from flask import Response, abort, flash, g, redirect, render_template, request, session, url_for
from flask_sock import ConnectionClosed, Sock

from auth import validate_csrf
from duels import (ARENA_MAP_ID, ARENA_TOURNAMENT_TYPE, ARMY_LIMIT, BATTLE_DEADLINE_SECONDS, BATTLE_MIN_SECONDS, CHALLENGE_SECONDS,
                   RANKED_MIN_LEVEL, SIDES, SUSPICIOUS_POWER_RATIO, DuelError, DuelHub, DuelStore, army_profile,
                   start_sweeper, utc_label)
from portal_i18n import translate as _

MAX_MESSAGE_SIZE = 4096
PING_INTERVAL = 25  # seconds; keeps hosting proxies from closing idle sockets
SERVICE_KEY = b'3m0d3pwiupoetn7ysa02'  # Config.SERVER_KEY of the game (HMAC-SHA256 of service payloads)
GAME_PATH = '/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/'
DEFAULT_ARENA_FILE = Path(__file__).resolve().parent / 'config' / 'duels' / 'arena.json'


def duel_texts():
    """Texts the duel script shows, in the viewer's language (Portuguese source)."""
    return {
        'connecting': _('Conectando aos duelos…'),
        'offline': _('Sem conexão com os duelos. Tentando novamente…'),
        'nobody': _('Ninguém mais está conectado agora.'),
        'challenge': _('Desafiar'),
        'busy_label': _('Ocupado'),
        'received': _('{name} desafiou você para um duelo!'),
        'sent': _('Desafio enviado a {name}. Aguardando resposta…'),
        'seconds': _('{seconds} s'),
        'accept': _('Aceitar'),
        'decline': _('Recusar'),
        'cancel': _('Cancelar'),
        'close': _('Fechar'),
        'declined': _('{name} recusou o desafio.'),
        'expired': _('O desafio expirou.'),
        'cancelled': _('O desafio foi cancelado.'),
        'disconnected': _('{name} se desconectou; o desafio foi cancelado.'),
        'won': _('Vitória contra {name}!'),
        'lost': _('Derrota contra {name}.'),
        'draw': _('Empate contra {name}.'),
        'void': _('Duelo contra {name} anulado.'),
        'review': _('Duelo contra {name} em revisão.'),
        'ranked': _('Ranqueado: {before} → {after} pontos'),
        'friendly': _('Amistoso: não altera o ranking (os dois precisam de nível {level}).'),
        'not_rated': _('Não altera o ranking.'),
        'review_detail': _('O resultado é muito improvável para a força dos exércitos: só conta para o ranking se um administrador o validar.'),
        'void_detail': _('Nenhum dos dois informou um resultado válido a tempo.'),
        'void_restart': _('O servidor reiniciou durante a batalha.'),
        'line': _('{name}: {percent}% do exército rival em {time}'),
        'line_missing': _('{name}: não informou o resultado a tempo'),
        'line_too_fast': _('{name}: batalha curta demais (mínimo {seconds} s)'),
        'line_invalid': _('{name}: resultado inválido'),
        'line_not_started': _('{name}: não começou a batalha'),
        'starting': _('Duelo aceito contra {name}! Entrando na arena…'),
        'going_to_game': _('Abrindo o jogo para a batalha…'),
        'game_in_other_tab': _('A batalha abre na sua aba do jogo.'),
        'arena_help': _('Comande suas tropas contra o exército de {name}. Vence quem destruir a maior porcentagem do exército rival; em caso de empate, quem terminar mais rápido.'),
        'waiting': _('Esperando {name} terminar a batalha…'),
        'time_left': _('Tempo restante: {time}'),
        'game_not_ready': _('Volte para a sua vila no jogo para entrar na arena.'),
        'error_self': _('Você não pode desafiar a si mesmo.'),
        'error_offline': _('Este jogador não está conectado.'),
        'error_busy': _('Você já tem um desafio pendente.'),
        'error_target_busy': _('Este jogador já tem um desafio pendente.'),
        'error_rate_limited': _('Muitos desafios seguidos. Aguarde um minuto.'),
        'error_tutorial': _('Conclua o tutorial para duelar.'),
        'error_no_troops': _('Treine pelo menos uma tropa combatente para duelar.'),
        'error_target_not_ready': _('O outro jogador ainda não pode duelar.'),
        'error_gone': _('Este desafio não existe mais.'),
        'error_invalid': _('Mensagem inválida.'),
    }


def is_unit_death(item):
    """A game command that removes a unit killed in battle: 'kill', or 'sell' with reason KILL."""
    args = item.get('args')
    if item.get('cmd') == 'kill':
        return True
    return item.get('cmd') == 'sell' and isinstance(args, list) and len(args) > 5 and args[5] == 'KILL'


def service_response(data):
    """A tournament service answer: HMAC-SHA256(SERVER_KEY, payload) + ';' + payload."""
    payload = json.dumps({'data': data}, separators=(',', ':'))
    signature = hmac.new(SERVICE_KEY, payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return Response(f'{signature};{payload}', mimetype='text/plain')


def service_params():
    """Parameters the game's ServiceManager sent ('hash;json' in `data`), or {}."""
    raw = request.values.get('data', '')
    _, _, text = raw.partition(';') if ';' in raw[:65] else ('', '', raw)
    try:
        params = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return params if isinstance(params, dict) else {}


def with_duel_tournament(config):
    """The game config with the arena's tournament type in the original weekly mode.

    TournamentIA only leaves its waiting state (advance, then attack) in weekly
    tournaments; with weekly_tournaments 0 the rival army forms up, steps
    forward and then waits forever. The served copy turns it on; the config
    itself is not changed.
    """
    types = config.get('tournament_type') if isinstance(config, dict) else None
    key = str(ARENA_TOURNAMENT_TYPE)
    if not isinstance(types, dict) or not isinstance(types.get(key), dict):
        return config
    served = dict(config)
    served['tournament_type'] = {**types, key: {**types[key], 'weekly_tournaments': 1, 'map_id': ARENA_MAP_ID}}
    return served


def load_arena(path=None):
    path = Path(path or os.environ.get('SE_DUEL_ARENA_FILE') or DEFAULT_ARENA_FILE)
    arena = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(arena, dict) or not isinstance(arena.get('map', {}).get('items'), list):
        raise ValueError(f'Invalid duel arena map: {path}')
    return arena


def install_duels(app, accounts, village_lock, all_saves_userid, village_session, data_dir, number_format,
                  validate_game_key):
    """Register the duel routes and start the hub (called only with SE_DUELS=on)."""
    store = DuelStore(data_dir / 'duels.sqlite3')
    arena = load_arena()

    def profile(account_id):
        account = accounts().get(account_id)
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        with village_lock:
            if account['village_id'] not in all_saves_userid():
                return None
            result = army_profile(village_session(account['village_id']))
        result['name'] = account['name']
        return result

    hub = DuelHub(store, profile)
    app.extensions['duels'] = hub
    app.config.setdefault('SOCK_SERVER_OPTIONS', {'ping_interval': PING_INTERVAL, 'max_message_size': MAX_MESSAGE_SIZE})
    sock = Sock(app)
    start_sweeper(hub)
    arena_villages = {}  # village id -> account id, for players who entered the arena

    def current_player():
        account = g.get('account')
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        if session.get('USERID') != account['village_id']:
            return None
        return account

    def same_origin():
        origin = request.headers.get('Origin', '')
        return bool(origin) and urlsplit(origin).netloc == request.host

    def game_player():
        """The player behind a game request (server.protect_access already tied USERID to the session)."""
        if 'USERID' in request.values:
            validate_game_key(request.values['USERID'])
        return current_player()

    @app.before_request
    def guard_duel_socket():
        # Runs before the WebSocket handshake: without a valid session or from
        # another site the request ends with 403 and no socket is opened.
        if request.path == '/duels/ws' and (not current_player() or not same_origin()):
            abort(403)

    @app.before_request
    def serve_arena_map():
        # The arena is loaded like an adventure map (get_player_info with user=<map id>).
        if request.path == GAME_PATH + 'get_player_info.php' and request.values.get('user') == str(ARENA_MAP_ID):
            validate_game_key(request.values.get('USERID', ''))
            return arena

    def filter_commands(userid, commands):
        account_id = arena_villages.get(userid)
        if account_id is None or not hub.guards_commands(account_id):
            return commands
        kept = []
        for item in commands:
            if is_unit_death(item):  # same console log style as command.py
                print(f" [duel] arena command dropped for {userid}: {item.get('cmd')}({item.get('args')})")
            else:
                kept.append(item)
        return kept

    app.extensions['duel_command_filter'] = filter_commands

    original_config_view = app.view_functions['get_game_config_response']
    served_configs = {}

    def duel_game_config():
        config = original_config_view()
        if not isinstance(config, dict):
            return config
        cached = served_configs.get(id(config))
        if cached is None or cached[0] is not config:
            cached = served_configs[id(config)] = (config, with_duel_tournament(config))
        return cached[1]

    app.view_functions['get_game_config_response'] = duel_game_config

    @app.route(GAME_PATH + 'tournaments/start_tournament_match.php', methods=['GET', 'POST'])
    def duel_start_match():
        account = game_player()
        if not account:
            return service_response({'result': 'NOK'})
        try:
            hub.start_match(account['id'])
        except DuelError:
            return service_response({'result': 'NOK'})
        arena_villages[account['village_id']] = account['id']
        return service_response({'result': 'OK'})

    @app.route(GAME_PATH + 'tournaments/finish_tournament_match.php', methods=['GET', 'POST'])
    def duel_finish_match():
        account = game_player()
        if account:
            try:
                hub.report(account['id'], service_params().get('attacker_points'))
            except DuelError:
                pass
        # Always OK: the game then shows its result window and goes back home; the
        # duel notice on the page tells the real outcome.
        return service_response({'result': 'OK'})

    @app.context_processor
    def duel_context():
        if not current_player():
            return {}
        # url_for() returns a full ws:// URL for WebSocket routes; the page needs the path.
        return {'duel_config': {'wsPath': request.script_root + '/duels/ws', 'pageUrl': url_for('duels_page'),
                                'playUrl': url_for('play'), 'rankedLevel': RANKED_MIN_LEVEL,
                                'minSeconds': int(BATTLE_MIN_SECONDS), 'texts': duel_texts()}}

    @sock.route('/duels/ws', endpoint='duels_socket')
    def duels_socket(ws):
        account = current_player()
        if not account or not same_origin():  # also checked before the handshake
            ws.close(reason=1008, message='forbidden')
            return
        connection = hub.connect(account['id'], account['name'], lambda message: ws.send(json.dumps(message)))
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    continue
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    message = None
                hub.handle(account['id'], message)
        except ConnectionClosed:
            pass
        finally:
            hub.disconnect(account['id'], connection)

    def outcome_for(duel, side):
        if duel['status'] in ('void', 'review'):
            return duel['status']
        if duel['winner'] == 'draw':
            return 'draw'
        return 'won' if duel['winner'] == side else 'lost'

    @app.get('/duels', endpoint='duels_page')
    def duels_page():
        account = current_player()
        if not account:
            if not g.get('account'):
                return redirect(url_for('login'))
            abort(403, description='Sua conta não está aprovada.')
        names = {row['id']: row['name'] for row in accounts().list_accounts()}
        mine = profile(account['id']) or {'level': 1, 'power': 0, 'troops': 0}
        ranking = [{**row, 'name': names.get(row['account_id'], '?')} for row in store.ranking()]
        history = []
        for duel in store.history(account['id']):
            side = 'challenger' if duel['challenger_id'] == account['id'] else 'defender'
            other_side = 'defender' if side == 'challenger' else 'challenger'
            history.append({'other': names.get(duel[f'{other_side}_id'], '?'), 'outcome': outcome_for(duel, side),
                            'ranked': bool(duel['rated']), 'eligible': bool(duel['ranked']), 'mine': duel[f'{side}_power'], 'theirs': duel[f'{other_side}_power'],
                            'my_percent': duel[f'{side}_percent'], 'their_percent': duel[f'{other_side}_percent'],
                            'created_label': utc_label(duel['created_at'])})
        return render_template('duels.html', me=mine, my_rating=store.rating(account['id']), ranking=ranking,
                               history=history, ranked_level=RANKED_MIN_LEVEL, army_limit=ARMY_LIMIT,
                               challenge_seconds=CHALLENGE_SECONDS, min_seconds=int(BATTLE_MIN_SECONDS),
                               deadline_minutes=max(1, round(BATTLE_DEADLINE_SECONDS / 60)))

    def require_admin():
        account = g.get('account')
        if not account or not account['is_admin'] or account['status'] != 'approved':
            abort(403, description='Esta página é exclusiva dos administradores.')
        return account

    def admin_row(duel, names):
        row = dict(duel)
        for side in SIDES:
            row[f'{side}_name'] = names.get(duel[f'{side}_id'], '?')
        row['created_label'] = utc_label(duel['created_at'])
        row['resolved_label'] = utc_label(duel['resolved_at']) if duel['resolved_at'] else ''
        return row

    @app.get('/admin/duels', endpoint='admin_duels')
    def admin_duels():
        require_admin()
        names = {row['id']: row['name'] for row in accounts().list_accounts()}
        pending, resolved = store.reviews()
        return render_template('admin_duels.html', pending=[admin_row(d, names) for d in pending],
                               resolved=[admin_row(d, names) for d in resolved],
                               ratio_percent=round(SUSPICIOUS_POWER_RATIO * 100))

    @app.post('/admin/duels/<int:duel_id>', endpoint='admin_resolve_duel')
    def admin_resolve_duel(duel_id):
        admin = require_admin()
        validate_csrf()
        try:
            duel = store.resolve(duel_id, request.form.get('action', ''), admin['name'], hub.clock())
        except DuelError as error:
            flash('Este duelo já foi resolvido.' if error.code == 'gone' else 'Ação inválida.', 'error')
            return redirect(url_for('admin_duels'))
        hub.deliver_result(hub.result_message(duel))  # both players hear the decision
        flash('Duelo validado: conta para o ranking.' if duel['status'] == 'done' else 'Duelo anulado.', 'success')
        return redirect(url_for('admin_duels'))

    return hub
