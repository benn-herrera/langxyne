"""Load, validate and normalise an .adef.toml API definition.

Parameter and field order is document order. The loader relies on `tomllib`
building insertion-ordered dicts, so iterating a table yields its keys in the
order they appear in the file.
"""

import functools
import json
import re
import tomllib
from collections.abc import Callable, Container, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Generic, TypeVar

try:
    import jsonschema
except ImportError:
    jsonschema = None

from langxyne import naming

BUILTIN_TYPES = frozenset({*naming.BUILTIN_C_TYPES, "memory", naming.TEXT})
# The labels a duplicate objection names the text type and its resolver by.
TEXT_DEFINER = f"the builtin type {naming.TEXT}"
RESOLVER_DEFINER = "the generated text resolver"
# ...and the types and conversion an output defines once where some union declares `_mixed_type_list`.
UNION_ERROR_DEFINER = "the generated union error"
UNION_CLAUSE_DEFINER = "the generated union clause"
UNION_CLAUSE_TEXT_DEFINER = "the generated union clause text"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_LOWERCASE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*\Z")
_LITERAL_TERM = re.compile(r"(-?)(?:0x([0-9a-fA-F]+)|([0-9]+))\Z")
# It lands in Rust and Lua string literals, a linker's -l flag and a file name; a dot would
# stop LuaJIT appending the platform's extension, and LuaJIT adds no `lib` prefix to a name
# that has one, where a linker does.
_LIBRARY_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")
FORMATS = ("dec", "hex")
REFS = ("in", "out", "inout")
# a group's members are named items
NAMED_KINDS = ("typed_const", "opaque_ref", "boxed_scalar", "struct", "union", "callback", "function")
TABLES = frozenset({"_general", "untyped_bit_const", "untyped_const", "string_const", *NAMED_KINDS, "_wrapped_api"})
GROUP_PROPERTIES = frozenset({"_docstring", "_base_type", "_to_string"})
STRING_GROUP_PROPERTIES = frozenset({"_docstring"})  # a string constant has no fixed-width representation
NAMED_GROUP_PROPERTIES = frozenset({"_docstring"})  # a group of a named kind; its members are its items
OPAQUE_PROPERTIES = frozenset({"_docstring", "_class", "_ctor", "_dtor", "_hides_pointer"})
BOXED_PROPERTIES = frozenset({"_docstring", "_base_type"})
CONST_ATTRIBUTES = frozenset({"_value", "_docstring", "_format"})
FIELD_ATTRIBUTES = frozenset({"_type", "_docstring"})
PARAM_ATTRIBUTES = frozenset({"_type", "_ref", "_count", "_optional", "_wrote_needed", "_docstring"})
CALLBACK_PARAM_ATTRIBUTES = frozenset({"_type", "_ref", "_count", "_docstring"})
UNION_PROPERTIES = frozenset({"_docstring", "_mixed_type_list"})
MEMBER_ATTRIBUTES = frozenset({"_tag", "_type", "_docstring"})
# a union's prefix begins with its tag, then any u8 fields, then its record's byte length
PREFIX_TAG_TYPES = ("u8", "u16", "u32")
PREFIX_LENGTH_TYPES = ("u16", "u32")
COUNT_BITS = {"u8": 8, "u16": 16, "u32": 32, "u64": 64}
COUNT_TYPES = tuple(COUNT_BITS)
FLOAT_TYPES = ("f32", "f64")
INTEGER_TYPES = tuple(t for t in naming.BUILTIN_C_TYPES if t not in FLOAT_TYPES)  # a boxed scalar's _base_type


class DefinitionError(Exception):
    """The definition cannot be turned into an API."""

    def objections(self) -> tuple["DefinitionError", ...]:
        """Each objection this error carries, in order: itself alone."""
        return (self,)


class NotImplementedDefinition(DefinitionError):
    """The definition says something the format allows and the generator cannot produce yet."""


class DefinitionErrors(DefinitionError):
    """Several objections to one definition, in the document order of the items they concern."""

    def __init__(self, errors: Sequence[DefinitionError]) -> None:
        super().__init__("\n".join(str(e) for e in errors))
        self.errors = tuple(errors)

    def objections(self) -> tuple[DefinitionError, ...]:
        return self.errors


# The item an objection's `where` names: its table, then an array index or a name.
_WHERE = re.compile(r"(\w+)(?:\[(\d+)\])?(?:\.(\w+))?")
T = TypeVar("T")


class _Objections:
    """The loader's objections, collected item by item and raised together at the end,
    ordered by where each item stands in `data`. Without `data`, they keep the order found,
    which is document order for one item's own members."""

    def __init__(self, data: Mapping | None = None) -> None:
        self._data = data if data is not None else {}
        self._found: list[tuple[tuple[int, int, int], DefinitionError]] = []
        self.failed: set[str] = set()  # the `where` of every item that drew an objection

    @contextmanager
    def item(self, where: str) -> Iterator[None]:
        """Runs the block as the item at `where`, recording a `DefinitionError` it raises."""
        try:
            yield
        except DefinitionError as e:
            self.record(e, where)

    def record(self, error: DefinitionError, where: str) -> None:
        self.failed.add(where)
        position = self._position(where)
        self._found += [(position, e) for e in error.objections()]

    def raise_any(self) -> None:
        """Raises what was recorded: a lone objection as itself, several as `DefinitionErrors`."""
        errors = [e for _, e in sorted(self._found, key=lambda found: found[0])]
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise DefinitionErrors(errors)

    def _position(self, where: str) -> tuple[int, int, int]:
        """(the table's position among the top-level tables, the group's within that array,
        the member's within that group) for `where` such as `function.open_port.unit`,
        `untyped_const[1]`, `function[1].open` or `untyped_bit_const.feat_a`; a named member
        stands in the first group holding it, and a group itself before its members."""
        match = _WHERE.match(where)
        assert match is not None  # every where begins with its table's name
        category, index, name = match.groups()
        tables = list(self._data)
        if category not in tables:
            return len(tables), 0, 0
        table = self._data[category]
        groups = [g if isinstance(g, dict) else {} for g in table] if isinstance(table, list) else []
        if index is not None:
            group = int(index)
        else:
            group = next((i for i, members in enumerate(groups) if name in members), 0)
        members = list(groups[group]) if group < len(groups) else []
        return tables.index(category), group, members.index(name) if name in members else -1


@dataclass(frozen=True, kw_only=True)
class Node:
    """Every item of the tree: its name as the definition writes it, and its docstring."""

    name: str
    docstring: str | None


@dataclass(frozen=True)
class LiteralTerm:
    """A composed entry's literal term, parsed once by the loader."""

    value: int
    format: str  # one of FORMATS: the base the definition wrote it in


# A composed entry's term: the name of an earlier entry, or a literal.
Term = str | LiteralTerm


@dataclass(frozen=True, kw_only=True)
class BitConst(Node):
    """An `untyped_bit_const` entry: a single bit, or a sum of earlier entries and literals."""

    bit: int | None  # set for a single bit
    parts: tuple[Term, ...]  # set for a sum, in the order written
    value: int  # the resolved value: 1 << bit, or the (overlap-checked) sum of parts
    format: str  # one of FORMATS: how a literal of the value is spelled


@dataclass(frozen=True, kw_only=True)
class EnumEntry(Node):
    """An integer constant: a typed enum's entry, or a plain `untyped_const` group's, which
    alone may be a sum."""

    value: int
    format: str  # one of FORMATS
    parts: tuple[Term, ...] = ()  # set for a plain-group sum, in the order written


@dataclass(frozen=True, kw_only=True)
class StringConst(Node):
    value: str  # holds no '"', '\' or control character, so it is a valid C and Lua literal as-is


Entry = TypeVar("Entry", bound=Node)


@dataclass(frozen=True, kw_only=True)
class Group(Node, Generic[Entry]):
    """One table of a top-level array: a constant group's entries, or the items of a group of
    a named kind (`typed_const`, `opaque_ref`, `boxed_scalar`, `struct`, `union`, `callback`,
    `function`). A group
    has no name in the definition, so `name` is where it is, `untyped_const[0]`, never an
    identifier."""

    base_type: str | None  # a key of naming.BASE_C_TYPES; None for a string group and a named kind's
    to_string: str | None  # the conversion function's name; always None for a string group and a named kind's
    entries: tuple[Entry, ...]


def headed(groups: Iterable[Group[Entry]], run: Iterable[Entry] | None = None) -> list[tuple[str | None, Entry]]:
    """(heading, item) for each item of `run`, the items an output renders together in the
    order it renders them, by default every item of `groups` in document order: the heading
    is the item's group's docstring where the item is the first of its group's in `run`,
    else None, so a group's docstring heads the first of its items wherever they render."""
    groups = tuple(groups)
    group_of = {item.name: group for group in groups for item in group.entries}
    pairs: list[tuple[str | None, Entry]] = []
    seen: set[str] = set()
    for item in (item for group in groups for item in group.entries) if run is None else run:
        group = group_of[item.name]
        pairs.append((group.docstring if group.name not in seen else None, item))
        seen.add(group.name)
    return pairs


def single_bit_entries(group: Group[BitConst]) -> tuple[BitConst, ...]:
    """`group`'s entries whose value has exactly one bit set, in document order: what a bit
    group's conversion decomposes a value into; a multi-bit composed entry is never one."""
    return tuple(c for c in group.entries if c.value > 0 and c.value & (c.value - 1) == 0)


def named_values(group: Group[EnumEntry]) -> tuple[EnumEntry, ...]:
    """One entry per distinct value of a plain group, in the order the values first appear,
    each the later entry where two share a value: what a plain group's conversion names a
    value by. The loader refuses a shared value in an enum, so an enum needs no such step."""
    return tuple({e.value: e for e in group.entries}.values())


@dataclass(frozen=True, kw_only=True)
class TypedConst(Node):
    entries: tuple[EnumEntry, ...]
    base_type: str  # a key of naming.BASE_C_TYPES
    to_string: str | None  # the conversion function's name


@dataclass(frozen=True, kw_only=True)
class OpaqueRef(Node):
    ctor: str | None  # function with exactly one out parameter of this type
    dtor: str | None  # function taking only this type by value; set only with ctor
    class_name: str  # `_class`, lowercase, or else the ref's name; each binding applies its own casing
    hides_pointer: bool  # `_hides_pointer`: the handle is a raw pointer the library does not validate


@dataclass(frozen=True, kw_only=True)
class BoxedScalar(Node):
    base_type: str  # one of INTEGER_TYPES


@dataclass(frozen=True, kw_only=True)
class Field(Node):
    type: str


@dataclass(frozen=True, kw_only=True)
class Struct(Node):
    fields: tuple[Field, ...]


@dataclass(frozen=True, kw_only=True)
class UnionMember(Node):
    """One of a union's members: the `untyped_const` entry its prefix's tag holds, and its struct."""

    tag: str
    struct: str


@dataclass(frozen=True, kw_only=True)
class Union(Node):
    """A tagged union: its members, every one's struct beginning with the struct `prefix`, whose
    first field is the tag and whose first field after it not `u8` is the record's own byte
    length."""

    prefix: str  # inferred: the type of every member struct's first field
    tag_field: str  # the prefix's field holding a member's tag
    length_field: str  # the prefix's field holding the record's byte length
    members: tuple[UnionMember, ...]
    mixed_type_list: bool  # `_mixed_type_list`: its members lie in a list back to back, each by its own size
    count_type: str = "u32"  # the `_count` of every counted parameter of it, one per union; u32 where none is


@dataclass(frozen=True, kw_only=True)
class Param(Node):
    """A function parameter, in its function's document order."""

    type: str  # a buffer's element type, `memory` for bytes
    ref: str | None  # one of REFS; None is by value
    count_type: str | None  # a buffer's, one of COUNT_TYPES: the type of its count and its reports
    optional: bool  # only with a ref, and on a buffer only with ref "in"
    wrote_needed: bool  # only on an "out" buffer: the callee reports what it wrote and needs
    callback: bool = False  # a function's parameter of a callback type, by value
    is_union: bool = False  # a sequence of a union's members, a buffer whose `type` is the union

    @property
    def is_buffer(self) -> bool:
        """`memory`, a typed array or a sequence: a pointer the C signature follows with its count."""
        return self.count_type is not None

    def derived_names(self) -> tuple[str, ...]:
        """The C parameters this one brings after itself, in C order: a buffer its count, then
        with `_wrote_needed` its two reports, or for a sequence its byte extent; a callback its
        `user_data`; none for any other."""
        if self.callback:
            return (self.user_data_name(),)
        if not self.is_buffer:
            return ()
        if self.is_union:
            return (self.count_name(), self.bytes_name())
        return (self.count_name(), *self.report_names())

    def count_name(self) -> str:
        """A buffer's count parameter, of elements, bytes or a sequence's members."""
        return naming.count_param(self.name)

    def bytes_name(self) -> str:
        """A sequence's byte extent parameter."""
        return naming.bytes_param(self.name)

    def report_names(self) -> tuple[str, ...]:
        """A buffer's reports, what it wrote and what it needs, where it has `_wrote_needed`."""
        return (naming.wrote_param(self.name), naming.needed_param(self.name)) if self.wrote_needed else ()

    def user_data_name(self) -> str:
        """A callback parameter's `user_data` pointer."""
        return naming.user_data_param(self.name)


@dataclass(frozen=True, kw_only=True)
class Function(Node):
    """A function, or a callback type's signature: its `_return` enum's name and its
    parameters. A callback's parameters are by value or views, `in` buffers. A function's
    `stack_mb` is the `untyped_const` entry its `_stack_mb` names, the stack in MiB a call needs
    on the caller's thread where the library runs it there."""

    returns: str
    params: tuple[Param, ...]
    stack_mb: EnumEntry | None = None

    def docs(self) -> list[str]:
        """The function's docstring, if any, followed by each parameter's as `name: text`."""
        docs = [self.docstring] if self.docstring else []
        docs += [f"{p.name}: {p.docstring}" for p in self.params if p.docstring]
        return docs


@dataclass(frozen=True)
class ClassShape:
    """What an object-semantics binding builds for an opaque ref with a `_ctor`, as the
    definition states it."""

    opaque: OpaqueRef
    ctor: Function
    handle: Param  # the ctor's one `out` parameter of the opaque's type
    cached: tuple[Param, ...]  # the ctor's other `out` parameters, each kept on the object
    methods: tuple[Function, ...]  # every other function but the dtor whose first parameter is the opaque by value
    dtor: Function | None

    def class_params(self) -> list[tuple[Function, tuple[Param, ...], bool]]:
        """(function, the parameters the class renders, whether it is the ctor) for the ctor
        and each method: the ctor's every parameter, a method's all but its first, which
        is the handle the object holds. The dtor renders none."""
        return [(self.ctor, self.ctor.params, True), *((fn, fn.params[1:], False) for fn in self.methods)]

    def drives(self) -> bool:
        """Whether a method of the class takes a callback, so that a call of an object can be
        in progress while the consumer's code runs: every binding then refuses the object, as
        receiver or argument, until that call returns."""
        return any(p.callback for fn in self.methods for p in fn.params)

    def functions(self) -> list[Function]:
        """The functions the class renders, in the order every binding renders them: the
        ctor, each method, the dtor."""
        return [self.ctor, *self.methods, *([self.dtor] if self.dtor is not None else [])]

    def members(self, own: Iterable[str]) -> list[tuple[str, str]]:
        """(where, name) of every member the class defines: `own`, the members a binding
        generates itself, then each method and each cached `out` under its parameter's name."""
        members = [("the class's own member", name) for name in own]
        members += [(f"function.{fn.name}", fn.name) for fn in self.methods]
        members += [(f"function.{self.ctor.name}.{p.name}", p.name) for p in self.cached]
        return members


@dataclass(frozen=True)
class WrappedApi:
    """`[_wrapped_api]`: the wrapped API, as its C headers (`_headers`), which the
    implementation includes, and the constants of this API pinned to those headers' macros
    (`_pinned_value`)."""

    headers: tuple[str, ...]  # each relative to the project directory, in list order, none twice
    pins: tuple[tuple[str, str], ...]  # (untyped_bit_const name, the headers' macro it equals)


@dataclass(frozen=True)
class Library:
    """The library the outputs that load or link one reach: its platform-neutral `name`
    (`_general._bound_library`, or `--library`), `None` where neither names one, and how a
    consumer's build links it, `link`, one of `naming.LINK_MODES`."""

    name: str | None
    link: str


@dataclass(frozen=True)
class Api:
    name: str
    namespace: str
    version: tuple[int, int, int, int]
    library: Library
    bit_const_groups: tuple[Group[BitConst], ...]
    const_groups: tuple[Group[EnumEntry], ...]
    string_const_groups: tuple[Group[StringConst], ...]
    typed_const_groups: tuple[Group[TypedConst], ...]
    opaque_ref_groups: tuple[Group[OpaqueRef], ...]
    boxed_scalar_groups: tuple[Group[BoxedScalar], ...]
    struct_groups: tuple[Group[Struct], ...]
    union_groups: tuple[Group[Union], ...]
    callback_groups: tuple[Group[Function], ...]
    function_groups: tuple[Group[Function], ...]
    wrapped_api: WrappedApi | None

    @property
    def typed_consts(self) -> tuple[TypedConst, ...]:
        """Every enum across the groups, in document order."""
        return tuple(t for g in self.typed_const_groups for t in g.entries)

    @property
    def opaque_refs(self) -> tuple[OpaqueRef, ...]:
        """Every opaque ref across the groups, in document order."""
        return tuple(o for g in self.opaque_ref_groups for o in g.entries)

    @property
    def boxed_scalars(self) -> tuple[BoxedScalar, ...]:
        """Every boxed scalar across the groups, in document order."""
        return tuple(b for g in self.boxed_scalar_groups for b in g.entries)

    @property
    def structs(self) -> tuple[Struct, ...]:
        """Every struct across the groups, in document order."""
        return tuple(s for g in self.struct_groups for s in g.entries)

    @property
    def unions(self) -> tuple[Union, ...]:
        """Every union across the groups, in document order."""
        return tuple(u for g in self.union_groups for u in g.entries)

    def listed_unions(self) -> list[Union]:
        """The unions declaring `_mixed_type_list`, in document order: those whose members lie in
        a list, the only ones an output renders more than the structs of."""
        return [u for u in self.unions if u.mixed_type_list]

    def union(self, name: str) -> Union:
        """The union named `name`."""
        return next(u for u in self.unions if u.name == name)

    def prefix_fields(self, union: Union) -> tuple[Field, Field]:
        """`union`'s prefix's tag field and length field."""
        fields = {f.name: f for s in self.structs if s.name == union.prefix for f in s.fields}
        return fields[union.tag_field], fields[union.length_field]

    @property
    def callbacks(self) -> tuple[Function, ...]:
        """Every callback type across the groups, in document order."""
        return tuple(c for g in self.callback_groups for c in g.entries)

    @property
    def functions(self) -> tuple[Function, ...]:
        """Every function across the groups, in document order."""
        return tuple(f for g in self.function_groups for f in g.entries)

    @property
    def bit_consts(self) -> tuple[BitConst, ...]:
        """Every untyped_bit_const entry across the groups, in document order."""
        return tuple(c for g in self.bit_const_groups for c in g.entries)

    @property
    def consts(self) -> tuple[EnumEntry, ...]:
        """Every untyped_const entry across the groups, in document order."""
        return tuple(c for g in self.const_groups for c in g.entries)

    @property
    def string_consts(self) -> tuple[StringConst, ...]:
        """Every string_const entry across the groups, in document order."""
        return tuple(c for g in self.string_const_groups for c in g.entries)

    def constant_names(self, *, enum_entries: bool = True, version: bool = False) -> list[tuple[str, str]]:
        """(where, name) for every constant of every kind in document order, typed enum
        entries last unless `enum_entries` is false, and with `version` the version constant
        first: everything that becomes a `naming.const_name`."""
        names = [("the API version constant", naming.VERSION_KEY)] if version else []
        names += [(f"untyped_bit_const.{c.name}", c.name) for c in self.bit_consts]
        names += [(f"untyped_const.{c.name}", c.name) for c in self.consts]
        names += [(f"string_const.{c.name}", c.name) for c in self.string_consts]
        if enum_entries:
            names += [(f"typed_const.{t.name}.{e.name}", e.name) for t in self.typed_consts for e in t.entries]
        return names

    def c_identifiers(self) -> list[tuple[str, str]]:
        """(where, C identifier) for every constant and declaration the header names from the
        definition, in the header's order: the version and every constant, the text type where
        some field is text, then each enum, opaque ref and its incomplete struct, boxed scalar,
        struct, callback type and function."""
        ns = self.namespace
        idents = [(where, naming.const_name(ns, name)) for where, name in self.constant_names(version=True)]
        if self.uses_text():
            idents.append((TEXT_DEFINER, naming.type_name(ns, naming.TEXT)))
        idents += [(f"typed_const.{t.name}", naming.type_name(ns, t.name)) for t in self.typed_consts]
        for o in self.opaque_refs:
            where = f"opaque_ref.{o.name}"
            idents += [(where, naming.type_name(ns, o.name)), (where, naming.opaque_struct(ns, o.name))]
        idents += [(f"boxed_scalar.{b.name}", naming.type_name(ns, b.name)) for b in self.boxed_scalars]
        idents += [(f"struct.{s.name}", naming.type_name(ns, s.name)) for s in self.structs]
        idents += [(f"callback.{c.name}", naming.type_name(ns, c.name)) for c in self.callbacks]
        idents += [(f"function.{f.name}", naming.function_name(ns, f.name)) for f in self.functions]
        return idents

    def classes(self) -> tuple[ClassShape, ...]:
        """One shape per opaque ref that names a `_ctor`, in document order."""
        functions = {f.name: f for f in self.functions}
        shapes = []
        for o in self.opaque_refs:
            if o.ctor is None:
                continue
            ctor = functions[o.ctor]
            shapes.append(
                ClassShape(
                    opaque=o,
                    ctor=ctor,
                    handle=next(p for p in ctor.params if p.type == o.name and p.ref == "out"),
                    cached=tuple(p for p in ctor.params if p.ref == "out" and p.type != o.name),
                    methods=tuple(
                        f
                        for f in self.functions
                        if f.name not in (o.ctor, o.dtor)
                        and f.params
                        and f.params[0].type == o.name
                        and f.params[0].ref is None
                    ),
                    dtor=None if o.dtor is None else functions[o.dtor],
                )
            )
        return tuple(shapes)

    def free_functions(self) -> tuple[Function, ...]:
        """Every function no class renders as its ctor, a method or its dtor, in document
        order: what a binding renders at module scope."""
        rendered = {fn.name for shape in self.classes() for fn in shape.functions()}
        return tuple(fn for fn in self.functions if fn.name not in rendered)

    def success_entry(self, fn: Function) -> EnumEntry:
        """The zero-valued entry of `fn`'s return enum, which the loader requires: a function's
        success, a callback's continue."""
        returns = next(t for t in self.typed_consts if t.name == fn.returns)
        return next(e for e in returns.entries if e.value == 0)

    def first_nonzero_entry(self, fn: Function) -> EnumEntry | None:
        """The first entry of `fn`'s return enum in document order whose value is not 0, `None`
        where there is none: a callback's stop (`stop_entry()`), and what a binding answers for a
        method of an object refused while a call of that object drives a callback."""
        returns = next(t for t in self.typed_consts if t.name == fn.returns)
        return next((e for e in returns.entries if e.value != 0), None)

    def stop_entry(self, callback: Function) -> EnumEntry:
        """`first_nonzero_entry()` of `callback`, which the loader requires a callback to have:
        what a binding answers for a callback whose consumer code failed."""
        entry = self.first_nonzero_entry(callback)
        assert entry is not None
        return entry

    def callback(self, type_name: str) -> Function:
        """The callback type named `type_name`."""
        return next(c for c in self.callbacks if c.name == type_name)

    def uses_text(self) -> bool:
        """Whether some struct field is `text`: the outputs render the text type only then."""
        return any(f.type == naming.TEXT for s in self.structs for f in s.fields)

    def uses_64_bit(self) -> bool:
        """Whether some value position holds an `i64` or `u64`: a struct field, a function's or
        callback type's parameter whatever its ref, an array's element included, or its return,
        or a boxed scalar's `_base_type`. A `_count` of `"u64"` is a count width, not a value,
        so it never counts: the binding's count reports stay cdata without the support
        module."""
        _64_BIT = frozenset({"i64", "u64"})
        if any(f.type in _64_BIT for s in self.structs for f in s.fields):
            return True
        return (
            any(p.type in _64_BIT for f in self.functions for p in f.params)
            or any(f.returns in _64_BIT for f in self.functions)
            or any(b.base_type in _64_BIT for b in self.boxed_scalars)
            or any(p.type in _64_BIT for cb in self.callbacks for p in cb.params)
            or any(cb.returns in _64_BIT for cb in self.callbacks)
        )

    def kind(self, type_name: str) -> str:
        """One of "builtin", "text", "enum", "opaque", "boxed", "struct", "union", "callback" for
        a validated type name: `text` is a builtin rendered as a struct, so it is a kind of its
        own."""
        if type_name == naming.TEXT:
            return "text"
        if type_name in BUILTIN_TYPES:
            return "builtin"
        if any(t.name == type_name for t in self.typed_consts):
            return "enum"
        if any(o.name == type_name for o in self.opaque_refs):
            return "opaque"
        if any(b.name == type_name for b in self.boxed_scalars):
            return "boxed"
        if any(s.name == type_name for s in self.structs):
            return "struct"
        if any(u.name == type_name for u in self.unions):
            return "union"
        if any(c.name == type_name for c in self.callbacks):
            return "callback"
        raise KeyError(type_name)

    def layout(self, type_name: str) -> tuple[int, int]:
        """(size, alignment) in bytes of `type_name` as C lays it out on every target: a builtin
        scalar its width for both, the text type, an enum or boxed scalar its fields' or base
        type's, a struct its fields at their aligned offsets, rounded up to its alignment. The
        one layout model: `KeyError` for a type with no layout of its own (`memory`, an opaque
        ref, a callback type, a union) or a struct holding an opaque ref."""
        return _layout(type_name, _layout_types(self.structs, self.typed_consts, self.boxed_scalars))

    def field_offsets(self, type_name: str) -> tuple[tuple[str, str, int], ...]:
        """(name, type, offset in bytes) of each field of the struct `type_name`, or of the text
        type's, in declaration order, where `layout()` lays it: the one layout model's."""
        if type_name == naming.TEXT:
            fields = naming.TEXT_FIELDS
        else:
            fields = tuple((f.name, f.type) for f in next(s for s in self.structs if s.name == type_name).fields)
        types = _layout_types(self.structs, self.typed_consts, self.boxed_scalars)
        return tuple((n, t, o) for (n, t), o in zip(fields, _fields_layout(fields, types)[4]))

    def list_alignment(self, union: Union) -> int:
        """The alignment of `union`'s list, every record's: the largest alignment of any field in
        any member, the prefix's, since the loader holds every member to it. Every record's size
        is a multiple of it, so the C pointer to the prefix carries it to every record."""
        return self.layout(union.prefix)[1]

    def names(self) -> list[tuple[str, str]]:
        """(where, name) for every name the definition gives, in document order, `where`
        spelled as the loader's messages spell it: `function.open_port.unit`."""
        names = [("_general._namespace", self.namespace), *self.constant_names()]
        names += [
            (f"{g.name}._to_string", g.to_string)
            for g in (*self.bit_const_groups, *self.const_groups)
            if g.to_string is not None
        ]
        for t in self.typed_consts:
            names.append((f"typed_const.{t.name}", t.name))
            if t.to_string is not None:
                names.append((f"typed_const.{t.name}._to_string", t.to_string))
        for o in self.opaque_refs:
            names += [(f"opaque_ref.{o.name}", o.name), (f"opaque_ref.{o.name}._class", o.class_name)]
        names += [(f"boxed_scalar.{b.name}", b.name) for b in self.boxed_scalars]
        for s in self.structs:
            names.append((f"struct.{s.name}", s.name))
            names += [(f"struct.{s.name}.{f.name}", f.name) for f in s.fields]
        for u in self.unions:
            names.append((f"union.{u.name}", u.name))
            names += [(f"union.{u.name}.{m.name}", m.name) for m in u.members]
        for kind, signatures in (("callback", self.callbacks), ("function", self.functions)):
            for fn in signatures:
                names.append((f"{kind}.{fn.name}", fn.name))
                names += [(f"{kind}.{fn.name}.{p.name}", p.name) for p in fn.params]
        return names

    def version_value(self) -> int:
        """The version packed into one 32-bit value, most-significant byte first."""
        shifts = (24, 16, 8, 0)
        return sum(b << s for b, s in zip(self.version, shifts))


def duplicates(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Each name that `pairs`, (what defines it, name), holds more than once, with every
    definer in order, in the order the names are first seen."""
    definers: dict[str, list[str]] = {}
    for definer, name in pairs:
        definers.setdefault(name, []).append(definer)
    return {name: found for name, found in definers.items() if len(found) > 1}


def duplicate_objections(pairs: Iterable[tuple[str, str]], where: str) -> list[str]:
    """One objection per name that `pairs`, (what defines it, name), holds more than once,
    naming everything that defines it, as a binding reports a name it would define twice
    in `where`."""
    return [f"{where}: {n} would be defined more than once, by {' and '.join(s)}" for n, s in duplicates(pairs).items()]


def generated_name_objections(names: Iterable[tuple[str, str]], used: Container[str]) -> list[str]:
    """One objection per (where, name) of `names` whose name is in `used`: a name an output's
    generated code binds or reaches itself where that definition name would be in scope."""
    return [f"{where}: '{name}' is a name the generated code uses" for where, name in names if name in used]


_SCHEMA_PATH = Path(__file__).parent / "api_def.schema.json"


@functools.lru_cache(maxsize=1)
def _schema_validator() -> "jsonschema.Draft202012Validator":
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _line_note(lines: Sequence[str], error: "jsonschema.ValidationError") -> str:
    """The first document line that assigns the key the error concerns, as ` (line N: text)`;
    empty where no line does (a missing required key has none, and an array index is not a
    key, so the enclosing key's line stands)."""
    key: str | None = None
    if error.validator == "additionalProperties":
        unexpected = re.search(r"\('([^']+)' was unexpected\)", error.message)
        if unexpected:
            key = unexpected.group(1)
    if key is None:
        key = next((p for p in reversed(list(error.absolute_path)) if isinstance(p, str)), None)
    if key is None:
        return ""
    assign = re.compile(rf"(?:^|[\s{{,]){re.escape(key)}\s*=")
    for n, line in enumerate(lines, 1):
        if assign.search(line):
            return f" (line {n}: {line.strip()})"
    return ""


def _shape_objections(data: Mapping, lines: Sequence[str]) -> list[str]:
    """Every objection `api_def.schema.json` has to the parsed definition, one per schema
    error, ordered by its pointer: `schema: {pointer}: {message}` with the document line of
    the key it concerns where one names a key."""
    objections = []
    for error in sorted(
        _schema_validator().iter_errors(data), key=lambda e: (_pointer(e), str(e.validator), e.message)
    ):
        objections.append(f"schema: {_pointer(error)}: {error.message}{_line_note(lines, error)}")
    return objections


def _pointer(error: "jsonschema.ValidationError") -> str:
    """The error's location in the document as a JSON pointer: `/` at the root."""
    return "/" + "/".join(str(p) for p in error.absolute_path)


def load(path: Path, *, schema: bool = True) -> Api:
    """The definition in the file at `path` as an `Api`; see `from_dict()`.

    `from_dict()` is the authority on every rule. Where `schema` holds and `jsonschema`
    imports, a pass against `api_def.schema.json` runs first; a definition it refuses draws its
    objections in place of the loader's, each naming the JSON pointer and document line of the
    key at fault."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise DefinitionError(str(e)) from e
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise DefinitionError(str(e)) from e
    if schema and jsonschema is not None:
        objections = _shape_objections(data, text.splitlines())
        if objections:
            raise DefinitionErrors([DefinitionError(o) for o in objections])
    return from_dict(data)


def from_dict(data: Mapping) -> Api:
    """The definition in `data` as an `Api`, else a `DefinitionError` carrying every objection
    found, in the document order of the items they concern (`DefinitionError.objections()`).

    Every kind is an array of groups. Each item (a constant group, a typed enum, an opaque
    ref, a boxed scalar, a struct, a union, a callback type, a function, `[_wrapped_api]`) is
    parsed on its own, as are a named kind's group's own properties, each field of a struct, each
    member of a union and each parameter and the
    `_return` of a function, so one mistake does not hide another. The checks across items
    then run over what parsed; one whose subject failed to parse is skipped, and a reference to an item that failed reports an unknown name. A
    failure that leaves nothing to parse stops alone: an unknown top-level table, a missing
    or malformed `[_general]`, and in `load()` a file that is not UTF-8 TOML.
    """
    unknown = sorted(set(data) - TABLES)
    if unknown:
        raise DefinitionError(f"unknown table(s) {', '.join(f'[{k}]' for k in unknown)}")
    general = data.get("_general")
    if not isinstance(general, dict):
        raise DefinitionError("missing [_general] table")
    _reject_unknown(general, {"_name", "_namespace", "_version", "_bound_library"}, "_general")

    api_name = general.get("_name")
    if not isinstance(api_name, str):
        raise DefinitionError("_general._name must be an identifier string")
    _identifier(api_name, "_general._name")
    namespace = general.get("_namespace")
    if not isinstance(namespace, str):
        raise DefinitionError("_general._namespace must be an identifier string")
    _identifier(namespace, "_general._namespace")
    version = general.get("_version")
    if not (isinstance(version, list) and len(version) == 4 and all(_is_int(v) and 0 <= v <= 255 for v in version)):
        raise DefinitionError("_general._version must be a list of 4 integers in 0..255")
    library = general.get("_bound_library")
    if library is not None and not isinstance(library, str):
        raise DefinitionError("_general._bound_library must be a string")
    if library is not None:
        check_library_name(library, "_general._bound_library")

    objections = _Objections(data)
    resolved_bits: dict[str, tuple[int, str]] = {}
    bit_const_groups = _constant_groups(
        data,
        "untyped_bit_const",
        objections,
        lambda where, body: _bit_const_group(where, body, resolved=resolved_bits),
    )
    resolved_consts: dict[str, tuple[int, str]] = {}
    const_groups = _constant_groups(
        data, "untyped_const", objections, lambda where, body: _const_group(where, body, resolved=resolved_consts)
    )
    string_const_groups = _constant_groups(data, "string_const", objections, _string_group)
    outlines = {kind: _named_groups(data, kind, objections) for kind in NAMED_KINDS}
    typed_consts = _parse_items(outlines["typed_const"], "typed_const", objections, _typed_const)
    opaque_refs = _parse_items(outlines["opaque_ref"], "opaque_ref", objections, _opaque_ref)
    boxed_scalars = _parse_items(outlines["boxed_scalar"], "boxed_scalar", objections, _boxed_scalar)
    struct_tables = [member for group in outlines["struct"] for member in group.members]
    union_tables = [member for group in outlines["union"] for member in group.members]
    callback_tables = [member for group in outlines["callback"] for member in group.members]

    type_names: dict[str, str] = {}
    for category, names in (
        ("typed_const", [t.name for t in typed_consts]),
        ("opaque_ref", [o.name for o in opaque_refs]),
        ("boxed_scalar", [b.name for b in boxed_scalars]),
        ("union", [name for name, _ in union_tables]),
        ("struct", [name for name, _ in struct_tables]),
        ("callback", [name for name, _ in callback_tables]),
    ):
        for name in names:
            with objections.item(f"{category}.{name}"):
                if name in BUILTIN_TYPES:
                    raise DefinitionError(f"{category}.{name}: shadows builtin type {name}")
                if name in type_names:
                    raise DefinitionError(f"{category}.{name}: type name already defined in {type_names[name]}")
                type_names[name] = category
    # a type whose name failed is skipped from here on, so its clash reports once
    typed_consts = tuple(t for t in typed_consts if f"typed_const.{t.name}" not in objections.failed)
    opaque_refs = tuple(o for o in opaque_refs if f"opaque_ref.{o.name}" not in objections.failed)
    boxed_scalars = tuple(b for b in boxed_scalars if f"boxed_scalar.{b.name}" not in objections.failed)

    structs: list[Struct] = []
    for name, body in struct_tables:
        where = f"struct.{name}"
        if where in objections.failed:
            continue  # its name is another type's
        with objections.item(where):
            structs.append(_struct(name, body, type_names, defined_structs={s.name for s in structs}))
        if where in objections.failed:
            del type_names[name]  # so a later use of it reports an unknown type

    unions: list[Union] = []
    tags = {c.name: c for g in const_groups for c in g.entries}
    layout_types = _layout_types(structs, typed_consts, boxed_scalars)
    for name, body in union_tables:
        where = f"union.{name}"
        if where in objections.failed:
            continue  # its name is another type's
        with objections.item(where):
            unions.append(_union(name, body, type_names=type_names, tags=tags, layout_types=layout_types))
        if where in objections.failed:
            del type_names[name]  # so a later use of it reports an unknown type

    enums = {t.name: t for t in typed_consts}
    lists = {u.name for u in unions if u.mixed_type_list}
    callbacks: list[Function] = []
    for name, body in callback_tables:
        where = f"callback.{name}"
        if where in objections.failed:
            continue  # its name is another type's
        with objections.item(where):
            callbacks.append(_callback(name, body, type_names, enums, lists))
        if where in objections.failed:
            del type_names[name]  # so a later use of it reports an unknown type

    functions = _parse_items(
        outlines["function"],
        "function",
        objections,
        lambda name, body: _function(name, body, type_names, enums, lists, tags),
    )
    functions_by_name = {f.name: f for f in functions}
    for o in opaque_refs:
        if any(f"function.{f}" in objections.failed for f in (o.ctor, o.dtor) if f is not None):
            continue  # the function it names has its own objection
        with objections.item(f"opaque_ref.{o.name}"):
            _check_lifecycle(o, functions_by_name)
    signatures = [("callback", c) for c in callbacks] + [("function", f) for f in functions]
    unions = _counted_unions(unions, signatures, objections)

    wrapped_api = None
    with objections.item("_wrapped_api"):
        wrapped_api = _wrapped_api(data.get("_wrapped_api"), {c.name for g in bit_const_groups for c in g.entries})

    api = Api(
        name=api_name,
        namespace=namespace,
        version=tuple(version),
        library=Library(name=library, link=naming.DEFAULT_LINK),
        bit_const_groups=bit_const_groups,
        const_groups=const_groups,
        string_const_groups=string_const_groups,
        typed_const_groups=_grouped(outlines["typed_const"], typed_consts),
        opaque_ref_groups=_grouped(outlines["opaque_ref"], opaque_refs),
        boxed_scalar_groups=_grouped(outlines["boxed_scalar"], boxed_scalars),
        struct_groups=_grouped(outlines["struct"], structs),
        union_groups=_grouped(outlines["union"], unions),
        callback_groups=_grouped(outlines["callback"], callbacks),
        function_groups=_grouped(outlines["function"], functions),
        wrapped_api=wrapped_api,
    )
    for where, message in _identifier_clashes(api):
        objections.record(DefinitionError(message), where)
    objections.raise_any()
    return api


def _groups(data: Mapping, kind: str, objections: _Objections) -> list[tuple[str, dict]]:
    """(where, body) of each table of the array `[[kind]]`, `where` being `kind[i]`; a `kind`
    that is not such an array is an objection of its own, and has no groups."""
    bodies: list[dict] = []
    with objections.item(kind):
        bodies = _group_bodies(data, kind)
    return [(f"{kind}[{i}]", body) for i, body in enumerate(bodies)]


def _constant_groups(
    data: Mapping, kind: str, objections: _Objections, parse: Callable[[str, dict], T]
) -> tuple[T, ...]:
    """`parse(where, body)` for each group of a constant kind, each group an item of its own."""
    parsed = []
    for where, body in _groups(data, kind, objections):
        with objections.item(where):
            parsed.append(parse(where, body))
    return tuple(parsed)


@dataclass(frozen=True)
class _GroupOutline:
    """A group of a named kind before its items are parsed."""

    where: str  # `function[0]`
    docstring: str | None
    members: list[tuple[str, dict]]  # (item name, item body), in document order


def _named_groups(data: Mapping, kind: str, objections: _Objections) -> list[_GroupOutline]:
    """Each group of the named kind `kind`, split into its `_docstring` and its items. A
    group's own fault (an unknown property, a bad docstring, no items) is the group's
    objection and keeps its items; an item whose name is not an identifier, whose body is
    not a table, or whose name an earlier group of `kind` holds is an objection of its own
    and is dropped."""
    defined: dict[str, str] = {}  # item name -> where its group is
    outlines = []
    for where, body in _groups(data, kind, objections):
        props = {k: v for k, v in body.items() if k.startswith("_")}
        docstring = None
        with objections.item(where):
            _reject_unknown(props, NAMED_GROUP_PROPERTIES, where)
            if len(props) == len(body):
                raise DefinitionError(f"{where}: has no entries")
            docstring = _docstring(props.get("_docstring"), f"{where}._docstring")
        members = []
        for name, item in body.items():
            if name in props:
                continue
            item_where = f"{kind}.{name}"
            if name in defined:
                repeat = DefinitionError(f"{item_where}: already defined in {defined[name]}")
                objections.record(repeat, f"{where}.{name}")
                continue
            defined[name] = where
            with objections.item(item_where):
                _identifier(name, item_where)
                if not isinstance(item, dict):
                    raise DefinitionError(f"{item_where} must be a table")
                members.append((name, item))
        outlines.append(_GroupOutline(where, docstring, members))
    return outlines


def _parse_items(
    outlines: Iterable[_GroupOutline], kind: str, objections: _Objections, parse: Callable[[str, dict], T]
) -> list[T]:
    """`parse(name, body)` for each item of `outlines`' groups in document order, each an
    item of its own."""
    parsed = []
    for outline in outlines:
        for name, body in outline.members:
            with objections.item(f"{kind}.{name}"):
                parsed.append(parse(name, body))
    return parsed


def _grouped(outlines: Iterable[_GroupOutline], items: Iterable[Entry]) -> tuple[Group[Entry], ...]:
    """`outlines` as groups of the `items` that parsed, each in the group that wrote it."""
    by_name = {item.name: item for item in items}
    return tuple(
        Group(
            name=o.where,
            docstring=o.docstring,
            base_type=None,
            to_string=None,
            entries=tuple(by_name[name] for name, _ in o.members if name in by_name),
        )
        for o in outlines
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _identifier(name: str, where: str) -> str:
    """The language-independent rule for a name; each emitter's `validate` refuses its
    own language's keywords."""
    if name.startswith("_"):
        raise DefinitionError(f"{where}: '{name}': a key beginning with '_' is a property, not a name")
    if not _IDENTIFIER.match(name):
        raise DefinitionError(f"{where}: '{name}' is not an identifier")
    return name


def check_literal_text(value: str, where: str) -> None:
    """Refuses a string that cannot be emitted verbatim inside a C or Lua string literal:
    one holding '"', '\\' or a control character. `where` names it in the message."""
    if any(c in '"\\' or ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise DefinitionError(f"{where} must not contain '\"', '\\' or a control character")


def _is_library_name(s: str) -> bool:
    """`s` is a library's name: ASCII letters, digits, `_` and `-`, not beginning with `-`
    or with `lib`, compared case-sensitively as LuaJIT compares bytes."""
    return _LIBRARY_NAME.fullmatch(s) is not None and not s.startswith("lib")


def check_library_name(value: str, where: str) -> None:
    """Refuses a string that is not a library's name (`_is_library_name`): one with the form
    of a platform's library file, or beginning with `lib`, naming the name it holds where
    that is one. `where` names it in the message."""
    if _is_library_name(value):
        return
    stem = naming.library_file_stem(value)
    if stem is not None and _is_library_name(stem):
        raise DefinitionError(f"{where}: {value!r} is a file name; name the library {stem!r}")
    if _LIBRARY_NAME.fullmatch(value):
        refusal = f"{where}: {value!r} begins with 'lib', which LuaJIT's loader does not add again and a linker does"
        rest = value[len("lib") :]
        raise DefinitionError(f"{refusal}; name the library {rest!r}" if _is_library_name(rest) else refusal)
    raise DefinitionError(
        f"{where}: {value!r} is not a library name: ASCII letters, digits, '_' and '-', not beginning with '-'"
    )


def _group_bodies(data: Mapping, key: str) -> list[dict]:
    """The tables of the array `[[key]]`."""
    groups = data.get(key, [])
    if isinstance(groups, dict):
        raise DefinitionError(f"[{key}] must be an array of tables, [[{key}]]")
    if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
        raise DefinitionError(f"[[{key}]] must be an array of tables")
    return groups


def _group_properties(
    body: dict, where: str, *, properties: frozenset[str] = GROUP_PROPERTIES, floats_planned: bool = False
) -> tuple[str | None, str | None, str | None, list[tuple[str, object]]]:
    """(docstring, base type, to_string, members) of one constant group; base type and
    to_string are None where `properties` lacks them (a string constant has no fixed width
    and no conversion). `floats_planned` is `_base_type()`'s."""
    props, members = _split(body, properties, where)
    if not members:
        raise DefinitionError(f"{where}: has no entries")
    base_type = _base_type(props, where, floats_planned=floats_planned) if "_base_type" in properties else None
    doc = _docstring(props.get("_docstring"), f"{where}._docstring")
    return doc, base_type, _to_string(props, where), members


def _split(body: dict, properties: frozenset[str], where: str) -> tuple[dict, list[tuple[str, object]]]:
    """A described item's `_`-prefixed properties, and its members in document order."""
    props = {k: v for k, v in body.items() if k.startswith("_")}
    _reject_unknown(props, properties, where)
    return props, [(k, v) for k, v in body.items() if not k.startswith("_")]


def _attributes(entry: object, *, naked: str, allowed: frozenset[str], where: str) -> dict:
    """An entry's attributes; a value that is not a table is sugar for `{ <naked> = value }`."""
    if not isinstance(entry, dict):
        return {naked: entry}
    plain = next((k for k in entry if not k.startswith("_")), None)
    if plain is not None:
        raise DefinitionError(f"{where}: '{plain}': entry attributes begin with _")
    _reject_unknown(entry, allowed, where)
    return entry


def _base_type(props: Mapping, where: str, *, floats_planned: bool = False) -> str:
    """`floats_planned` marks a plain constant group, where a floating-point base type is
    meaningful but not generated yet; for bit flags and enums it is a plain error."""
    value = props.get("_base_type", "i32")
    if floats_planned and value in FLOAT_TYPES:
        raise NotImplementedDefinition(f"{where}._base_type: {value} constants are not implemented")
    if not isinstance(value, str) or value not in naming.BASE_C_TYPES:
        raise DefinitionError(f"{where}._base_type must be one of {', '.join(naming.BASE_C_TYPES)}")
    return value


def _to_string(props: Mapping, where: str) -> str | None:
    """A group's `_to_string` property: absent, or a name like any other."""
    name = props.get("_to_string")
    if name is None:
        return None
    if not isinstance(name, str):
        raise DefinitionError(f"{where}._to_string must be an identifier")
    return _identifier(name, f"{where}._to_string")


def _docstring(doc: object, where: str) -> str | None:
    """`doc` validated as the docstring found at `where`."""
    if doc is None:
        return None
    if not isinstance(doc, str):
        raise DefinitionError(f"{where} must be a string")
    if "*/" in doc or "]]" in doc:
        raise DefinitionError(f"{where} must not contain '*/' or ']]'")
    if "\n" in doc or "\r" in doc:
        raise DefinitionError(f"{where} must not contain a line break")
    return doc


def _reject_unknown(body: Mapping, allowed: frozenset[str] | set[str], where: str) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise DefinitionError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _unwrap_value(entry: object, where: str) -> tuple[object, str | None, str]:
    """A constant entry as (value, docstring, format)."""
    attrs = _attributes(entry, naked="_value", allowed=CONST_ATTRIBUTES, where=where)
    fmt = attrs.get("_format", "dec")
    if fmt not in FORMATS:
        raise DefinitionError(f"{where}._format must be one of {', '.join(FORMATS)}")
    return attrs.get("_value"), _docstring(attrs.get("_docstring"), f"{where}._docstring"), fmt


def _check_fits(value: int, base_type: str, where: str) -> None:
    base = naming.BASE_C_TYPES[base_type]
    if not base.min_value <= value <= base.max_value:
        raise DefinitionError(f"{where}: {value} does not fit {base_type} ({base.min_value}..{base.max_value})")


def _term(
    term: str, resolved: dict[str, tuple[int, str]], where: str, *, kind: str, base_type: str
) -> tuple[Term, int]:
    """A composed entry's list term and its value: a `LiteralTerm` if `term` is a literal
    (decimal or 0x-prefixed, an optional leading '-'), else the name of an earlier
    same-table entry. Either way it is of the entry's `base_type`."""
    literal = _LITERAL_TERM.match(term)
    if literal is not None:
        sign, hex_digits, dec_digits = literal.groups()
        magnitude = int(hex_digits, 16) if hex_digits is not None else int(dec_digits)
        value = -magnitude if sign else magnitude
        _check_fits(value, base_type, f"{where}: term {term}")
        return LiteralTerm(value, "hex" if hex_digits is not None else "dec"), value
    if not _IDENTIFIER.match(term):
        raise DefinitionError(
            f"{where}: term '{term}' is neither an entry name nor a literal (decimal or 0x-prefixed, "
            "an optional leading '-')"
        )
    if term not in resolved:
        raise DefinitionError(f"{where}: composes unknown constant '{term}' (only earlier {kind} entries or literals)")
    value, term_base_type = resolved[term]
    if term_base_type != base_type:
        raise DefinitionError(
            f"{where} ({base_type}) composes {kind}.{term} ({term_base_type}): a sum's terms share its _base_type"
        )
    return term, value


def _check_disjoint_bits(where: str, written: list[str], values: list[int]) -> None:
    """Refuses a bit-group sum whose terms share a bit, naming the two as written."""
    for i, (term, value) in enumerate(zip(written, values)):
        earlier = next((t for t, v in zip(written[:i], values) if v & value), None)
        if earlier is not None:
            raise DefinitionError(f"{where}: {earlier} and {term} share bits")


def _check_running_sum(where: str, written: list[str], values: list[int], base_type: str) -> None:
    """Refuses a sum whose running total, term by term in the order written, leaves
    `base_type`'s range before its last term, even where the final value fits: a constant
    expression that overflows midway is a compile error in Rust and undefined in C. The
    final value is the caller's to check."""
    total = 0
    for term, value in list(zip(written, values))[:-1]:
        total += value
        _check_fits(total, base_type, f"{where}: the running sum after term {term}")


def _bit_const_group(group_where: str, body: dict, *, resolved: dict[str, tuple[int, str]]) -> Group[BitConst]:
    """A composed value may name an entry of any earlier group of its base type or be a
    literal, so the groups share `resolved`, every entry read so far; disjoint terms sum to
    the same value as their OR, so every running total of a sum fits as its terms do."""
    group_doc, base_type, to_string, members = _group_properties(body, group_where)
    assert base_type is not None  # untyped_bit_const groups always carry _base_type
    bits = naming.BASE_C_TYPES[base_type].max_value.bit_length()  # a flag is a positive value
    consts = []
    for name, entry in members:
        where = f"untyped_bit_const.{name}"
        _identifier(name, where)
        raw, doc, fmt = _unwrap_value(entry, where)
        if _is_int(raw):
            if not 0 <= raw < bits:
                raise DefinitionError(f"{where}: bit index {raw} is outside 0..{bits - 1} for _base_type {base_type}")
            bit, parts, value = raw, (), 1 << raw
        elif isinstance(raw, list) and raw and all(isinstance(p, str) for p in raw):
            terms = [_term(p, resolved, where, kind="untyped_bit_const", base_type=base_type) for p in raw]
            _check_disjoint_bits(where, raw, [v for _, v in terms])
            bit, parts, value = None, tuple(t for t, _ in terms), sum(v for _, v in terms)
        else:
            raise DefinitionError(f"{where}: must be a bit index or a non-empty list of constant names or literals")
        consts.append(BitConst(name=name, docstring=doc, bit=bit, parts=parts, value=value, format=fmt))
        resolved[name] = value, base_type
    return Group(name=group_where, docstring=group_doc, base_type=base_type, to_string=to_string, entries=tuple(consts))


def _int_entry(name: str, entry: object, where: str, *, base_type: str) -> EnumEntry:
    _identifier(name, where)
    value, doc, fmt = _unwrap_value(entry, where)
    if not _is_int(value):
        raise DefinitionError(f"{where}: value must be an integer")
    _check_fits(value, base_type, where)
    return EnumEntry(name=name, docstring=doc, value=value, format=fmt)


def _plain_const_entry(
    name: str, entry: object, where: str, *, base_type: str, resolved: dict[str, tuple[int, str]]
) -> EnumEntry:
    """An untyped_const entry: a plain integer, or a list summing earlier untyped_const
    entries and literals, the same composition untyped_bit_const uses (without the
    disjointness rule, since a plain group is arithmetic, not bit flags)."""
    _identifier(name, where)
    raw, doc, fmt = _unwrap_value(entry, where)
    if isinstance(raw, float):
        raise NotImplementedDefinition(f"{where}: f64 constants are not implemented")
    if _is_int(raw):
        value, parts = raw, ()
    elif isinstance(raw, list) and raw and all(isinstance(p, str) for p in raw):
        terms = [_term(p, resolved, where, kind="untyped_const", base_type=base_type) for p in raw]
        _check_running_sum(where, raw, [v for _, v in terms], base_type)
        parts, value = tuple(t for t, _ in terms), sum(v for _, v in terms)
    else:
        raise DefinitionError(f"{where}: must be an integer or a non-empty list of constant names or literals")
    _check_fits(value, base_type, where)
    resolved[name] = value, base_type
    return EnumEntry(name=name, docstring=doc, value=value, format=fmt, parts=parts)


def _const_group(group_where: str, body: dict, *, resolved: dict[str, tuple[int, str]]) -> Group[EnumEntry]:
    """A composed value may name an entry of any earlier group of its base type, so the
    groups share `resolved`, every entry read so far."""
    doc, base_type, to_string, members = _group_properties(body, group_where, floats_planned=True)
    assert base_type is not None  # untyped_const groups always carry _base_type
    entries = tuple(
        _plain_const_entry(name, entry, f"untyped_const.{name}", base_type=base_type, resolved=resolved)
        for name, entry in members
    )
    return Group(name=group_where, docstring=doc, base_type=base_type, to_string=to_string, entries=entries)


def _string_group(where: str, body: dict) -> Group[StringConst]:
    doc, _, _, members = _group_properties(body, where, properties=STRING_GROUP_PROPERTIES)
    return Group(
        name=where,
        docstring=doc,
        base_type=None,
        to_string=None,
        entries=tuple(_string_const(name, entry) for name, entry in members),
    )


def _string_const(name: str, entry: object) -> StringConst:
    where = f"string_const.{name}"
    _identifier(name, where)
    attrs = _attributes(entry, naked="_value", allowed=frozenset({"_value", "_docstring"}), where=where)
    value = attrs.get("_value")
    if not isinstance(value, str):
        raise DefinitionError(f"{where}: value must be a string")
    check_literal_text(value, f"{where}: value")
    return StringConst(name=name, docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"), value=value)


def _typed_const(name: str, body: dict) -> TypedConst:
    where = f"typed_const.{name}"
    props, members = _split(body, GROUP_PROPERTIES, where)
    base_type = _base_type(props, where)
    entries = [_int_entry(key, entry, f"{where}.{key}", base_type=base_type) for key, entry in members]
    if not entries:
        raise DefinitionError(f"{where}: has no entries")
    by_value: dict[int, str] = {}
    for e in entries:
        if e.value in by_value:
            raise DefinitionError(f"{where}.{e.name}: value {e.value} already given to {where}.{by_value[e.value]}")
        by_value[e.value] = e.name
    return TypedConst(
        name=name,
        docstring=_docstring(props.get("_docstring"), f"{where}._docstring"),
        entries=tuple(entries),
        base_type=base_type,
        to_string=_to_string(props, where),
    )


def _opaque_ref(name: str, body: dict) -> OpaqueRef:
    where = f"opaque_ref.{name}"
    props, members = _split(body, OPAQUE_PROPERTIES, where)
    if members:
        raise DefinitionError(f"{where}: '{members[0][0]}': an opaque_ref has no members; its properties begin with _")
    for key in ("_ctor", "_dtor"):
        if not isinstance(props.get(key, ""), str):
            raise DefinitionError(f"{where}.{key} must be a function name")
    class_name = props.get("_class", name)
    if "_class" in props:
        if not isinstance(class_name, str):
            raise DefinitionError(f"{where}._class must be an identifier")
        _identifier(class_name, f"{where}._class")
        if not _LOWERCASE_IDENTIFIER.match(class_name):
            raise DefinitionError(
                f"{where}._class: '{class_name}' must be lowercase; each binding applies its own casing"
            )
    hides_pointer = props.get("_hides_pointer", False)
    if not isinstance(hides_pointer, bool):
        raise DefinitionError(f"{where}._hides_pointer must be true or false")
    return OpaqueRef(
        name=name,
        docstring=_docstring(props.get("_docstring"), f"{where}._docstring"),
        ctor=props.get("_ctor"),
        dtor=props.get("_dtor"),
        class_name=class_name,
        hides_pointer=hides_pointer,
    )


def _boxed_scalar(name: str, body: dict) -> BoxedScalar:
    where = f"boxed_scalar.{name}"
    props, members = _split(body, BOXED_PROPERTIES, where)
    if members:
        raise DefinitionError(f"{where}: '{members[0][0]}': a boxed_scalar has no members; its properties begin with _")
    base_type = props.get("_base_type")
    if base_type not in INTEGER_TYPES:
        raise DefinitionError(f"{where}._base_type is required, one of {', '.join(INTEGER_TYPES)}")
    return BoxedScalar(
        name=name, docstring=_docstring(props.get("_docstring"), f"{where}._docstring"), base_type=base_type
    )


def _check_lifecycle(o: OpaqueRef, functions: Mapping[str, Function]) -> None:
    where = f"opaque_ref.{o.name}"
    if o.dtor is not None and o.ctor is None:
        raise DefinitionError(f"{where}._dtor: requires _ctor")
    if o.ctor is None:
        return
    ctor = functions.get(o.ctor)
    if ctor is None or sum(p.type == o.name and p.ref == "out" for p in ctor.params) != 1:
        raise DefinitionError(
            f"{where}._ctor: '{o.ctor}' must name a function with exactly one {o.name} parameter of _ref \"out\""
        )
    buffer = next((p for p in ctor.params if p.ref == "out" and p.is_buffer), None)
    if buffer is not None:
        raise DefinitionError(
            f"{where}._ctor: function.{ctor.name}.{buffer.name}: a constructor cannot cache an out buffer"
        )
    inout = next((p for p in ctor.params if p.ref == "inout"), None)
    if inout is not None:
        raise DefinitionError(f"{where}._ctor: function.{ctor.name}.{inout.name}: a constructor has no inout parameter")
    callback = next((p for p in ctor.params if p.callback), None)
    if callback is not None:
        raise NotImplementedDefinition(
            f"{where}._ctor: function.{ctor.name}.{callback.name}: a constructor's callback parameter is not implemented"
        )
    if o.dtor is not None:
        dtor = functions.get(o.dtor)
        if dtor is None or [(p.type, p.ref) for p in dtor.params] != [(o.name, None)]:
            raise DefinitionError(
                f"{where}._dtor: '{o.dtor}' must name a function whose only parameter is a {o.name} by value"
            )


def _variable(entry: object, *, allowed: frozenset[str], type_names: dict[str, str], where: str) -> tuple[str, dict]:
    """A field or parameter as (type, attributes), its type checked to exist."""
    attrs = _attributes(entry, naked="_type", allowed=allowed, where=where)
    type_name = attrs.get("_type")
    if not isinstance(type_name, str):
        raise DefinitionError(f"{where}: must be a type name or a table with _type")
    if type_name not in BUILTIN_TYPES and type_name not in type_names:
        raise DefinitionError(f"{where}: unknown type '{type_name}'")
    return type_name, attrs


def _struct(name: str, body: dict, type_names: dict[str, str], *, defined_structs: set[str]) -> Struct:
    """A struct whose fields are checked each on its own, every field's objection reported."""
    where = f"struct.{name}"
    props, members = _split(body, frozenset({"_docstring"}), where)
    doc = _docstring(props.get("_docstring"), f"{where}._docstring")
    if not members:
        raise DefinitionError(f"{where}: has no fields")
    objections = _Objections()
    fields = []
    for key, entry in members:
        with objections.item(f"{where}.{key}"):
            fields.append(_field(key, entry, f"{where}.{key}", type_names=type_names, defined_structs=defined_structs))
    objections.raise_any()
    return Struct(name=name, docstring=doc, fields=tuple(fields))


def _field(key: str, entry: object, where: str, *, type_names: dict[str, str], defined_structs: set[str]) -> Field:
    _identifier(key, where)
    type_name, attrs = _variable(entry, allowed=FIELD_ATTRIBUTES, type_names=type_names, where=where)
    if type_name == "memory":
        raise DefinitionError(f"{where}: 'memory' is not a field type")
    if type_names.get(type_name) == "callback":
        raise NotImplementedDefinition(f"{where}: a field of callback '{type_name}' is not implemented")
    if type_names.get(type_name) == "union":
        raise NotImplementedDefinition(f"{where}: a field of union '{type_name}' is not implemented")
    if type_names.get(type_name) == "struct" and type_name not in defined_structs:
        raise DefinitionError(f"{where}: struct '{type_name}' must be defined before it is used")
    return Field(
        name=key,
        docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"),
        type=type_name,
    )


def _layout_types(
    structs: Iterable[Struct], enums: Iterable[TypedConst], boxed_scalars: Iterable[BoxedScalar]
) -> dict[str, "Struct | str"]:
    """Each struct by its name, and each enum and boxed scalar to its base type: the types a
    layout is computed from."""
    types: dict[str, Struct | str] = {s.name: s for s in structs}
    types |= {t.name: t.base_type for t in enums}
    types |= {b.name: b.base_type for b in boxed_scalars}
    return types


def _layout(type_name: str, types: Mapping[str, "Struct | str"]) -> tuple[int, int]:
    """(size, alignment) of `type_name` over `types`; for a struct, one `_unlaid()` finds nothing in."""
    if type_name in naming.BUILTIN_C_TYPES:
        width = int(type_name[1:]) // 8
        return width, width
    if type_name == naming.TEXT:
        return _fields_layout(naming.TEXT_FIELDS, types)[:2]
    found = types[type_name]
    if isinstance(found, str):
        return _layout(found, types)
    return _fields_layout([(f.name, f.type) for f in found.fields], types)[:2]


def _fields_layout(
    fields: Iterable[tuple[str, str]], types: Mapping[str, "Struct | str"]
) -> tuple[int, int, str | None, int, tuple[int, ...]]:
    """(size, alignment, the field after which the first padding falls, else None, the end of
    the last field, each field's offset) of a C struct of `fields`, (name, type) in order: each
    at the next offset its alignment allows, the size rounded up to the largest alignment."""
    offset, align, padded, previous, offsets = 0, 1, None, None, []
    for name, type_name in fields:
        size, field_align = _layout(type_name, types)
        aligned = -(-offset // field_align) * field_align
        if aligned != offset and padded is None:
            padded = previous
        offsets.append(aligned)
        offset, align, previous = aligned + size, max(align, field_align), name
    size = -(-offset // align) * align
    if size != offset and padded is None:
        padded = previous
    return size, align, padded, offset, tuple(offsets)


def _unlaid(struct: Struct, types: Mapping[str, "Struct | str"]) -> tuple[str, Field] | None:
    """(struct, field) of the first field in `struct` or a struct it holds whose type has no
    layout of its own, an opaque ref's pointer differing in size by target; None where every
    field has one."""
    for f in struct.fields:
        found = types.get(f.type)
        if isinstance(found, Struct):
            unlaid = _unlaid(found, types)
            if unlaid is not None:
                return unlaid
        elif found is None and f.type not in naming.BUILTIN_C_TYPES and f.type != naming.TEXT:
            return struct.name, f
    return None


def _padding(struct: Struct, types: Mapping[str, "Struct | str"]) -> tuple[str, str] | None:
    """(struct, field) of the first padding in `struct` or a struct it holds, the field it
    follows; None where every byte is a field's."""
    padded = _fields_layout([(f.name, f.type) for f in struct.fields], types)[2]
    if padded is not None:
        return struct.name, padded
    held = (types[f.type] for f in struct.fields if isinstance(types.get(f.type), Struct))
    return next((found for s in held if (found := _padding(s, types)) is not None), None)


def _union(
    name: str, body: dict, *, type_names: Mapping[str, str], tags: Mapping[str, EnumEntry], layout_types: Mapping
) -> Union:
    """A union whose members are each checked on their own, then the shape they share: one
    prefix struct beginning with the tag and the length, and every member laid out over it."""
    where = f"union.{name}"
    props, entries = _split(body, UNION_PROPERTIES, where)
    doc = _docstring(props.get("_docstring"), f"{where}._docstring")
    mixed_type_list = props.get("_mixed_type_list", False)
    if not isinstance(mixed_type_list, bool):
        raise DefinitionError(f"{where}._mixed_type_list must be true or false")
    if not entries:
        raise DefinitionError(f"{where}: names no member")
    objections = _Objections()
    members: list[UnionMember] = []
    for key, entry in entries:
        with objections.item(f"{where}.{key}"):
            members.append(
                _union_member(key, entry, f"{where}.{key}", type_names=type_names, tags=tags, structs=layout_types)
            )
    by_tag: dict[int, UnionMember] = {}
    by_struct: dict[str, UnionMember] = {}
    heads: dict[str, str] = {}
    for m in members:
        with objections.item(f"{where}.{m.name}"):
            other = by_tag.setdefault(tags[m.tag].value, m)
            if other is not m and other.tag == m.tag:
                raise DefinitionError(f"{where}.{m.name}._tag: {m.tag} is already {where}.{other.name}'s tag")
            if other is not m:
                raise DefinitionError(
                    f"{where}.{m.name}._tag: {m.tag}'s value {tags[m.tag].value} is already "
                    f"{where}.{other.name}'s tag, {other.tag}"
                )
            other = by_struct.setdefault(m.struct, m)
            if other is not m:
                raise DefinitionError(
                    f"{where}.{m.name}._type: struct '{m.struct}' is already {where}.{other.name}'s struct"
                )
            head = layout_types[m.struct].fields[0].type
            if type_names.get(head) != "struct":
                raise DefinitionError(f"{where}.{m.name}._type: struct '{m.struct}' must begin with a struct field")
            heads[m.name] = head
    objections.raise_any()
    prefix, tag_field, length_field = _prefix(where, members, heads, layout_types)
    for m in members:
        with objections.item(f"{where}.{m.name}"):
            _check_member(
                f"{where}.{m.name}",
                m,
                prefix,
                union=name,
                tag=tags[m.tag].value,
                tag_field=tag_field,
                length_field=length_field,
                types=layout_types,
            )
    objections.raise_any()
    return Union(
        name=name,
        docstring=doc,
        prefix=prefix.name,
        tag_field=tag_field.name,
        length_field=length_field.name,
        members=tuple(members),
        mixed_type_list=mixed_type_list,
    )


def _counted_unions(
    unions: Iterable[Union], signatures: Iterable[tuple[str, Function]], objections: _Objections
) -> list[Union]:
    """Each union with the `_count` type of its counted parameters (`kind`, signature) in
    `signatures`, which share one: a parameter counting it by another type than the first in
    document order is refused, naming that first one."""
    params = [(f"{kind}.{fn.name}.{p.name}", p) for kind, fn in signatures for p in fn.params if p.is_union]
    first: dict[str, tuple[str, str]] = {}
    for where, p in sorted(params, key=lambda found: objections._position(found[0])):
        at, count_type = first.setdefault(p.type, (where, p.count_type))
        if p.count_type != count_type:
            objections.record(
                DefinitionError(
                    f"{where}: union '{p.type}' is counted by {p.count_type} here and by {count_type} at {at}; "
                    "one count type per union"
                ),
                where,
            )
    return [replace(u, count_type=first[u.name][1]) if u.name in first else u for u in unions]


def _union_member(
    key: str,
    entry: object,
    where: str,
    *,
    type_names: Mapping[str, str],
    tags: Mapping[str, EnumEntry],
    structs: Mapping,
) -> UnionMember:
    """A member, `{ _tag = "<untyped_const entry>", _type = "<struct>" }`."""
    _identifier(key, where)
    if not isinstance(entry, dict):
        raise DefinitionError(f"{where}: a member needs _tag and _type")
    attrs = _attributes(entry, naked="_type", allowed=MEMBER_ATTRIBUTES, where=where)
    tag, struct = attrs.get("_tag"), attrs.get("_type")
    if not (isinstance(tag, str) and isinstance(struct, str)):
        raise DefinitionError(f"{where}: a member needs _tag and _type")
    if tag not in tags:
        raise DefinitionError(f"{where}._tag: '{tag}' is not an untyped_const entry")
    if not isinstance(structs.get(struct), Struct):
        if struct in BUILTIN_TYPES or struct in type_names:
            raise DefinitionError(f"{where}._type: '{struct}' is not a struct")
        raise DefinitionError(f"{where}._type: struct '{struct}' must be defined before it is used")
    return UnionMember(
        name=key, docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"), tag=tag, struct=struct
    )


def _prefix(
    where: str, members: Sequence[UnionMember], heads: Mapping[str, str], types: Mapping
) -> tuple[Struct, Field, Field]:
    """The union's prefix, the one struct every member's struct begins with, laid out on every
    target with no padding, and its tag and length fields: the first field, one of
    PREFIX_TAG_TYPES, and the first after it not `u8`, one of PREFIX_LENGTH_TYPES."""
    first = members[0]
    other = next((m for m in members if heads[m.name] != heads[first.name]), None)
    if other is not None:
        raise DefinitionError(
            f"{where}: members must begin with one struct; {first.name} begins with '{heads[first.name]}' "
            f"and {other.name} with '{heads[other.name]}'"
        )
    prefix = types[heads[first.name]]
    tag, *rest = prefix.fields
    length = next((f for f in rest if f.type != "u8"), None)
    if tag.type not in PREFIX_TAG_TYPES or length is None or length.type not in PREFIX_LENGTH_TYPES:
        raise DefinitionError(
            f"{where}: prefix '{prefix.name}' must begin with the tag, {_either(PREFIX_TAG_TYPES)}, then any u8 "
            f"fields, then the record's byte length, {_either(PREFIX_LENGTH_TYPES)}"
        )
    _check_laid_out(where, prefix, types)
    _check_whole(where, f"prefix '{prefix.name}'", prefix, _layout(prefix.name, types)[1], types)
    _check_dense(where, prefix, types)
    return prefix, tag, length


def _either(types: Sequence[str]) -> str:
    """`types` as prose alternatives: `u8, u16 or u32`."""
    return f"{', '.join(types[:-1])} or {types[-1]}"


def _check_laid_out(where: str, struct: Struct, types: Mapping) -> None:
    """Refuses a struct a union's record is, its prefix or a member's, whose layout differs by
    target: one holding an opaque ref, itself or in a struct it holds."""
    unlaid = _unlaid(struct, types)
    if unlaid is not None:
        holder, f = unlaid
        raise DefinitionError(
            f"{where}: struct '{holder}' has field '{f.name}' of opaque_ref '{f.type}', whose size is each "
            "target's; a member has one layout on every target"
        )


def _check_whole(where: str, what: str, struct: Struct, list_align: int, types: Mapping) -> None:
    """Refuses a struct a union's record is, its prefix or a member's, whose fields end short of
    a multiple of the list's alignment, so that a record after it would start misaligned."""
    end = _fields_layout([(f.name, f.type) for f in struct.fields], types)[3]
    if end % list_align:
        raise DefinitionError(f"{where}: {what} is {end} bytes, not a multiple of the list's alignment, {list_align}")


def _check_dense(where: str, struct: Struct, types: Mapping) -> None:
    """Refuses a struct a union's record is, its prefix or a member's, holding padding, itself
    or in a struct it holds."""
    padded = _padding(struct, types)
    if padded is not None:
        raise DefinitionError(f"{where}: struct '{padded[0]}' has padding after field '{padded[1]}'; a member has none")


def _check_member(
    where: str,
    member: UnionMember,
    prefix: Struct,
    *,
    union: str,
    tag: int,
    tag_field: Field,
    length_field: Field,
    types: Mapping,
) -> None:
    """Refuses a member whose tag does not fit the prefix's tag field, or whose struct differs
    from the prefix's alignment, which is then the list's, is not a whole multiple of it, holds
    padding or is longer than the length field counts."""
    struct = types[member.struct]
    if not 0 <= tag <= naming.integer_range(tag_field.type)[1]:
        raise DefinitionError(
            f"{where}._tag: {member.tag}'s value {tag} does not fit {prefix.name}.{tag_field.name} ({tag_field.type})"
        )
    _check_laid_out(where, struct, types)
    size, align = _layout(struct.name, types)
    _, prefix_align = _layout(prefix.name, types)
    if align != prefix_align:
        wide = next(f for f in struct.fields if _layout(f.type, types)[1] > prefix_align)
        raise DefinitionError(
            f"{where}: struct '{struct.name}' has alignment {align} (field '{wide.name}' is {wide.type}); "
            f"a member of '{union}' has the prefix's alignment, {prefix_align}"
        )
    _check_whole(where, f"struct '{struct.name}'", struct, prefix_align, types)
    _check_dense(where, struct, types)
    if size > naming.integer_range(length_field.type)[1]:
        raise DefinitionError(
            f"{where}: struct '{struct.name}' of {size} bytes does not fit "
            f"{prefix.name}.{length_field.name} ({length_field.type})"
        )


def _function(
    name: str,
    body: dict,
    type_names: dict[str, str],
    enums: Mapping[str, TypedConst],
    lists: Container[str],
    consts: Mapping[str, EnumEntry],
) -> Function:
    """A function whose `_return`, `_stack_mb` and parameters are checked each on its own, every
    one's objection reported; `consts` are the `untyped_const` entries `_stack_mb` may name."""
    return _signature(
        f"function.{name}", name, body, enums, _param, type_names=type_names, lists=lists, stops=False, consts=consts
    )


def _callback(
    name: str, body: dict, type_names: dict[str, str], enums: Mapping[str, TypedConst], lists: Container[str]
) -> Function:
    """A callback type, checked as a function is: a `_return` that can also stop, and the
    parameters a callback takes."""
    return _signature(
        f"callback.{name}", name, body, enums, _callback_param, type_names=type_names, lists=lists, stops=True
    )


def _signature(
    where: str,
    name: str,
    body: dict,
    enums: Mapping[str, TypedConst],
    parse_param: Callable[..., Param],
    *,
    type_names: dict[str, str],
    lists: Container[str],
    stops: bool,
    consts: Mapping[str, EnumEntry] | None = None,
) -> Function:
    """The function or callback at `where`, its `_return`, a function's `_stack_mb` (one with
    `consts`) and each parameter, parsed by `parse_param`, checked on its own."""
    properties = {"_docstring", "_return", *(["_stack_mb"] if consts is not None else [])}
    props, members = _split(body, frozenset(properties), where)
    doc = _docstring(props.get("_docstring"), f"{where}._docstring")
    objections = _Objections()
    returns = ""
    with objections.item(f"{where}._return"):
        returns = _return(props.get("_return"), where, enums, stops=stops)
    stack_mb = None
    if consts is not None and "_stack_mb" in props:
        with objections.item(f"{where}._stack_mb"):
            stack_mb = _stack_mb(props["_stack_mb"], f"{where}._stack_mb", consts)
    names = {key for key, _ in members}
    params = []
    for key, entry in members:
        with objections.item(f"{where}.{key}"):
            params.append(parse_param(key, entry, f"{where}.{key}", type_names=type_names, lists=lists, names=names))
    objections.raise_any()
    return Function(name=name, docstring=doc, returns=returns, params=tuple(params), stack_mb=stack_mb)


def _stack_mb(entry: object, where: str, consts: Mapping[str, EnumEntry]) -> EnumEntry:
    """The `untyped_const` entry a function's `_stack_mb` names, whose value is positive."""
    if not isinstance(entry, str):
        raise DefinitionError(f"{where} must name an untyped_const entry")
    if entry not in consts:
        raise DefinitionError(f"{where}: '{entry}' is not an untyped_const entry")
    if consts[entry].value <= 0:
        raise DefinitionError(f"{where}: '{entry}' is {consts[entry].value}, not positive")
    return consts[entry]


def _return(returns: object, where: str, enums: Mapping[str, TypedConst], *, stops: bool) -> str:
    """The `_return` of the function or callback at `where`: an enum with a zero entry, and
    for a callback (`stops`) a non-zero one to stop with."""
    if not isinstance(returns, str):
        raise DefinitionError(f"{where}: missing '_return' naming a typed_const")
    if returns not in enums:
        raise DefinitionError(f"{where}._return: unknown typed_const '{returns}'")
    if not any(e.value == 0 for e in enums[returns].entries):
        raise DefinitionError(f"{where}._return: typed_const '{returns}' has no zero-valued entry for success")
    if stops and all(e.value == 0 for e in enums[returns].entries):
        raise DefinitionError(f"{where}._return: typed_const '{returns}' has no non-zero entry to stop with")
    return returns


def _ref_and_count(type_name: str, attrs: Mapping, where: str) -> tuple[str | None, str | None]:
    """A parameter's `_ref` and `_count`, the count making it a buffer, which needs a ref."""
    ref = attrs.get("_ref")
    if ref is not None and ref not in REFS:
        raise DefinitionError(f"{where}._ref must be one of {', '.join(REFS)}")
    count_type = attrs.get("_count")
    if type_name == "memory" and count_type not in COUNT_TYPES:
        raise DefinitionError(f"{where}: a 'memory' parameter requires _count, one of {', '.join(COUNT_TYPES)}")
    if type_name != "memory" and count_type is not None and count_type not in COUNT_TYPES:
        raise DefinitionError(f"{where}._count must be one of {', '.join(COUNT_TYPES)}")
    if count_type is not None and ref is None:
        raise DefinitionError(f"{where}: a buffer needs _ref")
    return ref, count_type


def _check_derived(param: Param, where: str, names: set[str]) -> None:
    """Refuses a parameter whose derived C parameter is another parameter's name."""
    if param.callback:
        roles: tuple[str, ...] = ("user_data",)
    elif param.is_union:
        roles = ("count", "extent")
    else:
        roles = ("count", "report", "report")
    for role, derived in zip(roles, param.derived_names()):
        if derived in names:
            raise DefinitionError(f"{where}: its {role} parameter {derived} is already a parameter")


def _callback_param(
    key: str, entry: object, where: str, *, type_names: dict[str, str], lists: Container[str], names: set[str]
) -> Param:
    """A parameter of a callback type: by value a builtin scalar or an enum, or with
    `_ref = "in"` a view, a buffer of bytes or of a builtin, boxed scalar or struct. LuaJIT
    takes no aggregate by value in a callback, and the bindings would have to check every
    element of an enum view, so either is not implemented."""
    _identifier(key, where)
    if key == naming.USER_DATA:
        raise DefinitionError(f"{where}: '{key}' is the C callback type's own last parameter")
    type_name, attrs = _variable(entry, allowed=CALLBACK_PARAM_ATTRIBUTES, type_names=type_names, where=where)
    if type_name == naming.TEXT:
        raise NotImplementedDefinition(f"{where}: a text parameter is not implemented; text is a struct field type")
    ref, count_type = _ref_and_count(type_name, attrs, where)
    category = type_names.get(type_name)
    if category == "callback":
        raise NotImplementedDefinition(f"{where}: callback '{type_name}' as a callback's parameter is not implemented")
    if category == "union":
        _check_sequence(where, type_name, ref=ref, count_type=count_type, lists=lists, in_callback=True)
    if ref is not None and (count_type is None or ref != "in"):
        raise NotImplementedDefinition(
            f'{where}: a callback parameter with _ref = "{ref}" is not implemented, only a buffer with _ref = "in"'
        )
    if count_type is not None and type_name != "memory" and category != "union":
        _check_array(where, type_name, ref=ref, type_names=type_names, view=True)
    if count_type is None and category == "opaque_ref":
        raise NotImplementedDefinition(f"{where}: an opaque_ref '{type_name}' is not implemented in a callback")
    if count_type is None and category in ("boxed_scalar", "struct"):
        raise NotImplementedDefinition(f"{where}: a {category} '{type_name}' by value is not implemented in a callback")
    param = Param(
        name=key,
        docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"),
        type=type_name,
        ref=ref,
        count_type=count_type,
        optional=False,
        wrote_needed=False,
        is_union=category == "union",
    )
    _check_derived(param, where, names)
    return param


def _param(
    key: str, entry: object, where: str, *, type_names: dict[str, str], lists: Container[str], names: set[str]
) -> Param:
    """A parameter of a function whose parameters are `names`, `lists` the unions with
    `_mixed_type_list`."""
    _identifier(key, where)
    type_name, attrs = _variable(entry, allowed=PARAM_ATTRIBUTES, type_names=type_names, where=where)
    if type_name == naming.TEXT:
        raise NotImplementedDefinition(f"{where}: a text parameter is not implemented; text is a struct field type")
    ref, count_type = _ref_and_count(type_name, attrs, where)
    union = type_names.get(type_name) == "union"
    if union:
        _check_sequence(where, type_name, ref=ref, count_type=count_type, lists=lists, in_callback=False)
    elif type_name != "memory" and count_type is not None:
        _check_array(where, type_name, ref=ref, type_names=type_names)
    callback = type_names.get(type_name) == "callback"
    if callback and ref is not None:
        raise DefinitionError(f"{where}: a callback is passed by value")
    optional = attrs.get("_optional", False)
    if not isinstance(optional, bool):
        raise DefinitionError(f"{where}._optional must be true or false")
    if optional and ref is None:
        raise DefinitionError(f"{where}._optional: a by-value parameter has no null to pass")
    if optional and count_type is not None and ref != "in":
        raise DefinitionError(f'{where}._optional: a buffer is optional only with _ref = "in"')
    wrote_needed = attrs.get("_wrote_needed", False)
    if not isinstance(wrote_needed, bool):
        raise DefinitionError(f"{where}._wrote_needed must be true or false")
    if wrote_needed and (count_type is None or ref != "out"):
        raise DefinitionError(f'{where}._wrote_needed: only an "out" buffer reports what it wrote and needs')
    param = Param(
        name=key,
        docstring=_docstring(attrs.get("_docstring"), f"{where}._docstring"),
        type=type_name,
        ref=ref,
        count_type=count_type,
        optional=optional,
        wrote_needed=wrote_needed,
        callback=callback,
        is_union=union,
    )
    _check_derived(param, where, names)
    return param


def _check_sequence(
    where: str, type_name: str, *, ref: str | None, count_type: str | None, lists: Container[str], in_callback: bool
) -> None:
    """Refuses a parameter of a union type that is not a sequence the callee reads, `_ref =
    "in"` with `_count`, of a union whose members lie in a list (`lists`)."""
    if ref is None and count_type is None:
        context = " in a callback" if in_callback else ""
        raise NotImplementedDefinition(f"{where}: union '{type_name}' by value is not implemented{context}")
    if ref in ("out", "inout"):
        raise NotImplementedDefinition(f'{where}: a union with _ref = "{ref}" is not implemented, only "in"')
    if count_type is None:
        raise DefinitionError(f'{where}: a union is passed as a list; it needs _ref = "in" and _count')
    if type_name not in lists:
        raise DefinitionError(
            f"{where}: a counted parameter needs union '{type_name}' to declare _mixed_type_list = true"
        )


def _check_array(where: str, type_name: str, *, ref: str, type_names: dict[str, str], view: bool = False) -> None:
    """Refuses a typed array, `_count` on a type other than `memory`, that the generator does
    not produce: anything but an `in` or `out` array of builtins, boxed scalars or structs,
    or a function's `in` array of an enum, whose values the caller made. An enum array the
    library writes, an `out` array or a callback's `view`, would need every element checked."""
    if ref not in ("in", "out"):
        raise NotImplementedDefinition(f'{where}: an array with _ref = "{ref}" is not implemented, only "in" or "out"')
    category = type_names.get(type_name)
    caller_made_enums = category == "typed_const" and ref == "in" and not view
    if category in ("typed_const", "opaque_ref", "callback") and not caller_made_enums:
        raise NotImplementedDefinition(f"{where}: an array of {category} '{type_name}' is not implemented")


def _wrapped_api(body: object, bit_names: set[str]) -> WrappedApi | None:
    if body is None:
        return None
    if not isinstance(body, dict):
        raise DefinitionError("[_wrapped_api] must be a table")
    _reject_unknown(body, frozenset({"_headers", "_pinned_value"}), "_wrapped_api")
    headers = body.get("_headers")
    if not (isinstance(headers, list) and headers and all(isinstance(h, str) for h in headers)):
        raise DefinitionError("_wrapped_api._headers must be a non-empty list of strings")
    for i, header in enumerate(headers):
        where = f"_wrapped_api._headers[{i}]"
        check_literal_text(header, where)
        if header.startswith(("/", "../")):
            raise DefinitionError(
                f"{where} must be relative to the project directory, not absolute or beginning with '../'"
            )
        if header in headers[:i]:
            raise DefinitionError(f"{where}: already listed")
    pinned = body.get("_pinned_value", {})
    if not isinstance(pinned, dict):
        raise DefinitionError("_wrapped_api._pinned_value must be a table")
    _, members = _split(pinned, frozenset(), "_wrapped_api._pinned_value")
    pins = []
    for key, macro in members:
        where = f"_wrapped_api._pinned_value.{key}"
        if key not in bit_names:
            raise DefinitionError(f"{where}: pins undefined untyped_bit_const '{key}'")
        if not isinstance(macro, str) or not _IDENTIFIER.match(macro):
            raise DefinitionError(f"{where}: must be a macro name")
        pins.append((key, macro))
    return WrappedApi(tuple(headers), tuple(pins))


def _identifier_clashes(api: Api) -> list[tuple[str, str]]:
    """(where, objection) for every generated C identifier, constant or declaration, that a
    later item defines again, naming the first definer."""
    clashes = []
    for ident, (first, *later) in duplicates(api.c_identifiers()).items():
        clashes += [(where, f"{where}: C identifier {ident} already defined by {first}") for where in later]
    return clashes
