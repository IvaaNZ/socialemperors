"""The in-game season pass window (SE_SEASON_PASS): levels, rewards and challenges without leaving the game.

The game's "Pase" button (swf_season_pass.py) calls window.seOpenSeasonPass(); the window
(templates/js/season_pass_overlay.js) reads this JSON API. Claiming adds the rewards to the village and changes its
revision (season_pass.revision, part of server.village_revision): like a treasury claim, the page then pauses the
game and asks to reload it, so the game shows the new gold, cash and gifts.

Raids and duels also count for the pass: install_season_pass() returns record_for(userid, event, once), which the
raid routes call, and listens to finished duels.

Nothing here exists unless SE_SEASON_PASS=on: install_season_pass() is only called then.
"""

from flask import abort, g, jsonify, request, session, url_for

from auth import validate_csrf
from portal_i18n import translate as _
from season_pass import SeasonPass, record_event


def overlay_texts():
    return {
        'title': _('Passe de temporada'), 'close': _('Fechar'), 'loading': _('Carregando…'),
        'season': _('Passe de {season} {year}'),
        'seasons': {'summer': _('Verão'), 'autumn': _('Outono'), 'winter': _('Inverno'), 'spring': _('Primavera')},
        'tab_rewards': _('Recompensas'), 'tab_challenges': _('Desafios do passe'),
        'level': _('Nível {level}'), 'level_of': _('Nível {level} de {levels}'),
        'points': _('{points} de {total} pontos para o próximo nível'), 'max_level': _('Nível máximo alcançado!'),
        'ends_in': _('Termina em {time}'), 'play_today': _('Pontos por jogar hoje: {points} de {cap}'),
        'claim': _('Receber'), 'claim_all': _('Receber tudo ({count})'), 'claimed': _('Recebido'), 'locked': _('Bloqueado'),
        'unit': _('Unidade: {name}'), 'cash': _('{amount} de dinheiro'),
        'resources': {'coins': _('{amount} de ouro'), 'wood': _('{amount} de madeira'), 'food': _('{amount} de comida'),
                      'stone': _('{amount} de pedra')},
        'daily': _('Desafios diários'), 'weekly': _('Desafios semanais'),
        'daily_in': _('Novos desafios em {time}'), 'weekly_in': _('Novos desafios em {time}'),
        'reward_points': _('+{points} pontos'), 'done': _('Concluído'),
        'challenges': {
            'collect': _('Coletar {target} vezes nos seus edifícios'),
            'quest_win': _('Vencer {target} ilhas de aventura'),
            'raid_win': _('Vencer {target} saques'),
            'world_attack_win': _('Vencer {target} ataques no Explorador do mundo'),
            'duel_play': _('Jogar {target} duelos'),
            'duel_win': _('Vencer {target} duelos'),
        },
        'challenges_one': {  # the same with a target of 1
            'collect': _('Coletar 1 vez nos seus edifícios'),
            'quest_win': _('Vencer 1 ilha de aventura'),
            'raid_win': _('Vencer 1 saque'),
            'world_attack_win': _('Vencer 1 ataque no Explorador do mundo'),
            'duel_play': _('Jogar 1 duelo'),
            'duel_win': _('Vencer 1 duelo'),
        },
        'how': _('Ganhe pontos jogando (coletar, aventuras, saques, Explorador, duelos) e muito mais com os desafios.'),
        'received': _('Você recebeu {count} recompensas. Recarregue a vila para vê-las; as unidades estão nos presentes.'),
        'reload': _('Recarregar a vila'),
        'error': _('Não foi possível concluir. Tente novamente.'),
        'days': _('{days} d'), 'hours': _('{hours} h'), 'minutes': _('{minutes} min'),
    }


def install_season_pass(app, village_lock, village_session, save_village, unit_name, accounts=None):
    def current_player():
        account = g.get('account')
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        if session.get('USERID') != account['village_id']:
            return None
        return account

    @app.context_processor
    def season_pass_context():
        if not current_player():
            return {}
        return {'season_pass_overlay': {
            'state': url_for('season_pass_api_state'), 'claim': url_for('season_pass_api_claim'),
            'play': url_for('play'), 'texts': overlay_texts(),
        }}

    def icon_of(reward):
        """The reward's picture (templates/img/season_pass, drawn by tools/make_season_pass_icons.py)."""
        name = (f"unit_{reward['unit']}" if 'unit' in reward else 'cash' if 'cash' in reward else reward['resource'])
        return url_for('images', path=f'season_pass/{name}.png')

    def state_of(userid):
        view = SeasonPass(village_session(userid)).view()
        for row in view['rewards']:
            extra = {'icon': icon_of(row['reward'])}
            if 'unit' in row['reward']:
                extra['name'] = unit_name(row['reward']['unit'])
            row['reward'] = {**row['reward'], **extra}
        return view

    @app.get('/season-pass/api/state', endpoint='season_pass_api_state')
    def season_pass_state():
        if not current_player():
            abort(403)
        with village_lock:
            userid = session['USERID']
            before = village_session(userid).get('privateState', {}).get('seasonPass')
            view = state_of(userid)
            if village_session(userid)['privateState'].get('seasonPass') is not before:
                save_village(userid)  # a new day, week or season was set up: keep it
        return jsonify(view)

    @app.post('/season-pass/api/claim', endpoint='season_pass_api_claim')
    def season_pass_claim():
        validate_csrf()
        if not current_player():
            abort(403)
        wanted = request.form.get('level', 'all')
        try:
            levels = None if wanted == 'all' else [int(wanted)]
        except ValueError:
            return jsonify({'error': _('Não foi possível concluir. Tente novamente.')}), 400
        with village_lock:
            userid = session['USERID']
            given = SeasonPass(village_session(userid)).claim(levels)
            if given:
                save_village(userid)
            view = state_of(userid)
        return jsonify({'given': [{'level': level, 'reward': reward} for level, reward in given], 'state': view})

    def record_for(userid, event, once=None):
        """Count a raid or a duel for a village (the caller may already hold village_lock: it is reentrant)."""
        with village_lock:
            save = village_session(userid)
            if save is not None and record_event(save, event, once=once):
                save_village(userid)

    def on_duel(duel):
        if accounts is None:
            return
        for side in ('challenger', 'defender'):
            account = accounts().get(duel.get(f'{side}_id'))
            if not account or not account.get('village_id'):
                continue
            record_for(account['village_id'], 'duel_play', once=duel.get('id'))
            if duel.get('winner') == side:
                record_for(account['village_id'], 'duel_win', once=duel.get('id'))

    app.extensions['season_pass'] = {'record_for': record_for, 'on_duel': on_duel}
    return record_for
