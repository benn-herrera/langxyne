"""The Python module: the library loaded through ctypes from a fixed path, every function's
prototype, the constants, enums, conversions, typed raw handles and structures, and one class per
opaque ref that names a constructor, every call raising for a result other than the zero entry."""

import keyword
from dataclasses import dataclass, field
from pathlib import Path

from langxyne import model, naming
from langxyne.emitters import c, emitter
from langxyne.model import (
    Api,
    BitConst,
    ClassShape,
    EnumEntry,
    Function,
    Group,
    Param,
    TypedConst,
    Union,
    duplicate_objections,
    generated_name_objections,
    headed,
    named_values,
    single_bit_entries,
)

LABEL = "python"

_BODY_NAMES = (
    "self",
    "callable",
    "isinstance",
    "len",
    "list",
    "float",
    "bytes",
    "memoryview",
    "TypeError",
    "ValueError",
    "RuntimeError",
)
"""What a function body spells where its parameters are in scope, beside the names the module
defines and its private `_` names: `self` and the builtins it calls. A parameter named like one
would shadow it."""
_MODULE_BUILTINS = (
    "BaseException",
    "Exception",
    "ImportError",
    "IndexError",
    "OSError",
    "RuntimeError",
    "TypeError",
    "ValueError",
    "bytes",
    "callable",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "memoryview",
    "property",
    "range",
    "slice",
    "super",
    "type",
)
"""Every builtin the module spells, which a module-scope name of the same spelling would shadow."""
_STRUCTURE_METHODS = ("from_buffer_copy", "from_address", "from_buffer", "from_param")
"""The ctypes classmethods of a generated structure, which a field of the same name would hide."""
_CTYPES = {
    "i8": "c_int8",
    "u8": "c_uint8",
    "i16": "c_int16",
    "u16": "c_uint16",
    "i32": "c_int32",
    "u32": "c_uint32",
    "i64": "c_int64",
    "u64": "c_uint64",
    "f32": "c_float",
    "f64": "c_double",
}
_IN_CALL = "_in_call"
_CALLS = "_calls"
_I = " " * 4
_UNION_ERROR = naming.UNION_ERROR
_CLAUSE_TEXTS = naming.UNION_CLAUSE_TEXTS


def validate(api: Api) -> list[str]:
    """Every objection the Python module has to `api`: a Python keyword where the module spells
    a definition name as written or in UpperCamel; a struct field named like a classmethod of a
    structure the module calls; a parameter named like a name its function body spells or the
    module defines; a name defined twice in the module or in a class; no library named; and a
    static link, since the module loads its library at run time."""
    raw = [("_general._name", api.name)]
    raw += [(f"struct.{s.name}.{f.name}", f.name) for s in api.structs for f in s.fields]
    raw += _conversion_names(api)
    raw += [(f"function.{fn.name}", fn.name) for fn in api.functions]
    params = [(f"function.{fn.name}.{p.name}", _arg_name(p)) for fn, rendered in _rendered(api) for p in rendered]
    raw += params
    raw += [(f"function.{shape.ctor.name}.{p.name}", p.name) for shape in api.classes() for p in shape.cached]
    camel = [(f"typed_const.{t.name}", t.name) for t in api.typed_consts]
    camel += [(f"boxed_scalar.{b.name}", b.name) for b in api.boxed_scalars]
    camel += [(f"struct.{s.name}", s.name) for s in api.structs]
    camel += [(f"opaque_ref.{s.opaque.name}._class", s.opaque.class_name) for s in api.classes()]
    objections = [f"{where}: '{name}' is a Python keyword" for where, name in raw if keyword.iskeyword(name)]
    objections += [
        f"{where}: '{naming.upper_camel(name)}' is a Python keyword"
        for where, name in camel
        if keyword.iskeyword(naming.upper_camel(name))
    ]
    fields = [(f"struct.{s.name}.{f.name}", f.name) for s in api.structs for f in s.fields]
    objections += generated_name_objections(fields, set(_STRUCTURE_METHODS))
    module = _module_names(api)
    unions = _union_names(api)
    used = {*_BODY_NAMES, *(name for _, name in (*module, *unions))}
    objections += generated_name_objections(params, used)
    objections += duplicate_objections(
        [*(("the builtins", name) for name in _MODULE_BUILTINS), *module], "module scope"
    )
    objections += _union_name_objections(unions, module)
    for shape in api.classes():
        # `property` decorates each accessor in the class body, where a member of its name would hide it
        own = ["handle", "property", *(["release"] if shape.dtor is not None else [])]
        objections += duplicate_objections(shape.members(own), f"class {naming.upper_camel(shape.opaque.class_name)}")
    if api.library.name is None:
        objections.append(emitter.NO_LIBRARY)
    if api.library.link == naming.STATIC:
        objections.append(
            f"--link={naming.STATIC}: the Python module loads its library at run time and cannot link it statically"
        )
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("python") / f"{name}.py"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def _conversion_names(api: Api) -> list[tuple[str, str]]:
    """(where the definition names it, module function) for every `_to_string` conversion."""
    names = [
        (f"{g.name}._to_string", naming.flat_to_string(g.to_string, typename=None))
        for g in (*api.bit_const_groups, *api.const_groups)
        if g.to_string is not None
    ]
    names += [
        (f"typed_const.{t.name}._to_string", naming.flat_to_string(t.to_string, typename=t.name))
        for t in api.typed_consts
        if t.to_string is not None
    ]
    return names


def _module_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of everything the module defines at its scope but its private `_` names."""
    const = naming.unprefixed_const_name
    camel = naming.upper_camel
    names = [(where, const(name)) for where, name in api.constant_names(version=True)]
    names += _conversion_names(api)
    names += [(f"typed_const.{t.name}", camel(t.name)) for t in api.typed_consts]
    names += [(f"opaque_ref.{o.name}", naming.handle_type(o.name)) for o in api.opaque_refs]
    names += [(f"boxed_scalar.{b.name}", camel(b.name)) for b in api.boxed_scalars]
    if api.uses_text():
        names += [
            (f"the builtin type {naming.TEXT}", camel(naming.TEXT)),
            ("the generated text resolver", naming.RESOLVE),
        ]
    names += [(f"struct.{s.name}", camel(s.name)) for s in api.structs]
    names.append(("the module's exception class", naming.ERROR))
    names += [(f"opaque_ref.{s.opaque.name}._class", camel(s.opaque.class_name)) for s in api.classes()]
    names += [(f"function.{fn.name}", fn.name) for fn in api.free_functions()]
    return names


def _union_names(api: Api) -> list[tuple[str, str]]:
    """(definer, name) of what the module defines at its scope for its unions: each one's sequence
    class and alignment constant, and `UnionError`, the first one's."""
    lists = api.listed_unions()
    if not lists:
        return []
    return [
        *((f"union '{u.name}'", name) for u in lists for name in (naming.union_sequence(u.name), _union_align(u))),
        (f"union '{lists[0].name}'", _UNION_ERROR),
    ]


def _union_align(union: Union) -> str:
    """The module constant of union `union`'s list alignment: `NOTE_ALIGN`."""
    return naming.unprefixed_const_name(naming.union_align(union.name))


def _union_name_objections(unions: list[tuple[str, str]], module: list[tuple[str, str]]) -> list[str]:
    """Each name of `module`, (where, name), that a union's rendering defines, naming the union."""
    defined = {name: union for union, name in unions}
    return [
        f"{where}: module scope name {name} already defined by {defined[name]}"
        for where, name in module
        if name in defined
    ]


def _rendered(api: Api) -> list[tuple[Function, list[Param]]]:
    """Each function the module renders with the parameters its Python signature takes, every
    one but a non-buffer `out`, which it returns: a class's ctor and methods, the method's first
    parameter `self`, and every free function."""
    rendered = [(fn, params) for shape in api.classes() for fn, params, _ in shape.class_params()]
    rendered += [(fn, fn.params) for fn in api.free_functions()]
    return [(fn, [p for p in params if p.is_buffer or p.ref != "out"]) for fn, params in rendered]


def _arg_name(p: Param) -> str:
    """The Python argument a parameter is: an `out` buffer's count, which the caller gives in
    the buffer's place, else the parameter itself."""
    return p.count_name() if p.is_buffer and p.ref == "out" else p.name


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The Python module, loading the library's shared file for the platform it runs on from its
    own directory, or from the absolute path the library variable names."""
    files = {
        host: naming.library_file_name(api.library.name, platform=platform, link=naming.SHARED)
        for host, platform in naming.HOST_PLATFORMS.items()
    }
    lib, variable = api.library.name, naming.library_variable(api.namespace)
    beside = "_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), _FILES[_sys.platform])"
    out = [
        f"# {emitter.banner(source_name)}\n",
        "import ctypes as _ctypes\n",
        "import enum as _enum\n",
        "import os as _os\n",
        "import sys as _sys\n",
        "import threading as _threading\n",
        "import weakref as _weakref\n",
        f"\n_FILES = {files!r}\n",
        "if _sys.platform not in _FILES:\n",
        f'{_I}raise ImportError(f"no file of the library {lib} for the platform {{_sys.platform!r}}")\n',
        f'_path = _os.environ.get("{variable}") or {beside}\n',
        "if not _os.path.isabs(_path):\n",
        f'{_I}raise ImportError(f"{variable} must be an absolute path, not {{_path!r}}")\n',
        "try:\n",
        f"{_I}_lib = _ctypes.CDLL(_path)\n",
        "except OSError as error:\n",
        f'{_I}raise ImportError(f"cannot load the library {lib} from {{_path}}: {{error}}") from error\n',
    ]
    for doc, literals in _constant_sections(api):
        out.append(f"\n{_comment(doc)}" if doc else "\n")
        out += [f"{name} = {value}\n" for name, value in literals]
    out += [_bit_to_string(g) for g in api.bit_const_groups if g.to_string is not None]
    out += [
        _lookup(
            naming.flat_to_string(g.to_string, typename=None), named_values(g), unknown=naming.unknown_value_name(None)
        )
        for g in api.const_groups
        if g.to_string is not None
    ]
    out += [_enum(t, heading=h) for h, t in headed(api.typed_const_groups)]
    out += [
        _lookup(
            naming.flat_to_string(t.to_string, typename=t.name), t.entries, unknown=naming.unknown_value_name(t.name)
        )
        for t in api.typed_consts
        if t.to_string is not None
    ]
    out += [_handle_class(api, o.name) for o in api.opaque_refs]
    out += [
        _structure(naming.upper_camel(b.name), b.docstring, [("value", _ctype(api, b.base_type))], heading=h)
        for h, b in headed(api.boxed_scalar_groups)
    ]
    if api.uses_text():
        out.append(
            _structure(
                naming.upper_camel(naming.TEXT),
                "A run of bytes in an arena, as its offset and its length.",
                [(n, _ctype(api, t)) for n, t in naming.TEXT_FIELDS],
                heading=None,
            )
        )
        out.append(_RESOLVE_TEXT)
    out += [
        _structure(
            naming.upper_camel(s.name), s.docstring, [(f.name, _ctype(api, f.type)) for f in s.fields], heading=h
        )
        for h, s in headed(api.struct_groups)
    ]
    lists = api.listed_unions()
    if lists:
        out.append(_SEQUENCE_TEXT)
    out += [_sequence(api, u, heading=h) for h, u in headed(api.union_groups, lists)]
    out.append(_ERROR_TEXT)
    if api.callbacks:
        out.append(_CALLBACK_TEXT)
    out += [_trampoline(api, cb) for cb in api.callbacks]
    out.append("\n")
    out += [_prototype(api, fn) for fn in api.functions]
    classes = api.classes()
    if any(_locked(shape) for shape in classes):
        out.append(_FINALIZE_TEXT)
    if any(shape.dtor is not None and not _locked(shape) for shape in classes):
        out.append(_FINALIZE_COUNTED_TEXT)
    opaque_headings = {o.name: h for h, o in headed(api.opaque_ref_groups, (s.opaque for s in classes))}
    out += [_class(api, shape, heading=opaque_headings[shape.opaque.name]) for shape in classes]
    out += [_function(api, fn, heading=h) for h, fn in headed(api.function_groups, api.free_functions())]
    return "".join(out)


def _comment(doc: str | None, *, indent: str = "") -> str:
    return f"{indent}# {doc}\n" if doc else ""


def _docstring(docs: list[str], *, indent: str) -> str:
    """`docs` as a docstring statement, through `repr()`, so any text is a valid literal."""
    return indent + repr("\n".join(docs)) + "\n" if docs else ""


def _ctype(api: Api, type_name: str) -> str:
    """A definition type's ctypes spelling: a builtin's or an enum's base type's simple type, an
    opaque ref its raw handle class, a boxed scalar, text or struct its class, a callback type
    its `CFUNCTYPE`."""
    kind = api.kind(type_name)
    if kind == "builtin":
        return f"_ctypes.{_CTYPES[type_name]}"
    if kind == "enum":
        return f"_ctypes.{_CTYPES[_enum_base(api, type_name)]}"
    if kind == "opaque":
        return naming.handle_type(type_name)
    if kind == "callback":
        return f"_{type_name}_c_type"
    return naming.upper_camel(type_name)


def _enum_base(api: Api, type_name: str) -> str:
    return next(t.base_type for t in api.typed_consts if t.name == type_name)


def _constant_sections(api: Api) -> list[tuple[str | None, list[tuple[str, str]]]]:
    """Every constant's (name, literal) in the C header's order, as the Lua module renders them,
    each group's under its docstring."""
    name = naming.unprefixed_const_name
    sections = [(None, [(name(naming.VERSION_KEY), f"0x{api.version_value():08x}")])]
    sections += [
        (g.docstring, [(name(e.name), c.int_literal(e.value, e.format)) for e in g.entries])
        for g in (*api.bit_const_groups, *api.const_groups)
    ]
    sections += [
        (g.docstring, [(name(e.name), c.int_literal(e.value, e.format)) for t in g.entries for e in t.entries])
        for g in api.typed_const_groups
    ]
    sections += [(g.docstring, [(name(e.name), f'"{e.value}"') for e in g.entries]) for g in api.string_const_groups]
    return sections


def _lookup(name: str, entries: tuple[EnumEntry, ...], *, unknown: str) -> str:
    """A value-to-name conversion, one key per value of `entries`."""
    keys = ", ".join(f'{c.int_literal(e.value, e.format)}: "{naming.unprefixed_const_name(e.name)}"' for e in entries)
    return f'\n\ndef {name}(value):\n{_I}return {{{keys}}}.get(value, "{unknown}")\n'


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term of their 32-bit pattern."""
    flags = "".join(
        f'{_I}if value & {k}:\n{_I * 2}names.append("{k}")\n{_I * 2}value &= ~{k}\n'
        for k in (naming.unprefixed_const_name(e.name) for e in single_bit_entries(group))
    )
    return (
        f"\n\ndef {naming.flat_to_string(group.to_string, typename=None)}(value):\n"
        f'{_I}if value == 0:\n{_I * 2}return "{naming.NO_FLAGS}"\n'
        f"{_I}names = []\n"
        f"{flags}"
        f"{_I}if value:\n"
        f'{_I * 2}names.append(f"0x{{value & 0xFFFFFFFF:x}}")\n'
        f'{_I}return "|".join(names)\n'
    )


def _enum(typed: TypedConst, *, heading: str | None) -> str:
    entries = "".join(
        _comment(e.docstring, indent=_I)
        + f"{_I}{naming.unprefixed_const_name(e.name)} = {c.int_literal(e.value, e.format)}\n"
        for e in typed.entries
    )
    doc = _docstring([typed.docstring] if typed.docstring else [], indent=_I)
    return f"\n\n{_comment(heading)}class {naming.upper_camel(typed.name)}(_enum.IntEnum):\n{doc}{entries}"


def _handle_class(api: Api, opaque: str) -> str:
    """The class of an opaque ref's raw handle, which only the module makes: one an argument
    takes is one the module issued for that opaque, never an `int` or another handle, and one
    is never copied, so releasing an object clears the one handle every holder reads."""
    cls = naming.handle_type(opaque)
    c_type = naming.type_name(api.namespace, opaque)
    refused = f'{_I * 2}raise TypeError("a {cls} cannot be copied")\n'
    return (
        f"\n\nclass {cls}(_ctypes.c_void_p):\n"
        f'{_I}"""A raw {c_type} handle the module issued; one is never made from a value."""\n\n'
        f"{_I}def __init__(self, *args):\n"
        f"{_I * 2}if args:\n"
        f'{_I * 3}raise TypeError("a {cls} is issued by the module, never made from a value")\n'
        f"{_I * 2}super().__init__()\n\n"
        f"{_I}def __copy__(self):\n{refused}\n"
        f"{_I}def __deepcopy__(self, memo):\n{refused}\n"
        f"{_I}def __reduce_ex__(self, protocol):\n{refused}"
    )


def _structure(name: str, doc: str | None, fields: list[tuple[str, str]], *, heading: str | None) -> str:
    rows = "".join(f'{_I * 2}("{n}", {t}),\n' for n, t in fields)
    return (
        f"\n\n{_comment(heading)}class {name}(_ctypes.Structure):\n"
        + _docstring([doc] if doc else [], indent=_I)
        + f"{_I}_fields_ = [\n{rows}{_I}]\n"
    )


_RESOLVE_TEXT = f'''

def {naming.RESOLVE}(text, arena):
    """The bytes of `arena` the run `text` covers, a copy of the run alone, None where the run
    leaves the arena: `arena` a bytes-like value, or a byte view while its callback runs."""
    end = text.{naming.TEXT_OFFSET} + text.{naming.TEXT_LENGTH}
    if end > len(arena):
        return None
    return bytes(arena[text.{naming.TEXT_OFFSET}:end])
'''

_SEQUENCE_TEXT = f'''

class {_UNION_ERROR}(RuntimeError):
    """A sequence refused at a record: `index` and `offset` are the record's, `clause` the text of
    why, one of the six a walk refuses with."""

    def __init__(self, what, index, offset, clause):
        super().__init__(f"{{what}} refused at record {{index}}, offset {{offset}}: {{clause}}")
        self.index, self.offset, self.clause = index, offset, clause


class _Sequence:
    """A list of a union's members the library passed a callback: `count` records back to back in
    `extent` bytes at `address`, read lazily, a record's prefix only once its bytes remain and the
    record only once its tag is a member's and its size that member's, each record read a copy
    of its member's structure, and refused on any other thread than its callback's and once its
    callback returns. A subclass names the prefix and its size, the list's alignment, the
    prefix's tag and length fields, and each member's structure and size by tag."""

    __slots__ = ("_address", "_count", "_extent", "_what", "_live", "_thread")

    def __init__(self, address, count, extent, what):
        if not address and (count or extent):
            raise RuntimeError(f"{{what}} outside the definition")
        self._address, self._count, self._extent, self._what = address or 0, count, extent, what
        self._live, self._thread = True, _threading.get_ident()

    def _check(self):
        if not self._live or _threading.get_ident() != self._thread:
            raise ValueError("a view is valid only on its callback's thread, until its callback returns")

    def __len__(self):
        self._check()
        return self._count

    @property
    def bytes(self):
        self._check()
        return self._extent

    def _member(self, index, at):
        """The structure and size of the member at byte `at`, the record `index`; {_UNION_ERROR}
        where it is refused."""
        if at == self._extent:
            clause = "{_CLAUSE_TEXTS['count_not_met']}"
        elif self._extent - at < self._PREFIX_SIZE:
            clause = "{_CLAUSE_TEXTS['header_past_extent']}"
        else:
            head = self._PREFIX.from_address(self._address + at)
            member = self._MEMBERS.get(getattr(head, self._TAG))
            if member is None:
                clause = "{_CLAUSE_TEXTS['unknown_tag']}"
            elif getattr(head, self._LENGTH) != member[1]:
                clause = "{_CLAUSE_TEXTS['size_not_the_members']}"
            elif self._extent - at < member[1]:
                clause = "{_CLAUSE_TEXTS['record_past_extent']}"
            else:
                return member
        raise {_UNION_ERROR}(self._what, index, at, clause)

    def _copy(self, structure, at):
        return structure.from_buffer_copy(structure.from_address(self._address + at))

    def __iter__(self):
        at = 0
        for index in range(self._count):
            self._check()
            structure, size = self._member(index, at)
            yield self._copy(structure, at)
            at += size
        self._check()
        if at != self._extent:
            raise {_UNION_ERROR}(self._what, self._count, at, "{_CLAUSE_TEXTS['count_not_met']}")

    def at(self, index):
        """The record `index` units of the list's alignment from the sequence's start, a copy of
        its member's structure; {_UNION_ERROR} where the walk from the start refuses a record
        before it, the count's among them, or does not land on it."""
        self._check()
        offset = index * self._ALIGN
        walked, at = 0, 0
        while True:
            if walked == self._count:
                if at != self._extent:
                    raise {_UNION_ERROR}(self._what, walked, at, "{_CLAUSE_TEXTS['count_not_met']}")
                break
            structure, size = self._member(walked, at)
            if at >= offset:
                if at == offset:
                    return self._copy(structure, at)
                break
            walked, at = walked + 1, at + size
        raise {_UNION_ERROR}(self._what, walked, offset, "{_CLAUSE_TEXTS['not_a_record_start']}")

    def _c_arguments(self):
        """The pointer, count and extent a C call passes for the sequence."""
        self._check()
        return self._address or None, self._count, self._extent
'''


def _sequence(api: Api, union: Union, *, heading: str | None) -> str:
    """The module constant of `union`'s list alignment, then its sequence class: its prefix,
    the prefix's size, the list's alignment, the prefix's tag and length fields, and each
    member's structure and size by its tag's constant, every size the layout model's."""
    members = ", ".join(
        f"{naming.unprefixed_const_name(m.tag)}: ({naming.upper_camel(m.struct)}, {api.layout(m.struct)[0]})"
        for m in union.members
    )
    size, align = api.layout(union.prefix)[0], _union_align(union)
    seq = naming.union_sequence(union.name)
    return (
        f"\n\n# the list's alignment, the unit of {seq}.at's index\n{align} = {api.list_alignment(union)}\n"
        f"\n\n{_comment(heading)}class {seq}(_Sequence):\n"
        + _docstring([union.docstring] if union.docstring else [], indent=_I)
        + f"{_I}__slots__ = ()\n"
        + f"{_I}_PREFIX, _PREFIX_SIZE, _ALIGN = {naming.upper_camel(union.prefix)}, {size}, {align}\n"
        + f'{_I}_TAG, _LENGTH = "{union.tag_field}", "{union.length_field}"\n'
        + f"{_I}_MEMBERS = {{{members}}}\n"
    )


_ERROR_TEXT = f'''

class {naming.ERROR}(Exception):
    """A call's result other than the zero entry; `result` is it, a member of the return enum."""

    def __init__(self, result):
        super().__init__(result.name)
        self.result = result


def _named(enum, value, what):
    """`value` as a member of `enum`: a value no entry has is the library answering outside the
    definition, what `what` says."""
    try:
        return enum(value)
    except ValueError:
        raise RuntimeError(f"{{what}} ({{value}})") from None


def _integer(value, low, high, what):
    """`value` as an int from `low` to `high`; `what` is the refusal's text."""
    if not isinstance(value, int):
        raise TypeError(what)
    if not low <= value <= high:
        raise ValueError(what)
    return int(value)


def _member(enum, value, what):
    """`value` as a member of `enum`; `what` is the refusal's text."""
    try:
        return enum(value)
    except (TypeError, ValueError):
        raise ValueError(what) from None
'''

_CALLBACK_TEXT = '''

class _View:
    """A view the library passed a callback: `count` elements of `ctype` at `address`, read
    lazily, each element read a copy, a boxed scalar's its value, and refused on any other
    thread than its callback's and once its callback returns."""

    __slots__ = ("_address", "_count", "_ctype", "_live", "_thread", "_boxed")

    def __init__(self, address, count, ctype, what, boxed=False):
        if not address and count:
            raise RuntimeError(f"{what} outside the definition")
        self._address, self._count, self._ctype, self._live = address or 0, count, ctype, True
        self._thread, self._boxed = _threading.get_ident(), boxed

    def _check(self):
        if not self._live or _threading.get_ident() != self._thread:
            raise ValueError("a view is valid only on its callback's thread, until its callback returns")

    def __len__(self):
        self._check()
        return self._count

    def __getitem__(self, index):
        self._check()
        if isinstance(index, slice):
            items = [self[i] for i in range(*index.indices(self._count))]
            return bytes(items) if self._ctype is _ctypes.c_ubyte else items
        if index < 0:
            index += self._count
        if not 0 <= index < self._count:
            raise IndexError("view index out of range")
        element = self._ctype.from_address(self._address + index * _ctypes.sizeof(self._ctype))
        if isinstance(element, _ctypes.Structure):
            return element.value if self._boxed else type(element).from_buffer_copy(element)
        return element.value

    def __iter__(self):
        return (self[i] for i in range(len(self)))


class _Failure:
    """What failed during one driving call, shared by all its callbacks: the first exception,
    which the call raises again once the library returns."""

    __slots__ = ("error",)

    def __init__(self):
        self.error = None

    def record(self, error):
        if self.error is None:
            self.error = error
'''

_FINALIZE_TEXT = '''

def _finalize(dtor, handle, lock):
    """Releases an object never released, unless a call of it holds its lock, as at interpreter
    exit with another thread inside one: that handle is left to the process's end. The lock is
    kept, so no later call reaches the destroyed handle."""
    if lock.acquire(blocking=False):
        dtor(handle)
        handle.value = None
'''

_FINALIZE_COUNTED_TEXT = '''

def _finalize_counted(dtor, handle, calls):
    """Releases an object never released, unless a call of it is in progress, as at interpreter
    exit with another thread inside one: that handle is left to the process's end."""
    if not calls[0]:
        dtor(handle)
        handle.value = None
'''


def _locked(shape: ClassShape) -> bool:
    """Whether the class holds a lock wrapping its handle's lifetime: it has a dtor and its
    opaque's `_hides_pointer` says the library does not validate the handle."""
    return shape.dtor is not None and shape.opaque.hides_pointer


def _trampoline(api: Api, callback: Function) -> str:
    """The callback type's `CFUNCTYPE`, and `_<c>_trampoline`, which gives one for a callable
    and a driving call, every statement of its body under one `try` catching any exception as
    the call's failure: on another thread than the driving call's, where the call's failure is
    recorded, or where an invocation of it runs, it answers the stop entry without calling the
    callable, recording the first and last as failures; otherwise it builds each view and enum
    and calls the callable, and maps its answer, None the zero entry, a member of the return
    enum or an int its base type holds itself, anything else a failure. Each view is refused
    once the callable returns."""
    c_type = naming.type_name(api.namespace, callback.name)
    returns = next(t for t in api.typed_consts if t.name == callback.returns)
    enum = naming.upper_camel(returns.name)
    low, high = naming.integer_range(returns.base_type)
    base = naming.BASE_C_TYPES[returns.base_type].c_type
    stop_entry = api.stop_entry(callback)
    stop = c.int_literal(stop_entry.value, stop_entry.format)
    go = c.int_literal(api.success_entry(callback).value, "dec")
    arg_types = _arg_types(api, callback)
    names = [f"a{i}" for i in range(len(arg_types))]
    reads, args = [], []
    i = 0
    for p in callback.params:
        if p.is_union:
            reads.append(
                f"views.append({naming.union_sequence(p.type)}(a{i}, a{i + 1}, a{i + 2}, "
                f'"{c_type} received view {p.name}"))'
            )
            args.append(f"views[{len(reads) - 1}]")
        elif p.is_buffer:
            element = "_ctypes.c_ubyte" if p.type == "memory" else _ctype(api, p.type)
            boxed = ", boxed=True" if api.kind(p.type) == "boxed" else ""
            reads.append(f'views.append(_View(a{i}, a{i + 1}, {element}, "{c_type} received view {p.name}"{boxed}))')
            args.append(f"views[{len(reads) - 1}]")
        elif api.kind(p.type) == "enum":
            enum_c = naming.type_name(api.namespace, p.type)
            args.append(
                f'_named({naming.upper_camel(p.type)}, a{i}, "{c_type} received a {p.name} value {enum_c} does not name")'
            )
        else:
            args.append(f"a{i}")
        i += 1 + len(p.derived_names())
    body = [
        "nonlocal running",
        "entered, views = False, []",
        "try:",
        "    if _threading.get_ident() != thread:",
        f'        failure.record(RuntimeError(f"{c_type} called on another thread than the one calling {{driving}}"))',
        f"        return {stop}",
        "    if failure.error is not None:",
        f"        return {stop}",
        "    if running:",
        f'        failure.record(RuntimeError(f"{c_type} called again while a call of it was running in {{driving}}"))',
        f"        return {stop}",
        "    running = entered = True",
        *(f"    {r}" for r in reads),
        f"    answer = fn({', '.join(args)})",
        "    if failure.error is not None:",
        f"        return {stop}",
        "    if answer is None:",
        f"        return {go}",
        f"    if isinstance(answer, {enum}) or (type(answer) is int and {low} <= answer <= {high}):",
        "        return int(answer)",
        "    failure.record(",
        f'        TypeError(f"{c_type}: the callable answered {{answer!r}}, not None, a {enum} or an int {base} holds")',
        "    )",
        f"    return {stop}",
        "except BaseException as error:",
        "    failure.record(error)",
        f"    return {stop}",
        "finally:",
        "    if entered:",
        "        running = False",
        "    for view in views:",
        "        view._live = False",
    ]
    proto = f"_{callback.name}_c_type"
    return (
        f"\n\n{proto} = _ctypes.CFUNCTYPE({', '.join([_ctype(api, callback.returns), *arg_types])})\n"
        f"\n\ndef _{naming.trampoline(callback.name)}(fn, failure, driving):\n"
        f'{_I}"""The C function calling `fn` as {c_type} for one call of the C function `driving`."""\n'
        f"{_I}thread = _threading.get_ident()\n"
        f"{_I}running = False\n\n"
        f"{_I}def trampoline({', '.join(names)}):\n"
        + "".join(f"{_I * 2}{line}\n" for line in body)
        + f"\n{_I}return {proto}(trampoline)\n"
    )


def _arg_types(api: Api, fn: Function) -> list[str]:
    """The ctypes of each C parameter of `fn`, a function or a callback type, in order, a
    callback type's `user_data` last; a callback's view a `void` pointer, read by `_View` or a
    sequence class, and a union's list, a function's or a callback's, a `void` pointer, its
    count and its extent."""
    if fn in api.callbacks:
        types = []
        for p in fn.params:
            if p.is_buffer:
                count = f"_ctypes.{_CTYPES[p.count_type]}"
                types += ["_ctypes.c_void_p", count, *([count] if p.is_union else [])]
            else:
                types.append(_ctype(api, p.type))
        return [*types, "_ctypes.c_void_p"]
    types = []
    for p in fn.params:
        if p.callback:
            types += [_ctype(api, p.type), "_ctypes.c_void_p"]
            continue
        if p.is_union:
            count = f"_ctypes.{_CTYPES[p.count_type]}"
            types += ["_ctypes.c_void_p", count, count]
            continue
        if p.is_buffer:
            pointer = "_ctypes.c_void_p" if p.type == "memory" else f"_ctypes.POINTER({_ctype(api, p.type)})"
            count = f"_ctypes.{_CTYPES[p.count_type]}"
            types += [pointer, count, *(f"_ctypes.POINTER({count})" for _ in p.report_names())]
            continue
        ctype = _ctype(api, p.type)
        types.append(ctype if p.ref is None else f"_ctypes.POINTER({ctype})")
    return types


def _prototype(api: Api, fn: Function) -> str:
    fname = naming.function_name(api.namespace, fn.name)
    types = _arg_types(api, fn)
    return (
        f"_lib.{fname}.argtypes = ({', '.join(types)}{',' if len(types) == 1 else ''})\n"
        f"_lib.{fname}.restype = {_ctype(api, fn.returns)}\n"
    )


@dataclass
class _Marshalled:
    """A function's parameters as the module renders them around one C call."""

    params: list[str] = field(default_factory=list)  # the Python signature's arguments
    checks: list[str] = field(default_factory=list)  # refusals of the caller's misuse and of a wrong type
    before: list[str] = field(default_factory=list)  # conversions and copies preparing the call's arguments
    state: list[str] = field(default_factory=list)  # refusals of a handle argument's state, last before the call
    locking: bool = False  # whether `state` takes an argument's lock into `_held`
    callbacks: list[tuple[str, str]] = field(default_factory=list)  # (local, its CFUNCTYPE) of each callback
    args: list[str] = field(default_factory=list)  # the C call's arguments, in order
    after: list[str] = field(default_factory=list)  # statements after a successful result
    outs: list[str] = field(default_factory=list)  # each value returned, in order


def _out_value(api: Api, fn: Function, p: Param, local: str) -> str:
    """What the caller receives of a value the call wrote into `local`."""
    kind = api.kind(p.type)
    if kind in ("struct", "text"):
        return local
    if kind == "opaque":
        return f"None if {local}.value is None else {local}"
    if kind == "enum":
        fname = naming.function_name(api.namespace, fn.name)
        enum_c = naming.type_name(api.namespace, p.type)
        return f'_named({naming.upper_camel(p.type)}, {local}.value, "{fname} wrote a {p.name} value {enum_c} does not name")'
    return f"{local}.value"


def _converted(api: Api, type_name: str, value: str, *, subject: str) -> str | None:
    """`value` refused unless it is what a parameter of type `type_name` takes, else converted to
    it: an integer within its type, a float, a member of its enum, a boxed scalar's base value
    within the base type and boxed; `subject` names it in the refusal. None for a struct or text,
    which ctypes itself checks."""
    kind = api.kind(type_name)
    if kind == "boxed":
        base = next(b.base_type for b in api.boxed_scalars if b.name == type_name)
        return f"{naming.upper_camel(type_name)}({_converted(api, base, value, subject=subject)})"
    if kind == "enum":
        enum = naming.upper_camel(type_name)
        return f'_member({enum}, {value}, "{subject} must be a {enum}")'
    if kind != "builtin":
        return None
    if type_name in ("f32", "f64"):
        return f"float({value})"
    low, high = naming.integer_range(type_name)
    return f'_integer({value}, {low}, {high}, "{subject} must be an int {naming.BUILTIN_C_TYPES[type_name]} holds")'


def _when_present(p: Param, statement: str) -> str:
    """`statement`, run only for a present argument where `p` is `_optional`."""
    if not p.optional:
        return statement
    return f"if {p.name} is not None:\n" + "".join(f"{_I}{line}\n" for line in statement.split("\n")).rstrip("\n")


def _marshal(api: Api, fn: Function, params: tuple[Param, ...], *, ctx: str) -> _Marshalled:
    """`params` of `fn` as Python arguments and results around the C call, `ctx` naming the
    Python function in a refusal of the caller's misuse. Each argument is refused unless it has
    the parameter's type and fits it, then converted or copied; a handle argument's lock is taken
    and its state refused last, after every conversion, so no consumer code runs between it and
    the call."""
    m = _Marshalled()
    fname = naming.function_name(api.namespace, fn.name)
    shapes = {shape.opaque.name: shape for shape in api.classes()}
    for p in params:
        kind = api.kind(p.type)
        local = f"_l_{p.name}"
        if p.callback:
            m.params.append(p.name)
            m.checks.append(f'if not callable({p.name}):\n{_I}raise TypeError("{ctx}: {p.name} must be callable")')
            m.callbacks.append((f"_k_{p.name}", f'_{naming.trampoline(p.type)}({p.name}, _failure, "{fname}")'))
            m.args += [f"_k_{p.name}", "None"]
        elif p.is_buffer:
            _marshal_buffer(api, fn, p, ctx=ctx, into=m)
        elif p.ref == "out":
            m.before.append(f"{local} = {_ctype(api, p.type)}()")
            m.args.append(f"_ctypes.byref({local})")
            m.outs.append(_out_value(api, fn, p, local))
        elif kind == "opaque":
            _marshal_handle(api, fn, p, shapes.get(p.type), ctx=ctx, into=m)
        else:
            m.params.append(p.name)
            converted = _converted(api, p.type, p.name, subject=f"{ctx}: {p.name}")
            if converted is None:  # a struct or text, a copy of the caller's taken before the call
                cls = naming.upper_camel(p.type)
                m.checks.append(
                    _when_present(
                        p,
                        f'if not isinstance({p.name}, {cls}):\n{_I}raise TypeError("{ctx}: {p.name} must be a {cls}")',
                    )
                )
                made = p.name if p.ref is None else f"{cls}.from_buffer_copy({p.name})"
            elif p.ref is None or kind == "boxed":
                made = converted
            else:
                made = f"{_ctype(api, p.type)}({converted})"
            if p.ref is None:
                m.before.append(f"{local} = {made}")
                m.args.append(local)
                continue
            if p.optional:
                m.before.append(f"{local} = None if {p.name} is None else {made}")
                m.args.append(f"None if {local} is None else _ctypes.byref({local})")
            else:
                m.before.append(f"{local} = {made}")
                m.args.append(f"_ctypes.byref({local})")
            if p.ref == "inout":
                read = _out_value(api, fn, p, local)
                m.outs.append(f"None if {local} is None else {read}" if p.optional else read)
    return m


def _marshal_handle(api: Api, fn: Function, p: Param, shape: ClassShape | None, *, ctx: str, into: _Marshalled) -> None:
    """An opaque ref the caller passes: where its opaque has a class, by value or `in`, an object
    of that class, its lock taken and held for the call where the class is locked, refused where
    another call holds it or where released, as the receiver is; otherwise refused where the
    class drives a callback, in a driving call, its handle passed whatever the library makes of
    it; with no class, the raw handle class the module issued for it, refused where null. An
    `inout` raw handle is returned as the caller's, the library having written it."""
    into.params.append(p.name)
    if shape is not None and p.ref in (None, "in"):
        cls = naming.upper_camel(shape.opaque.class_name)
        check = f'if not isinstance({p.name}, {cls}):\n{_I}raise TypeError("{ctx}: {p.name} must be a {cls}")'
        in_progress = f"{{{p.name}.{_IN_CALL}}} is in progress on it"
        refused = _busy(api, fn, message=f"{ctx}: {p.name} is a {cls} while {in_progress}")
        state = []
        if _locked(shape):
            into.locking = True
            state += [
                _acquire(p.name, refused),
                f"_held.append({p.name}._lock)",
                f"if {p.name}._handle is None:\n"
                f'{_I}raise ValueError("{ctx}: {p.name} is a {cls} used after {shape.dtor.name}")',
            ]
        elif shape.drives():
            state.append(f"if {p.name}.{_IN_CALL} is not None:\n{_I}raise {refused}")
        value = f"{p.name}._handle" if p.ref is None else f"_ctypes.byref({p.name}._handle)"
    else:
        handle = naming.handle_type(p.type)
        check = f'if not isinstance({p.name}, {handle}):\n{_I}raise TypeError("{ctx}: {p.name} must be a {handle}")'
        state = [f'if {p.name}.value is None:\n{_I}raise ValueError("{ctx}: {p.name} is a null {handle}")']
        value = p.name if p.ref is None else f"_ctypes.byref({p.name})"
        if p.ref == "inout":
            into.outs.append(p.name)
    into.checks.append(_when_present(p, check))
    if state:
        into.state.append(_when_present(p, "\n".join(state)))
    into.args.append(f"None if {p.name} is None else {value}" if p.optional else value)


def _marshal_buffer(api: Api, fn: Function, p: Param, *, ctx: str, into: _Marshalled) -> None:
    """A buffer: `memory` `in` a bytes-like value; `out` the count, returning the bytes written
    for `memory` and the array uncopied for an array; `memory` `inout` a bytes-like value
    returned as the bytes written; an `in` array any sequence, each element converted as a
    parameter of its type is, then copied. A count its type cannot hold is refused before
    anything is allocated or copied. A reported buffer returns its data, what it wrote and what
    it needs, the reports checked within the count and the need first. A union's list is the
    sequence class's instance a callback received, passed while that callback runs, uncopied."""
    local, count = f"_l_{p.name}", f"_c_{p.name}"
    if p.is_union:
        cls, extent = naming.union_sequence(p.type), f"_b_{p.name}"
        into.params.append(p.name)
        into.checks.append(
            _when_present(
                p, f'if not isinstance({p.name}, {cls}):\n{_I}raise TypeError("{ctx}: {p.name} must be a {cls}")'
            )
        )
        made = f"{p.name}._c_arguments()"
        into.before.append(
            f"{local}, {count}, {extent} = " + (f"(None, 0, 0) if {p.name} is None else {made}" if p.optional else made)
        )
        into.args += [local, count, extent]
        return
    element = "_ctypes.c_ubyte" if p.type == "memory" else _ctype(api, p.type)
    count_c = naming.BUILTIN_C_TYPES[p.count_type]
    low, high = naming.integer_range(p.count_type)
    arg = _arg_name(p)
    into.params.append(arg)
    # a Python length is below 2**63, which u64 holds
    length_check = (
        f'if {count} > {high}:\n{_I}raise ValueError("{ctx}: {p.name} is longer than {p.count_type} can count")'
        if model.COUNT_BITS[p.count_type] < 64
        else None
    )
    if p.ref == "out":
        into.before.append(
            f'{count} = _integer({arg}, {low}, {high}, "{ctx}: {arg} must be a whole number {count_c} holds")'
        )
        into.before.append(f"{local} = ({element} * {count})()")
    elif p.type == "memory":
        view = f"_m_{p.name}"
        cast = "" if p.ref == "in" else '.cast("B")'
        into.before.append(
            f"{view} = None if {p.name} is None else memoryview({p.name}){cast}"
            if p.optional
            else f"{view} = memoryview({p.name}){cast}"
        )
        into.before.append(
            f"{count} = 0 if {view} is None else {view}.nbytes" if p.optional else f"{count} = {view}.nbytes"
        )
        into.before += [length_check] if length_check else []
        made = f"bytes({view})" if p.ref == "in" else f"({element} * {count}).from_buffer_copy({view})"
        into.before.append(f"{local} = None if {view} is None else {made}" if p.optional else f"{local} = {made}")
    else:
        values = f"_v_{p.name}"
        converted = _converted(api, p.type, "_e", subject=f"{ctx}: an element of {p.name}")
        each = f"list({p.name})" if converted is None else f"[{converted} for _e in {p.name}]"
        into.before.append(f"{values} = None if {p.name} is None else {each}" if p.optional else f"{values} = {each}")
        into.before.append(
            f"{count} = 0 if {values} is None else len({values})" if p.optional else f"{count} = len({values})"
        )
        into.before += [length_check] if length_check else []
        made = f"({element} * {count})(*{values})"
        into.before.append(f"{local} = None if {values} is None else {made}" if p.optional else f"{local} = {made}")
    into.args += [local, count]
    reports = p.report_names()
    if reports:
        wrote, needed = f"_w_{p.name}", f"_n_{p.name}"
        ctype = f"_ctypes.{_CTYPES[p.count_type]}"
        into.before.append(f"{wrote}, {needed} = {ctype}(), {ctype}()")
        into.args += [f"_ctypes.byref({wrote})", f"_ctypes.byref({needed})"]
        fname = naming.function_name(api.namespace, fn.name)
        into.after.append(
            f"if {wrote}.value > {count} or {wrote}.value > {needed}.value:\n"
            f'{_I}raise RuntimeError("{fname} over-reported {p.name}: it wrote more than the buffer holds or than the '
            'result needs")'
        )
    if p.ref == "in":
        return
    if p.type == "memory":
        into.outs.append(f"bytes({local})[:{wrote}.value]" if reports else f"bytes({local})")
    else:
        into.outs.append(local)
    if reports:
        into.outs += [f"{wrote}.value", f"{needed}.value"]


def _body(
    api: Api,
    fn: Function,
    m: _Marshalled,
    *,
    first_args: list[str],
    receiver: list[str],
    busy: str | None,
    drives: bool,
    counted: bool,
    ok: list[str],
    returns: bool,
) -> list[str]:
    """A function body's statements, unindented: the misuse and type checks, the conversions and
    copies, then the state checks, `receiver`'s and the arguments', and nothing but the callback
    objects and the call after them. Where `busy`, the receiver's refusal while another call
    holds its lock, the state checks and the call run holding it (see `_holding`), as they do
    the arguments' locks they take; where `drives`, the receiver's class being unlocked, the
    call runs under `try`/`finally` marking it in progress, and where `counted` counting it among
    the object's calls in progress. Then the recorded failure raised, the result checked, `ok`,
    and where `returns` the outs."""
    fname = naming.function_name(api.namespace, fn.name)
    call = f"_raw = _lib.{fname}({', '.join([*first_args, *m.args])})"
    guarded = [*receiver, *m.state]
    if m.callbacks:
        guarded += ["_failure = _Failure()", *(f"{local} = {made}" for local, made in m.callbacks)]
    entering = [*([f'self.{_IN_CALL} = "{fname}"'] if drives else []), *([f"self.{_CALLS}[0] += 1"] if counted else [])]
    leaving = [*([f"self.{_CALLS}[0] -= 1"] if counted else []), *([f"self.{_IN_CALL} = None"] if drives else [])]
    if leaving:
        guarded += [*entering, "try:", f"{_I}{call}", "finally:", *(f"{_I}{s}" for s in leaving)]
    else:
        guarded.append(call)
    lines = [*m.checks, *m.before]
    if busy is not None or m.locking:
        lines += _holding(guarded, busy=busy, fname=fname)
    else:
        lines += guarded
    if m.callbacks:
        lines += [f"{local} = None" for local, _ in m.callbacks]
        lines.append(
            f"if _failure.error is not None:\n{_I}_error, _failure.error = _failure.error, None\n{_I}raise _error"
        )
    lines += [*_result_check(api, fn), *m.after, *ok]
    if returns:
        if len(m.outs) == 1:
            lines.append(f"return {m.outs[0]}")
        elif m.outs:
            lines.append(f"return ({', '.join(m.outs)})")
    return lines


def _result_check(api: Api, fn: Function) -> list[str]:
    """`_raw`, the call's result, as `_result`, a member of the return enum, raised as `Error`
    unless it is the zero entry."""
    fname = naming.function_name(api.namespace, fn.name)
    enum = naming.upper_camel(fn.returns)
    unnamed = f"{fname} returned a value {naming.type_name(api.namespace, fn.returns)} does not name"
    success = naming.unprefixed_const_name(api.success_entry(fn).name)
    return [
        f'_result = _named({enum}, _raw, "{unnamed}")',
        f"if _result != {enum}.{success}:\n{_I}raise {naming.ERROR}(_result)",
    ]


def _block(lines: list[str], indent: str) -> str:
    return "".join(f"{indent}{line}\n" if line else "\n" for text in lines for line in text.split("\n"))


def _indented(lines: list[str]) -> list[str]:
    return [f"{_I}{line}" for text in lines for line in text.split("\n")]


def _busy(api: Api, fn: Function, *, message: str) -> str:
    """The exception refusing a call of `fn` while another call holds an object, or for a class
    with no dtor drives a callback of it: `Error` of the first non-zero entry of its return enum,
    or where that enum has none `RuntimeError` of `message`, an f-string's body."""
    entry = api.first_nonzero_entry(fn)
    if entry is not None:
        return f"{naming.ERROR}({naming.upper_camel(fn.returns)}.{naming.unprefixed_const_name(entry.name)})"
    return f'RuntimeError(f"{message}")'


def _receiver_busy(api: Api, fn: Function, *, cls: str, name: str) -> str:
    return _busy(api, fn, message=f"{cls}.{name} called while {{self.{_IN_CALL}}} is in progress on this {cls}")


def _in_call_guard(busy: str) -> str:
    """An unlocked object's refusal, `busy` raised, while a call of it drives a callback."""
    return f"if self.{_IN_CALL} is not None:\n{_I}raise {busy}"


def _acquire(holder: str, refused: str) -> str:
    """`holder`'s lock taken without waiting, `refused` raised where another call holds it."""
    return f"if not {holder}._lock.acquire(blocking=False):\n{_I}raise {refused}"


def _holding(guarded: list[str], *, busy: str | None, fname: str) -> list[str]:
    """`guarded` under `try`, every lock it gathers in `_held` released in the `finally`: where
    `busy`, the receiver's lock taken first, `busy` raised where another call holds it, and the
    receiver's in-call state naming the C function `fname` while it is held."""
    if busy is None:
        taken = ["_held = []"]
    else:
        taken = [_acquire("self", busy), "_held = [self._lock]", f'self.{_IN_CALL} = "{fname}"']
    return [
        *taken,
        "try:",
        *_indented(guarded),
        "finally:",
        *([f"{_I}self.{_IN_CALL} = None"] if busy is not None else []),
        f"{_I}for _lock in _held:",
        f"{_I * 2}_lock.release()",
    ]


def _class(api: Api, shape: ClassShape, *, heading: str | None) -> str:
    """The class, owning its handle and refusing to be copied: its constructor, raising on
    failure; `handle` and a property per cached `out`; a method per member function; with a dtor
    `release()`, the context manager calling it and a finalizer releasing an object never
    released. Locked (see `_locked`), one lock, every method and `release()` holding it for the
    call and raising `ValueError` naming the dtor once released, the finalizer releasing only
    where no call holds it; unlocked, every call after release passing the null handle to the
    library, the finalizer releasing only where no call is in progress, and where the class
    drives a callback every method and `release()` refused during a driving call."""
    cls = naming.upper_camel(shape.opaque.class_name)
    headings = {fn.name: h for h, fn in headed(api.function_groups, shape.functions())}
    drives = shape.drives()
    ctor, dtor = shape.ctor, shape.dtor
    locked = _locked(shape)
    counted = dtor is not None and not locked
    cached = [f"_cached_{p.name}" for p in shape.cached]
    slots = [
        "_handle",
        *(["_lock", "_finalizer"] if locked else []),
        *([_CALLS, "_finalizer"] if counted else []),
        *([_IN_CALL] if locked or drives else []),
        *cached,
        *(["__weakref__"] if dtor else []),
    ]
    m = _marshal(api, ctor, ctor.params, ctx=cls)
    state = [f"self._handle = _l_{shape.handle.name}"]
    if dtor is not None:
        dtor_c = naming.function_name(api.namespace, dtor.name)
        if locked:
            state += [
                "self._lock = _threading.Lock()",
                f"self._finalizer = _weakref.finalize(self, _finalize, _lib.{dtor_c}, self._handle, self._lock)",
            ]
        else:
            state += [
                f"self.{_CALLS} = [0]",
                f"self._finalizer = _weakref.finalize(self, _finalize_counted, _lib.{dtor_c}, self._handle, "
                f"self.{_CALLS})",
            ]
    if locked or drives:
        state.append(f"self.{_IN_CALL} = None")
    state += [f"self._cached_{p.name} = {_out_value(api, ctor, p, f'_l_{p.name}')}" for p in shape.cached]
    body = _body(
        api, ctor, m, first_args=[], receiver=[], busy=None, drives=False, counted=False, ok=state, returns=False
    )
    docs = [
        *([shape.opaque.docstring] if shape.opaque.docstring else []),
        (
            "Its calls are mutually exclusive: a call or a release during another call of the same object, "
            "from a callback or another thread, raises rather than waits."
            if locked
            else "Not safe for concurrent use: one thread at a time."
        ),
    ]
    refused = f'{_I * 2}raise TypeError("a {cls} owns its handle and cannot be copied")\n'
    out = [
        f"\n\n{_comment(heading)}class {cls}:\n",
        _docstring(docs, indent=_I),
        f"{_I}__slots__ = ({', '.join(repr(s) for s in slots)}{',' if len(slots) == 1 else ''})\n",
        f"\n{_comment(headings[ctor.name], indent=_I)}{_I}def __init__({', '.join(['self', *m.params])}):\n",
        _docstring(ctor.docs(), indent=_I * 2),
        _block(body, _I * 2),
        f"\n{_I}def __copy__(self):\n{refused}",
        f"\n{_I}def __deepcopy__(self, memo):\n{refused}",
        f"\n{_I}def __reduce_ex__(self, protocol):\n{refused}",
        f"\n{_I}@property\n{_I}def handle(self):\n{_I * 2}return self._handle\n",
    ]
    out += [f"\n{_I}@property\n{_I}def {p.name}(self):\n{_I * 2}return self._cached_{p.name}\n" for p in shape.cached]
    live = f'if self._handle is None:\n{_I}raise ValueError("{cls} used after {dtor.name}")' if locked else None
    for fn in shape.methods:
        m = _marshal(api, fn, fn.params[1:], ctx=f"{cls}.{fn.name}")
        busy = _receiver_busy(api, fn, cls=cls, name=fn.name)
        if locked:
            receiver = [live]
        elif drives:
            receiver = [_in_call_guard(busy)]
        else:
            receiver = []
        body = _body(
            api,
            fn,
            m,
            first_args=["self._handle"],
            receiver=receiver,
            busy=busy if locked else None,
            drives=not locked and any(p.callback for p in fn.params),
            counted=counted,
            ok=[],
            returns=True,
        )
        out.append(
            f"\n{_comment(headings[fn.name], indent=_I)}{_I}def {fn.name}({', '.join(['self', *m.params])}):\n"
            + _docstring(fn.docs(), indent=_I * 2)
            + _block(body, _I * 2)
        )
    if dtor is not None:
        release = (
            _locked_release(api, dtor, cls=cls, live=live)
            if locked
            else _counted_release(api, dtor, cls=cls, drives=drives)
        )
        out.append(
            f"\n{_comment(headings[dtor.name], indent=_I)}{_I}def release(self):\n"
            + _docstring(dtor.docs(), indent=_I * 2)
            + _block(release, _I * 2)
            + f"\n{_I}def __enter__(self):\n{_I * 2}return self\n"
            + f"\n{_I}def __exit__(self, *exc_info):\n{_I * 2}self.release()\n{_I * 2}return False\n"
        )
    return "".join(out)


def _locked_release(api: Api, dtor: Function, *, cls: str, live: str) -> list[str]:
    """A locked class's `release()` statements, holding the object's lock: refused where
    released, then the finalizer detached, the object's handle taken, the dtor called and the
    handle cleared in place for every holder; then the result checked."""
    fname = naming.function_name(api.namespace, dtor.name)
    guarded = [
        live,
        "self._finalizer.detach()",
        "handle, self._handle = self._handle, None",
        f"_raw = _lib.{fname}(handle)",
        "handle.value = None",
    ]
    return [
        *_holding(guarded, busy=_receiver_busy(api, dtor, cls=cls, name="release"), fname=fname),
        *_result_check(api, dtor),
    ]


def _counted_release(api: Api, dtor: Function, *, cls: str, drives: bool) -> list[str]:
    """An unlocked class's `release()` statements: refused during a driving call; the finalizer
    detached; the dtor called, counted as in progress; the handle cleared in place for every
    holder, the object keeping it, so every later call, a second release included, passes the
    null handle to the library; then the result checked."""
    return [
        *([_in_call_guard(_receiver_busy(api, dtor, cls=cls, name="release"))] if drives else []),
        "self._finalizer.detach()",
        f"self.{_CALLS}[0] += 1",
        "try:",
        f"{_I}_raw = _lib.{naming.function_name(api.namespace, dtor.name)}(self._handle)",
        "finally:",
        f"{_I}self.{_CALLS}[0] -= 1",
        "self._handle.value = None",
        *_result_check(api, dtor),
    ]


def _function(api: Api, fn: Function, *, heading: str | None) -> str:
    """A function no class renders, at module scope."""
    m = _marshal(api, fn, fn.params, ctx=fn.name)
    body = _body(api, fn, m, first_args=[], receiver=[], busy=None, drives=False, counted=False, ok=[], returns=True)
    return (
        f"\n\n{_comment(heading)}def {fn.name}({', '.join(m.params)}):\n"
        + _docstring(fn.docs(), indent=_I)
        + _block(body, _I)
    )
