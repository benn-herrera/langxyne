"""The header-only C++20 wrapper: the constants, enums and structs under the namespace, a
checked range and `as<T>()` per union declaring `_mixed_type_list`, and a move-only class
per opaque ref that names a constructor, forwarding inline to the C functions."""

from pathlib import Path

from langxyne import model, naming
from langxyne.emitters import c, cpp, emitter
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

_HANDLE_MEMBER = "handle_"
_GENERATED_NAMES = ("result", "status", "handle", _HANDLE_MEMBER)
"""The fixed names the class's generated text binds where a definition parameter's name is
in scope: `create()`'s `result` parameter and `status` local beside the ctor's parameters,
the private constructor's `handle` parameter beside the cached `out`s, and the `handle_`
member every method reads beside its own parameters. A parameter named like one of these
would collide with it or shadow it; `_rendered_names()` holds the ones the definition
names."""
LABEL = "wrapper"
_UNION_ERROR = naming.UNION_ERROR
_UNION_CLAUSE = naming.UNION_CLAUSE_TYPE
_UNION_DEFINERS = (
    (model.UNION_ERROR_DEFINER, _UNION_ERROR),
    (model.UNION_CLAUSE_DEFINER, _UNION_CLAUSE),
    (model.UNION_CLAUSE_TEXT_DEFINER, naming.UNION_CLAUSE_TEXT),
)
"""The namespace names the wrapper defines once where some union declares `_mixed_type_list`."""
# Each clause's entry of `UnionClause`, by its name in `naming.UNION_CLAUSES`.
_CLAUSE = {name: f"{_UNION_CLAUSE}::{naming.upper_camel(name)}" for name, _ in naming.UNION_CLAUSES}
_AS = "as"


def _rendered_names(api: Api) -> set[str]:
    """Every name the class's generated text spells where a definition parameter or member
    name is in scope: the C functions it calls, the C typedefs and fixed-width types its
    signatures name, and the namespace's enum classes, boxed scalar and struct aliases,
    sequence classes and classes."""
    ns = api.namespace
    names = {naming.function_name(ns, f.name) for f in api.functions}
    names |= {
        naming.type_name(ns, t.name) for t in (*api.typed_consts, *api.opaque_refs, *api.boxed_scalars, *api.structs)
    }
    names |= {naming.upper_camel(t.name) for t in (*api.typed_consts, *api.boxed_scalars, *api.structs)}
    names |= {naming.union_sequence(u.name) for u in api.listed_unions()}
    names |= {naming.upper_camel(shape.opaque.class_name) for shape in api.classes()}
    return names | set(naming.BUILTIN_C_TYPES.values())


def validate(api: Api) -> list[str]:
    """Every objection the wrapper has to `api`: a name that is a C++ keyword, a parameter
    named like a type the header's declarations spell, a parameter a class renders named
    like one of `_GENERATED_NAMES` or `_rendered_names()`, or like a name its method binds
    for a callback (`_callback_names()`), a callback parameter whose template parameter is
    one of `_rendered_names()`, a method named like one of the latter, and a name the
    wrapper would define twice in the namespace, an enum class or a class. Enums'
    conversions may share a name, since each overloads on its own enum class, and unions'
    `as` may, since each overloads on its own prefix; two unions of one prefix may not."""
    objections = cpp.cpp_keyword_objections(api) + c.parameter_type_objections(api)
    classes = api.classes()
    rendered_names = _rendered_names(api)
    params = [
        (f"function.{fn.name}.{p.name}", name)
        for shape in classes
        for fn, rendered, _ in shape.class_params()
        for p in rendered
        for name in (p.name, *p.derived_names())
    ]
    objections += generated_name_objections(params, {*_GENERATED_NAMES, *(rendered_names - c.type_names(api))})
    for shape in classes:
        for fn in shape.methods:
            rendered = [(f"function.{fn.name}.{p.name}", p.name) for p in fn.params[1:]]
            objections += generated_name_objections(rendered, _callback_names(api, fn))
            templates = [
                (f"function.{fn.name}.{p.name}", naming.cpp_template_param(p.name)) for p in fn.params if p.callback
            ]
            objections += generated_name_objections(templates, rendered_names)
    methods = [(f"function.{fn.name}", fn.name) for shape in classes for fn in shape.methods]
    objections += generated_name_objections(methods, rendered_names)
    const = naming.unprefixed_const_name
    namespace = [(where, const(name)) for where, name in api.constant_names(enum_entries=False, version=True)]
    namespace += [(f"typed_const.{t.name}", naming.upper_camel(t.name)) for t in api.typed_consts]
    namespace += [(f"boxed_scalar.{b.name}", naming.upper_camel(b.name)) for b in api.boxed_scalars]
    namespace += [(f"struct.{s.name}", naming.upper_camel(s.name)) for s in api.structs]
    listed = api.listed_unions()
    if listed:
        namespace += _UNION_DEFINERS
        namespace.append((f"union.{listed[0].name}", _AS))
    namespace += [(f"union.{u.name}", naming.union_sequence(u.name)) for u in listed]
    objections += duplicate_objections(
        [(f"union.{u.name}", f"{_AS}(const {naming.upper_camel(u.prefix)}&)") for u in listed],
        f"namespace {api.namespace}",
    )
    if api.uses_text():
        namespace += [
            (model.TEXT_DEFINER, naming.upper_camel(naming.TEXT)),
            (model.RESOLVER_DEFINER, naming.RESOLVE),
        ]
    namespace += [(f"opaque_ref.{s.opaque.name}._class", naming.upper_camel(s.opaque.class_name)) for s in classes]
    namespace += [
        (f"{g.name}._to_string", g.to_string)
        for g in (*api.bit_const_groups, *api.const_groups)
        if g.to_string is not None
    ]
    overloads: dict[str, str] = {}
    for t in api.typed_consts:
        if t.to_string is not None:
            overloads.setdefault(t.to_string, f"typed_const.{t.name}._to_string")
    namespace += [(where, name) for name, where in overloads.items()]
    objections += duplicate_objections(namespace, f"namespace {api.namespace}")
    for t in api.typed_consts:
        objections += duplicate_objections(
            [(f"typed_const.{t.name}.{e.name}", naming.upper_camel(e.name)) for e in t.entries],
            f"enum class {naming.upper_camel(t.name)}",
        )
    for shape in classes:
        cls = naming.upper_camel(shape.opaque.class_name)
        own = [cls, "create", "handle", _HANDLE_MEMBER, *(["release"] if shape.dtor is not None else [])]
        objections += duplicate_objections(shape.members(own), f"class {cls}")
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("include") / project / f"{name}.hpp"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The header-only C++ wrapper."""
    ns = api.namespace
    std_headers = {"utility"}
    if any(g.to_string is not None for g in api.bit_const_groups):
        std_headers |= {"charconv", "string"}
    if any(g.to_string is not None for g in api.const_groups):
        std_headers.add("string")
    if api.uses_text():
        std_headers |= {"optional", "string_view"}
    listed = api.listed_unions()
    if listed:
        std_headers |= {"cstddef", "iterator", "optional", "type_traits"}
    classes = api.classes()
    if any(shape.drives() for shape in classes):
        std_headers |= {"cstdio", "cstdlib", "memory", "thread", "type_traits"}
    if any(
        api.first_nonzero_entry(fn) is None and _marshal(api, params, outrefs_are_locals=ctor)[2]
        for shape in classes
        for fn, params, ctor in shape.class_params()
    ):  # an object argument's refusal aborts
        std_headers |= {"cstdio", "cstdlib"}
    out = [
        f"// {emitter.banner(source_name)}\n",
        "#pragma once\n\n",
        f'#include "{name}.h"\n\n',
        "".join(f"#include <{h}>\n" for h in sorted(std_headers)) + "\n",
        f"namespace {ns} {{\n",
    ]

    def constant(c_type: str, name: str) -> str:
        return f"inline constexpr {c_type} {naming.unprefixed_const_name(name)} = {naming.const_name(ns, name)};\n"

    # the header's macros carry each untyped constant's type, so restating it here could only disagree
    runs = [constant("auto", naming.VERSION_KEY)]
    runs += [
        _comment(g.docstring) + "".join(constant("auto", entry.name) for entry in g.entries) + _bit_to_string(g)
        for g in api.bit_const_groups
    ]
    runs += [
        _comment(g.docstring) + "".join(constant("auto", entry.name) for entry in g.entries) + _plain_to_string(g)
        for g in api.const_groups
    ]
    runs += [
        _comment(g.docstring) + "".join(constant("const char*", entry.name) for entry in g.entries)
        for g in api.string_const_groups
    ]
    out += ["\n" + run for run in runs]
    out += ["\n" + _comment(h) + _enum(api, t) for h, t in headed(api.typed_const_groups)]
    aliased = [
        *((h, b.name) for h, b in headed(api.boxed_scalar_groups)),
        *([(None, naming.TEXT)] if api.uses_text() else []),
        *((h, s.name) for h, s in headed(api.struct_groups)),
    ]
    if aliased:
        out.append(
            "\n"
            + "".join(f"{_comment(h)}using {naming.upper_camel(t)} = {naming.type_name(ns, t)};\n" for h, t in aliased)
        )
    if api.uses_text():
        out.append(_resolve())
    if listed:
        out.append(_union_clause_and_error(api))
        out += ["\n" + _comment(h) + _sequence(api, u) for h, u in headed(api.union_groups, listed)]
    opaque_headings = {o.name: h for h, o in headed(api.opaque_ref_groups, (s.opaque for s in classes))}
    names = [naming.upper_camel(shape.opaque.class_name) for shape in classes]
    if names:
        out.append("\n" + "".join(f"class {name};\n" for name in names))
    rendered = [
        _class(api, shape, heading=opaque_headings[shape.opaque.name], others=[n for n in names if n != name])
        for shape, name in zip(classes, names)
    ]
    out += [text for text, _ in rendered]
    out += [definitions for _, definitions in rendered]
    out.append(f"\n}}  // namespace {ns}\n")
    return "".join(out)


def _resolve() -> str:
    """`resolve()`, the bytes of whatever arena a text's run indexes, which the caller names;
    `std::nullopt` where the run leaves the arena."""
    offset, length = naming.TEXT_OFFSET, naming.TEXT_LENGTH
    return (
        f"\n[[nodiscard]] inline std::optional<std::string_view> {naming.RESOLVE}"
        f"({naming.upper_camel(naming.TEXT)} text, std::string_view arena) {{\n"
        f"  if (text.{offset} > arena.size() || text.{length} > arena.size() - text.{offset}) {{\n"
        "    return std::nullopt;\n"
        "  }\n"
        f"  return arena.substr(text.{offset}, text.{length});\n"
        "}\n"
    )


def _union_clause_and_error(api: Api) -> str:
    """`UnionClause`, the six clauses over the header's clause enum, each trailed by its text,
    then `union_clause_text()`, a clause's text, and `UnionError`, whose index and offset are
    `uint32_t`, or `uint64_t` where some union declaring `_mixed_type_list` is counted by `u64`,
    so every union's count type fits."""
    ns = api.namespace
    clauses = c.union_clause_enum(api)
    entries = "".join(
        f"  {naming.upper_camel(name)} = {naming.const_name(ns, naming.union_clause_entry(name))},  // {text}\n"
        for name, text in naming.UNION_CLAUSES
    )
    wide = any(u.count_type == "u64" for u in api.listed_unions())
    position = naming.BUILTIN_C_TYPES["u64" if wide else "u32"]
    text = _switch(
        naming.UNION_CLAUSE_TEXT,
        returns="const char*",
        param=_UNION_CLAUSE,
        cases=[(_CLAUSE[name], text) for name, text in naming.UNION_CLAUSES],
        unknown=naming.unknown_value_name(naming.UNION_CLAUSE),
    )
    return (
        f"\n// why a walk of a union's list refused it, beside the record's index and byte offset in a {_UNION_ERROR}\n"
        f"enum class {_UNION_CLAUSE} : {naming.BASE_C_TYPES[clauses.base_type].c_type} {{\n{entries}}};\n"
        f"{text}"
        "// where a walk of a sequence refused it: the record's index, its byte offset, the clause\n"
        f"struct {_UNION_ERROR} {{\n  {position} index;\n  {position} offset;\n  {_UNION_CLAUSE} clause;\n}};\n"
    )


def _sequence(api: Api, union: Union) -> str:
    """`union`'s sequence class under its docstring, a forward range over each record's prefix
    whose iterator checks each record by the header's `record_clause` before reaching it, its
    count, extent and offsets of the union's count type, as the header's helpers take them;
    then `as<T>()`, the record as member `T` where its tag is `T`'s, which compiles only for a
    member."""
    ns = api.namespace
    seq = naming.union_sequence(union.name)
    head = naming.upper_camel(union.prefix)
    tag, length = api.prefix_fields(union)
    tag_type = naming.BUILTIN_C_TYPES[tag.type]
    ct = naming.BUILTIN_C_TYPES[union.count_type]
    align = api.list_alignment(union)
    record_clause = naming.union_helper(ns, union.name, "record_clause")
    ok = naming.const_name(ns, naming.UNION_OK)
    count_not_met = naming.const_name(ns, naming.union_clause_entry("count_not_met"))
    members = [naming.upper_camel(m.struct) for m in union.members]
    tags = [f"{tag_type}({naming.unprefixed_const_name(m.tag)})" for m in union.members]
    is_member = " || ".join(f"std::is_same_v<T, {s}>" for s in members)
    tag_of_t = (
        "".join(f"      std::is_same_v<T, {s}> ? {t} :\n" for s, t in zip(members[:-1], tags[:-1]))
        + f"      {tags[-1]};\n"
    )
    return f"""\
{_comment(union.docstring)}// A list of {union.name}'s members back to back, each by its own size: a range over each record's
// {head}, which the iterator reaches only once {record_clause} admits it, reading no byte past the
// extent; a walk, begin() or at(), that stops at a record it refuses says why in error(), empty where
// the walk met the count at the extent
// the records of a sequence a callback receives are valid for that call of the callback only;
// incrementing an iterator equal to end(), a walk ended or refused, is undefined, as for any forward iterator
class {seq} {{
 public:
  class iterator {{
   public:
    using iterator_category = std::forward_iterator_tag;
    using value_type = {head};
    using difference_type = std::ptrdiff_t;
    using pointer = const {head}*;
    using reference = const {head}&;

    iterator() noexcept = default;
    reference operator*() const noexcept {{ return *record_; }}
    pointer operator->() const noexcept {{ return record_; }}
    iterator& operator++() noexcept {{
      offset_ = {ct}(offset_ + record_->{length.name});
      ++index_;
      record_ = sequence_->walk(index_, offset_);
      return *this;
    }}
    iterator operator++(int) noexcept {{
      iterator before = *this;
      ++*this;
      return before;
    }}
    friend bool operator==(const iterator& a, const iterator& b) noexcept {{ return a.record_ == b.record_; }}

   private:
    friend class {seq};
    iterator(const {seq}* sequence, const {head}* record) noexcept : sequence_(sequence), record_(record) {{}}

    const {seq}* sequence_ = nullptr;
    const {head}* record_ = nullptr;
    {ct} index_ = 0;
    {ct} offset_ = 0;
  }};

  // the list's alignment, the unit of at()'s index
  static constexpr {ct} align = {align};

  // validates nothing yet: each walk checks each record it reaches
  {seq}(const {head}* list, {ct} count, {ct} bytes) noexcept : list_(list), count_(count), bytes_(bytes) {{}}
  [[nodiscard]] const {head}* data() const noexcept {{ return list_; }}
  [[nodiscard]] {ct} count() const noexcept {{ return count_; }}
  [[nodiscard]] {ct} bytes() const noexcept {{ return bytes_; }}
  [[nodiscard]] iterator begin() const noexcept {{
    error_.reset();
    return iterator(this, walk(0, 0));
  }}
  [[nodiscard]] iterator end() const noexcept {{ return iterator(this, nullptr); }}
  [[nodiscard]] std::optional<{_UNION_ERROR}> error() const noexcept {{ return error_; }}
  // the record at byte `index` * align from the start, found by walking from the start, the
  // byte offset saturating at the count type's largest; nullptr where the walk refuses a record before it or does
  // not land on it
  [[nodiscard]] const {head}* at({ct} index) const noexcept {{
    error_.reset();
    const {ct} offset = index <= {ct}({ct}(-1) / align) ? {ct}(index * align) : {ct}(-1);
    {ct} walked = 0;
    {ct} here = 0;
    const {head}* record = walk(walked, here);
    while (record && here < offset) {{
      here = {ct}(here + record->{length.name});
      record = walk(++walked, here);
    }}
    if (record && here == offset) {{
      return record;
    }}
    if (!error_) {{
      error_ = {_UNION_ERROR}{{walked, offset, {_CLAUSE['not_a_record_start']}}};
    }}
    return nullptr;
  }}

 private:
  // the record `index` at byte `offset` where {record_clause} admits it; else nullptr, and the error unless the
  // walk has met the count at the extent
  const {head}* walk({ct} index, {ct} offset) const noexcept {{
    {naming.type_name(ns, naming.UNION_CLAUSE)} clause = {count_not_met};
    if (index == count_) {{
      if (offset == bytes_) {{
        return nullptr;
      }}
    }} else {{
      const {head}* record = reinterpret_cast<const {head}*>(reinterpret_cast<const char*>(list_) + offset);
      clause = {record_clause}(record, offset, bytes_);
      if (clause == {ok}) {{
        return record;
      }}
    }}
    error_ = {_UNION_ERROR}{{index, offset, {_UNION_CLAUSE}(clause)}};
    return nullptr;
  }}

  const {head}* list_;
  {ct} count_;
  {ct} bytes_;
  mutable std::optional<{_UNION_ERROR}> error_;
}};

// the record as member T, or nullptr where its tag is another member's; T must be a member of {union.name}
template <class T>
[[nodiscard]] const T* {_AS}(const {head}& record) noexcept {{
  static_assert({is_member}, "T must be a member of union {union.name}");
  constexpr {tag_type} tag =
{tag_of_t}  return record.{tag.name} == tag ? reinterpret_cast<const T*>(&record) : nullptr;
}}
"""


def _enum(api: Api, typed: TypedConst) -> str:
    cls = naming.upper_camel(typed.name)
    entries = "".join(
        f"  {naming.upper_camel(e.name)} = {naming.const_name(api.namespace, e.name)},\n" for e in typed.entries
    )
    text = f"enum class [[nodiscard]] {cls} : {naming.BASE_C_TYPES[typed.base_type].c_type} {{\n{entries}}};\n"
    if typed.to_string is not None:
        text += _switch(
            typed.to_string,
            returns="const char*",
            param=cls,
            cases=[
                (f"{cls}::{naming.upper_camel(e.name)}", naming.unprefixed_const_name(e.name)) for e in typed.entries
            ],
            unknown=naming.unknown_value_name(typed.name),
        )
    return text


def _plain_to_string(group: Group[EnumEntry]) -> str:
    if group.to_string is None:
        return ""
    return _switch(
        group.to_string,
        returns="std::string",
        param=naming.BASE_C_TYPES[group.base_type].c_type,
        cases=[(naming.unprefixed_const_name(e.name),) * 2 for e in named_values(group)],
        unknown=naming.unknown_value_name(None),
    )


def _switch(name: str, *, returns: str, param: str, cases: list[tuple[str, str]], unknown: str) -> str:
    """A value-to-text conversion from (case label, text) pairs, one per value: duplicate
    case labels do not compile, so a plain group's come from `named_values()`."""
    body = "".join(f'    case {label}: return "{text}";\n' for label, text in cases)
    return (
        f"\ninline {returns} {name}({param} value) {{\n  switch (value) {{\n{body}" f'  }}\n  return "{unknown}";\n}}\n'
    )


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term."""
    if group.to_string is None:
        return ""
    flags = "".join(
        f'  if (value & {k}) {{\n    text += "|{k}";\n    value &= ~{k};\n  }}\n'
        for k in (naming.unprefixed_const_name(entry.name) for entry in single_bit_entries(group))
    )
    return (
        f"\ninline std::string {group.to_string}({naming.BASE_C_TYPES[group.base_type].c_type} value) {{\n"
        f'  if (value == 0) {{\n    return "{naming.NO_FLAGS}";\n  }}\n'
        "  std::string text;\n"
        f"{flags}"
        "  if (value != 0) {\n"
        "    char hex[8];\n"
        "    char* const end = std::to_chars(hex, hex + sizeof(hex), uint32_t(value), 16).ptr;\n"
        '    text += "|0x";\n'
        "    text.append(hex, end);\n"
        "  }\n"
        "  return text.substr(1);\n"
        "}\n"
    )


def _ref_type(api: Api, type_name: str) -> str:
    """C++ spelling of a non-memory type the C side reaches through a pointer or caches:
    the boxed scalar or struct alias, else the C type."""
    if api.kind(type_name) in ("boxed", "struct"):
        return naming.upper_camel(type_name)
    return c.c_type(api, type_name)


def _marshal(
    api: Api, params: tuple[Param, ...], *, outrefs_are_locals: bool
) -> tuple[list[str], list[str], list[tuple[Param, ClassShape]]]:
    """The C++ parameter list, the C call arguments and each object argument with its class. A
    buffer is forwarded as the C header declares it, pointer and count, an array's pointer to
    its alias or C type, `const` for `in`, and each report a reference to the count's type
    passed by address; a callback is a callable of its own template parameter, passed as
    `_callback_locals()`' trampoline and state; an opaque with a class, by value or `in`, is the
    object by `const` reference, its handle passed, or `_optional` by pointer; with
    `outrefs_are_locals`, a non-memory out parameter is the caller's local, passed by address
    and absent from the signature (a constructor's cached outrefs; `_optional` never reaches
    them). An `_optional` struct or scalar `in`/`out`/`inout` parameter elsewhere is a pointer,
    forwarded as-is, instead of a reference; defaults are trailing, so it is given `= nullptr`
    only when every parameter after it in the signature has one too."""
    shapes = {shape.opaque.name: shape for shape in api.classes()}
    objects = []
    # (can this position default to nullptr, its signature text or None if it has none
    # (a constructor's local outref), the C call argument).
    entries: list[tuple[bool, str | None, str]] = []
    for p in params:
        if api.kind(p.type) == "opaque" and p.type in shapes and p.ref in (None, "in"):
            objects.append((p, shapes[p.type]))
            cls = naming.upper_camel(shapes[p.type].opaque.class_name)
            if p.optional:
                entries.append((True, f"const {cls}* {p.name}", f"{p.name} ? &{p.name}->{_HANDLE_MEMBER} : nullptr"))
            else:
                handle = f"{p.name}.{_HANDLE_MEMBER}"
                entries.append((False, f"const {cls}& {p.name}", handle if p.ref is None else f"&{handle}"))
        elif p.callback:
            entries += [
                (False, f"{naming.cpp_template_param(p.name)}&& {p.name}", naming.trampoline(p.name)),
                (False, None, f"&{naming.cpp_call_state(p.name)}"),
            ]
        elif p.is_union:
            entries.append((False, f"{naming.union_sequence(p.type)} {p.name}", f"{p.name}.data()"))
            entries += [(False, None, f"{p.name}.count()"), (False, None, f"{p.name}.bytes()")]
        elif p.is_buffer:
            const = "const " if p.ref == "in" else ""
            pointer = c.param_type(api, p) if p.type == "memory" else f"{const}{_ref_type(api, p.type)}*"
            count_type = c.c_type(api, p.count_type)
            count = p.count_name()
            entries.append((False, f"{pointer} {p.name}", p.name))
            entries.append((False, f"{count_type} {count}", count))
            entries += [(False, f"{count_type}& {report}", f"&{report}") for report in p.report_names()]
        elif p.ref == "in":
            if p.optional:
                entries.append((True, f"const {_ref_type(api, p.type)}* {p.name}", p.name))
            else:
                entries.append((False, f"const {_ref_type(api, p.type)}& {p.name}", f"&{p.name}"))
        elif p.ref is not None:
            local_outref = outrefs_are_locals and p.ref == "out"
            if local_outref:
                entries.append((False, None, f"&{p.name}"))
            elif p.optional:
                entries.append((True, f"{_ref_type(api, p.type)}* {p.name}", p.name))
            else:
                entries.append((False, f"{_ref_type(api, p.type)}& {p.name}", f"&{p.name}"))
        elif api.kind(p.type) == "enum":
            entries.append((False, f"{naming.upper_camel(p.type)} {p.name}", f"{c.c_type(api, p.type)}({p.name})"))
        else:
            entries.append((False, f"{_ref_type(api, p.type)} {p.name}", p.name))

    sig: list[str] = []
    can_default = True
    for can_be_default, text, _ in reversed(entries):
        if text is None:
            continue
        if can_be_default and can_default:
            sig.append(f"{text} = nullptr")
        else:
            sig.append(text)
            can_default = False
    sig.reverse()
    return sig, [call for _, _, call in entries], objects


_CALLBACK_NAMES = ("call", "answer", "stderr")
"""The names a callback's trampoline binds or reads, where a method's parameters are in scope."""
_FAILED_LOCAL = "_failed"
"""A callback method's local recording whether any callback of its call failed, which no
definition name can take: none begins with `_`."""
_IN_CALL = "_in_call"
"""The member naming the C function a call of the object is driving a callback in, which no
definition name can take: none begins with `_`."""


def _trampoline_params(api: Api, callback: Function) -> list[tuple[str, str]]:
    """(C type, name) of the trampoline's parameters, named by position."""
    return [(t, naming.cpp_trampoline_param(i)) for i, (t, _) in enumerate(c.callback_params(api, callback))]


def _callback_locals(api: Api, fn: Function, p: Param) -> str:
    """The statements before the C call for a method's callback parameter `p`: its state, the
    callable's address with its type kept, the driving call's thread, whether an invocation
    is running and the method's failure flag, which the trampoline reaches through
    `user_data`; and the trampoline, a captureless `noexcept` lambda converted to the C
    callback type, which aborts on another thread, naming the callback type and the C
    function; answers the stop entry without calling the callable where the call has
    recorded a failure or the callable's previous invocation has not returned, recording the
    latter; refuses at compile time a callable whose result is not the return enum class; and
    otherwise calls the callable, an enum as its enum class, and answers its enum class as the
    C enum."""
    callback = api.callback(p.type)
    params = _trampoline_params(api, callback)
    c_type = naming.type_name(api.namespace, callback.name)
    c_return = c.c_type(api, callback.returns)
    ret = naming.upper_camel(callback.returns)
    stop = f"{c_return}({ret}::{naming.upper_camel(api.stop_entry(callback).name)})"
    fname = naming.function_name(api.namespace, fn.name)
    state = naming.cpp_call_state(p.name)
    args, position = [], 0
    for q in callback.params:
        name = params[position][1]
        if q.is_union:
            args.append(f"{naming.union_sequence(q.type)}({', '.join(n for _, n in params[position : position + 3])})")
        else:
            args.append(f"{naming.upper_camel(q.type)}({name})" if api.kind(q.type) == "enum" else name)
            if q.is_buffer:
                args.append(params[position + 1][1])
        position += len(c.c_params(api, q))
    invoke = f"(*call.callable)({', '.join(args)})"
    signature = ", ".join(f"{t} {n}" for t, n in params)
    return (
        "    struct {\n"
        f"      decltype(std::addressof({p.name})) callable;\n"
        "      std::thread::id thread;\n"
        "      bool running;\n"
        "      bool* failed;\n"
        f"    }} {state}{{std::addressof({p.name}), std::this_thread::get_id(), false, &{_FAILED_LOCAL}}};\n"
        f"    const {c_type} {naming.trampoline(p.name)} = []({signature}) noexcept -> {c_return} {{\n"
        f"      auto& call = *static_cast<decltype({state})*>({params[-1][1]});\n"
        "      if (call.thread != std::this_thread::get_id()) {\n"
        f'        std::fputs("{c_type} called on another thread than the one calling {fname}\\n", stderr);\n'
        "        std::abort();\n"
        "      }\n"
        "      if (*call.failed || call.running) {\n"
        "        *call.failed = true;\n"
        f"        return {stop};\n"
        "      }\n"
        f"      static_assert(std::is_same_v<std::remove_cvref_t<decltype({invoke})>, {ret}>,\n"
        f'                    "{p.name} must return {api.namespace}::{ret}");\n'
        "      call.running = true;\n"
        f"      const {c_return} answer = {c_return}({invoke});\n"
        "      call.running = false;\n"
        f"      return *call.failed ? {stop} : answer;\n"
        "    };\n"
    )


def _in_call_abort(what: str, member: str) -> str:
    """The statement aborting where `member` names a C function driving a callback, the message
    `what` followed by that function."""
    return (
        f"    if ({member}) {{\n"
        f'      std::fputs("{what} while ", stderr);\n'
        f"      std::fputs({member}, stderr);\n"
        '      std::fputs(" is in progress on it\\n", stderr);\n'
        "      std::abort();\n"
        "    }\n"
    )


def _in_call_refusal(api: Api, fn: Function, *, cls: str, name: str) -> str:
    """The statement refusing `name`, the class's member over `fn`, while a call of the object
    drives a callback: the first non-zero entry of its return enum, or where there is none an
    abort naming the class, the member and the driving C function."""
    entry = api.first_nonzero_entry(fn)
    if entry is None:
        return _in_call_abort(f"{api.namespace}::{cls}::{name} called", _IN_CALL)
    return f"    if ({_IN_CALL}) {{\n      return {naming.upper_camel(fn.returns)}::{naming.upper_camel(entry.name)};\n    }}\n"


def _callback_names(api: Api, fn: Function) -> set[str]:
    """Every name a method rendering `fn` binds for its callback parameters where its other
    parameters are in scope: each one's template parameter and locals, the trampolines'
    positional parameters and their locals; none where it takes no callback."""
    callbacks = [p for p in fn.params if p.callback]
    if not callbacks:
        return set()
    names = set(_CALLBACK_NAMES)
    for p in callbacks:
        names |= {naming.cpp_template_param(p.name), naming.cpp_call_state(p.name), naming.trampoline(p.name)}
        names |= {n for _, n in _trampoline_params(api, api.callback(p.type))}
    return names


def _doc(fn: Function, heading: str | None) -> str:
    """`heading`, the docstring of the group `fn` is the first of in its class, then `fn`'s own."""
    return "".join(_comment(doc, indent="  ") for doc in [heading, *fn.docs()])


def _c_call(api: Api, fn: Function, args: list[str]) -> str:
    ret = naming.upper_camel(fn.returns)
    return f"{ret}({naming.function_name(api.namespace, fn.name)}({', '.join(args)}))"


def _class(api: Api, shape: ClassShape, *, heading: str | None, others: list[str]) -> tuple[str, str]:
    """The class under `heading`, its opaque ref's group docstring where it is the first of
    that group's classes, each of its functions under its own group's where it is the first
    of that group's here, a friend of each of `others`, the other classes, whose methods read
    its handle; and the definitions of its methods taking an object, which follow the last
    class."""
    opaque, ctor, dtor, cached = shape.opaque, shape.ctor, shape.dtor, shape.cached
    cls = naming.upper_camel(opaque.class_name)
    handle_type = naming.type_name(api.namespace, opaque.name)
    headings = {fn.name: h for h, fn in headed(api.function_groups, shape.functions())}

    ret = naming.upper_camel(ctor.returns)
    zero = api.success_entry(ctor)
    sig, call, objects = _marshal(api, ctor.params, outrefs_are_locals=True)
    locals_ = "".join(f"    {_ref_type(api, p.type)} {p.name}{{}};\n" for p in ctor.params if p.ref == "out")
    failure = f"{cls}({', '.join(['nullptr', *('{}' for _ in cached)])})"
    entry = api.first_nonzero_entry(ctor)
    refused = (
        f"      if (result) {{\n        *result = {ret}::{naming.upper_camel(entry.name)};\n      }}\n"
        f"      return {failure};\n"
        if entry is not None
        else None
    )
    create = (
        f"{_doc(ctor, headings[ctor.name])}"
        f"  [[nodiscard]] static {cls} create({', '.join([*sig, f'{ret}* result = nullptr'])}) {{\n"
        + "".join(_argument_refusal(api, p, s, what=f"{cls}::create", refused=refused) for p, s in objects)
        + f"{locals_}"
        f"    const {ret} status = {_c_call(api, ctor, call)};\n"
        f"    if (result) {{\n      *result = status;\n    }}\n"
        f"    if (status != {ret}::{naming.upper_camel(zero.name)}) {{\n      return {failure};\n    }}\n"
        f"    return {cls}({', '.join([shape.handle.name, *(p.name for p in cached)])});\n"
        "  }\n"
    )

    drives = shape.drives()
    subject = f"{api.namespace}::{cls}"

    def lifetime_guard(what: str, member: str) -> str:
        return _in_call_abort(f"{subject} {what}", member) if drives else ""

    release_guard = f"      if ({_HANDLE_MEMBER}) {{\n        (void)release();\n      }}\n" if dtor is not None else ""
    member = naming.cpp_member
    reassign = "".join(f"      {member(p.name)} = other.{member(p.name)};\n" for p in cached)
    move_body = lifetime_guard("moved", f"other.{_IN_CALL}")
    lifetime = (
        f"\n  {cls}(const {cls}&) = delete;\n"
        f"  {cls}& operator=(const {cls}&) = delete;\n"
        f"  {cls}({cls}&& other) noexcept\n"
        f"      : {', '.join([*(f'{member(p.name)}(other.{member(p.name)})' for p in cached), f'{_HANDLE_MEMBER}(std::exchange(other.{_HANDLE_MEMBER}, nullptr))'])} {{"
        + (f"\n{move_body}  }}\n" if move_body else "}\n")
        + f"  {cls}& operator=({cls}&& other) noexcept {{\n"
        + lifetime_guard("moved into", _IN_CALL)
        + lifetime_guard("moved", f"other.{_IN_CALL}")
        + f"    if (this != &other) {{\n"
        f"{release_guard}"
        f"      {_HANDLE_MEMBER} = std::exchange(other.{_HANDLE_MEMBER}, nullptr);\n"
        f"{reassign}"
        f"    }}\n    return *this;\n  }}\n"
    )
    if dtor is not None:
        lifetime += (
            f"  ~{cls}() {{\n"
            + lifetime_guard("destroyed", _IN_CALL)
            + f"    if ({_HANDLE_MEMBER}) {{\n      (void)release();\n    }}\n  }}\n"
        )
    lifetime += (
        f"\n  explicit operator bool() const {{ return {_HANDLE_MEMBER} != nullptr; }}\n"
        f"  {handle_type} handle() const {{ return {_HANDLE_MEMBER}; }}\n"
    )

    body, definitions = [], []
    for fn in shape.methods:
        msig, mcall, objects = _marshal(api, fn.params[1:], outrefs_are_locals=False)
        callbacks = [p for p in fn.params if p.callback]
        template = (
            f"template <{', '.join(f'typename {naming.cpp_template_param(p.name)}' for p in callbacks)}>\n"
            if callbacks
            else ""
        )
        entry = api.first_nonzero_entry(fn)
        refused = (
            f"      return {naming.upper_camel(fn.returns)}::{naming.upper_camel(entry.name)};\n" if entry else None
        )
        guard = (_in_call_refusal(api, fn, cls=cls, name=fn.name) if drives else "") + "".join(
            _argument_refusal(api, p, s, what=f"{cls}::{fn.name}", refused=refused) for p, s in objects
        )
        call_text = _c_call(api, fn, [_HANDLE_MEMBER, *mcall])
        if callbacks:
            ret_type = naming.upper_camel(fn.returns)
            call = (
                f"    bool {_FAILED_LOCAL} = false;\n"
                + "".join(_callback_locals(api, fn, p) for p in callbacks)
                + f'    {_IN_CALL} = "{naming.function_name(api.namespace, fn.name)}";\n'
                f"    const {ret_type} status = {call_text};\n"
                f"    {_IN_CALL} = nullptr;\n"
                "    return status;\n"
            )
        else:
            call = f"    return {call_text};\n"
        ret = naming.upper_camel(fn.returns)
        declaration = (
            f"\n{_doc(fn, headings[fn.name])}{_indented(template)}  [[nodiscard]] {ret} {fn.name}({', '.join(msig)})"
        )
        if not objects:
            body.append(f"{declaration} {{\n{guard}{call}  }}\n")
            continue
        # another class's object may be incomplete here: the method is defined after the last class
        body.append(f"{declaration};\n")
        params = ", ".join(s.removesuffix(" = nullptr") for s in msig)
        definitions.append(
            f"\n{template}inline {ret} {cls}::{fn.name}({params}) {{\n"
            + "".join(line.removeprefix("  ") for line in (guard + call).splitlines(keepends=True))
            + "}\n"
        )
    if dtor is not None:
        body.append(
            f"\n{_doc(dtor, headings[dtor.name])}  [[nodiscard]] {naming.upper_camel(dtor.returns)} release() {{\n"
            + (_in_call_refusal(api, dtor, cls=cls, name="release") if drives else "")
            + f"    return {_c_call(api, dtor, [f'std::exchange({_HANDLE_MEMBER}, nullptr)'])};\n  }}\n"
        )

    accessors = "".join(
        (
            f"  const {_ref_type(api, p.type)}& {p.name}() const {{ return {member(p.name)}; }}\n"
            if api.kind(p.type) == "struct"
            else f"  {_ref_type(api, p.type)} {p.name}() const {{ return {member(p.name)}; }}\n"
        )
        for p in cached
    )
    private_members = "".join(f"  {_ref_type(api, p.type)} {member(p.name)};\n" for p in cached)
    ctor_params = ", ".join([f"{handle_type} handle", *(f"const {_ref_type(api, p.type)}& {p.name}" for p in cached)])
    inits = ", ".join([*(f"{member(p.name)}({p.name})" for p in cached), f"{_HANDLE_MEMBER}(handle)"])
    friends = "".join(f"  friend class {other};\n" for other in others)
    text = (
        f"\n{_comment(heading)}{_comment(opaque.docstring)}class {cls} {{\n public:\n{create}{lifetime}{''.join(body)}"
        + (f"\n{accessors}" if accessors else "")
        + f"\n private:\n{friends}  {cls}({ctor_params}) : {inits} {{}}\n\n{private_members}  {handle_type} {_HANDLE_MEMBER};\n"
        + (f"  const char* {_IN_CALL} = nullptr;\n" if drives else "")
        + "};\n"
    )
    return text, "".join(definitions)


def _indented(text: str) -> str:
    return "".join(f"  {line}" for line in text.splitlines(keepends=True))


def _argument_refusal(api: Api, p: Param, shape: ClassShape, *, what: str, refused: str | None) -> str:
    """The refusal of object argument `p`, of class `shape`, where it holds no handle, released
    or moved from, or where its class drives a callback and a call of it is in progress:
    `refused`, the statements answering the first non-zero entry of the return enum, or where
    that is None an abort naming `what` and the parameter."""
    access = "->" if p.optional else "."
    cond = f"!{p.name}{access}{_HANDLE_MEMBER}"
    if shape.drives():
        cond += f" || {p.name}{access}{_IN_CALL}"
    if p.optional:
        cond = f"{p.name} && ({cond})"
    if refused is None:
        message = f"{api.namespace}::{what}: {p.name} is released or in a driving call"
        refused = f'      std::fputs("{message}\\n", stderr);\n      std::abort();\n'
    return f"    if ({cond}) {{\n{refused}    }}\n"


def _comment(doc: str | None, *, indent: str = "") -> str:
    return f"{indent}// {doc}\n" if doc else ""
