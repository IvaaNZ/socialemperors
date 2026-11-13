"""Automatic unit abilities, a limit of one summon and ability tooltips (SE_ABILITIES=on only).

The game's special units (IsoSpecialUnit: dragons, gods, colossi...) have
abilities ("special attacks", SpecialUnitAttack) that only fire when the
player clicks their button in the unit's info box (PortraitSpecialAttack);
not even the enemy AI uses them. Each unit has one state: idle, casting or
cooling down. This edit adds:

  * IsoSpecialUnit.__abilityTick(), called first in IsoSpecialUnit.tTick (the
    unit's timer): when the unit is alive, idle and attacking (bAttacking:
    in the duel arena TargetElement stays empty), it casts its next ready
    ability with unlimited uses (__autoCast, round
    robin, through the game's own doAttack). It runs for every unit, the
    player's and the enemy's. When the unit is the one shown in the info box,
    the box shows the cast and cooldown as for a click
    (RecuadroInfo.castSpecialAttacks), and its summon buttons refresh
    (__refreshPortraits);
  * a summon limit of one: IsoSpecialUnit.doAttack refuses a summon while the
    unit has a summon alive (__summonBlocked), and the shared spawn
    routines create at most one unit (AbstractDelegate.spawnMinions caps its
    count at 1; IsoSpecialUnit.spawnMinionFromEgg and spawnMinion spawn
    nothing while one is alive). Summons are recognised here, when the movie
    is patched: their check is checkMaxMinions/checkMinions or their action
    spawns minions, draggies, eggs, imps or spiders;
  * a tooltip on every ability button (PortraitSpecialAttack: roll over /
    roll out): the kind of ability, a short description, "Limit X/1" for a
    summon (X = summons alive) and whether it casts by itself in combat or,
    having limited uses, stays manual. It is drawn on the stage, to the left
    of the ability buttons;
  * a summon button whose cooldown is over while the unit already has its
    summon alive turns red and shows "Limit 1/1" (__limitView).

The descriptions go by kind (summon, healing, protection, ultimate,
whirlwind, area, ranged, strong hit, other), chosen here from each ability's
name and code; the table (name|thumbnail -> kind) is a static object of
IsoSpecialUnit built the first time it is read. Every new method runs inside
its own try/catch, so an unexpected value can never break a battle.

Ruffle's verifier rules this code follows: a backward branch must land on an
OP_label; a catch handler starts with an empty scope stack, so a handler that
rejoins the method's code pushes `this` back first; max_stack is computed.
"""

import ast
import re
import struct
import zlib

from swf_abc import Abc, AbcError, Reader, OPCODES, disassemble, u30
from swf_duel_bridge import DO_ABC, assemble, prepend, used_multiname
from swf_range_overlay import OPCODE_BY_NAME, _add_int, _qname

MAX_SUMMONS = 1
SUMMON = 'summon'
KINDS = ('summon', 'heal', 'shield', 'limit', 'whirl', 'area', 'ranged', 'melee', 'other')

TEXTS = {
    'es': {
        'summon': ('Invocación', 'Invoca una unidad aliada que pelea a su lado. Puede tener 1 invocación viva a la vez.'),
        'heal': ('Curación', 'Recupera vida de la unidad o de sus aliados cercanos.'),
        'shield': ('Protección', 'Protege a la unidad: reduce o evita el daño por un tiempo.'),
        'limit': ('Ataque definitivo', 'Se carga peleando; cuando está lleno, lanza un ataque muy fuerte.'),
        'whirl': ('Torbellino', 'Gira y golpea a todos los enemigos que tiene alrededor.'),
        'area': ('Ataque en área', 'Golpea una zona y daña a todos los enemigos que están en ella.'),
        'ranged': ('Ataque a distancia', 'Lanza proyectiles o rayos que dañan a los enemigos desde lejos.'),
        'melee': ('Golpe fuerte', 'Un golpe poderoso contra el enemigo.'),
        'other': ('Habilidad especial', 'Un ataque especial propio de esta unidad.'),
        'auto': 'Se lanza sola en combate cuando termina la recarga.',
        'manual': 'Tiene usos limitados: se usa a mano, haciendo clic.',
        'limit_word': 'Límite',
    },
    'en': {
        'summon': ('Summon', 'Summons an allied unit that fights at its side. It can have 1 summon alive at a time.'),
        'heal': ('Healing', 'Restores life to the unit or its nearby allies.'),
        'shield': ('Protection', 'Protects the unit: it takes less or no damage for a while.'),
        'limit': ('Ultimate attack', 'Charges while fighting; when full, it unleashes a very strong attack.'),
        'whirl': ('Whirlwind', 'Spins and hits every enemy around it.'),
        'area': ('Area attack', 'Strikes an area and damages every enemy in it.'),
        'ranged': ('Ranged attack', 'Shoots projectiles or rays that damage enemies from afar.'),
        'melee': ('Strong hit', 'A powerful blow against the enemy.'),
        'other': ('Special ability', 'A special attack of this unit.'),
        'auto': 'Casts by itself in combat when its cooldown ends.',
        'manual': 'It has limited uses: cast it by hand, with a click.',
        'limit_word': 'Limit',
    },
    'pt-BR': {
        'summon': ('Invocação', 'Invoca uma unidade aliada que luta ao seu lado. Pode ter 1 invocação viva por vez.'),
        'heal': ('Cura', 'Recupera a vida da unidade ou dos aliados próximos.'),
        'shield': ('Proteção', 'Protege a unidade: reduz ou evita o dano por um tempo.'),
        'limit': ('Ataque final', 'Carrega lutando; quando enche, lança um ataque muito forte.'),
        'whirl': ('Redemoinho', 'Gira e atinge todos os inimigos ao redor.'),
        'area': ('Ataque em área', 'Atinge uma área e causa dano a todos os inimigos nela.'),
        'ranged': ('Ataque à distância', 'Lança projéteis ou raios que ferem os inimigos de longe.'),
        'melee': ('Golpe forte', 'Um golpe poderoso contra o inimigo.'),
        'other': ('Habilidade especial', 'Um ataque especial desta unidade.'),
        'auto': 'É lançada sozinha em combate quando a recarga termina.',
        'manual': 'Tem usos limitados: é usada à mão, com um clique.',
        'limit_word': 'Limite',
    },
}

TIP_PREFIX = '<font face="Arial" size="12" color="#2B1A0B">'
TIP_SUFFIX = '</font>'
LABEL_HTML = '<font face="Arial" size="10" color="#FFFFFF"><b>{word} {max}/{max}</b></font>'
TIP_WIDTH = 200
TIP_BACKGROUND = 0xFFF6D8
TIP_BORDER = 0x6B3D16
LABEL_BACKGROUND = 0xB3261E
RED_OFFSETS = (110, -80, -80)  # ColorTransform offsets (red, green, blue) for a limited summon button

SUMMON_CHECKS = {'checkMaxMinions', 'checkMinions', 'maxMinionsToSpawn'}
SUMMON_ACTION = re.compile(r'spawn|minion|dragg|egg|imps|spiders', re.I)
NOT_SUMMON_ACTION = re.compile(r'whirl|tornado', re.I)  # spawnWhirlwind, MAX_WHIRLWIND_TO_SPAWN: whirlwinds, not units
KIND_PATTERNS = (
    ('heal', re.compile(r'heal|cura|moral|endurance|regener', re.I)),
    ('shield', re.compile(r'shield|forcefield|force field|field|roots|protect|invisib|wall|absorb', re.I)),
    ('whirl', re.compile(r'whirl|torbell|spin|girat|tornado|360|culetazo|torning', re.I)),
    ('area', re.compile(r'rain|lluvia|storm|quake|explos|hole|crack|olas|wave|pisoton|ritual|suelo|rage|nightmare|fury|battlecry|shout|galaxy|earth', re.I)),
    ('ranged', re.compile(r'ball|fire|ray|rayo|beam|laser|shoot|lightning|boomerang|breath|skull|soul|poison|oil|anchor|bubble|energy|electric|spear|light', re.I)),
    ('melee', re.compile(r'slash|smash|sword|kick|jump|horn|tail|charge|carga|blow|pincer|golpe|attack|ataque|salto|pectoral|wing', re.I)),
)


def classify(name, thumb, actions, checks):
    """Kind of an ability from its name, thumbnail and the names of its action/check functions."""
    if checks & SUMMON_CHECKS or any(SUMMON_ACTION.search(action) and not NOT_SUMMON_ACTION.search(action) for action in actions):
        return SUMMON
    if 'limit' in name.lower() or any(check.startswith('canDo') for check in checks):
        return 'limit'
    text = ' '.join([name, thumb] + list(actions))
    for kind, pattern in KIND_PATTERNS:
        if pattern.search(text):
            return kind
    return 'other'


def _string(operand):
    """A pushstring operand as the disassembler prints it (a Python literal) -> its text."""
    try:
        value = ast.literal_eval(operand)
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


def ability_table(abc):
    """'name|thumbnail' -> kind, for every ability the game defines."""
    table = {}
    for index in range(len(abc.methods)):
        try:
            ops = disassemble(abc, abc.body_of(index)['code'])
        except Exception:
            continue
        for position, (_, op, operand) in enumerate(ops):
            if op == 'constructprop' and str(operand).startswith('SpecialUnitAttack '):
                start = position
                while start > 0 and not (ops[start][1] == 'findpropstrict' and str(ops[start][2]).startswith('SpecialUnitAttack')):
                    start -= 1
                segment = ops[start + 1:position]
                strings = [_string(x[2]) for x in segment if x[1] == 'pushstring']
                names = [str(x[2]) for x in segment if x[1] in ('getproperty', 'getlex')]
                name, thumb = (strings + ['', ''])[:2]
            elif op == 'constructprop' and str(operand).startswith('SpecialUnitAttackCreator '):
                end = position
                while end < len(ops) and not (ops[end][1].startswith('call') and str(ops[end][2]).startswith('create ')):
                    end += 1
                segment = ops[position:end]
                name = thumb = ''
                for k, (_, sop, sarg) in enumerate(segment):
                    if sop.startswith('call') and str(sarg).startswith('withAttackName') and k and segment[k - 1][1] == 'pushstring':
                        name = _string(segment[k - 1][2]) or ''
                    if sop.startswith('call') and str(sarg).startswith('withImageThumbName') and k and segment[k - 1][1] == 'pushstring':
                        thumb = _string(segment[k - 1][2]) or ''
                names = [str(x[2]) for x in segment if x[1] in ('getproperty', 'getlex', 'constructprop')]
            else:
                continue
            checks = {n.split(' ')[0] for n in names}
            table[f'{name or ""}|{thumb or ""}'] = classify(name or '', thumb or '', [n.split(' ')[0] for n in names], checks)
    return table


def public_late(abc):
    """A run-time multiname (obj[key]) whose namespace set has the public namespace: Array, Vector and Object keys.

    The game's own `getproperty <late>` instructions are not safe to copy: its code is obfuscated with dead
    instructions, and a late name without the public namespace finds nothing in an Array.
    """
    public = lambda namespace: abc.namespaces[namespace - 1][0] in (0x16, 0x08) and abc.string(abc.namespaces[namespace - 1][1]) == ''  # noqa: E731
    for index, entry in enumerate(abc.multinames, 1):
        if entry[0] == 0x1B and any(public(namespace) for namespace in abc.ns_sets[entry[1] - 1]):  # MultinameL
            return index
    namespace = next((i for i in range(1, len(abc.namespaces) + 1) if public(i)), None)
    if namespace is None:
        raise AbcError('No public namespace in the game code')
    abc.ns_sets.append([namespace])
    abc.multinames.append((0x1B, len(abc.ns_sets)))
    return len(abc.multinames)


def _instructions(code):
    r = Reader(code)
    out = []
    while r.pos < len(code):
        offset = r.pos
        op_name, kinds = OPCODES[r.u8()]
        for kind in kinds:
            if kind == 'u8':
                r.u8()
            elif kind == 's24':
                r.s24()
            elif kind == 'switch':
                r.s24()
                for _ in range(r.u30() + 1):
                    r.s24()
            else:
                r.u30()
        out.append((offset, op_name))
    return out


def _insert_before_final_return(body, code):
    at, name = _instructions(body['code'])[-1]
    if name != 'returnvoid':
        raise AbcError('Expected the method to end with returnvoid')
    body['code'] = body['code'][:at] + code + body['code'][at:]
    for exception in body['exceptions']:
        for position in range(3):
            if exception[position] > at:
                exception[position] += len(code)
    return at


BRANCHES_1 = {'iftrue', 'iffalse'}
BRANCHES_2 = {'ifeq', 'ifne', 'iflt', 'ifle', 'ifgt', 'ifge', 'ifnlt', 'ifnle', 'ifngt', 'ifnge', 'ifstricteq', 'ifstrictne'}
PUSHES = {'getlocal0', 'getlocal1', 'getlocal2', 'getlocal3', 'getlocal', 'pushbyte', 'pushshort', 'pushint', 'pushstring',
          'pushtrue', 'pushfalse', 'pushnull', 'pushundefined', 'pushnan', 'getlex', 'findpropstrict', 'findproperty', 'dup',
          'newfunction', 'getglobalscope'}
POPS = {'setlocal0', 'setlocal1', 'setlocal2', 'setlocal3', 'setlocal', 'pop', 'pushscope', 'returnvalue'} | BRANCHES_1
BINARY = {'add', 'subtract', 'multiply', 'divide', 'modulo', 'equals', 'strictequals', 'lessthan', 'lessequals', 'greaterthan',
          'greaterequals', 'add_i', 'subtract_i', 'multiply_i'}
NEUTRAL = {'convert_i', 'convert_d', 'convert_s', 'convert_b', 'coerce_a', 'coerce_s', 'coerce', 'not', 'increment_i',
           'decrement_i', 'increment', 'decrement', 'negate', 'jump', 'returnvoid', 'nop', 'label'}


def max_stack_of(abc, program, handlers=()):
    """Deepest operand stack a program reaches (the verifier rejects a method whose max_stack is smaller).

    `handlers` are labels where an exception handler starts (one value on the stack).
    """
    late = lambda index: abc.multiname_name(index) == '<late>'  # noqa: E731
    depth, deepest, at_label = 0, 0, {label: 1 for label in handlers}
    for item in program:
        op, *operands = item
        if op == 'label:':
            depth = at_label.get(operands[0], depth)
            continue
        if op in PUSHES:
            change = 1
        elif op in POPS:
            change = -1
        elif op in BRANCHES_2:
            change = -2
        elif op in BINARY:
            change = -1
        elif op in NEUTRAL:
            change = 0
        elif op == 'getproperty':
            change = -1 if late(operands[0]) else 0
        elif op in ('setproperty', 'initproperty'):
            change = -3 if late(operands[0]) else -2
        elif op == 'callproperty':
            change = -operands[1]
        elif op == 'callpropvoid':
            change = -operands[1] - 1
        elif op == 'constructprop':
            change = -operands[1]
        elif op == 'newobject':
            change = -2 * operands[0] + 1
        elif op == 'newarray':
            change = -operands[0] + 1
        else:
            raise AbcError(f'max_stack: unknown instruction {op}')
        depth += change
        if depth < 0:
            raise AbcError(f'max_stack: the stack goes below zero at {item}')
        deepest = max(deepest, depth)
        if op in BRANCHES_1 or op in BRANCHES_2 or op == 'jump':
            at_label.setdefault(operands[0], depth)
    return deepest


def guarded_call(code_before_original, original_label='original'):
    """`code` that may throw, then the original method: a failure just skips to the original code."""
    return code_before_original + [('label:', 'try_end'), ('jump', original_label), ('label:', 'catch'), ('pop',),
                                   ('label:', original_label)]


class _Builder:
    """Adds guarded methods and slots to the game's classes."""

    def __init__(self, abc):
        self.abc = abc
        self.debug_names = None  # (ExternalInterface, call) when SE_ABILITIES_DEBUG: caught errors go to the console

    def qname(self, name, package=''):
        try:
            return _qname(self.abc, name, package)
        except AbcError:
            if package:
                raise
            return self.abc.add_qname('', name)

    def method(self, class_name, name, params, program, *, returns=False, max_stack=12, local_count=8, reference=None):
        """A new instance method; `program` runs inside try/catch (a value method returns false on errors)."""
        abc = self.abc
        reference_body = abc.body_of(reference if reference is not None else abc.instances[abc.class_index(class_name)]['iinit'])
        handler = [('getlocal0',), ('pushscope',)]
        locals_needed = max(local_count, params + 1)
        if self.debug_names:
            external, call = self.debug_names
            handler += [('setlocal', locals_needed), ('getlex', external), ('pushstring', abc.add_string('console.log')),
                        ('pushstring', abc.add_string(f'se-ability error {name}')), ('getlocal', locals_needed), ('convert_s',),
                        ('callpropvoid', call, 3)]
            locals_needed += 1
        else:
            handler += [('pop',)]
        handler += [('pushfalse',), ('returnvalue',)] if returns else [('returnvoid',)]
        full = ([('getlocal0',), ('pushscope',), ('label:', 'try')] + program
                + [('label:', 'try_end')] + ([] if returns else [('jump', 'done')])
                + [('label:', 'catch')] + handler + ([] if returns else [('label:', 'done'), ('returnvoid',)]))
        code, labels = assemble(full)
        max_stack = max_stack_of(abc, full, handlers=('catch',)) + 1
        index = len(abc.methods)
        abc.methods.append({'return_type': 0, 'param_types': [0] * params, 'name': abc.add_string(name), 'flags': 0,
                            'options': None, 'param_names': None})
        abc.bodies.append({'method': index, 'max_stack': max_stack, 'local_count': locals_needed,
                           'init_scope_depth': reference_body['init_scope_depth'],
                           'max_scope_depth': reference_body['init_scope_depth'] + 1,
                           'code': code, 'exceptions': [[labels['try'], labels['try_end'], labels['catch'], 0, 0]],
                           'traits': []})
        qname = abc.add_qname('', name)
        abc.instances[abc.class_index(class_name)]['traits'].append({'name': qname, 'kind': 1, 'data': [0, index], 'metadata': None})
        return qname

    def slot(self, class_name, name, static=False):
        qname = self.abc.add_qname('', name)
        target = self.abc.classes[self.abc.class_index(class_name)][1] if static else self.abc.instances[self.abc.class_index(class_name)]['traits']
        target.append({'name': qname, 'kind': 0, 'data': [0, 0, 0], 'metadata': None})
        return qname


def add_unit_abilities_to_abc(abc, language='es', debug=False):
    texts = TEXTS.get(language, TEXTS['es'])
    if any(abc.multiname_name(t['name']) == '__abilityTick' for t in abc.instances[abc.class_index('IsoSpecialUnit')]['traits']):
        raise AbcError('The unit abilities are already present')
    table = ability_table(abc)
    if len(table) < 50:
        raise AbcError('Unit abilities not found')
    b = _Builder(abc)
    m = {}
    tick = abc.method_of('IsoSpecialUnit', 'tTick')
    do_attack = abc.method_of('IsoSpecialUnit', 'doAttack')
    click = abc.method_of('PortraitSpecialAttack', 'clickItem')
    update_state = abc.method_of('PortraitSpecialAttack', 'updateState')
    cast = abc.method_of('RecuadroInfo', 'castSpecialAttacks')
    m.update(
        state=used_multiname(abc, tick, 'getproperty', 'state'),
        IDLE=used_multiname(abc, tick, 'getproperty', 'SU_STATE_IDLE'),
        ISU=used_multiname(abc, tick, 'getlex', 'IsoSpecialUnit'),
        bDead=used_multiname(abc, tick, 'getproperty', 'bDead'),
        bIsExpired=used_multiname(abc, tick, 'getproperty', 'bIsExpired'),
        arAttacks=used_multiname(abc, do_attack, 'getproperty', 'arAttacks'),
        late=public_late(abc),
        getAttacks=used_multiname(abc, abc.method_of('RecuadroInfo', 'addSpecialAttacksInRecuadro'), 'callproperty', 'getAttacks'),
        getAttack=used_multiname(abc, abc.method_of('PortraitSpecialAttack', 'updateAttacks'), 'callproperty', 'getAttack'),
        numAttacks=used_multiname(abc, do_attack, 'getproperty', 'numAttacks'),
        minionsAlive=used_multiname(abc, abc.method_of('IsoSpecialUnit', 'checkMaxMinions'), 'getproperty', 'minionsAlive'),
        TargetElement=used_multiname(abc, abc.method_of('IsoSpecialUnit', 'hasTarget'), 'getlex', 'TargetElement'),
        targetDead=used_multiname(abc, abc.method_of('IsoSpecialUnit', 'hasTarget'), 'getproperty', 'bDead'),
        doAttack=used_multiname(abc, click, 'callproperty', 'doAttack'),
        id=used_multiname(abc, click, 'getproperty', 'id'),
        castTime=used_multiname(abc, click, 'getproperty', 'castTime'),
        coolDown=used_multiname(abc, click, 'getproperty', 'coolDown'),
        Base=used_multiname(abc, click, 'getlex', 'Base'),
        Gui=used_multiname(abc, click, 'getproperty', 'Gui'),
        recuadroInfo=used_multiname(abc, click, 'getproperty', 'recuadroInfo'),
        castSpecialAttacks=used_multiname(abc, click, 'callpropvoid', 'castSpecialAttacks'),
        eElement=used_multiname(abc, click, 'getproperty', 'eElement'),
        oAttack=used_multiname(abc, click, 'getproperty', 'oAttack'),
        attackName=used_multiname(abc, click, 'getproperty', 'attackName'),
        vSpecialAttacks=used_multiname(abc, cast, 'getproperty', 'vSpecialAttacks'),
        length=used_multiname(abc, cast, 'getproperty', 'length'),
        spState=used_multiname(abc, update_state, 'getproperty', 'spState'),
        portraitISU=used_multiname(abc, update_state, 'getlex', 'IsoSpecialUnit'),
        portraitIDLE=used_multiname(abc, update_state, 'getproperty', 'SU_STATE_IDLE'),
    )
    m['imgThumb'] = b.qname('imgThumb')
    for name, package in (('TextField', 'flash.text'), ('ColorTransform', 'flash.geom'), ('Point', 'flash.geom'),
                          ('MouseEvent', 'flash.events'), ('Event', 'flash.events'), ('ExternalInterface', 'flash.external')):
        m[name] = b.qname(name, package)
    for name in ('htmlText', 'autoSize', 'wordWrap', 'multiline', 'width', 'height', 'background', 'backgroundColor',
                 'border', 'borderColor', 'selectable', 'mouseEnabled', 'x', 'y', 'stage', 'addChild', 'removeChild',
                 'localToGlobal', 'addEventListener', 'transform', 'colorTransform', 'visible', 'parent', 'ROLL_OVER',
                 'ROLL_OUT', 'REMOVED_FROM_STAGE', 'call', 'available'):
        m[name] = b.qname(name)
    s = lambda text: abc.add_string(text)  # noqa: E731
    if debug:
        b.debug_names = (m['ExternalInterface'], m['call'])
    integer = lambda value: _add_int(abc, value)  # noqa: E731

    # -- IsoSpecialUnit: the kinds table and the texts --
    table_slot = b.slot('IsoSpecialUnit', '__abilityKinds', static=True)
    texts_slot = b.slot('IsoSpecialUnit', '__abilityTexts', static=True)
    b.slot('IsoSpecialUnit', '__autoNext')
    kinds_object = []
    for key, kind in sorted(table.items()):
        kinds_object += [('pushstring', s(key)), ('pushstring', s(kind))]
    texts_object = []
    for kind in KINDS:
        title, description = texts[kind]
        texts_object += [('pushstring', s(kind)), ('pushstring', s(f'<b>{title}</b><br>{description}'))]
    kind_name = b.method('IsoSpecialUnit', '__abilityKind', 1, [
        ('getlex', m['ISU']), ('getproperty', table_slot), ('iftrue', 'ready'),
        ('getlex', m['ISU'])] + kinds_object + [('newobject', len(table)), ('setproperty', table_slot),
        ('getlex', m['ISU'])] + texts_object + [('newobject', len(KINDS)), ('setproperty', texts_slot),
        ('label:', 'ready'),
        ('getlex', m['ISU']), ('getproperty', table_slot),
        ('getlocal1',), ('getproperty', m['attackName']), ('pushstring', s('|')), ('add',),
        ('getlocal1',), ('getproperty', m['imgThumb']), ('add',),
        ('getproperty', m['late']), ('setlocal2',),
        ('getlocal2',), ('iftrue', 'found'), ('pushstring', s('other')), ('returnvalue',),
        ('label:', 'found'), ('getlocal2',), ('returnvalue',),
    ], returns=True, max_stack=2 * len(table) + 6, local_count=3, reference=do_attack)
    is_summon = b.method('IsoSpecialUnit', '__isSummon', 1, [
        ('getlocal0',), ('getlocal1',), ('callproperty', kind_name, 1), ('pushstring', s(SUMMON)), ('equals',), ('returnvalue',),
    ], returns=True, max_stack=4, local_count=2, reference=do_attack)
    b.method('IsoSpecialUnit', '__tipHtml', 1, [
        ('getlocal0',), ('getlocal1',), ('callproperty', kind_name, 1), ('setlocal2',),
        ('getlex', m['ISU']), ('getproperty', texts_slot), ('getlocal2',), ('getproperty', m['late']), ('setlocal3',),
        ('getlocal2',), ('pushstring', s(SUMMON)), ('ifne', 'auto'),
        ('getlocal3',), ('pushstring', s(f'<br><b>{texts["limit_word"]} ')), ('add',),
        ('getlocal0',), ('getproperty', m['minionsAlive']), ('convert_i',), ('add',),
        ('pushstring', s(f'/{MAX_SUMMONS}</b>')), ('add',), ('setlocal3',),
        ('label:', 'auto'),
        # only unlimited abilities (numAttacks -1) are cast automatically; the others stay manual
        ('pushstring', s(f'<br><i>{texts["auto"]}</i>')), ('setlocal2',),
        ('getlocal1',), ('getproperty', m['numAttacks']), ('pushbyte', 255), ('ifeq', 'note'),
        ('pushstring', s(f'<br><i>{texts["manual"]}</i>')), ('setlocal2',),
        ('label:', 'note'),
        ('pushstring', s(TIP_PREFIX)), ('getlocal3',), ('add',), ('getlocal2',), ('add',), ('pushstring', s(TIP_SUFFIX)), ('add',),
        ('returnvalue',),
    ], returns=True, max_stack=6, local_count=4, reference=do_attack)
    summon_blocked = b.method('IsoSpecialUnit', '__summonBlocked', 1, [
        ('getlocal0',), ('getlocal1',), ('callproperty', m['getAttack'], 1), ('setlocal2',),
        ('getlocal2',), ('iffalse', 'no'),
        ('getlocal0',), ('getlocal2',), ('callproperty', is_summon, 1), ('iffalse', 'no'),
        ('getlocal0',), ('getproperty', m['minionsAlive']), ('pushbyte', MAX_SUMMONS), ('greaterequals',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',),
    ], returns=True, max_stack=4, local_count=3, reference=do_attack)

    # RecuadroInfo shows this unit? (its first ability button belongs to it)
    shown_in = b.method('IsoSpecialUnit', '__shownIn', 1, [
        ('getlocal1',), ('iffalse', 'no'),
        ('getlocal1',), ('getproperty', m['vSpecialAttacks']), ('setlocal2',),
        ('getlocal2',), ('iffalse', 'no'),
        ('getlocal2',), ('getproperty', m['length']), ('pushbyte', 0), ('ifngt', 'no'),
        ('getlocal2',), ('pushbyte', 0), ('getproperty', m['late']), ('setlocal3',),
        ('getlocal3',), ('iffalse', 'no'),
        ('getlocal3',), ('getproperty', m['eElement']), ('getlocal0',), ('strictequals',), ('returnvalue',),
        ('label:', 'no'), ('pushfalse',), ('returnvalue',),
    ], returns=True, max_stack=4, local_count=4, reference=do_attack)
    recuadro = [('getlex', m['Base']), ('getproperty', m['Gui']), ('getproperty', m['recuadroInfo'])]
    notify = b.method('IsoSpecialUnit', '__notifyCast', 1, recuadro + [('setlocal2',),
        ('getlocal0',), ('getlocal2',), ('callproperty', shown_in, 1), ('iffalse', 'done'),
        ('getlocal2',), ('getlocal1',), ('getproperty', m['castTime']), ('getlocal1',), ('getproperty', m['coolDown']),
        ('callpropvoid', m['castSpecialAttacks'], 2),
    ], max_stack=4, local_count=3, reference=do_attack)
    limit_view = abc.add_qname('', '__limitView')  # PortraitSpecialAttack method, defined below
    refresh = b.method('IsoSpecialUnit', '__refreshPortraits', 0, recuadro + [('setlocal1',),
        ('getlocal0',), ('getlocal1',), ('callproperty', shown_in, 1), ('iffalse', 'done'),
        ('getlocal1',), ('getproperty', m['vSpecialAttacks']), ('setlocal2',),
        ('pushbyte', 0), ('setlocal3',),
        ('label:', 'loop'), ('label',),  # a backward branch must land on an OP_label
        ('getlocal3',), ('getlocal2',), ('getproperty', m['length']), ('ifnlt', 'done'),
        ('getlocal2',), ('getlocal3',), ('getproperty', m['late']), ('setlocal', 4),
        ('getlocal', 4), ('iffalse', 'next'),
        ('getlocal', 4), ('callpropvoid', limit_view, 0),
        ('label:', 'next'),
        ('getlocal3',), ('increment_i',), ('setlocal3',), ('jump', 'loop'),
    ], max_stack=4, local_count=5, reference=do_attack)
    auto_next = abc.add_qname('', '__autoNext')
    auto_cast = b.method('IsoSpecialUnit', '__autoCast', 0, [
        ('getlocal0',), ('getproperty', m['arAttacks']), ('setlocal', 5),
        ('getlocal', 5), ('iffalse', 'done'),
        ('getlocal', 5), ('getproperty', m['length']), ('convert_i',), ('setlocal1',),
        ('pushbyte', 0), ('setlocal2',),
        ('label:', 'loop'), ('label',),  # a backward branch must land on an OP_label
        ('getlocal2',), ('getlocal1',), ('ifnlt', 'done'),
        ('getlocal0',), ('getproperty', auto_next), ('convert_i',), ('getlocal2',), ('add',), ('getlocal1',), ('modulo',),
        ('convert_i',), ('setlocal3',),
        ('getlocal', 5), ('getlocal3',), ('getproperty', m['late']), ('setlocal', 4),
        ('getlocal', 4), ('iffalse', 'next'),
        ('getlocal', 4), ('getproperty', m['numAttacks']), ('pushbyte', 255), ('ifne', 'next'),  # unlimited uses (-1)
        ('getlocal0',), ('getlocal', 4), ('getproperty', m['id']), ('callproperty', m['doAttack'], 1), ('iffalse', 'next'),
        ('getlocal0',), ('getlocal3',), ('pushbyte', 1), ('add',), ('convert_i',), ('setproperty', auto_next),
        ('getlocal0',), ('getlocal', 4), ('callpropvoid', notify, 1),
    ] + ([  # SE_ABILITIES_DEBUG: every automatic cast is written to the browser console
        ('getlex', m['ExternalInterface']), ('getproperty', m['available']), ('iffalse', 'done'),
        ('getlex', m['ExternalInterface']), ('pushstring', s('console.log')), ('pushstring', s('se-ability cast')),
        ('getlocal', 4), ('getproperty', m['attackName']), ('getlocal0',), ('getproperty', m['minionsAlive']),
        ('callpropvoid', m['call'], 4),
    ] if debug else []) + [
        ('jump', 'done'),
        ('label:', 'next'),
        ('getlocal2',), ('increment_i',), ('setlocal2',), ('jump', 'loop'),
    ], max_stack=4, local_count=6, reference=do_attack)
    ability_tick = b.method('IsoSpecialUnit', '__abilityTick', 0, [
        ('getlocal0',), ('getproperty', m['bDead']), ('iftrue', 'done'),
        ('getlocal0',), ('getproperty', m['bIsExpired']), ('iftrue', 'done'),
        ('getlocal0',), ('getproperty', m['state']), ('getlex', m['ISU']), ('getproperty', m['IDLE']), ('ifne', 'refresh'),
        # in combat: the unit is attacking (bAttacking; TargetElement stays empty in the arena)
        ('getlocal0',), ('getproperty', b.qname('bAttacking')), ('iffalse', 'refresh'),
        ('getlocal0',), ('callpropvoid', auto_cast, 0),
        ('label:', 'refresh'),
        ('getlocal0',), ('callpropvoid', refresh, 0),
    ], max_stack=3, local_count=2, reference=do_attack)

    # tTick: the ability step first; doAttack: no summon over the limit.
    def guarded_prepend(method, program, tag='guard'):
        body = abc.body_of(method)
        full = [('label:', 'try')] + guarded_call(program)
        if debug:  # the guard writes what it caught to the browser console
            spare = body['local_count']
            body['local_count'] += 1
            catch = full.index(('label:', 'catch'))
            full[catch + 1:catch + 2] = [('setlocal', spare), ('getlex', m['ExternalInterface']), ('pushstring', s('console.log')),
                                         ('pushstring', s(f'se-ability error {tag}')), ('getlocal', spare), ('convert_s',),
                                         ('callpropvoid', m['call'], 3)]
        code, labels = assemble(full)
        prepend(body, code, exceptions=[[labels['try'], labels['try_end'], labels['catch'], 0, 0]])
        body['max_stack'] = max(body['max_stack'], max_stack_of(abc, full, handlers=('catch',)) + 1)

    guarded_prepend(tick, [('getlocal0',), ('callpropvoid', ability_tick, 0)], 'guard tTick')
    guarded_prepend(do_attack, [('getlocal0',), ('getlocal1',), ('callproperty', summon_blocked, 1), ('iffalse', 'original'),
                                ('pushfalse',), ('returnvalue',)], 'guard doAttack')

    # Shared spawn routines: one unit at most.
    for method in (abc.method_of('IsoSpecialUnit', 'spawnMinionFromEgg'), abc.method_of('IsoSpecialUnit', 'spawnMinion')):
        guarded_prepend(method, [('getlocal0',), ('getproperty', m['minionsAlive']), ('pushbyte', MAX_SUMMONS), ('iflt', 'original'),
                                 ('returnvoid',)], 'guard spawn')
    guarded_prepend(abc.method_of('AbstractDelegate', 'spawnMinions'),
                    [('getlocal2',), ('pushbyte', MAX_SUMMONS), ('ifngt', 'original'), ('pushbyte', MAX_SUMMONS), ('setlocal2',)],
                    'guard spawnMinions')

    # -- PortraitSpecialAttack: tooltip and the red "Limit 1/1" --
    tip_slot = b.slot('PortraitSpecialAttack', '__tip')
    label_slot = b.slot('PortraitSpecialAttack', '__label')
    red_slot = b.slot('PortraitSpecialAttack', '__red')
    text_field = lambda local: [  # noqa: E731
        ('findpropstrict', m['TextField']), ('constructprop', m['TextField'], 0), ('coerce_a',), ('setlocal', local),
        ('getlocal', local), ('pushfalse',), ('setproperty', m['selectable']),
        ('getlocal', local), ('pushfalse',), ('setproperty', m['mouseEnabled']),
        ('getlocal', local), ('pushtrue',), ('setproperty', m['background']),
    ]
    out = b.method('PortraitSpecialAttack', '__tipOut', 1, [
        ('getlocal0',), ('getproperty', tip_slot), ('setlocal2',),
        ('getlocal2',), ('iffalse', 'clear'),
        ('getlocal2',), ('getproperty', m['parent']), ('iffalse', 'clear'),
        ('getlocal2',), ('getproperty', m['parent']), ('getlocal2',), ('callpropvoid', m['removeChild'], 1),
        ('label:', 'clear'),
        ('getlocal0',), ('pushnull',), ('setproperty', tip_slot),
    ], max_stack=3, local_count=3, reference=click)
    over = b.method('PortraitSpecialAttack', '__tipOver', 1, [
        ('getlocal0',), ('pushnull',), ('callpropvoid', out, 1),
        ('getlocal0',), ('getproperty', m['eElement']), ('getlocal0',), ('getproperty', m['oAttack']),
        ('callproperty', abc.add_qname('', '__tipHtml'), 1), ('setlocal2',),
    ] + text_field(3) + [
        ('getlocal3',), ('pushtrue',), ('setproperty', m['wordWrap']),
        ('getlocal3',), ('pushtrue',), ('setproperty', m['multiline']),
        ('getlocal3',), ('pushshort', TIP_WIDTH), ('setproperty', m['width']),
        ('getlocal3',), ('pushstring', s('left')), ('setproperty', m['autoSize']),
        ('getlocal3',), ('pushint', integer(TIP_BACKGROUND)), ('setproperty', m['backgroundColor']),
        ('getlocal3',), ('pushtrue',), ('setproperty', m['border']),
        ('getlocal3',), ('pushint', integer(TIP_BORDER)), ('setproperty', m['borderColor']),
        ('getlocal3',), ('getlocal2',), ('setproperty', m['htmlText']),
        ('getlocal0',), ('findpropstrict', m['Point']), ('pushbyte', 0), ('pushbyte', 0), ('constructprop', m['Point'], 2),
        ('callproperty', m['localToGlobal'], 1), ('setlocal', 4),
        # to the left of the button group, bottoms aligned: over the panel's empty middle, not over the other buttons
        ('getlocal3',), ('getlocal0',), ('getproperty', m['parent']), ('findpropstrict', m['Point']), ('pushbyte', 0), ('pushbyte', 0),
        ('constructprop', m['Point'], 2), ('callproperty', m['localToGlobal'], 1), ('getproperty', m['x']),
        ('pushshort', TIP_WIDTH + 6), ('subtract',), ('setproperty', m['x']),
        ('getlocal3',), ('getlocal', 4), ('getproperty', m['y']), ('getlocal0',), ('getproperty', m['height']), ('add',),
        ('getlocal3',), ('getproperty', m['height']), ('subtract',), ('setproperty', m['y']),
        ('getlocal3',), ('getproperty', m['y']), ('pushbyte', 0), ('ifnlt', 'placed'),
        ('getlocal3',), ('pushbyte', 0), ('setproperty', m['y']),
        ('label:', 'placed'),
        ('getlocal0',), ('getproperty', m['stage']), ('getlocal3',), ('callpropvoid', m['addChild'], 1),
        ('getlocal0',), ('getlocal3',), ('setproperty', tip_slot),
    ], max_stack=6, local_count=5, reference=click)
    hook = b.method('PortraitSpecialAttack', '__tipHook', 0, [
        ('getlocal0',), ('getlex', m['MouseEvent']), ('getproperty', m['ROLL_OVER']), ('getlocal0',), ('getproperty', over),
        ('callpropvoid', m['addEventListener'], 2),
        ('getlocal0',), ('getlex', m['MouseEvent']), ('getproperty', m['ROLL_OUT']), ('getlocal0',), ('getproperty', out),
        ('callpropvoid', m['addEventListener'], 2),
        ('getlocal0',), ('getlex', m['Event']), ('getproperty', m['REMOVED_FROM_STAGE']), ('getlocal0',), ('getproperty', out),
        ('callpropvoid', m['addEventListener'], 2),
    ], max_stack=4, local_count=1, reference=click)
    color = lambda offsets: [  # noqa: E731
        ('getlocal0',), ('getproperty', m['transform']),
        ('findpropstrict', m['ColorTransform']), ('pushbyte', 1), ('pushbyte', 1), ('pushbyte', 1), ('pushbyte', 1),
        ('pushbyte', offsets[0] & 0xFF), ('pushbyte', offsets[1] & 0xFF), ('pushbyte', offsets[2] & 0xFF), ('pushbyte', 0),
        ('constructprop', m['ColorTransform'], 8), ('setproperty', m['colorTransform']),
    ]
    b.method('PortraitSpecialAttack', '__limitView', 0, [
        ('getlocal0',), ('getproperty', m['eElement']), ('setlocal1',),
        ('getlocal1',), ('getlocal0',), ('getproperty', m['oAttack']), ('callproperty', is_summon, 1), ('iffalse', 'off'),
        ('getlocal1',), ('getproperty', m['minionsAlive']), ('pushbyte', MAX_SUMMONS), ('iflt', 'off'),
        ('getlocal1',), ('getproperty', m['spState']), ('getlex', m['portraitISU']), ('getproperty', m['portraitIDLE']), ('ifne', 'off'),
        # limited: the red label, created once
        ('getlocal0',), ('getproperty', label_slot), ('iftrue', 'has_label'),
    ] + text_field(2) + [
        ('getlocal2',), ('pushstring', s('left')), ('setproperty', m['autoSize']),
        ('getlocal2',), ('pushint', integer(LABEL_BACKGROUND)), ('setproperty', m['backgroundColor']),
        ('getlocal2',), ('pushstring', s(LABEL_HTML.format(word=texts['limit_word'], max=MAX_SUMMONS))), ('setproperty', m['htmlText']),
        ('getlocal2',), ('pushbyte', 2), ('setproperty', m['x']),
        ('getlocal2',), ('pushbyte', 2), ('setproperty', m['y']),
        ('getlocal0',), ('getlocal2',), ('callpropvoid', m['addChild'], 1),
        ('getlocal0',), ('getlocal2',), ('setproperty', label_slot),
        ('label:', 'has_label'),
        ('getlocal0',), ('getproperty', label_slot), ('pushtrue',), ('setproperty', m['visible']),
        ('getlocal0',), ('getproperty', red_slot), ('iftrue', 'done'),
    ] + color(RED_OFFSETS) + [
        ('getlocal0',), ('pushtrue',), ('setproperty', red_slot),
        ('jump', 'done'),
        ('label:', 'off'),
        ('getlocal0',), ('getproperty', label_slot), ('iffalse', 'no_label'),
        ('getlocal0',), ('getproperty', label_slot), ('pushfalse',), ('setproperty', m['visible']),
        ('label:', 'no_label'),
        ('getlocal0',), ('getproperty', red_slot), ('iffalse', 'done'),
    ] + color((0, 0, 0)) + [
        ('getlocal0',), ('pushfalse',), ('setproperty', red_slot),
    ], max_stack=12, local_count=3, reference=click)

    # PortraitSpecialAttack's constructor: listen for the mouse.
    body = abc.body_of(abc.instances[abc.class_index('PortraitSpecialAttack')]['iinit'])
    # a caught exception empties the scope stack; the handler puts `this` back so both paths meet at depth 1
    handler = [('pop',)]
    if debug:  # SE_ABILITIES_DEBUG: what the handler caught goes to the browser console
        handler = [('setlocal', body['local_count']), ('getlex', m['ExternalInterface']), ('pushstring', s('console.log')),
                   ('pushstring', s('se-ability error portrait')), ('getlocal', body['local_count']), ('convert_s',),
                   ('callpropvoid', m['call'], 3)]
        body['local_count'] += 1
    full = [('label:', 'try'), ('getlocal0',), ('callpropvoid', hook, 0), ('label:', 'try_end'), ('jump', 'after'),
            ('label:', 'catch'), ('getlocal0',), ('pushscope',)] + handler + [('label:', 'after')]
    code, labels = assemble(full)
    at = _insert_before_final_return(body, code)
    body['exceptions'].append([at + labels['try'], at + labels['try_end'], at + labels['catch'], 0, 0])
    body['max_stack'] = max(body['max_stack'], 5)
    return abc


def add_unit_abilities(data, language='es', debug=False):
    """Return the movie with automatic abilities, the summon limit and ability tooltips."""
    from swf_localization import decode_swf, encode_tag, iter_tags
    body, header_length = decode_swf(data)
    tags = []
    count = 0
    for code, payload, long_length in iter_tags(body, header_length):
        if code == DO_ABC:
            count += 1
            offset = payload.index(b'\0', 4) + 1
            abc = Abc(payload[offset:])
            payload = payload[:offset] + add_unit_abilities_to_abc(abc, language, debug).serialize()
        tags.append(encode_tag(code, payload, long_length))
    if count != 1:
        raise AbcError('Expected exactly one DoABC tag')
    patched = body[:header_length] + b''.join(tags)
    header = data[:4] + struct.pack('<I', len(patched) + 8)
    return header + (zlib.compress(patched) if data[:3] == b'CWS' else patched)
