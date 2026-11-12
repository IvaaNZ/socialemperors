"""Web side of the clans (SE_CLANS=on): pages, actions and the admin section.

Installed by server.py only when SE_CLANS=on; with clans off nothing here is
imported, so no route or template variable exists. Every action is a POST
with the CSRF token, made by an approved, logged-in player whose session
village matches the account; the permission itself is checked again by
ClanStore inside the transaction, so a hand-made request cannot skip it.
"""

from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from auth import validate_csrf
from clans import (ANNOUNCEMENT_LENGTH, CHALLENGE_ANSWER_SECONDS, CHALLENGE_SIZES, DESCRIPTION_LENGTH, EMBLEMS,
                   MAX_ASSISTS, MAX_MEMBERS, MAX_OPEN_REQUESTS, NAME_LENGTH, RECRUIT_LANGUAGES, REJOIN_SECONDS,
                   REQUEST_SECONDS, TAG_LENGTH, ClanError, ClanStore)
from portal_i18n import translate as _
from duels import utc_label

# Error codes -> Portuguese source text (translated when the flash message is shown).
ERRORS = {
    'already_in_clan': 'Você já está em um clã.',
    'rejoin_wait': 'Você saiu de um clã há pouco. Aguarde uma hora para entrar em outro.',
    'name_taken': 'Já existe um clã com esse nome.',
    'tag_taken': 'Já existe um clã com essa etiqueta.',
    'bad_name': 'O nome do clã deve ter de 3 a 24 caracteres: letras, números, espaços, ponto, hífen ou apóstrofo.',
    'bad_tag': 'A etiqueta deve ter de 2 a 5 letras (sem acentos) ou números.',
    'bad_description': 'A descrição pode ter até 200 caracteres.',
    'clan_full': 'O clã está completo (70 membros).',
    'already_requested': 'Você já pediu para entrar neste clã.',
    'too_many_requests': 'Você já tem 3 pedidos abertos. Cancele um para pedir outro.',
    'gone': 'Este pedido não existe mais.',
    'forbidden': 'Você não tem permissão para fazer isso.',
    'too_many_assists': 'O clã já tem 3 Assist.',
    'not_in_clan': 'Você não está em um clã.',
    'transfer_first': 'Transfira a liderança antes de sair do clã.',
    'reason_required': 'Informe o motivo.',
    'no_clan': 'Este clã não existe mais.',
    'tutorial': 'Conclua o tutorial para criar um clã.',
    'confirm': 'Marque a confirmação para dissolver o clã.',
    'bad_size': 'Escolha melhor de 3, 5 ou 7 duelos.',
    'own_clan': 'Você não pode desafiar o seu próprio clã.',
    'challenge_busy': 'O seu clã já tem um desafio pendente ou em andamento.',
    'target_challenge_busy': 'Esse clã já tem um desafio pendente ou em andamento.',
    'bad_announcement': 'O anúncio pode ter até 500 caracteres.',
    'bad_settings': 'Confira o emblema, o nível mínimo e o idioma.',
    'level_too_low': 'Sua vila principal não tem o nível mínimo deste clã.',
    'not_open': 'Este clã aceita membros só por pedido.',
}


def overlay_texts():
    """Texts of the in-game clan window, in the viewer's language (Portuguese source)."""
    return {
        'button': _('Clã'), 'title': _('Clã'), 'close': _('Fechar'), 'loading': _('Carregando…'),
        'tab_clan': _('Meu clã'), 'tab_members': _('Membros'), 'tab_challenges': _('Desafios'),
        'tab_ranking': _('Classificação'), 'tab_find': _('Buscar clã'), 'tab_create': _('Criar clã'),
        'no_clan': _('Você ainda não está em um clã. Busque um clã para entrar ou crie o seu.'),
        'search_placeholder': _('Buscar por nome ou etiqueta'), 'search': _('Buscar'),
        'members_count': _('{count} de {max} membros'), 'power': _('Poder {power}'), 'level_min': _('Nível {level}+'),
        'open': _('Aberto'), 'by_request': _('Com pedido'), 'join': _('Entrar'), 'ask': _('Pedir para entrar'),
        'requested': _('Pedido enviado'), 'cancel_request': _('Cancelar pedido'), 'view': _('Ver'), 'back': _('Voltar'),
        'leader': _('Líder: {name}'), 'your_rank': _('Seu cargo: {role}'),
        'master': _('Guild Master'), 'assist': _('Assist'), 'member': _('Membro'),
        'announcement': _('Anúncio'), 'no_announcement': _('Ainda não há anúncio.'),
        'recruitment': _('Recrutamento'), 'language_all': _('Todos os idiomas'),
        'language_es': _('Espanhol'), 'language_pt-BR': _('Português'), 'language_en': _('Inglês'),
        'edit': _('Editar'), 'save': _('Salvar'), 'cancel': _('Cancelar'), 'dissolve': _('Dissolver clã'),
        'dissolve_confirm': _('Quero dissolver o clã: todos os membros saem e não dá para desfazer.'),
        'leave': _('Sair do clã'), 'leave_confirm': _('Tem certeza de que quer sair do clã?'),
        'emblem': _('Emblema'), 'motto': _('Lema'), 'name': _('Nome'), 'tag': _('Etiqueta'),
        'min_level': _('Nível mínimo'), 'language': _('Idioma'), 'recruit_mode': _('Entrada'),
        'create': _('Criar clã'), 'create_tutorial': _('Conclua o tutorial para criar um clã.'),
        'rejoin_wait': _('Você saiu de um clã há pouco. Poderá entrar em outro ou criar um em {minutes} min.'),
        'requests': _('Pedidos para entrar'), 'no_requests': _('Nenhum pedido pendente.'),
        'accept': _('Aceitar'), 'reject': _('Recusar'), 'make_assist': _('Nomear Assist'), 'remove_assist': _('Tirar Assist'),
        'transfer': _('Passar liderança'), 'kick': _('Remover'), 'you': _('você'),
        'transfer_confirm': _('Passar a liderança para {name}? Você vira membro comum.'),
        'kick_confirm': _('Remover {name} do clã?'),
        'challenge_title': _('Desafio entre clãs'), 'no_challenge': _('Nenhum desafio agora.'),
        'challenge_hint': _('Para desafiar outro clã, busque-o e abra a ficha dele.'),
        'challenge_incoming': _('{name} desafiou o seu clã para o melhor de {count} duelos.'),
        'challenge_outgoing': _('Vocês desafiaram {name} para o melhor de {count} duelos. Esperando a resposta…'),
        'minutes_left': _('Restam {minutes} min para responder.'), 'only_master_answers': _('Só o Guild Master pode responder.'),
        'accept_challenge': _('Aceitar desafio'), 'decline_challenge': _('Recusar desafio'), 'cancel_challenge': _('Cancelar desafio'),
        'best_of_against': _('Melhor de {count} contra {name}'),
        'needed': _('Vence o clã que chegar primeiro a {needed} vitórias. Cada duelo terminado entre os dois clãs soma uma vitória.'),
        'duel_line': _('{winner} venceu {loser}'), 'go_duels': _('Ir para Duelos'),
        'surrender': _('Render-se'), 'surrender_confirm': _('Render-se? O outro clã ganha o desafio.'),
        'challenge_clan': _('Desafiar este clã'), 'best_of': _('Melhor de'), 'duels_count': _('{count} duelos'),
        'challenge_send': _('Desafiar'), 'answer_minutes': _('O Guild Master do outro clã tem {minutes} min para aceitar.'),
        'history': _('Desafios anteriores'), 'won': _('Vitória'), 'lost': _('Derrota'),
        'declined': _('Recusado'), 'expired': _('Venceu sem resposta'), 'cancelled': _('Cancelado'),
        'by_majority': _('por maioria'), 'by_surrender': _('por rendição'), 'by_dissolved': _('o clã rival foi dissolvido'),
        'ranking': _('Ranking de clãs'), 'no_ranking': _('Ainda não há desafios terminados.'),
        'challenges_won': _('Desafios ganhos'), 'challenges_lost': _('Desafios perdidos'), 'duels_won': _('Duelos ganhos'),
        'no_clans': _('Nenhum clã encontrado.'), 'error': _('Não foi possível concluir. Tente de novo.'),
        'portal_page': _('Abrir no portal'),
    }


def install_clans(app, accounts, village_lock, all_saves_userid, village_session, data_dir):
    """Register the clan routes (called only with SE_CLANS=on)."""
    store = ClanStore(data_dir / 'clans.sqlite3')
    app.extensions['clans'] = store

    def current_player():
        account = g.get('account')
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        if session.get('USERID') != account['village_id']:
            return None
        return account

    def player_or_redirect():
        account = current_player()
        if account:
            return account
        if not g.get('account'):
            abort(redirect(url_for('login')))
        abort(403, description='Sua conta não está aprovada.')

    def tutorial_complete(account):
        with village_lock:
            if account['village_id'] not in all_saves_userid():
                return False
            info = village_session(account['village_id']).get('playerInfo', {})
        try:
            return int(info.get('completed_tutorial') or 0) == 1
        except (TypeError, ValueError):
            return False

    def names():
        return {row['id']: row['name'] for row in accounts().list_accounts()}

    def notify(account_id, message):
        """A live notice through the duel connection (only when duels are on too)."""
        hub = app.extensions.get('duels')
        if hub is not None and account_id:
            hub.send_to(account_id, message)

    def master_id(clan_id):
        clan = store.clan(clan_id)
        return next((m['account_id'] for m in clan['members'] if m['role'] == 'master'), None) if clan else None

    def challenge_view(challenge, clan_id, everyone):
        """A challenge as seen from one of its two clans."""
        if not challenge:
            return None
        ours_first = challenge['challenger_clan'] == clan_id
        view = dict(challenge)
        view.update(
            incoming=challenge['defender_clan'] == clan_id,
            rival_id=challenge['defender_clan'] if ours_first else challenge['challenger_clan'],
            rival_tag=challenge['defender_tag'] if ours_first else challenge['challenger_tag'],
            rival_name=challenge['defender_name'] if ours_first else challenge['challenger_name'],
            our_wins=challenge['challenger_wins'] if ours_first else challenge['defender_wins'],
            their_wins=challenge['defender_wins'] if ours_first else challenge['challenger_wins'],
            needed=challenge['best_of'] // 2 + 1,
            outcome=('won' if challenge.get('winner_clan') == clan_id else 'lost') if challenge.get('winner_clan') else None,
            minutes_left=-(-challenge.get('expires_in', 0) // 60),
            when=utc_label(challenge.get('finished_at') or challenge.get('ended_at') or challenge['created_at']),
        )
        view['duel_lines'] = [{'winner': everyone.get(d['winner_id'], '?'), 'loser': everyone.get(d['loser_id'], '?'),
                               'ours': d['winner_clan'] == clan_id} for d in challenge.get('duels', [])]
        return view

    def act(action, success, back):
        """Run one clan action; flash its result and go back."""
        validate_csrf()
        try:
            result = action()
        except ClanError as error:
            flash(ERRORS.get(error.code, ERRORS['forbidden']), 'error')
            return redirect(back)
        message = success(result) if callable(success) else success
        if message:
            flash(message, 'success')
        return redirect(back)

    @app.context_processor
    def clan_context():
        context = {'clan_limits': {'members': MAX_MEMBERS, 'assists': MAX_ASSISTS, 'requests': MAX_OPEN_REQUESTS,
                                   'name': NAME_LENGTH, 'tag': TAG_LENGTH, 'description': DESCRIPTION_LENGTH,
                                   'request_days': REQUEST_SECONDS // 86400, 'rejoin_minutes': REJOIN_SECONDS // 60,
                                   'sizes': CHALLENGE_SIZES, 'answer_minutes': CHALLENGE_ANSWER_SECONDS // 60}}
        account = current_player()
        if account:
            context['clan_overlay'] = {'state': url_for('clan_api_state'), 'search': url_for('clan_api_search'),
                                       'clan': url_for('clan_api_clan', clan_id=0).rsplit('/', 1)[0] + '/',
                                       'action': url_for('clan_api_action'), 'portal': url_for('clans_page'),
                                       'duels': url_for('duels_page') if app.extensions.get('duels') is not None else '',
                                       'texts': overlay_texts()}
        if account and app.extensions.get('duels') is not None:
            # For the duel pages: clan tags next to the names, and the rivals of an active challenge.
            membership = store.membership(account['id'])
            challenge = store.current_challenge(membership['clan_id']) if membership else None
            rivals = []
            if challenge and challenge['status'] == 'active':
                rivals = [player for player, clan in challenge['roster'].items() if clan != membership['clan_id']]
            context['clan_duels'] = {'tags': {str(k): v for k, v in store.member_tags().items()}, 'rivals': rivals}
        return context

    @app.get('/clans', endpoint='clans_page')
    def clans_page():
        account = player_or_redirect()
        search = request.args.get('q', '')[:40]
        membership = store.membership(account['id'])
        return render_template('clans.html', clans=store.clans(search), search=search, membership=membership,
                               ranking=store.ranking(),
                               my_requests=store.requests_of(account['id']),
                               requested={r['clan_id'] for r in store.requests_of(account['id'])},
                               rejoin_minutes=-(-store.rejoin_wait(account['id']) // 60),
                               can_create=tutorial_complete(account))

    @app.post('/clans', endpoint='clans_create')
    def clans_create():
        account = player_or_redirect()

        def create():
            if not tutorial_complete(account):
                raise ClanError('tutorial')
            return store.create(account['id'], request.form.get('name', ''), request.form.get('tag', ''),
                                request.form.get('description', ''), actor_name=account['name'])
        validate_csrf()
        try:
            clan = create()
        except ClanError as error:
            flash(ERRORS.get(error.code, ERRORS['forbidden']), 'error')
            return redirect(url_for('clans_page'))
        flash('Clã criado.', 'success')
        return redirect(url_for('clan_page', clan_id=clan['id']))

    @app.get('/clans/<int:clan_id>', endpoint='clan_page')
    def clan_page(clan_id):
        account = player_or_redirect()
        clan = store.clan(clan_id)
        if not clan:
            abort(404, description='Este clã não existe mais.')
        everyone = names()
        mine = next((m for m in clan['members'] if m['account_id'] == account['id']), None)
        role = mine['role'] if mine else None
        for member in clan['members']:
            member['name'] = everyone.get(member['account_id'], '?')
            member['joined_label'] = utc_label(member['joined_at'])
        requests_list = []
        if role in ('master', 'assist'):
            for item in store.requests_for(clan_id):
                requests_list.append({**item, 'name': everyone.get(item['account_id'], '?'),
                                      'created_label': utc_label(item['created_at'])})
        membership = store.membership(account['id'])
        current = challenge_view(store.current_challenge(clan_id), clan_id, everyone)
        history = [challenge_view(item, clan_id, everyone) for item in store.challenge_history(clan_id)]
        can_challenge = (not role and membership and membership['role'] == 'master' and not current
                         and not store.current_challenge(membership['clan_id']))
        return render_template('clan.html', clan=clan, role=role, me=account['id'], requests=requests_list,
                               challenge=current, history=history, can_challenge=can_challenge,
                               own_challenge=challenge_view(store.current_challenge(membership['clan_id']),
                                                            membership['clan_id'], everyone) if membership and not role else None,
                               membership=membership,
                               requested=any(r['clan_id'] == clan_id for r in store.requests_of(account['id'])),
                               assist_count=sum(m['role'] == 'assist' for m in clan['members']),
                               rejoin_minutes=-(-store.rejoin_wait(account['id']) // 60),
                               log=[{**entry, 'created_label': utc_label(entry['created_at']),
                                     'target_name': everyone.get(entry['target_id'], '') if entry['target_id'] else ''}
                                    for entry in store.log(clan_id, limit=15)] if role else [])

    @app.post('/clans/<int:clan_id>/request', endpoint='clan_request')
    def clan_request(clan_id):
        account = player_or_redirect()
        back = url_for('clan_page', clan_id=clan_id)
        if request.form.get('action') == 'cancel':
            return act(lambda: store.cancel_request(account['id'], clan_id), 'Pedido cancelado.', back)
        return act(lambda: store.request_join(account['id'], clan_id), 'Pedido enviado. Um líder do clã vai responder.', back)

    @app.post('/clans/requests/<int:request_id>', endpoint='clan_answer')
    def clan_answer(request_id):
        account = player_or_redirect()
        membership = store.membership(account['id'])
        back = url_for('clan_page', clan_id=membership['clan_id']) if membership else url_for('clans_page')
        accept = request.form.get('action') == 'accept'
        return act(lambda: store.answer_request(account['id'], request_id, accept, actor_name=account['name']),
                   'Membro aceito.' if accept else 'Pedido recusado.', back)

    @app.post('/clans/members/<int:target_id>', endpoint='clan_member_action')
    def clan_member_action(target_id):
        account = player_or_redirect()
        membership = store.membership(account['id'])
        back = url_for('clan_page', clan_id=membership['clan_id']) if membership else url_for('clans_page')
        action = request.form.get('action')
        actions = {
            'kick': (lambda: store.kick(account['id'], target_id, actor_name=account['name']), 'Membro removido do clã.'),
            'assist': (lambda: store.set_role(account['id'], target_id, 'assist', actor_name=account['name']), 'Agora é Assist.'),
            'member': (lambda: store.set_role(account['id'], target_id, 'member', actor_name=account['name']), 'Deixou de ser Assist.'),
            'transfer': (lambda: store.transfer(account['id'], target_id, actor_name=account['name']), 'Liderança transferida.'),
        }
        if action not in actions:
            abort(400, description='Ação inválida.')
        return act(actions[action][0], actions[action][1], back)

    @app.post('/clans/leave', endpoint='clan_leave')
    def clan_leave():
        account = player_or_redirect()
        return act(lambda: store.leave(account['id'], actor_name=account['name']),
                   lambda result: 'O clã foi dissolvido.' if result == 'dissolved' else 'Você saiu do clã.',
                   url_for('clans_page'))

    @app.post('/clans/edit', endpoint='clan_edit')
    def clan_edit():
        account = player_or_redirect()
        membership = store.membership(account['id'])
        back = url_for('clan_page', clan_id=membership['clan_id']) if membership else url_for('clans_page')
        return act(lambda: store.edit(account['id'], request.form.get('description', ''), actor_name=account['name']),
                   'Descrição atualizada.', back)

    @app.post('/clans/dissolve', endpoint='clan_dissolve')
    def clan_dissolve():
        account = player_or_redirect()

        def dissolve():
            if request.form.get('confirm') != 'yes':
                raise ClanError('confirm')
            store.dissolve(account['id'], actor_name=account['name'])
        membership = store.membership(account['id'])
        validate_csrf()
        try:
            dissolve()
        except ClanError as error:
            flash(ERRORS.get(error.code, ERRORS['forbidden']), 'error')
            return redirect(url_for('clan_page', clan_id=membership['clan_id']) if membership else url_for('clans_page'))
        flash('O clã foi dissolvido.', 'success')
        return redirect(url_for('clans_page'))

    @app.post('/clans/<int:clan_id>/challenge', endpoint='clan_challenge')
    def clan_challenge(clan_id):
        account = player_or_redirect()
        validate_csrf()
        try:
            challenge = store.challenge(account['id'], clan_id, request.form.get('best_of'), actor_name=account['name'])
        except ClanError as error:
            flash(ERRORS.get(error.code, ERRORS['forbidden']), 'error')
            return redirect(url_for('clan_page', clan_id=clan_id))
        notify(master_id(clan_id), {
            'type': 'clan_challenge', 'id': challenge['id'], 'best_of': challenge['best_of'],
            'clan': {'tag': challenge['challenger_tag'], 'name': challenge['challenger_name']},
            'minutes': CHALLENGE_ANSWER_SECONDS // 60, 'url': url_for('clan_page', clan_id=clan_id)})
        flash('Desafio enviado. O outro clã tem 10 minutos para responder.', 'success')
        return redirect(url_for('clan_page', clan_id=challenge['challenger_clan']))

    @app.post('/clans/challenges/<int:challenge_id>', endpoint='clan_challenge_action')
    def clan_challenge_action(challenge_id):
        account = player_or_redirect()
        membership = store.membership(account['id'])
        back = url_for('clan_page', clan_id=membership['clan_id']) if membership else url_for('clans_page')
        action = request.form.get('action')
        validate_csrf()
        try:
            if action in ('accept', 'decline'):
                challenge = store.answer_challenge(account['id'], challenge_id, action == 'accept', actor_name=account['name'])
                notify(master_id(challenge['challenger_clan']), {
                    'type': 'clan_challenge_answer', 'id': challenge_id, 'accepted': action == 'accept',
                    'clan': {'tag': challenge['defender_tag'], 'name': challenge['defender_name']},
                    'url': url_for('clan_page', clan_id=challenge['challenger_clan'])})
                message = 'Desafio aceito. Desafiem os membros do outro clã em Duelos.' if action == 'accept' else 'Desafio recusado.'
            elif action == 'cancel':
                store.cancel_challenge(account['id'], challenge_id, actor_name=account['name'])
                message = 'Desafio cancelado.'
            elif action == 'surrender':
                store.surrender(account['id'], challenge_id, actor_name=account['name'])
                message = 'Seu clã se rendeu. O outro clã ganhou o desafio.'
            else:
                abort(400, description='Ação inválida.')
        except ClanError as error:
            flash(ERRORS.get(error.code, ERRORS['forbidden']), 'error')
            return redirect(back)
        flash(message, 'success')
        return redirect(back)

    # -- JSON API for the in-game clan window (templates/js/clan_overlay.js) --
    def village_level(account):
        from pvp import _main_map
        with village_lock:
            if account['village_id'] not in all_saves_userid():
                return 1
            try:
                _, town = _main_map(village_session(account['village_id']))
                return max(1, int(town.get('level') or 1))
            except Exception:
                return 1

    def member_power(account_id, accounts_by_id):
        from duels import army_profile
        account = accounts_by_id.get(account_id)
        if not account or not account.get('village_id'):
            return 0
        with village_lock:
            if account['village_id'] not in all_saves_userid():
                return 0
            try:
                return army_profile(village_session(account['village_id']))['power']
            except Exception:
                return 0

    def clan_summary(clan, count=None):
        return {'id': clan['id'], 'name': clan['name'], 'tag': clan['tag'], 'description': clan['description'],
                'emblem': clan.get('emblem', 1), 'open': bool(clan.get('recruit_open')),
                'min_level': clan.get('recruit_min_level', 1), 'language': clan.get('recruit_language', 'all'),
                'members': count if count is not None else len(clan.get('members', []))}

    def clan_detail(clan_id, viewer):
        clan = store.clan(clan_id)
        if not clan:
            return None
        rows = {row['id']: row for row in accounts().list_accounts()}
        everyone = {k: v['name'] for k, v in rows.items()}
        mine = next((m for m in clan['members'] if m['account_id'] == viewer['id']), None)
        detail = clan_summary(clan)
        detail.update(
            announcement=clan.get('announcement', ''),
            power=sum(member_power(m['account_id'], rows) for m in clan['members']),
            leader=next((everyone.get(m['account_id'], '?') for m in clan['members'] if m['role'] == 'master'), '?'),
            role=mine['role'] if mine else None,
            members_list=[{'id': m['account_id'], 'name': everyone.get(m['account_id'], '?'), 'role': m['role'],
                           'joined': utc_label(m['joined_at'])} for m in clan['members']],
            assists=sum(m['role'] == 'assist' for m in clan['members']),
        )
        if mine and mine['role'] in ('master', 'assist'):
            detail['requests'] = [{'id': r['id'], 'name': everyone.get(r['account_id'], '?'), 'when': utc_label(r['created_at'])}
                                  for r in store.requests_for(clan_id)]
        current = challenge_view(store.current_challenge(clan_id), clan_id, everyone)
        if current and not mine:
            current = None  # a clan's ongoing challenge is shown to its own members
        detail['challenge'] = public_challenge(current)
        detail['history'] = [public_challenge(item) for item in
                             (challenge_view(row, clan_id, everyone) for row in store.challenge_history(clan_id))] if mine else []
        return detail

    def public_challenge(view):
        if not view:
            return None
        keys = ('id', 'status', 'best_of', 'incoming', 'rival_id', 'rival_tag', 'rival_name', 'our_wins', 'their_wins',
                'needed', 'outcome', 'minutes_left', 'ending', 'when', 'duel_lines')
        return {key: view.get(key) for key in keys}

    def api_state(account):
        membership = store.membership(account['id'])
        own_requests = store.requests_of(account['id'])
        state = {
            'me': {'id': account['id'], 'name': account['name'], 'level': village_level(account),
                   'rejoin_minutes': -(-store.rejoin_wait(account['id']) // 60),
                   'can_create': tutorial_complete(account),
                   'requests': [{'clan_id': r['clan_id'], 'name': r['name'], 'tag': r['tag']} for r in own_requests]},
            'clan': clan_detail(membership['clan_id'], account) if membership else None,
            'ranking': store.ranking(),
            'limits': {'members': MAX_MEMBERS, 'assists': MAX_ASSISTS, 'name': NAME_LENGTH, 'tag': TAG_LENGTH,
                       'description': DESCRIPTION_LENGTH, 'announcement': ANNOUNCEMENT_LENGTH, 'emblems': EMBLEMS,
                       'languages': RECRUIT_LANGUAGES, 'sizes': CHALLENGE_SIZES,
                       'answer_minutes': CHALLENGE_ANSWER_SECONDS // 60},
            'can_challenge': bool(membership and membership['role'] == 'master'
                                  and not store.current_challenge(membership['clan_id'])),
        }
        return state

    def api_player():
        account = current_player()
        if not account:
            abort(403, description='Sua conta não está aprovada.')
        return account

    @app.get('/clans/api/state', endpoint='clan_api_state')
    def clan_api_state():
        return jsonify(api_state(api_player()))

    @app.get('/clans/api/clans', endpoint='clan_api_search')
    def clan_api_search():
        api_player()
        found = store.clans(request.args.get('q', '')[:40])
        return jsonify({'clans': [clan_summary(clan, clan['member_count']) for clan in found[:50]]})

    @app.get('/clans/api/clans/<int:clan_id>', endpoint='clan_api_clan')
    def clan_api_clan(clan_id):
        account = api_player()
        detail = clan_detail(clan_id, account)
        if not detail:
            return jsonify({'ok': False, 'message': _(ERRORS['no_clan'])}), 404
        membership = store.membership(account['id'])
        detail['requested'] = any(r['clan_id'] == clan_id for r in store.requests_of(account['id']))
        detail['can_challenge_this'] = bool(
            membership and membership['role'] == 'master' and membership['clan_id'] != clan_id
            and not store.current_challenge(membership['clan_id']) and not store.current_challenge(clan_id))
        return jsonify(detail)

    @app.post('/clans/api/action', endpoint='clan_api_action')
    def clan_api_action():
        account = api_player()
        validate_csrf()
        form = request.form
        action = form.get('action', '')
        me, name = account['id'], account['name']

        def number(field):
            try:
                return int(form.get(field, ''))
            except ValueError:
                raise ClanError('forbidden') from None

        def create():
            if not tutorial_complete(account):
                raise ClanError('tutorial')
            store.create(me, form.get('name', ''), form.get('tag', ''), form.get('description', ''), actor_name=name,
                         emblem=form.get('emblem', 1))
            return 'Clã criado.'

        def join():
            clan_id = number('clan_id')
            clan = store.clan(clan_id)
            if not clan:
                raise ClanError('no_clan')
            if clan.get('recruit_open'):
                store.join(me, clan_id, village_level(account), actor_name=name)
                return 'Você entrou no clã.'
            store.request_join(me, clan_id, village_level(account))
            return 'Pedido enviado. Um líder do clã vai responder.'

        def challenge():
            target = number('clan_id')
            created = store.challenge(me, target, form.get('best_of'), actor_name=name)
            notify(master_id(target), {
                'type': 'clan_challenge', 'id': created['id'], 'best_of': created['best_of'],
                'clan': {'tag': created['challenger_tag'], 'name': created['challenger_name']},
                'minutes': CHALLENGE_ANSWER_SECONDS // 60, 'url': url_for('clan_page', clan_id=target)})
            return 'Desafio enviado. O outro clã tem 10 minutos para responder.'

        def challenge_answer(accept):
            answered = store.answer_challenge(me, number('challenge_id'), accept, actor_name=name)
            notify(master_id(answered['challenger_clan']), {
                'type': 'clan_challenge_answer', 'id': answered['id'], 'accepted': accept,
                'clan': {'tag': answered['defender_tag'], 'name': answered['defender_name']},
                'url': url_for('clan_page', clan_id=answered['challenger_clan'])})
            return 'Desafio aceito. Desafiem os membros do outro clã em Duelos.' if accept else 'Desafio recusado.'

        def dissolve():
            if form.get('confirm') != 'yes':
                raise ClanError('confirm')
            store.dissolve(me, actor_name=name)
            return 'O clã foi dissolvido.'

        actions = {
            'create': create,
            'join': join,
            'cancel_request': lambda: (store.cancel_request(me, number('clan_id')), 'Pedido cancelado.')[1],
            'accept_request': lambda: (store.answer_request(me, number('request_id'), True, actor_name=name), 'Membro aceito.')[1],
            'reject_request': lambda: (store.answer_request(me, number('request_id'), False, actor_name=name), 'Pedido recusado.')[1],
            'kick': lambda: (store.kick(me, number('target_id'), actor_name=name), 'Membro removido do clã.')[1],
            'make_assist': lambda: (store.set_role(me, number('target_id'), 'assist', actor_name=name), 'Agora é Assist.')[1],
            'remove_assist': lambda: (store.set_role(me, number('target_id'), 'member', actor_name=name), 'Deixou de ser Assist.')[1],
            'transfer': lambda: (store.transfer(me, number('target_id'), actor_name=name), 'Liderança transferida.')[1],
            'leave': lambda: 'O clã foi dissolvido.' if store.leave(me, actor_name=name) == 'dissolved' else 'Você saiu do clã.',
            'settings': lambda: (store.settings(me, form.get('emblem'), form.get('description', ''), form.get('announcement', ''),
                                                form.get('recruit_open'), form.get('min_level'), form.get('language'),
                                                actor_name=name), 'Clã atualizado.')[1],
            'dissolve': dissolve,
            'challenge': challenge,
            'accept_challenge': lambda: challenge_answer(True),
            'decline_challenge': lambda: challenge_answer(False),
            'cancel_challenge': lambda: (store.cancel_challenge(me, number('challenge_id'), actor_name=name), 'Desafio cancelado.')[1],
            'surrender': lambda: (store.surrender(me, number('challenge_id'), actor_name=name),
                                  'Seu clã se rendeu. O outro clã ganhou o desafio.')[1],
        }
        if action not in actions:
            return jsonify({'ok': False, 'message': _('Ação inválida.')}), 400
        try:
            message = actions[action]()
        except ClanError as error:
            return jsonify({'ok': False, 'message': _(ERRORS.get(error.code, ERRORS['forbidden'])), 'state': api_state(account)})
        return jsonify({'ok': True, 'message': _(message), 'state': api_state(account)})

    def require_admin():
        account = g.get('account')
        if not account or not account['is_admin'] or account['status'] != 'approved':
            abort(403, description='Esta página é exclusiva dos administradores.')
        return account

    @app.get('/admin/clans', endpoint='admin_clans')
    def admin_clans():
        require_admin()
        everyone = names()
        clans_list = []
        for clan in store.clans():
            detail = store.clan(clan['id'])
            master = next((m for m in detail['members'] if m['role'] == 'master'), None)
            clans_list.append({**clan, 'master_name': everyone.get(master['account_id'], '?') if master else '?',
                               'created_label': utc_label(clan['created_at'])})
        return render_template('admin_clans.html', clans=clans_list,
                               log=[{**entry, 'created_label': utc_label(entry['created_at']),
                                     'target_name': everyone.get(entry['target_id'], '') if entry['target_id'] else ''}
                                    for entry in store.log(limit=30)])

    @app.post('/admin/clans/<int:clan_id>/dissolve', endpoint='admin_dissolve_clan')
    def admin_dissolve_clan(clan_id):
        admin = require_admin()
        return act(lambda: store.admin_dissolve(clan_id, admin['id'], admin['name'], request.form.get('reason', '')),
                   'O clã foi dissolvido.', url_for('admin_clans'))

    return store
