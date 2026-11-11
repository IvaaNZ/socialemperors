"""Server-resolved raids between approved players, with recoverable settlement.

The caller holds the shared village lock for this service and every legacy save
mutation. One game-server process owns the in-memory saves. SQLite records both
AFTER snapshots before either JSON save is replaced, so interrupted settlements
can be replayed without calculating or transferring the loot a second time.
"""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from get_game_config import get_item_from_id
from sessions import session, save_session
import sessions as village_sessions
from balance import pvp_unit_power
from portal_i18n import translate


RAID_LOOT_PERCENT = 20
ATTACK_COOLDOWN_SECONDS = 15 * 60
DEFENDER_PROTECTION_SECONDS = 60 * 60
PAIR_COOLDOWN_SECONDS = 6 * 60 * 60
RESOURCE_KEYS = ('coins', 'wood', 'food', 'stone')
HISTORY_LIMIT = 20
POWER_DESCRIPTION = (
    'Cada tropa soma 10 × ataque + 5 × defesa + vida; nos kamikazes o ataque '
    'conta uma vez e nas máquinas de cerco, pela metade. A defesa soma também '
    'as muralhas, torres e outras estruturas de defesa. Só contam tropas '
    'da raça da vila, soltas ou abrigadas; trabalhadores e curandeiros não '
    'participam. A maior força vence; em empate, a defesa vence.'
)


class RaidError(ValueError):
    """A rejected raid that the player can correct or retry later."""


def _sync_saves_directory():
    # The JSON writer fsyncs each file before replacing it. Persist the directory
    # entries too before the ledger discards recovery snapshots (POSIX). Windows
    # still supports process-interruption recovery; directory fsync is POSIX-only.
    if os.name != 'posix':
        return
    descriptor = os.open(village_sessions.SAVES_DIR, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _number(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return default


def _main_map(save):
    # Raids concern the village displayed at login, never a client-selected map.
    index = _number(save['playerInfo'].get('default_map'))
    if index >= len(save['maps']):
        raise RaidError('A vila não possui um mapa principal válido.')
    return index, save['maps'][index]


def _resource(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RaidError('Os recursos da vila estão inválidos; o saque foi cancelado.')
    try:
        number = int(value)
    except ValueError:
        raise RaidError('Os recursos da vila estão inválidos; o saque foi cancelado.') from None
    if number < 0:
        raise RaidError('Os recursos da vila estão inválidos; o saque foi cancelado.')
    return number


def _item(item_id):
    if isinstance(item_id, bool):
        return None
    try:
        return get_item_from_id(item_id)
    except (TypeError, ValueError, OverflowError):
        return None


def _power(item):
    # 10 x attack + 5 x defense + life, with the kamikaze and siege fixes in balance.py.
    return pvp_unit_power(item)


def _combatant(item, race):
    groups = set(str(item.get('groups', '')).split())
    return (item.get('type') == 'u' and item.get('race') == race
            and _number(item.get('attack')) > 0
            and not groups.intersection({'worker', 'healer'})
            and _number(item.get('life')) > 0)


def _public_village(userid, save):
    index, town = _main_map(save)
    race = town.get('race', 'h')
    attack_power = 0
    defense_structures = 0
    combatants = 0
    defenses = 0
    for placed in town.get('items', []):
        if not isinstance(placed, list) or not placed:
            continue
        item = _item(placed[0])
        if not item:
            continue
        if _combatant(item, race):
            combatants += 1
            attack_power += _power(item)
        elif (item.get('type') == 'b' and item.get('race') == race
              and str(item.get('category_id')) == '2'):
            defenses += 1
            defense_structures += _power(item)
        # Units sheltered in an owned building remain part of the garrison.
        if item.get('type') == 'b' and item.get('race') == race and len(placed) > 6 and isinstance(placed[6], list):
            for unit_id in placed[6]:
                unit = _item(unit_id)
                if unit and _combatant(unit, race):
                    combatants += 1
                    attack_power += _power(unit)
    names = save['playerInfo'].get('map_names', [])
    name = str(names[index]) if index < len(names) else translate('Meu Império')
    return {
        'userid': userid, 'name': name, 'level': max(1, _number(town.get('level'), 1)),
        'attack_power': attack_power, 'defense_power': attack_power + defense_structures,
        'combatants': combatants, 'troop_count': combatants, 'defenses': defenses,
        'resources': {key: _resource(town.get(key, 0)) for key in RESOURCE_KEYS},
        'tutorial_complete': _number(save['playerInfo'].get('completed_tutorial')) == 1,
    }


class RaidService:
    def __init__(self, database_path):
        self.database_path = str(Path(database_path).expanduser())
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS raids (
                    id TEXT PRIMARY KEY,
                    attacker_id TEXT NOT NULL,
                    defender_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'applied')),
                    result_json TEXT NOT NULL,
                    attacker_after_json TEXT,
                    defender_after_json TEXT,
                    UNIQUE (attacker_id, request_id)
                );
                CREATE INDEX IF NOT EXISTS raids_attacker_time ON raids(attacker_id, created_at);
                CREATE INDEX IF NOT EXISTS raids_defender_time ON raids(defender_id, created_at);
                CREATE INDEX IF NOT EXISTS raids_pending ON raids(status);
            ''')

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        # FULL also applies when this database shares the account store's WAL.
        connection.execute('PRAGMA synchronous = FULL')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _eligible(eligible_userids):
        return {str(userid) for userid in eligible_userids if session(str(userid)) is not None}

    def _apply(self, row):
        snapshots = (
            (row['attacker_id'], json.loads(row['attacker_after_json'])),
            (row['defender_id'], json.loads(row['defender_after_json'])),
        )
        for userid, snapshot in snapshots:
            save = session(userid)
            if save is None or str(snapshot['playerInfo']['pid']) != userid:
                # Never silently lose a journal entry or apply it to another PID.
                raise RuntimeError('Não foi possível recuperar o saque: vila ausente ou inválida.')
        for userid, snapshot in snapshots:
            save = session(userid)
            save.clear()
            save.update(snapshot)
        for userid, _ in snapshots:
            save_session(userid)
        _sync_saves_directory()
        with self._connection() as connection:
            connection.execute('''UPDATE raids SET status = 'applied',
                attacker_after_json = NULL, defender_after_json = NULL
                WHERE id = ? AND status = 'pending' ''', (row['id'],))

    def recover_pending(self):
        """Replay durable AFTER snapshots before allowing any further save edits."""
        with self._connection() as connection:
            pending = connection.execute("SELECT * FROM raids WHERE status = 'pending' ORDER BY created_at, rowid").fetchall()
        for row in pending:
            self._apply(row)
        return len(pending)

    def _applied(self):
        with self._connection() as connection:
            rows = connection.execute("SELECT result_json FROM raids WHERE status = 'applied' ORDER BY created_at DESC, rowid DESC").fetchall()
        return [json.loads(row['result_json']) for row in rows]

    def revision(self, userid):
        """Identify the latest settled raid affecting this player's HUD."""
        with self._connection() as connection:
            row = connection.execute('''SELECT id FROM raids
                WHERE status = 'applied' AND (attacker_id = ? OR defender_id = ?)
                ORDER BY rowid DESC LIMIT 1''', (str(userid), str(userid))).fetchone()
        return row['id'] if row else ''

    @staticmethod
    def _timers(userid, results):
        attack_available_at = 0
        protected_until = 0
        for result in results:
            if result['attacker_id'] == userid:
                attack_available_at = max(attack_available_at, result['created_at'] + ATTACK_COOLDOWN_SECONDS)
            if result['defender_id'] == userid and result['won']:
                protected_until = max(protected_until, result['created_at'] + DEFENDER_PROTECTION_SECONDS)
        return attack_available_at, protected_until

    @staticmethod
    def _permission(own, rival, results, now):
        attack_at, _ = RaidService._timers(own['userid'], results)
        _, protection_at = RaidService._timers(rival['userid'], results)
        pair_at = max((result['created_at'] + PAIR_COOLDOWN_SECONDS for result in results
                       if result['attacker_id'] == own['userid'] and result['defender_id'] == rival['userid']), default=0)
        available_at = max(attack_at, protection_at, pair_at)
        if not own['tutorial_complete']:
            return False, 'Conclua o tutorial para participar dos saques.', available_at
        if not rival['tutorial_complete']:
            return False, 'Esta vila está protegida durante o tutorial.', available_at
        if not own['combatants']:
            return False, 'Treine pelo menos uma tropa combatente para atacar.', available_at
        if abs(own['level'] - rival['level']) > max(3, own['level'] // 2):
            return False, 'Esta vila está fora da sua faixa de nível.', available_at
        if attack_at > now:
            return False, 'Seu exército precisa aguardar entre os ataques.', available_at
        if protection_at > now:
            return False, 'Esta vila está protegida após um saque.', available_at
        if pair_at > now:
            return False, 'Você já atacou esta vila nas últimas 6 horas.', available_at
        return True, '', available_at

    def overview(self, userid, eligible_userids):
        self.recover_pending()
        userid = str(userid)
        eligible = self._eligible(eligible_userids)
        if userid not in eligible:
            raise RaidError('Sua conta não está habilitada para participar dos saques.')
        now = int(time.time())
        results = self._applied()
        own = _public_village(userid, session(userid))
        own['attack_available_at'], own['protected_until'] = self._timers(userid, results)
        rivals = []
        ranking = []
        for rival_id in sorted(eligible):
            rival = _public_village(rival_id, session(rival_id))
            wins = [result for result in results if result['attacker_id'] == rival_id and result['won']]
            ranking.append({
                'userid': rival_id, 'name': rival['name'], 'level': rival['level'],
                'wins': len(wins), 'loot_total': sum(result['total_loot'] for result in wins),
                'defenses_won': sum(result['defender_id'] == rival_id and not result['won'] for result in results),
            })
            if rival_id == userid:
                continue
            rival['can_attack'], rival['blocked_reason'], rival['available_at'] = self._permission(own, rival, results, now)
            _, rival['protected_until'] = self._timers(rival_id, results)
            rival['estimated_loot'] = {key: value * RAID_LOOT_PERCENT // 100 for key, value in rival['resources'].items()}
            rivals.append(rival)
        ranking.sort(key=lambda row: (-row['wins'], -row['loot_total'], -row['defenses_won'], row['name'].casefold(), row['userid']))
        for position, row in enumerate(ranking, 1):
            row['position'] = position
        history = []
        for result in results:
            if userid not in (result['attacker_id'], result['defender_id']):
                continue
            entry = deepcopy(result)
            entry['role'] = 'attacker' if result['attacker_id'] == userid else 'defender'
            entry['enemy_name'] = result['defender_name'] if entry['role'] == 'attacker' else result['attacker_name']
            history.append(entry)
            if len(history) == HISTORY_LIMIT:
                break
        return {
            'own': own, 'rivals': rivals, 'history': history, 'ranking': ranking,
            'rules': {
                'loot_percent': RAID_LOOT_PERCENT, 'attack_cooldown_seconds': ATTACK_COOLDOWN_SECONDS,
                'defender_protection_seconds': DEFENDER_PROTECTION_SECONDS,
                'pair_cooldown_seconds': PAIR_COOLDOWN_SECONDS,
                'max_level_gap': max(3, own['level'] // 2), 'power_description': POWER_DESCRIPTION,
            },
        }

    def raid(self, attacker_id, defender_id, eligible_userids, request_id, now=None):
        self.recover_pending()
        attacker_id, defender_id = str(attacker_id), str(defender_id)
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_id):
            raise RaidError('Solicitação de saque inválida. Atualize a página e tente novamente.')
        eligible = self._eligible(eligible_userids)
        if attacker_id not in eligible or defender_id not in eligible:
            raise RaidError('O saque só está disponível entre contas aprovadas com vilas próprias.')
        if attacker_id == defender_id:
            raise RaidError('Você não pode atacar sua própria vila.')
        with self._connection() as connection:
            previous = connection.execute('SELECT * FROM raids WHERE attacker_id = ? AND request_id = ?', (attacker_id, request_id)).fetchone()
        if previous:
            if previous['defender_id'] != defender_id:
                raise RaidError('Esta solicitação já foi usada para outra vila.')
            return json.loads(previous['result_json'])
        now = int(time.time()) if now is None else _number(now)
        attacker_save, defender_save = session(attacker_id), session(defender_id)
        own, rival = _public_village(attacker_id, attacker_save), _public_village(defender_id, defender_save)
        allowed, reason, _ = self._permission(own, rival, self._applied(), now)
        if not allowed:
            raise RaidError(reason)
        won = own['attack_power'] > rival['defense_power']
        loot = {key: rival['resources'][key] * RAID_LOOT_PERCENT // 100 if won else 0 for key in RESOURCE_KEYS}
        attacker_after, defender_after = deepcopy(attacker_save), deepcopy(defender_save)
        _, attacker_town = _main_map(attacker_after)
        _, defender_town = _main_map(defender_after)
        for key in RESOURCE_KEYS:
            attacker_town[key] = own['resources'][key] + loot[key]
            defender_town[key] = rival['resources'][key] - loot[key]
        result = {
            'id': uuid.uuid4().hex, 'attacker_id': attacker_id, 'defender_id': defender_id,
            'attacker_name': own['name'], 'defender_name': rival['name'], 'created_at': now,
            'attacker_power': own['attack_power'], 'defender_power': rival['defense_power'],
            'won': won, 'loot': loot, 'total_loot': sum(loot.values()),
            'loot_percent': RAID_LOOT_PERCENT,
        }
        with self._connection() as connection:
            connection.execute('''INSERT INTO raids
                (id, attacker_id, defender_id, request_id, created_at, status, result_json, attacker_after_json, defender_after_json)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)''', (
                    result['id'], attacker_id, defender_id, request_id, now,
                    json.dumps(result, ensure_ascii=False), json.dumps(attacker_after, ensure_ascii=False),
                    json.dumps(defender_after, ensure_ascii=False),
                ))
            row = connection.execute('SELECT * FROM raids WHERE id = ?', (result['id'],)).fetchone()
        self._apply(row)
        return result
