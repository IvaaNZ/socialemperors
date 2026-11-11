"""Web side of the live duels: WebSocket, /duels page and page texts.

Installed by server.py only when SE_DUELS=on; with duels off nothing here is
imported, so no route, template variable or thread exists.

The WebSocket accepts a connection only from an approved, logged-in player
whose session village matches the account, and only from a page of this same
site (the Origin header must name this host). Each page holds one connection;
the DuelHub (duels.py) keeps them and the challenges.
"""

import json
from urllib.parse import urlsplit

from flask import abort, g, redirect, render_template, request, session, url_for
from flask_sock import ConnectionClosed, Sock

from duels import (ARMY_LIMIT, CHALLENGE_SECONDS, RANKED_MIN_LEVEL, DuelHub, DuelStore, army_profile,
                   start_sweeper, utc_label)
from portal_i18n import translate as _

MAX_MESSAGE_SIZE = 4096
PING_INTERVAL = 25  # seconds; keeps hosting proxies from closing idle sockets


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
        'powers': _('Sua força: {mine} · Força de {name}: {theirs}'),
        'ranked': _('Ranqueado: {before} → {after} pontos'),
        'friendly': _('Amistoso: não altera o ranking (os dois precisam de nível {level}).'),
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


def install_duels(app, accounts, village_lock, all_saves_userid, village_session, data_dir, number_format):
    """Register the duel routes and start the hub (called only with SE_DUELS=on)."""
    store = DuelStore(data_dir / 'duels.sqlite3')

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

    @app.before_request
    def guard_duel_socket():
        # Runs before the WebSocket handshake: without a valid session or from
        # another site the request ends with 403 and no socket is opened.
        if request.path == '/duels/ws' and (not current_player() or not same_origin()):
            abort(403)

    @app.context_processor
    def duel_context():
        if not current_player():
            return {}
        # url_for() returns a full ws:// URL for WebSocket routes; the page needs the path.
        return {'duel_config': {'wsPath': request.script_root + '/duels/ws', 'pageUrl': url_for('duels_page'),
                                'rankedLevel': RANKED_MIN_LEVEL, 'texts': duel_texts()}}

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
            is_challenger = duel['challenger_id'] == account['id']
            other = duel['defender_id'] if is_challenger else duel['challenger_id']
            side = 'challenger' if is_challenger else 'defender'
            outcome = 'draw' if duel['winner'] == 'draw' else 'won' if duel['winner'] == side else 'lost'
            history.append({'other': names.get(other, '?'), 'outcome': outcome, 'ranked': bool(duel['ranked']),
                            'mine': duel[f'{side}_power'],
                            'theirs': duel['defender_power' if is_challenger else 'challenger_power'],
                            'created_label': utc_label(duel['created_at'])})
        return render_template('duels.html', me=mine, my_rating=store.rating(account['id']), ranking=ranking,
                               history=history, ranked_level=RANKED_MIN_LEVEL, army_limit=ARMY_LIMIT,
                               challenge_seconds=CHALLENGE_SECONDS)

    return hub
