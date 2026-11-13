"""Automatic unit abilities, the one-summon limit and ability tooltips (swf_unit_abilities.py)."""

import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swf_abc import AbcError, OPCODES, Reader, disassemble
from swf_unit_abilities import (KINDS, MAX_SUMMONS, SUMMON, TEXTS, ability_table, add_unit_abilities,
                                automatic_ability_units, classify)
from test_swf_duel_bridge import abc_of

_boot_directory = tempfile.TemporaryDirectory(prefix='socialemperors-tests-')
with patch.dict(os.environ, {
    'SOCIAL_EMPIRES_DATA_DIR': _boot_directory.name,
    'SOCIAL_EMPIRES_LANGUAGE': 'pt-BR',
    'SOCIAL_EMPIRES_SAVES_DIR': str(Path(_boot_directory.name) / 'saves'),
}), contextlib.redirect_stdout(io.StringIO()):
    os.environ.pop('SE_ABILITIES', None)
    import server

NEW_UNIT_METHODS = ('__abilityKind', '__isSummon', '__tipHtml', '__summonBlocked', '__shownIn', '__notifyCast',
                    '__refreshPortraits', '__autoCast', '__abilityTick')
NEW_PORTRAIT_METHODS = ('__tipOut', '__tipOver', '__tipHook', '__limitView')
BRANCHES = {'jump', 'iftrue', 'iffalse', 'ifeq', 'ifne', 'iflt', 'ifle', 'ifgt', 'ifge', 'ifnlt', 'ifnle', 'ifngt', 'ifnge',
            'ifstricteq', 'ifstrictne'}


def ops(abc, method_index):
    return [(name, operands) for _, name, operands in disassemble(abc, abc.body_of(method_index)['code'])]


def shape(code):
    """Instructions without branch targets (absolute offsets move when code is prepended)."""
    return [(name, '' if name in BRANCHES or name == 'lookupswitch' else operands) for name, operands in code]


def branches(code):
    """(instruction offset, target offset, instruction name) of every branch, and the set of instruction offsets."""
    reader, starts, found = Reader(code), {}, []
    while reader.pos < len(code):
        start = reader.pos
        name, kinds = OPCODES[reader.u8()]
        starts[start] = name
        for kind in kinds:
            if kind == 'u8':
                reader.u8()
            elif kind == 's24':
                offset = reader.s24()
                if name in BRANCHES:
                    found.append((start, reader.pos + offset, name))
            elif kind == 'switch':
                reader.s24()
                for _ in range(reader.u30() + 1):
                    reader.s24()
            else:
                reader.u30()
    return found, starts


class AbilityTableTests(unittest.TestCase):
    def test_summons_are_recognised_by_their_code(self):
        self.assertEqual(classify('Egg', 'egg.png', ['spawnMinionFromEgg'], set()), SUMMON)
        self.assertEqual(classify('Whatever', '', [], {'checkMaxMinions'}), SUMMON)
        self.assertEqual(classify('Whirlwind', '', ['spawnWhirlwind'], set()), 'whirl')  # whirlwinds are not units
        self.assertEqual(classify('Fireball Rain', '', [], set()), 'area')
        self.assertEqual(classify('Heal', '', [], set()), 'heal')
        self.assertEqual(classify('Limit attack', '', [], set()), 'limit')
        self.assertEqual(classify('Zzz', '', [], set()), 'other')

    def test_every_language_describes_every_kind(self):
        for language, texts in TEXTS.items():
            for kind in KINDS:
                title, description = texts[kind]
                self.assertTrue(title and description, (language, kind))
            for word in ('auto', 'manual', 'limit_word'):
                self.assertTrue(texts[word], (language, word))
        self.assertEqual(MAX_SUMMONS, 1)


class UnitAbilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            cls.original, _ = server.localized_game_movie('es')  # abilities off
        cls.patched = add_unit_abilities(cls.original, language='es')
        cls.debug = add_unit_abilities(cls.original, language='es', debug=True)
        cls.before, _ = abc_of(cls.original)
        cls.abc, cls.raw = abc_of(cls.patched)

    def test_the_duel_list_of_automatic_units_matches_the_movie(self):
        import json
        saved = json.loads((Path(__file__).resolve().parent.parent / 'config' / 'duels' / 'ability_units.json')
                           .read_text(encoding='utf-8'))
        units = automatic_ability_units(self.before)
        self.assertEqual(saved, {'movie': server.GAME_VERSION, 'units': units})  # tools/make_ability_units.py
        self.assertGreater(len(units), 150)
        self.assertTrue({615, 765, 781, 847} <= set(units))  # mummy, Hades, Vulcano and its dragon
        self.assertNotIn(1, units)  # a plain soldier

    def test_the_movie_rebuilds_byte_for_byte(self):
        self.assertEqual(self.abc.serialize(), self.raw)

    def test_abilities_off_serves_the_original_game(self):
        self.assertFalse(server.ABILITIES_ENABLED)
        for name in NEW_UNIT_METHODS:
            with self.assertRaises(AbcError):
                self.before.method_of('IsoSpecialUnit', name)

    def test_it_is_added_once(self):
        with self.assertRaises(AbcError):
            add_unit_abilities(self.patched)

    def test_the_table_knows_the_game_abilities(self):
        table = ability_table(self.before)
        self.assertGreater(len(table), 300)
        self.assertGreater(list(table.values()).count(SUMMON), 30)
        self.assertLessEqual(set(table.values()), set(KINDS))

    def test_the_unit_timer_and_the_spawn_routines_are_guarded(self):
        tick = self.abc.method_of('IsoSpecialUnit', 'tTick')
        self.assertEqual(ops(self.abc, tick)[:2], [('getlocal0', ''), ('callpropvoid', '__abilityTick 0')])
        for owner, name in (('IsoSpecialUnit', 'tTick'), ('IsoSpecialUnit', 'doAttack'), ('IsoSpecialUnit', 'spawnMinion'),
                            ('IsoSpecialUnit', 'spawnMinionFromEgg'), ('AbstractDelegate', 'spawnMinions')):
            method = self.abc.method_of(owner, name)
            before = self.before.body_of(self.before.method_of(owner, name))['exceptions']
            # one more handler than the game had: a failure of the new code runs the original method
            self.assertEqual(len(self.abc.body_of(method)['exceptions']), len(before) + 1, name)
            original = shape(ops(self.before, self.before.method_of(owner, name)))
            self.assertEqual(shape(ops(self.abc, method))[-len(original):], original, name)  # the game's code follows intact

    def test_summons_are_capped_at_one(self):
        egg = ops(self.abc, self.abc.method_of('IsoSpecialUnit', 'spawnMinionFromEgg'))
        self.assertEqual(egg[:4], [('getlocal0', ''), ('getproperty', 'minionsAlive'), ('pushbyte', str(MAX_SUMMONS)),
                                   ('iflt', egg[3][1])])
        spawn = ops(self.abc, self.abc.method_of('AbstractDelegate', 'spawnMinions'))
        self.assertEqual(spawn[:2], [('getlocal2', ''), ('pushbyte', str(MAX_SUMMONS))])
        attack = ops(self.abc, self.abc.method_of('IsoSpecialUnit', 'doAttack'))
        self.assertIn(('callproperty', '__summonBlocked 1'), attack[:4])

    def test_only_unlimited_abilities_cast_by_themselves(self):
        code = ops(self.abc, self.abc.method_of('IsoSpecialUnit', '__autoCast'))
        at = code.index(('getproperty', 'numAttacks'))
        self.assertEqual(code[at + 1][0], 'pushbyte')
        self.assertIn(code[at + 1][1], ('-1', '255'))  # unlimited uses
        self.assertEqual(code[at + 2][0], 'ifne')
        self.assertIn(('callproperty', 'doAttack 1'), code)
        tick = ops(self.abc, self.abc.method_of('IsoSpecialUnit', '__abilityTick'))
        self.assertIn(('getproperty', 'bAttacking'), tick)  # only in combat

    def test_the_new_code_passes_ruffle_verifier_rules(self):
        methods = [self.abc.method_of('IsoSpecialUnit', name) for name in NEW_UNIT_METHODS]
        methods += [self.abc.method_of('PortraitSpecialAttack', name) for name in NEW_PORTRAIT_METHODS]
        for method in methods:
            found, starts = branches(self.abc.body_of(method)['code'])
            for at, target, name in found:
                self.assertIn(target, starts, (method, at))
                if target <= at:  # a backward branch lands on an OP_label
                    self.assertEqual(starts[target], 'label', (method, at))
            self.assertEqual(len(self.abc.body_of(method)['exceptions']), 1, method)

    def test_the_button_constructor_handler_restores_the_scope(self):
        iinit = self.abc.instances[self.abc.class_index('PortraitSpecialAttack')]['iinit']
        body = self.abc.body_of(iinit)
        handler = body['exceptions'][-1][2]
        code = disassemble(self.abc, body['code'])
        after = [(name, operands) for offset, name, operands in code if offset >= handler][:2]
        self.assertEqual(after, [('getlocal0', ''), ('pushscope', '')])
        self.assertIn(('callpropvoid', '__tipHook 0'), [(name, operands) for _, name, operands in code])

    def test_tooltip_texts_and_the_red_limit_label(self):
        strings = set(self.abc.strings)
        texts = TEXTS['es']
        self.assertIn(f'<br><i>{texts["auto"]}</i>', strings)
        self.assertIn(f'<br><i>{texts["manual"]}</i>', strings)
        self.assertIn(f'<br><b>{texts["limit_word"]} ', strings)
        self.assertTrue(any(f'{texts["limit_word"]} 1/1' in text for text in strings if isinstance(text, str)))
        limit_view = ops(self.abc, self.abc.method_of('PortraitSpecialAttack', '__limitView'))
        self.assertIn(('constructprop', 'ColorTransform 8'), limit_view)

    def test_console_traces_only_with_the_debug_switch(self):
        self.assertNotIn(b'se-ability', abc_of(self.patched)[1])
        traced = abc_of(self.debug)[1]
        self.assertIn(b'se-ability cast', traced)
        self.assertIn(b'se-ability error', traced)
        for noisy in (b'se-ability tick', b'se-ability step', b'se-ability tip'):
            self.assertNotIn(noisy, traced)


if __name__ == '__main__':
    unittest.main()
