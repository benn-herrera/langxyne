"""The Go binding: one cgo package whose preamble is the C declarations a binding carries,
over them the constants, enums, conversions and types, and one object per opaque ref that
names a constructor, every call returning an `error`."""

from dataclasses import dataclass, field
from pathlib import Path

from langxyne import model, naming
from langxyne.emitters import c, emitter
from langxyne.model import (
    Api,
    BitConst,
    ClassShape,
    EnumEntry,
    Field,
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

LABEL = "go"

_GO_KEYWORDS = frozenset(
    "break case chan const continue default defer else fallthrough for func go goto if import interface map "
    "package range return select struct switch type var".split()
)
_GO_TYPES = {
    "i8": "int8",
    "u8": "uint8",
    "i16": "int16",
    "u16": "uint16",
    "i32": "int32",
    "u32": "uint32",
    "i64": "int64",
    "u64": "uint64",
    "f32": "float32",
    "f64": "float64",
}
_BODY_NAMES = ("C", "unsafe", "nil", "len", "panic", *_GO_TYPES.values())
"""What a function body spells where the function's parameters are in scope, beside the
names the package defines and its private `_` names: cgo's `C`, the `unsafe` package, whose
`unsafe.Pointer` an `//export` signature must spell so, the predeclared names it calls, and the
Go integer and float types, which a result local is declared as. A parameter named like one
would shadow it."""
_LD64_PLATFORMS = ("macos",)
"""The table platforms whose linker, ld64, has no `-l:<file>`: a static link there names the
library and needs the archive alone in its search directory."""
_IN_CALL = "_in_call"
_FAILURE = "_failure"
_FAILURE_TYPE = "_failure_record"
_FRAME_TYPE = "_frame"
_SELF = "_self"
_UNION_ERROR = naming.UNION_ERROR


def validate(api: Api) -> list[str]:
    """Every objection the Go binding has to `api`: a Go keyword where the package spells a
    definition name as written (the package name, a parameter, a struct field, which cgo reaches
    by its C name); a parameter a function body has in scope named like a name that body spells
    or a name the package defines; a name defined twice in the package, in an enum's methods,
    in a struct or in a class; a package-scope name a union's rendering defines that anything
    else defines, naming the union; and no library named."""
    objections = [f"_general._name: '{api.name}' is a Go keyword"] if api.name in _GO_KEYWORDS else []
    raw = [(f"struct.{s.name}.{f.name}", f.name) for s in api.structs for f in s.fields]
    raw += [
        (f"{kind}.{fn.name}.{p.name}", p.name)
        for kind, signatures in (("callback", api.callbacks), ("function", api.functions))
        for fn in signatures
        for p in fn.params
    ]
    objections += [f"{where}: '{name}' is a Go keyword" for where, name in raw if name in _GO_KEYWORDS]

    package = _package_names(api)
    unions = _union_names(api)
    used = {*_BODY_NAMES, *(name for _, name in (*package, *unions))}
    params = [(f"function.{fn.name}.{p.name}", p.name) for fn, rendered in _rendered(api) for p in rendered]
    objections += generated_name_objections(params, used)
    objections += duplicate_objections(package, "package scope")
    defined = {name: union for union, name in unions}
    objections += [
        f"{where}: package scope name {name} already defined by {defined[name]}"
        for where, name in package
        if name in defined
    ]
    objections += duplicate_objections(unions, "package scope")
    returned = {fn.returns for fn in api.functions}
    for t in api.typed_consts:
        methods = []
        if t.to_string is not None:
            methods += [
                (f"typed_const.{t.name}._to_string", naming.go_exported(t.to_string)),
                ("its Stringer", "String"),
            ]
        if t.name in returned:
            methods.append(("its error interface", "Error"))
        objections += duplicate_objections(methods, f"enum {naming.go_exported(t.name)}")
    for s in api.structs:
        fields = [(f"struct.{s.name}.{f.name}", naming.go_exported(f.name)) for f in s.fields]
        objections += duplicate_objections(fields, f"struct {naming.go_exported(s.name)}")
    for shape in api.classes():
        own = ["Handle", *(["Release"] if shape.dtor is not None else [])]
        members = [(where, naming.go_exported(name)) for where, name in shape.members(own)]
        objections += duplicate_objections(members, f"class {naming.go_exported(shape.opaque.class_name)}")
    if api.library.name is None:
        objections.append(emitter.NO_LIBRARY)
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("go") / name / f"{name}.go"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def _package_names(api: Api) -> list[tuple[str, str]]:
    """(where, name) of everything the package defines, and cgo's `C`, which `import "C"`
    holds in every file of it."""
    exported = naming.go_exported
    names = [('import "C"', "C")]
    names += [(where, exported(name)) for where, name in api.constant_names(enum_entries=False, version=True)]
    names += [
        (f"{g.name}._to_string", exported(g.to_string))
        for g in (*api.bit_const_groups, *api.const_groups)
        if g.to_string is not None
    ]
    for t in api.typed_consts:
        names.append((f"typed_const.{t.name}", exported(t.name)))
        names += [(f"typed_const.{t.name}.{e.name}", naming.go_enum_entry(t.name, e.name)) for e in t.entries]
    names += [(f"opaque_ref.{o.name}", naming.handle_type(o.name)) for o in api.opaque_refs]
    names += [(f"boxed_scalar.{b.name}", exported(b.name)) for b in api.boxed_scalars]
    if api.uses_text():
        names.append((f"the builtin type {naming.TEXT}", exported(naming.TEXT)))
    names += [(f"struct.{s.name}", exported(s.name)) for s in api.structs]
    if _renders_filled(api):
        names.append(("the generated struct of a reported buffer", naming.FILLED))
    names += [(f"callback.{cb.name}", exported(cb.name)) for cb in api.callbacks]
    for shape in api.classes():
        names.append((f"opaque_ref.{shape.opaque.name}._class", exported(shape.opaque.class_name)))
        names.append((f"opaque_ref.{shape.opaque.name}._ctor", naming.go_constructor(shape.opaque.class_name)))
    names += [(f"function.{fn.name}", exported(fn.name)) for fn in api.free_functions()]
    return names


def _union_types(union: Union) -> tuple[str, str, str]:
    """The package-scope types of union `union`'s list: `NoteSequence`, `NoteRecord`, `NoteWalker`."""
    return naming.union_sequence(union.name), naming.go_union_record(union.name), naming.go_union_walker(union.name)


def _union_clause(name: str) -> str:
    """The constant of clause `name` of `naming.UNION_CLAUSES`: `UnionClauseUnknownTag`."""
    return naming.go_enum_entry(naming.UNION_CLAUSE, name)


def _union_names(api: Api) -> list[tuple[str, str]]:
    """(definer, name) of what the package defines for its unions declaring `_mixed_type_list`:
    `UnionClause`, its constants and `UnionError`, the first such union's, then each one's types and alignment constant."""
    listed = api.listed_unions()
    if not listed:
        return []
    first = f"union '{listed[0].name}'"
    names = [(first, naming.UNION_CLAUSE_TYPE), (first, _UNION_ERROR)]
    names += [(first, _union_clause(name)) for name, _ in naming.UNION_CLAUSES]
    names += [(f"union '{u.name}'", name) for u in listed for name in (*_union_types(u), _union_align(u))]
    return names


def _union_align(union: Union) -> str:
    """The package-scope constant of union `union`'s list alignment: `NoteAlign`."""
    return naming.go_exported(naming.union_align(union.name))


def _union_position(api: Api) -> str:
    """The Go type of a `UnionError`'s index and offset: `uint32`, or `uint64` where some union
    declaring `_mixed_type_list` is counted by `u64`, so every union's count type fits."""
    return "uint64" if any(u.count_type == "u64" for u in api.listed_unions()) else "uint32"


def _rendered(api: Api) -> list[tuple[Function, list[Param]]]:
    """Each function the package renders with the parameters its Go signature takes, every one
    but a non-buffer `out` it returns (each of a ctor's, a method's but an `_optional` one): a
    class's ctor and methods, the method's first parameter the object, and every free function."""
    rendered = [(fn, params, ctor) for shape in api.classes() for fn, params, ctor in shape.class_params()]
    rendered += [(fn, fn.params, False) for fn in api.free_functions()]
    return [
        (fn, [p for p in params if p.is_buffer or p.ref != "out" or (p.optional and not ctor)])
        for fn, params, ctor in rendered
    ]


def _renders_filled(api: Api) -> bool:
    return any(p.wrote_needed for fn in api.functions for p in fn.params)


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The Go package's one file, as gofmt lays it out."""
    blocks = [_version(api)]
    blocks += [_constant_group(api, g) + _bit_to_string(g) for g in api.bit_const_groups]
    blocks += [_constant_group(api, g) + _plain_to_string(g) for g in api.const_groups]
    blocks += [_string_group(g) for g in api.string_const_groups]
    returned = {fn.returns for fn in api.functions}
    blocks += [_enum(api, t, heading=h, returned=t.name in returned) for h, t in headed(api.typed_const_groups)]
    blocks += [_handle_type(api, h, o.name, o.docstring) for h, o in headed(api.opaque_ref_groups)]
    blocks += [
        _comment(h) + _comment(b.docstring) + f"type {naming.go_exported(b.name)} {_GO_TYPES[b.base_type]}\n"
        for h, b in headed(api.boxed_scalar_groups)
    ]
    blocks += [_size_assertion(api, b.name) for b in api.boxed_scalars]
    if api.uses_text():
        blocks.append(_text(api))
    blocks += [_struct(api, h, s.name, s.docstring, s.fields) for h, s in headed(api.struct_groups)]
    listed = api.listed_unions()
    if listed:
        blocks.append(_union_clause_and_error(api))
        blocks += [_union(api, h, u) for h, u in headed(api.union_groups, listed)]
    if _renders_filled(api):
        blocks.append(_FILLED_TEXT)
    if any(p.is_buffer for fn in api.functions for p in fn.params):
        blocks.append(_DATA_TEXT)
    if api.callbacks:
        blocks.append(_CALLBACK_TEXT)
    classes = api.classes()
    if classes:
        blocks.append(_NO_COPY_TEXT)
    blocks += [_callback_type(api, h, cb) for h, cb in headed(api.callback_groups)]
    blocks += [_trampoline(api, cb) for cb in api.callbacks]
    opaque_headings = {o.name: h for h, o in headed(api.opaque_ref_groups, (s.opaque for s in classes))}
    blocks += [_class(api, shape, heading=opaque_headings[shape.opaque.name]) for shape in classes]
    blocks += [_function(api, fn, heading=h) for h, fn in headed(api.function_groups, api.free_functions())]
    imports = _imports(api)
    import_block = "\nimport (\n" + "".join(f"\t{i}\n" for i in imports) + ")\n" if imports else ""
    text = (
        emitter.go_banner(source_name)
        + "\n\n"
        + _package_doc(api)
        + f"package {api.name}\n\n"
        + _preamble(api)
        + 'import "C"\n'
        + import_block
        + "\n"
        + "\n".join(blocks)
    )
    return emitter.formatted(["gofmt"], text, outputs="the Go output", output="the Go output")


def _package_doc(api: Api) -> str:
    """Under a static link, the package doc comment stating what ld64 links from a directory
    holding both of the library's files."""
    if api.library.link != naming.STATIC:
        return ""
    lib = api.library.name
    dylib = naming.library_file_name(lib, platform="macos", link=naming.SHARED)
    archive = naming.library_file_name(lib, platform="macos", link=naming.STATIC)
    return (
        f"// On macOS the linker takes {dylib} before {archive} from the same directory, so the directory"
        f" CGO_LDFLAGS names must hold the archive and no {dylib}.\n"
    )


def _imports(api: Api) -> list[str]:
    """The standard-library imports the file spells, each only where it does, since an unused
    import does not compile: `runtime/cgo` for the callbacks' handles and `os` for a
    trampoline's exit, `strconv` and `strings` for a bit group's conversion and `strconv` for
    the `Error()` of a returned enum without one or of `UnionError`, and `unsafe` for a layout
    assertion, a pointer argument or a callback. `unsafe` keeps its name, the one spelling of
    `unsafe.Pointer` cgo accepts in an `//export` signature."""
    bit_conversion = any(g.to_string is not None for g in api.bit_const_groups)
    returned = {fn.returns for fn in api.functions}
    numbered_error = api.listed_unions() or any(t.name in returned and t.to_string is None for t in api.typed_consts)
    pointers = any(
        p.is_buffer or p.ref is not None or api.kind(p.type) in ("boxed", "struct")
        for fn in api.functions
        for p in fn.params
    )
    imports = ['_os "os"', '_cgo "runtime/cgo"'] if api.callbacks else []
    imports += ['_strconv "strconv"'] if bit_conversion or numbered_error else []
    imports += ['_strings "strings"'] if bit_conversion else []
    if api.boxed_scalars or api.structs or api.callbacks or pointers:
        imports.append('"unsafe"')
    return imports


def _preamble(api: Api) -> str:
    """The cgo preamble, a `//` comment so the C comments in it end nothing: the link flags,
    `<stdint.h>`, the C declarations a binding carries, and each trampoline's prototype, which
    is the one `_cgo_export.h` declares, every pointer without `const`."""
    lines = [*_link_lines(api), "#include <stdint.h>"]
    lines += c.binding_declarations(api).splitlines()
    for cb in api.callbacks:
        params = ", ".join(f"{t.removeprefix('const ')} {n}" for t, n in c.callback_params(api, cb))
        symbol = naming.go_export_symbol(api.namespace, cb.name)
        lines.append(f"extern {c.c_type(api, cb.returns)} {symbol}({params});")
    return "".join(f"// {line}\n" if line else "//\n" for line in lines)


def _link_lines(api: Api) -> list[str]:
    """The `#cgo LDFLAGS` naming the library: `-l<lib>` shared; static, the archive's file
    by `-l:<file>` where the platform's linker takes it, else `-l<lib>`."""
    lib = api.library.name
    if api.library.link != naming.STATIC:
        return [f"#cgo LDFLAGS: -l{lib}"]
    lines = []
    for platform, goos in naming.GO_OS.items():
        if platform in _LD64_PLATFORMS:
            lines.append(f"#cgo {goos} LDFLAGS: -l{lib}")
        else:
            archive = naming.library_file_name(lib, platform=platform, link=naming.STATIC)
            lines.append(f"#cgo {goos} LDFLAGS: -l:{archive}")
    return lines


def _comment(doc: str | None, *, indent: str = "") -> str:
    return f"{indent}// {doc}\n" if doc else ""


def _doc_lines(docs: list[str], *, heading: str | None = None, indent: str = "") -> str:
    return "".join(_comment(d, indent=indent) for d in [heading, *docs])


def _go_type(api: Api, type_name: str) -> str:
    """A definition type's Go spelling at package scope: a builtin its Go type, an opaque ref its
    raw handle type, anything else its exported name."""
    kind = api.kind(type_name)
    if kind == "builtin":
        return _GO_TYPES[type_name]
    if kind == "opaque":
        return naming.handle_type(type_name)
    return naming.go_exported(type_name)


def _cgo_type(api: Api, type_name: str) -> str:
    """A definition type's C type as cgo names it: `C.uint32_t`, `C.xy_stats`."""
    return f"C.{c.c_type(api, type_name)}"


def _cgo_spelling(c_type: str) -> str:
    """A C parameter type of the declarations as a Go parameter type: a `void` pointer
    `unsafe.Pointer`, any other pointer `*C.T`, else `C.T`; `const` dropped."""
    c_type = c_type.removeprefix("const ")
    if c_type == "void*":
        return "unsafe.Pointer"
    if c_type.endswith("*"):
        return f"*C.{c_type[:-1]}"
    return f"C.{c_type}"


def _version(api: Api) -> str:
    return f"const {naming.go_exported(naming.VERSION_KEY)} uint32 = 0x{api.version_value():08x}\n"


def _constant_group(api: Api, group: Group[BitConst] | Group[EnumEntry]) -> str:
    """A bit or plain group as one `const` block under its docstring, each constant typed by the
    group's base type, its value the model's resolved one spelled per `_format`."""
    base = _GO_TYPES[group.base_type]
    lines = "".join(
        _comment(e.docstring, indent="\t")
        + f"\t{naming.go_exported(e.name)} {base} = {c.int_literal(e.value, e.format)}\n"
        for e in group.entries
    )
    return f"{_comment(group.docstring)}const (\n{lines})\n"


def _string_group(group: Group) -> str:
    lines = "".join(
        _comment(e.docstring, indent="\t") + f'\t{naming.go_exported(e.name)} = "{e.value}"\n' for e in group.entries
    )
    return f"{_comment(group.docstring)}const (\n{lines})\n"


def _plain_to_string(group: Group[EnumEntry]) -> str:
    if group.to_string is None:
        return ""
    base = _GO_TYPES[group.base_type]
    cases = [(naming.go_exported(e.name), naming.unprefixed_const_name(e.name)) for e in named_values(group)]
    return (
        f"\n// {naming.go_exported(group.to_string)} is the name of a value of the group, "
        f"{naming.unknown_value_name(None)} where none has it.\n"
        f"func {naming.go_exported(group.to_string)}(value {base}) string {{\n"
        + _switch("value", cases, unknown=naming.unknown_value_name(None))
        + "}\n"
    )


def _switch(value: str, cases: list[tuple[str, str]], *, unknown: str) -> str:
    arms = "".join(f'\tcase {const}:\n\t\treturn "{text}"\n' for const, text in cases)
    return f"\tswitch {value} {{\n{arms}\t}}\n" f'\treturn "{unknown}"\n'


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term of their 32-bit pattern."""
    if group.to_string is None:
        return ""
    base = _GO_TYPES[group.base_type]
    flags = "".join(
        f"\tif value&{k} != 0 {{\n"
        f'\t\t_names = append(_names, "{naming.unprefixed_const_name(e.name)}")\n'
        f"\t\tvalue &^= {k}\n"
        "\t}\n"
        for e in single_bit_entries(group)
        for k in [naming.go_exported(e.name)]
    )
    return (
        f"\n// {naming.go_exported(group.to_string)} is the names of the group's flags set in a value.\n"
        f"func {naming.go_exported(group.to_string)}(value {base}) string {{\n"
        f'\tif value == 0 {{\n\t\treturn "{naming.NO_FLAGS}"\n\t}}\n'
        "\tvar _names []string\n"
        f"{flags}"
        "\tif value != 0 {\n"
        '\t\t_names = append(_names, "0x"+_strconv.FormatUint(uint64(uint32(value)), 16))\n'
        "\t}\n"
        '\treturn _strings.Join(_names, "|")\n'
        "}\n"
    )


def _enum(api: Api, typed: TypedConst, *, heading: str | None, returned: bool) -> str:
    """The enum's type over its base type, its entries, `_named()`, and with `_to_string` its
    conversion and `String()`; an enum a function returns is an `error`."""
    name = naming.go_exported(typed.name)
    c_name = naming.type_name(api.namespace, typed.name)
    entries = "".join(
        _comment(e.docstring, indent="\t")
        + f"\t{naming.go_enum_entry(typed.name, e.name)} {name} = {c.int_literal(e.value, e.format)}\n"
        for e in typed.entries
    )
    constants = ", ".join(naming.go_enum_entry(typed.name, e.name) for e in typed.entries)
    out = [
        _comment(heading)
        + _comment(typed.docstring)
        + f"// Converting an integer no entry names to {name} is not refused: the library receives it as it is.\n"
        + f"type {name} {_GO_TYPES[typed.base_type]}\n\n",
        f"const (\n{entries})\n\n",
        f"func (_v {name}) _named() bool {{\n\tswitch _v {{\n\tcase {constants}:\n\t\treturn true\n\t}}\n"
        "\treturn false\n}\n",
    ]
    if typed.to_string is not None:
        conversion = naming.go_exported(typed.to_string)
        cases = [
            (naming.go_enum_entry(typed.name, e.name), naming.unprefixed_const_name(e.name)) for e in typed.entries
        ]
        out.append(
            f"\n// {conversion} is the entry's name, {naming.unknown_value_name(typed.name)} where no entry has the value.\n"
            f"func (_v {name}) {conversion}() string {{\n"
            + _switch("_v", cases, unknown=naming.unknown_value_name(typed.name))
            + "}\n"
            f"\n// String is {conversion}().\nfunc (_v {name}) String() string {{\n\treturn _v.{conversion}()\n}}\n"
        )
    if returned:
        text = (
            f"_v.{naming.go_exported(typed.to_string)}()"
            if typed.to_string is not None
            else f'"{c_name}(" + _strconv.FormatInt(int64(_v), 10) + ")"'
        )
        out.append(
            f"\n// Error makes a result other than the zero entry an error.\nfunc (_v {name}) Error() string {{\n\treturn {text}\n}}\n"
        )
    return "".join(out)


def _handle_type(api: Api, heading: str | None, opaque: str, doc: str | None) -> str:
    return (
        _comment(heading)
        + _comment(doc)
        + f"// {naming.handle_type(opaque)} is a raw handle; its zero value is the null handle.\n"
        + f"type {naming.handle_type(opaque)} struct{{ _h {_cgo_type(api, opaque)} }}\n"
    )


def _assertion(go: str, c_side: str) -> str:
    """A package-level declaration that compiles only where `go` equals `c_side`, both `uintptr`
    constants: their difference is an array length, a negative one overflowing `uintptr`."""
    return f"var _ [0]struct{{}} = [{go} - {c_side}]struct{{}}{{}}\n"


def _size_assertion(api: Api, type_name: str) -> str:
    zero = "(0)" if api.kind(type_name) == "boxed" else "{}"
    return _assertion(
        f"unsafe.Sizeof({_go_type(api, type_name)}{zero})", f"unsafe.Sizeof({_cgo_type(api, type_name)}{{}})"
    )


def _field_assertions(api: Api, type_name: str, fields: list[tuple[str, str]]) -> str:
    """Size and every field's offset of the Go type against its C type, `fields` each (Go
    field, C field)."""
    go, cgo = naming.go_exported(type_name), _cgo_type(api, type_name)
    return _size_assertion(api, type_name) + "".join(
        _assertion(f"unsafe.Offsetof({go}{{}}.{g})", f"unsafe.Offsetof({cgo}{{}}.{cf})") for g, cf in fields
    )


def _text(api: Api) -> str:
    offset, length = (naming.go_exported(n) for n, _ in naming.TEXT_FIELDS)
    fields = "".join(f"\t{naming.go_exported(n)} {_GO_TYPES[t]}\n" for n, t in naming.TEXT_FIELDS)
    resolve = naming.go_exported(naming.RESOLVE)
    return (
        "// Text is a run of bytes in an arena, as its offset and its length.\n"
        f"type Text struct {{\n{fields}}}\n\n"
        + _field_assertions(api, naming.TEXT, [(naming.go_exported(n), n) for n, _ in naming.TEXT_FIELDS])
        + f"\n// {resolve} is the bytes of arena the run covers, a subslice no append can grow into arena, valid as"
        " long as arena is (over a callback's view, until the func returns), and false where the run leaves"
        " arena.\n"
        f"func (_t Text) {resolve}(arena []byte) ([]byte, bool) {{\n"
        f"\t_end := uint64(_t.{offset}) + uint64(_t.{length})\n"
        "\tif _end > uint64(len(arena)) {\n\t\treturn nil, false\n\t}\n"
        f"\treturn arena[_t.{offset}:_end:_end], true\n"
        "}\n"
    )


def _struct(api: Api, heading: str | None, name: str, doc: str | None, fields: tuple[Field, ...]) -> str:
    lines = "".join(
        _comment(f.docstring, indent="\t") + f"\t{naming.go_exported(f.name)} {_go_type(api, f.type)}\n" for f in fields
    )
    return (
        _comment(heading)
        + _comment(doc)
        + f"type {naming.go_exported(name)} struct {{\n{lines}}}\n\n"
        + _field_assertions(api, name, [(naming.go_exported(f.name), f.name) for f in fields])
    )


def _union_clause_and_error(api: Api) -> str:
    """`UnionClause`, the six clauses from 1, whose `String()` is the clause's text, and
    `UnionError`, whose `Error()` names the record's index, its byte offset and the clause."""
    clause = naming.UNION_CLAUSE_TYPE
    position = _union_position(api)
    entries = "".join(
        f"\t// {text}\n\t{_union_clause(name)} {clause} = {value}\n"
        for value, (name, text) in enumerate(naming.UNION_CLAUSES, start=1)
    )
    cases = [(_union_clause(name), text) for name, text in naming.UNION_CLAUSES]
    index, offset = (f"_strconv.FormatUint(uint64(_e.{f}), 10)" for f in ("Index", "Offset"))
    return (
        f"// {clause} is why a walk of a union's list refused it, beside the record's index and byte offset in a\n"
        f"// {_UNION_ERROR}.\n"
        f"type {clause} int32\n\nconst (\n{entries})\n\n"
        f"// String is the clause's text.\nfunc (_c {clause}) String() string {{\n"
        + _switch("_c", cases, unknown=naming.unknown_value_name(naming.UNION_CLAUSE))
        + "}\n\n"
        f"// {_UNION_ERROR} is where a walk of a sequence refused it: the record's index, its byte offset, the clause.\n"
        f"type {_UNION_ERROR} struct {{\n\tIndex  {position}\n\tOffset {position}\n\tClause {clause}\n}}\n\n"
        "// Error is `record <index> at offset <offset>: <clause>`.\n"
        f"func (_e *{_UNION_ERROR}) Error() string {{\n"
        f'\treturn "record " + {index} + " at offset " + {offset} + ": " + _e.Clause.String()\n'
        "}\n"
    )


def _union(api: Api, heading: str | None, union: Union) -> str:
    """`union`'s list under its heading and docstring: the record interface each member's
    struct implements, the layout assertions holding the prefix and every member to
    `Api.layout()`, the list's alignment constant, the sequence, its walker and `At`. The walk reads a prefix only once its
    bytes remain and a member only once its tag names the member and its length is the member's
    size, every size a literal of the layout and every tag its constant's value."""
    seq, record, walker = _union_types(union)
    marker = naming.go_union_marker(union.name)
    head = naming.go_exported(union.prefix)
    tag, length = naming.go_exported(union.tag_field), naming.go_exported(union.length_field)
    head_size, align = api.layout(union.prefix)[0], api.list_alignment(union)
    align_const = _union_align(union)
    ct = _GO_TYPES[union.count_type]
    position = _union_position(api)
    consts = {k.name: k for k in api.consts}
    members = [
        (naming.go_exported(m.struct), c.int_literal(consts[m.tag].value, consts[m.tag].format), m)
        for m in union.members
    ]
    pointers = " or ".join(f"*{s}" for s, _, _ in members)
    markers = "".join(
        f"// {m.name}{f': {m.docstring}' if m.docstring else ''}\nfunc (*{s}) {marker}() {{}}\n" for s, _, m in members
    )
    assertions = "".join(
        _assertion(f"unsafe.Sizeof({s}{{}})", str(api.layout(name)[0]))
        + _assertion(f"unsafe.Alignof({s}{{}})", str(align))
        for s, name in ((head, union.prefix), *((s, m.struct) for s, _, m in members))
    )
    sizes = "".join(
        f"\t\tcase {value}: // {m.name}\n\t\t\t_size = {api.layout(m.struct)[0]}\n" for _, value, m in members
    )
    casts = "".join(
        f"\t\tcase _head.{tag} == {value}:\n\t\t\treturn (*{s})(unsafe.Pointer(_head)), _size, nil\n"
        for s, value, _ in members[:-1]
    )
    casts += f"\t\tdefault:\n\t\t\treturn (*{members[-1][0]})(unsafe.Pointer(_head)), _size, nil\n"

    def refused(offset: str, clause: str) -> str:
        return f"&{_UNION_ERROR}{{Index: {position}(_index), Offset: {position}({offset}), Clause: {clause}}}"

    not_a_start = refused("offset", _union_clause("not_a_record_start"))
    return (
        _comment(heading)
        + _comment(union.docstring)
        + f"// {record} is a record of {union.name} as its member's struct, {pointers}, which a type switch tells"
        " apart.\n"
        f"type {record} interface {{\n\t{marker}()\n}}\n\n"
        f"{markers}\n"
        f"{assertions}\n"
        f"// {align_const} is the list's alignment, the unit of {seq}.At's index.\n"
        f"const {align_const} = {align}\n\n"
        f"// {seq} is a list of {union.name}'s members back to back, each by its own size, as the library passed"
        " it: Walk walks it and At resolves an offset in units of the list's alignment, each refusing a malformed record and reading no byte"
        " past the extent. It is the library's memory, valid only until the func that received it returns, and"
        " read-only, as a slice a callback receives is.\n"
        f"type {seq} struct {{\n\t_bytes []byte\n\t_count {ct}\n}}\n\n"
        f"// Count is the number of records, as the library counted them.\n"
        f"func (_s {seq}) Count() {ct} {{\n\treturn _s._count\n}}\n\n"
        f"// Bytes is the records' bytes, the extent their length.\n"
        f"func (_s {seq}) Bytes() []byte {{\n\treturn _s._bytes\n}}\n\n"
        f"// Walk is a walker from the first record: for r, ok := w.Next(); ok; r, ok = w.Next() {{ switch r :="
        " r.(type) { ... } }, then w.Err().\n"
        f"func (_s {seq}) Walk() *{walker} {{\n\treturn &{walker}{{_s: _s}}\n}}\n\n"
        f"// At is the record at byte index × {align_const} from the sequence's start, found by"
        f" walking from the start, the byte offset saturating at {ct}'s largest: a *{_UNION_ERROR} where the walk"
        " refuses a record up to it, or passes it or ends without landing on it.\n"
        f"func (_s {seq}) At(index {ct}) ({record}, error) {{\n"
        f"\toffset := ^{ct}(0)\n"
        f"\tif index <= offset/{align_const} {{\n\t\toffset = index * {align_const}\n\t}}\n"
        "\t_w := _s.Walk()\n"
        "\tfor {\n"
        "\t\t_index, _at := _w._index, _w._at\n"
        f"\t\tif uint64(_at) > uint64(offset) {{\n\t\t\treturn nil, {not_a_start}\n\t\t}}\n"
        "\t\t_r, _ok := _w.Next()\n"
        "\t\tif !_ok {\n"
        "\t\t\tif _w._err != nil {\n\t\t\t\treturn nil, _w._err\n\t\t\t}\n"
        f"\t\t\treturn nil, {not_a_start}\n"
        "\t\t}\n"
        "\t\tif uint64(_at) == uint64(offset) {\n\t\t\treturn _r, nil\n\t\t}\n"
        "\t}\n"
        "}\n\n"
        f"// _member is the record _index at byte _at and its size, where the walk admits it; nil and nil where"
        " the walk has met the count at the extent; else nil and the refusal.\n"
        f"func (_s {seq}) _member(_index {ct}, _at int) ({record}, int, *{_UNION_ERROR}) {{\n"
        "\t_left := len(_s._bytes) - _at\n"
        f"\t_clause := {_union_clause('count_not_met')}\n"
        "\tswitch {\n"
        "\tcase _index == _s._count && _left == 0:\n\t\treturn nil, 0, nil\n"
        f"\tcase _index < _s._count && _left >= {head_size}:\n"
        f"\t\t_head := (*{head})(unsafe.Pointer(&_s._bytes[_at]))\n"
        "\t\t_size := 0\n"
        f"\t\tswitch _head.{tag} {{\n{sizes}\t\t}}\n"
        "\t\tswitch {\n"
        f"\t\tcase _size == 0:\n\t\t\t_clause = {_union_clause('unknown_tag')}\n"
        f"\t\tcase int(_head.{length}) != _size:\n\t\t\t_clause = {_union_clause('size_not_the_members')}\n"
        f"\t\tcase _left < _size:\n\t\t\t_clause = {_union_clause('record_past_extent')}\n"
        f"{casts}"
        "\t\t}\n"
        f"\tcase _index < _s._count && _left > 0:\n\t\t_clause = {_union_clause('header_past_extent')}\n"
        "\t}\n"
        f"\treturn nil, 0, {refused('_at', '_clause')}\n"
        "}\n\n"
        f"// {walker} walks a {seq}: Next answers each record in order until the walk meets the count or refuses"
        " a record, and Err then says which.\n"
        f"type {walker} struct {{\n\t_s {seq}\n\t_index {ct}\n\t_at int\n\t_err *{_UNION_ERROR}\n\t_done bool\n}}\n\n"
        "// Next is the next record and true, or nil and false once the walk has ended, at the count or at a"
        " record it refused.\n"
        f"func (_w *{walker}) Next() ({record}, bool) {{\n"
        "\tif _w._done {\n\t\treturn nil, false\n\t}\n"
        "\t_r, _size, _err := _w._s._member(_w._index, _w._at)\n"
        "\tif _r == nil {\n\t\t_w._done, _w._err = true, _err\n\t\treturn nil, false\n\t}\n"
        "\t_w._index++\n\t_w._at += _size\n"
        "\treturn _r, true\n"
        "}\n\n"
        f"// Err is the *{_UNION_ERROR} the walk ended at, or nil while it runs and where it met the count at the"
        " extent.\n"
        f"func (_w *{walker}) Err() error {{\n"
        "\tif _w._err == nil {\n\t\treturn nil\n\t}\n"
        "\treturn _w._err\n"
        "}\n"
    )


_FILLED_TEXT = f"""// {naming.FILLED} is how much of a caller's buffer a call wrote and how much its whole result
// needs, in elements (bytes for a byte buffer): Wrote < Needed means the buffer was too short
// for the whole result.
type {naming.FILLED} struct {{
    Wrote  int
    Needed int
}}

// _filled is the reports of a buffer of _count elements as a {naming.FILLED}, a library reporting
// more written than the buffer holds or the result needs, or a need int cannot hold, panicking.
func _filled(_wrote, _needed, _count uint64, _function, _buffer string) {naming.FILLED} {{
    if _wrote > _count || _wrote > _needed {{
        panic(_function + " over-reported " + _buffer + ": it wrote more than the buffer holds or than the result needs")
    }}
    if _needed > uint64(^uint(0)>>1) {{
        panic(_function + " reported a size of " + _buffer + " int cannot hold")
    }}
    return {naming.FILLED}{{Wrote: int(_wrote), Needed: int(_needed)}}
}}
"""

_DATA_TEXT = """// _empty is what an empty buffer's pointer points at, so a present buffer is never NULL: aligned
// for every element type a definition has.
var _empty uint64

// _data is the address of a slice's first element, or of _empty for an empty slice.
func _data[T any](_s []T) unsafe.Pointer {
    if len(_s) == 0 {
        return unsafe.Pointer(&_empty)
    }
    return unsafe.Pointer(&_s[0])
}

// _data_or_nil is _data, or NULL for a nil slice: an optional buffer the caller left absent.
func _data_or_nil[T any](_s []T) unsafe.Pointer {
    if _s == nil {
        return nil
    }
    return _data(_s)
}
"""

_CALLBACK_TEXT = f"""// {_FAILURE_TYPE} is what failed during one driving call, shared by all its callbacks: whether
// any did, and the first panic's value, which the call panics with again once the library returns.
type {_FAILURE_TYPE} struct {{
    _failed bool
    _value  any
}}

func (_r *{_FAILURE_TYPE}) _record(_value any) {{
    if !_r._failed {{
        _r._failed, _r._value = true, _value
    }}
}}

// {_FRAME_TYPE} is a func a driving call passes the library as a callback, for that call: the C
// function it drives, whether an invocation of it is running, and the call's failure record. The
// library receives a cgo.Handle of it, by address, as user_data.
type {_FRAME_TYPE}[F any] struct {{
    _fn       F
    _function string
    _running  bool
    _failure  *{_FAILURE_TYPE}
}}
"""

_NO_COPY_TEXT = """// _noCopy makes go vet's copylocks check report a copy of the class holding it.
type _noCopy struct{}

func (*_noCopy) Lock()   {}
func (*_noCopy) Unlock() {}
"""


def _callback_type(api: Api, heading: str | None, callback: Function) -> str:
    params = []
    for p in callback.params:
        if p.type == "memory":
            params.append(f"{p.name} []byte")
        elif p.is_union:
            params.append(f"{p.name} {_union_types(api.union(p.type))[0]}")
        elif p.is_buffer:
            params.append(f"{p.name} []{_go_type(api, p.type)}")
        else:
            params.append(f"{p.name} {_go_type(api, p.type)}")
    name = naming.go_exported(callback.name)
    rules = [
        f"A func of type {name} is called only during the call it is passed to, on that call's thread,",
        "and never again once it returns. Each slice it receives is the library's memory, valid only",
        "until it returns: keep indices into it, never the slice. Each slice is read-only: writing",
        "through one, or appending to a slice that shares its memory, is a consumer error the library",
        "cannot detect. A panic in it stops the call, which panics with the same value once the",
        "library returns; runtime.Goexit in it, as testing's FailNow, crashes the process.",
    ]
    docs = _doc_lines(callback.docs(), heading=heading)
    return (
        docs
        + ("//\n" if docs else "")
        + _doc_lines(rules)
        + f"type {name} func({', '.join(params)}) {naming.go_exported(callback.returns)}\n"
    )


def _trampoline(api: Api, callback: Function) -> str:
    """The `//export` function the library calls as the callback type, every statement under
    one deferred recover: it reads the frame its `user_data` holds, a `user_data` that is no
    frame of this callback type ending the process with exit status 2; answers the stop entry
    where the call's failure is recorded or an invocation of the frame runs, recording the
    latter; and otherwise calls the frame's func, a panic recorded and answered stop."""
    symbol = naming.go_export_symbol(api.namespace, callback.name)
    c_type = naming.type_name(api.namespace, callback.name)
    c_params = c.callback_params(api, callback)
    params = ", ".join(f"_a{i} {_cgo_spelling(t)}" for i, (t, _) in enumerate(c_params))
    returns = _cgo_type(api, callback.returns)
    stop_entry = api.stop_entry(callback)
    stop = c.int_literal(stop_entry.value, stop_entry.format)
    checks, args = [], []
    i = 0
    for p in callback.params:
        if p.type == "memory":
            args.append(f"unsafe.Slice((*byte)(_a{i}), _a{i + 1})")
        elif p.is_union:
            union = api.union(p.type)
            pointer, count, extent = (f"_a{i + k}" for k in range(3))
            checks.append(
                f"\tif ({pointer} == nil && ({count} != 0 || {extent} != 0)) ||"
                f" uintptr(unsafe.Pointer({pointer}))%unsafe.Alignof({naming.go_exported(union.prefix)}{{}}) != 0 {{\n"
                f'\t\tpanic("{c_type} received view {p.name} outside the definition")\n\t}}\n'
                f"\t_v{i} := {_union_types(union)[0]}{{_bytes: unsafe.Slice((*byte)(unsafe.Pointer({pointer})),"
                f" {extent}), _count: {_GO_TYPES[union.count_type]}({count})}}\n"
            )
            args.append(f"_v{i}")
        elif p.is_buffer:
            args.append(f"unsafe.Slice((*{_go_type(api, p.type)})(unsafe.Pointer(_a{i})), _a{i + 1})")
        elif api.kind(p.type) == "enum":
            enum_c = naming.type_name(api.namespace, p.type)
            checks.append(
                f"\t_v{i} := {_go_type(api, p.type)}(_a{i})\n"
                f"\tif !_v{i}._named() {{\n"
                f'\t\tpanic("{c_type} received a {p.name} value {enum_c} does not name")\n\t}}\n'
            )
            args.append(f"_v{i}")
        else:
            args.append(f"{_go_type(api, p.type)}(_a{i})")
        i += 1 + len(p.derived_names())
    user_data = len(c_params) - 1
    frame = f"*{_FRAME_TYPE}[{naming.go_exported(callback.name)}]"
    return (
        f"//export {symbol}\n"
        f"func {symbol}({params}) (_answer {returns}) {{\n"
        f"\t_answer = {stop}\n"
        f"\tvar _f {frame}\n"
        "\t_entered, _returned := false, false\n"
        "\tdefer func() {\n"
        "\t\tif _entered {\n\t\t\t_f._running = false\n\t\t}\n"
        "\t\tif _returned {\n\t\t\treturn\n\t\t}\n"
        "\t\t_v := recover()\n"
        "\t\tif _f == nil {\n"
        f'\t\t\tprintln("{c_type} received a user_data no driving call of it made")\n'
        "\t\t\t_os.Exit(2)\n"
        "\t\t}\n"
        "\t\t_f._failure._record(_v)\n"
        f"\t\t_answer = {stop}\n"
        "\t}()\n"
        f"\t_f = (*(*_cgo.Handle)(_a{user_data})).Value().({frame})\n"
        f"\tif _f._failure._failed {{\n\t\t_returned = true\n\t\treturn {stop}\n\t}}\n"
        "\tif _f._running {\n"
        f'\t\t_f._failure._record("{c_type} called again while a call of it was running in " + _f._function)\n'
        f"\t\t_returned = true\n\t\treturn {stop}\n\t}}\n"
        "\t_f._running, _entered = true, true\n"
        + "".join(checks)
        + f"\t_answer = {returns}(_f._fn({', '.join(args)}))\n"
        "\t_returned = true\n"
        f"\tif _f._failure._failed {{\n\t\t_answer = {stop}\n\t}}\n"
        "\treturn _answer\n"
        "}\n"
    )


@dataclass
class _Marshalled:
    """A function's parameters as the package renders them around one C call."""

    params: list[str] = field(default_factory=list)  # the Go signature's `name type`
    outs: list[tuple[str, str]] = field(default_factory=list)  # (Go type, local) of each result but the error
    checks: list[str] = field(default_factory=list)  # refusals of the caller's misuse, before anything else
    before: list[str] = field(default_factory=list)  # statements preparing the call's arguments
    handles: list[str] = field(default_factory=list)  # each callback's frame handle, made right before the call
    args: list[str] = field(default_factory=list)  # the C call's arguments, in order
    cleanup: list[str] = field(default_factory=list)  # the deferred statements undoing `handles` on every path
    released: list[str] = field(default_factory=list)  # statements right after the call
    after: list[str] = field(default_factory=list)  # statements after a successful result


def _marshal(api: Api, fn: Function, params: tuple[Param, ...], *, ctx: str, ctor: bool) -> _Marshalled:
    """`params` of `fn` as Go parameters and results around the C call, `ctx` naming the Go
    function in a refusal of the caller's misuse. Every handle the call passes is refused
    before anything else where it cannot be passed: a nil, released or driving object, or a
    null raw handle."""
    m = _Marshalled()
    shapes = {shape.opaque.name: shape for shape in api.classes()}
    objects = []  # (where in m.checks, parameter) of each object argument, whose refusals name the results
    for p in params:
        kind = api.kind(p.type)
        if p.callback:
            _marshal_callback(api, fn, p, ctx=ctx, into=m)
        elif p.is_buffer:
            _marshal_buffer(api, fn, p, into=m)
        elif kind == "opaque" and p.type in shapes and p.ref in (None, "in"):
            objects.append((len(m.checks), p))
            m.params.append(f"{p.name} *{naming.go_exported(shapes[p.type].opaque.class_name)}")
            if p.ref is None:
                m.args.append(f"{p.name}._handle")
            elif p.optional:
                local = f"_l_{p.name}"
                m.before.append(
                    f"\tvar {local} *{_cgo_type(api, p.type)}\n\tif {p.name} != nil {{\n\t\t{local} = &{p.name}._handle\n\t}}\n"
                )
                m.args.append(local)
            else:
                m.args.append(f"&{p.name}._handle")
        elif p.ref is None:
            m.params.append(f"{p.name} {_go_type(api, p.type)}")
            if kind == "opaque":
                m.checks.append(_null_handle_check(p.name, p.type, ctx=ctx))
                m.args.append(f"{p.name}._h")
            elif kind in ("builtin", "enum"):
                m.args.append(f"{_cgo_type(api, p.type)}({p.name})")
            else:
                m.args.append(f"*(*{_cgo_type(api, p.type)})(unsafe.Pointer(&{p.name}))")
        elif p.ref == "out" and (ctor or not p.optional):
            local = f"_o_{p.name}"
            m.outs.append((_go_type(api, p.type), local))
            m.args.append(f"(*{_cgo_type(api, p.type)})(unsafe.Pointer(&{local}))")
            if kind == "enum":
                m.after.append(_enum_written(api, fn, p, local))
        else:
            pointer = p.ref != "in" or p.optional
            m.params.append(f"{p.name} {'*' if pointer else ''}{_go_type(api, p.type)}")
            if p.ref == "inout" and not p.optional:
                m.checks.append(f'\tif {p.name} == nil {{\n\t\tpanic("{ctx}: {p.name} is nil")\n\t}}\n')
            if kind == "opaque" and p.ref != "out":
                check = _null_handle_check(f"(*{p.name})" if pointer else p.name, p.type, ctx=ctx, name=p.name)
                m.checks.append(f"\tif {p.name} != nil {{\n{_indent(check)}\t}}\n" if p.optional else check)
            m.args.append(f"(*{_cgo_type(api, p.type)})(unsafe.Pointer({'' if pointer else '&'}{p.name}))")
            if kind == "enum" and p.ref != "in":
                check = _enum_written(api, fn, p, f"(*{p.name})")
                m.after.append(check if not p.optional else f"\tif {p.name} != nil {{\n{_indent(check)}\t}}\n")
    failed = ["nil"] if ctor else [local for _, local in m.outs]
    for at, p in reversed(objects):
        m.checks.insert(at, _object_checks(api, fn, p, shapes[p.type], ctx=ctx, failed=failed))
    if m.handles:
        m.before.insert(0, f"\tvar {_FAILURE} {_FAILURE_TYPE}\n")
        m.released.append(f"\tif {_FAILURE}._failed {{\n\t\tpanic({_FAILURE}._value)\n\t}}\n")
    return m


def _null_handle_check(value: str, opaque: str, *, ctx: str, name: str | None = None) -> str:
    """The refusal of a raw handle `value`, parameter `name` (by default `value` itself), that
    is null: the library is never handed one the binding can see."""
    return (
        f"\tif {value}._h == nil {{\n"
        f'\t\tpanic("{ctx}: {name or value} is a null {naming.handle_type(opaque)}")\n\t}}\n'
    )


def _object_checks(api: Api, fn: Function, p: Param, shape: ClassShape, *, ctx: str, failed: list[str]) -> str:
    """The refusals of object argument `p` of class `shape`: nil, but where `_optional`;
    released; and where its class drives a callback, in a driving call, answered as the
    receiver's in-call guard answers, `failed` the results listed before the entry."""
    cls = naming.go_exported(shape.opaque.class_name)
    reason = f"used after {shape.dtor.name}" if shape.dtor is not None else "with no handle"
    checks = f'\tif {p.name}._handle == nil {{\n\t\tpanic("{ctx}: {p.name} is a {cls} {reason}")\n\t}}\n'
    if shape.drives():
        entry = api.first_nonzero_entry(fn)
        if entry is not None:
            refused = f"return {', '.join([*failed, naming.go_enum_entry(fn.returns, entry.name)])}"
        else:
            refused = f'panic("{ctx}: {p.name} is a {cls} while " + {p.name}.{_IN_CALL} + " is in progress on it")'
        checks += f'\tif {p.name}.{_IN_CALL} != "" {{\n\t\t{refused}\n\t}}\n'
    if p.optional:
        return f"\tif {p.name} != nil {{\n{_indent(checks)}\t}}\n"
    return f'\tif {p.name} == nil {{\n\t\tpanic("{ctx}: {p.name} is nil")\n\t}}\n' + checks


def _indent(text: str) -> str:
    return "".join(f"\t{line}\n" for line in text.splitlines())


def _enum_written(api: Api, fn: Function, p: Param, value: str) -> str:
    fname = naming.function_name(api.namespace, fn.name)
    enum_c = naming.type_name(api.namespace, p.type)
    return f'\tif !{value}._named() {{\n\t\tpanic("{fname} wrote a {p.name} value {enum_c} does not name")\n\t}}\n'


def _marshal_callback(api: Api, fn: Function, p: Param, *, ctx: str, into: _Marshalled) -> None:
    """A callback parameter: a func, nil refused; for the call, a frame of it under a cgo.Handle
    whose address is the `user_data`, deleted on every path once the call is made."""
    fname = naming.function_name(api.namespace, fn.name)
    handle = f"_h_{p.name}"
    cb_type = naming.go_exported(p.type)
    into.params.append(f"{p.name} {cb_type}")
    into.checks.append(f'\tif {p.name} == nil {{\n\t\tpanic("{ctx}: {p.name} is nil")\n\t}}\n')
    into.handles.append(
        f'\t{handle} := _cgo.NewHandle(&{_FRAME_TYPE}[{cb_type}]{{_fn: {p.name}, _function: "{fname}", '
        f"_failure: &{_FAILURE}}})\n"
    )
    into.args += [
        f"{_cgo_type(api, p.type)}(C.{naming.go_export_symbol(api.namespace, p.type)})",
        f"unsafe.Pointer(&{handle})",
    ]
    into.cleanup.append(f"\t\t{handle}.Delete()\n")


def _marshal_buffer(api: Api, fn: Function, p: Param, *, into: _Marshalled) -> None:
    """A buffer as a slice of bytes or of its element, its count the slice's length, a length the
    count type cannot hold panicking; a present buffer's pointer never NULL. Each report is a
    local of the count type the call writes, checked after a successful call and returned as a
    `Filled`. A union's list is the sequence a callback received, passed as its pointer, count
    and extent, uncopied; for an `_optional` one the zero sequence passes null."""
    if p.is_union:
        union = api.union(p.type)
        count_type = f"C.{naming.BUILTIN_C_TYPES[p.count_type]}"
        data = f"_data_or_nil({p.name}._bytes)" if p.optional else f"_data({p.name}._bytes)"
        into.params.append(f"{p.name} {_union_types(union)[0]}")
        into.args += [
            f"(*{_cgo_type(api, union.prefix)})({data})",
            f"{count_type}({p.name}._count)",
            f"{count_type}(len({p.name}._bytes))",
        ]
        return
    element = "byte" if p.type == "memory" else _go_type(api, p.type)
    into.params.append(f"{p.name} []{element}")
    bits = model.COUNT_BITS[p.count_type]
    if bits < 64:  # a Go length is below 2**63, which u64 holds
        into.checks.append(
            f"\tif uint64(len({p.name})) > {2**bits - 1} {{\n"
            f'\t\tpanic("{p.name} is longer than {p.count_type} can count")\n\t}}\n'
        )
    data = f"_data_or_nil({p.name})" if p.optional else f"_data({p.name})"
    into.args.append(data if p.type == "memory" else f"(*{_cgo_type(api, p.type)})({data})")
    count_type = f"C.{naming.BUILTIN_C_TYPES[p.count_type]}"
    into.args.append(f"{count_type}(len({p.name}))")
    reports = p.report_names()
    if not reports:
        return
    wrote, needed = (f"_w_{p.name}", f"_n_{p.name}")
    into.before.append(f"\tvar {wrote}, {needed} {count_type}\n")
    into.args += [f"&{wrote}", f"&{needed}"]
    local = f"_f_{p.name}"
    into.outs.append((naming.FILLED, local))
    fname = naming.function_name(api.namespace, fn.name)
    into.after.append(
        f'\t{local} = _filled(uint64({wrote}), uint64({needed}), uint64(len({p.name})), "{fname}", "{p.name}")\n'
    )


def _signature_results(outs: list[tuple[str, str]], *, first: str | None = None) -> str:
    types = [*([first] if first else []), *(t for t, _ in outs), "error"]
    return types[0] if len(types) == 1 else f"({', '.join(types)})"


def _call_body(
    api: Api,
    fn: Function,
    m: _Marshalled,
    *,
    receiver_args: list[str],
    guards: list[str],
    failed: list[str],
    ok: list[str],
    drives: bool,
    destroy_on_panic: str | None = None,
) -> str:
    """A function body: the result locals, `guards`, the caller-misuse checks, the argument
    preparation, the handles and in-call state with their deferred undoing, the call, the
    result checked, the reports and written enums checked, then `ok`'s results and nil.
    `failed` is what every other return lists before its error. `destroy_on_panic`, a
    constructor's, releases the handle the call made where a check after it panics."""
    fname = naming.function_name(api.namespace, fn.name)
    enum = naming.go_exported(fn.returns)
    unnamed = f"{fname} returned a value {naming.type_name(api.namespace, fn.returns)} does not name"
    success = naming.go_enum_entry(fn.returns, api.success_entry(fn).name)
    declarations = [f"\tvar {local} {t}\n" for t, local in m.outs]
    failure_return = ", ".join([*failed, "_result"])
    cleanup = [*([f'\t\t{_SELF}.{_IN_CALL} = ""\n'] if drives else []), *m.cleanup]
    destroy = (
        [
            f"\tdefer func() {{\n\t\tif _v := recover(); _v != nil {{\n\t\t\t{destroy_on_panic}\n\t\t\tpanic(_v)\n\t\t}}\n\t}}()\n"
        ]
        if destroy_on_panic is not None and m.after
        else []
    )
    lines = [
        *declarations,
        *guards,
        *m.checks,
        *m.before,
        *m.handles,
        *([f'\t{_SELF}.{_IN_CALL} = "{fname}"\n'] if drives else []),
        *([f"\tdefer func() {{\n{''.join(cleanup)}\t}}()\n"] if cleanup else []),
        f"\t_raw := C.{fname}({', '.join([*receiver_args, *m.args])})\n",
        *m.released,
        f"\t_result := {enum}(_raw)\n",
        f'\tif !_result._named() {{\n\t\tpanic("{unnamed}")\n\t}}\n',
        f"\tif _result != {success} {{\n\t\treturn {failure_return}\n\t}}\n",
        *destroy,
        *m.after,
        f"\treturn {', '.join([*ok, 'nil'])}\n",
    ]
    return "".join(lines)


def _in_call_guard(api: Api, fn: Function, *, cls: str, method: str, failed: list[str]) -> str:
    """The refusal of a method while a call of the object drives a callback: the first non-zero
    entry of its return enum as its error, or where that enum has none a panic naming the class,
    the method and the driving C function."""
    entry = api.first_nonzero_entry(fn)
    if entry is not None:
        refused = ", ".join([*failed, naming.go_enum_entry(fn.returns, entry.name)])
        return f'\tif {_SELF}.{_IN_CALL} != "" {{\n\t\treturn {refused}\n\t}}\n'
    return (
        f'\tif {_SELF}.{_IN_CALL} != "" {{\n'
        f'\t\tpanic("{cls}.{method} called while " + {_SELF}.{_IN_CALL} + " is in progress on this {cls}")\n\t}}\n'
    )


def _class(api: Api, shape: ClassShape, *, heading: str | None) -> str:
    """The class: a struct holding the handle, the in-call state where a method drives a
    callback, and each other `out` of the ctor; its constructor, `Handle`, an accessor per
    cached `out`, a method per member function and with a dtor `Release`, after which every
    method panics naming the dtor. Holding a `_noCopy`, a copy of one is what go vet reports."""
    cls = naming.go_exported(shape.opaque.class_name)
    handle_type = _cgo_type(api, shape.opaque.name)
    headings = {fn.name: h for h, fn in headed(api.function_groups, shape.functions())}
    drives = shape.drives()
    fields = ["\t_nocopy _noCopy\n", f"\t_handle {handle_type}\n", *([f"\t{_IN_CALL} string\n"] if drives else [])]
    fields += [f"\t_cached_{p.name} {_go_type(api, p.type)}\n" for p in shape.cached]
    rules = f"// A {cls} is not safe for concurrent use, and must not be copied: pass *{cls}; go vet reports a copy."
    if shape.dtor is not None:
        rules += " Its methods panic once it is released, and Handle's value is the library's only until then."
    out = [
        _comment(heading)
        + _comment(shape.opaque.docstring)
        + f"{rules}\n"
        + f"type {cls} struct {{\n{''.join(fields)}}}\n"
    ]

    ctor = shape.ctor
    ctor_name = naming.go_constructor(shape.opaque.class_name)
    m = _marshal(api, ctor, ctor.params, ctx=ctor_name, ctor=True)
    values = [f"_handle: _o_{shape.handle.name}._h", *(f"_cached_{p.name}: _o_{p.name}" for p in shape.cached)]
    destroy = (
        None
        if shape.dtor is None
        else f"C.{naming.function_name(api.namespace, shape.dtor.name)}(_o_{shape.handle.name}._h)"
    )
    body = _call_body(
        api,
        ctor,
        m,
        receiver_args=[],
        guards=[],
        failed=["nil"],
        ok=[f"&{cls}{{{', '.join(values)}}}"],
        drives=False,
        destroy_on_panic=destroy,
    )
    out.append(
        "\n"
        + _doc_lines(ctor.docs(), heading=headings[ctor.name])
        + f"func {ctor_name}({', '.join(m.params)}) (*{cls}, error) {{\n{body}}}\n"
    )
    out.append(
        f"\n// Handle is the object's raw handle.\nfunc ({_SELF} *{cls}) Handle() {naming.handle_type(shape.opaque.name)} {{\n"
        f"\treturn {naming.handle_type(shape.opaque.name)}{{{_SELF}._handle}}\n}}\n"
    )
    out += [
        f"\nfunc ({_SELF} *{cls}) {naming.go_exported(p.name)}() {_go_type(api, p.type)} {{\n"
        f"\treturn {_SELF}._cached_{p.name}\n}}\n"
        for p in shape.cached
    ]
    reason = f"used after {shape.dtor.name}" if shape.dtor is not None else "has no handle"
    live = f'\tif {_SELF}._handle == nil {{\n\t\tpanic("{cls} {reason}")\n\t}}\n'
    for fn in shape.methods:
        method = naming.go_exported(fn.name)
        m = _marshal(api, fn, fn.params[1:], ctx=f"{cls}.{method}", ctor=False)
        failed = [local for _, local in m.outs]
        guards = [live, *([_in_call_guard(api, fn, cls=cls, method=method, failed=failed)] if drives else [])]
        body = _call_body(
            api,
            fn,
            m,
            receiver_args=[f"{_SELF}._handle"],
            guards=guards,
            failed=failed,
            ok=failed,
            drives=any(p.callback for p in fn.params),
        )
        out.append(
            "\n"
            + _doc_lines(fn.docs(), heading=headings[fn.name])
            + f"func ({_SELF} *{cls}) {method}({', '.join(m.params)}) {_signature_results(m.outs)} {{\n{body}}}\n"
        )
    if shape.dtor is not None:
        dtor = shape.dtor
        guards = [_in_call_guard(api, dtor, cls=cls, method="Release", failed=[])] if drives else []
        m = _Marshalled(released=[f"\t{_SELF}._handle = nil\n"])  # a second release passes the null handle
        body = _call_body(
            api, dtor, m, receiver_args=[f"{_SELF}._handle"], guards=guards, failed=[], ok=[], drives=False
        )
        out.append(
            "\n"
            + _doc_lines(dtor.docs(), heading=headings[dtor.name])
            + f"func ({_SELF} *{cls}) Release() error {{\n{body}}}\n"
        )
    return "".join(out)


def _function(api: Api, fn: Function, *, heading: str | None) -> str:
    """A function no class renders, as a package function."""
    name = naming.go_exported(fn.name)
    m = _marshal(api, fn, fn.params, ctx=name, ctor=False)
    failed = [local for _, local in m.outs]
    body = _call_body(api, fn, m, receiver_args=[], guards=[], failed=failed, ok=failed, drives=False)
    return (
        _doc_lines(fn.docs(), heading=heading)
        + f"func {name}({', '.join(m.params)}) {_signature_results(m.outs)} {{\n{body}}}\n"
    )
