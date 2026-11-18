print (" [+] Loading basics...")
import os
if __name__ == '__main__':
    _console_env = dict(os.environ)  # before server.env: the update watcher hands this to each new server
    # The switches in server.env (SE_DUELS, SE_PVP...), before any module reads them; console variables win.
    from server_settings import SETTINGS_FILE, describe, load_settings_file
    _settings = load_settings_file()
    print(f" [+] Settings from {SETTINGS_FILE}: {describe(_settings) or 'none (file missing), built-in defaults'}")
    if (os.environ.get('SE_AUTO_UPDATE', 'on').lower() in ('on', '1', 'true', 'yes')
            and not os.environ.get('SE_SERVER_CHILD')):
        # SE_AUTO_UPDATE: this process only watches for new commits and runs the server as a child (updater.py)
        import updater
        raise SystemExit(updater.supervise(_console_env))
import json
import secrets
import threading
import hashlib
import hmac
import sqlite3
import copy
import re
from functools import lru_cache
from io import BytesIO
from datetime import timedelta, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import click
if os.name == 'nt':
    os.system("color")
    os.system("title Social Empires Server")
else:
    import sys
    sys.stdout.write("\x1b]2;Social Empires Server\x07")

print (" [+] Loading game config...")
from get_game_config import get_game_config, patch_game_config
from darts import with_daily_darts

print (" [+] Loading players...")
from get_player_info import get_player_info, get_neighbor_info
from sessions import load_saved_villages, all_saves_userid, save_info, new_village, fb_friends_str, session as village_session
from village_stats import catalog as stats_catalog, summary as stats_summary, village_stats
load_saved_villages()

print (" [+] Loading server...")
from flask import Flask, render_template, send_from_directory, send_file, request, redirect, session, g, abort, flash, url_for, Response
from auth import AccountStore, AccountError, csrf_token, validate_csrf
from command import command
from engine import timestamp_now
from version import version_name
from constants import Constant
from quests import get_quest_map
from localization import LANGUAGE_FLAGS, LANGUAGE_NAMES, PLAYER_LANGUAGES
from portal_i18n import set_portal_language, portal_language, translate as _, translations_for
from swf_localization import localize_swf
from village_commands import fill_map_defaults, grant_missed_level_mana, village_commands_enabled
from seasons import apply_season, seasons_enabled
import world
from sessions import save_session as save_village
from village_names import rename_village, normalize_legacy_village_name, name_default_player, validate_player_name, VillageNameError, MAX_VILLAGE_NAME_LENGTH
from pvp import RaidService, RaidError
from admin_villages import (AdminVillageService, AdminVillageError, AdminVillageConflict, EDITABLE_FIELDS, RESOURCE_LIMIT, CASH_LIMIT,
                            UNITS_PER_CHANGE, giveable_units, mission_state)
from economy import EconomyService, EconomyError
from swf_abc_strings import localize_abc_strings
from swf_range_overlay import add_range_overlay
from swf_private_economy import patch_private_economy
from swf_tutorial import patch_tutorial
from tutorial import TutorialError
from bundle import ASSETS_DIR, STUB_DIR, TEMPLATES_DIR, BASE_DIR

host = os.environ.get('HOST', '127.0.0.1')
port = int(os.environ.get('PORT', '5050'))

app = Flask(__name__, template_folder=TEMPLATES_DIR)


@app.url_value_preprocessor
def reject_huge_ids(endpoint, values):
    """An <int:...> in an address larger than any stored id is a page that does not exist (not a 500)."""
    for value in (values or {}).values():
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2 ** 63 - 1:
            abort(404)
data_dir = Path(os.environ.get('SOCIAL_EMPIRES_DATA_DIR', 'instance')).resolve()
data_dir.mkdir(parents=True, exist_ok=True)


def language_setting(name, default):
    value = os.environ.get(name, default)
    if value not in PLAYER_LANGUAGES:
        raise RuntimeError(f'{name} deve ser um destes idiomas / debe ser uno de estos idiomas: {", ".join(PLAYER_LANGUAGES)}.')
    return value


GAME_LANGUAGE = language_setting('SOCIAL_EMPIRES_LANGUAGE', 'es')
set_portal_language(GAME_LANGUAGE)
app.jinja_env.globals['_'] = _


def _secret_key():
    configured = os.environ.get('SECRET_KEY')
    if configured:
        if len(configured) < 32:
            raise RuntimeError(_('SECRET_KEY deve ter pelo menos 32 caracteres.'))
        return configured
    key_file = data_dir / 'secret_key'
    try:
        descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(secrets.token_hex(32))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass
    saved_key = key_file.read_text(encoding='utf-8').strip()
    if len(saved_key) < 32:
        raise RuntimeError(_('A chave em instance/secret_key está inválida. Restaure o arquivo de backup ou configure SECRET_KEY com pelo menos 32 caracteres.'))
    return saved_key


app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '0') == '1',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
app.extensions['accounts'] = AccountStore(data_dir / 'accounts.sqlite3')
village_lock = threading.RLock()
app.extensions['raids'] = RaidService(data_dir / 'raids.sqlite3')
app.extensions['village_admin'] = AdminVillageService(data_dir / 'administration.sqlite3')


def cash_setting(name, default):
    value = os.environ.get(name, str(default))
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= CASH_LIMIT:
        raise RuntimeError(_('{name} deve ser um inteiro entre 1 e {limit}.', name=name, limit=CASH_LIMIT))
    return int(value)


app.extensions['economy'] = EconomyService(
    data_dir / 'treasury.sqlite3',
    initial_bonus=cash_setting('SOCIAL_EMPIRES_INITIAL_CASH', 500),
    daily_reward=cash_setting('SOCIAL_EMPIRES_DAILY_CASH', 100),
)
with village_lock:
    app.extensions['raids'].recover_pending()
    app.extensions['village_admin'].recover_pending()
    app.extensions['economy'].recover_pending()
STATIC_GAME_PREFIX = '/default01.static.socialpointgames.com/static/socialempires/'
DYNAMIC_GAME_PREFIX = '/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/'
GAME_VERSION = 'SocialEmpires0926bsec.swf'


def accounts():
    return app.extensions['accounts']


def raids():
    return app.extensions['raids']


def village_admin():
    return app.extensions['village_admin']


def economy():
    return app.extensions['economy']


def village_revision(userid):
    return '.'.join(value for value in (
        raids().revision(userid), village_admin().change_revision(userid), economy().revision(userid),
        season_pass_revision(village_session(userid)) if SEASON_PASS_ENABLED else '',
    ) if value)


def game_session_key(userid):
    """Invalidate an open legacy client after administrative edits.

    Form CSRF remains stable. Only a newly rendered game receives the key for
    the current administrative revision, preventing stale absolute XP writes.
    """
    token = session.get('_csrf_token', '')
    if not token:
        return ''
    revision = village_admin().change_revision(userid)
    if not revision:
        return token
    secret = app.secret_key.encode('utf-8') if isinstance(app.secret_key, str) else app.secret_key
    return hmac.new(secret, f'game:{userid}:{token}:{revision}'.encode('utf-8'), hashlib.sha256).hexdigest()


def validate_game_key(userid):
    supplied = request.values.get('user_key', '')
    expected = game_session_key(userid)
    if not expected or not secrets.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
        abort(403, description='Sua vila ou sessão foi atualizada. Recarregue o jogo para continuar.')


def recover_raids():
    """Recover all journals under village_lock before any later save mutation.

    A failed write blocks every subsequent mutation, so only one service can
    have a pending snapshot and recovery order cannot reverse later changes.
    """
    try:
        raids().recover_pending()
        village_admin().recover_pending()
        economy().recover_pending()
    except (OSError, sqlite3.Error, RuntimeError, ValueError, KeyError):
        app.logger.exception('Não foi possível recuperar as alterações da vila.')
        abort(503, description='O servidor está recuperando alterações da vila. Tente novamente em instantes.')


def eligible_village_ids():
    return {account['village_id'] for account in accounts().list_accounts()
            if account['status'] == 'approved' and account['village_id']}


world.set_eligible(lambda: eligible_village_ids())


def raid_tokens():
    return URLSafeTimedSerializer(app.secret_key, salt='socialemperors-raids')


@lru_cache(maxsize=1)
def _game_script_sources():
    """Portuguese strings that game.js passes through its t() helper."""
    script = (Path(TEMPLATES_DIR) / 'js' / 'game.js').read_text(encoding='utf-8')
    return tuple(dict.fromkeys(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', script)))


def game_script_texts():
    return translations_for(_game_script_sources())


@app.template_filter('game_number')
def game_number(value):
    """Whole number with the viewer's thousands separator (1.000 / 1,000 in English)."""
    text = f'{int(value):,}'
    return text if portal_language() == 'en' else text.replace(',', '.')


@app.template_filter('game_decimal')
def game_decimal(value):
    """One decimal place with the viewer's decimal mark (1,5 / 1.5 in English)."""
    text = f'{float(value):.1f}'
    return text if portal_language() == 'en' else text.replace('.', ',')


@app.template_filter('game_datetime')
def game_datetime(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%d/%m/%Y %H:%M UTC')


def ensure_village(account):
    with village_lock:
        recover_raids()
        account = accounts().get(account['id'])
        if not account['village_id']:
            village_id = new_village()
            if EMPIRE_NAME_ENABLED:
                try:  # the new empire is named after its player
                    rename_village(village_id, account['name'])
                except VillageNameError:
                    pass  # an older account whose name is no village name keeps the default one
            account = accounts().bind_village(account['id'], village_id)
        if account['village_id'] not in all_saves_userid():
            abort(503, description='O arquivo da sua vila não foi encontrado. Contate o administrador para restaurar o save.')
        if EMPIRE_NAME_ENABLED:  # the friends bar shows the account's name, not "Emperador"
            name_default_player(account['village_id'], account['name'])
        normalize_legacy_village_name(account['village_id'])
        if village_commands_enabled():  # the level-up mana of levels reached before the server counted it
            village = village_session(account['village_id'])
            counted = 'manaRewardLevel' in village['privateState']
            grant_missed_level_mana(village, get_game_config()['globals'])
            if fill_map_defaults(village) or not counted:  # also the map fields the market reads
                save_village(account['village_id'])
        if world.world_explorer_enabled():  # the explorer's fields the game reads at load (world.py)
            if world.prepare_world(village_session(account['village_id'])):
                save_village(account['village_id'])
        if seasons_enabled():  # a new season gives the islands its weather (seasons.py)
            village = village_session(account['village_id'])
            if apply_season(village):
                save_village(account['village_id'])
        return account


@app.context_processor
def access_context():
    return dict(current_account=getattr(g, 'account', None), csrf_token=csrf_token, version=version_name,
                portal_lang=portal_language(), languages=LANGUAGE_NAMES, language_flags=LANGUAGE_FLAGS)


def chosen_language():
    """The account's language, else one picked in this browser session, else None."""
    account = g.get('account')
    if account and account.get('language') in PLAYER_LANGUAGES:
        return account['language']
    language = session.get('language')
    return language if language in PLAYER_LANGUAGES else None


def game_language():
    """Language for this request's game data: the player's choice or the server default."""
    return g.get('language') or GAME_LANGUAGE


@app.before_request
def protect_access():
    g.account = accounts().get(session.get('account_id'))
    chosen = chosen_language()
    g.language = chosen or GAME_LANGUAGE
    g.portal_language = chosen  # None keeps the server's portal language.
    protected = request.path in ('/play.html', '/ruffle.html', '/new.html', '/null', '/village', '/village/events', '/rivals', '/treasury', '/treasury/claim') or request.path.startswith((STATIC_GAME_PREFIX, DYNAMIC_GAME_PREFIX, '/rivals/'))
    if not protected:
        return
    is_api = request.path.startswith((STATIC_GAME_PREFIX, DYNAMIC_GAME_PREFIX))
    if not g.account:
        if is_api:
            return {'error': _('Faça login para acessar o jogo.')}, 401
        return redirect(url_for('login'))
    if g.account['status'] != 'approved':
        if is_api:
            return {'error': _('Sua conta não está aprovada.')}, 403
        session.clear()
        flash('Sua conta precisa da aprovação de um administrador para jogar.', 'info')
        return redirect(url_for('login'))
    village_id = g.account['village_id']
    if not village_id or session.get('USERID') != village_id:
        abort(403, description='A vila desta sessão não pertence à sua conta. Entre novamente.')
    # FlashVars identify the player, but only the authenticated session authorizes it.
    if request.path.startswith(DYNAMIC_GAME_PREFIX):
        for field in ('USERID', 'user_id'):
            if field in request.values and request.values[field] != village_id:
                abort(403, description='Você só pode acessar sua própria vila.')
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if request.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlsplit(origin).netloc != request.host):
                abort(403, description='Origem da solicitação inválida.')
        if request.path.rsplit('/', 1)[-1] in ('get_game_config.php', 'get_player_info.php', 'command.php', 'sync_error_track.php', 'get_continent_ranking.php'):
            validate_game_key(village_id)


@app.after_request
def response_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    if request.endpoint not in ('images', 'css', 'javascript', 'ruffle_assets', 'static_assets_loader'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
@app.errorhandler(503)
def access_error(error):
    message = error.description
    if message == type(error).description:
        # Werkzeug's built-in English text: show our own translated message instead.
        message = DEFAULT_ERROR_MESSAGES.get(error.code, message)
    if request.path.startswith(DYNAMIC_GAME_PREFIX):
        return {'error': _(message)}, error.code
    return render_template('error.html', status_code=error.code, message=_(message)), error.code


DEFAULT_ERROR_MESSAGES = {
    400: 'A solicitação não pôde ser processada. Atualize a página e tente novamente.',
    403: 'Você não tem permissão para acessar esta página.',
    404: 'Esta página não existe. Confira o endereço ou volte ao início.',
    413: 'O envio é grande demais.',
    503: 'O servidor está indisponível no momento. Tente novamente em instantes.',
}

print (" [+] Configuring server routes...")

##########
# ROUTES #
##########

## PAGES AND RESOURCES

@app.route("/login", methods=['GET', 'POST'])
@app.route("/", methods=['GET', 'POST'])
def login():
    if g.account and g.account['status'] == 'approved' and request.method == 'GET':
        return redirect(url_for('play'))
    error = block_reason = None
    values = {'email': request.form.get('email', '').strip()}
    if request.method == 'POST':
        validate_csrf()
        email = values['email']
        address = request.remote_addr or 'unknown'
        picked = session.get('language') if session.get('language') in PLAYER_LANGUAGES else None
        try:
            accounts().check_login_allowed(email, address)
            account = accounts().authenticate(email, request.form.get('password', ''))
            if not account:
                accounts().record_login_failure(email, address)
                error = 'E-mail ou senha incorretos.'
            elif account['status'] == 'pending':
                error = 'Seu cadastro está aguardando aprovação do administrador. Tente entrar novamente após a liberação.'
            elif account['status'] != 'approved':
                error = 'Sua conta está bloqueada. Entre em contato com o administrador.'
                block_reason = account.get('block_reason')
            else:
                account = ensure_village(account)
                accounts().clear_login_failures(email, address)
                if picked and account.get('language') != picked:
                    # A language chosen on the login page is saved in the account.
                    account = accounts().set_language(account['id'], picked)
                session.clear()
                session.permanent = True
                session['account_id'] = account['id']
                session['USERID'] = account['village_id']
                session['GAMEVERSION'] = GAME_VERSION
                csrf_token()
                return redirect(url_for('play'))
        except AccountError as exc:
            error = str(exc)
    return render_template('login.html', error=error, block_reason=block_reason, values=values)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    values = {key: request.form.get(key, '').strip() for key in ('name', 'email')}
    if request.method == 'POST':
        validate_csrf()
        try:
            password = request.form.get('password', '')
            if password != request.form.get('password_confirm', ''):
                raise AccountError('As senhas não conferem.')
            if EMPIRE_NAME_ENABLED:
                try:
                    values['name'] = validate_player_name(values['name'])
                except VillageNameError as exc:
                    raise AccountError(str(exc)) from exc
            language = session.get('language') if session.get('language') in PLAYER_LANGUAGES else None
            accounts().create_account(values['name'], values['email'], password, language=language,
                                      status='approved' if AUTO_APPROVE else 'pending')
            if EMPIRE_NAME_ENABLED:
                # Whoever was signed in in this browser (an administrator, say) is signed out: the next
                # login is the new account's, not the previous session's.
                session.clear()
                if language:
                    session['language'] = language
            if AUTO_APPROVE:
                flash('Conta criada! Já pode entrar na sua vila.', 'success')
            else:
                flash('Cadastro recebido! Aguarde a aprovação do administrador para entrar na sua vila.', 'success')
            return redirect(url_for('login'))
        except AccountError as exc:
            error = str(exc)
    return render_template('register.html', error=error, values=values)


@app.post('/language')
def change_language():
    """Switch the portal and game language; saved in the account when logged in."""
    validate_csrf()
    language = request.form.get('language', '')
    if language not in PLAYER_LANGUAGES:
        abort(400, description='O idioma escolhido não é válido.')
    session['language'] = language
    if g.account:
        accounts().set_language(g.account['id'], language)
    destination = request.form.get('next', '')
    # Only local paths: never redirect to another site.
    if not destination.startswith('/') or destination.startswith('//') or '\\' in destination:
        destination = url_for('play') if g.account else url_for('login')
    return redirect(destination)


@app.post('/logout')
def logout():
    validate_csrf()
    session.clear()
    return redirect(url_for('login'))


def require_admin():
    if not g.account or not g.account['is_admin'] or g.account['status'] != 'approved':
        abort(403, description='Esta página é exclusiva dos administradores.')


@app.get('/admin')
def admin_accounts():
    require_admin()
    all_accounts = accounts().list_accounts()
    # With automatic approval nobody waits: the page opens on every account unless some are pending.
    default_filter = 'pending' if any(account['status'] == 'pending' for account in all_accounts) else 'all'
    selected_filter = request.args.get('status', default_filter)
    if selected_filter not in ('all', 'pending', 'approved', 'rejected'):
        abort(400, description='Filtro de contas inválido.')
    return render_template('admin.html', accounts=[account for account in all_accounts if selected_filter == 'all' or account['status'] == selected_filter], pending_count=sum(account['status'] == 'pending' for account in all_accounts), selected_filter=selected_filter)


@app.get('/admin/')
@app.get('/admin/accounts')
@app.get('/admin/accounts/<int:account_id>')
def admin_accounts_alias(account_id=None):
    """Addresses people type or reload (e.g. after approving) lead to the accounts page."""
    require_admin()
    return redirect(url_for('admin_accounts'))


@app.post('/admin/accounts/<int:account_id>')
def update_account(account_id):
    require_admin()
    validate_csrf()
    action = request.form.get('action')
    status = {'approve': 'approved', 'unblock': 'approved', 'reject': 'rejected', 'block': 'rejected'}.get(action)
    if not status:
        abort(400, description='Ação inválida.')
    # Blocking a player needs a reason (the player reads it when logging in); refusing a registration does not.
    reason = request.form.get('reason', '') if action == 'block' else (request.form.get('reason') or None)
    account = accounts().get(account_id)
    if not account:
        abort(404, description='Conta não encontrada.')
    try:
        if status == 'approved':
            ensure_village(account)
        accounts().set_status(account_id, status, reason)
        flash({'block': 'Conta bloqueada.', 'unblock': 'Conta desbloqueada.'}.get(action, 'Acesso da conta atualizado.'), 'success')
    except AccountError as exc:
        flash(str(exc), 'error')
    chosen = request.form.get('status')
    return redirect(url_for('admin_accounts', status=chosen) if chosen in ('pending', 'approved', 'rejected', 'all') else url_for('admin_accounts'))


@app.get('/admin/villages')
def admin_villages():
    require_admin()
    entries = []
    with village_lock:
        recover_raids()
        saved_ids = set(all_saves_userid())
        for account in accounts().list_accounts():
            userid = account['village_id']
            if not userid:
                continue
            if userid not in saved_ids:
                entries.append({'account': account, 'unavailable': True})
                continue
            village = village_admin().get(userid)
            entries.append({'account': account, 'village': village, 'stats': village_stats(village_session(userid), game_language()),
                            'resources': village['resources'], 'cash': village['cash'], 'unavailable': False})
    overview = stats_summary([entry['stats'] for entry in entries if not entry['unavailable']])
    return render_template('admin_villages.html', villages=entries, overview=overview)


MISSION_STATE_LABELS = {'open': 'Pendente', 'completed': 'Concluída (recompensa a receber)', 'rewarded': 'Concluída e recebida'}


def administrative_history(userid):
    administrators = {account['id']: account['name'] for account in accounts().list_accounts()}
    items, missions = stats_catalog(game_language())
    labels = {'name': _('Nome'), 'coins': _('Ouro'), 'wood': _('Madeira'), 'food': _('Comida'),
              'stone': _('Pedra'), 'cash': _('Dinheiro'), 'level': _('Nível'), 'xp': _('Experiência'),
              'tutorial_complete': _('Tutorial')}
    history = []
    for entry in village_admin().history(userid):
        changes = []
        for field in entry['changed_fields']:
            if field == 'units':  # units given or removed: the unit's total before and after
                unit = items.get(entry['after']['unit'], {})
                changes.append({'label': _('Unidades: {name}', name=unit.get('name') or entry['after']['unit']),
                                'before': game_number(entry['before']['total']), 'after': game_number(entry['after']['total'])})
                continue
            if field == 'mission':
                title = missions.get(entry['after']['mission'], str(entry['after']['mission']))
                changes.append({'label': _('Missão: {name}', name=title),
                                'before': _(MISSION_STATE_LABELS[entry['before']['state']]),
                                'after': _(MISSION_STATE_LABELS[entry['after']['state']])})
                continue
            values = []
            for snapshot in (entry['before'], entry['after']):
                value = snapshot['resources'][field] if field in ('coins', 'wood', 'food', 'stone') else snapshot[field]
                if field == 'tutorial_complete':
                    value = _('Concluído') if value else _('Em andamento')
                elif field != 'name':
                    value = game_number(value)
                values.append(value)
            changes.append({'label': labels[field], 'before': values[0], 'after': values[1]})
        history.append({**entry, 'admin_name': administrators.get(entry['admin_account_id'], _('Administrador')),
                        'created_label': game_datetime(entry['created_at']), 'changes': changes})
    return history


@app.route('/admin/villages/<int:account_id>', methods=['GET', 'POST'])
def admin_village(account_id):
    require_admin()
    if request.method == 'POST':
        validate_csrf()
    account = accounts().get(account_id)
    if not account or not account['village_id']:
        abort(404, description='Esta conta ainda não possui uma vila vinculada.')
    error, conflict, response_status = None, False, 200
    with village_lock:
        recover_raids()
        if account['village_id'] not in all_saves_userid():
            abort(503, description='O save desta vila não foi encontrado. Restaure o arquivo de backup antes de editar.')
        village = village_admin().get(account['village_id'])
        values = {'name': village['name'], **village['resources'], 'cash': village['cash'],
                  'level': village['level'], 'tutorial_complete': int(village['tutorial_complete']), 'reason': ''}
        expected_revision = village['revision']
        if request.method == 'POST':
            values = {field: request.form.get(field, '') for field in EDITABLE_FIELDS}
            values['reason'] = request.form.get('reason', '')
            expected_revision = request.form.get('expected_revision', '')
            try:
                result = village_admin().update(
                    account['village_id'], {key: value for key, value in values.items() if key != 'reason'},
                    g.account['id'], expected_revision, values['reason'],
                )
            except AdminVillageConflict as exc:
                error, conflict, response_status = str(exc), True, 409
            except AdminVillageError as exc:
                error, response_status = str(exc), 400
            except (OSError, sqlite3.Error):
                app.logger.exception('A alteração administrativa aguarda recuperação.')
                abort(503, description='Não foi possível concluir a alteração agora. Atualize a página para recuperar a gravação antes de tentar novamente.')
            else:
                flash('Vila atualizada. O jogador verá um aviso para recarregar o jogo.' if result['changed_fields'] else 'A vila já estava com esses valores.', 'success')
                return redirect(url_for('admin_village', account_id=account_id), code=303)
        history = administrative_history(account['village_id'])
        save = village_session(account['village_id'])
        stats = village_stats(save, game_language())
        items, mission_names = stats_catalog(game_language())
        unit_choices = sorted(({'id': unit_id, 'name': items[unit_id].get('name') or str(unit_id)} for unit_id in giveable_units()),
                              key=lambda unit: (unit['name'].casefold(), unit['id']))
        mission_choices = [{'id': mission_id, 'name': name, 'state': mission_state(save, mission_id)}
                           for mission_id, name in mission_names.items()]
    return render_template('admin_village.html', account=account, village=village, values=values, stats=stats,
                           error=error, conflict=conflict, expected_revision=expected_revision, history=history,
                           unit_choices=unit_choices, mission_choices=mission_choices, units_per_change=UNITS_PER_CHANGE,
                           mission_state_labels=MISSION_STATE_LABELS,
                           limits={'resource_max': RESOURCE_LIMIT, 'cash_max': CASH_LIMIT,
                                   'name_max_length': MAX_VILLAGE_NAME_LENGTH, 'max_level': village['max_level']}), response_status


def administrative_change(account_id, change):
    """Run one unit or mission change for the account's village and go back to its page."""
    require_admin()
    validate_csrf()
    account = accounts().get(account_id)
    if not account or not account['village_id']:
        abort(404, description='Esta conta ainda não possui uma vila vinculada.')
    with village_lock:
        recover_raids()
        if account['village_id'] not in all_saves_userid():
            abort(503, description='O save desta vila não foi encontrado. Restaure o arquivo de backup antes de editar.')
        try:
            change(account['village_id'])
        except AdminVillageError as exc:
            flash(str(exc), 'error')
        except (OSError, sqlite3.Error):
            app.logger.exception('A alteração administrativa aguarda recuperação.')
            abort(503, description='Não foi possível concluir a alteração agora. Atualize a página para recuperar a gravação antes de tentar novamente.')
        else:
            flash('Vila atualizada. O jogador verá um aviso para recarregar o jogo.', 'success')
    return redirect(url_for('admin_village', account_id=account_id) + request.form.get('anchor', ''), code=303)


@app.post('/admin/villages/<int:account_id>/units')
def admin_village_units(account_id):
    return administrative_change(account_id, lambda userid: village_admin().change_units(
        userid, request.form.get('unit_id', ''), request.form.get('count', ''), request.form.get('action', ''),
        g.account['id'], request.form.get('reason', '')))


@app.post('/admin/villages/<int:account_id>/missions')
def admin_village_missions(account_id):
    return administrative_change(account_id, lambda userid: village_admin().change_mission(
        userid, request.form.get('mission_id', ''), request.form.get('action', ''), g.account['id'],
        request.form.get('reason', '')))


@app.get('/treasury')
def treasury():
    with village_lock:
        recover_raids()
        try:
            overview = economy().overview(session['USERID'])
        except EconomyError as exc:
            abort(400, description=str(exc))
    return render_template('treasury.html', overview=overview)


@app.post('/treasury/claim')
def claim_treasury():
    validate_csrf()
    with village_lock:
        recover_raids()
        try:
            reward = economy().claim(session['USERID'], request.form.get('action', ''))
        except EconomyError as exc:
            flash(str(exc), 'error')
        except (OSError, sqlite3.Error):
            app.logger.exception('O resgate gratuito aguarda recuperação.')
            abort(503, description='Não foi possível concluir o resgate agora. Atualize a página para recuperar a gravação antes de tentar novamente.')
        else:
            flash(_('Você recebeu {amount} de dinheiro gratuito. Reabra a vila para usar o saldo.', amount=game_number(reward['amount'])), 'success')
    return redirect(url_for('treasury'), code=303)


@app.route("/play.html")
def play():
    ensure_village(g.account)
    USERID = session['USERID']
    with village_lock:
        recover_raids()
        server_time = timestamp_now()
        last_login = village_session(USERID)['playerInfo'].get('last_logged_in', -1)
        if not isinstance(last_login, int) or last_login < 0:
            last_login = server_time
        daily_next = None
        if HUD_ENABLED:  # the HUD's "Daily bonus" chest counts down to the treasury's next daily reward
            try:
                daily_next = economy().overview(USERID)['next_claim_at']
            except Exception:
                app.logger.exception('The daily bonus chest could not read the treasury.')
        return render_template("play.html", script_texts=game_script_texts(), daily_next=daily_next, save_info=save_info(USERID), serverTime=server_time, last_logged_in=last_login, friendsInfo=fb_friends_str(USERID), version=version_name, GAMEVERSION=GAME_VERSION, raid_revision=village_revision(USERID), game_user_key=game_session_key(USERID),
                               webgl_renderer=RUFFLE_SETTINGS['renderer'] == 'webgl', ruffle_settings=RUFFLE_SETTINGS,
                               push_time=QUICK_SAVE_SECONDS if QUICK_SAVE_ENABLED else None, sound_hint=SOUND_FIX_ENABLED,
                               day_night=DAY_NIGHT_ENABLED, hud_clock=HUD_ENABLED and DAY_NIGHT_ENABLED, hud_bar=HUD_ENABLED, full_view=VIEW_ENABLED, perf_mode=PERF_MODE_ENABLED,
                               update_notice=UPDATE_NOTICE_ENABLED, server_build=SERVER_BUILD)


@app.route('/village', methods=['GET', 'POST'])
def village_settings():
    error = None
    with village_lock:
        recover_raids()
        normalize_legacy_village_name(session['USERID'])
        info = save_info(session['USERID'])
        name = request.form.get('village_name', info['name'])
        if request.method == 'POST':
            validate_csrf()
            try:
                rename_village(session['USERID'], name)
            except VillageNameError as exc:
                error = str(exc)
            except OSError:
                abort(503, description='Não foi possível salvar o nome da vila. Tente novamente.')
            else:
                flash('Nome da vila atualizado.', 'success')
                return redirect(url_for('village_settings'), code=303)
    return render_template('village.html', village=info, village_name=name, error=error, name_max_length=MAX_VILLAGE_NAME_LENGTH), 400 if error else 200


@app.get('/version')
def server_version():
    """The running server's build (public: the page asks it to know when the server was updated)."""
    response = Response(json.dumps({'build': SERVER_BUILD}), mimetype='application/json')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/village/events')
def village_events():
    with village_lock:
        recover_raids()
        return {'revision': village_revision(session['USERID'])}


@app.get('/rivals')
def rival_villages():
    with village_lock:
        recover_raids()
        try:
            overview = raids().overview(session['USERID'], eligible_village_ids())
        except RaidError as exc:
            abort(400, description=str(exc))
        for rival in overview['rivals']:
            rival['raid_token'] = raid_tokens().dumps({
                'attacker': session['USERID'], 'defender': rival['userid'],
                'nonce': secrets.token_hex(16),
            })
        last_battle = next((entry for entry in overview['history']
                            if entry['id'] == request.args.get('battle') and entry['role'] == 'attacker'), None)
    return render_template('rivals.html', **overview, last_battle=last_battle, server_now=timestamp_now())


@app.post('/rivals/<defender_id>/raid')
def raid_village(defender_id):
    validate_csrf()
    try:
        token = raid_tokens().loads(request.form.get('raid_token', ''), max_age=3600)
    except (BadSignature, SignatureExpired):
        abort(400, description='A solicitação de ataque expirou ou é inválida. Volte à lista de rivais e tente novamente.')
    if not isinstance(token, dict) or token.get('attacker') != session['USERID'] or token.get('defender') != defender_id:
        abort(403, description='A solicitação de ataque não pertence à sua vila ou a este rival.')
    with village_lock:
        recover_raids()
        try:
            result = raids().raid(session['USERID'], defender_id, eligible_village_ids(), token.get('nonce'))
        except RaidError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('rival_villages'), code=303)
        except (OSError, sqlite3.Error):
            app.logger.exception('A transferência do saque aguarda recuperação.')
            abort(503, description='Não foi possível finalizar o saque agora. A transferência será recuperada antes da próxima ação; atualize a página em instantes.')
        record_raid_for_season_pass(result)
    return redirect(url_for('rival_villages', battle=result['id']), code=303)

def record_raid_for_season_pass(result):
    """A raid won counts for the attacker's season pass (SE_SEASON_PASS; once per raid)."""
    season = app.extensions.get('season_pass')
    if season and isinstance(result, dict) and result.get('won'):
        season['record_for'](result.get('attacker_id') or session['USERID'], 'raid_win', once=result.get('id'))


@app.route("/ruffle.html")
def ruffle():
    return redirect(url_for('play'))


@app.route("/new.html")
def new():
    return redirect(url_for('play'))

@app.route("/crossdomain.xml")
def crossdomain():
    return send_from_directory(STUB_DIR, "crossdomain.xml")

@app.route("/img/<path:path>")
def images(path):
    return send_from_directory(TEMPLATES_DIR + "/img", path)

@app.route("/css/<path:path>")
def css(path):
    return send_from_directory(TEMPLATES_DIR + "/css", path)


@app.get('/js/<path:path>')
def javascript(path):
    return send_from_directory(TEMPLATES_DIR + '/js', path)


@app.get('/vendor/ruffle/<path:path>')
def ruffle_assets(path):
    return send_from_directory(TEMPLATES_DIR + '/vendor/ruffle', path)

## GAME STATIC


@app.route("/default01.static.socialpointgames.com/static/socialempires/swf/05122012_projectiles.swf")
def similar_05122012_projectiles():
    return send_from_directory(ASSETS_DIR + "/swf", "20130417_projectiles.swf")

@app.route("/default01.static.socialpointgames.com/static/socialempires/swf/05122012_magicParticles.swf")
def similar_05122012_magicParticles():
    return send_from_directory(ASSETS_DIR + "/swf", "20131010_magicParticles.swf")

@app.route("/default01.static.socialpointgames.com/static/socialempires/swf/05122012_dynamic.swf")
def similar_05122012_dynamic():
    return send_from_directory(ASSETS_DIR + "/swf", "120608_dynamic.swf")

@app.route("/default01.static.socialpointgames.com/static/socialempires/fx/p.miniFireball2.swf")
def similar_mini_fireball():
    # The game's P_MINI_FIREBALL projectile; the file is not among the bundled assets (it answered 404).
    return send_from_directory(ASSETS_DIR + "/fx", "p.fireBall_02.swf")

@app.route("/default01.static.socialpointgames.com/static/socialempires/<path:path>")
def static_assets_loader(path):
    if path == f'flash/{GAME_VERSION}':
        movie, checksum = localized_game_movie(game_language())
        response = send_file(BytesIO(movie), mimetype='application/x-shockwave-flash', download_name=GAME_VERSION, etag=checksum, conditional=True)
        # One URL, one movie per language: always revalidate (the ETag differs per language).
        response.headers['Cache-Control'] = 'private, no-cache'
        response.headers['Vary'] = 'Cookie'
        return response
    if HD_SPRITES_ENABLED and path.startswith('buildingsprites/') and hd_sprite_allowed(path):
        # SE_HD_SPRITES: the HD version of a building's picture when it was made (tools/make_hd_sprites.py)
        hd_folder = Path(ASSETS_DIR).resolve().parent / 'assets_hd'
        if (hd_folder / path).is_file():
            return send_from_directory(hd_folder, path)
    return send_from_directory(ASSETS_DIR, path)


@lru_cache(maxsize=1)
def hd_resource_sprites():
    from swf_hd_icons import resource_sprite_names
    return frozenset(name.lower() for name in resource_sprite_names(get_game_config()['items']))


def hd_sprite_allowed(path):
    """SE_HD_SPRITES=recursos: only the map's resources; on / todo: every sprite that has its HD version."""
    if HD_SPRITES_MODE != 'recursos':
        return True
    return Path(path).stem.lower() in hd_resource_sprites()


@lru_cache(maxsize=None)
def localized_game_movie(language=None):
    language = language or GAME_LANGUAGE
    original = (Path(ASSETS_DIR) / 'flash' / GAME_VERSION).read_bytes()
    patched = patch_tutorial(patch_private_economy(localize_swf(original, language=language)))
    # Bytecode strings change last: the audited patches above pin the ABC checksum.
    translated = add_range_overlay(localize_abc_strings(patched, language), all_in_tournament=DUELS_ENABLED)
    if SOUND_FIX_ENABLED:  # the game's music and sound buttons keep their choice after a reload
        from swf_sound_settings import fix_sound_settings
        translated = fix_sound_settings(translated)
    if DAY_NIGHT_ENABLED:  # the page tints the map by the hour (day and night)
        from swf_daylight import add_daylight
        translated = add_daylight(translated)
    if HUD_ENABLED:  # the page reads the player's numbers and draws its own resource bar (swf_hud.py)
        from swf_hud import add_hud
        translated = add_hud(translated)
    if VIEW_ENABLED:  # the game fills the browser window and the page zooms the map smoothly (swf_view.py)
        from swf_view import add_view
        translated = add_view(translated)
    if FAST_HOVER_ENABLED:  # the pointer over a building no longer redraws it on every move (swf_fast_hover.py)
        from swf_fast_hover import add_fast_hover
        translated = add_fast_hover(translated)
    if SMART_AI_ENABLED:  # smarter targets, help in groups, the wounded fall back (swf_smart_ai.py)
        from swf_smart_ai import add_smart_ai
        translated = add_smart_ai(translated)
    if QUEST_TEAMS_ENABLED or COOP_ENABLED:  # every adventure island opens "Elige tu equipo" (swf_coop.py)
        from swf_coop import add_quest_teams
        translated = add_quest_teams(translated)
    if COOP_ENABLED:  # Solitario or Clan before an adventure; the clan raid's team (swf_coop.py, COOP_PLAN.md)
        from swf_coop import add_coop
        translated = add_coop(translated)
    if PERF_MODE_ENABLED:  # the player may stop the buildings' animations from the menu (swf_perf_mode.py)
        from swf_perf_mode import add_perf_mode
        translated = add_perf_mode(translated)
    if READABLE_UI_ENABLED:  # white lettering with a black outline; no "x0" units in the team window
        from swf_readable_text import make_text_readable
        translated = make_text_readable(translated)
    if DUELS_ENABLED:  # lets the duel page open the tournament arena
        from swf_duel_bridge import add_duel_bridge
        translated = add_duel_bridge(translated)
    if ABILITIES_ENABLED:  # automatic unit abilities, one summon at most and ability tooltips
        from localization import normalize_locale as ability_locale
        from swf_unit_abilities import add_unit_abilities
        translated = add_unit_abilities(translated, language=ability_locale(language),
                                        debug=os.environ.get('SE_ABILITIES_DEBUG', '').lower() in ('on', '1', 'true', 'yes'))
    if CLANS_ENABLED:  # the "Clan" button in the game's icon panel, once inside the empire
        from portal_i18n import normalize_locale
        from swf_clan_button import add_clan_button
        locale = normalize_locale(language)

        def art(prefix):
            name = f'{prefix}_{locale}.png'
            return '/img/' + (name if (Path(TEMPLATES_DIR) / 'img' / name).exists() else f'{prefix}_es.png')
        translated = add_clan_button(translated, image_url=art('clan_button'))
    if PVP_ENABLED:  # the "PvP" button (below "Clan") and the game's team selection for raids and duels
        from portal_i18n import normalize_locale as pvp_locale
        from swf_pvp import add_pvp
        name = f'pvp_button_{pvp_locale(language)}.png'
        translated = add_pvp(translated, image_url='/img/' + (name if (Path(TEMPLATES_DIR) / 'img' / name).exists()
                                                              else 'pvp_button_es.png'))
    if SEASON_PASS_ENABLED:  # the "Pase" button in the game's icon panel (below "PvP")
        from portal_i18n import normalize_locale as pass_locale
        from swf_season_pass import add_season_pass_button
        name = f'season_pass_button_{pass_locale(language)}.png'
        translated = add_season_pass_button(translated, image_url='/img/' + (
            name if (Path(TEMPLATES_DIR) / 'img' / name).exists() else 'season_pass_button_es.png'))
    from swf_hd_icons import apply_hd_icons, hd_icons_enabled
    if hd_icons_enabled():  # the game's icons at twice their pixels (pictures and shape fills only, never code)
        translated = apply_hd_icons(translated, language)
    return translated, hashlib.sha256(translated).hexdigest()

## GAME DYNAMIC

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/track_game_status.php", methods=['POST'])
def track_game_status_response():
    status = request.values['status']
    installId = request.values['installId']
    user_id = request.values['user_id']

    app.logger.info('Client status for player %s: %s', user_id, status[:100])
    if os.environ.get('SE_ABILITIES_DEBUG', '').lower() in ('on', '1', 'true', 'yes'):  # see what the game reports while testing
        print(f' [client status] {user_id}: {status[:300]}')
    return ("", 200)

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/get_game_config.php", methods=['GET','POST'])
def get_game_config_response():
    spdebug = None

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    language = request.values['language']

    return with_daily_darts(get_game_config(game_language()))

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/get_player_info.php", methods=['POST'])
def get_player_info_response():

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    spdebug = request.values['spdebug'] if 'spdebug' in request.values else None
    language = request.values['language']
    neighbors = request.values['neighbors'] if 'neighbors' in request.values else None
    client_id = request.values['client_id']
    user = request.values['user'] if 'user' in request.values else None
    map = request.values.get('map')
    map = int(map) if map not in (None, '', 'null', 'undefined') else None  # an explorer rival without 'map'

    with village_lock:
        recover_raids()
        validate_game_key(USERID)
        # Copy before releasing the lock: JSON serialization must see one state.
        if user is None:
            return (copy.deepcopy(get_player_info(USERID)), 200)
        elif user in (Constant.NEIGHBOUR_ARTHUR_GUINEVERE_1, Constant.NEIGHBOUR_ARTHUR_GUINEVERE_2, Constant.NEIGHBOUR_ARTHUR_GUINEVERE_3):
            return (copy.deepcopy(get_neighbor_info(user, map if map is not None else 0)), 200)
        elif user.startswith("100000"):
            return get_quest_map(user, game_language())
        else:
            from sessions import neighbor_session
            if neighbor_session(user) is None:
                abort(404, description='Vila não encontrada.')
            return (copy.deepcopy(get_neighbor_info(user, map if map is not None else 0)), 200)

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/sync_error_track.php", methods=['POST'])
def sync_error_track_response():
    spdebug = None

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    language = request.values['language']
    error = request.values['error']
    current_failed = request.values['current_failed']
    tries = request.values['tries'] if 'tries' in request.values else None
    survival = request.values['survival']
    previous_failed = request.values['previous_failed']
    description = request.values['description']
    user_id = request.values['user_id']

    app.logger.info('Client sync error for player %s', USERID)
    return ("", 200)

@app.route("/null")
def flash_sync_error_response():
    return redirect("/play.html")

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/command.php", methods=['POST'])
def command_response():
    spdebug = None

    USERID = request.values['USERID']
    user_key = request.values['user_key']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    language = request.values['language']
    client_id = request.values['client_id']

    data_str = request.values['data']
    if len(data_str) < 66 or data_str[64] != ';':
        abort(400, description='Pacote de comandos inválido.')
    try:
        data = json.loads(data_str[65:])
    except (ValueError, TypeError):
        abort(400, description='Pacote de comandos inválido.')
    if not isinstance(data, dict) or not isinstance(data.get('commands'), list) or not all(key in data for key in ('ts', 'first_number', 'accessToken', 'tries', 'publishActions')):
        abort(400, description='Pacote de comandos inválido.')
    if not all(isinstance(item, dict) and isinstance(item.get('cmd'), str) and isinstance(item.get('args'), list) for item in data['commands']):
        abort(400, description='Pacote de comandos inválido.')

    duel_filter = app.extensions.get('duel_command_filter')  # SE_DUELS=on: arena commands never reach the village
    if duel_filter is not None:
        data['commands'] = duel_filter(USERID, data['commands'])
    coop_filter = app.extensions.get('coop_command_filter')  # SE_COOP=on: a clan raid's deaths never leave the host's village
    if coop_filter is not None:
        data['commands'] = coop_filter(USERID, data['commands'])
    with village_lock:
        recover_raids()
        validate_game_key(USERID)
        try:
            command(USERID, data)
        except (VillageNameError, TutorialError) as exc:
            abort(400, description=str(exc))
    
    return ({"result": "success"}, 200)

@app.route("/dynamic.flash1.dev.socialpoint.es/appsfb/socialempiresdev/srvempires/get_continent_ranking.php")
def get_continent_ranking_response():

    USERID = request.values['USERID']
    worldChange = request.values['worldChange']
    if 'spdebug' in request.values:
        spdebug = request.values['spdebug']
    town_id = request.values['map']
    user_key = request.values['user_key']

    if world.world_explorer_enabled():
        with village_lock:
            validate_game_key(USERID)
            response = world.continent(USERID, request.values.get('level_id'), request.values.get('relocate') == '1')
            save_village(USERID)
        return response
    # SE_WORLD_EXPLORER=off: the earlier fixed continent
    response = {
        "world_id": 0,
        "continent": [
            {"posicion": 0, "nivel": 1, "user_id": 1111}, # villages/AcidCaos
            {"posicion": 1, "nivel": 0},
            {"posicion": 2, "nivel": 0},
            {"posicion": 3, "nivel": 0},
            {"posicion": 4, "nivel": 0},
            {"posicion": 5, "nivel": 0},
            {"posicion": 6, "nivel": 0},
            {"posicion": 7, "nivel": 0}
        ]
    }
    return(response)


########
# MAIN #
########


@app.cli.command('create-admin')
@click.option('--name', prompt=_('Nome do administrador'))
@click.option('--email', prompt='E-mail')
@click.option('--password', prompt=_('Senha (mínimo de 10 caracteres)'), hide_input=True, confirmation_prompt=True)
@click.option('--village-id', default=None, help=_('Vincula um save existente e ainda não associado a uma conta.'))
def create_admin(name, email, password, village_id):
    """Cria um administrador aprovado, sem senha padrão."""
    if village_id and village_id not in all_saves_userid():
        raise click.ClickException(_('O save informado não existe. Use o PID do arquivo em saves/.'))
    try:
        account = accounts().create_admin(name, email, password, village_id=village_id)
    except AccountError as exc:
        raise click.ClickException(_(str(exc))) from exc
    click.echo(_('Administrador criado: {email}. Entre e acesse /admin para aprovar os cadastros.', email=account['email']))

# Live duels (duels.py, duels_web.py): off unless SE_DUELS=on. Off, nothing of
# them is imported or registered and the server keeps one request at a time.
DUELS_ENABLED = os.environ.get('SE_DUELS', 'off').strip().lower() in ('on', '1', 'true', 'yes')
app.jinja_env.globals['duels_enabled'] = DUELS_ENABLED
CLANS_ENABLED = os.environ.get('SE_CLANS', 'off').strip().lower() in ('on', '1', 'true', 'yes')
# New accounts are active at once (the owner's decision); SE_AUTO_APPROVE=off brings back approval one by one.
AUTO_APPROVE = os.environ.get('SE_AUTO_APPROVE', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# Unit abilities (swf_unit_abilities.py): automatic, one summon at most, tooltips. Off: the movie is unchanged.
ABILITIES_ENABLED = os.environ.get('SE_ABILITIES', 'off').strip().lower() in ('on', '1', 'true', 'yes')
PVP_ENABLED = os.environ.get('SE_PVP', 'off').strip().lower() in ('on', '1', 'true', 'yes')
# Point 25: free season pass, one per season of Argentina (season_pass.py, season_pass_web.py, swf_season_pass.py).
from season_pass import season_pass_enabled, revision as season_pass_revision
SEASON_PASS_ENABLED = season_pass_enabled()
SOUND_FIX_ENABLED = os.environ.get('SE_SOUND_FIX', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# Point 23: the village darkens at night by Argentina's hour, with rain or snow by season (swf_daylight.py, game.js).
DAY_NIGHT_ENABLED = os.environ.get('SE_DAY_NIGHT', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# Point 26: the improved HUD over the game (the hour and weather clock, ...). The clock follows the day and night cycle.
HUD_ENABLED = os.environ.get('SE_HUD', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# The game fills the whole browser window (no green bands), without the zoom slider, and the map zooms smoothly
# with the mouse wheel or two fingers (swf_view.py, game.js).
VIEW_ENABLED = os.environ.get('SE_VIEW', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# Moving the mouse over the village: the game's check of whether the pointer is on a building's picture keeps its
# last drawing instead of drawing the building again on every move (swf_fast_hover.py).
FAST_HOVER_ENABLED = os.environ.get('SE_FAST_HOVER', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# Point 27: a smarter combat AI for both sides: targets by priority, help in groups, the wounded fall back
# (swf_smart_ai.py).
SMART_AI_ENABLED = os.environ.get('SE_SMART_AI', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# Point 28: every adventure island lets the player choose the team that sails (swf_coop.py).
QUEST_TEAMS_ENABLED = os.environ.get('SE_QUEST_TEAMS', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# Point 28: adventures alone or with the clan, live (COOP_PLAN.md). Off until the live raid works.
COOP_ENABLED = os.environ.get('SE_COOP', 'off').strip().lower() in ('on', '1', 'true', 'yes')
# The menu's performance mode: each player may stop the buildings' animations (swf_perf_mode.py, game.js).
PERF_MODE_ENABLED = os.environ.get('SE_PERF_MODE', 'on').strip().lower() in ('on', '1', 'true', 'yes')
READABLE_UI_ENABLED = os.environ.get('SE_READABLE_UI', 'on').strip().lower() in ('on', '1', 'true', 'yes')
# New accounts: the player name is letters and digits only and names the new empire; registering signs out
# whoever was signed in in that browser. Off: the earlier registration.
EMPIRE_NAME_ENABLED = os.environ.get('SE_EMPIRE_NAME', 'on').strip().lower() in ('on', '1', 'true', 'yes')
app.jinja_env.globals['empire_name_enabled'] = EMPIRE_NAME_ENABLED
# The game queues what the player does and sends it every push_time seconds (a page parameter, 3 to 60; missing,
# the game's own TIMER_COMMANDS, about 30 s). Reloading before that lost it: a gift placed on the map came back
# to the gifts. SE_QUICK_SAVE (on) asks for 3 s, the game's minimum; an empty queue sends nothing.
QUICK_SAVE_ENABLED = os.environ.get('SE_QUICK_SAVE', 'on').strip().lower() in ('on', '1', 'true', 'yes')
QUICK_SAVE_SECONDS = 3
# HD buildings, decorations and map resources (assets_hd/buildingsprites, made by tools/make_hd_sprites.py, not in git):
# served instead of the originals when they exist. Off, or for a sprite without its HD version: the original.
# SE_HD_SPRITES=recursos serves only the map's resources in HD (swf_hd_icons.resource_sprite_names); on: everything made.
HD_SPRITES_MODE = os.environ.get('SE_HD_SPRITES', 'on').strip().lower()
HD_SPRITES_ENABLED = HD_SPRITES_MODE in ('on', '1', 'true', 'yes', 'todo', 'recursos')
# Updates: every start of the server has its own build (updater.py sets SE_BUILD; a server started by hand makes one).
# The game page asks /version and, when it changed, shows "There is an update available" with a Restart button and
# reloads by itself after 10 s, so nobody keeps playing an old server's game (SE_UPDATE_NOTICE, on).
UPDATE_NOTICE_ENABLED = os.environ.get('SE_UPDATE_NOTICE', 'on').strip().lower() in ('on', '1', 'true', 'yes')
SERVER_BUILD = os.environ.get('SE_BUILD') or f'{int(datetime.now(timezone.utc).timestamp())}-{os.getpid()}'
# Ruffle's renderer and quality for the game page ("default" lets Ruffle choose its renderer). With SE_ABILITIES=on
# the quality is "high": at "16x16" Ruffle's wgpu renderer crashed building the ability effects' colour-filter
# shader; its own WebGL renderer does not crash but draws no filters (no outlines, dotted hover highlights).
RUFFLE_RENDERERS = ('webgpu', 'wgpu-webgl', 'webgl', 'canvas')
RUFFLE_QUALITIES = ('low', 'medium', 'high', 'best', '8x8', '8x8linear', '16x16', '16x16linear')


def ruffle_settings():
    renderer = os.environ.get('SE_RUFFLE_RENDERER', 'default').strip().lower()
    quality = os.environ.get('SE_RUFFLE_QUALITY', 'high' if ABILITIES_ENABLED else '16x16').strip().lower()
    return {'renderer': renderer if renderer in RUFFLE_RENDERERS else '',
            'quality': quality if quality in RUFFLE_QUALITIES else '16x16'}


RUFFLE_SETTINGS = ruffle_settings()
app.jinja_env.globals['clans_enabled'] = CLANS_ENABLED
if CLANS_ENABLED:
    from clans_web import install_clans
    install_clans(app, accounts, village_lock, all_saves_userid, village_session, data_dir)
if SEASON_PASS_ENABLED:  # the in-game season pass window; raids and duels count for it
    from get_game_config import get_name_from_item_id
    from localization import load_catalog
    item_texts = lru_cache(maxsize=4)(load_catalog)  # the item names of one language, read once
    from season_pass_web import install_season_pass

    def season_unit_name(item_id):
        name = get_name_from_item_id(int(item_id)) or str(item_id)
        return item_texts(portal_language()).get(name, name)
    install_season_pass(app, village_lock, village_session, save_village, season_unit_name, accounts)
if PVP_ENABLED:  # the in-game PvP window (rivals, raids, duels) and raids with a chosen team
    from pvp import TEAM_LIMIT
    from pvp_web import install_pvp
    install_pvp(app, accounts, village_lock, recover_raids, raids, eligible_village_ids, raid_tokens, TEAM_LIMIT)
if DUELS_ENABLED:
    from duels_web import install_duels
    install_duels(app, accounts, village_lock, all_saves_userid, village_session, data_dir, game_number,
                  validate_game_key)
    if CLANS_ENABLED:  # finished duels count for clan challenges
        app.extensions['duels'].result_listeners.append(app.extensions['clans'].record_duel)
    if SEASON_PASS_ENABLED:  # ... and for the season pass of both players
        app.extensions['duels'].result_listeners.append(app.extensions['season_pass']['on_duel'])
if COOP_ENABLED and CLANS_ENABLED:  # the clan raid's room (coop_web.py); its live notices need SE_DUELS
    from coop_web import install_coop
    install_coop(app, accounts, data_dir)

print (" [+] Running server...")

if __name__ == '__main__':
    # Duels hold open WebSockets, so they need threads; village_lock guards the saves.
    app.run(host=host, port=port, debug=False, threaded=DUELS_ENABLED)
