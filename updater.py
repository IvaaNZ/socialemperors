"""Automatic updates (SE_AUTO_UPDATE, on by default): `python server.py` keeps the game server running and
replaces it when the code changes, without anyone restarting it by hand.

`python server.py` then starts this watcher instead of the server. The watcher runs the real server as a child
process (`server.py` with SE_SERVER_CHILD=1) and every POLL_SECONDS looks at:

  * the current Git commit (`git rev-parse HEAD`): a new commit is an update;
  * server.env: a changed switch is an update too (no tests needed for it).

Before an update replaces the running server it must pass, in this order:

  1. the test suite (`python -m unittest discover -s tests`), for a new commit;
  2. a trial start of the new server on a free port with an empty, temporary data folder (the players' villages
     and accounts are never touched by the trial), which must answer /login.

If either fails, the running server stays and the reason is written to the log (instance/actualizaciones.log, or
SOCIAL_EMPIRES_DATA_DIR/actualizaciones.log); that commit is not tried again. If both pass, the running server is
stopped and the new one started. Villages are written to disk after every batch of game commands, so stopping it
loses nothing saved. Each start gets a new SE_BUILD: the players' pages see it at /version and show "There is an
update available" with a Restart button (they reload by themselves after 10 seconds), so everyone runs the new
code. A server that stops by itself is started again.

Only commits count, not every saved file: a change half made is never put in front of the players. The server
reads the files of this folder, so what it runs is what is on disk at that commit.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POLL_SECONDS = 10
TEST_TIMEOUT = 1800
START_TIMEOUT = 180
RESTART_PAUSE = 3


def _log_file(environ):
    data_dir = Path(environ.get('SOCIAL_EMPIRES_DATA_DIR') or ROOT / 'instance')
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / 'actualizaciones.log'


class Watcher:
    def __init__(self, console_env, port=None, clock=time.time, sleep=time.sleep, run=subprocess.run,
                 popen=subprocess.Popen):
        """`console_env`: the environment before server.env was read, so the child reads server.env again."""
        self.console_env = dict(console_env)
        self.port = int(port or console_env.get('PORT') or 5050)
        host = console_env.get('HOST') or '127.0.0.1'
        self.host = '127.0.0.1' if host in ('0.0.0.0', '::', '') else host  # listening everywhere: ask locally
        self.clock, self.sleep, self.run, self.popen = clock, sleep, run, popen
        self.log_path = _log_file(console_env)
        self.process = None
        self.commit = None
        self.settings = None
        self.rejected = set()  # commits (or settings) that failed: not tried again

    # --- what the server is running ---
    def say(self, text):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}"
        print(f' [actualizador] {text}', flush=True)
        try:
            with open(self.log_path, 'a', encoding='utf-8') as stream:
                stream.write(line + '\n')
        except OSError:
            pass

    def current_commit(self):
        try:
            result = self.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None

    @staticmethod
    def current_settings():
        try:
            return (ROOT / 'server.env').read_bytes()
        except OSError:
            return b''

    def _child_env(self, extra):
        env = dict(self.console_env)
        env.update(extra)
        env['SE_SERVER_CHILD'] = '1'
        env.setdefault('PYTHONUNBUFFERED', '1')
        return env

    # --- checks before an update ---
    def tests_pass(self):
        self.say('corriendo las pruebas…')
        try:
            result = self.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=ROOT,
                              env=self._child_env({}), capture_output=True, text=True, timeout=TEST_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as error:
            self.say(f'las pruebas no se pudieron correr: {error}')
            return False
        summary = [line for line in (result.stderr or '').splitlines() if line.startswith(('Ran ', 'OK', 'FAILED'))]
        if result.returncode != 0:
            self.say('las pruebas fallaron: ' + ' / '.join(summary[-2:]))
            failures = [line for line in (result.stderr or '').splitlines() if line.startswith(('FAIL:', 'ERROR:'))]
            for line in failures[:10]:
                self.say('  ' + line)
            return False
        self.say('pruebas: ' + ' / '.join(summary[-2:]))
        return True

    @staticmethod
    def free_port():
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            return probe.getsockname()[1]

    def answers(self, port, host='127.0.0.1'):
        try:
            with urllib.request.urlopen(f'http://{host}:{port}/login', timeout=5) as response:
                return response.status == 200
        except OSError:
            return False

    def wait_ready(self, process, port, host='127.0.0.1'):
        deadline = self.clock() + START_TIMEOUT
        while self.clock() < deadline:
            if process.poll() is not None:
                return False
            if self.answers(port, host):
                return True
            self.sleep(1)
        return False

    def trial_start(self):
        """Starts the new code on a free port with empty temporary data: does it answer?"""
        folder = tempfile.mkdtemp(prefix='se-prueba-')
        port = self.free_port()
        (Path(folder) / 'saves').mkdir()
        env = self._child_env({'PORT': str(port), 'HOST': '127.0.0.1', 'SOCIAL_EMPIRES_DATA_DIR': folder,
                               'SOCIAL_EMPIRES_SAVES_DIR': str(Path(folder) / 'saves'), 'SE_BUILD': 'prueba'})
        self.say(f'probando que el servidor nuevo arranque (puerto {port}, datos vacíos)…')
        errors = Path(folder) / 'errores.txt'  # a file, not a pipe: a chatty server can never block on it
        ready = False
        try:
            with open(errors, 'wb') as stream:
                process = self.popen([sys.executable, '-u', 'server.py'], cwd=ROOT, env=env,
                                     stdout=subprocess.DEVNULL, stderr=stream)
                try:
                    ready = self.wait_ready(process, port)
                finally:
                    self._stop(process)
            if not ready:
                self.say('el servidor nuevo no arrancó')
                lines = errors.read_bytes().decode('utf-8', 'replace').strip().splitlines()
                for line in lines[-5:]:
                    self.say('  ' + line)
            return ready
        except OSError as error:
            self.say(f'no se pudo arrancar la prueba: {error}')
            return False
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    # --- the running server ---
    def start(self):
        build = f"{(self.commit or 'local')[:12]}-{int(self.clock())}"
        self.say(f"arrancando el servidor (commit {(self.commit or '?')[:7]}, versión {build})")
        self.process = self.popen([sys.executable, '-u', 'server.py'], cwd=ROOT,
                                  env=self._child_env({'SE_BUILD': build}))
        if self.wait_ready(self.process, self.port, self.host):
            self.say(f'servidor listo en el puerto {self.port}')
            return True
        self.say('el servidor no respondió a tiempo')
        return False

    @staticmethod
    def _stop(process, wait=20):
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=wait)

    def stop(self):
        self._stop(self.process)
        self.process = None

    # --- the loop ---
    def check(self):
        """One look: a stopped server is started again; a new commit or server.env is tried and applied."""
        if self.process is not None and self.process.poll() is not None:
            self.say(f'el servidor se detuvo (código {self.process.returncode}); se vuelve a arrancar')
            self.sleep(RESTART_PAUSE)
            self.start()
            return 'restarted'
        commit, settings = self.current_commit(), self.current_settings()
        new_commit = commit is not None and commit != self.commit
        new_settings = settings != self.settings
        if not new_commit and not new_settings:
            return None
        key = (commit, settings)
        if key in self.rejected:
            return None
        if new_commit:
            self.say(f'commit nuevo: {commit[:7]}')
        else:
            self.say('server.env cambió')
        if (new_commit and not self.tests_pass()) or not self.trial_start():
            self.rejected.add(key)
            self.say('actualización rechazada: sigue el servidor anterior')
            return 'rejected'
        self.say('actualización aprobada: reiniciando el servidor; los jugadores verán el aviso')
        self.stop()
        self.commit, self.settings = commit, settings
        self.start()
        return 'updated'

    def serve_forever(self):
        self.commit, self.settings = self.current_commit(), self.current_settings()
        self.say(f'vigilando los commits y server.env cada {POLL_SECONDS} s (SE_AUTO_UPDATE=off lo apaga)')
        self.start()
        try:
            while True:
                self.sleep(POLL_SECONDS)
                self.check()
        except KeyboardInterrupt:
            self.say('apagando')
        finally:
            self.stop()
        return 0


def supervise(console_env):
    return Watcher(console_env).serve_forever()
