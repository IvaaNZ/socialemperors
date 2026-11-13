"""Every sentence the clan and duel pages can show has a Spanish and an English translation.

The web side writes its messages in Portuguese (the source language) and translates them when
they are shown; a sentence missing from a catalog would reach the player in Portuguese.
"""

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('clans_web.py', 'duels_web.py')


def sentences(path):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            text = node.value
            if ' ' in text and text[:1].isupper() and text.rstrip()[-1:] in '.!?…' and not text.startswith(('SELECT', 'UPDATE', 'INSERT', 'DELETE')):
                yield text


class WebTextsTranslatedTests(unittest.TestCase):
    def test_clan_and_duel_sentences_are_in_the_catalogs(self):
        for language in ('es', 'en'):
            catalog = json.loads((ROOT / 'config' / 'locales' / f'{language}-portal.json').read_text(encoding='utf-8'))
            for path in SOURCES:
                missing = sorted({text for text in sentences(path) if text not in catalog})
                self.assertEqual(missing, [], f'{path} → {language}-portal.json')

    def test_every_logged_clan_action_has_a_label(self):
        import re
        from clans_web import log_labels
        source = (ROOT / 'clans.py').read_text(encoding='utf-8')
        logged = set()
        for call in re.findall(r"self\._log\(([^\n]*)", source):
            logged.update(re.findall(r"(?<!== )'([a-z_]+)'(?=,? (?:now|if|else))", call))  # not the role == '...' test
        self.assertGreaterEqual(len(logged), 15)
        self.assertEqual(sorted(logged - set(log_labels())), [])  # shown as their internal code otherwise


if __name__ == '__main__':
    unittest.main()
