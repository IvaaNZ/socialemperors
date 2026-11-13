"""The in-game PvP window (SE_PVP=on): rivals, raids and duels without leaving the game.

The game's "PvP" button (swf_pvp.py) calls window.seOpenPvp(); the window
(templates/js/pvp_overlay.js) reads this JSON API. A raid from the window
fights with the team chosen in the game's own team window (sent as `army`);
the raid rules are the same as on the rivals page (pvp.RaidService). Duels go
through the duel connection (duels.js), with the chosen team as well.

Nothing here exists unless SE_PVP=on: install_pvp() is only called then.
"""

import json
import secrets
import sqlite3

from flask import abort, g, jsonify, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired

from auth import validate_csrf
from portal_i18n import translate as _
from pvp import RaidError, parse_team

RAID_RESULT_KEYS = ('id', 'won', 'loot', 'total_loot', 'attacker_power', 'defender_power', 'attacker_troops',
                    'defender_name')


def overlay_texts():
    return {
        'title': _('PvP'), 'close': _('Fechar'), 'loading': _('Carregando…'),
        'tab_rivals': _('Rivais'), 'tab_raids': _('Saques'), 'tab_duels': _('Duelos'),
        'your_attack': _('Seu ataque: {power} ({troops} tropas mais fortes)'),
        'choose_note': _('Ao atacar ou desafiar, você escolhe até {count} tropas na janela do jogo.'),
        'level': _('Nível {level}'), 'defense': _('Defesa: {power}'), 'loot': _('Saque possível: {amount}'),
        'attack': _('Atacar'), 'challenge': _('Desafiar'), 'busy': _('Ocupado'),
        'no_rivals': _('Nenhuma vila rival por enquanto'), 'next_attack': _('Próximo ataque em {time}.'),
        'no_raids': _('Nenhum combate ainda'),
        'raid_won': _('Você saqueou {name}.'), 'raid_lost': _('Seu ataque foi defendido por {name}.'),
        'defended': _('Você defendeu sua vila de {name}.'), 'robbed': _('Sua vila foi saqueada por {name}.'),
        'raid_line': _('Ataque {mine} contra defesa {theirs} · {amount} recursos'),
        'result_won': _('Vitória contra {name}! Você saqueou {amount} recursos com {troops} tropas.'),
        'result_lost': _('A defesa de {name} venceu. Ataque {mine} contra defesa {theirs}.'),
        'online': _('Jogadores conectados'), 'nobody': _('Ninguém mais está conectado agora.'),
        'duels_off': _('Os duelos não estão ativos neste servidor.'),
        'rating': _('Sua pontuação: {rating}'), 'last_duels': _('Últimos duelos'), 'no_duels': _('Nenhum duelo ainda.'),
        'duel_won': _('Vitória contra {name}'), 'duel_lost': _('Derrota contra {name}'), 'duel_draw': _('Empate com {name}'),
        'duel_void': _('Duelo anulado contra {name}'), 'duel_review': _('Duelo em revisão contra {name}'),
        'duel_line': _('{mine}% contra {theirs}%'),
        'choosing': _('Escolha suas tropas na janela do jogo.'),
        'not_ready': _('Volte para a sua vila para escolher as tropas.'),
        'no_team': _('Escolha pelo menos uma tropa.'),
        'error': _('Não foi possível concluir. Tente novamente.'),
        'portal': _('Abrir a página completa'),
        'resources': {'coins': _('Ouro'), 'wood': _('Madeira'), 'food': _('Comida'), 'stone': _('Pedra')},
    }


def install_pvp(app, accounts, village_lock, recover_raids, raids, eligible_village_ids, raid_tokens, team_limit):
    def current_player():
        account = g.get('account')
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        if session.get('USERID') != account['village_id']:
            return None
        return account

    @app.context_processor
    def pvp_context():
        if not current_player():
            return {}
        duels = app.extensions.get('duels') is not None
        return {'pvp_overlay': {
            'state': url_for('pvp_api_state'), 'raid': url_for('pvp_api_raid'), 'rivals': url_for('rival_villages'),
            'duels': url_for('duels_page') if duels else '', 'teamLimit': team_limit, 'texts': overlay_texts(),
        }}

    def duel_summary(account):
        hub = app.extensions.get('duels')
        if hub is None:
            return None
        names = {row['id']: row['name'] for row in accounts().list_accounts()}
        history = []
        for duel in hub.store.history(account['id'], limit=8):
            side = 'challenger' if duel['challenger_id'] == account['id'] else 'defender'
            other = 'defender' if side == 'challenger' else 'challenger'
            if duel['status'] in ('void', 'review'):
                outcome = duel['status']
            elif duel['winner'] == 'draw':
                outcome = 'draw'
            else:
                outcome = 'won' if duel['winner'] == side else 'lost'
            history.append({'other': names.get(duel[f'{other}_id'], '?'), 'outcome': outcome,
                            'mine': duel[f'{side}_percent'], 'theirs': duel[f'{other}_percent']})
        return {'rating': hub.store.rating(account['id']), 'history': history}

    @app.get('/pvp/api/state', endpoint='pvp_api_state')
    def pvp_state():
        account = current_player()
        if not account:
            abort(403)
        with village_lock:
            recover_raids()
            try:
                overview = raids().overview(session['USERID'], eligible_village_ids())
            except RaidError as exc:
                return jsonify({'error': _(str(exc))}), 400
        rivals = []
        for rival in overview['rivals']:
            rivals.append({
                'id': rival['userid'], 'name': rival['name'], 'level': rival['level'],
                'defense': rival['defense_power'], 'loot': sum(rival['estimated_loot'].values()),
                'can_attack': rival['can_attack'], 'reason': _(rival['blocked_reason']) if rival['blocked_reason'] else '',
                'token': raid_tokens().dumps({'attacker': session['USERID'], 'defender': rival['userid'],
                                              'nonce': secrets.token_hex(16)}),
            })
        history = [{'role': entry['role'], 'name': entry['enemy_name'], 'won': entry['won'],
                    'loot': entry['total_loot'], 'mine': entry['attacker_power'] if entry['role'] == 'attacker' else entry['defender_power'],
                    'theirs': entry['defender_power'] if entry['role'] == 'attacker' else entry['attacker_power'],
                    'at': entry['created_at']} for entry in overview['history']]
        own = overview['own']
        return jsonify({'own': {'attack': own['attack_power'], 'troops': own['troop_count'],
                                'attack_available_at': own['attack_available_at']},
                        'rivals': rivals, 'history': history, 'duels': duel_summary(account), 'me': account['id']})

    @app.post('/pvp/api/raid', endpoint='pvp_api_raid')
    def pvp_raid():
        validate_csrf()
        account = current_player()
        if not account:
            abort(403)
        defender_id = request.form.get('defender_id', '')
        try:
            token = raid_tokens().loads(request.form.get('raid_token', ''), max_age=3600)
        except (BadSignature, SignatureExpired):
            return jsonify({'error': _('A solicitação de ataque expirou ou é inválida. Volte à lista de rivais e tente novamente.')}), 400
        if not isinstance(token, dict) or token.get('attacker') != session['USERID'] or token.get('defender') != defender_id:
            return jsonify({'error': _('A solicitação de ataque não pertence à sua vila ou a este rival.')}), 403
        try:
            team = parse_team(json.loads(request.form.get('army', 'null')))
        except ValueError:
            return jsonify({'error': _('Escolha pelo menos uma tropa da sua vila para atacar.')}), 400
        with village_lock:
            recover_raids()
            try:
                result = raids().raid(session['USERID'], defender_id, eligible_village_ids(), token.get('nonce'), team=team)
            except RaidError as exc:
                return jsonify({'error': _(str(exc))}), 400
            except (OSError, sqlite3.Error):
                app.logger.exception('A transferência do saque aguarda recuperação.')
                return jsonify({'error': _('Não foi possível finalizar o saque agora. A transferência será recuperada antes da próxima ação; atualize a página em instantes.')}), 503
        return jsonify({'result': {key: result.get(key) for key in RAID_RESULT_KEYS}})
