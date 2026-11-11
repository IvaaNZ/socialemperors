"""Read, edit and write the game's ActionScript 3 bytecode (one DoABC block).

The parser keeps every structure needed to serialize the block again byte for
byte; `serialize(parse(abc)) == abc` is checked before any edit is trusted.
Edits supported here are the ones the server needs: appending constant-pool
entries (strings, namespaces, multinames) and replacing a method body's code
while shifting its exception table. Method bodies refer to everything by index,
so appending to the pools never changes the meaning of existing code.
The opcode table follows the AVM2 Overview (Adobe, 2007).
"""

import struct


class AbcError(ValueError):
    """The bytecode is not in the expected format."""


class Reader:
    def __init__(self, data, pos=0):
        self.data, self.pos = data, pos

    def u8(self):
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self):
        value = struct.unpack_from('<H', self.data, self.pos)[0]
        self.pos += 2
        return value

    def s24(self):
        value = int.from_bytes(self.data[self.pos:self.pos + 3], 'little', signed=True)
        self.pos += 3
        return value

    def u30(self):
        value = shift = 0
        for _ in range(5):
            byte = self.data[self.pos]
            self.pos += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
        raise AbcError('Invalid variable-length integer')

    def raw(self, count):
        value = self.data[self.pos:self.pos + count]
        if len(value) != count:
            raise AbcError('Truncated bytecode')
        self.pos += count
        return value


def u30(value):
    if value < 0:
        raise AbcError('Negative u30')
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def s24(value):
    return value.to_bytes(3, 'little', signed=True)


# --- constant pool -----------------------------------------------------------

QNAME_KINDS = (0x07, 0x0D)
RTQNAME_KINDS = (0x0F, 0x10)
RTQNAMEL_KINDS = (0x11, 0x12)
MULTINAME_KINDS = (0x09, 0x0E)
MULTINAMEL_KINDS = (0x1B, 0x1C)
TYPENAME_KIND = 0x1D
PACKAGE_NAMESPACE = 0x16


class Abc:
    """Parsed ABC. Pools keep raw entries; index 0 is the implicit entry."""

    def __init__(self, data):
        r = Reader(data)
        self.minor, self.major = r.u16(), r.u16()
        # Integer pools: keep each entry's raw encoding for an exact round trip.
        self.ints = self._raw_varints(r)
        self.uints = self._raw_varints(r)
        count = r.u30()
        self.doubles = [r.raw(8) for _ in range(max(count - 1, 0))]
        count = r.u30()
        self.strings = []
        for _ in range(max(count - 1, 0)):
            length = r.u30()
            self.strings.append(r.raw(length).decode('utf-8', errors='surrogateescape'))
        count = r.u30()
        self.namespaces = [(r.u8(), r.u30()) for _ in range(max(count - 1, 0))]
        count = r.u30()
        self.ns_sets = []
        for _ in range(max(count - 1, 0)):
            self.ns_sets.append([r.u30() for _ in range(r.u30())])
        count = r.u30()
        self.multinames = [self._read_multiname(r) for _ in range(max(count - 1, 0))]
        # Everything after the constant pool is kept as parsed structures.
        self.methods = [self._read_method(r) for _ in range(r.u30())]
        self.metadata = []
        for _ in range(r.u30()):
            name = r.u30()
            self.metadata.append((name, [(r.u30(), r.u30()) for _ in range(r.u30())]))
        class_count = r.u30()
        self.instances = [self._read_instance(r) for _ in range(class_count)]
        self.classes = [(r.u30(), self._read_traits(r)) for _ in range(class_count)]
        self.scripts = [(r.u30(), self._read_traits(r)) for _ in range(r.u30())]
        self.bodies = [self._read_body(r) for _ in range(r.u30())]
        if r.pos != len(data):
            raise AbcError('Unexpected data after the method bodies')

    # -- readers --
    @staticmethod
    def _raw_varints(r):
        count = r.u30()
        entries = []
        for _ in range(max(count - 1, 0)):
            start = r.pos
            r.u30()
            entries.append(r.data[start:r.pos])
        return entries

    @staticmethod
    def _read_multiname(r):
        kind = r.u8()
        if kind in QNAME_KINDS:
            return (kind, r.u30(), r.u30())
        if kind in RTQNAME_KINDS:
            return (kind, r.u30())
        if kind in RTQNAMEL_KINDS:
            return (kind,)
        if kind in MULTINAME_KINDS:
            return (kind, r.u30(), r.u30())
        if kind in MULTINAMEL_KINDS:
            return (kind, r.u30())
        if kind == TYPENAME_KIND:
            name = r.u30()
            return (kind, name, tuple(r.u30() for _ in range(r.u30())))
        raise AbcError(f'Unknown multiname kind {kind:#x}')

    @staticmethod
    def _read_method(r):
        param_count = r.u30()
        method = {'return_type': r.u30(), 'param_types': [r.u30() for _ in range(param_count)],
                  'name': r.u30(), 'flags': r.u8(), 'options': None, 'param_names': None}
        if method['flags'] & 0x08:
            method['options'] = [(r.u30(), r.u8()) for _ in range(r.u30())]
        if method['flags'] & 0x80:
            method['param_names'] = [r.u30() for _ in range(param_count)]
        return method

    def _read_traits(self, r):
        traits = []
        for _ in range(r.u30()):
            name, kind = r.u30(), r.u8()
            base = kind & 0x0F
            if base in (0, 6):
                data = [r.u30(), r.u30()]
                vindex = r.u30()
                data.append(vindex)
                if vindex:
                    data.append(r.u8())
            elif base in (1, 2, 3, 4, 5):
                data = [r.u30(), r.u30()]
            else:
                raise AbcError(f'Unknown trait kind {kind:#x}')
            metadata = [r.u30() for _ in range(r.u30())] if kind & 0x40 else None
            traits.append({'name': name, 'kind': kind, 'data': data, 'metadata': metadata})
        return traits

    def _read_instance(self, r):
        instance = {'name': r.u30(), 'super': r.u30(), 'flags': r.u8(), 'protected_ns': None}
        if instance['flags'] & 0x08:
            instance['protected_ns'] = r.u30()
        instance['interfaces'] = [r.u30() for _ in range(r.u30())]
        instance['iinit'] = r.u30()
        instance['traits'] = self._read_traits(r)
        return instance

    def _read_body(self, r):
        body = {'method': r.u30(), 'max_stack': r.u30(), 'local_count': r.u30(),
                'init_scope_depth': r.u30(), 'max_scope_depth': r.u30()}
        body['code'] = r.raw(r.u30())
        body['exceptions'] = [[r.u30() for _ in range(5)] for _ in range(r.u30())]
        body['traits'] = self._read_traits(r)
        return body

    # -- writers --
    def serialize(self):
        out = bytearray(struct.pack('<HH', self.minor, self.major))
        for pool in (self.ints, self.uints):
            out += u30(len(pool) + 1 if pool else 0)
            for entry in pool:
                out += entry
        out += u30(len(self.doubles) + 1 if self.doubles else 0)
        for entry in self.doubles:
            out += entry
        out += u30(len(self.strings) + 1 if self.strings else 0)
        for text in self.strings:
            encoded = text.encode('utf-8', errors='surrogateescape')
            out += u30(len(encoded)) + encoded
        out += u30(len(self.namespaces) + 1 if self.namespaces else 0)
        for kind, name in self.namespaces:
            out += bytes([kind]) + u30(name)
        out += u30(len(self.ns_sets) + 1 if self.ns_sets else 0)
        for entry in self.ns_sets:
            out += u30(len(entry)) + b''.join(u30(value) for value in entry)
        out += u30(len(self.multinames) + 1 if self.multinames else 0)
        for entry in self.multinames:
            out += bytes([entry[0]])
            if entry[0] == TYPENAME_KIND:
                out += u30(entry[1]) + u30(len(entry[2])) + b''.join(u30(v) for v in entry[2])
            else:
                out += b''.join(u30(value) for value in entry[1:])
        out += u30(len(self.methods))
        for method in self.methods:
            out += u30(len(method['param_types'])) + u30(method['return_type'])
            out += b''.join(u30(value) for value in method['param_types'])
            out += u30(method['name']) + bytes([method['flags']])
            if method['flags'] & 0x08:
                out += u30(len(method['options']))
                for value, kind in method['options']:
                    out += u30(value) + bytes([kind])
            if method['flags'] & 0x80:
                out += b''.join(u30(value) for value in method['param_names'])
        out += u30(len(self.metadata))
        for name, items in self.metadata:
            out += u30(name) + u30(len(items)) + b''.join(u30(k) + u30(v) for k, v in items)
        out += u30(len(self.instances))
        for instance in self.instances:
            out += u30(instance['name']) + u30(instance['super']) + bytes([instance['flags']])
            if instance['flags'] & 0x08:
                out += u30(instance['protected_ns'])
            out += u30(len(instance['interfaces'])) + b''.join(u30(v) for v in instance['interfaces'])
            out += u30(instance['iinit']) + self._traits_bytes(instance['traits'])
        for cinit, traits in self.classes:
            out += u30(cinit) + self._traits_bytes(traits)
        out += u30(len(self.scripts))
        for init, traits in self.scripts:
            out += u30(init) + self._traits_bytes(traits)
        out += u30(len(self.bodies))
        for body in self.bodies:
            for key in ('method', 'max_stack', 'local_count', 'init_scope_depth', 'max_scope_depth'):
                out += u30(body[key])
            out += u30(len(body['code'])) + body['code']
            out += u30(len(body['exceptions']))
            for exception in body['exceptions']:
                out += b''.join(u30(value) for value in exception)
            out += self._traits_bytes(body['traits'])
        return bytes(out)

    @staticmethod
    def _traits_bytes(traits):
        out = bytearray(u30(len(traits)))
        for trait in traits:
            out += u30(trait['name']) + bytes([trait['kind']])
            data = trait['data']
            if trait['kind'] & 0x0F in (0, 6):
                out += u30(data[0]) + u30(data[1]) + u30(data[2])
                if data[2]:
                    out.append(data[3])
            else:
                out += u30(data[0]) + u30(data[1])
            if trait['kind'] & 0x40:
                out += u30(len(trait['metadata'])) + b''.join(u30(v) for v in trait['metadata'])
        return bytes(out)

    # -- names and lookups --
    def string(self, index):
        return self.strings[index - 1] if index else '*'

    def multiname_name(self, index):
        if not index:
            return '*'
        entry = self.multinames[index - 1]
        if entry[0] in QNAME_KINDS or entry[0] in MULTINAME_KINDS:
            return self.string(entry[2] if entry[0] in QNAME_KINDS else entry[1])
        if entry[0] in RTQNAME_KINDS:
            return self.string(entry[1])
        if entry[0] == TYPENAME_KIND:
            return self.multiname_name(entry[1]) + '.<' + ','.join(self.multiname_name(v) for v in entry[2]) + '>'
        return '<late>'

    def body_of(self, method_index):
        for body in self.bodies:
            if body['method'] == method_index:
                return body
        raise AbcError(f'Method {method_index} has no body')

    def class_index(self, name):
        for index, instance in enumerate(self.instances):
            if self.multiname_name(instance['name']) == name:
                return index
        raise AbcError(f'Class {name} not found')

    def method_of(self, class_name, method_name):
        """Method index of an instance method (or getter) of a class."""
        instance = self.instances[self.class_index(class_name)]
        if method_name == '<init>':
            return instance['iinit']
        for trait in instance['traits']:
            if trait['kind'] & 0x0F in (1, 2, 3) and self.multiname_name(trait['name']) == method_name:
                return trait['data'][1]
        raise AbcError(f'{class_name}.{method_name} not found')

    # -- appending --
    def add_string(self, text):
        if text in self.strings:
            return self.strings.index(text) + 1
        self.strings.append(text)
        return len(self.strings)

    def add_namespace(self, kind, name):
        entry = (kind, self.add_string(name))
        if entry in self.namespaces:
            return self.namespaces.index(entry) + 1
        self.namespaces.append(entry)
        return len(self.namespaces)

    def add_qname(self, package, name):
        """QName multiname for a public name in a package ('' = top level)."""
        entry = (0x07, self.add_namespace(PACKAGE_NAMESPACE, package), self.add_string(name))
        if entry in self.multinames:
            return self.multinames.index(entry) + 1
        self.multinames.append(entry)
        return len(self.multinames)

    def find_qname(self, name, package=None):
        """Existing QName index for a name (optionally in a given package)."""
        for index, entry in enumerate(self.multinames, 1):
            if entry[0] in QNAME_KINDS and self.string(entry[2]) == name:
                if package is None or self.string(self.namespaces[entry[1] - 1][1]) == package:
                    return index
        return None


# --- disassembly ---------------------------------------------------------------

# opcode -> (name, operand kinds): 'u30', 'u8', 's24', 'switch'
OPCODES = {
    0x01: ('bkpt', ()), 0x02: ('nop', ()), 0x03: ('throw', ()), 0x04: ('getsuper', ('mn',)),
    0x05: ('setsuper', ('mn',)), 0x06: ('dxns', ('u30',)), 0x07: ('dxnslate', ()), 0x08: ('kill', ('u30',)),
    0x09: ('label', ()), 0x0C: ('ifnlt', ('s24',)), 0x0D: ('ifnle', ('s24',)), 0x0E: ('ifngt', ('s24',)),
    0x0F: ('ifnge', ('s24',)), 0x10: ('jump', ('s24',)), 0x11: ('iftrue', ('s24',)), 0x12: ('iffalse', ('s24',)),
    0x13: ('ifeq', ('s24',)), 0x14: ('ifne', ('s24',)), 0x15: ('iflt', ('s24',)), 0x16: ('ifle', ('s24',)),
    0x17: ('ifgt', ('s24',)), 0x18: ('ifge', ('s24',)), 0x19: ('ifstricteq', ('s24',)), 0x1A: ('ifstrictne', ('s24',)),
    0x1B: ('lookupswitch', ('switch',)), 0x1C: ('pushwith', ()), 0x1D: ('popscope', ()), 0x1E: ('nextname', ()),
    0x1F: ('hasnext', ()), 0x20: ('pushnull', ()), 0x21: ('pushundefined', ()), 0x23: ('nextvalue', ()),
    0x24: ('pushbyte', ('u8',)), 0x25: ('pushshort', ('u30',)), 0x26: ('pushtrue', ()), 0x27: ('pushfalse', ()),
    0x28: ('pushnan', ()), 0x29: ('pop', ()), 0x2A: ('dup', ()), 0x2B: ('swap', ()), 0x2C: ('pushstring', ('str',)),
    0x2D: ('pushint', ('u30',)), 0x2E: ('pushuint', ('u30',)), 0x2F: ('pushdouble', ('u30',)), 0x30: ('pushscope', ()),
    0x31: ('pushnamespace', ('u30',)), 0x32: ('hasnext2', ('u30', 'u30')), 0x35: ('li8', ()), 0x36: ('li16', ()),
    0x37: ('li32', ()), 0x38: ('lf32', ()), 0x39: ('lf64', ()), 0x3A: ('si8', ()), 0x3B: ('si16', ()),
    0x3C: ('si32', ()), 0x3D: ('sf32', ()), 0x3E: ('sf64', ()), 0x40: ('newfunction', ('u30',)),
    0x41: ('call', ('u30',)), 0x42: ('construct', ('u30',)), 0x43: ('callmethod', ('u30', 'u30')),
    0x44: ('callstatic', ('u30', 'u30')), 0x45: ('callsuper', ('mn', 'u30')), 0x46: ('callproperty', ('mn', 'u30')),
    0x47: ('returnvoid', ()), 0x48: ('returnvalue', ()), 0x49: ('constructsuper', ('u30',)),
    0x4A: ('constructprop', ('mn', 'u30')), 0x4C: ('callproplex', ('mn', 'u30')), 0x4E: ('callsupervoid', ('mn', 'u30')),
    0x4F: ('callpropvoid', ('mn', 'u30')), 0x50: ('sxi1', ()), 0x51: ('sxi8', ()), 0x52: ('sxi16', ()),
    0x53: ('applytype', ('u30',)), 0x55: ('newobject', ('u30',)), 0x56: ('newarray', ('u30',)), 0x57: ('newactivation', ()),
    0x58: ('newclass', ('u30',)), 0x59: ('getdescendants', ('mn',)), 0x5A: ('newcatch', ('u30',)),
    0x5D: ('findpropstrict', ('mn',)), 0x5E: ('findproperty', ('mn',)), 0x5F: ('finddef', ('mn',)), 0x60: ('getlex', ('mn',)),
    0x61: ('setproperty', ('mn',)), 0x62: ('getlocal', ('u30',)), 0x63: ('setlocal', ('u30',)), 0x64: ('getglobalscope', ()),
    0x65: ('getscopeobject', ('u8',)), 0x66: ('getproperty', ('mn',)), 0x68: ('initproperty', ('mn',)),
    0x6A: ('deleteproperty', ('mn',)), 0x6C: ('getslot', ('u30',)), 0x6D: ('setslot', ('u30',)),
    0x6E: ('getglobalslot', ('u30',)), 0x6F: ('setglobalslot', ('u30',)), 0x70: ('convert_s', ()), 0x71: ('esc_xelem', ()),
    0x72: ('esc_xattr', ()), 0x73: ('convert_i', ()), 0x74: ('convert_u', ()), 0x75: ('convert_d', ()),
    0x76: ('convert_b', ()), 0x77: ('convert_o', ()), 0x78: ('checkfilter', ()), 0x80: ('coerce', ('mn',)),
    0x81: ('coerce_b', ()), 0x82: ('coerce_a', ()), 0x83: ('coerce_i', ()), 0x84: ('coerce_d', ()), 0x85: ('coerce_s', ()),
    0x86: ('astype', ('mn',)), 0x87: ('astypelate', ()), 0x88: ('coerce_u', ()), 0x89: ('coerce_o', ()),
    0x90: ('negate', ()), 0x91: ('increment', ()), 0x92: ('inclocal', ('u30',)), 0x93: ('decrement', ()),
    0x94: ('declocal', ('u30',)), 0x95: ('typeof', ()), 0x96: ('not', ()), 0x97: ('bitnot', ()), 0xA0: ('add', ()),
    0xA1: ('subtract', ()), 0xA2: ('multiply', ()), 0xA3: ('divide', ()), 0xA4: ('modulo', ()), 0xA5: ('lshift', ()),
    0xA6: ('rshift', ()), 0xA7: ('urshift', ()), 0xA8: ('bitand', ()), 0xA9: ('bitor', ()), 0xAA: ('bitxor', ()),
    0xAB: ('equals', ()), 0xAC: ('strictequals', ()), 0xAD: ('lessthan', ()), 0xAE: ('lessequals', ()),
    0xAF: ('greaterthan', ()), 0xB0: ('greaterequals', ()), 0xB1: ('instanceof', ()), 0xB2: ('istype', ('mn',)),
    0xB3: ('istypelate', ()), 0xB4: ('in', ()), 0xC0: ('increment_i', ()), 0xC1: ('decrement_i', ()),
    0xC2: ('inclocal_i', ('u30',)), 0xC3: ('declocal_i', ('u30',)), 0xC4: ('negate_i', ()), 0xC5: ('add_i', ()),
    0xC6: ('subtract_i', ()), 0xC7: ('multiply_i', ()), 0xD0: ('getlocal0', ()), 0xD1: ('getlocal1', ()),
    0xD2: ('getlocal2', ()), 0xD3: ('getlocal3', ()), 0xD4: ('setlocal0', ()), 0xD5: ('setlocal1', ()),
    0xD6: ('setlocal2', ()), 0xD7: ('setlocal3', ()), 0xEF: ('debug', ('u8', 'u30', 'u8', 'u30')),
    0xF0: ('debugline', ('u30',)), 0xF1: ('debugfile', ('str',)), 0xF2: ('bkptline', ('u30',)), 0xF3: ('timestamp', ()),
}


def disassemble(abc, code):
    """[(offset, name, operands as readable text)] for a method body's code."""
    r = Reader(code)
    out = []
    while r.pos < len(code):
        offset = r.pos
        opcode = r.u8()
        if opcode not in OPCODES:
            raise AbcError(f'Unknown opcode {opcode:#x} at {offset}')
        name, kinds = OPCODES[opcode]
        operands = []
        for kind in kinds:
            if kind == 'u8':
                operands.append(str(r.u8()))
            elif kind == 's24':
                target = r.s24()
                operands.append(f'->{r.pos + target}')
            elif kind == 'switch':
                default = r.s24()
                cases = [r.s24() for _ in range(r.u30() + 1)]
                operands.append(f'default ->{offset + default} cases ' + ','.join(f'->{offset + c}' for c in cases))
            elif kind == 'mn':
                operands.append(abc.multiname_name(r.u30()))
            elif kind == 'str':
                index = r.u30()
                operands.append(repr(abc.string(index)))
            else:
                operands.append(str(r.u30()))
        out.append((offset, name, ' '.join(operands)))
    return out


def find_abc(body, header_length):
    """(tag start offset in body, payload, abc offset in payload) of the only DoABC tag."""
    from swf_localization import iter_tags
    found = None
    offset = header_length
    for code, payload, long_length in iter_tags(body, header_length):
        if code == 82:
            if found:
                raise AbcError('Expected exactly one DoABC tag')
            found = payload
    if found is None:
        raise AbcError('No DoABC tag')
    return found, found.index(b'\0', 4) + 1
