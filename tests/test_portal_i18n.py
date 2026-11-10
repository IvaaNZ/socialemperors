"""Check the Spanish portal catalog and its use in rendered pages and messages."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from auth import AccountStore
import portal_i18n
from portal_i18n import load_portal_catalog, set_portal_language, translate, translations_for

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}):
    with contextlib.redirect_stdout(io.StringIO()):
        import server
        import sessions

ROOT = Path(__file__).resolve().parent.parent


def template_sources():
    """Portuguese literals passed to _() in templates and server.py, and t() in game.js."""
    sources = set()
    for path in sorted((ROOT / 'templates').glob('*.html')):
        sources.update(re.findall(r"_\('((?:[^'\\]|\\.)*)'", path.read_text(encoding='utf-8')))
    sources.update(re.findall(r"_\('((?:[^'\\]|\\.)*)'", (ROOT / 'server.py').read_text(encoding='utf-8')))
    sources.update(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', (ROOT / 'templates' / 'js' / 'game.js').read_text(encoding='utf-8')))
    return sources


class SpanishPortalTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_portal_language, portal_i18n.portal_language())
        set_portal_language('es')

    def test_catalog_covers_every_marked_text_and_keeps_placeholders(self):
        catalog = json.loads((ROOT / 'config' / 'locales' / 'es-portal.json').read_text(encoding='utf-8'))
        missing = sorted(source for source in template_sources() if source not in catalog)
        self.assertEqual(missing, [])
        for source, translated in catalog.items():
            with self.subTest(source=source):
                self.assertTrue(translated)
                self.assertEqual(sorted(re.findall(r'\{\w+\}', source)), sorted(re.findall(r'\{\w+\}', translated)))

    def test_translation_fills_values_and_matches_dynamic_messages(self):
        self.assertEqual(translate('Minha vila'), 'Mi aldea')
        self.assertEqual(translate('Nível {level}', level=7), 'Nivel 7')
        self.assertEqual(translate('Informe um número inteiro válido para dinheiro.'), 'Ingresa un número entero válido para dinero.')
        self.assertEqual(translate('O nome da vila deve ter entre 2 e 32 caracteres.'), 'El nombre de la aldea debe tener entre 2 y 32 caracteres.')
        self.assertEqual(translate('Texto desconhecido'), 'Texto desconhecido')
        self.assertEqual(translate(None), None)
        self.assertEqual(translations_for(['Silenciar', 'Ativar som', 'Texto desconhecido']), {'Ativar som': 'Activar sonido'})

    def test_portuguese_stays_the_source_language(self):
        set_portal_language('pt-BR')
        self.assertEqual(translate('Minha vila'), 'Minha vila')
        self.assertEqual(translate('Nível {level}', level=7), 'Nível 7')
        self.assertEqual(load_portal_catalog('pt-BR'), ({}, ()))

    def test_login_and_register_pages_render_in_spanish(self):
        directory = tempfile.TemporaryDirectory(prefix='socialemperors-i18n-')
        self.addCleanup(directory.cleanup)
        saves = patch.object(sessions, 'SAVES_DIR', str(Path(directory.name) / 'saves'))
        saves.start()
        self.addCleanup(saves.stop)
        store = AccountStore(Path(directory.name) / 'accounts.sqlite3')
        extension = patch.dict(server.app.extensions, {'accounts': store})
        extension.start()
        self.addCleanup(extension.stop)
        server.app.config.update(TESTING=True)
        client = server.app.test_client()

        page = client.get('/login').get_data(as_text=True)
        self.assertIn('<html lang="es">', page)
        self.assertIn('Entra a tu aldea', page)
        self.assertIn('Contraseña', page)
        self.assertNotIn('Entre na sua vila', page)

        with client.session_transaction() as session:
            token = session['_csrf_token']
        failed = client.post('/login', data={'email': 'nobody@example.com', 'password': 'secret-password', 'csrf_token': token})
        self.assertIn('Correo o contraseña incorrectos.', failed.get_data(as_text=True))

        register = client.get('/register').get_data(as_text=True)
        self.assertIn('Crea tu cuenta', register)
        self.assertIn('Solicitar registro', register)

    def test_game_script_receives_only_spanish_overrides(self):
        texts = server.game_script_texts()
        self.assertEqual(texts['Não foi possível abrir o jogo'], 'No se pudo abrir el juego')
        self.assertNotIn('Volume', texts)


if __name__ == '__main__':
    unittest.main()
