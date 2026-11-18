"""The global chat's page side (block G, SE_CHAT): the "Msj" button at the left of the game and its window.

The page (templates/js/global_chat.js) reads /chat/api/state (the last messages, whether there is something unread,
whether the player is muted), sends with /chat/api/send and marks what it showed with /chat/api/read. New and
deleted messages reach every open page at once through the live connection the duels opened
(duels.py's hub, SE_DUELS=on; the page receives them as "se-live" events: chat_message, chat_deleted); without it
the page asks again every POLL_SECONDS.

Administrators have /admin/chat: the last messages with a delete button, muting a player (an hour, a day, a week or
for good) and lifting it, and what was done.

Nothing here exists unless SE_CHAT=on: install_chat() is only called then.
"""

from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from auth import validate_csrf
from chat import INTERVAL_SECONDS, LENGTH, MUTE_CHOICES, ChatError, ChatStore
from duels import utc_label
from portal_i18n import translate as _

POLL_SECONDS = 30


def chat_texts():
    return {
        'button': _('Msj'), 'title': _('Chat global'), 'close': _('Fechar'), 'loading': _('Carregando…'),
        'placeholder': _('Escreva uma mensagem…'), 'send': _('Enviar'),
        'empty': _('Ainda não há mensagens. Diga olá!'),
        'unread': _('Mensagens novas no chat global'), 'no_unread': _('Chat global'),
        'you': _('Você'),
        'muted': _('Você foi silenciado no chat até {time}.'), 'muted_forever': _('Você foi silenciado no chat.'),
        'error': _('Não foi possível concluir. Tente novamente.'),
        'errors': {
            'empty': _('Escreva algo antes de enviar.'),
            'too_long': _('A mensagem pode ter até {length} letras.'),
            'too_fast': _('Espere {seconds} segundos entre uma mensagem e outra.'),
            'muted': _('Você foi silenciado no chat até {time}.'),
            'muted_forever': _('Você foi silenciado no chat.'),
        },
    }


def install_chat(app, accounts, data_dir, village_lock, village_session):
    store = ChatStore(data_dir / 'chat.sqlite3')
    app.extensions['chat'] = store

    def current_player():
        account = g.get('account')
        if not account or account['status'] != 'approved' or not account['village_id']:
            return None
        if session.get('USERID') != account['village_id']:
            return None
        return account

    def hub():
        return app.extensions.get('duels')

    def broadcast(message):
        live = hub()
        if live is None:
            return
        for account_id in list(live.connections):
            live.send_to(account_id, message)

    def tag_of(account_id):
        clans = app.extensions.get('clans')
        member = clans.membership(account_id) if clans else None
        return member['clan']['tag'] if member else ''

    def level_of(account):
        try:
            with village_lock:
                town = (village_session(account['village_id']).get('maps') or [{}])[0]
            return int(town.get('level') or 0)
        except Exception:  # an unreadable village never stops a message
            return 0

    def view(row):
        return {'id': row['id'], 'from': row['account_id'], 'name': row['name'], 'tag': row['tag'],
                'level': row['level'], 'text': row['text'], 'at': int(row['created_at'])}

    def error_answer(error):
        texts = chat_texts()['errors']
        values = dict(error.values)
        if 'until' in values:
            values['time'] = utc_label(values['until'])
        # 'until' (seconds) lets the page show the end of a mute in the player's own hour
        return jsonify({'ok': False, 'code': error.code, 'until': int(error.values.get('until') or 0),
                        'message': texts.get(error.code, chat_texts()['error']).format(**values)}), 409

    @app.context_processor
    def chat_context():
        if not current_player():
            return {}
        return {'chat_overlay': {
            'state': url_for('chat_api_state'), 'send': url_for('chat_api_send'), 'read': url_for('chat_api_read'),
            'length': LENGTH, 'interval': INTERVAL_SECONDS, 'poll': POLL_SECONDS, 'texts': chat_texts(),
        }}

    @app.get('/chat/api/state', endpoint='chat_api_state')
    def chat_state():
        account = current_player()
        if not account:
            abort(403)
        muted = store.muted_until(account['id'])
        return jsonify({'me': account['id'], 'messages': [view(row) for row in store.recent()],
                        'unread': store.unread(account['id']),
                        'muted': muted is not None, 'muted_until': int(muted or 0)})  # 0: for good

    @app.post('/chat/api/send', endpoint='chat_api_send')
    def chat_send():
        validate_csrf()
        account = current_player()
        if not account:
            abort(403)
        try:
            row = store.post(account['id'], account['name'], tag_of(account['id']), level_of(account),
                             request.form.get('text', ''))
        except ChatError as error:
            return error_answer(error)
        message = view(row)
        broadcast({'type': 'chat_message', 'message': message})
        return jsonify({'ok': True, 'message': message})

    @app.post('/chat/api/read', endpoint='chat_api_read')
    def chat_read():
        validate_csrf()
        account = current_player()
        if not account:
            abort(403)
        try:
            store.mark_read(account['id'], int(request.form.get('last', 0)))
        except ValueError:
            abort(400)
        return jsonify({'ok': True})

    # ---- administrators
    def require_admin():
        account = g.get('account')
        if not account or not account['is_admin'] or account['status'] != 'approved':
            abort(403, description='Esta página é exclusiva dos administradores.')
        return account

    def names():
        return {row['id']: row['name'] for row in accounts().list_accounts()}

    @app.get('/admin/chat', endpoint='admin_chat')
    def admin_chat():
        require_admin()
        everyone = names()
        messages = [{**row, 'created_label': utc_label(row['created_at'])} for row in reversed(store.recent())]
        mutes = [{**row, 'name': everyone.get(row['account_id'], '?'),
                  'until_label': utc_label(row['until']) if row['until'] else _('Para sempre')} for row in store.mutes()]
        players = sorted(({'id': account_id, 'name': name} for account_id, name in everyone.items()),
                         key=lambda row: row['name'].lower())
        return render_template('admin_chat.html', messages=messages, mutes=mutes, players=players,
                               choices=list(MUTE_CHOICES),
                               log=[{**row, 'created_label': utc_label(row['created_at'])} for row in store.log()])

    @app.post('/admin/chat/<int:message_id>/delete', endpoint='admin_chat_delete')
    def admin_chat_delete(message_id):
        validate_csrf()
        admin = require_admin()
        try:
            store.delete(message_id, admin['name'])
        except ChatError:
            flash(_('Essa mensagem já não existe.'), 'error')
            return redirect(url_for('admin_chat'))
        broadcast({'type': 'chat_deleted', 'id': message_id})
        flash(_('A mensagem foi apagada.'), 'success')
        return redirect(url_for('admin_chat'))

    @app.post('/admin/chat/mute', endpoint='admin_chat_mute')
    def admin_chat_mute():
        validate_csrf()
        admin = require_admin()
        try:
            account_id = int(request.form.get('account', ''))
        except ValueError:
            abort(400)
        target = accounts().get(account_id)
        if not target:
            abort(404)
        try:
            store.mute(account_id, target['name'], request.form.get('time', ''), admin['name'],
                       request.form.get('reason', ''))
        except ChatError:
            abort(400)
        flash(_('{name} foi silenciado no chat.', name=target['name']), 'success')
        return redirect(url_for('admin_chat'))

    @app.post('/admin/chat/<int:account_id>/unmute', endpoint='admin_chat_unmute')
    def admin_chat_unmute(account_id):
        validate_csrf()
        admin = require_admin()
        target = accounts().get(account_id)
        store.unmute(account_id, target['name'] if target else '?', admin['name'])
        flash(_('{name} já pode escrever no chat.', name=target['name'] if target else '?'), 'success')
        return redirect(url_for('admin_chat'))

    return store
