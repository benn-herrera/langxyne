"""C language facts every emitter shares: the keywords, the spelling of a definition's
types and literals, and the declaration text the header and the Lua module's ffi.cdef both
render."""

from langxyne import naming
from langxyne.model import (
    Api,
    BitConst,
    BoxedScalar,
    EnumEntry,
    Function,
    Group,
    LiteralTerm,
    OpaqueRef,
    Param,
    Struct,
    Term,
    TypedConst,
    Union,
    generated_name_objections,
    headed,
    named_values,
    single_bit_entries,
)

C_KEYWORDS = frozenset(
    "auto break case char const continue default do double else enum extern float for goto if "
    "inline int long register restrict return short signed sizeof static struct switch typedef "
    "union unsigned void volatile while".split()
)
_USER_DATA_TYPE = "void*"


def c_type(api: Api, type_name: str) -> str:
    """C spelling of a definition type used by value."""
    if type_name in naming.BUILTIN_C_TYPES:
        return naming.BUILTIN_C_TYPES[type_name]
    return naming.type_name(api.namespace, type_name)


def int_literal(value: int, fmt: str) -> str:
    """An integer spelled as a Lua number, a Rust literal with its sign in front, and a C
    literal when non-negative: decimal, or lower-case unpadded hex."""
    if fmt == "hex":
        return f"-0x{-value:x}" if value < 0 else f"0x{value:x}"
    return str(value)


def typed_literal(value: int, fmt: str, base_type: str) -> str:
    """`value` as a C constant expression of `base_type`: the type's `<stdint.h>` macro
    around a non-negative literal spelled per `fmt`, the sign outside the macro. A
    negative literal would be the negation of a literal typed on its own, unsigned for
    hex beyond the signed maximum and wider than the type for the decimal minimum; the
    type's minimum, whose magnitude the type cannot hold, is the negated maximum less one."""
    base = naming.BASE_C_TYPES[base_type]
    if value >= 0:
        return f"{base.const_macro}({int_literal(value, fmt)})"
    if value == base.min_value:
        return f"(-{base.const_macro}({int_literal(base.max_value, fmt)}) - 1)"
    return f"(-{base.const_macro}({int_literal(-value, fmt)}))"


def c_params(api: Api, param: Param) -> list[tuple[str, str]]:
    """(C type, name) of each C parameter a definition parameter becomes: a buffer is the
    pointer, its count, and a pointer to each report of the count's type; a union's list the
    pointer, its count and its byte extent, both of the count's type; a callback the function
    pointer and its `user_data`; every other parameter itself."""
    params = [(param_type(api, param), param.name)]
    if param.is_buffer:
        count_type = naming.BUILTIN_C_TYPES[param.count_type]
        params.append((count_type, param.count_name()))
        if param.is_union:
            params.append((count_type, param.bytes_name()))
        params += [(f"{count_type}*", report) for report in param.report_names()]
    if param.callback:
        params.append((_USER_DATA_TYPE, param.user_data_name()))
    return params


def callback_params(api: Api, callback: Function) -> list[tuple[str, str]]:
    """(C type, name) of each parameter of `callback`'s C type: each of its parameters'
    `c_params()`, then its own `user_data`."""
    return [*(pair for p in callback.params for pair in c_params(api, p)), (_USER_DATA_TYPE, naming.USER_DATA)]


def param_list(api: Api, fn: Function) -> str:
    """A function's C parameter list text, `void` for none: every parameter's `c_params()`
    pairs, joined in signature order. The one join the header's declaration and the
    stub's definition both use, so their signatures can never drift apart."""
    return ", ".join(f"{t} {n}" for p in fn.params for t, n in c_params(api, p)) or "void"


def param_type(api: Api, param: Param) -> str:
    """C spelling of a parameter: `c_type()` by value, a pointer to it through `_ref`
    (`const` for `in`), so an array is a pointer to its element and a union's list a pointer to
    its prefix, and a `void` pointer for `memory`."""
    if param.type == "memory":
        return "const void*" if param.ref == "in" else "void*"
    if param.is_union:
        return f"const {c_type(api, api.union(param.type).prefix)}*"
    base = c_type(api, param.type)
    if param.ref == "in":
        return f"const {base}*"
    if param.ref is not None:
        return f"{base}*"
    return base


def type_names(api: Api) -> set[str]:
    """Every type name the declarations spell: the fixed-width types and the typedefs, the
    text type's where some field is text, and the callback types'."""
    typedefs = [t.name for t in (*api.typed_consts, *api.opaque_refs, *api.boxed_scalars, *api.structs)]
    if api.uses_text():
        typedefs.append(naming.TEXT)
    typedefs += [c.name for c in api.callbacks]
    return {*naming.BUILTIN_C_TYPES.values(), *(naming.type_name(api.namespace, t) for t in typedefs)}


def parameter_type_objections(api: Api) -> list[str]:
    """A parameter of a function or a callback type, or a buffer's count or report or a
    callback's `user_data`, named like one of `type_names()`: in a prototype the name hides
    that type from every parameter after it."""
    params = (
        (f"{kind}.{fn.name}.{p.name}", name)
        for kind, signatures in (("callback", api.callbacks), ("function", api.functions))
        for fn in signatures
        for p in fn.params
        for name in (p.name, *p.derived_names())
    )
    return generated_name_objections(params, type_names(api))


def header_macros(namespace: str) -> frozenset[str]:
    """Every macro the header defines or tests for itself, beside one per constant."""
    return frozenset(
        {
            naming.c_api_macro(namespace),
            naming.api_macro(namespace),
            naming.impl_macro(namespace),
            naming.version_const(namespace),
        }
    )


def declarations(api: Api, *, function_prefix: str, header: bool = True) -> str:
    """The header's declarations in its order, each function after `function_prefix`
    (`NS_API ` in the header): with `header`, the version, the bit, plain, enum and string
    constants, each group or enum with `_to_string` followed by its conversion, a group's after
    the blank line ending its run, then the opaque
    refs, boxed scalars, structs, with `header` the lists of the unions declaring `_mixed_type_list`, then callback types and functions, a named kind's
    group docstring a comment line above the first of the group's items."""
    ns = api.namespace
    blocks = []
    if header:
        version = f"{naming.BASE_C_TYPES['u32'].const_macro}(0x{api.version_value():08x})"
        blocks.append(_define(naming.version_const(ns), version, None))
        for g in api.bit_const_groups:
            blocks.append(_constant_group(api, g, operator="|"))
            if g.to_string is not None:
                blocks.append(_bit_to_string(api, g))
        for g in api.const_groups:
            blocks.append(_constant_group(api, g, operator="+"))
            if g.to_string is not None:
                blocks.append(_plain_to_string(api, g))
        blocks += [
            comment_line(h) + _typed_enum(api, t) + _enum_to_string(api, t) for h, t in headed(api.typed_const_groups)
        ]
        blocks += [
            comment_line(g.docstring)
            + "".join(
                f'static const char {naming.const_name(ns, c.name)}[] = "{c.value}";{_trailing(c.docstring)}\n'
                for c in g.entries
            )
            for g in api.string_const_groups
        ]
    blocks += [comment_line(h) + _opaque(api, o) for h, o in headed(api.opaque_ref_groups)]
    # before the structs, so a struct may hold one
    blocks += [comment_line(h) + _boxed(api, b) for h, b in headed(api.boxed_scalar_groups)]
    if api.uses_text():
        blocks.append(_text(api))
    blocks += [comment_line(h) + _struct(api, s) for h, s in headed(api.struct_groups)]
    if header and api.listed_unions():
        blocks.append(_typed_enum(api, union_clause_enum(api)) + _union_clause_text(api))
        blocks += [comment_line(h) + _union_list(api, u) for h, u in headed(api.union_groups, api.listed_unions())]
    blocks += [comment_line(h) + _callback(api, cb) for h, cb in headed(api.callback_groups)]
    if api.functions:
        blocks.append(
            "".join(comment_line(h) + _function(api, f, function_prefix) for h, f in headed(api.function_groups))
        )
    return "\n".join(blocks)


def binding_declarations(api: Api) -> str:
    """The C declarations a binding carries in place of the header: a typedef of its base
    type for each enum (not its body, since a binding carries constants as its own literals),
    then `declarations()` without constants or a function prefix."""
    typedefs = [
        comment_line(h)
        + f"typedef {naming.BASE_C_TYPES[t.base_type].c_type} {naming.type_name(api.namespace, t.name)};\n"
        for h, t in headed(api.typed_const_groups)
    ]
    return "\n".join([*typedefs, declarations(api, function_prefix="", header=False)])


def union_clause_enum(api: Api) -> TypedConst:
    """The clause enum, `ns_union_clause`: `NS_UNION_OK`, 0, then each of `naming.UNION_CLAUSES`
    from 1, its text its docstring."""
    ok = EnumEntry(name=naming.UNION_OK, docstring=None, value=0, format="dec")
    clauses = [
        EnumEntry(name=naming.union_clause_entry(name), docstring=text, value=value, format="dec")
        for value, (name, text) in enumerate(naming.UNION_CLAUSES, start=1)
    ]
    doc = f"why a walk of a union's list refused it; {naming.const_name(api.namespace, ok.name)} where it did not"
    return TypedConst(name=naming.UNION_CLAUSE, docstring=doc, entries=(ok, *clauses), base_type="i32", to_string=None)


def union_names(api: Api) -> list[tuple[str, str]]:
    """(union 'u', C identifier) for every name the header's lists define, the clause enum's
    and its conversion's under the first union declaring `_mixed_type_list`, then each such
    union's alignment macro and helpers."""
    listed = api.listed_unions()
    if not listed:
        return []
    ns = api.namespace
    first = f"union '{listed[0].name}'"
    clauses = union_clause_enum(api)
    names = [(first, naming.type_name(ns, clauses.name))]
    names += [(first, naming.const_name(ns, e.name)) for e in clauses.entries]
    names.append((first, naming.function_name(ns, naming.UNION_CLAUSE_TEXT)))
    for u in listed:
        names.append((f"union '{u.name}'", naming.const_name(ns, naming.union_align(u.name))))
        names += [(f"union '{u.name}'", naming.union_helper(ns, u.name, h)) for h in naming.UNION_HELPERS]
    return names


def to_string_name(api: Api, to_string: str, *, typename: str | None) -> str:
    """The C identifier of a `_to_string` conversion: `naming.flat_to_string()`'s name, an
    enum's after its type name, as a function's is prefixed."""
    return naming.function_name(api.namespace, naming.flat_to_string(to_string, typename=typename))


def to_string_names(api: Api) -> list[tuple[str, str]]:
    """(where, C identifier) of every `_to_string` conversion the header defines: each bit and
    plain group's, then each enum's."""
    groups = [
        (f"{g.name}._to_string", to_string_name(api, g.to_string, typename=None))
        for g in (*api.bit_const_groups, *api.const_groups)
        if g.to_string is not None
    ]
    return groups + [
        (f"typed_const.{t.name}._to_string", to_string_name(api, t.to_string, typename=t.name))
        for t in api.typed_consts
        if t.to_string is not None
    ]


def comment_line(doc: str | None) -> str:
    """`doc` as a `/* */` comment line, nothing for none."""
    return f"/* {doc} */\n" if doc else ""


def _trailing(doc: str | None) -> str:
    return f" /* {doc} */" if doc else ""


def _define(name: str, value: str, doc: str | None) -> str:
    return f"#define {name} {value}{_trailing(doc)}\n"


def _constant_group(api: Api, group: Group[BitConst] | Group[EnumEntry], *, operator: str) -> str:
    """A bit or plain group as one `#define` per entry under its docstring, each typed by
    the group's base type: a literal through its `<stdint.h>` macro, a single bit as that
    macro's 1 shifted, a composed entry as its terms joined by `operator`."""
    ns = api.namespace
    base = naming.BASE_C_TYPES[group.base_type]
    lines = []
    for c in group.entries:
        if c.parts:
            value = _sum(api, c.parts, operator=operator, base_type=group.base_type)
        elif isinstance(c, BitConst):
            value = f"({base.const_macro}(1) << {c.bit})"
        else:
            value = typed_literal(c.value, c.format, group.base_type)
        lines.append(_define(naming.const_name(ns, c.name), value, c.docstring))
    return comment_line(group.docstring) + "".join(lines)


def _sum(api: Api, parts: tuple[Term, ...], *, operator: str, base_type: str) -> str:
    """A composed entry's value, symbolic and parenthesised; every term is of `base_type`,
    a literal through `typed_literal()`."""
    return (
        "("
        + f" {operator} ".join(
            (
                typed_literal(p.value, p.format, base_type)
                if isinstance(p, LiteralTerm)
                else naming.const_name(api.namespace, p)
            )
            for p in parts
        )
        + ")"
    )


def _typed_enum(api: Api, typed: TypedConst) -> str:
    ns = api.namespace
    name = naming.type_name(ns, typed.name)
    entries = typed.entries

    def value(e: EnumEntry) -> str:
        return int_literal(e.value, e.format) if e.value >= 0 else typed_literal(e.value, e.format, typed.base_type)

    lines = "".join(
        f"  {naming.const_name(ns, e.name)} = {value(e)}"
        f"{',' if i < len(entries) - 1 else ''}{_trailing(e.docstring)}\n"
        for i, e in enumerate(entries)
    )
    return f"{comment_line(typed.docstring)}enum {name} {{\n{lines}}};\ntypedef enum {name} {name};\n"


def _opaque(api: Api, opaque: OpaqueRef) -> str:
    ns = api.namespace
    target = naming.opaque_struct(ns, opaque.name)
    return (
        f"{comment_line(opaque.docstring)}struct {target};\n"
        f"typedef struct {target}* {naming.type_name(ns, opaque.name)};\n"
    )


def _boxed(api: Api, boxed: BoxedScalar) -> str:
    name = naming.type_name(api.namespace, boxed.name)
    value = naming.BUILTIN_C_TYPES[boxed.base_type]
    return f"{comment_line(boxed.docstring)}typedef struct {name} {{ {value} value; }} {name};\n"


def _text(api: Api) -> str:
    name = naming.type_name(api.namespace, naming.TEXT)
    fields = " ".join(f"{naming.BUILTIN_C_TYPES[t]} {n};" for n, t in naming.TEXT_FIELDS)
    return f"typedef struct {name} {{ {fields} }} {name};\n"


def _struct(api: Api, struct: Struct) -> str:
    name = naming.type_name(api.namespace, struct.name)
    decls = [f"{c_type(api, f.type)} {f.name};" for f in struct.fields]
    width = max(len(d) for d in decls)
    lines = "".join(
        f"\t{d.ljust(width)} /* {f.docstring} */\n" if f.docstring else f"\t{d}\n" for d, f in zip(decls, struct.fields)
    )
    return f"{comment_line(struct.docstring)}struct {name} {{\n{lines}}};\ntypedef struct {name} {name};\n"


def _callback(api: Api, callback: Function) -> str:
    """A callback type as the typedef of a pointer to its function type, `user_data` last, its
    comment ending, where it has a view, with how long its views are valid."""
    params = ", ".join(f"{t} {n}" for t, n in callback_params(api, callback))
    returns = c_type(api, callback.returns)
    name = naming.type_name(api.namespace, callback.name)
    docs = callback.docs()
    if any(p.is_buffer for p in callback.params):
        docs.append("Its views are valid for that call only.")
    return f"{comment_line(' '.join(docs))}typedef {returns} (*{name})({params});\n"


def _function(api: Api, fn: Function, prefix: str) -> str:
    returns = c_type(api, fn.returns)
    name = naming.function_name(api.namespace, fn.name)
    return f"{comment_line(' '.join(fn.docs()))}{prefix}{returns} {name}({param_list(api, fn)});\n"


def _text_switch(
    doc: str, name: str, *, param_type: str, param: str = "value", cases: list[tuple[str, str]], unknown: str
) -> str:
    """A `static inline` value-to-text function under its comment, of one parameter: a `switch`
    answering each (case label, text) pair and `unknown` by default; duplicate case labels do
    not compile, so a plain group's come from `named_values()`."""
    body = "".join(f'\tcase {label}: return "{text}";\n' for label, text in cases)
    return (
        f"/* {doc} */\n"
        f"static inline const char* {name}({param_type} {param}) {{\n"
        f"\tswitch ({param}) {{\n{body}"
        f'\tdefault: return "{unknown}";\n'
        "\t}\n}\n"
    )


def _enum_to_string(api: Api, typed: TypedConst) -> str:
    """An enum's conversion, where it has `_to_string`: each entry's unprefixed name, and
    `UNKNOWN_<ENUM>` for a value no entry has."""
    if typed.to_string is None:
        return ""
    unknown = naming.unknown_value_name(typed.name)
    return _text_switch(
        f"the unprefixed name of `value`'s entry; {unknown} for a value no entry has",
        to_string_name(api, typed.to_string, typename=typed.name),
        param_type=naming.type_name(api.namespace, typed.name),
        cases=[(naming.const_name(api.namespace, e.name), naming.unprefixed_const_name(e.name)) for e in typed.entries],
        unknown=unknown,
    )


def _plain_to_string(api: Api, group: Group[EnumEntry]) -> str:
    """A plain group's conversion, where it has `_to_string`: each value's entry's unprefixed
    name, the later entry's where two share a value, and `UNKNOWN` for a value no entry has."""
    if group.to_string is None:
        return ""
    unknown = naming.unknown_value_name(None)
    return _text_switch(
        f"the unprefixed name of `value`'s entry, the later where two share it; {unknown} for a value no entry has",
        to_string_name(api, group.to_string, typename=None),
        param_type=naming.BASE_C_TYPES[group.base_type].c_type,
        cases=[
            (naming.const_name(api.namespace, e.name), naming.unprefixed_const_name(e.name))
            for e in named_values(group)
        ],
        unknown=unknown,
    )


def _bit_to_string(api: Api, group: Group[BitConst]) -> str:
    """A bit group's conversion, where it has `_to_string`, in `snprintf`'s form, since its text
    is composed: the unprefixed name of each single-bit entry present, in document order, joined
    with `|`, the bits left over as one last term of `0x` and lower-case hex, `NONE` for 0;
    at most `text_count` bytes of it written, the last a NUL where `text_count` > 0, and its
    whole length returned, the NUL excluded."""
    if group.to_string is None:
        return ""
    flags = single_bit_entries(group)
    tests = "".join(
        f"\tif ((left & (uint32_t){naming.const_name(api.namespace, e.name)}) != 0) {{\n"
        f'\t\tterms[count++] = "{naming.unprefixed_const_name(e.name)}";\n'
        f"\t\tleft &= ~(uint32_t){naming.const_name(api.namespace, e.name)};\n"
        "\t}\n"
        for e in flags
    )
    return f"""\
/* the unprefixed name of each single-bit entry `value` holds, in order, joined with |, the bits left over a last \
term of 0x and lower-case hex, {naming.NO_FLAGS} for 0: writes at most text_count bytes of it, the last a NUL where \
text_count > 0, and returns its whole length, the NUL excluded */
static inline uint32_t {to_string_name(api, group.to_string, typename=None)}\
({naming.BASE_C_TYPES[group.base_type].c_type} value, char* text, uint32_t text_count) {{
\tconst char* terms[{len(flags) + 1}];
\tchar hex[11] = "0x";
\tuint32_t left = (uint32_t)value, count = 0, length = 0, i;
\tint shift, digits = 2;
{tests}\tif (left != 0) {{
\t\tfor (shift = 28; shift >= 0; shift -= 4) {{
\t\t\tif ((left >> shift) != 0) hex[digits++] = "0123456789abcdef"[(left >> shift) & 0xf];
\t\t}}
\t\tterms[count++] = hex;
\t}}
\tif (count == 0) terms[count++] = "{naming.NO_FLAGS}";
\tfor (i = 0; i < count; i++) {{
\t\tconst char* c;
\t\tif (i > 0) {{
\t\t\tif (length + 1 < text_count) text[length] = '|';
\t\t\tlength++;
\t\t}}
\t\tfor (c = terms[i]; *c != '\\0'; c++, length++) {{
\t\t\tif (length + 1 < text_count) text[length] = *c;
\t\t}}
\t}}
\tif (text_count > 0) text[length < text_count ? length : text_count - 1] = '\\0';
\treturn length;
}}
"""


def _union_clause_text(api: Api) -> str:
    """The clause-to-text conversion, `ns_union_clause_text`: each clause's text, every binding's
    refusal's words, and `UNKNOWN_UNION_CLAUSE` for `NS_UNION_OK` or a value no clause has."""
    ns = api.namespace
    unknown = naming.unknown_value_name(naming.UNION_CLAUSE)
    return _text_switch(
        f"the text of `clause`, as every binding's refusal words it; {unknown} for "
        f"{naming.const_name(ns, naming.UNION_OK)} or a value no clause has",
        naming.function_name(ns, naming.UNION_CLAUSE_TEXT),
        param_type=naming.type_name(ns, naming.UNION_CLAUSE),
        param="clause",
        cases=[(naming.const_name(ns, naming.union_clause_entry(name)), text) for name, text in naming.UNION_CLAUSES],
        unknown=unknown,
    )


def _union_list(api: Api, union: Union) -> str:
    """A union's list under its docstring: the comment stating what a consumer relies on, the
    macro of the list's alignment, then its helpers, `static inline` in the CMSG_FIRSTHDR/CMSG_NXTHDR idiom, each count, offset and
    extent of the union's count type, each tag its constant's value and every size and the
    alignment a literal from `Api.layout()`, so the header needs nothing beyond `<stdint.h>`."""
    ns = api.namespace
    prefix = next(s for s in api.structs if s.name == union.prefix)
    head = c_type(api, prefix.name)
    tag, length = api.prefix_fields(union)
    head_size, align = api.layout(prefix.name)[0], api.list_alignment(union)
    fn = {h: naming.union_helper(ns, union.name, h) for h in naming.UNION_HELPERS}
    clause = naming.type_name(ns, naming.UNION_CLAUSE)
    ok = naming.const_name(ns, naming.UNION_OK)
    k = {name: naming.const_name(ns, naming.union_clause_entry(name)) for name, _ in naming.UNION_CLAUSES}
    null = f"(const {head}*)0"
    ct = naming.BUILTIN_C_TYPES[union.count_type]
    tags = {c.name: c for c in api.consts}
    cases = "".join(
        f"\tcase {int_literal(tags[m.tag].value, tags[m.tag].format)}: return {api.layout(m.struct)[0]};"
        f"{_trailing(f'{m.name}: {m.docstring}' if m.docstring else m.name)}\n"
        for m in union.members
    )
    return f"""\
{comment_line(union.docstring)}/* A list of {union.name}: records back to back from a pointer aligned to {align}, each a member's \
struct, which begins with {head}, its {tag.name} the member's tag and its {length.name} the record's byte length, a \
multiple of {align}, so every record's {head} is aligned; the records lie in allocated storage with no declared type, \
so a read through the record's pointer cast to the member's struct, after a switch on {tag.name}, has that struct as \
its effective type */
/* the list's alignment, the unit of every binding's `at` index */
#define {naming.const_name(ns, naming.union_align(union.name))} {typed_literal(align, "dec", "u32")}
/* the size of the member's struct, 0 for a tag this header does not name: the one table the helpers read */
static inline uint32_t {fn["member_size"]}({naming.BUILTIN_C_TYPES[tag.type]} tag) {{
\tswitch (tag) {{
{cases}\tdefault: return 0;
\t}}
}}
/* the clause of the record at byte `at` of a list `bytes` long, {ok} where it is a member this header \
names, its size that member's, within the extent; reads its header only once {head_size} bytes remain */
static inline {clause} {fn["record_clause"]}(const {head}* record, {ct} at, {ct} bytes) {{
\tuint32_t need;
\tif (bytes <= at) return {k["count_not_met"]};
\tif (({ct})(bytes - at) < {head_size}) return {k["header_past_extent"]};
\tneed = {fn["member_size"]}(record->{tag.name});
\tif (need == 0) return {k["unknown_tag"]};
\tif (record->{length.name} != need) return {k["size_not_the_members"]};
\tif (({ct})(bytes - at) < need) return {k["record_past_extent"]};
\treturn {ok};
}}
/* {fn["first"]}, {fn["next"]} and {fn["well_formed"]} take `list` as a {head}*, so it is aligned to {align} by its \
type; the caller's duties: `list` non-null wherever `bytes` > 0, and valid for `bytes` bytes; `cur` a record this \
list's walk returned */
/* the first record of the list, or NULL where the list is empty or its first record is malformed */
static inline const {head}* {fn["first"]}(const {head}* list, {ct} bytes) {{
\treturn {fn["record_clause"]}(list, 0, bytes) == {ok} ? list : {null};
}}
/* the record after `cur`, or NULL at the list's end or where the next record is malformed; \
{fn["well_formed"]} tells the two apart */
static inline const {head}* {fn["next"]}(const {head}* list, const {head}* cur, {ct} bytes) {{
\t{ct} at = ({ct})((const char*)cur - (const char*)list + cur->{length.name});
\tconst {head}* record = (const {head}*)(const void*)((const char*)list + at);
\treturn {fn["record_clause"]}(record, at, bytes) == {ok} ? record : {null};
}}
/* {ok} where `list` holds exactly `count` records in `bytes` bytes; else the clause, and in *index and \
*offset the record it stopped at and its byte offset; reads no byte past the extent */
static inline {clause} {fn["well_formed"]}(const {head}* list, {ct} count, {ct} bytes, {ct}* index, {ct}* offset) {{
\t{ct} at = 0, i = 0;
\tconst {head}* record = list;
\tfor (; i < count; i++) {{
\t\t{clause} clause;
\t\t*index = i;
\t\t*offset = at;
\t\tclause = {fn["record_clause"]}(record, at, bytes);
\t\tif (clause != {ok}) return clause;
\t\tat = ({ct})(at + record->{length.name});
\t\trecord = (const {head}*)(const void*)((const char*)list + at);
\t}}
\t*index = i;
\t*offset = at;
\treturn at == bytes ? {ok} : {k["count_not_met"]};
}}
"""
