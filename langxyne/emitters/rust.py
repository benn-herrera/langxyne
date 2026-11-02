"""Rust language facts every Rust emitter shares: the keywords, rustc's snake_case rule,
the FFI spelling of a definition's types, the C-named constant, type and function
declarations a Rust file renders at the C header's ABI, the `ffi` module, enum and
re-export blocks the binding and the relay both carry with the checks that go with
them, and rustfmt, which lays out every Rust output."""

import re
from collections.abc import Container, Iterable
from dataclasses import dataclass

from langxyne import naming
from langxyne.emitters import c, emitter
from langxyne.model import (
    TEXT_DEFINER,
    UNION_CLAUSE_DEFINER,
    UNION_ERROR_DEFINER,
    Api,
    BitConst,
    EnumEntry,
    Function,
    Group,
    LiteralTerm,
    Param,
    StringConst,
    Struct,
    Term,
    TypedConst,
    Union,
    duplicate_objections,
    headed,
)

# Strict, reserved and weak keywords of editions 2021 and 2024 (`gen`, reserved from 2024):
# the generated text compiles under either.
RUST_KEYWORDS = frozenset(
    "as break const continue crate else enum extern false fn for if impl in let loop match mod "
    "move mut pub ref return self Self static struct super trait true type unsafe use where while "
    "async await dyn abstract become box do final macro override priv typeof unsized virtual yield "
    "try gen union macro_rules".split()
)

PRELUDE_NAMES = ("Default", "Drop", "Err", "Ok", "Option", "Result", "Some", "String", "ToString", "TryFrom")
"""The Rust prelude's names a hand-written crate root commonly spells unqualified, which an
item imported there would shadow: the stub's list. The binding and the relay each list
the ones their own text spells, since a prelude trait whose name an item takes stays in
scope for method calls."""

# clippy's default `too_many_arguments` threshold: a function with more parameters, the
# receiver counted, is refused under `-D warnings`
_MAX_ARGUMENTS = 7
_C_VOID = "core::ffi::c_void"
_INDENT = " " * 4
# rustc's `non_snake_case` test of a name once its leading and trailing `_` are trimmed
_NOT_SNAKE_CASE = re.compile(r"[A-Z]|__")

LEN_HELPER = "c_len"
"""The count check every slice helper calls: the name `_LEN_TEXT` defines and each of
`_SLICE_TEXT` calls, which a rename changes in all four."""
SLICE_HELPERS = {"in": "c_slice", "inout": "c_slice_mut", "out": "c_out_slice"}
"""The slice helper a C pointer and count of each `_ref` goes through: the name its
`_SLICE_TEXT` defines, which a rename changes in both."""

# Every element type the loader admits in a buffer (u8 for `memory`; builtins, boxed
# scalars, and structs of them, of `text` and of enum aliases) is valid as all-zero bytes,
# which `OutSlice::take` relies on.
_OUT_SLICE_TEXT = f"""/// An `out` buffer of the caller's, `len()` elements the relay has not written: `take`
/// zero-fills it, since the caller's memory may be uninitialised, and hands it over, so a call
/// refused before the buffer is taken leaves the caller's memory as it was.
pub struct {naming.OUT_SLICE}<'a, T> {{
    ptr: *mut T,
    len: usize,
    _call: core::marker::PhantomData<&'a mut [T]>,
}}

impl<'a, T> {naming.OUT_SLICE}<'a, T> {{
    /// The buffer's length in elements.
    pub fn len(&self) -> usize {{
        self.len
    }}

    /// Whether the buffer holds no element.
    pub fn is_empty(&self) -> bool {{
        self.len == 0
    }}

    /// The buffer as a slice, zero-filled.
    pub fn take(self) -> &'a mut [T] {{
        // SAFETY: only `{SLICE_HELPERS["out"]}` builds one, from a non-null pointer aligned and valid for
        // writes of `len` elements for `'a`, of an element type valid as all-zero bytes.
        unsafe {{ self.ptr.write_bytes(0, self.len) }};
        unsafe {{ core::slice::from_raw_parts_mut(self.ptr, self.len) }}
    }}
}}
"""
_LEN_TEXT = """/// A C element count as the length of a slice of `T`: `None` below zero, or where the slice's
/// bytes would exceed `isize::MAX`.
fn c_len<T>(count: impl core::convert::TryInto<isize>) -> Option<usize> {
    let len = usize::try_from(count.try_into().ok()?).ok()?;
    let bytes = len.checked_mul(core::mem::size_of::<T>())?;
    isize::try_from(bytes).is_ok().then_some(len)
}
"""
_SLICE_TEXT = {
    "in": """/// A C `in` pointer and count as a slice: empty for null with a count of 0; `None` for null with
/// any other count, a misaligned pointer, or a count whose bytes exceed `isize::MAX`.
///
/// # Safety
///
/// A non-null `ptr` is valid for reads of `count` elements while the slice lives.
unsafe fn c_slice<'a, T>(ptr: *const T, count: impl core::convert::TryInto<isize>) -> Option<&'a [T]> {
    let len = c_len::<T>(count)?;
    if ptr.is_null() {
        return (len == 0).then_some(&[]);
    }
    if !ptr.is_aligned() {
        return None;
    }
    Some(unsafe { core::slice::from_raw_parts(ptr, len) })
}
""",
    "inout": """/// A C `inout` buffer as the implementation's slice: `None` for a null or misaligned pointer, or a
/// count whose bytes exceed `isize::MAX`.
///
/// # Safety
///
/// A non-null `ptr` is valid for reads and writes of `count` initialised elements while the
/// slice lives.
unsafe fn c_slice_mut<'a, T>(ptr: *mut T, count: impl core::convert::TryInto<isize>) -> Option<&'a mut [T]> {
    let len = c_len::<T>(count)?;
    if ptr.is_null() || !ptr.is_aligned() {
        return None;
    }
    Some(unsafe { core::slice::from_raw_parts_mut(ptr, len) })
}
""",
    "out": f"""/// A C `out` buffer as the implementation's `{naming.OUT_SLICE}`, written by nothing until the
/// implementation takes it: `None` for a null or misaligned pointer, or a count whose bytes
/// exceed `isize::MAX`.
///
/// # Safety
///
/// A non-null `ptr` is valid for writes of `count` elements for `'a`, and `T` is valid as
/// all-zero bytes.
unsafe fn {SLICE_HELPERS["out"]}<'a, T>(ptr: *mut T, count: impl core::convert::TryInto<isize>) -> Option<{naming.OUT_SLICE}<'a, T>> {{
    let len = c_len::<T>(count)?;
    if ptr.is_null() || !ptr.is_aligned() {{
        return None;
    }}
    Some({naming.OUT_SLICE} {{ ptr, len, _call: core::marker::PhantomData }})
}}
""",
}


def slice_helpers(refs: Container[str]) -> list[tuple[str, str]]:
    """(name, text) of the private functions that turn a C pointer and count into a slice:
    `c_len`, then, for `out`, the public `naming.OUT_SLICE` its helper builds, then the helper
    of each `_ref` in `refs`, in `SLICE_HELPERS`' order; none where `refs` holds none of them.
    Each helper is generic over the element, a `memory` pointer reaching it as `u8`, and is
    called as `self::c_slice(...)`, a path no parameter shadows. The one statement of both what
    a file emits and what it defines at module scope."""
    helpers = [(SLICE_HELPERS[r], text) for r, text in _SLICE_TEXT.items() if r in refs]
    if not helpers:
        return []
    out_slice = [(naming.OUT_SLICE, _OUT_SLICE_TEXT)] if "out" in refs else []
    return [(LEN_HELPER, _LEN_TEXT), *out_slice, *helpers]


def rustfmt(text: str) -> str:
    """`text` as `rustfmt --edition 2024` lays it out under its default configuration;
    `--config-path /dev/null` keeps any `rustfmt.toml`, beside the cwd, above it or in the
    user's configuration directory, from reaching the output."""
    return emitter.formatted(
        ["rustfmt", "--edition", "2024", "--config-path", "/dev/null"],
        text,
        outputs="the Rust outputs",
        output="a Rust output",
    )


def rust_keyword_objections(api: Api) -> list[str]:
    """Every name that is a Rust keyword, unprefixed by an output."""
    return [f"{where}: '{name}' is a Rust keyword" for where, name in api.names() if name in RUST_KEYWORDS]


def snake_case_objections(names: Iterable[tuple[str, str]]) -> list[str]:
    """Every (where, rendered name) pair whose name rustc's `non_snake_case` lint refuses,
    a warning `-D warnings` makes an error. The caller passes only names the lint reaches:
    it skips `no_mangle` and `extern`-block function names."""
    return [
        f"{where}: '{name}' is not snake_case (an uppercase letter or '__'), which rustc requires of it"
        for where, name in names
        if _NOT_SNAKE_CASE.search(name.strip("_"))
    ]


def field_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of every struct field, which both Rust outputs render as a field."""
    return [(f"struct.{s.name}.{f.name}", f.name) for s in api.structs for f in s.fields]


def param_names(where: str, params: Iterable[Param]) -> list[tuple[str, str]]:
    """(where, name) of each of `params` of the function or callback at `where` and of what
    each brings beside itself: a buffer's count and reports, a callback's `user_data`."""
    return [(f"{where}.{p.name}", name) for p in params for name in (p.name, *p.derived_names())]


def opaque_field_objections(api: Api) -> list[str]:
    """A struct field of opaque type: the structs derive `Default`, which a raw pointer
    has not."""
    return [
        f"struct.{s.name}.{f.name}: a field of opaque_ref type is not implemented for Rust"
        for s in api.structs
        for f in s.fields
        if api.kind(f.type) == "opaque"
    ]


def _doc_lines(lines: Iterable[str], *, indent: str = "") -> str:
    """Each of `lines` as a `///` line, an empty one as a bare `///`."""
    return "".join(f"{indent}///{' ' + line if line else ''}\n" for line in lines)


def doc_comment(doc: str | None, *, indent: str = "") -> str:
    """An item's docstring as a `///` line above it."""
    return _doc_lines([doc] if doc else [], indent=indent)


def function_docs(fn: Function, *, extra: Iterable[str] = (), safety: Iterable[str] = (), indent: str = "") -> str:
    """A function's `///` lines: its docstring, then each parameter's and `extra`, then,
    where `safety` has lines, a `# Safety` section holding them; a bare `///` ends the
    docstring before whatever follows it, so rustdoc keeps it a paragraph of its own and
    clippy reads no list or quote marker it opens with as running into the next line."""
    docstring = [fn.docstring] if fn.docstring else []
    rest = [*fn.docs()[len(docstring) :], *extra]
    safety = list(safety)
    lines = [*docstring, *([""] if docstring and rest else []), *rest]
    if safety:
        lines += [*([""] if lines else []), "# Safety", "", *safety]
    return _doc_lines(lines, indent=indent)


def many_arguments_allow(count: int, *, indent: str = "") -> str:
    """The `too_many_arguments` allow above a function of `count` parameters, the receiver
    counted, where clippy's default threshold refuses it; else nothing."""
    return f"{indent}#[allow(clippy::too_many_arguments)]\n" if count > _MAX_ARGUMENTS else ""


def group_comment(doc: str | None, *, indent: str = "") -> str:
    """A group's docstring as a `//` line: a group is no item to document."""
    return f"{indent}// {doc}\n" if doc else ""


def rust_type(api: Api, type_name: str, *, path: str = "") -> str:
    """FFI spelling of a definition type used by value: a builtin is its own Rust name, any
    other type its C name, an enum's and an opaque's being their aliases, after `path`
    (`ffi::`) where the C names live in another module."""
    if type_name in naming.BUILTIN_C_TYPES:
        return type_name
    return path + naming.type_name(api.namespace, type_name)


def _param_type(api: Api, param: Param, *, path: str = "") -> str:
    """FFI spelling of a parameter: `rust_type()` by value, a raw pointer to it through
    `_ref`, a `c_void` pointer for `memory`, a pointer to the prefix for a union's list."""
    if param.type == "memory":
        return f"*const {_C_VOID}" if param.ref == "in" else f"*mut {_C_VOID}"
    if param.is_union:
        return f"*const {rust_type(api, api.union(param.type).prefix, path=path)}"
    base = rust_type(api, param.type, path=path)
    if param.ref == "in":
        return f"*const {base}"
    if param.ref is not None:
        return f"*mut {base}"
    return base


def ffi_params(api: Api, param: Param, *, path: str = "") -> list[tuple[str, str]]:
    """(Rust type, name) of each FFI parameter a definition parameter becomes: a buffer is
    the pointer, its count, and a pointer to each report of the count's type, a union's list
    the pointer, its count and its byte extent; a callback its `ffi` alias and its
    `user_data`; every other parameter itself."""
    pairs = [(_param_type(api, param, path=path), param.name)]
    if param.is_union:
        pairs += [(param.count_type, param.count_name()), (param.count_type, param.bytes_name())]
    elif param.is_buffer:
        pairs.append((param.count_type, param.count_name()))
        pairs += [(f"*mut {param.count_type}", report) for report in param.report_names()]
    if param.callback:
        pairs.append((f"*mut {_C_VOID}", param.user_data_name()))
    return pairs


def value_type(api: Api, type_name: str) -> str:
    """A non-memory type as a file spells it where `reexports()` and `ffi` are in scope: a
    boxed scalar or struct by its re-export, every other type `rust_type()` under `ffi::`."""
    if api.kind(type_name) in ("boxed", "struct"):
        return naming.upper_camel(type_name)
    return rust_type(api, type_name, path="ffi::")


def out_default(api: Api, type_name: str) -> str:
    """The function an `out` local of a non-memory type starts from: a null handle, else
    `value_type()`'s `default`."""
    if api.kind(type_name) == "opaque":
        return "core::ptr::null_mut"
    return f"{value_type(api, type_name)}::default"


def implementation_type(api: Api, param: Param) -> str:
    """The type the relay hands the implementation `param` as: an `out` buffer its
    `naming.OUT_SLICE` of bytes or of `value_type()`, any other buffer one slice of them, `None`
    for null; a callback an `Option` of the relay's wrapper of it,
    `None` for null; a pointer an `Option` of a reference to `value_type()`, `None` for null;
    by value `value_type()` itself; a union's list an `Option` of its sequence, `None` for a
    null or malformed base."""
    if param.is_union:
        return f"Option<{naming.union_sequence(param.type)}<'_>>"
    if param.is_buffer and param.ref == "out":
        return f"Option<{naming.OUT_SLICE}<'_, {_element(api, param)}>>"
    if param.is_buffer:
        return f"Option<{view_type(api, param, mutable=param.ref == 'inout')}>"
    if param.callback:
        return f"Option<{naming.upper_camel(param.type)}<'_>>"
    base = value_type(api, param.type)
    if param.ref == "in":
        return f"Option<&{base}>"
    if param.ref is not None:
        return f"Option<&mut {base}>"
    return base


def implementation_params(api: Api, fn: Function) -> list[tuple[str, str]]:
    """(name, `implementation_type()`) of each parameter the implementation of `fn` takes, in
    order: each definition parameter, a buffer one slice that carries its count, followed by
    its reports as `Option<&mut>` of the count's type. The relay's pin and the stub's
    signature both read it."""
    params = []
    for p in fn.params:
        params.append((p.name, implementation_type(api, p)))
        params += [(report, f"Option<&mut {p.count_type}>") for report in p.report_names()]
    return params


def view_type(api: Api, param: Param, *, mutable: bool = False) -> str:
    """A buffer as a slice of bytes or of `value_type()`, as the relay and its callbacks spell it."""
    return f"&mut [{_element(api, param)}]" if mutable else f"&[{_element(api, param)}]"


def _element(api: Api, param: Param) -> str:
    """A buffer's element: `u8` for `memory`, else `value_type()`."""
    return "u8" if param.type == "memory" else value_type(api, param.type)


def callback_c_params(api: Api, callback: Function, *, path: str = "") -> list[tuple[str, str]]:
    """(Rust type, name) of each parameter of `callback`'s C function type: each of its
    parameters' `ffi_params()`, then its own `user_data`."""
    params = [pair for p in callback.params for pair in ffi_params(api, p, path=path)]
    return [*params, (f"*mut {_C_VOID}", naming.USER_DATA)]


def callback_fn_type(api: Api, callback: Function, *, path: str = "") -> str:
    """`callback`'s C function type, the pointer its `ffi` alias holds where it is not null."""
    params = ", ".join(f"{n}: {t}" for t, n in callback_c_params(api, callback, path=path))
    return f'unsafe extern "C" fn({params}) -> {rust_type(api, callback.returns, path=path)}'


def signature(api: Api, fn: Function, *, prefix: str, path: str = "") -> str:
    """`fn`'s FFI signature from `prefix` (`pub unsafe extern "C" fn `) to its return type,
    every C-named type after `path`."""
    parts = ", ".join(f"{n}: {t}" for p in fn.params for t, n in ffi_params(api, p, path=path))
    return f"{prefix}{naming.function_name(api.namespace, fn.name)}({parts}) -> {rust_type(api, fn.returns, path=path)}"


def abi_file_name(name: str) -> str:
    """The relay's file name, which the relay is written as and the stub includes."""
    return f"{name}_abi.rs"


def ffi_module(blocks: Iterable[str], *, tail: str = "") -> str:
    """`pub mod ffi`, where the C names live: each of `blocks` indented under a blank line,
    then `tail`, already indented."""
    body = "".join("\n" + _indented(b, _INDENT) for b in blocks)
    return f"pub mod ffi {{\n    #![allow(non_camel_case_types)]\n{body}{tail}}}\n"


def reexports(api: Api) -> str:
    """Each boxed scalar, the text type where some field is text, then each struct,
    re-exported from `ffi` under its UpperCamel name, the first of a documented group's under
    its `group_comment()`; empty where there is none."""
    text = [(None, naming.TEXT)] if api.uses_text() else []
    return "".join(
        f"{group_comment(h)}pub use ffi::{naming.type_name(api.namespace, name)} as {naming.upper_camel(name)};\n"
        for h, name in (
            *((h, b.name) for h, b in headed(api.boxed_scalar_groups)),
            *text,
            *((h, s.name) for h, s in headed(api.struct_groups)),
        )
    )


def enum_blocks(api: Api) -> list[str]:
    """`enum_block()` for each enum in document order, the first of a documented group's
    under its `group_comment()`."""
    return [group_comment(h) + enum_block(t) for h, t in headed(api.typed_const_groups)]


def enum_block(typed: TypedConst) -> str:
    """The enum over its C values, its `TryFrom` from the base type, and with a conversion
    that conversion and a `Display` through it."""
    cls, base = naming.upper_camel(typed.name), typed.base_type
    entries = [(naming.upper_camel(e.name), c.int_literal(e.value, e.format), e) for e in typed.entries]
    variants = "".join(f"{doc_comment(e.docstring, indent=_INDENT)}    {v} = {lit},\n" for v, lit, e in entries)
    arms = "".join(f"            {lit} => Ok({cls}::{v}),\n" for v, lit, _ in entries)
    text = (
        f"{doc_comment(typed.docstring)}#[repr({base})]\n#[derive(Clone, Copy, Debug, PartialEq, Eq)]\n"
        f"pub enum {cls} {{\n{variants}}}\n"
        f"\nimpl core::convert::TryFrom<{base}> for {cls} {{\n    type Error = {base};\n\n"
        f"    fn try_from(raw: {base}) -> core::result::Result<{cls}, {base}> {{\n"
        f"        match raw {{\n{arms}            _ => Err(raw),\n        }}\n    }}\n}}\n"
    )
    if typed.to_string is not None:
        names = "".join(f'            {cls}::{v} => "{naming.unprefixed_const_name(e.name)}",\n' for v, _, e in entries)
        text += (
            f"\nimpl {cls} {{\n    pub fn {typed.to_string}(self) -> &'static str {{\n"
            f"        match self {{\n{names}        }}\n    }}\n}}\n"
            f"\nimpl core::fmt::Display for {cls} {{\n"
            "    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {\n"
            f"        f.write_str({cls}::{typed.to_string}(*self))\n    }}\n}}\n"
        )
    return text


def type_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of every enum, boxed scalar and struct, the types `enum_block()` and
    `reexports()` name in UpperCamel at module scope."""
    names = [(f"typed_const.{t.name}", t.name) for t in api.typed_consts]
    names += [(f"boxed_scalar.{b.name}", b.name) for b in api.boxed_scalars]
    names += [(f"struct.{s.name}", s.name) for s in api.structs]
    return names


def callback_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of every callback type, which the relay's wrapper of it names in
    UpperCamel at module scope."""
    return [(f"callback.{c.name}", c.name) for c in api.callbacks]


def camel_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of every name `enum_block()`, `reexports()`, `union_blocks()` and the
    relay's callback wrappers render in UpperCamel: `type_names()`, `callback_names()`, each
    enum entry and each list union's member, a variant of its ref enum."""
    entries = [(f"typed_const.{t.name}.{e.name}", e.name) for t in api.typed_consts for e in t.entries]
    members = [(f"union.{u.name}.{m.name}", m.name) for u in api.listed_unions() for m in u.members]
    return type_names(api) + callback_names(api) + entries + members


def camel_keyword_objections(names: Iterable[tuple[str, str]]) -> list[str]:
    """Each of `names`' (where, name) whose UpperCamel rendering is a Rust keyword the name
    itself is not."""
    return [
        f"{where}: '{name}' renders as '{naming.upper_camel(name)}', a Rust keyword"
        for where, name in names
        if naming.upper_camel(name) in RUST_KEYWORDS and name not in RUST_KEYWORDS
    ]


def enum_conversion_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of each enum's `_to_string` conversion, a method `enum_block()`
    renders where rustc's `non_snake_case` reaches it."""
    return [(f"typed_const.{t.name}._to_string", t.to_string) for t in api.typed_consts if t.to_string is not None]


def prelude_names(names: Iterable[str] = PRELUDE_NAMES) -> list[tuple[str, str]]:
    """(definer, name) of each of the prelude's `names`, for a module-scope duplicate check."""
    return [("the Rust prelude", name) for name in names]


def module_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of what `enum_block()` and `reexports()` define at module scope."""
    names = [(where, naming.upper_camel(name)) for where, name in type_names(api)]
    if api.uses_text():
        names.append((TEXT_DEFINER, naming.upper_camel(naming.TEXT)))
    return names


def enum_member_objections(api: Api) -> list[str]:
    """A name `enum_block()` would define twice in one enum: an entry, `try_from`, its
    conversion."""
    objections = []
    for t in api.typed_consts:
        members = [(f"typed_const.{t.name}.{e.name}", naming.upper_camel(e.name)) for e in t.entries]
        members.append(("the generated TryFrom conversion", "try_from"))
        if t.to_string is not None:
            members.append((f"typed_const.{t.name}._to_string", t.to_string))
        objections += duplicate_objections(members, f"enum {naming.upper_camel(t.name)}")
    return objections


def enum_alias(api: Api, typed: TypedConst) -> str:
    """An enum's C name aliasing its base type, under its docstring: the FFI's enum type."""
    return (
        f"{doc_comment(typed.docstring)}pub type {naming.type_name(api.namespace, typed.name)} = {typed.base_type};\n"
    )


def version_constant(api: Api, *, prefixed: bool) -> str:
    """The version as a `u32` constant, its four bytes as eight hex digits."""
    return f"pub const {_const_name(api, naming.VERSION_KEY, prefixed=prefixed)}: u32 = 0x{api.version_value():08x};\n"


def constant_group(api: Api, group: Group[BitConst] | Group[EnumEntry], *, prefixed: bool) -> str:
    """A bit or plain group as one `pub const` per entry under its docstring, typed by the
    group's base type, C-named or with `prefixed` false unprefixed: a single bit as 1
    shifted, a composed entry as its terms joined by `|` in a bit group and `+` in a plain
    one, a literal spelled per its format with the sign in front."""
    lines = []
    for e in group.entries:
        if e.parts:
            operator = "|" if isinstance(e, BitConst) else "+"
            value = _sum(api, e.parts, operator=operator, prefixed=prefixed)
        elif isinstance(e, BitConst):
            value = f"1 << {e.bit}"
        else:
            value = c.int_literal(e.value, e.format)
        name = _const_name(api, e.name, prefixed=prefixed)
        lines.append(f"{doc_comment(e.docstring)}pub const {name}: {group.base_type} = {value};\n")
    return group_comment(group.docstring) + "".join(lines)


def string_group(api: Api, group: Group[StringConst], *, prefixed: bool) -> str:
    """A string group as one `pub const ...: &str` per entry under its docstring."""
    return group_comment(group.docstring) + "".join(
        f'{doc_comment(s.docstring)}pub const {_const_name(api, s.name, prefixed=prefixed)}: &str = "{s.value}";\n'
        for s in group.entries
    )


def type_definitions(api: Api) -> list[str]:
    """One block per opaque ref (its pointer alias and the struct it points to), boxed
    scalar (a transparent newtype), the text type where some field is text, struct, and
    callback type (an `Option` of its C function type, `None` for null), at the C header's
    ABI, in that order, the first of a documented group's under its `group_comment()`."""
    ns = api.namespace
    boxed_derive = "#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]\n"
    struct_derive = "#[derive(Clone, Copy, Debug, Default, PartialEq)]\n"
    text_derive = "#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]\n"
    blocks = [
        f"{group_comment(h)}{doc_comment(o.docstring)}"
        f"pub type {naming.type_name(ns, o.name)} = *mut {naming.opaque_struct(ns, o.name)};\n"
        f"#[repr(C)]\npub struct {naming.opaque_struct(ns, o.name)} {{\n    _private: [u8; 0],\n}}\n"
        for h, o in headed(api.opaque_ref_groups)
    ]
    blocks += [
        f"{group_comment(h)}{doc_comment(b.docstring)}#[repr(transparent)]\n{boxed_derive}"
        f"pub struct {naming.type_name(ns, b.name)}(pub {b.base_type});\n"
        for h, b in headed(api.boxed_scalar_groups)
    ]
    if api.uses_text():
        fields = "".join(f"    pub {n}: {t},\n" for n, t in naming.TEXT_FIELDS)
        blocks.append(
            f"#[repr(C)]\n{text_derive}pub struct {naming.type_name(ns, naming.TEXT)} {{\n{fields}}}\n",
        )
    blocks += [
        f"{group_comment(h)}{doc_comment(s.docstring)}#[repr(C)]\n{struct_derive}"
        f"pub struct {naming.type_name(ns, s.name)} {{\n"
        + "".join(
            f"{doc_comment(f.docstring, indent='    ')}    pub {f.name}: {rust_type(api, f.type)},\n" for f in s.fields
        )
        + "}\n"
        for h, s in headed(api.struct_groups)
    ]
    blocks += [
        f"{group_comment(h)}{function_docs(cb)}"
        f"pub type {naming.type_name(ns, cb.name)} = Option<{callback_fn_type(api, cb)}>;\n"
        for h, cb in headed(api.callback_groups)
    ]
    return blocks


UNION_ERROR = naming.UNION_ERROR
UNION_CLAUSE = naming.UNION_CLAUSE_TYPE
# The two module-scope types every file rendering a list union defines once, by what defines them.
_UNION_DEFINERS = ((UNION_ERROR_DEFINER, UNION_ERROR), (UNION_CLAUSE_DEFINER, UNION_CLAUSE))
# Each clause's variant, by its name in `naming.UNION_CLAUSES`, and its text, in the C enum's order from 1.
_UNION_CLAUSES = tuple((naming.upper_camel(name), text) for name, text in naming.UNION_CLAUSES)
_CLAUSE = {name: f"{UNION_CLAUSE}::{naming.upper_camel(name)}" for name, _ in naming.UNION_CLAUSES}


@dataclass(frozen=True)
class UnionNames:
    """The module-scope names a list union renders: its sequence, the ref enum of its records,
    their iterator, its alignment constant, and in the relay its buffer and a place in that
    buffer."""

    sequence: str
    ref: str
    records: str
    align: str
    buf: str
    buf_mark: str


def union_names(union: Union) -> UnionNames:
    """`union`'s module-scope names: `NoteSequence`, `NoteRef`, `NoteRecords`, `NOTE_ALIGN`,
    `NoteBuf`, `NoteBufMark` for `note`."""
    u = union.name
    return UnionNames(
        naming.union_sequence(u),
        naming.rust_union_ref(u),
        naming.rust_union_records(u),
        naming.unprefixed_const_name(naming.union_align(u)),
        naming.rust_union_buf(u),
        naming.rust_union_buf_mark(u),
    )


def push_name(member: str) -> str:
    """The relay buffer's method appending a record of `member`: `push_line`."""
    return f"push_{member}"


def struct_named(api: Api, name: str) -> Struct:
    """The struct `name` of a validated definition."""
    return next(s for s in api.structs if s.name == name)


def union_module_names(api: Api, *, relay: bool) -> list[tuple[str, str]]:
    """(definer, name) of what `union_blocks()`, and in the relay its buffers, define at module
    scope."""
    unions = api.listed_unions()
    names = list(_UNION_DEFINERS) if unions else []
    for u in unions:
        n = union_names(u)
        names += [(f"union.{u.name}", name) for name in (n.sequence, n.ref, n.records, n.align)]
        names += [(f"union.{u.name}", name) for name in (n.buf, n.buf_mark)] if relay else []
    return names


def union_member_objections(api: Api) -> list[str]:
    """Two members of a list union rendering one variant of its ref enum."""
    return [
        o
        for u in api.listed_unions()
        for o in duplicate_objections(
            [(f"union.{u.name}.{m.name}", naming.upper_camel(m.name)) for m in u.members],
            f"enum {union_names(u).ref}",
        )
    ]


def union_blocks(api: Api) -> list[str]:
    """`UnionClause` and `UnionError` where some union declares `_mixed_type_list`, then per
    such union, the first of a documented group's under its `group_comment()`: its ref enum,
    the layout assertions holding the prefix and each member to `Api.layout()`, the list's
    alignment constant, its sequence and the iterator of its records, the walk reading a prefix only once its bytes remain and a
    member only once its tag names it and its size is the member's, every size and the
    alignment a literal from `Api.layout()`; none for a union without the property."""
    headed_unions = [(h, u) for h, u in headed(api.union_groups) if u.mixed_type_list]
    if not headed_unions:
        return []
    return [
        _UNION_CLAUSE_TEXT + "\n" + _UNION_ERROR_TEXT,
        *(group_comment(h) + _union_block(api, u) for h, u in headed_unions),
    ]


def sequence_constructor(api: Api, union: Union) -> str:
    """The private `from_c` of `union`'s sequence: a C pointer, count and byte extent as the
    sequence, `None` for null but with 0 and 0, a pointer the prefix's alignment refuses, or a
    count or extent `u32` cannot hold or whose bytes exceed `isize::MAX`; a file renders it for
    a union whose list reaches it from C."""
    n = union_names(union)
    prefix = naming.upper_camel(union.prefix)
    return (
        f"impl {n.sequence}<'_> {{\n"
        "    /// The sequence over a C pointer, its count and its byte extent: empty for null with 0 and 0;\n"
        "    /// `None` for null otherwise, a pointer not aligned to the prefix, or a count or extent `u32`\n"
        "    /// cannot hold or whose bytes exceed `isize::MAX`.\n"
        "    ///\n    /// # Safety\n    ///\n"
        "    /// A non-null `ptr` is valid for reads of `bytes` bytes for as long as the sequence lives.\n"
        f"    unsafe fn from_c(ptr: *const {prefix}, count: impl core::convert::TryInto<u32>, "
        "bytes: impl core::convert::TryInto<u32>) -> Option<Self> {\n"
        "        let count = count.try_into().ok()?;\n"
        "        let len = usize::try_from(isize::try_from(bytes.try_into().ok()?).ok()?).ok()?;\n"
        "        if ptr.is_null() {\n"
        f"            return (count == 0 && len == 0).then_some({n.sequence} {{ bytes: &[], count }});\n"
        "        }\n"
        "        if !ptr.is_aligned() {\n            return None;\n        }\n"
        "        let bytes = unsafe { core::slice::from_raw_parts(ptr.cast::<u8>(), len) };\n"
        f"        Some({n.sequence} {{ bytes, count }})\n"
        "    }\n"
        "}\n"
    )


def sequence_arguments(
    param: Param, *, pointer: str, count: str, length: str, context: str
) -> tuple[list[str], list[str]]:
    """The statements and C arguments passing a list union's sequence as `param`'s three C
    parameters, from the expressions of its pointer, its `u32` count and its `usize` byte
    length: the count and the extent each a local of `param`'s count type, one it cannot
    hold panicking with a message after `context`."""
    ct = param.count_type
    if ct == "u32":
        counted = count
    elif ct == "u64":
        counted = f"u64::from({count})"
    else:
        counted = f'{ct}::try_from({count}).expect("{context}{param.name} holds more records than {ct} can count")'
    statements = [
        f"let {param.count_name()} = {counted};",
        f"let {param.bytes_name()} = {ct}::try_from({length})"
        f'.expect("{context}{param.name} is longer than {ct} can count");',
    ]
    return statements, [f"{pointer}.cast()", param.count_name(), param.bytes_name()]


_UNION_CLAUSE_TEXT = (
    "/// Why a walk of a union's list refused it, beside the record's index and byte offset in a\n"
    f"/// `{UNION_ERROR}`.\n"
    f"#[repr(i32)]\n#[derive(Clone, Copy, Debug, PartialEq, Eq)]\npub enum {UNION_CLAUSE} {{\n"
    + "".join(
        f"    /// {text}\n    {variant}{' = 1' if i == 0 else ''},\n"
        for i, (variant, text) in enumerate(_UNION_CLAUSES)
    )
    + "}\n\n"
    f"impl core::fmt::Display for {UNION_CLAUSE} {{\n"
    "    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {\n"
    "        f.write_str(match self {\n"
    + "".join(f'            {UNION_CLAUSE}::{variant} => "{text}",\n' for variant, text in _UNION_CLAUSES)
    + "        })\n    }\n}\n"
)
_UNION_ERROR_TEXT = (
    "/// Where a walk of a sequence refused it: the record's index, its byte offset, the clause.\n"
    f"#[derive(Clone, Copy, Debug, PartialEq, Eq)]\npub struct {UNION_ERROR} {{\n"
    f"    pub index: u32,\n    pub offset: u32,\n    pub clause: {UNION_CLAUSE},\n}}\n\n"
    f"impl core::fmt::Display for {UNION_ERROR} {{\n"
    "    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {\n"
    '        write!(f, "record {} at offset {}: {}", self.index, self.offset, self.clause)\n'
    "    }\n}\n"
)


def _union_block(api: Api, union: Union) -> str:
    """`union`'s ref enum, layout assertions, alignment constant, sequence and records iterator."""
    n = union_names(union)
    prefix = naming.upper_camel(union.prefix)
    prefix_size, align = api.layout(union.prefix)[0], api.list_alignment(union)
    tag, length = union.tag_field, union.length_field
    members = [
        (naming.upper_camel(m.name), naming.upper_camel(m.struct), _tag_value(api, m.tag), api.layout(m.struct)[0], m)
        for m in union.members
    ]
    variants = "".join(f"{doc_comment(m.docstring, indent=_INDENT)}    {v}(&'a {s}),\n" for v, s, _, _, m in members)
    asserts = "".join(
        f"const _: () = assert!(core::mem::size_of::<{s}>() == {size} && core::mem::align_of::<{s}>() == {align});\n"
        for s, size in ((prefix, prefix_size), *((s, size) for _, s, _, size, _ in members))
    )
    sizes = "".join(f"            {value} => {size},\n" for _, _, value, size, _ in members)
    # the tag is one of the members' once its size is found, so the last member's arm is `_`
    casts = [
        (str(value) if i < len(members) - 1 else "_", f"{n.ref}::{v}(&*start.cast::<{s}>())")
        for i, (v, s, value, _, _) in enumerate(members)
    ]
    if len(casts) == 1:
        cast = casts[0][1]
    else:
        cast = (
            f"match head.{tag} {{\n"
            + "".join(f"                {arm} => {value},\n" for arm, value in casts)
            + "            }"
        )
    error = f"{UNION_ERROR} {{ index: self.index, offset: self.offset as u32, clause }}"
    return (
        f"{doc_comment(union.docstring)}#[derive(Clone, Copy, Debug)]\npub enum {n.ref}<'a> {{\n{variants}}}\n\n"
        f"{asserts}\n"
        f"/// The list's alignment, the unit of `{n.sequence}::at`'s index.\n"
        f"pub const {n.align}: usize = {align};\n\n"
        f"/// A list of `{union.name}`'s members back to back, each by its own size, as a C caller or the\n"
        "/// library delivered it: `records()` walks it and `at()` resolves an offset in units of the list's\n"
        "/// alignment, each refusing a malformed record and reading no byte past the extent.\n"
        f"#[derive(Clone, Copy)]\npub struct {n.sequence}<'a> {{\n    bytes: &'a [u8],\n    count: u32,\n}}\n\n"
        f"impl<'a> {n.sequence}<'a> {{\n"
        "    /// The number of records, as the producer counted them.\n"
        "    pub fn count(&self) -> u32 {\n        self.count\n    }\n\n"
        "    /// The records' bytes, the extent their length.\n"
        "    pub fn bytes(&self) -> &'a [u8] {\n        self.bytes\n    }\n\n"
        "    /// The records in order, ending at the first one refused, which is yielded as the error.\n"
        f"    pub fn records(&self) -> {n.records}<'a> {{\n"
        f"        {n.records} {{ sequence: *self, offset: 0, index: 0, done: false }}\n    }}\n\n"
        f"    /// The record at byte `index` × `{n.align}` from the sequence's start, found by walking from\n"
        "    /// the start, the byte offset saturating at `u32::MAX`.\n"
        f"    pub fn at(&self, index: u32) -> Result<{n.ref}<'a>, {UNION_ERROR}> {{\n"
        f"        let offset = index.saturating_mul({n.align} as u32);\n"
        "        let target = offset as usize;\n"
        "        let mut records = self.records();\n"
        "        loop {\n"
        "            let (walked, here) = (records.index, records.offset);\n"
        "            match records.next() {\n"
        "                Some(Ok(record)) if here == target => return Ok(record),\n"
        "                Some(Ok(_)) if here < target => {}\n"
        "                Some(Err(error)) => return Err(error),\n"
        f"                _ => return Err({UNION_ERROR} {{ index: walked, offset, clause: {_CLAUSE['not_a_record_start']} }}),\n"
        "            }\n"
        "        }\n"
        "    }\n\n"
        "    /// The record at byte `offset`, a record's start the walk reached, and its size: refused where\n"
        "    /// fewer than the prefix's bytes remain, its tag names no member, its size is not that member's,\n"
        "    /// or its bytes pass the extent.\n"
        f"    fn record(&self, offset: usize) -> Result<({n.ref}<'a>, usize), {UNION_CLAUSE}> {{\n"
        "        let rest = &self.bytes[offset..];\n"
        f"        if rest.len() < {prefix_size} {{\n            return Err({_CLAUSE['header_past_extent']});\n        }}\n"
        "        let start = rest.as_ptr();\n"
        "        // SAFETY: the sequence's start is aligned to the prefix and every size the walk stepped by is\n"
        "        // a multiple of its alignment; the prefix's bytes remain, and any bytes are a valid prefix.\n"
        f"        let head = unsafe {{ &*start.cast::<{prefix}>() }};\n"
        f"        let size = match head.{tag} {{\n{sizes}            _ => return Err({_CLAUSE['unknown_tag']}),\n        }};\n"
        f"        if head.{length} as usize != size {{\n            return Err({_CLAUSE['size_not_the_members']});\n        }}\n"
        f"        if rest.len() < size {{\n            return Err({_CLAUSE['record_past_extent']});\n        }}\n"
        "        // SAFETY: as for the prefix, whose alignment every member has; the tag names this member,\n"
        "        // its size remains, and any bytes are a valid member.\n"
        f"        let record = unsafe {{ {cast} }};\n"
        "        Ok((record, size))\n"
        "    }\n"
        "}\n\n"
        f"/// The walk of a `{n.sequence}`: each record in order, then, where the walk refuses one, its error\n"
        "/// once.\n"
        f"pub struct {n.records}<'a> {{\n    sequence: {n.sequence}<'a>,\n    offset: usize,\n    index: u32,\n    done: bool,\n}}\n\n"
        f"impl<'a> Iterator for {n.records}<'a> {{\n"
        f"    type Item = Result<{n.ref}<'a>, {UNION_ERROR}>;\n\n"
        "    fn next(&mut self) -> Option<Self::Item> {\n"
        "        if self.done {\n            return None;\n        }\n"
        "        let left = self.sequence.bytes.len() - self.offset;\n"
        "        let counted = self.index == self.sequence.count;\n"
        "        if left == 0 && counted {\n            self.done = true;\n            return None;\n        }\n"
        "        let walked = if left == 0 || counted {\n"
        f"            Err({_CLAUSE['count_not_met']})\n"
        "        } else {\n            self.sequence.record(self.offset)\n        };\n"
        "        match walked {\n"
        "            Ok((record, size)) => {\n"
        "                self.offset += size;\n                self.index += 1;\n                Some(Ok(record))\n"
        "            }\n"
        "            Err(clause) => {\n"
        f"                self.done = true;\n                Some(Err({error}))\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n\n"
        f"impl core::iter::FusedIterator for {n.records}<'_> {{}}\n"
    )


def _tag_value(api: Api, tag: str) -> int:
    """The value of the `untyped_const` entry `tag`."""
    return next(e.value for e in api.consts if e.name == tag)


def _indented(text: str, indent: str) -> str:
    return "".join(indent + line if line.strip() else line for line in text.splitlines(keepends=True))


def _const_name(api: Api, key: str, *, prefixed: bool) -> str:
    return naming.const_name(api.namespace, key) if prefixed else naming.unprefixed_const_name(key)


def _sum(api: Api, parts: tuple[Term, ...], *, operator: str, prefixed: bool) -> str:
    """A composed entry's value, symbolic and unparenthesised: Rust's unary minus binds
    tighter than `+` and `|`, so a negative literal term needs none."""
    return f" {operator} ".join(
        c.int_literal(p.value, p.format) if isinstance(p, LiteralTerm) else _const_name(api, p, prefixed=prefixed)
        for p in parts
    )
