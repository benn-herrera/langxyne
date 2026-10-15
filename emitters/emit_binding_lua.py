"""The LuaJIT base module: ffi.cdef of the header, constants, raw functions and a class
per opaque ref that names a constructor."""

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
    OpaqueRef,
    Param,
    Union,
    duplicate_objections,
    generated_name_objections,
    headed,
    named_values,
    single_bit_entries,
)

_LUA_KEYWORDS = frozenset(
    "and break do else elseif end false for function goto if in local nil not or repeat return "
    "then true until while".split()
)
_GENERATED_NAMES = (
    "M",
    "ffi",
    "lib",
    "assert",
    "type",
    "tonumber",
    "setmetatable",
    "getmetatable",
    "self",
    "result",
    "h",
)
"""Every free name the generated text binds or references where a class function's
arguments are in scope: the module's locals, the globals it calls, and the locals a class
function binds. A parameter is the one definition name that becomes a bare Lua name, so
a parameter named like one of these would shadow it. The names the module uses only where
no parameter is in scope are not here: `require` at the top, `bit`, `string`, `table` and
a conversion's locals (`value`, `names`) in the conversion functions, and the `handle`
local of the dtor's method, which takes no parameter but `self`."""
_CALLBACK_NAMES = ("jit", "pcall", "error", "failure")
"""Where a class renders a callback: the module's `jit` local, the globals a callback
method and its trampoline call, and the local a callback method keeps a failure in."""
_TRAMPOLINE_NAMES = (
    "fn",
    "failure",
    "driving",
    "running",
    "view",
    "call",
    "ok",
    "answer",
    "ffi",
    "pcall",
    "type",
    "tostring",
    "view_bounds",
)
"""What a trampoline binds or calls beside its callback type's parameters: a callback
parameter named like one would shadow it. A callback type with more than one byte view adds
the locals `_view_locals()` names after `view`."""
_IN_CALL = "_in_call"
"""The object field naming the C function a call of it is driving a callback in, which no
definition name can take: none begins with `_`."""
_COPY_ARRAY = "copy_array"
"""The module's local copying an `in` array's table into a new cdata array."""
_COPY_ARRAY_TEXT = f"""
-- An `in` array's 1-based table as a new 0-based cdata array of `ctype` ("T[?]") and its
-- count, copied element by element from t[1], so a stray t[0] cannot shift it; nil, 0 for nil.
local function {_COPY_ARRAY}(ctype, t)
    if t == nil then
        return nil, 0
    end
    local n = #t
    local array = ffi.new(ctype, n)
    for i = 1, n do
        array[i - 1] = t[i]
    end
    return array, n
end
"""

# LuaJIT hands a 64-bit integer over as cdata as readily as a number, since a Lua number is
# a double; a by-value or `inout` 64-bit parameter accepts either, a literal like `48ULL`
# possibly either C type.
_CDATA_INTEGERS = frozenset({"i64", "u64"})

_SUPPORT_ASSET = (Path(__file__).parent / "assets" / "i64.lua").read_text(encoding="utf-8")
"""The integer support module: `assets/i64.lua`, copied byte for byte beside a binding whose
definition uses a 64-bit type in a value position, as `lua/i64.lua`. A generic resource
of this emitter: no API name is associated with it, and the same bytes are written for every
definition that carries it."""

# The label every objection carries, naming the output file's identity: "binding x.lua:".
LABEL = "lua"

# Every conversion answers nil as `tostring(nil)` does.
_NIL_CLAUSE = '    if value == nil then return "nil" end\n'


def validate(api: Api) -> list[str]:
    """Every objection the Lua module has to `api`: a name that is a Lua keyword, a
    parameter of a class function named like one of `_GENERATED_NAMES`, a bit flag beyond
    the signed 32-bit range, a module field (constant, conversion, `raw` or class) defined
    twice, a class member defined twice, no library named, and a static link, since the
    module loads its library at run time."""
    objections = [f"{where}: '{name}' is a Lua keyword" for where, name in api.names() if name in _LUA_KEYWORDS]
    signed_max = naming.BASE_C_TYPES["i32"].max_value
    objections += [
        f"untyped_bit_const.{entry.name}: value 0x{entry.value:x} exceeds 0x{signed_max:x}; LuaJIT bit operations are "
        "signed 32-bit, so the flag would not equal its own masked result"
        for entry in api.bit_consts
        if entry.value > signed_max
    ]
    classes = api.classes()
    params = [
        (f"function.{fn.name}.{p.name}", p.name)
        for shape in classes
        for fn, rendered, _ in shape.class_params()
        for p in rendered
    ]
    callbacks = _rendered_callbacks(api, classes)
    used = set(_GENERATED_NAMES)
    if _renders_in_array(classes):
        used.add(_COPY_ARRAY)
    if callbacks:
        used |= {*_CALLBACK_NAMES, *(naming.trampoline(cb.name) for cb in callbacks)}
    objections += generated_name_objections(params, used)
    for cb in callbacks:
        objections += generated_name_objections(
            ((f"callback.{cb.name}.{p.name}", p.name) for p in cb.params), {*_TRAMPOLINE_NAMES, *_view_locals(cb)}
        )
    const = naming.unprefixed_const_name
    fields = [(where, const(name)) for where, name in api.constant_names(version=True)]
    fields += _conversion_names(api)
    fields.append(("the raw function table", "raw"))
    if api.uses_text():
        fields.append((model.RESOLVER_DEFINER, naming.RESOLVE))
    if api.uses_64_bit():
        fields.append(("the module local requiring the support module", "i64"))
    fields += [(f"opaque_ref.{s.opaque.name}._class", naming.upper_camel(s.opaque.class_name)) for s in classes]
    objections += duplicate_objections(fields, "module M")
    unions = {name: u.name for u in api.listed_unions() for name in _union_fields(u)}
    objections += [
        f"{where}: module field {name} already defined by union '{unions[name]}'"
        for where, name in fields
        if name in unions
    ]
    for shape in classes:
        members = shape.members(own=("new", "_handle"))
        if shape.dtor is not None:
            members.append((f"function.{shape.dtor.name}", shape.dtor.name))
        objections += duplicate_objections(members, f"class {naming.upper_camel(shape.opaque.class_name)}")
    if api.library.name is None:
        objections.append(emitter.NO_LIBRARY)
    if api.library.link == naming.STATIC:
        objections.append(
            f"--link={naming.STATIC}: the Lua module loads its library at run time and cannot link it statically"
        )
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("lua") / f"{name}.lua"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    """The module's companion, the integer support module: `assets/i64.lua` byte for byte,
    written beside the binding as `lua/i64.lua`, exactly where `api.uses_64_bit()`
    holds. `name` is ignored: nothing here is per-API."""
    if not api.uses_64_bit():
        return []
    return [(Path("lua") / "i64.lua", _SUPPORT_ASSET)]


def _union_fields(union: Union) -> tuple[str, str, str]:
    """The module fields walking a list of `union`, resolving an offset in one, and the list's
    alignment, the unit of that offset."""
    return (
        naming.lua_union_records(union.name),
        naming.lua_union_at(union.name),
        naming.unprefixed_const_name(naming.union_align(union.name)),
    )


def _rendered_callbacks(api: Api, classes: tuple[ClassShape, ...]) -> list[Function]:
    """The callback types some class function takes a parameter of, in document order: the
    ones whose trampoline the module renders."""
    used = {p.type for shape in classes for fn, rendered, _ in shape.class_params() for p in rendered if p.callback}
    return [cb for cb in api.callbacks if cb.name in used]


def _renders_in_array(classes: tuple[ClassShape, ...]) -> bool:
    """Whether some class function takes an `in` array, which `copy_array` copies."""
    return any(_is_in_array(p) for shape in classes for fn, rendered, _ in shape.class_params() for p in rendered)


def _is_in_array(p: Param) -> bool:
    return p.is_buffer and p.ref == "in" and p.type != "memory"


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The LuaJIT module, loading the library by its name, from which LuaJIT derives the
    platform's file name."""
    ns = api.namespace
    classes = api.classes()
    callbacks = _rendered_callbacks(api, classes)
    out = [
        f"-- {emitter.banner(source_name)}\n",
        'local ffi = require("ffi")\n',
        'local bit = require("bit")\n' if any(g.to_string is not None for g in api.bit_const_groups) else "",
        'local jit = require("jit")\n' if callbacks else "",
        'local i64 = require("i64")\n' if api.uses_64_bit() else "",
        "\n",
        _cdef(api),
        f'\nlocal lib = ffi.load("{api.library.name}")\n\nlocal M = {{}}\n\n',
    ]

    for doc, literals in _constant_sections(api):
        out.append(_comment(doc))
        out += [f"M.{name} = {value}\n" for name, value in literals]

    out += [_bit_to_string(g) for g in api.bit_const_groups if g.to_string is not None]
    out += [
        _lookup(
            naming.flat_to_string(g.to_string, typename=None), named_values(g), unknown=naming.unknown_value_name(None)
        )
        for g in api.const_groups
        if g.to_string is not None
    ]
    out += [
        _lookup(
            naming.flat_to_string(t.to_string, typename=t.name), t.entries, unknown=naming.unknown_value_name(t.name)
        )
        for t in api.typed_consts
        if t.to_string is not None
    ]
    bounded = _bounds_views(api, callbacks)
    if bounded:
        out.append(_VIEW_BOUNDS_TEXT)
    if api.uses_text():
        out.append(_resolve(bounded=bounded))
    if _renders_in_array(classes):
        out.append(_COPY_ARRAY_TEXT)
    out += [_trampoline(api, cb, bounded=bounded) for cb in callbacks]
    lists = api.listed_unions()
    if lists:
        out.append(_UNION_LIST_TEXT)
    out += [_union_list(api, u, heading=h) for h, u in headed(api.union_groups, lists)]

    raw = "".join(
        f"{_comment(h, indent='    ')}    {f.name} = lib.{naming.function_name(ns, f.name)},\n"
        for h, f in headed(api.function_groups)
    )
    out.append(f"\nM.raw = {{\n{raw}}}\n")

    opaque_headings = {o.name: h for h, o in headed(api.opaque_ref_groups, (s.opaque for s in classes))}
    out += [_class(api, shape, heading=opaque_headings[shape.opaque.name]) for shape in classes]

    out.append("\nreturn M\n")
    return "".join(out)


def _version_literal(api: Api) -> str:
    return f"0x{api.version_value():08x}"


def _constant_sections(api: Api) -> list[tuple[str | None, list[tuple[str, str]]]]:
    """Every constant's (name, Lua literal), in the same order the C header defines them,
    as (docstring, literals) sections: one per constant group and one per enum group, its
    entries' literals under the group's docstring, the version undocumented. Every value is
    the model's already-resolved one; a composed entry's sum was computed, and a bit group's
    overlap-checked, once in model.py."""
    name = naming.unprefixed_const_name
    sections = [(None, [(name(naming.VERSION_KEY), _version_literal(api))])]
    sections += [
        (g.docstring, [(name(entry.name), c.int_literal(entry.value, entry.format)) for entry in g.entries])
        for g in (*api.bit_const_groups, *api.const_groups)
    ]
    sections += [
        (g.docstring, [(name(e.name), c.int_literal(e.value, e.format)) for t in g.entries for e in t.entries])
        for g in api.typed_const_groups
    ]
    sections += [
        (g.docstring, [(name(entry.name), f'"{entry.value}"') for entry in g.entries]) for g in api.string_const_groups
    ]
    return sections


def _conversion_names(api: Api) -> list[tuple[str, str]]:
    """(where the definition names it, module field) for every `_to_string` conversion."""
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


def _lookup(name: str, entries: tuple[EnumEntry, ...], *, unknown: str) -> str:
    """A value-to-name conversion through a table, one key per value of `entries`: the order
    a table constructor assigns repeated keys in is undefined, so a plain group's come from
    `named_values()`."""
    keys = "".join(f'    [M.{key}] = "{key}",\n' for key in (naming.unprefixed_const_name(e.name) for e in entries))
    table = naming.lua_lookup_table(name)
    return (
        f"\nlocal {table} = {{\n{keys}}}\n"
        f'function M.{name}(value)\n{_NIL_CLAUSE}    return {table}[value] or "{unknown}"\nend\n'
    )


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term of their 32-bit pattern."""
    flags = "".join(
        f"    if bit.band(value, M.{k}) ~= 0 then\n"
        f'        names[#names + 1] = "{k}"\n'
        f"        value = bit.band(value, bit.bnot(M.{k}))\n"
        "    end\n"
        for k in (naming.unprefixed_const_name(entry.name) for entry in single_bit_entries(group))
    )
    return (
        f"\nfunction M.{naming.flat_to_string(group.to_string, typename=None)}(value)\n"
        f"{_NIL_CLAUSE}"
        f'    if value == 0 then return "{naming.NO_FLAGS}" end\n'
        "    local names = {}\n"
        f"{flags}"
        "    if value ~= 0 then\n"
        '        names[#names + 1] = string.format("0x%x", value % 0x100000000)\n'
        "    end\n"
        '    return table.concat(names, "|")\n'
        "end\n"
    )


_VIEW_BOUNDS = "view_bounds"
"""The module local mapping each byte view a running callback holds to the library's count for
it, which `M.resolve` bounds the view by."""
_VIEW_BOUNDS_TEXT = f'\nlocal {_VIEW_BOUNDS} = setmetatable({{}}, {{ __mode = "k" }})\n'
_RESOLVE_UNBOUNDED = f"M.{naming.RESOLVE}: a cdata arena needs its length; a callback's byte view is bounded only while its callback runs"


def _bounds_views(api: Api, callbacks: list[Function]) -> bool:
    """Whether the module keeps `view_bounds`: where some text resolves and some rendered
    callback has a byte view."""
    return api.uses_text() and any(p.type == "memory" for cb in callbacks for p in cb.params)


def _view_locals(callback: Function) -> list[str]:
    """The trampoline's local holding each byte view of `callback` while it runs, in order:
    `view`, then `view2` and on."""
    count = sum(p.type == "memory" for p in callback.params)
    return ["view" if i == 0 else f"view{i + 1}" for i in range(count)]


def _resolve(*, bounded: bool) -> str:
    """`M.resolve(text, arena, length)`: the bytes a text's run covers of whatever arena the
    caller names, as a string, `nil` where the run leaves it: a Lua string `arena` whatever
    `length` says; a byte view whose callback still runs, where `bounded`, by the library's
    count for it or a smaller `length`; any other cdata by `length`, which it then needs; read
    without copying the arena."""
    offset, length = naming.TEXT_OFFSET, naming.TEXT_LENGTH
    unbounded = f'assert(arena_length ~= nil, "{_RESOLVE_UNBOUNDED}")'
    if bounded:
        bound = (
            f"    local bound = {_VIEW_BOUNDS}[arena]\n"
            "    if bound == nil then\n"
            f"        {unbounded}\n"
            "        bound = arena_length\n"
            "    elseif arena_length ~= nil and arena_length < bound then\n"
            "        bound = arena_length\n"
            "    end\n"
        )
    else:
        bound = f"    {unbounded}\n    local bound = arena_length\n"
    return (
        f"\nfunction M.{naming.RESOLVE}(text, arena, arena_length)\n"
        f"    local {offset}, {length} = tonumber(text.{offset}), tonumber(text.{length})\n"
        '    if type(arena) == "string" then\n'
        f"        if {offset} + {length} > #arena then\n"
        "            return nil\n"
        "        end\n"
        f"        return arena:sub({offset} + 1, {offset} + {length})\n"
        "    end\n"
        f"{bound}"
        f"    if {offset} + {length} > bound then\n"
        "        return nil\n"
        "    end\n"
        f'    return ffi.string(ffi.cast("const uint8_t*", arena) + {offset}, {length})\n'
        "end\n"
    )


_CLAUSE_TEXTS = naming.UNION_CLAUSE_TEXTS
_UNION_LIST_TEXT = f"""
-- A walk of a union's list refused at the record `index`, `at` bytes from the list's start.
local function union_refuse(what, index, at, clause)
    error(string.format("%s: record %d at offset %d: %s", what, index, at, clause), 0)
end

-- The record at byte `at` of the list `seq`, `bytes` long, the record `index`, as cdata of its
-- member's struct, and its size: its prefix read only once the prefix's bytes remain, the record
-- only once its tag is a member's and its size that member's; else the refusal naming `what`.
local function union_record(union, what, seq, bytes, index, at)
    local clause
    if at == bytes then
        clause = "{_CLAUSE_TEXTS['count_not_met']}"
    elseif bytes - at < union.prefix_size then
        clause = "{_CLAUSE_TEXTS['header_past_extent']}"
    else
        local head = ffi.cast(union.prefix, ffi.cast("const uint8_t*", seq) + at)
        local member = union.members[head[union.tag]]
        if member == nil then
            clause = "{_CLAUSE_TEXTS['unknown_tag']}"
        elseif head[union.length] ~= member.size then
            clause = "{_CLAUSE_TEXTS['size_not_the_members']}"
        elseif bytes - at < member.size then
            clause = "{_CLAUSE_TEXTS['record_past_extent']}"
        else
            return ffi.cast(member.ctype, head), member.size
        end
    end
    union_refuse(what, index, at, clause)
end

-- An iterator over the `count` records of the list `seq`, `bytes` long, refusing where they do
-- not fill it exactly.
local function union_records(union, what, seq, count, bytes)
    local index, at = 0, 0
    return function()
        if index == count then
            if at ~= bytes then
                union_refuse(what, index, at, "{_CLAUSE_TEXTS['count_not_met']}")
            end
            return nil
        end
        local record, size = union_record(union, what, seq, bytes, index, at)
        index, at = index + 1, at + size
        return record
    end
end

-- The record `index` units of the list's alignment from the start of the list `seq` of `count`
-- records, `bytes` long, refused where the walk from the start refuses a record before it, the
-- count's among them, or does not land on it.
local function union_at(union, what, seq, count, bytes, index)
    local offset = index * union.align
    local walked, at = 0, 0
    while true do
        if walked == count then
            if at ~= bytes then
                union_refuse(what, walked, at, "{_CLAUSE_TEXTS['count_not_met']}")
            end
            break
        end
        local record, size = union_record(union, what, seq, bytes, walked, at)
        if at >= offset then
            if at == offset then
                return record
            end
            break
        end
        walked, at = walked + 1, at + size
    end
    union_refuse(what, walked, offset, "{_CLAUSE_TEXTS['not_a_record_start']}")
end
"""


def _union_list(api: Api, union: Union, *, heading: str | None) -> str:
    """`union`'s module constant `M.<U>_ALIGN`, the list's alignment, its shape, every size the
    layout model's, and its module fields: `M.<u>_records`, iterating a list's records as cdata
    of each one's member struct, and `M.<u>_at`."""
    members = "".join(
        f"        [M.{naming.unprefixed_const_name(m.tag)}] = "
        f'{{ ctype = ffi.typeof("const {c.c_type(api, m.struct)}*"), size = {api.layout(m.struct)[0]} }},\n'
        for m in union.members
    )
    shape = naming.lua_union_shape(union.name)
    records, at, align = _union_fields(union)
    ns = api.namespace
    return (
        f"\n{_comment(heading)}{_comment(union.docstring)}"
        f"-- the list's alignment, the unit of M.{at}'s index\n"
        f"M.{align} = {api.list_alignment(union)}\n"
        f"local {shape} = {{\n"
        f'    prefix = ffi.typeof("const {c.c_type(api, union.prefix)}*"),\n'
        f"    prefix_size = {api.layout(union.prefix)[0]},\n"
        f"    align = M.{align},\n"
        f'    tag = "{union.tag_field}",\n'
        f'    length = "{union.length_field}",\n'
        f"    members = {{\n{members}    }},\n"
        "}\n"
        f"-- the records M.{records} and M.{at} return are cdata into the view, valid for the callback's call only\n"
        f"function M.{records}(seq, count, bytes)\n"
        f'    return union_records({shape}, "{naming.function_name(ns, records)}", seq, count, bytes)\n'
        "end\n"
        f"function M.{at}(seq, count, bytes, index)\n"
        f'    return union_at({shape}, "{naming.function_name(ns, at)}", seq, count, bytes, index)\n'
        "end\n"
    )


def _trampoline(api: Api, callback: Function, *, bounded: bool) -> str:
    """`<c>_trampoline(fn, failure, driving)`, the Lua function a callback method casts to the
    C callback type for one driving call of the C function `driving`. Where the call has
    recorded a failure it answers the stop entry, and where the library calls it while a call
    of it runs it records that as the call's failure and answers the stop entry, reaching `fn`
    in neither case. Otherwise it calls `fn` under `pcall` through `call`, which makes every
    conversion the module makes, a byte view cast to `const uint8_t*` so it indexes and offsets
    by byte, and where `bounded` recorded in `view_bounds` until the call returns, every other
    argument, a union's list's pointer, count and extent among them, as LuaJIT hands it over. `nil` answers the zero entry and a whole number in the
    return enum's base type's range itself; a failure, or any other answer, is recorded in
    `failure` and answered with the stop entry, and the method raises it once the call
    returns."""
    c_type = naming.type_name(api.namespace, callback.name)
    returns = next(t for t in api.typed_consts if t.name == callback.returns)
    base = naming.BASE_C_TYPES[returns.base_type]
    views = iter(_view_locals(callback))
    names, args, casts, clears = [], [], [], []
    for p in callback.params:
        for name in (p.name, *p.derived_names()):
            names.append(name)
            if name == p.name and p.type == "memory":
                view = next(views)
                casts.append(f'        {view} = ffi.cast("const uint8_t*", {name})\n')
                if bounded:
                    casts.append(f"        {_VIEW_BOUNDS}[{view}] = {p.count_name()}\n")
                clears.append(
                    f"        if {view} ~= nil then\n"
                    + (f"            {_VIEW_BOUNDS}[{view}] = nil\n" if bounded else "")
                    + f"            {view} = nil\n"
                    "        end\n"
                )
                args.append(view)
            else:
                args.append(name)
    stop_entry = api.stop_entry(callback)
    stop = c.int_literal(stop_entry.value, stop_entry.format)
    go = api.success_entry(callback).value
    locals_ = ", ".join(["running", *_view_locals(callback)])
    initial = ", ".join(["false", *("nil" for _ in _view_locals(callback))])
    parameters = ", ".join(names)
    return (
        f"\n-- The function a callback method casts to {c_type} for one driving call, of the C function `driving`.\n"
        f"local function {naming.trampoline(callback.name)}(fn, failure, driving)\n"
        f"    local {locals_} = {initial}\n"
        f"    local function call({parameters})\n"
        f"{''.join(casts)}"
        f"        return fn({', '.join(args)})\n"
        "    end\n"
        f"    return function({parameters})\n"
        "        if failure.raised then\n"
        f"            return {stop}\n"
        "        end\n"
        "        if running then\n"
        "            failure.raised = true\n"
        f'            failure.error = "{c_type} called again while a call of it was running in " .. driving\n'
        f"            return {stop}\n"
        "        end\n"
        "        running = true\n"
        f"        local ok, answer = pcall(call, {parameters})\n"
        "        running = false\n"
        f"{''.join(clears)}"
        "        if failure.raised then\n"
        f"            return {stop}\n"
        "        end\n"
        "        if ok and answer == nil then\n"
        f"            return {go}\n"
        "        end\n"
        '        if ok and type(answer) == "number" and answer % 1 == 0 and answer >= '
        f"{base.min_value} and answer <= {base.max_value} then\n"
        "            return answer\n"
        "        end\n"
        "        failure.raised = true\n"
        f'        failure.error = ok and ("{c_type}: the function answered " .. tostring(answer)\n'
        f'            .. ", not nil or a whole number {base.c_type} holds") or answer\n'
        f"        return {stop}\n"
        "    end\n"
        "end\n"
    )


def _cdef(api: Api) -> str:
    """The `ffi.cdef` block: `c.binding_declarations()`."""
    return f"ffi.cdef[[\n{c.binding_declarations(api)}]]\n"


def _comment(doc: str | None, *, indent: str = "") -> str:
    """`doc` as a `--` comment line, nothing for none."""
    return f"{indent}-- {doc}\n" if doc else ""


def _doc_lines(fn: Function, heading: str | None) -> str:
    """`heading`, the docstring of the group `fn` is the first of here, then `fn`'s own."""
    return "".join(_comment(doc) for doc in [heading, *fn.docs()])


def _unboxed(api: Api, type_name: str) -> str:
    """The type a Lua caller passes and receives for `type_name`: a boxed scalar's base
    type, else the type itself."""
    return next((b.base_type for b in api.boxed_scalars if b.name == type_name), type_name)


def _lua_value(api: Api, type_name: str, expr: str, *, indent: str = "    ") -> str:
    """Enum values and builtins narrower than 64 bits become Lua numbers, a struct a table
    of its fields converted the same way (nested structs included); 64-bit and opaque values
    stay cdata. A boxed scalar or a text, reached only as a struct field here, is a copy of
    its FFI struct: indexing a struct field of struct type yields a reference into the
    parent, which the GC does not keep alive. `indent` is the indentation of the line the
    expression starts on."""
    kind = api.kind(type_name)
    if kind in ("boxed", "text"):
        return f'ffi.new("{c.c_type(api, type_name)}", {expr})'
    if kind == "struct":
        fields = next(s for s in api.structs if s.name == type_name).fields
        inner = indent + "    "
        body = "".join(
            f"{inner}{f.name} = {_lua_value(api, f.type, f'{expr}.{f.name}', indent=inner)},\n" for f in fields
        )
        return f"{{\n{body}{indent}}}"
    as_number = kind == "enum" or (kind == "builtin" and type_name not in _CDATA_INTEGERS)
    return f"tonumber({expr})" if as_number else expr


def _box(api: Api, type_name: str) -> str:
    """The ffi.new type for a value the C side reaches through a pointer: a struct or
    boxed scalar itself, anything else a one-element array."""
    c_type = c.c_type(api, type_name)
    return c_type if api.kind(type_name) in ("boxed", "struct") else f"{c_type}[1]"


def _alloc(api: Api, p: Param) -> str:
    """The cdata a non-memory reference parameter's C pointer reaches: an `in` or `inout`
    value arrives as a Lua value (a table or cdata for a struct) and is copied in; an
    `out` value starts zeroed. An `_optional` `in` or `inout` parameter builds the cdata
    only when the caller's value is non-nil; `nil` passes straight through, so the FFI
    turns it into a null pointer. A constructor's cached `out` parameter (also `out`
    here) ignores `_optional`, since the binding always supplies it."""
    box = _box(api, p.type)
    if p.optional and p.ref != "out":
        return f'    local {p.name} = {p.name} ~= nil and ffi.new("{box}", {p.name}) or nil\n'
    init = "" if p.ref == "out" else f", {p.name}"
    return f'    local {p.name} = ffi.new("{box}"{init})\n'


def _read_back(api: Api, p: Param) -> str:
    """The Lua value of what the C call wrote through a reference parameter. An
    `_optional` `inout` parameter reads back `nil` when the caller's own value was nil,
    since `_alloc` never built a pointer for the call to write through. A boxed scalar
    reads back its base type's value from `.value`."""
    kind = api.kind(p.type)
    if kind == "boxed":
        value = _lua_value(api, _unboxed(api, p.type), f"{p.name}.value")
    else:
        value = _lua_value(api, p.type, p.name if kind == "struct" else f"{p.name}[0]")
    if p.optional and p.ref != "out":
        return f"({p.name} ~= nil and {value} or nil)"
    return value


def _use_guard(opaque: OpaqueRef) -> str:
    """The assert every non-dtor method on the class begins with: using the object
    after release, or of a class whose opaque has no dtor to release it at all, is a
    caller bug, not a library result."""
    class_display = naming.upper_camel(opaque.class_name)
    reason = f"used after {opaque.dtor}" if opaque.dtor is not None else "has no handle"
    return f'assert(self._handle ~= nil, "{class_display} {reason}")'


def _type_check(api: Api, param: Param, name: str) -> tuple[str, str]:
    """The Lua condition `name`'s argument must satisfy, and the words describing the
    expected value for an assert message, keyed by the parameter's kind: a buffer (a
    string for `memory`, a table for an `in` array, or for an `out` buffer's count a whole
    number, each refused where its count type cannot hold the count, never truncated), a
    callback (a function), a struct (a table or its own
    cdata type), a by-value opaque (its own cdata type, never bare `cdata`), a 64-bit
    builtin (a number or 64-bit cdata, since a literal like `48ULL` may be `uint64_t`
    or `int64_t`), or a plain number (every narrower builtin and every enum); a boxed
    scalar is checked as its base type, which is what the caller passes. An
    `_optional` parameter's condition also admits `nil`, and its expected text gains
    an " or nil" suffix; the loader refuses `_optional` on a by-value parameter and on a
    buffer other than `_ref = "in"`, so neither reaches here."""
    if param.is_buffer:
        c_type = naming.BUILTIN_C_TYPES[param.count_type]
        bits = model.COUNT_BITS[param.count_type]
        limit = 2**bits
        if param.ref == "out":
            condition = f'type({name}) == "number" and {name} >= 0 and {name} < {limit} and {name} % 1 == 0'
            return condition, f"a whole number {c_type} holds"
        lua_type = "string" if param.type == "memory" else "table"
        condition, expected = f'type({name}) == "{lua_type}"', f"a {lua_type}"
        if bits < 64:
            condition, expected = f"{condition} and #{name} < {limit}", f"a {lua_type} {c_type} can count"
        if param.optional:
            condition, expected = f"{name} == nil or {condition}", f"{expected} or nil"
        return condition, expected
    if param.callback:
        return f'type({name}) == "function"', "a function"
    kind = api.kind(param.type)
    if kind == "struct":
        c_type = c.c_type(api, param.type)
        condition, expected = f'type({name}) == "table" or ffi.istype("{c_type}", {name})', f"a table or {c_type}"
    elif kind == "opaque" and _object_class(api, param) is not None:
        cls = f"M.{naming.upper_camel(_object_class(api, param).opaque.class_name)}"
        condition, expected = f"getmetatable({name}) == {cls}", f"a {cls}"
    elif kind == "opaque":
        c_type = c.c_type(api, param.type)
        condition, expected = f'ffi.istype("{c_type}", {name})', f"a {c_type}"
    elif _unboxed(api, param.type) in _CDATA_INTEGERS:
        condition = f'type({name}) == "number" or ffi.istype("uint64_t", {name}) or ffi.istype("int64_t", {name})'
        expected = "a number or 64-bit cdata"
    else:
        condition, expected = f'type({name}) == "number"', "a number"
    if param.optional:
        condition, expected = f"{name} == nil or {condition}", f"{expected} or nil"
    return condition, expected


def _object_class(api: Api, param: Param) -> ClassShape | None:
    """The class of an object argument, an opaque with a class by value or `in`; else None."""
    if param.ref not in (None, "in"):
        return None
    return next((shape for shape in api.classes() if shape.opaque.name == param.type), None)


def _object_handles(api: Api, params: tuple[Param, ...], *, context: str) -> list[str]:
    """For each object argument, after the asserts of every argument's type: the assert that it
    is not released, its refusal where its class drives a callback and a call of it does, and
    its handle in a local of the parameter's name, on which marshalling proceeds."""
    lines = []
    for p in _visible_args(params):
        shape = _object_class(api, p) if api.kind(p.type) == "opaque" else None
        if shape is None:
            continue
        cls = naming.upper_camel(shape.opaque.class_name)
        reason = f"used after {shape.dtor.name}" if shape.dtor is not None else "with no handle"
        checks = f'assert({p.name}._handle ~= nil, "{context}: {p.name} is a {cls} {reason}")\n'
        if shape.drives():
            checks += (
                f"if {p.name}.{_IN_CALL} ~= nil then\n"
                f'    error("{context}: {p.name} is a {cls} while " .. {p.name}.{_IN_CALL} .. " is in progress on it", 2)\n'
                "end\n"
            )
        if p.optional:
            checks = f"if {p.name} ~= nil then\n" + "".join(f"    {line}" for line in checks.splitlines(keepends=True))
            checks += "end\n" + f"local {p.name} = {p.name} and {p.name}._handle\n"
        else:
            checks += f"local {p.name} = {p.name}._handle\n"
        lines += [f"    {line}" for line in checks.splitlines(keepends=True)]
    return lines


def _visible_args(params: tuple[Param, ...]) -> list[Param]:
    """Parameters that appear as a Lua argument: every one but a non-buffer `out`,
    which is allocated internally and returned instead."""
    return [p for p in params if p.is_buffer or p.ref != "out"]


def _arg_asserts(api: Api, params: tuple[Param, ...], *, context: str) -> list[str]:
    """One `assert` per Lua-visible argument, in signature order, checking its type
    before any FFI allocation or call."""
    lines = []
    for p in _visible_args(params):
        if p.is_union:
            lines += _union_arg_asserts(api, p, context=context)
            continue
        name = _buffer_arg(p) if p.is_buffer else p.name
        condition, expected = _type_check(api, p, name)
        lines.append(f'    assert({condition}, "{context}: {name} must be {expected}")\n')
    return lines


def _union_arg_asserts(api: Api, p: Param, *, context: str) -> list[str]:
    """The asserts of a union's list, three arguments as a callback receives one: the pointer to
    the prefix, `nil` admitted where `_optional`, its count and its extent, each a number."""
    prefix = next(u.prefix for u in api.unions if u.name == p.type)
    pointer = f"const {c.c_type(api, prefix)}*"
    condition, expected = f'ffi.istype("{pointer}", {p.name})', f"a {pointer}"
    if p.optional:
        condition, expected = f"{p.name} == nil or {condition}", f"{expected} or nil"
    checks = [(p.name, condition, expected)]
    checks += [(name, f'type({name}) == "number"', "a number") for name in p.derived_names()]
    return [
        f'    assert({condition}, "{context}: {name} must be {expected}")\n' for name, condition, expected in checks
    ]


def _class(api: Api, shape: ClassShape, *, heading: str | None) -> str:
    """The class under `heading`, its opaque ref's group docstring where it is the first of
    that group's classes, each of its functions under its own group's where it is the first
    of that group's here."""
    class_display = naming.upper_camel(shape.opaque.class_name)
    cls = f"M.{class_display}"
    headings = {fn.name: h for h, fn in headed(api.function_groups, shape.functions())}
    out = [f"\n{_comment(heading)}{cls} = {{}}\n{cls}.__index = {cls}\n"]
    out.append(_constructor(api, shape, cls=cls, class_display=class_display, heading=headings[shape.ctor.name]))
    guard = _use_guard(shape.opaque)
    drives = shape.drives()
    out += [
        _method(
            api,
            fn,
            cls=cls,
            class_display=class_display,
            guard=guard,
            in_call=_in_call_guard(class_display, fn.name) if drives else "",
            heading=headings[fn.name],
        )
        for fn in shape.methods
    ]
    if shape.dtor is not None:
        in_call = _in_call_guard(class_display, shape.dtor.name) if drives else ""
        out.append(_release(api, shape.dtor, cls=cls, in_call=in_call, heading=headings[shape.dtor.name]))
    return "".join(out)


def _buffer_arg(p: Param) -> str:
    """The Lua-visible name in a buffer's own signature position: the parameter's name
    for `in`/`inout`, where the caller passes a string; its count name for `out`, where
    the caller says how many elements (bytes for `memory`) to allocate instead."""
    return p.count_name() if p.ref == "out" else p.name


def _buffer_alloc(api: Api, p: Param) -> str | None:
    """The buffer a buffer parameter's C pointer reaches: `out` allocates an array of its
    element (bytes for `memory`) sized by the caller's count; `inout` (`memory` only) first
    captures the caller's string length in a local, since a cdata array has no length
    operator once it replaces the string under the same name, then copies the string into a
    buffer that size; an `in` array copies its table into a new cdata array and counts it
    (`copy_array`); `memory` `in` needs no buffer, a Lua string converts straight to
    `const void*`."""
    count = p.count_name()
    element = "uint8_t" if p.type == "memory" else c.c_type(api, p.type)
    if _is_in_array(p):
        return f'    local {p.name}, {count} = {_COPY_ARRAY}("{element}[?]", {p.name})\n'
    if p.ref == "in":
        return None
    if p.ref == "out":
        return f'    local {p.name} = ffi.new("{element}[?]", {count})\n'
    return f"    local {count} = #{p.name}\n" f'    local {p.name} = ffi.new("{element}[?]", {count}, {p.name})\n'


def _buffer_count(p: Param) -> str:
    """The count passed to the C call and, unreported, read back for the returned string:
    `#` of the caller's string for `in`; the count local, either the caller's `out`
    argument or the one `_buffer_alloc` captured for `inout`, otherwise. An `_optional`
    `in` argument's count is 0 when the caller passed `nil` instead of a string. An `in`
    array's is the local `_buffer_alloc` counted it into."""
    if p.ref != "in" or p.type != "memory":
        return p.count_name()
    if p.optional:
        return f"({p.name} and #{p.name} or 0)"
    return f"#{p.name}"


def _marshal(
    api: Api, fn: Function, params: tuple[Param, ...]
) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str], list[str]]:
    """Lua arguments, C call arguments, allocations, the callback casts, the statements right
    after the call, returned values and the checks of what the library reported, made after a
    successful call. A callback is a Lua function, cast to its C type through its trampoline
    for this call alone, `user_data` nil: the casts follow every other allocation and set the
    object's in-call field, so nothing between a cast and its free can raise but the C call;
    once the call returns, on every path, the casts are freed, the field cleared and a failure
    of the function raised before the result is read. An `in` array is a table, copied into a cdata
    array of its element. A `memory` parameter is a Lua
    string, never cdata the consumer sees: `in` passes the caller's string straight through;
    `out` and `inout` allocate a buffer and return its bytes as a string, exactly as a scalar
    `out`/`inout` is returned. An `out` array is allocated as a cdata array of its element and
    returned as that array, never copied. A buffer that reports what it wrote and needs
    returns three values in its position, its data (a string of the bytes it wrote for
    `memory`), what it wrote and what it needs, once checked within its count and its need.
    Every other `out` is allocated and returned rather than taken. A boxed scalar by value
    arrives as its base type's value and is boxed for the call. A union's list is the three
    values a callback receives one as, passed straight through."""
    args, call, allocs, casts, released, rets, checks = [], [], [], [], [], [], []
    fname = naming.function_name(api.namespace, fn.name)
    for p in params:
        if p.callback:
            if not casts:
                casts.append("    local failure = {}\n")
            args.append(p.name)
            c_type = c.c_type(api, p.type)
            casts.append(
                f'    local {p.name} = ffi.cast("{c_type}", {naming.trampoline(p.type)}({p.name}, failure, "{fname}"))\n'
            )
            call += [p.name, "nil"]
            released.append(f"    {p.name}:free()\n")
            continue
        if p.is_union:
            names = [p.name, *p.derived_names()]
            args += names
            call += names
            continue
        if p.is_buffer:
            args.append(_buffer_arg(p))
            alloc = _buffer_alloc(api, p)
            if alloc is not None:
                allocs.append(alloc)
            count = _buffer_count(p)
            reports = p.report_names()
            call += [p.name, count, *reports]
            allocs += [f'    local {report} = ffi.new("{_box(api, p.count_type)}")\n' for report in reports]
            if p.ref == "in":
                continue
            if p.type == "memory":
                rets.append(f"ffi.string({p.name}, {reports[0] + '[0]' if reports else count})")
            else:
                rets.append(p.name)
            if reports:
                wrote, needed = (f"{report}[0]" for report in reports)
                checks.append(
                    f"    assert({wrote} <= {count} and {wrote} <= {needed}, "
                    f'"{fname} over-reported {p.name}: it wrote more than the buffer holds or than the result needs")\n'
                )
                # a u64 count's report stays cdata, the one value LuaJIT cannot hand over as a
                # number exactly; every narrower count's is a number
                rets += [f"{report}[0]" if p.count_type == "u64" else f"tonumber({report}[0])" for report in reports]
            continue
        call.append(p.name)
        if p.ref != "out":
            args.append(p.name)
        if p.ref is None and api.kind(p.type) == "boxed":
            allocs.append(f'    local {p.name} = ffi.new("{c.c_type(api, p.type)}", {p.name})\n')
        if p.ref is not None:
            allocs.append(_alloc(api, p))
            if p.ref != "in":
                rets.append(_read_back(api, p))
    if casts:
        casts.append(f'    self.{_IN_CALL} = "{fname}"\n')
        released.append(f"    self.{_IN_CALL} = nil\n")
        released.append("    if failure.raised then\n        error(failure.error, 0)\n    end\n")
    return args, call, allocs, casts, released, rets, checks


def _call(api: Api, fn: Function, call: list[str], released: list[str]) -> str:
    c_name = naming.function_name(api.namespace, fn.name)
    return f"    local result = lib.{c_name}({', '.join(call)})\n" + "".join(released) + _result_check(api, fn)


def _in_call_guard(class_display: str, name: str) -> str:
    """The statement refusing class function `name` while a call of the object drives a
    callback, naming the function and the driving C function."""
    return (
        f"    if self.{_IN_CALL} ~= nil then\n"
        f'        error("{class_display}.{name}: called while " .. self.{_IN_CALL} .. " is in progress on this '
        f'{class_display}", 2)\n'
        "    end\n"
    )


def _result_check(api: Api, fn: Function) -> str:
    ok = naming.unprefixed_const_name(api.success_entry(fn).name)
    return f"    if result ~= M.{ok} then\n        return nil, result\n    end\n"


def _constructor(api: Api, shape: ClassShape, *, cls: str, class_display: str, heading: str | None) -> str:
    """`new`, which caches every out parameter other than the handle on the object under
    its parameter name."""
    fn, opaque = shape.ctor, shape.opaque
    args, call, allocs, casts, released, _, _ = _marshal(api, fn, fn.params)
    out = [
        _doc_lines(fn, heading),
        f"function {cls}.new({', '.join(args)})\n",
        *_arg_asserts(api, fn.params, context=f"{class_display}.new"),
        *_object_handles(api, fn.params, context=f"{class_display}.new"),
        *allocs,
        *casts,
    ]
    out.append(_call(api, fn, call, released))
    handle_value = f"{shape.handle.name}[0]"
    if opaque.dtor is not None:
        dtor_call = f"lib.{naming.function_name(api.namespace, opaque.dtor)}"
        handle_value = f"ffi.gc({handle_value}, function(h) {dtor_call}(h) end)"
    out.append(f"    local self = setmetatable({{}}, {cls})\n    self._handle = {handle_value}\n")
    out += [f"    self.{p.name} = {_read_back(api, p)}\n" for p in shape.cached]
    out.append("    return self, nil\nend\n")
    return "\n" + "".join(out)


def _method(
    api: Api, fn: Function, *, cls: str, class_display: str, guard: str, in_call: str, heading: str | None
) -> str:
    """A method, its live-handle `guard` and then its `in_call` refusal first; one that takes a
    callback is never JIT-compiled, since LuaJIT forbids a compiled FFI call into a C function
    that calls back into Lua."""
    args, call, allocs, casts, released, rets, checks = _marshal(api, fn, fn.params[1:])
    rets = rets or ["true"]
    return (
        f"\n{_doc_lines(fn, heading)}function {cls}.{fn.name}({', '.join(['self', *args])})\n"
        f"    {guard}\n"
        + in_call
        + "".join(_arg_asserts(api, fn.params[1:], context=f"{class_display}.{fn.name}"))
        + "".join(_object_handles(api, fn.params[1:], context=f"{class_display}.{fn.name}"))
        + "".join(allocs)
        + "".join(casts)
        + _call(api, fn, ["self._handle", *call], released)
        + "".join(checks)
        + f"    return {', '.join(rets)}, nil\nend\n"
        + (f"jit.off({cls}.{fn.name})\n" if released else "")
    )


def _release(api: Api, dtor: Function, *, cls: str, in_call: str, heading: str | None) -> str:
    """The dtor as an explicit method, its `in_call` refusal first: detaches the GC finalizer
    if one is attached, releases whatever _handle holds, or else a NULL handle of its own
    cdata type (the FFI call takes real cdata, never a bare Lua nil; the library answers a
    NULL handle the same as any other), and drops the handle whatever the result."""
    opaque_type = c.c_type(api, dtor.params[0].type)
    return (
        f"\n{_doc_lines(dtor, heading)}function {cls}.{dtor.name}(self)\n"
        + in_call
        + f'    local handle = self._handle or ffi.new("{opaque_type}")\n'
        "    if self._handle ~= nil then\n"
        "        ffi.gc(self._handle, nil)\n"
        "    end\n"
        f"    local result = lib.{naming.function_name(api.namespace, dtor.name)}(handle)\n"
        "    self._handle = nil\n" + _result_check(api, dtor) + "    return true, nil\nend\n"
    )
