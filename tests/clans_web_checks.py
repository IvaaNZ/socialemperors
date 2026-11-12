"""Clan pages and actions through the web (run by test_clans_web.py with SE_CLANS=on).

Not collected by unittest discovery on its own: the server module must be
imported with SE_CLANS=on, and the rest of the suite imports it with clans off.
"""

import contextlib
import io
import json
import os
import re
from pathlib import Path
import tempfile
import unittest

assert os.environ.get('SE_CLANS') == 'on', 'run through test_clans_web.py'
_data = tempfile.mkdtemp(prefix='socialemperors-clans-')
os.environ.update(SOCIAL_EMPIRES_DATA_DIR=_data, SOCIAL_EMPIRES_SAVES_DIR=str(Path(_data) / 'saves'),
                  SOCIAL_EMPIRES_LANGUAGE='es')
os.environ.pop('SE_DUELS', None)
with contextlib.redirect_stdout(io.StringIO()):
    import server
    import sessions


class ClanWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.app.config.update(TESTING=True)
        cls.accounts = server.app.extensions['accounts']
        cls.clans = server.app.extensions['clans']
        cls.count = 0

    def player(self, tutorial=True, admin=False):
        type(self).count += 1
        email = f'clan{self.count}@example.com'
        name = f'Jugador {self.count}'
        if admin:
            account = self.accounts.create_admin(name, email, 'secret-password')
        else:
            account = self.accounts.create_account(name, email, 'secret-password', status='approved')
        client = server.app.test_client()
        client.get('/login')
        with client.session_transaction() as session:
            token = session['_csrf_token']
        with contextlib.redirect_stdout(io.StringIO()):
            client.post('/login', data={'email': email, 'password': 'secret-password', 'csrf_token': token})
            client.get('/play.html')  # makes the village
        with client.session_transaction() as session:
            token = session['_csrf_token']  # a new session after login
        account = self.accounts.get(account['id'])
        if account['village_id']:
            with server.village_lock:
                sessions.session(account['village_id'])['playerInfo']['completed_tutorial'] = 1 if tutorial else 0
        client.account = account
        client.token = token
        return client

    def post(self, client, path, **data):
        with contextlib.redirect_stdout(io.StringIO()):
            return client.post(path, data={'csrf_token': client.token, **data})

    def page(self, client, path):
        with contextlib.redirect_stdout(io.StringIO()):
            return client.get(path).get_data(as_text=True)

    def role(self, client):
        member = self.clans.membership(client.account['id'])
        return member and member['role']

    def make_clan(self, master, name, tag):
        response = self.post(master, '/clans', name=name, tag=tag, description='Hola')
        self.assertEqual(response.status_code, 302)
        return self.clans.membership(master.account['id'])['clan_id']

    def join(self, client, clan_id, approver):
        self.post(client, f'/clans/{clan_id}/request', action='join')
        request_id = next(r['id'] for r in self.clans.requests_for(clan_id) if r['account_id'] == client.account['id'])
        self.post(approver, f'/clans/requests/{request_id}', action='accept')
        self.assertEqual(self.role(client), 'member')

    def test_create_join_and_pages(self):
        ana, beto = self.player(), self.player()
        clan_id = self.make_clan(ana, 'Los Ñandúes', 'nan')
        self.assertEqual(self.role(ana), 'master')
        page = self.page(ana, f'/clans/{clan_id}')
        self.assertIn('[NAN] Los Ñandúes', page)
        self.assertIn('Guild Master', page)
        self.assertIn('Clanes', page)  # menu link, in Spanish
        self.post(beto, f'/clans/{clan_id}/request', action='join')
        self.assertIn('Solicitud enviada', self.page(beto, f'/clans/{clan_id}'))
        self.assertIn('Solicitudes para entrar', self.page(ana, f'/clans/{clan_id}'))
        self.assertIn(beto.account['name'], self.page(ana, f'/clans/{clan_id}'))
        request_id = self.clans.requests_for(clan_id)[0]['id']
        self.post(ana, f'/clans/requests/{request_id}', action='accept')
        self.assertEqual(self.role(beto), 'member')
        listing = self.page(beto, '/clans?q=nandu')
        self.assertIn('Tu clan', listing)
        self.assertIn('2 de 70 miembros', listing)

    def test_no_tutorial_no_clan_and_csrf_is_required(self):
        novice = self.player(tutorial=False)
        self.post(novice, '/clans', name='Novatos', tag='NOV')
        self.assertIsNone(self.role(novice))
        self.assertIn('Termina el tutorial para crear un clan.', self.page(novice, '/clans'))
        ana = self.player()
        with contextlib.redirect_stdout(io.StringIO()):
            response = ana.post('/clans', data={'name': 'Sin token', 'tag': 'SIN'})
        self.assertIn(response.status_code, (400, 403))
        self.assertIsNone(self.role(ana))

    def test_hand_made_requests_cannot_skip_permissions(self):
        master, assist, member, other = self.player(), self.player(), self.player(), self.player()
        clan_id = self.make_clan(master, 'Permisos', 'PRM')
        for client in (assist, member, other):
            self.join(client, clan_id, master)
        self.post(master, f'/clans/members/{assist.account["id"]}', action='assist')
        self.assertEqual(self.role(assist), 'assist')
        # An Assist cannot name Assists, remove an Assist or the Guild Master, nor edit or dissolve.
        self.post(assist, f'/clans/members/{member.account["id"]}', action='assist')
        self.post(assist, f'/clans/members/{master.account["id"]}', action='kick')
        self.post(assist, f'/clans/members/{member.account["id"]}', action='transfer')
        self.post(assist, '/clans/edit', description='hackeado')
        self.post(assist, '/clans/dissolve', confirm='yes')
        self.assertEqual((self.role(master), self.role(assist), self.role(member)), ('master', 'assist', 'member'))
        self.assertEqual(self.clans.clan(clan_id)['description'], 'Hola')
        # A plain member cannot answer requests nor remove anyone.
        stranger = self.player()
        self.post(stranger, f'/clans/{clan_id}/request', action='join')
        request_id = self.clans.requests_for(clan_id)[0]['id']
        self.post(member, f'/clans/requests/{request_id}', action='accept')
        self.post(member, f'/clans/members/{other.account["id"]}', action='kick')
        self.assertEqual((self.role(stranger), self.role(other)), (None, 'member'))
        self.assertIn('No tienes permiso para hacer eso.', self.page(member, f'/clans/{clan_id}'))
        # The Assist does what an Assist may: answer requests and remove plain members.
        self.post(assist, f'/clans/requests/{request_id}', action='accept')
        self.post(assist, f'/clans/members/{other.account["id"]}', action='kick')
        self.assertEqual((self.role(stranger), self.role(other)), ('member', None))
        self.assertEqual(self.post(master, f'/clans/members/{member.account["id"]}', action='dance').status_code, 400)

    def test_text_is_escaped(self):
        ana = self.player()
        self.post(ana, '/clans', name='Seguros', tag='SEG', description='<script>alert(1)</script>')
        clan_id = self.clans.membership(ana.account['id'])['clan_id']
        page = self.page(ana, f'/clans/{clan_id}')
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;', page)

    def test_leave_transfer_and_dissolve_by_the_guild_master(self):
        master, member = self.player(), self.player()
        clan_id = self.make_clan(master, 'Salida', 'SAL')
        self.join(member, clan_id, master)
        self.post(master, '/clans/leave')
        self.assertEqual(self.role(master), 'master')  # must hand over the lead first
        self.post(master, f'/clans/members/{member.account["id"]}', action='transfer')
        self.assertEqual((self.role(master), self.role(member)), ('member', 'master'))
        self.post(master, '/clans/leave')
        self.assertIsNone(self.role(master))
        self.assertIn('Saliste de un clan hace poco', self.page(master, '/clans'))
        self.post(member, '/clans/dissolve')  # without the confirmation box
        self.assertEqual(self.role(member), 'master')
        self.post(member, '/clans/dissolve', confirm='yes')
        self.assertIsNone(self.clans.clan(clan_id))

    def test_admin_section(self):
        admin, player = self.player(admin=True), self.player()
        clan_id = self.make_clan(player, 'Ofensivo', 'OFE')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(player.get('/admin/clans').status_code, 403)
        page = self.page(admin, '/admin/clans')
        self.assertIn('[OFE] Ofensivo', page)
        self.post(admin, f'/admin/clans/{clan_id}/dissolve', reason='')
        self.assertIsNotNone(self.clans.clan(clan_id))
        self.post(admin, f'/admin/clans/{clan_id}/dissolve', reason='Nombre ofensivo')
        self.assertIsNone(self.clans.clan(clan_id))
        self.assertIn('Nombre ofensivo', self.page(admin, '/admin/clans'))
        self.assertIn('/admin/clans', self.page(admin, '/admin'))  # admin menu link

    def test_clan_challenge_through_the_pages(self):
        alfa, alfa_assist, beta = self.player(), self.player(), self.player()
        alfa_id = self.make_clan(alfa, 'Alfa Retos', 'ARE')
        beta_id = self.make_clan(beta, 'Beta Retos', 'BRE')
        self.join(alfa_assist, alfa_id, alfa)
        self.post(alfa, f'/clans/members/{alfa_assist.account["id"]}', action='assist')
        self.assertIn('Retar a este clan', self.page(alfa, f'/clans/{beta_id}'))
        self.assertNotIn('Retar a este clan', self.page(alfa_assist, f'/clans/{beta_id}'))  # only the Guild Master
        self.post(alfa_assist, f'/clans/{beta_id}/challenge', best_of='3')  # hand-made: refused
        self.assertIsNone(self.clans.current_challenge(alfa_id))
        self.post(alfa, f'/clans/{beta_id}/challenge', best_of='9')
        self.assertIsNone(self.clans.current_challenge(alfa_id))
        self.post(alfa, f'/clans/{beta_id}/challenge', best_of='5')
        challenge = self.clans.current_challenge(alfa_id)
        self.assertEqual((challenge['status'], challenge['best_of']), ('pending', 5))
        page = self.page(beta, f'/clans/{beta_id}')
        self.assertIn('retó a tu clan al mejor de 5 duelos.', page)
        self.assertIn('Aceptar reto', page)
        self.assertIn('Esperando la respuesta', self.page(alfa, f'/clans/{alfa_id}'))
        self.post(alfa, f'/clans/challenges/{challenge["id"]}', action='accept')  # the challenger cannot accept
        self.assertEqual(self.clans.current_challenge(alfa_id)['status'], 'pending')
        self.post(beta, f'/clans/challenges/{challenge["id"]}', action='accept')
        page = self.page(alfa, f'/clans/{alfa_id}')
        self.assertIn('Al mejor de 5 contra', page)
        self.assertIn('Gana el clan que llega primero a 3 victorias.', page)
        self.post(alfa_assist, f'/clans/challenges/{challenge["id"]}', action='surrender')  # an Assist cannot
        self.assertEqual(self.clans.current_challenge(alfa_id)['status'], 'active')
        self.post(beta, f'/clans/challenges/{challenge["id"]}', action='surrender')
        self.assertIsNone(self.clans.current_challenge(alfa_id))
        history = self.page(alfa, f'/clans/{alfa_id}')
        self.assertIn('Retos anteriores', history)
        self.assertIn('Victoria', history)
        self.assertIn('por rendición', history)
        ranking = self.page(alfa, '/clans')
        self.assertIn('Ranking de clanes', ranking)
        self.assertLess(ranking.index('[ARE]'), ranking.index('[BRE]'))
        self.post(beta, f'/clans/{alfa_id}/challenge', best_of='3')  # free to challenge again at once
        self.assertEqual(self.clans.current_challenge(beta_id)['status'], 'pending')

    def api(self, client, path):
        with contextlib.redirect_stdout(io.StringIO()):
            response = client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.get_json()

    def action(self, client, action, **fields):
        with contextlib.redirect_stdout(io.StringIO()):
            response = client.post('/clans/api/action', data={'csrf_token': client.token, 'action': action, **fields})
        return response.get_json(), response.status_code

    def test_game_page_carries_the_clan_window(self):
        ana = self.player()
        page = self.page(ana, '/play.html')
        config = json.loads(re.search(r'<script id="clan-overlay-config" type="application/json">(.*?)</script>', page).group(1))
        self.assertEqual((config['state'], config['action'], config['csrf']), ('/clans/api/state', '/clans/api/action', ana.token))
        self.assertEqual(config['texts']['button'], 'Clan')
        self.assertIn('js/clan_overlay.js', page)

    def test_the_window_api_creates_edits_and_joins(self):
        ana, beto, caro = self.player(), self.player(), self.player()
        state = self.api(ana, '/clans/api/state')
        self.assertIsNone(state['clan'])
        self.assertTrue(state['me']['can_create'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ana.post('/clans/api/action', data={'action': 'create', 'name': 'Sin token', 'tag': 'STK'}).status_code, 400)
        result, _ = self.action(ana, 'create', name='Ventana', tag='VEN', description='Lema', emblem='6')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['message'], 'Clan creado.')
        clan = result['state']['clan']
        self.assertEqual((clan['tag'], clan['emblem'], clan['role'], clan['leader'], clan['members']), ('VEN', 6, 'master', ana.account['name'], 1))
        self.assertGreaterEqual(clan['power'], 0)
        # By request: Beto asks; the Guild Master accepts from the window.
        result, _ = self.action(beto, 'join', clan_id=str(clan['id']))
        self.assertEqual((result['ok'], result['message']), (True, 'Solicitud enviada. Un líder del clan la va a responder.'))
        self.assertTrue(self.api(beto, f'/clans/api/clans/{clan["id"]}')['requested'])
        request_id = self.api(ana, '/clans/api/state')['clan']['requests'][0]['id']
        self.assertTrue(self.action(ana, 'accept_request', request_id=str(request_id))[0]['ok'])
        # An Assist cannot edit the clan.
        self.assertTrue(self.action(ana, 'make_assist', target_id=str(beto.account['id']))[0]['ok'])
        result, _ = self.action(beto, 'settings', emblem='2', description='', announcement='x', recruit_open='1', min_level='1', language='all')
        self.assertEqual((result['ok'], result['message']), (False, 'No tienes permiso para hacer eso.'))
        # Open recruitment with a minimum level.
        result, _ = self.action(ana, 'settings', emblem='9', description='Nuevo lema', announcement='Hola\nclan', recruit_open='1',
                                min_level='99', language='es')
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['state']['clan']['announcement'], result['state']['clan']['open']), ('Hola\nclan', True))
        result, _ = self.action(caro, 'join', clan_id=str(clan['id']))
        self.assertEqual((result['ok'], result['message']), (False, 'Tu aldea principal no tiene el nivel mínimo de este clan.'))
        self.action(ana, 'settings', emblem='9', description='Nuevo lema', announcement='', recruit_open='1', min_level='1', language='es')
        result, _ = self.action(caro, 'join', clan_id=str(clan['id']))
        self.assertEqual((result['ok'], result['message'], result['state']['clan']['role']), (True, 'Entraste al clan.', 'member'))
        found = self.api(caro, '/clans/api/clans?q=venta')['clans']
        self.assertEqual([(c['tag'], c['open'], c['language'], c['members']) for c in found], [('VEN', True, 'es', 3)])
        self.assertEqual(self.action(caro, 'dance')[1], 400)

    def test_the_window_api_runs_clan_challenges(self):
        ana, beto = self.player(), self.player()
        alfa = self.action(ana, 'create', name='Alfa API', tag='AAP')[0]['state']['clan']['id']
        beta = self.action(beto, 'create', name='Beta API', tag='BAP')[0]['state']['clan']['id']
        card = self.api(ana, f'/clans/api/clans/{beta}')
        self.assertTrue(card['can_challenge_this'])
        self.assertIsNone(card['challenge'])  # another clan's challenge is not shown to outsiders
        result, _ = self.action(ana, 'challenge', clan_id=str(beta), best_of='3')
        self.assertTrue(result['ok'], result)
        incoming = self.api(beto, '/clans/api/state')['clan']['challenge']
        self.assertEqual((incoming['status'], incoming['incoming'], incoming['best_of'], incoming['rival_tag']), ('pending', True, 3, 'AAP'))
        self.assertTrue(self.action(beto, 'accept_challenge', challenge_id=str(incoming['id']))[0]['ok'])
        active = self.api(ana, '/clans/api/state')['clan']['challenge']
        self.assertEqual((active['status'], active['needed'], active['our_wins']), ('active', 2, 0))
        self.assertFalse(self.api(ana, f'/clans/api/clans/{beta}')['can_challenge_this'])
        result, _ = self.action(ana, 'surrender', challenge_id=str(active['id']))
        self.assertTrue(result['ok'])
        history = result['state']['clan']['history'][0]
        self.assertEqual((history['outcome'], history['ending']), ('lost', 'surrender'))
        tags = [row['tag'] for row in self.api(ana, '/clans/api/state')['ranking']]
        self.assertLess(tags.index('BAP'), tags.index('AAP'))  # the clan that won the challenge ranks higher

    def test_the_window_api_needs_an_approved_player(self):
        anonymous = server.app.test_client()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(anonymous.get('/clans/api/state').status_code, 403)
            self.assertIn(anonymous.post('/clans/api/action', data={'action': 'create'}).status_code, (400, 403))

    def test_pages_need_an_approved_session(self):
        anonymous = server.app.test_client()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(anonymous.get('/clans').status_code, 302)
            self.assertIn(anonymous.post('/clans', data={'name': 'x'}).status_code, (302, 400, 403))


if __name__ == '__main__':
    unittest.main()
