"""Web side of the clans (SE_CLANS=on): pages, actions and the admin section.

Installed by server.py only when SE_CLANS=on; with clans off nothing here is
imported, so no route or template variable exists. Every action is a POST
with the CSRF token, made by an approved, logged-in player whose session
village matches the account; the permission itself is checked again by
ClanStore inside the transaction, so a hand-made request cannot skip it.
"""

from flask import abort, flash, g, redirect, render_template, request, session, url_for

from auth import validate_csrf
from clans import (DESCRIPTION_LENGTH, MAX_ASSISTS, MAX_MEMBERS, MAX_OPEN_REQUESTS, NAME_LENGTH, REJOIN_SECONDS,
                   REQUEST_SECONDS, TAG_LENGTH, ClanError, ClanStore)
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
        return {'clan_limits': {'members': MAX_MEMBERS, 'assists': MAX_ASSISTS, 'requests': MAX_OPEN_REQUESTS,
                                'name': NAME_LENGTH, 'tag': TAG_LENGTH, 'description': DESCRIPTION_LENGTH,
                                'request_days': REQUEST_SECONDS // 86400, 'rejoin_minutes': REJOIN_SECONDS // 60}}

    @app.get('/clans', endpoint='clans_page')
    def clans_page():
        account = player_or_redirect()
        search = request.args.get('q', '')[:40]
        membership = store.membership(account['id'])
        return render_template('clans.html', clans=store.clans(search), search=search, membership=membership,
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
        return render_template('clan.html', clan=clan, role=role, me=account['id'], requests=requests_list,
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
