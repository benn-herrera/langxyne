"""The Node binding: an ES module that instantiates the library's WASI module, built beside the
relay and the wasm shim, and marshals every call through the shim's allocator in linear memory;
the constants, enums, conversions, structures and raw handle classes at module scope, and per
instance one class per opaque ref that names a constructor and every other function. Its
companion is the TypeScript declarations of the same module."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from langxyne import naming
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

LABEL = "node"

_RESERVED = frozenset(
    "await break case catch class const continue debugger default delete do else enum export extends false "
    "finally for function if implements import in instanceof interface let new null package private protected "
    "public return static super switch this throw true try typeof var void while with yield arguments eval".split()
)
"""JavaScript's reserved words in a module's strict code, `arguments` and `eval` among them, none
of which binds a parameter or a function."""
_GLOBALS = (
    "Array",
    "ArrayBuffer",
    "DataView",
    "Error",
    "Map",
    "Math",
    "Number",
    "Object",
    "RangeError",
    "String",
    "Symbol",
    "TypeError",
    "Uint8Array",
    "WebAssembly",
    "undefined",
)
"""Every global the module spells, which a name the module defines, or a parameter, would shadow:
every other name a body spells beside the module's own begins with `_`."""
_CLASS_MEMBERS = ("constructor", "handle")
"""What every class defines itself beside its methods and cached `out`s."""
_STRUCT_FIELDS = ("constructor",)
"""A structure's property no field may be: TypeScript refuses a class field of that name."""
_SCALARS = {
    "i8": "Int8",
    "u8": "Uint8",
    "i16": "Int16",
    "u16": "Uint16",
    "i32": "Int32",
    "u32": "Uint32",
    "f32": "Float32",
    "f64": "Float64",
}
"""Each 32-bit-or-narrower builtin's `DataView` accessor stem."""
_WIDE = ("i64", "u64")
_I = "  "
_STATE = "_state"
_HANDLE = "_handle"
_HELD = "_held"
_ERROR = naming.NODE_ERROR
_CLAUSE_TEXTS = naming.UNION_CLAUSE_TEXTS
_POINTER = (4, 4)  # (size, alignment) of a pointer and of the opaque handle cell in wasm32
_EXTENT_MAX = 2**31 - 1  # isize::MAX in wasm32, the largest allocation Rust's Layout admits


def validate(api: Api) -> list[str]:
    """Every objection the Node binding has to `api`: a 64-bit type in any position; a struct
    field of opaque type; a JavaScript reserved word where the module binds a definition name; a
    struct field named like a structure's own property; a parameter named like a name its body
    spells or the module defines; a free function named like a parameter of `load`, which its
    declaration would shadow; a name defined twice at module scope, in the library or in a
    class; no library named; and a static link, since the module loads its library at run
    time."""
    objections = [f"{where}: a 64-bit type, {t}, is not implemented" for where, t in _wide_positions(api)]
    objections += [
        f"struct.{s.name}.{f.name}: a field of opaque_ref type is not implemented"
        for s in api.structs
        for f in s.fields
        if api.kind(f.type) == "opaque"
    ]
    params = [(f"function.{fn.name}.{p.name}", _arg_name(p)) for fn, rendered in _rendered(api) for p in rendered]
    bound = [*params, *((f"function.{fn.name}", fn.name) for fn in api.free_functions()), *_conversion_names(api)]
    objections += [f"{where}: '{name}' is a JavaScript reserved word" for where, name in bound if name in _RESERVED]
    fields = [(f"struct.{s.name}.{f.name}", f.name) for s in api.structs for f in s.fields]
    objections += generated_name_objections(fields, set(_STRUCT_FIELDS))
    module = _module_names(api)
    unions = _union_names(api)
    used = {*_GLOBALS, *(name for _, name in (*module, *unions))}
    objections += generated_name_objections(params, used)
    free = [(f"function.{fn.name}", fn.name) for fn in api.free_functions()]
    objections += generated_name_objections(free, set(naming.NODE_LOAD_PARAMS))
    objections += duplicate_objections([*(("the globals", name) for name in _GLOBALS), *module], "module scope")
    defined = {name: union for union, name in unions}
    objections += [
        f"{where}: module scope name {name} already defined by {defined[name]}"
        for where, name in module
        if name in defined
    ]
    for shape in api.classes():
        own = [*_CLASS_MEMBERS, *(["release"] if shape.dtor is not None else [])]
        objections += duplicate_objections(shape.members(own), f"class {naming.upper_camel(shape.opaque.class_name)}")
    if api.library.name is None:
        objections.append(emitter.NO_LIBRARY)
    if api.library.link == naming.STATIC:
        objections.append(
            f"--link={naming.STATIC}: the Node binding loads its module at run time and cannot link it statically"
        )
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("node") / f"{name}.mjs"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    """The TypeScript declarations of the module, beside it."""
    module = output_path(name=name, project="")
    return [(module.with_name(f"{name}.d.mts"), _declarations(api, module=module.name))]


def _wide_positions(api: Api) -> list[tuple[str, str]]:
    """(where, type) of every 64-bit type the definition holds: a struct field, a boxed scalar's
    base type, a function's or callback type's parameter, an array's element included, or a
    buffer's count."""
    found = [(f"struct.{s.name}.{f.name}", f.type) for s in api.structs for f in s.fields if f.type in _WIDE]
    found += [(f"boxed_scalar.{b.name}._base_type", b.base_type) for b in api.boxed_scalars if b.base_type in _WIDE]
    for kind, fns in (("function", api.functions), ("callback", api.callbacks)):
        for fn in fns:
            for p in fn.params:
                if p.type in _WIDE:
                    found.append((f"{kind}.{fn.name}.{p.name}", p.type))
                if p.count_type in _WIDE:
                    found.append((f"{kind}.{fn.name}.{p.name}._count", p.count_type))
    return found


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
    """(where, name) of everything the module and its declarations define at module scope, then
    what the library object holds, each of which `load` binds in the scope of every body."""
    camel = naming.upper_camel
    names = [(where, naming.unprefixed_const_name(name)) for where, name in api.constant_names(version=True)]
    names += _conversion_names(api)
    names += [(f"typed_const.{t.name}", camel(t.name)) for t in api.typed_consts]
    names += [(f"opaque_ref.{o.name}", naming.handle_type(o.name)) for o in api.opaque_refs]
    names += [(f"boxed_scalar.{b.name}", camel(b.name)) for b in api.boxed_scalars]
    if api.uses_text():
        names += [(f"the builtin type {naming.TEXT}", camel(naming.TEXT)), ("the text resolver", naming.RESOLVE)]
    names += [(f"struct.{s.name}", camel(s.name)) for s in api.structs]
    names += [(f"callback.{cb.name}", camel(cb.name)) for cb in api.callbacks]
    names += [("the module's own names", name) for name in naming.NODE_NAMES]
    for shape in api.classes():
        cls = camel(shape.opaque.class_name)
        names += [(f"opaque_ref.{shape.opaque.name}._class", n) for n in (cls, naming.node_constructor_type(cls))]
    names += [(f"function.{fn.name}", fn.name) for fn in api.free_functions()]
    return names


def _union_names(api: Api) -> list[tuple[str, str]]:
    """(definer, name) of what the module defines for its unions: each one's sequence class and
    alignment constant, and `UnionError`, the first one's."""
    lists = api.listed_unions()
    if not lists:
        return []
    return [
        *((f"union '{u.name}'", name) for u in lists for name in (naming.union_sequence(u.name), _union_align(u))),
        (f"union '{lists[0].name}'", naming.UNION_ERROR),
    ]


def _union_align(union: Union) -> str:
    return naming.unprefixed_const_name(naming.union_align(union.name))


def _rendered(api: Api) -> list[tuple[Function, list[Param]]]:
    """Each function the module renders with the parameters its signature takes, every one but a
    non-buffer `out`: a class's ctor and methods, the method's receiver aside, and every free
    function."""
    rendered = [(fn, params) for shape in api.classes() for fn, params, _ in shape.class_params()]
    rendered += [(fn, fn.params) for fn in api.free_functions()]
    return [(fn, [p for p in params if p.is_buffer or p.ref != "out"]) for fn, params in rendered]


def _arg_name(p: Param) -> str:
    """The argument a parameter is: an `out` buffer's count, which the caller gives in the
    buffer's place, else the parameter itself."""
    return p.count_name() if p.is_buffer and p.ref == "out" else p.name


# ---- the module's text ---------------------------------------------------------------------


def _module_doc(api: Api) -> str:
    """The module's doc comment, which states where it departs from the Python module."""
    lib = api.library.name
    file = naming.library_file_name(lib, platform="wasi", link=naming.SHARED)
    load = naming.NODE_LOAD
    return _jsdoc(
        [
            f"The Node binding of the library {lib}: `{load}(wasi, path)` instantiates its WASI module, `{file}` "
            f"beside this file or at the absolute `path` given, with the imports of `wasi`, a `node:wasi` WASI of "
            f"version preview1 not yet started, one per `{load}` since `wasi.initialize` refuses a second start, "
            f"and calls `wasi.initialize` once; every class and function of the library is a member of what it "
            f"returns. It departs from the Python module where Node does:",
            "- No finalizer: an object never released keeps its handle until its instance is gone; release it "
            "with `release()`, or `using`, which calls `[Symbol.dispose]`.",
            "- No thread check: an instance belongs to the one JavaScript agent that loaded it, which runs one "
            "call at a time, so a call during another call of an object comes only from its callbacks.",
            "- The dead instance: an exception leaving a call into the module that the binding did not raise "
            "itself, a trap, a panic or a RangeError from the JavaScript stack, leaves the instance dead. A call "
            "in progress when its instance dies throws the dead-instance error once control returns to it, "
            "whatever its callback answered; every later call of any of its objects throws an Error naming that "
            "first exception, reaching no export.",
            "- The preopens: the module reaches files only through the preopens of the WASI object it is given, "
            "and every path the library takes is a guest path; preopen the host's root at the guest's root, "
            '`preopens: { "/": "/" }`, for a guest path to be the host path.',
        ],
        indent="",
    )


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The ES module, which Node runs as written."""
    out = [
        f"// {emitter.banner(source_name)}\n",
        _module_doc(api),
        'import { readFileSync as _readFileSync } from "node:fs";\n',
        'import { dirname as _dirname, isAbsolute as _isAbsolute, join as _join } from "node:path";\n',
        'import { fileURLToPath as _fileURLToPath } from "node:url";\n',
        'import { isMainThread as _isMainThread, resourceLimits as _resourceLimits } from "node:worker_threads";\n',
    ]
    for doc, literals in _constant_sections(api):
        out.append("\n" + (f"// {doc}\n" if doc else ""))
        out += [f"export const {n} = {v};\n" for n, v in literals]
    out += [_bit_to_string(g) for g in api.bit_const_groups if g.to_string is not None]
    out += [
        _lookup(naming.flat_to_string(g.to_string, typename=None), named_values(g), naming.unknown_value_name(None))
        for g in api.const_groups
        if g.to_string is not None
    ]
    out += [_enum(t, heading=h) for h, t in headed(api.typed_const_groups)]
    out += [
        _lookup(naming.flat_to_string(t.to_string, typename=t.name), t.entries, naming.unknown_value_name(t.name))
        for t in api.typed_consts
        if t.to_string is not None
    ]
    out.append(_RUNTIME_TEXT)
    if api.callbacks or api.uses_text():
        out.append(_VIEW_TEXT)
    out += [_handle_class(api, o.name, heading=h) for h, o in headed(api.opaque_ref_groups)]
    text_doc = "A run of bytes in an arena, as its offset and its length."
    shown = [_structure(api, naming.TEXT, text_doc, None)] if api.uses_text() else []
    shown += [_structure(api, s.name, s.docstring, h) for h, s in headed(api.struct_groups)]
    lists = api.listed_unions()
    rest = [_SEQUENCE_TEXT] if lists else []
    rest += [_sequence(api, u, heading=h) for h, u in headed(api.union_groups, lists)]
    if api.callbacks:
        rest.append(_CALLBACK_TEXT)
    rest += [_trampoline(api, cb) for cb in api.callbacks]
    rest.append(_load(api))
    # a structure's reader, writer and taker are emitted where the rest of the module calls them
    called = _called(
        {name: helper for _, helpers in shown for name, helper in helpers.items()},
        "".join(rest) + (_RESOLVE_TEXT if api.uses_text() else ""),
    )
    rendered = [cls + "".join(h for name, h in helpers.items() if name in called) for cls, helpers in shown]
    if api.uses_text():
        rendered.insert(1, _RESOLVE_TEXT)
    return "".join([*out, *rendered, *rest])


def _jsdoc(lines: list[str], *, indent: str) -> str:
    if not lines:
        return ""
    if len(lines) == 1:
        return f"{indent}/** {lines[0]} */\n"
    return f"{indent}/**\n" + "".join(f"{indent} * {line}\n" for line in lines) + f"{indent} */\n"


def _constant_sections(api: Api) -> list[tuple[str | None, list[tuple[str, str]]]]:
    """Every constant's (name, literal) in the C header's order, each group's under its
    docstring, as the Python module renders them."""
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


def _lookup(name: str, entries: tuple[EnumEntry, ...], unknown: str) -> str:
    """A value-to-name conversion, one case per value of `entries`."""
    cases = "".join(
        f'{_I * 2}case {c.int_literal(e.value, e.format)}:\n{_I * 3}return "{naming.unprefixed_const_name(e.name)}";\n'
        for e in entries
    )
    return (
        f"\nexport function {name}(value) {{\n{_I}switch (value) {{\n{cases}"
        f'{_I * 2}default:\n{_I * 3}return "{unknown}";\n{_I}}}\n}}\n'
    )


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term of their 32-bit pattern."""
    flags = "".join(
        f'{_I}if (bits & {k}) {{\n{_I * 2}names.push("{k}");\n{_I * 2}bits &= ~{k};\n{_I}}}\n'
        for k in (naming.unprefixed_const_name(e.name) for e in single_bit_entries(group))
    )
    return (
        f"\nexport function {naming.flat_to_string(group.to_string, typename=None)}(value) {{\n"
        f'{_I}if (value === 0) {{\n{_I * 2}return "{naming.NO_FLAGS}";\n{_I}}}\n'
        f"{_I}const names = [];\n{_I}let bits = value | 0;\n{flags}"
        f"{_I}if (bits) {{\n{_I * 2}names.push(`0x${{(bits >>> 0).toString(16)}}`);\n{_I}}}\n"
        f'{_I}return names.join("|");\n}}\n'
    )


def _enum(typed: TypedConst, *, heading: str | None) -> str:
    entries = "".join(
        f"{_I}{naming.unprefixed_const_name(e.name)}: {c.int_literal(e.value, e.format)},\n" for e in typed.entries
    )
    return (
        "\n"
        + (f"// {heading}\n" if heading else "")
        + _jsdoc([typed.docstring] if typed.docstring else [], indent="")
        + f"export const {naming.upper_camel(typed.name)} = Object.freeze({{\n{entries}}});\n"
    )


_RUNTIME_TEXT = f"""
const _ISSUED = Symbol("issued by this module");

function _alive(state) {{
  if (state.dead !== null) {{
    throw new Error(`the instance is dead: a call into it threw ${{String(state.dead.error)}}`, {{ cause: state.dead.error }});
  }}
}}

function _invoke(state, name, args) {{
  _alive(state);
  let result;
  try {{
    result = state.exports[name](...args);
  }} catch (error) {{
    state.dead ??= {{ error }};
    throw error;
  }}
  _alive(state);
  return result;
}}

function _memory(state) {{
  return new DataView(state.memory.buffer);
}}

class _Blocks {{
  constructor(state) {{
    this.state = state;
    this.held = [];
  }}

  take(size, align) {{
    const at = _invoke(this.state, this.state.alloc, [size, align]) >>> 0;
    if (at === 0) {{
      throw new RangeError(`no block of ${{size}} bytes in the instance's memory`);
    }}
    this.held.push([at, size, align]);
    return at;
  }}

  release() {{
    if (this.state.dead !== null) {{
      return;
    }}
    for (const [at, size, align] of this.held.splice(0)) {{
      _invoke(this.state, this.state.free, [at, size, align]);
    }}
  }}
}}

function _integer(value, low, high, what) {{
  if (typeof value !== "number" || !Number.isInteger(value)) {{
    throw new TypeError(what);
  }}
  if (value < low || value > high) {{
    throw new RangeError(what);
  }}
  return value;
}}

function _float(value, what) {{
  if (typeof value !== "number") {{
    throw new TypeError(what);
  }}
  return value;
}}

function _member(values, value, what) {{
  if (typeof value !== "number" || !Number.isInteger(value)) {{
    throw new TypeError(what);
  }}
  if (!Object.values(values).includes(value)) {{
    throw new RangeError(what);
  }}
  return value;
}}

function _named(values, value, what) {{
  if (!Object.values(values).includes(value)) {{
    throw new Error(`${{what}} (${{value}})`);
  }}
  return value;
}}

function _object(value, what) {{
  if (typeof value !== "object" || value === null) {{
    throw new TypeError(what);
  }}
  return value;
}}

function _iterable(value, what) {{
  if (value === null || value === undefined || typeof value[Symbol.iterator] !== "function") {{
    throw new TypeError(what);
  }}
  return value;
}}

function _bytes(value, what) {{
  if (value instanceof ArrayBuffer) {{
    return new Uint8Array(value.slice(0));
  }}
  if (ArrayBuffer.isView(value)) {{
    const {{ buffer, byteOffset, byteLength }} = value;
    return new Uint8Array(buffer, byteOffset, byteLength).slice();
  }}
  throw new TypeError(what);
}}

function _copy_in(state, at, bytes) {{
  new Uint8Array(state.memory.buffer, at, bytes.length).set(bytes);
}}

function _copy_out(state, at, length) {{
  return new Uint8Array(state.memory.buffer, at, length).slice();
}}

/** A call's result other than the zero entry: `result` is it, a value of the return enum. */
export class {_ERROR} extends Error {{
  constructor(result, values) {{
    super(Object.keys(values).find((key) => values[key] === result));
    this.name = "{_ERROR}";
    this.result = result;
  }}
}}

class _Handle {{
  constructor(issued, state, value) {{
    if (issued !== _ISSUED) {{
      throw new TypeError(`a ${{new.target.name}} is issued by the module, never made`);
    }}
    this._state = state;
    this._value = value;
    Object.seal(this);
  }}

  /** The handle's value, null once the object holding it is released. */
  get value() {{
    return this._value;
  }}
}}
"""


def _handle_class(api: Api, opaque: str, *, heading: str | None) -> str:
    """The class of an opaque ref's raw handle, which only the module makes: one an argument
    takes is one this instance issued for that opaque, never a number or another's handle."""
    c_type = naming.type_name(api.namespace, opaque)
    return (
        "\n"
        + (f"// {heading}\n" if heading else "")
        + f"/** A raw {c_type} handle an instance issued; one is never made from a value. */\n"
        + f"export class {naming.handle_type(opaque)} extends _Handle {{}}\n"
    )


# ---- values in linear memory ----------------------------------------------------------------


def _scalar(api: Api, type_name: str) -> str | None:
    """The builtin scalar a value of `type_name` is in memory: a builtin's own, an enum's or a
    boxed scalar's base type; None for a struct or the text type."""
    kind = api.kind(type_name)
    if kind == "builtin":
        return type_name
    if kind == "enum":
        return next(t.base_type for t in api.typed_consts if t.name == type_name)
    if kind == "boxed":
        return next(b.base_type for b in api.boxed_scalars if b.name == type_name)
    return None


def _size(api: Api, type_name: str) -> tuple[int, int]:
    """(size, alignment) of a value of `type_name` in wasm32's linear memory."""
    return _POINTER if api.kind(type_name) == "opaque" else api.layout(type_name)


def _read(api: Api, type_name: str, view: str, at: str) -> str:
    """An expression reading the value of `type_name` at byte `at` through the `DataView` `view`,
    a u32 as unsigned and an opaque ref as its handle's number."""
    scalar = "u32" if api.kind(type_name) == "opaque" else _scalar(api, type_name)
    if scalar is None:
        return f"_read_{type_name}({view}, {at})"
    little = "" if scalar in ("i8", "u8") else ", true"
    return f"{view}.get{_SCALARS[scalar]}({at}{little})"


def _write(api: Api, type_name: str, view: str, at: str, value: str) -> str:
    """A statement writing `value` of `type_name` at byte `at` through the `DataView` `view`."""
    scalar = "u32" if api.kind(type_name) == "opaque" else _scalar(api, type_name)
    if scalar is None:
        return f"_write_{type_name}({view}, {at}, {value});"
    little = "" if scalar in ("i8", "u8") else ", true"
    return f"{view}.set{_SCALARS[scalar]}({at}, {value}{little});"


def _take(api: Api, type_name: str, value: str, subject: str) -> str:
    """An expression refusing `value` unless it is what a value of `type_name` takes, else its
    copy: an integer within its type, a number, a value of its enum, a boxed scalar's base value,
    a structure's fields each so; `subject`, a template literal's text, names it in the
    refusal."""
    kind = api.kind(type_name)
    if kind in ("struct", "text"):
        return f"_take_{type_name}({value}, `{subject}`)"
    if kind == "enum":
        enum = naming.upper_camel(type_name)
        return f"_member({enum}, {value}, `{subject} must be a {enum}`)"
    scalar = _scalar(api, type_name)
    if scalar in ("f32", "f64"):
        return f"_float({value}, `{subject} must be a number`)"
    low, high = naming.integer_range(scalar)
    return f"_integer({value}, {low}, {high}, `{subject} must be an integer {naming.BUILTIN_C_TYPES[scalar]} holds`)"


def _from_wasm(api: Api, type_name: str, value: str) -> str:
    """`value`, a wasm `i32` holding a value of `type_name`, as that value: a u32 made unsigned."""
    return f"{value} >>> 0" if (_scalar(api, type_name) or "u32") == "u32" else value


def _structure(api: Api, type_name: str, doc: str | None, heading: str | None) -> tuple[str, dict[str, str]]:
    """A structure's class, each field from the given fields where they hold it, else zero; and
    its private reader, writer and taker at the offsets of the layout model, by name."""
    cls = naming.upper_camel(type_name)
    fields = api.field_offsets(type_name)

    def zero(t: str) -> str:
        return f"new {naming.upper_camel(t)}()" if api.kind(t) in ("struct", "text") else "0"

    inits = "".join(f"{_I * 2}this.{n} = fields.{n} ?? {zero(t)};\n" for n, t, _ in fields)
    reads = "".join(f"{_I * 2}{n}: {_read(api, t, 'view', f'at + {o}')},\n" for n, t, o in fields)
    writes = "".join(f"{_I}{_write(api, t, 'view', f'at + {o}', f'value.{n}')}\n" for n, t, o in fields)
    takes = "".join(f"{_I * 2}{n}: {_take(api, t, f'value.{n}', '${what}.' + n)},\n" for n, t, _ in fields)
    return (
        "\n"
        + (f"// {heading}\n" if heading else "")
        + _jsdoc([doc] if doc else [], indent="")
        + f"export class {cls} {{\n"
        + f"{_I}constructor(fields = {{}}) {{\n{inits}{_I}}}\n}}\n"
    ), {
        f"_read_{type_name}": f"\nfunction _read_{type_name}(view, at) {{\n{_I}return new {cls}({{\n{reads}{_I}}});\n}}\n",
        f"_write_{type_name}": f"\nfunction _write_{type_name}(view, at, value) {{\n{writes}}}\n",
        f"_take_{type_name}": (
            f"\nfunction _take_{type_name}(value, what) {{\n"
            + f"{_I}_object(value, `${{what}} must be a {cls}`);\n"
            + f"{_I}return new {cls}({{\n{takes}{_I}}});\n}}\n"
        ),
    }


def _called(helpers: dict[str, str], text: str) -> set[str]:
    """The names of `helpers` that `text` calls, and those they call in turn."""
    called: set[str] = set()
    pending = [text]
    while pending:
        for name in re.findall(r"\b_(?:read|write|take)_\w+", pending.pop()):
            if name in helpers and name not in called:
                called.add(name)
                pending.append(helpers[name])
    return called


_RESOLVE_TEXT = f"""
/**
 * The bytes of `arena` the run `text` covers, a copy of the run alone, null where the run leaves
 * the arena: `arena` bytes, or a byte view while its callback runs.
 */
export function {naming.RESOLVE}(text, arena) {{
  const run = _take_text(text, "{naming.RESOLVE}: text");
  const end = run.{naming.TEXT_OFFSET} + run.{naming.TEXT_LENGTH};
  if (arena instanceof _ByteView) {{
    return end > arena.length ? null : _copy_out(arena._state, arena._address + run.{naming.TEXT_OFFSET}, run.{naming.TEXT_LENGTH});
  }}
  const bytes = _bytes(arena, "{naming.RESOLVE}: arena must be bytes or a byte view");
  return end > bytes.length ? null : bytes.slice(run.{naming.TEXT_OFFSET}, end);
}}
"""

_VIEW_TEXT = """
const _DEAD_VIEW = "a view is valid only until its callback returns";

class _View {
  constructor(state, address, count, size, read, what) {
    if (address === 0 && count !== 0) {
      throw new Error(`${what} outside the definition`);
    }
    this._state = state;
    this._address = address;
    this._count = count;
    this._size = size;
    this._read = read;
    this._live = true;
  }

  _check() {
    if (!this._live) {
      throw new Error(_DEAD_VIEW);
    }
  }

  get length() {
    this._check();
    return this._count;
  }

  at(index) {
    this._check();
    if (!Number.isInteger(index)) {
      throw new TypeError("a view's index is an integer");
    }
    const at = index < 0 ? index + this._count : index;
    if (at < 0 || at >= this._count) {
      throw new RangeError("view index out of range");
    }
    return this._read(_memory(this._state), this._address + at * this._size);
  }

  slice(start = 0, end = this._count) {
    this._check();
    const bound = (index) => (index < 0 ? Math.max(this._count + index, 0) : Math.min(index, this._count));
    const items = [];
    for (let index = bound(start); index < bound(end); index++) {
      items.push(this.at(index));
    }
    return items;
  }

  *[Symbol.iterator]() {
    for (let index = 0; index < this.length; index++) {
      yield this.at(index);
    }
  }
}

class _ByteView extends _View {
  slice(start, end) {
    return Uint8Array.from(super.slice(start, end));
  }
}
"""

_SEQUENCE_TEXT = f"""
/**
 * A sequence refused at a record: `index` and `offset` are the record's, `clause` the text of
 * why, one of the six a walk refuses with.
 */
export class {naming.UNION_ERROR} extends Error {{
  constructor(what, index, offset, clause) {{
    super(`${{what}} refused at record ${{index}}, offset ${{offset}}: ${{clause}}`);
    this.name = "{naming.UNION_ERROR}";
    this.index = index;
    this.offset = offset;
    this.clause = clause;
  }}
}}

class _Sequence {{
  constructor(state, address, count, extent, what) {{
    if (address === 0 && (count !== 0 || extent !== 0)) {{
      throw new Error(`${{what}} outside the definition`);
    }}
    this._state = state;
    this._address = address;
    this._count = count;
    this._extent = extent;
    this._what = what;
    this._live = true;
  }}

  _check() {{
    if (!this._live) {{
      throw new Error("a view is valid only until its callback returns");
    }}
  }}

  get length() {{
    this._check();
    return this._count;
  }}

  get bytes() {{
    this._check();
    return this._extent;
  }}

  _member(index, at) {{
    const shape = this.constructor;
    let clause;
    if (at === this._extent) {{
      clause = "{_CLAUSE_TEXTS['count_not_met']}";
    }} else if (this._extent - at < shape._PREFIX_SIZE) {{
      clause = "{_CLAUSE_TEXTS['header_past_extent']}";
    }} else {{
      const view = _memory(this._state);
      const member = shape._MEMBERS.get(shape._tag(view, this._address + at));
      if (member === undefined) {{
        clause = "{_CLAUSE_TEXTS['unknown_tag']}";
      }} else if (shape._length(view, this._address + at) !== member[1]) {{
        clause = "{_CLAUSE_TEXTS['size_not_the_members']}";
      }} else if (this._extent - at < member[1]) {{
        clause = "{_CLAUSE_TEXTS['record_past_extent']}";
      }} else {{
        return member;
      }}
    }}
    throw new {naming.UNION_ERROR}(this._what, index, at, clause);
  }}

  *[Symbol.iterator]() {{
    let at = 0;
    for (let index = 0; index < this._count; index++) {{
      this._check();
      const [read, size] = this._member(index, at);
      yield read(_memory(this._state), this._address + at);
      at += size;
    }}
    this._check();
    if (at !== this._extent) {{
      throw new {naming.UNION_ERROR}(this._what, this._count, at, "{_CLAUSE_TEXTS['count_not_met']}");
    }}
  }}

  /**
   * The record `index` units of the list's alignment from the sequence's start, a copy; a
   * {naming.UNION_ERROR} where the walk from the start refuses a record before it, the count's
   * among them, or does not land on it.
   */
  at(index) {{
    this._check();
    if (!Number.isInteger(index)) {{
      throw new TypeError("a sequence's index is an integer");
    }}
    const offset = index * this.constructor._ALIGN;
    let walked = 0;
    let at = 0;
    for (;;) {{
      if (walked === this._count) {{
        if (at !== this._extent) {{
          throw new {naming.UNION_ERROR}(this._what, walked, at, "{_CLAUSE_TEXTS['count_not_met']}");
        }}
        break;
      }}
      const [read, size] = this._member(walked, at);
      if (at >= offset) {{
        if (at === offset) {{
          return read(_memory(this._state), this._address + at);
        }}
        break;
      }}
      walked += 1;
      at += size;
    }}
    throw new {naming.UNION_ERROR}(this._what, walked, offset, "{_CLAUSE_TEXTS['not_a_record_start']}");
  }}

  _c_arguments(state, what) {{
    this._check();
    if (this._state !== state) {{
      throw new TypeError(`${{what}} must be a sequence this instance passed`);
    }}
    return [this._address, this._count, this._extent];
  }}
}}
"""


def _sequence(api: Api, union: Union, *, heading: str | None) -> str:
    """The module constant of `union`'s list alignment, then its sequence class: the prefix's
    size, the list's alignment, the readers of the prefix's tag and length, and each member's
    reader and size by its tag's constant, every offset and size the layout model's."""
    offsets = {n: (t, o) for n, t, o in api.field_offsets(union.prefix)}
    tag_type, tag_at = offsets[union.tag_field]
    length_type, length_at = offsets[union.length_field]
    members = ", ".join(
        f"[{naming.unprefixed_const_name(m.tag)}, [_read_{m.struct}, {api.layout(m.struct)[0]}]]" for m in union.members
    )
    align, seq = _union_align(union), naming.union_sequence(union.name)
    return (
        f"\n// the list's alignment, the unit of {seq}.at's index\nexport const {align} = {api.list_alignment(union)};\n\n"
        + (f"// {heading}\n" if heading else "")
        + _jsdoc([union.docstring] if union.docstring else [], indent="")
        + f"export class {seq} extends _Sequence {{\n"
        + f"{_I}static _PREFIX_SIZE = {api.layout(union.prefix)[0]};\n"
        + f"{_I}static _ALIGN = {align};\n"
        + f"{_I}static _MEMBERS = new Map([{members}]);\n\n"
        + f"{_I}static _tag(view, at) {{\n{_I * 2}return {_read(api, tag_type, 'view', f'at + {tag_at}')};\n{_I}}}\n\n"
        + f"{_I}static _length(view, at) {{\n{_I * 2}return {_read(api, length_type, 'view', f'at + {length_at}')};\n{_I}}}\n"
        + "}\n"
    )


_CALLBACK_TEXT = """
function _record(failure, error) {
  if (!failure.failed) {
    failure.failed = true;
    failure.error = error;
  }
}

function _frame(state, frame) {
  let id = state.next;
  while (id === 0 || state.frames.has(id)) {
    id = (id + 1) >>> 0;
  }
  state.next = (id + 1) >>> 0;
  state.frames.set(id, frame);
  return id;
}
"""


def _view_reader(api: Api, p: Param) -> tuple[str, int]:
    """The reader of one element of view `p` and the element's size."""
    if p.type == "memory":
        return "(view, at) => view.getUint8(at)", 1
    if _scalar(api, p.type) is not None:
        return f"(view, at) => {_read(api, p.type, 'view', 'at')}", api.layout(p.type)[0]
    return f"_read_{p.type}", api.layout(p.type)[0]


def _trampoline(api: Api, callback: Function) -> str:
    """`_<c>_trampoline`, the import the library calls as `callback`: its `user_data` names the
    frame its driving call made, else it answers stop at once. Every statement is under one
    `try` catching any exception as the call's failure, so nothing thrown leaves it: where the
    call's failure is recorded, or where an invocation of the frame runs, it answers stop without
    calling the function, recording the latter as a failure; otherwise it builds each view and
    enum and calls the function, and maps its answer, undefined the zero entry and an integer the
    return enum's base type holds itself, anything else a failure. Each view is refused once the
    function returns. A dead instance, found on entry or, in the `finally`, after the function
    returns or throws, throws the dead-instance error into the module in place of any answer, so
    no code of a dead instance runs again."""
    c_type = naming.type_name(api.namespace, callback.name)
    returns = next(t for t in api.typed_consts if t.name == callback.returns)
    low, high = naming.integer_range(returns.base_type)
    base = naming.BASE_C_TYPES[returns.base_type].c_type
    stop = c.int_literal(api.stop_entry(callback).value, "dec")
    go = c.int_literal(api.success_entry(callback).value, "dec")
    reads, args, i = [], [], 0
    for p in callback.params:
        what = f'"{c_type} received view {p.name}"'
        if p.is_union:
            reads.append(
                f"views.push(new {naming.union_sequence(p.type)}(state, a{i} >>> 0, a{i + 1} >>> 0, a{i + 2} >>> 0, {what}));"
            )
            args.append(f"views[{len(reads) - 1}]")
        elif p.is_buffer:
            reader, size = _view_reader(api, p)
            view = "_ByteView" if p.type == "memory" else "_View"
            reads.append(f"views.push(new {view}(state, a{i} >>> 0, a{i + 1} >>> 0, {size}, {reader}, {what}));")
            args.append(f"views[{len(reads) - 1}]")
        elif api.kind(p.type) == "enum":
            enum, enum_c = naming.upper_camel(p.type), naming.type_name(api.namespace, p.type)
            args.append(
                f'_named({enum}, {_from_wasm(api, p.type, f"a{i}")}, "{c_type} received a {p.name} value {enum_c} does not name")'
            )
        else:
            args.append(_from_wasm(api, p.type, f"a{i}"))
        i += 1 + len(p.derived_names())
    names = [f"a{k}" for k in range(i)]
    body = [
        "_alive(state);",
        "let frame;",
        "let entered = false;",
        "const views = [];",
        "try {",
        f"  frame = state.frames.get(a{i} >>> 0);",
        f'  if (frame === undefined || frame.type !== "{callback.name}") {{',
        f"    return {stop};",
        "  }",
        "  if (frame.failure.failed) {",
        f"    return {stop};",
        "  }",
        "  if (frame.running) {",
        f"    _record(frame.failure, new Error(`{c_type} called again while a call of it was running in ${{frame.driving}}`));",
        f"    return {stop};",
        "  }",
        "  frame.running = entered = true;",
        *(f"  {r}" for r in reads),
        f"  const answer = frame.fn({', '.join(args)});",
        "  if (frame.failure.failed) {",
        f"    return {stop};",
        "  }",
        "  if (answer === undefined) {",
        f"    return {go};",
        "  }",
        f'  if (typeof answer === "number" && Number.isInteger(answer) && answer >= {low} && answer <= {high}) {{',
        "    return answer;",
        "  }",
        "  _record(",
        "    frame.failure,",
        f"    new TypeError(`{c_type}: the function answered ${{String(answer)}}, not undefined or an integer {base} holds`),",
        "  );",
        f"  return {stop};",
        "} catch (error) {",
        "  if (frame !== undefined) {",
        "    _record(frame.failure, error);",
        "  }",
        f"  return {stop};",
        "} finally {",
        "  if (entered) {",
        "    frame.running = false;",
        "  }",
        "  for (const view of views) {",
        "    view._live = false;",
        "  }",
        "  _alive(state);",
        "}",
    ]
    return (
        f"\n/** The import the library calls as {c_type}, by the frame its `user_data` names. */\n"
        f"function _{naming.trampoline(callback.name)}(state, {', '.join([*names, f'a{i}'])}) {{\n"
        + "".join(f"{_I}{line}\n" for line in body)
        + "}\n"
    )


# ---- the calls ------------------------------------------------------------------------------


@dataclass
class _Marshalled:
    """A function's parameters as the module renders them around one C call."""

    params: list[str] = field(default_factory=list)  # the signature's arguments
    checks: list[str] = field(default_factory=list)  # refusals and copies of the arguments, before any allocation
    state: list[str] = field(default_factory=list)  # refusals of an object or handle's state, first in the call's try
    allocs: list[str] = field(default_factory=list)  # the blocks the call takes
    writes: list[str] = field(default_factory=list)  # the `in` values written into them through `_view`
    frames: list[tuple[str, str, str, str]] = field(
        default_factory=list
    )  # (local, argument, callback type, C function)
    args: list[str] = field(default_factory=list)  # the C call's arguments, in order
    locals: list[str] = field(default_factory=list)  # what the reads assign, declared before the try
    reads: list[str] = field(default_factory=list)  # the values the call wrote, read through `_view`
    after: list[str] = field(default_factory=list)  # statements after a successful result
    outs: list[str] = field(default_factory=list)  # each value returned, in order


def _optional(p: Param, value: str, made: str) -> str:
    """`made`, or null where `p` is `_optional` and `value` is absent."""
    return f"{value} == null ? null : {made}" if p.optional else made


def _marshal(api: Api, fn: Function, params: tuple[Param, ...], *, ctx: str) -> _Marshalled:
    """`params` of `fn` as arguments and results around the C call, `ctx` naming the function in
    a refusal of the caller's misuse: each argument refused unless it has the parameter's type
    and fits it, and copied, before anything is allocated; an object or handle argument's state
    refused last, in the call's try."""
    m = _Marshalled()
    fname = naming.function_name(api.namespace, fn.name)
    shapes = {shape.opaque.name: shape for shape in api.classes()}
    for p in params:
        kind = api.kind(p.type)
        local, pointer, value = f"_l_{p.name}", f"_p_{p.name}", f"_v_{p.name}"
        if p.callback:
            m.params.append(p.name)
            m.checks.append(
                f'if (typeof {p.name} !== "function") {{\n{_I}throw new TypeError("{ctx}: {p.name} must be a function");\n}}'
            )
            m.frames.append((f"_i_{p.name}", p.name, p.type, fname))
            m.args += [f"_addresses.{p.type}", f"_i_{p.name}"]
        elif p.is_buffer:
            _marshal_buffer(api, fn, p, ctx=ctx, into=m)
        elif p.ref == "out":
            size, align = _size(api, p.type)
            m.allocs.append(f"const {pointer} = _blocks.take({size}, {align});")
            m.args.append(pointer)
            m.locals.append(value)
            m.reads.append(f"{value} = {_read(api, p.type, '_view', pointer)};")
            m.outs.append(_out_value(api, fn, p, value))
        elif kind == "opaque":
            _marshal_handle(api, fn, p, shapes.get(p.type), ctx=ctx, into=m)
        else:
            m.params.append(p.name)
            m.checks.append(f"const {local} = {_optional(p, p.name, _take(api, p.type, p.name, f'{ctx}: {p.name}'))};")
            if p.ref is None:
                _by_value(api, p, local, into=m)
                continue
            size, align = _size(api, p.type)
            m.allocs.append(f"const {pointer} = {local} === null ? 0 : _blocks.take({size}, {align});")
            m.writes.append(f"if ({local} !== null) {{\n{_I}{_write(api, p.type, '_view', pointer, local)}\n}}")
            m.args.append(pointer)
            if p.ref == "inout":
                m.locals.append(value)
                m.reads.append(f"{value} = {local} === null ? null : {_read(api, p.type, '_view', pointer)};")
                read = _out_value(api, fn, p, value)
                m.outs.append(f"{value} === null ? null : {read}" if p.optional else read)
    return m


def _by_value(api: Api, p: Param, local: str, *, into: _Marshalled) -> None:
    """A value passed by value: a scalar itself; a struct as wasm32's C calling convention passes
    it, its one scalar where it holds exactly one, else a pointer to a copy."""
    if _scalar(api, p.type) is not None:
        into.args.append(local)
        return
    paths = _scalar_paths(api, p.type)
    if len(paths) == 1:
        into.args.append(f"{local}.{paths[0]}")
        return
    pointer = f"_p_{p.name}"
    size, align = api.layout(p.type)
    into.allocs.append(f"const {pointer} = _blocks.take({size}, {align});")
    into.writes.append(_write(api, p.type, "_view", pointer, local))
    into.args.append(pointer)


def _scalar_paths(api: Api, type_name: str) -> list[str]:
    """The property path of each scalar a struct or the text type holds, nested ones included."""
    paths = []
    for n, t, _ in api.field_offsets(type_name):
        paths += [f"{n}.{sub}" for sub in _scalar_paths(api, t)] if _scalar(api, t) is None else [n]
    return paths


def _out_value(api: Api, fn: Function, p: Param, value: str) -> str:
    """What the caller receives of `value`, read from what the call wrote: a value of its enum,
    checked; a raw handle, null for the null handle; anything else itself."""
    kind = api.kind(p.type)
    if kind == "enum":
        fname, enum_c = naming.function_name(api.namespace, fn.name), naming.type_name(api.namespace, p.type)
        return f'_named({naming.upper_camel(p.type)}, {value}, "{fname} wrote a {p.name} value {enum_c} does not name")'
    if kind == "opaque":
        return f"{value} === 0 ? null : new {naming.handle_type(p.type)}(_ISSUED, {_STATE}, {value})"
    return value


def _busy(api: Api, fn: Function, *, message: str) -> str:
    """The error refusing a call of `fn` while another call holds an object: `ResultError` of the
    first non-zero entry of its return enum, or where that enum has none `Error` of `message`, a
    template literal's text."""
    entry = api.first_nonzero_entry(fn)
    enum = naming.upper_camel(fn.returns)
    if entry is not None:
        return f"new {_ERROR}({enum}.{naming.unprefixed_const_name(entry.name)}, {enum})"
    return f"new Error(`{message}`)"


def _locked(shape: ClassShape) -> bool:
    """Whether the class wraps its handle's lifetime: it has a dtor and its opaque's
    `_hides_pointer` says the library does not validate the handle."""
    return shape.dtor is not None and shape.opaque.hides_pointer


def _marshal_handle(api: Api, fn: Function, p: Param, shape: ClassShape | None, *, ctx: str, into: _Marshalled) -> None:
    """An opaque ref the caller passes: where its opaque has a class, by value or `in`, an object
    of this instance's class, held for the call where the class is locked, refused where another
    call holds it or where released, as the receiver is; otherwise refused while a call of it
    drives a callback, its handle passed whatever the library makes of it; with no class, a raw
    handle this instance issued for it, refused where null. An `inout` raw handle is returned as
    the caller's, holding what the library wrote."""
    into.params.append(p.name)
    fname = naming.function_name(api.namespace, fn.name)
    pointer = f"_p_{p.name}"
    if shape is not None and p.ref in (None, "in"):
        cls = naming.upper_camel(shape.opaque.class_name)
        check = f'if (!({p.name} instanceof {cls})) {{\n{_I}throw new TypeError("{ctx}: {p.name} must be a {cls}");\n}}'
        refused = _busy(api, fn, message=f"{ctx}: {p.name} is a {cls} while ${{{p.name}.{_HELD}}} is in progress on it")
        state = []
        if _locked(shape) or shape.drives():
            state.append(f"if ({p.name}.{_HELD} !== null) {{\n{_I}throw {refused};\n}}")
        if _locked(shape):
            state += [
                f'{p.name}.{_HELD} = "{fname}";',
                f"_held.push({p.name});",
                f"if ({p.name}.{_HANDLE} === null) {{\n"
                f'{_I}throw new Error("{ctx}: {p.name} is a {cls} used after {shape.dtor.name}");\n}}',
            ]
        handle = f"({p.name}.{_HANDLE}._value ?? 0)"
    else:
        cls = naming.handle_type(p.type)
        check = (
            f"if (!({p.name} instanceof {cls}) || {p.name}._state !== {_STATE}) {{\n"
            f'{_I}throw new TypeError("{ctx}: {p.name} must be a {cls} this instance issued");\n}}'
        )
        state = [f'if ({p.name}._value === null) {{\n{_I}throw new Error("{ctx}: {p.name} is a null {cls}");\n}}']
        handle = f"{p.name}._value"
    into.checks.append(f"if ({p.name} != null) {{\n{_indented(check)}\n}}" if p.optional else check)
    if state:
        joined = "\n".join(state)
        into.state.append(f"if ({p.name} != null) {{\n{_indented(joined)}\n}}" if p.optional else joined)
    value = f"({p.name} == null ? 0 : {handle})" if p.optional else handle
    if p.ref is None:
        into.args.append(value)
        return
    into.allocs.append(f"const {pointer} = {p.name} == null ? 0 : _blocks.take({_POINTER[0]}, {_POINTER[1]});")
    into.writes.append(f"if ({pointer} !== 0) {{\n{_I}_view.setUint32({pointer}, {value}, true);\n}}")
    into.args.append(pointer)
    if p.ref == "inout":
        local = f"_v_{p.name}"
        into.locals.append(local)
        into.reads.append(f"{local} = {pointer} === 0 ? 0 : _view.getUint32({pointer}, true);")
        into.after.append(f"if ({p.name} != null) {{\n{_I}{p.name}._value = {local} === 0 ? null : {local};\n}}")
        into.outs.append(p.name)


def _marshal_buffer(api: Api, fn: Function, p: Param, *, ctx: str, into: _Marshalled) -> None:
    """A buffer: `memory` `in` or `inout` bytes, copied at the check, `inout` returned as the
    bytes written; `out` its count, returning the bytes or elements written, copied; an `in`
    array any iterable, materialised, each element taken as a parameter of its type is. A count
    its type cannot hold, and an `out` buffer whose bytes would pass 2**31 - 1, are refused
    before anything is allocated. A reported buffer returns its data, what it wrote and what it
    needs, the reports checked within the count and the need first. A union's list is the sequence a
    callback of this instance received, passed while that callback runs, uncopied."""
    local, pointer, count, value = f"_l_{p.name}", f"_p_{p.name}", f"_c_{p.name}", f"_v_{p.name}"
    if p.is_union:
        cls = naming.union_sequence(p.type)
        into.params.append(p.name)
        check = f'if (!({p.name} instanceof {cls})) {{\n{_I}throw new TypeError("{ctx}: {p.name} must be a {cls}");\n}}'
        into.checks.append(f"if ({p.name} != null) {{\n{_indented(check)}\n}}" if p.optional else check)
        made = f'{p.name}._c_arguments({_STATE}, "{ctx}: {p.name}")'
        into.checks.append(
            f"const [{pointer}, {count}, _b_{p.name}] = "
            + (f"{p.name} == null ? [0, 0, 0] : {made};" if p.optional else f"{made};")
        )
        into.args += [pointer, count, f"_b_{p.name}"]
        return
    low, high = naming.integer_range(p.count_type)
    arg = _arg_name(p)
    into.params.append(arg)
    size, align = (1, 1) if p.type == "memory" else api.layout(p.type)
    extent = count if size == 1 else f"{count} * {size}"
    longer = f'if ({count} > {high}) {{\n{_I}throw new RangeError("{ctx}: {p.name} is longer than {p.count_type} can count");\n}}'
    if p.ref == "out":
        c_count = naming.BUILTIN_C_TYPES[p.count_type]
        into.checks.append(
            f'const {count} = _integer({arg}, {low}, {high}, "{ctx}: {arg} must be a whole number {c_count} holds");'
        )
        if high * size > _EXTENT_MAX:
            into.checks.append(
                f"if ({count} > {_EXTENT_MAX // size}) {{\n"
                f'{_I}throw new RangeError("{ctx}: {p.name} would pass {_EXTENT_MAX} bytes");\n}}'
            )
        into.allocs.append(f"const {pointer} = _blocks.take({extent}, {align});")
    else:
        if p.type == "memory":
            made = f'_bytes({p.name}, "{ctx}: {p.name} must be bytes")'
        else:
            element = _take(api, p.type, "_e", f"{ctx}: an element of {p.name}")
            made = f'Array.from(_iterable({p.name}, "{ctx}: {p.name} must be iterable"), (_e) => {element})'
        into.checks += [
            f"const {local} = {_optional(p, p.name, made)};",
            (
                f"const {count} = {local} === null ? 0 : {local}.length;"
                if p.optional
                else f"const {count} = {local}.length;"
            ),
            longer,
        ]
        into.allocs.append(
            f"const {pointer} = {local} === null ? 0 : _blocks.take({extent}, {align});"
            if p.optional
            else f"const {pointer} = _blocks.take({extent}, {align});"
        )
        if p.type == "memory":
            write = f"_copy_in({_STATE}, {pointer}, {local});"
        else:
            write = f"{local}.forEach((_e, _k) => {{\n{_I}{_write(api, p.type, '_view', f'{pointer} + _k * {size}', '_e')}\n}});"
        into.writes.append(f"if ({local} !== null) {{\n{_indented(write)}\n}}" if p.optional else write)
    into.args += [pointer, count]
    reports = p.report_names()
    if reports:
        wrote, needed = f"_w_{p.name}", f"_n_{p.name}"
        csize = api.layout(p.count_type)[0]
        into.allocs += [f"const {cell} = _blocks.take({csize}, {csize});" for cell in (wrote, needed)]
        into.args += [wrote, needed]
        into.locals += [f"{wrote}_value", f"{needed}_value"]
        into.reads += [f"{cell}_value = {_read(api, p.count_type, '_view', cell)};" for cell in (wrote, needed)]
        fname = naming.function_name(api.namespace, fn.name)
        into.after.append(
            f"if ({wrote}_value > {count} || {wrote}_value > {needed}_value) {{\n"
            f'{_I}throw new Error("{fname} over-reported {p.name}: it wrote more than the buffer holds or than the result needs");\n}}'
        )
    if p.ref == "in":
        return
    into.locals.append(value)
    if p.type == "memory":
        into.reads.append(f"{value} = _copy_out({_STATE}, {pointer}, {count});")
        into.outs.append(f"{value}.slice(0, {wrote}_value)" if reports else value)
    else:
        element = _read(api, p.type, "_view", f"{pointer} + _k * {size}")
        into.reads.append(f"{value} = Array.from({{ length: {count} }}, (_, _k) => {element});")
        into.outs.append(value)
    if reports:
        into.outs += [f"{wrote}_value", f"{needed}_value"]


def _indented(text: str) -> str:
    return "\n".join(f"{_I}{line}" if line else line for line in text.split("\n"))


def _body(
    api: Api,
    fn: Function,
    m: _Marshalled,
    *,
    ctx: str,
    first_args: list[str],
    receiver: list[str],
    entering: bool,
    ok: list[str],
    returns: bool,
) -> list[str]:
    """A function body's statements: the instance's liveness, the thread's stack where `fn` has
    `_stack_mb`, `ctx` naming it, the argument checks and copies,
    then in one try the receiver's and the arguments' state, the blocks, the `in` values, the
    callback frames, the call and the reads, the finally releasing every frame, block and held
    object on every path; then the recorded failure thrown, the result checked, `after`, `ok`
    and where `returns` the outs. Where `entering`, the receiver is held for the call."""
    fname = naming.function_name(api.namespace, fn.name)
    lines = [
        f"_alive({_STATE});",
        *_stack_check(fn, ctx=ctx),
        *m.checks,
        "const _held = [];",
        f"const _blocks = new _Blocks({_STATE});",
    ]
    if m.frames:
        lines.append("const _failure = { failed: false, error: undefined };")
        lines += [f"let {local} = 0;" for local, *_ in m.frames]
    lines.append(f"let {', '.join(['_raw', *m.locals])};")
    inside = [*receiver, *m.state]
    if entering:
        inside += [f'this.{_HELD} = "{fname}";', "_held.push(this);"]
    inside += m.allocs
    # a memory buffer's copy in or out reaches the memory without the view
    writes_view = any("_view" in s for s in m.writes)
    reads_view = any("_view" in s for s in m.reads)
    if writes_view:
        inside.append(f"{'let' if reads_view else 'const'} _view = _memory({_STATE});")
    inside += m.writes
    inside += [
        f'{local} = _frame({_STATE}, {{ type: "{cb}", fn: {name}, failure: _failure, running: false, driving: "{driving}" }});'
        for local, name, cb, driving in m.frames
    ]
    inside.append(f'_raw = _invoke({_STATE}, "{fname}", [{", ".join([*first_args, *m.args])}]);')
    if reads_view:
        inside.append(f"{'' if writes_view else 'const '}_view = _memory({_STATE});")
    inside += m.reads
    cleanup = [f"{_STATE}.frames.delete({local});" for local, *_ in m.frames]
    cleanup += ["_blocks.release();", f"for (const _object of _held) {{\n{_I}_object.{_HELD} = null;\n}}"]
    lines += ["try {", *(_indented(s) for s in inside), "} finally {", *(_indented(s) for s in cleanup), "}"]
    if m.frames:
        lines.append(f"if (_failure.failed) {{\n{_I}throw _failure.error;\n}}")
    lines += [*_result_check(api, fn), *m.after, *ok]
    if returns:
        if len(m.outs) == 1:
            lines.append(f"return {m.outs[0]};")
        elif m.outs:
            lines.append(f"return [{', '.join(m.outs)}];")
    return lines


def _stack_check(fn: Function, *, ctx: str) -> list[str]:
    """Where `fn` has `_stack_mb`, the refusal of a call on a worker thread whose stack is
    smaller, `ctx` naming the function; the main thread's stack Node does not expose."""
    if fn.stack_mb is None:
        return []
    need = naming.unprefixed_const_name(fn.stack_mb.name)
    return [
        f"if (!_isMainThread && _resourceLimits.stackSizeMb < {need}) {{\n"
        f"{_I}throw new RangeError(\n"
        f"{_I * 2}`{ctx} needs a stack of ${{{need}}} MiB; this worker thread's is ${{_resourceLimits.stackSizeMb}} MiB`,\n"
        f"{_I});\n}}"
    ]


def _docs(fn: Function) -> list[str]:
    """`fn`'s doc lines, with the stack its `_stack_mb` names where it has one."""
    if fn.stack_mb is None:
        return fn.docs()
    need = naming.unprefixed_const_name(fn.stack_mb.name)
    return [
        *fn.docs(),
        f"Needs a JavaScript stack of {need}, {fn.stack_mb.value} MiB, on the caller's thread: refused with a "
        f"RangeError on a worker thread whose resourceLimits.stackSizeMb is smaller; unchecked on the main "
        f"thread, whose stack Node does not expose.",
    ]


def _result_check(api: Api, fn: Function) -> list[str]:
    """`_raw`, the call's result, as `_result`, a value of the return enum, thrown as
    `ResultError` unless it is the zero entry."""
    fname = naming.function_name(api.namespace, fn.name)
    enum = naming.upper_camel(fn.returns)
    unnamed = f"{fname} returned a value {naming.type_name(api.namespace, fn.returns)} does not name"
    success = naming.unprefixed_const_name(api.success_entry(fn).name)
    return [
        f'const _result = _named({enum}, {_from_wasm(api, fn.returns, "_raw")}, "{unnamed}");',
        f"if (_result !== {enum}.{success}) {{\n{_I}throw new {_ERROR}(_result, {enum});\n}}",
    ]


def _block(lines: list[str], indent: str) -> str:
    return "".join(f"{indent}{line}\n" if line else "\n" for text in lines for line in text.split("\n"))


def _class(api: Api, shape: ClassShape, *, heading: str | None) -> str:
    """The class, owning its handle: its constructor, throwing on failure; `handle` and a getter
    per cached `out`; a method per member function; with a dtor `release()` and
    `[Symbol.dispose]`. Locked (see `_locked`), every method and `release()` holding the object
    for the call and refusing it once released, naming the dtor; unlocked, every call after
    release passing the null handle to the library, and where the class drives a callback every
    method and `release()` refused during a driving call."""
    cls = naming.upper_camel(shape.opaque.class_name)
    headings = {fn.name: h for h, fn in headed(api.function_groups, shape.functions())}
    locked, drives, ctor, dtor = _locked(shape), shape.drives(), shape.ctor, shape.dtor
    m = _marshal(api, ctor, ctor.params, ctx=cls)
    handle = f"_v_{shape.handle.name}"
    ok = [
        f"this.{_HANDLE} = new {naming.handle_type(shape.opaque.name)}(_ISSUED, {_STATE}, {handle});",
        f"this.{_HELD} = null;",
    ]
    cached = [f"this._cached_{p.name} = {_out_value(api, ctor, p, f'_v_{p.name}')};" for p in shape.cached]
    if dtor is not None and any(api.kind(p.type) == "enum" for p in shape.cached):
        dtor_c = naming.function_name(api.namespace, dtor.name)
        # an object a check of its cached outs refuses is released, as no finalizer would
        cached = [
            "try {",
            *(_indented(s) for s in cached),
            "} catch (error) {",
            f'{_I}_invoke({_STATE}, "{dtor_c}", [{handle}]);',
            f"{_I}throw error;",
            "}",
        ]
    ok += [*cached, "Object.seal(this);"]
    body = _body(api, ctor, m, ctx=cls, first_args=[], receiver=[], entering=False, ok=ok, returns=False)
    docs = [shape.opaque.docstring] if shape.opaque.docstring else []
    if locked:
        docs.append(
            "Its calls are mutually exclusive: a call or a release during another call of the same object, "
            "from a callback, throws rather than waits."
        )
    elif dtor is not None:
        docs.append("After release its calls reach the library with the null handle.")
    out = [
        "\n" + _indented((f"// {heading}\n" if heading else "") + _jsdoc(docs, indent="").rstrip("\n")) + "\n",
        f"{_I}class {cls} {{\n",
        (f"{_I * 2}// {headings[ctor.name]}\n" if headings[ctor.name] else "") + _jsdoc(_docs(ctor), indent=_I * 2),
        f"{_I * 2}constructor({', '.join(m.params)}) {{\n",
        _block(body, _I * 3),
        f"{_I * 2}}}\n",
        f"\n{_I * 2}get handle() {{\n{_I * 3}return this.{_HANDLE};\n{_I * 2}}}\n",
    ]
    out += [f"\n{_I * 2}get {p.name}() {{\n{_I * 3}return this._cached_{p.name};\n{_I * 2}}}\n" for p in shape.cached]
    live = (
        f'if (this.{_HANDLE} === null) {{\n{_I}throw new Error("{cls} used after {dtor.name}");\n}}' if locked else None
    )
    for fn in shape.methods:
        m = _marshal(api, fn, fn.params[1:], ctx=f"{cls}.{fn.name}")
        busy = _receiver_busy(api, fn, cls=cls, name=fn.name)
        takes_callback = any(p.callback for p in fn.params)
        receiver = [f"if (this.{_HELD} !== null) {{\n{_I}throw {busy};\n}}"] if locked or drives else []
        if locked:
            receiver += [f'this.{_HELD} = "{naming.function_name(api.namespace, fn.name)}";', "_held.push(this);", live]
        handle_value = f"this.{_HANDLE}._value" if locked else f"(this.{_HANDLE}._value ?? 0)"
        body = _body(
            api,
            fn,
            m,
            ctx=f"{cls}.{fn.name}",
            first_args=[handle_value],
            receiver=receiver,
            entering=not locked and takes_callback,
            ok=[],
            returns=True,
        )
        out.append(
            "\n"
            + (f"{_I * 2}// {headings[fn.name]}\n" if headings[fn.name] else "")
            + _jsdoc(_docs(fn), indent=_I * 2)
            + f"{_I * 2}{fn.name}({', '.join(m.params)}) {{\n"
            + _block(body, _I * 3)
            + f"{_I * 2}}}\n"
        )
    if dtor is not None:
        out.append(
            "\n"
            + (f"{_I * 2}// {headings[dtor.name]}\n" if headings[dtor.name] else "")
            + _jsdoc(_docs(dtor), indent=_I * 2)
            + f"{_I * 2}release() {{\n"
            + _block(_release(api, dtor, cls=cls, locked=locked, drives=drives, live=live), _I * 3)
            + f"{_I * 2}}}\n"
            + f"\n{_I * 2}[Symbol.dispose]() {{\n{_I * 3}this.release();\n{_I * 2}}}\n"
        )
    out.append(f"{_I}}}\n")
    return "".join(out)


def _receiver_busy(api: Api, fn: Function, *, cls: str, name: str) -> str:
    return _busy(api, fn, message=f"{cls}.{name} called while ${{this.{_HELD}}} is in progress on this {cls}")


def _release(api: Api, dtor: Function, *, cls: str, locked: bool, drives: bool, live: str | None) -> list[str]:
    """`release()`'s statements: refused while another call holds the object or, unlocked, while
    a call of it drives a callback; locked, refused once released, and the object's handle taken
    and cleared, so `handle` reads null; unlocked, the handle cleared in place after the call, so
    every holder of it reads null and every later call passes the null handle; then the dtor's
    result checked."""
    fname = naming.function_name(api.namespace, dtor.name)
    busy = _receiver_busy(api, dtor, cls=cls, name="release")
    lines = [f"_alive({_STATE});", *_stack_check(dtor, ctx=f"{cls}.release")]
    if locked or drives:
        lines.append(f"if (this.{_HELD} !== null) {{\n{_I}throw {busy};\n}}")
    if locked:
        lines += [
            live,
            f"const _taken = this.{_HANDLE};",
            f"this.{_HANDLE} = null;",
            f'const _raw = _invoke({_STATE}, "{fname}", [_taken._value]);',
            "_taken._value = null;",
        ]
    else:
        lines += [
            f'const _raw = _invoke({_STATE}, "{fname}", [this.{_HANDLE}._value ?? 0]);',
            f"this.{_HANDLE}._value = null;",
        ]
    return [*lines, *_result_check(api, dtor)]


def _function(api: Api, fn: Function, *, heading: str | None) -> str:
    """A function no class renders, a member of the library."""
    m = _marshal(api, fn, fn.params, ctx=fn.name)
    body = _body(api, fn, m, ctx=fn.name, first_args=[], receiver=[], entering=False, ok=[], returns=True)
    return (
        "\n"
        + (f"{_I}// {heading}\n" if heading else "")
        + _jsdoc(_docs(fn), indent=_I)
        + f"{_I}function {fn.name}({', '.join(m.params)}) {{\n"
        + _block(body, _I * 2)
        + f"{_I}}}\n"
    )


def _load(api: Api) -> str:
    """`load`: the module file found, instantiated with WASI's imports and the shim's, WASI
    initialized once, each callback type's address read, then the classes and functions of this
    instance, returned as the library."""
    ns, lib = api.namespace, api.library.name
    file = naming.library_file_name(lib, platform="wasi", link=naming.SHARED)
    imports = "".join(
        f"{_I * 3}{naming.wasm_callback_import(ns, cb.name)}: (...args) => _{naming.trampoline(cb.name)}({_STATE}, ...args),\n"
        for cb in api.callbacks
    )
    addresses = "".join(
        f'{_I * 2}{cb.name}: _invoke({_STATE}, "{naming.wasm_callback_address(ns, cb.name)}", []) >>> 0,\n'
        for cb in api.callbacks
    )
    classes = api.classes()
    headings = {o.name: h for h, o in headed(api.opaque_ref_groups, (s.opaque for s in classes))}
    members = [naming.upper_camel(s.opaque.class_name) for s in classes] + [fn.name for fn in api.free_functions()]
    return (
        f"\n/** The library's classes and functions over a new instance of its module; see the module's comment. */\n"
        f"export function {naming.NODE_LOAD}(wasi, path) {{\n"
        f'{_I}const _file = path === undefined ? _join(_dirname(_fileURLToPath(import.meta.url)), "{file}") : path;\n'
        f'{_I}if (typeof _file !== "string" || !_isAbsolute(_file)) {{\n'
        f"{_I * 2}throw new TypeError(`the module of the library {lib} is named by an absolute path, not ${{String(_file)}}`);\n"
        f"{_I}}}\n"
        f"{_I}let _module;\n"
        f"{_I}try {{\n{_I * 2}_module = new WebAssembly.Module(_readFileSync(_file));\n"
        f"{_I}}} catch (error) {{\n"
        f"{_I * 2}throw new Error(`cannot load the module of the library {lib} from ${{_file}}: ${{String(error)}}`, {{ cause: error }});\n"
        f"{_I}}}\n"
        f"{_I}const {_STATE} = {{\n"
        f"{_I * 2}exports: null,\n{_I * 2}memory: null,\n{_I * 2}dead: null,\n{_I * 2}frames: new Map(),\n{_I * 2}next: 1,\n"
        f'{_I * 2}alloc: "{naming.wasm_alloc(ns)}",\n{_I * 2}free: "{naming.wasm_free(ns)}",\n{_I}}};\n'
        f"{_I}const _instance = new WebAssembly.Instance(_module, {{\n"
        f"{_I * 2}...wasi.getImportObject(),\n"
        f"{_I * 2}{naming.wasm_import_module(ns)}: {{\n{imports}{_I * 2}}},\n"
        f"{_I}}});\n"
        f"{_I}wasi.initialize(_instance);\n"
        f"{_I}{_STATE}.exports = _instance.exports;\n"
        f"{_I}{_STATE}.memory = _instance.exports.memory;\n"
        f"{_I}const _addresses = {{\n{addresses}{_I}}};\n"
        + "".join(_class(api, shape, heading=headings[shape.opaque.name]) for shape in classes)
        + "".join(_function(api, fn, heading=h) for h, fn in headed(api.function_groups, api.free_functions()))
        + f"\n{_I}return Object.freeze({{ {', '.join(members)} }});\n}}\n"
    )


# ---- the declarations -------------------------------------------------------------------------


def _ts_value(api: Api, type_name: str) -> str:
    """The TypeScript type of a value of `type_name`."""
    kind = api.kind(type_name)
    if kind == "builtin":
        return "number"
    if kind == "opaque":
        return naming.handle_type(type_name)
    return naming.upper_camel(type_name)


def _ts_param(api: Api, p: Param, shapes: dict[str, ClassShape]) -> str:
    """The TypeScript type of the argument `p` is."""
    if p.callback:
        found = naming.upper_camel(p.type)
    elif p.is_union:
        found = naming.union_sequence(p.type)
    elif p.is_buffer:
        if p.ref == "out":
            found = "number"
        elif p.type == "memory":
            found = "ArrayBufferView | ArrayBuffer"
        else:
            found = f"Iterable<{_ts_value(api, p.type)}>"
    elif api.kind(p.type) == "opaque" and p.type in shapes and p.ref in (None, "in"):
        found = naming.upper_camel(shapes[p.type].opaque.class_name)
    else:
        found = _ts_value(api, p.type)
    return f"{found} | null" if p.optional else found


def _ts_outs(api: Api, params: tuple[Param, ...]) -> list[str]:
    """The TypeScript type of each value a call of `params` returns, in order."""
    outs = []
    for p in params:
        if p.callback:
            continue
        if p.is_buffer:
            if p.ref == "in":
                continue
            outs.append("Uint8Array" if p.type == "memory" else f"{_ts_value(api, p.type)}[]")
            outs += ["number", "number"] if p.report_names() else []
        elif p.ref == "out":
            outs.append(
                f"{naming.handle_type(p.type)} | null" if api.kind(p.type) == "opaque" else _ts_value(api, p.type)
            )
        elif p.ref == "inout":
            outs.append(f"{_ts_value(api, p.type)}{' | null' if p.optional else ''}")
    return outs


def _ts_returns(outs: list[str]) -> str:
    if not outs:
        return "void"
    return outs[0] if len(outs) == 1 else f"[{', '.join(outs)}]"


def _ts_params(api: Api, params: tuple[Param, ...], shapes: dict[str, ClassShape]) -> str:
    """The parenthesized parameter list of a call taking `params`, a non-buffer `out` aside."""
    rendered = [p for p in params if p.is_buffer or p.ref != "out"]
    return f"({', '.join(f'{_arg_name(p)}: {_ts_param(api, p, shapes)}' for p in rendered)})"


def _ts_signature(api: Api, fn: Function, params: tuple[Param, ...], shapes: dict[str, ClassShape]) -> str:
    return f"{_ts_params(api, params, shapes)}: {_ts_returns(_ts_outs(api, params))}"


def _ts_callback(api: Api, callback: Function) -> str:
    """The function type a callback parameter takes."""
    args = []
    for p in callback.params:
        if p.is_union:
            found = naming.union_sequence(p.type)
        elif p.type == "memory":
            found = naming.NODE_BYTE_VIEW
        elif p.is_buffer:
            found = f"{naming.NODE_VIEW}<{_ts_value(api, p.type)}>"
        else:
            found = _ts_value(api, p.type)
        args.append(f"{p.name}: {found}")
    return f"export type {naming.upper_camel(callback.name)} = ({', '.join(args)}) => number | void;\n"


_TS_VIEWS = f"""
/** A view the library passed a callback, read lazily, valid until its callback returns. */
export interface {naming.NODE_VIEW}<T> extends Iterable<T> {{
  readonly length: number;
  at(index: number): T;
  slice(start?: number, end?: number): T[];
}}

/** A byte view the library passed a callback, valid until its callback returns. */
export interface {naming.NODE_BYTE_VIEW} extends Iterable<number> {{
  readonly length: number;
  at(index: number): number;
  slice(start?: number, end?: number): Uint8Array;
}}

/** A call's result other than the zero entry: `result` is it, a value of the return enum. */
export declare class {_ERROR} extends Error {{
  private constructor();
  readonly result: number;
}}

/** What the loader takes of a `node:wasi` WASI of version preview1, not yet started: one per `{naming.NODE_LOAD}`. */
export interface {naming.NODE_WASI} {{
  getImportObject(): object;
  initialize(instance: object): void;
}}
"""


def _declarations(api: Api, *, module: str) -> str:
    """The TypeScript declarations of the module `module`, `<name>.d.mts`."""
    # TypeScript's default libraries lack Symbol.dispose, which `release` declares
    out = [f"// {emitter.companion_banner(module)}\n", '/// <reference lib="esnext.disposable" />\n', _module_doc(api)]
    for doc, literals in _constant_sections(api):
        out.append("\n" + (f"// {doc}\n" if doc else ""))
        out += [f"export declare const {n}: {_ts_literal(v)};\n" for n, v in literals]
    out += [f"export declare function {name}(value: number): string;\n" for _, name in _conversion_names(api)]
    for h, t in headed(api.typed_const_groups):
        enum = naming.upper_camel(t.name)
        entries = "; ".join(f"readonly {naming.unprefixed_const_name(e.name)}: {e.value}" for e in t.entries)
        out.append(
            "\n"
            + (f"// {h}\n" if h else "")
            + _jsdoc([t.docstring] if t.docstring else [], indent="")
            + f"export declare const {enum}: {{ {entries} }};\n"
            + f"export type {enum} = (typeof {enum})[keyof typeof {enum}];\n"
        )
    out.append(_TS_VIEWS)
    out += [
        f"\n/** A raw {naming.type_name(api.namespace, o.name)} handle an instance issued. */\n"
        f"export declare class {naming.handle_type(o.name)} {{\n{_I}private constructor();\n{_I}readonly value: number | null;\n}}\n"
        for o in api.opaque_refs
    ]
    out += [f"export type {naming.upper_camel(b.name)} = number;\n" for b in api.boxed_scalars]
    structs = [(None, naming.TEXT, None, naming.TEXT_FIELDS)] if api.uses_text() else []
    structs += [(h, s.name, s.docstring, [(f.name, f.type) for f in s.fields]) for h, s in headed(api.struct_groups)]
    for h, name, doc, members in structs:
        cls = naming.upper_camel(name)
        fields = "".join(f"{_I}{n}: {_ts_value(api, t)};\n" for n, t in members)
        out.append(
            "\n"
            + (f"// {h}\n" if h else "")
            + _jsdoc([doc] if doc else [], indent="")
            + f"export declare class {cls} {{\n{_I}constructor(fields?: Partial<{cls}>);\n{fields}}}\n"
        )
    if api.uses_text():
        out.append(
            f"export declare function {naming.RESOLVE}(text: {naming.upper_camel(naming.TEXT)}, "
            f"arena: ArrayBufferView | ArrayBuffer | {naming.NODE_BYTE_VIEW}): Uint8Array | null;\n"
        )
    lists = api.listed_unions()
    if lists:
        out.append(
            f"\nexport declare class {naming.UNION_ERROR} extends Error {{\n{_I}private constructor();\n"
            f"{_I}readonly index: number;\n{_I}readonly offset: number;\n{_I}readonly clause: string;\n}}\n"
        )
    for h, u in headed(api.union_groups, lists):
        records = " | ".join(naming.upper_camel(m.struct) for m in u.members)
        out.append(
            f"\n// the list's alignment, the unit of {naming.union_sequence(u.name)}.at's index\n"
            f"export declare const {_union_align(u)}: {api.list_alignment(u)};\n"
            + (f"// {h}\n" if h else "")
            + _jsdoc([u.docstring] if u.docstring else [], indent="")
            + f"export declare class {naming.union_sequence(u.name)} implements Iterable<{records}> {{\n"
            + f"{_I}private constructor();\n{_I}readonly length: number;\n{_I}readonly bytes: number;\n"
            + f"{_I}at(index: number): {records};\n{_I}[Symbol.iterator](): Iterator<{records}>;\n}}\n"
        )
    out += ["\n" + _ts_callback(api, cb) for cb in api.callbacks]
    shapes = {shape.opaque.name: shape for shape in api.classes()}
    library = []
    for shape in api.classes():
        cls = naming.upper_camel(shape.opaque.class_name)
        members = [f"{_I}readonly handle: {naming.handle_type(shape.opaque.name)} | null;\n"]
        members += [f"{_I}readonly {p.name}: {_ts_outs(api, (p,))[0]};\n" for p in shape.cached]
        for fn in shape.methods:
            members.append(
                _jsdoc(_docs(fn), indent=_I) + f"{_I}{fn.name}{_ts_signature(api, fn, fn.params[1:], shapes)};\n"
            )
        if shape.dtor is not None:
            members.append(
                _jsdoc(_docs(shape.dtor), indent=_I) + f"{_I}release(): void;\n{_I}[Symbol.dispose](): void;\n"
            )
        ctor_args = _ts_params(api, shape.ctor.params, shapes)
        constructor = naming.node_constructor_type(cls)
        out.append(
            "\n"
            + _jsdoc([shape.opaque.docstring] if shape.opaque.docstring else [], indent="")
            + f"export interface {cls} {{\n{''.join(members)}}}\n"
            + f"export interface {constructor} {{\n"
            + _jsdoc(_docs(shape.ctor), indent=_I)
            + f"{_I}new {ctor_args}: {cls};\n{_I}readonly prototype: {cls};\n}}\n"
        )
        library.append(f"{_I}readonly {cls}: {constructor};\n")
    library += [
        _jsdoc(_docs(fn), indent=_I) + f"{_I}{fn.name}{_ts_signature(api, fn, fn.params, shapes)};\n"
        for fn in api.free_functions()
    ]
    out.append(
        f"\n/** What `{naming.NODE_LOAD}` returns: the library's classes and functions over one instance. */\n"
        f"export interface {naming.NODE_LIBRARY} {{\n{''.join(library)}}}\n"
        f"\nexport declare function {naming.NODE_LOAD}(wasi: {naming.NODE_WASI}, path?: string): {naming.NODE_LIBRARY};\n"
    )
    return "".join(out)


def _ts_literal(literal: str) -> str:
    """A constant's literal as its TypeScript literal type: a string itself, a number in decimal."""
    if literal.startswith('"'):
        return literal
    return str(int(literal, 0))
