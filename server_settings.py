"""The server's switches from a file, so "python server.py" is enough to start it.

Asked by the owner: starting the server needed a line like
"SE_DUELS=on SE_CLANS=on SE_ABILITIES=on SE_PVP=on python server.py". The
switches now live in server.env (next to server.py, like the mods folder):
one KEY=value per line, on/off for the features. server.py reads it first,
before any module looks at the switches, and only when it is the program being
run: the tests and "flask --app server ..." commands keep the built-in defaults.
A variable given in the console still wins over the file
(SE_PVP=off python server.py), so the old way keeps working.
"""

import os
import re

SETTINGS_FILE = 'server.env'
_LINE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')


def parse_settings(text):
    """KEY=value pairs of the file; blank lines and lines starting with # are skipped."""
    settings, errors = {}, []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = _LINE.match(line)
        if not match:
            errors.append(number)
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        elif '#' in value:  # "SE_COOP=on# comment" (a line glued to the next) is still on
            value = value.split('#', 1)[0].strip()
        settings[match.group(1)] = value
    return settings, errors


def load_settings_file(path=SETTINGS_FILE, environ=None):
    """Put the file's settings in the environment, without replacing variables already set there.

    Returns {key: (value, source)} with source 'file' or 'console'.
    """
    environ = os.environ if environ is None else environ
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8-sig') as handle:
        settings, errors = parse_settings(handle.read())
    for number in errors:
        print(f' [!] {path}, line {number}: not a KEY=value line, skipped.')
    applied = {}
    for key, value in settings.items():
        if key in environ:
            applied[key] = (environ[key], 'console')
        else:
            environ[key] = value
            applied[key] = (value, 'file')
    return applied


def describe(applied):
    """One line for the console: which switches are on and off."""
    switches = sorted((key, value) for key, (value, _) in applied.items() if key.startswith('SE_'))
    return ', '.join(f'{key}={value}' for key, value in switches)
