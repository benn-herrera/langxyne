"""The Rust binding: the C header's ABI as a nested `ffi` module linked against the
library, and over it the constants, enums, conversions, re-exported types and one owning
struct per opaque ref that names a constructor, every call returning a `Result`."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from langxyne import naming
from langxyne.emitters import emitter, rust
from langxyne.model import (
    Api,
    BitConst,
    ClassShape,
    EnumEntry,
    Function,
    Group,
    Param,
    duplicate_objections,
    generated_name_objections,
    headed,
    named_values,
    single_bit_entries,
)

LABEL = "rust"

_GENERATED_NAMES = ("raw", "result")
"""The locals every class call binds beside the parameters of the function it wraps: the
C call's `raw` result and that result as the enum, `result`."""
_PRELUDE_NAMES = ("Drop", "Err", "Ok", "Option", "Result", "Some", "String")
"""The prelude names the binding spells unqualified, which a module-scope item would shadow."""
_POINTERS_SAFE = (
    "every pointer argument points at a local or a caller reference that lives for the call, "
    "a slice's length its count; the library keeps no pointer after returning."
)
_SAFETY = f"// SAFETY: the handle came from a successful create and is not yet released; {_POINTERS_SAFE}\n"
_SAFETY_CREATE = f"// SAFETY: {_POINTERS_SAFE}\n"
_METHOD = " " * 4
_BODY = " " * 8


def _through_raw_local(api: Api, p: Param, *, ctor: bool) -> bool:
    """Whether the enum parameter `p` travels through its `<p>_raw` local: reached through
    `_ref`, other than an `out` the caller receives, which is a local of its own name."""
    return p.ref is not None and api.kind(p.type) == "enum" and not _received_out(p, ctor=ctor)


def _received_out(p: Param, *, ctor: bool) -> bool:
    """A non-buffer `out` the call writes into a local the caller receives: every one of a
    constructor's, and a method's unless `_optional`, which it takes as an `Option`."""
    return not p.is_buffer and p.ref == "out" and (ctor or not p.optional)


_FILLED_TEXT = f"""/// How much of a caller's buffer a call wrote and how much its whole result needs, in elements
/// (bytes for a byte buffer): `wrote < needed` means the buffer was too short for the whole result.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct {naming.FILLED} {{
    pub wrote: usize,
    pub needed: usize,
}}
"""
"""The struct a method's `Ok` value carries for each buffer that reports what it wrote and
needs, emitted where some method renders one."""


def _renders_filled(classes: tuple[ClassShape, ...]) -> bool:
    """Whether some method renders a buffer that reports what it wrote and needs."""
    return any(p.wrote_needed for shape in classes for fn in shape.methods for p in fn.params)


_TRAMPOLINE_NAMES = ("frame", "running", "failure", "answer", "callback", "value", "panic")
"""The names a trampoline binds or calls beside its callback type's parameters: a callback
parameter named like one would shadow it."""
_FAILURE_LOCAL = "_failure"
"""The method's local `CallbackFailure`, which no definition name can shadow: none begins with `_`."""
_IN_CALL = "_in_call"
"""The class field naming the C function a call of the object is driving a callback in, which no
definition name can take: none begins with `_`."""
_FRAME_TEXT = f"""/// What failed during one driving call, shared by all its callbacks: whether any did, and the
/// first panic, which the method resumes once the call returns.
#[derive(Default)]
struct {naming.CALLBACK_FAILURE} {{
    failed: core::cell::Cell<bool>,
    panic: core::cell::Cell<Option<Box<dyn core::any::Any + Send>>>,
}}

impl {naming.CALLBACK_FAILURE} {{
    /// Records a failure, keeping the first panic; a later one is dropped where a panic in its
    /// own drop cannot unwind out of the trampoline.
    fn record(&self, panic: Box<dyn core::any::Any + Send>) {{
        if self.failed.replace(true) {{
            let _ = std::panic::catch_unwind(core::panic::AssertUnwindSafe(move || drop(panic)));
        }} else {{
            self.panic.set(Some(panic));
        }}
    }}
}}

/// A closure a method passes the library as a callback, for the call that drives it: that
/// call's thread and C function, whether an invocation of it is running, and the call's
/// failure record.
struct {naming.CALLBACK_FRAME}<'a, F> {{
    callback: F,
    thread: std::thread::ThreadId,
    function: &'static str,
    running: core::cell::Cell<bool>,
    failure: &'a {naming.CALLBACK_FAILURE},
}}
"""


def _rendered_callbacks(api: Api, classes: tuple[ClassShape, ...]) -> list[Function]:
    """The callback types some method takes a parameter of, in document order: the ones
    whose trampoline the binding renders."""
    used = {p.type for shape in classes for fn in shape.methods for p in fn.params if p.callback}
    return [cb for cb in api.callbacks if cb.name in used]


def _views(callbacks: list[Function]) -> bool:
    """Whether some of `callbacks` takes a view other than a union's list, which the trampoline
    reads through `c_slice`."""
    return any(p.is_buffer and not p.is_union for cb in callbacks for p in cb.params)


def _sequence_views(callbacks: list[Function]) -> set[str]:
    """The unions some of `callbacks` takes a list of, which the trampoline reads through the
    sequence's `from_c`."""
    return {p.type for cb in callbacks for p in cb.params if p.is_union}


def validate(api: Api) -> list[str]:
    """Every objection the Rust binding has to `api`: a name that is a Rust keyword or
    renders as one in UpperCamel; a name the file renders where rustc's `non_snake_case`
    reaches it that the lint refuses; a field of opaque type; a parameter a class renders
    named like one of `_GENERATED_NAMES` or an enum local its function renders; a name
    the binding would define twice at module scope, in an enum or in a class; and no
    library named."""
    objections = rust.rust_keyword_objections(api)
    objections += rust.camel_keyword_objections(
        [
            *rust.camel_names(api),
            *((f"opaque_ref.{o.name}._class", o.class_name) for o in api.opaque_refs if o.ctor is not None),
        ]
    )

    classes = api.classes()
    groups = [g for g in (*api.bit_const_groups, *api.const_groups) if g.to_string is not None]
    lints = rust.field_names(api)
    lints += [(f"{g.name}._to_string", g.to_string) for g in groups]
    lints += rust.enum_conversion_names(api)
    generated = []
    for shape in classes:
        lints += [(f"function.{fn.name}", fn.name) for fn in shape.methods]
        for fn, params, ctor in shape.class_params():
            raw_locals = [
                (f"function.{fn.name}.{p.name}", naming.rust_raw_local(p.name))
                for p in params
                if _through_raw_local(api, p, ctor=ctor)
            ]
            # the binding renders no parameter a callback derives where the lint reaches it
            lints += [
                (f"function.{fn.name}.{p.name}", name)
                for p in params
                for name in (p.name, *(() if p.callback else p.derived_names()))
            ]
            lints += raw_locals
            generated += generated_name_objections(
                ((f"function.{fn.name}.{p.name}", p.name) for p in params),
                {*_GENERATED_NAMES, *(local for _, local in raw_locals)},
            )
    callbacks = _rendered_callbacks(api, classes)
    for cb in callbacks:
        lints.append((f"callback.{cb.name}", naming.trampoline(cb.name)))
        lints += rust.param_names(f"callback.{cb.name}", cb.params)
        generated += generated_name_objections(
            ((f"callback.{cb.name}.{p.name}", p.name) for p in cb.params), _TRAMPOLINE_NAMES
        )
    objections += rust.snake_case_objections(lints)
    objections += rust.opaque_field_objections(api)
    objections += generated

    module = rust.prelude_names(_PRELUDE_NAMES)
    constants = api.constant_names(enum_entries=False, version=True)
    module += [(where, naming.unprefixed_const_name(name)) for where, name in constants]
    module += [(f"{g.name}._to_string", g.to_string) for g in groups]
    module += rust.module_names(api)
    module += rust.union_module_names(api, relay=False)
    if _renders_filled(classes):
        module.append(("the generated struct of a reported buffer", naming.FILLED))
    if _views(callbacks):
        module += [("the binding's view helper", name) for name, _ in rust.slice_helpers({"in"})]
    if callbacks:
        module.append(("the binding's callback failure", naming.CALLBACK_FAILURE))
        module.append(("the binding's callback frame", naming.CALLBACK_FRAME))
    module += [(f"callback.{cb.name}", naming.trampoline(cb.name)) for cb in callbacks]
    module += [(f"opaque_ref.{s.opaque.name}._class", naming.upper_camel(s.opaque.class_name)) for s in classes]
    objections += duplicate_objections(module, "module scope")
    objections += rust.enum_member_objections(api)
    objections += rust.union_member_objections(api)
    for shape in classes:
        own = ["create", "handle", *(["release"] if shape.dtor is not None else [])]
        objections += duplicate_objections(shape.members(own), f"class {naming.upper_camel(shape.opaque.class_name)}")
    if api.library.name is None:
        objections.append(emitter.NO_LIBRARY)
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("rust") / f"{name}.rs"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The Rust binding, as rustfmt lays it out, its `ffi` module linked against the library."""
    blocks = [rust.version_constant(api, prefixed=False)]
    blocks += [rust.constant_group(api, g, prefixed=False) + _bit_to_string(g) for g in api.bit_const_groups]
    blocks += [rust.constant_group(api, g, prefixed=False) + _plain_to_string(g) for g in api.const_groups]
    blocks += [rust.string_group(api, g, prefixed=False) for g in api.string_const_groups]
    blocks += rust.enum_blocks(api)
    blocks.append(rust.reexports(api))
    if api.uses_text():
        blocks.append(_text_resolve())
    blocks += rust.union_blocks(api)
    classes = api.classes()
    if _renders_filled(classes):
        blocks.append(_FILLED_TEXT)
    callbacks = _rendered_callbacks(api, classes)
    viewed = _sequence_views(callbacks)
    blocks += [rust.sequence_constructor(api, u) for u in api.unions if u.name in viewed]
    if _views(callbacks):
        blocks += [text for _, text in rust.slice_helpers({"in"})]
    if callbacks:
        blocks.append(_FRAME_TEXT)
    blocks += [_trampoline(api, cb) for cb in callbacks]
    opaque_headings = {o.name: h for h, o in headed(api.opaque_ref_groups, (s.opaque for s in classes))}
    blocks += [_class(api, shape, heading=opaque_headings[shape.opaque.name]) for shape in classes]
    return rust.rustfmt(f"// {emitter.banner(source_name)}\n\n" + _ffi(api) + "".join("\n" + b for b in blocks))


def _text_resolve() -> str:
    """`Text::resolve`, the bytes of whatever arena a text's run indexes, which the caller names;
    `None` where the run leaves it."""
    offset, length = naming.TEXT_OFFSET, naming.TEXT_LENGTH
    return (
        f"impl {naming.upper_camel(naming.TEXT)} {{\n"
        "    /// The bytes of `arena` this run covers; `None` where the run leaves `arena`.\n"
        f"    pub fn {naming.RESOLVE}<'a>(&self, arena: &'a [u8]) -> Option<&'a [u8]> {{\n"
        f"        let ({offset}, {length}) = (self.{offset} as usize, self.{length} as usize);\n"
        f"        arena.get({offset}..{offset}.checked_add({length})?)\n"
        "    }\n"
        "}\n"
    )


def _usize(count_type: str, value: str, *, message: str) -> str:
    """`value`, of the count type, as a `usize`: by `From` where every value fits, since
    clippy refuses a fallible conversion there, else by `TryFrom`, panicking with `message`."""
    if count_type in ("u8", "u16"):
        return f"usize::from({value})"
    return f'usize::try_from({value}).expect("{message}")'


def _link_attribute(api: Api) -> str:
    """The `#[link]` naming the library, which the platform's linker turns into its file name.
    A static link defers the archive's search to the final link (`-bundle`), so a crate
    holding the binding builds as a lib with no archive present."""
    static = ', kind = "static", modifiers = "-bundle"' if api.library.link == naming.STATIC else ""
    return f'#[link(name = "{api.library.name}"{static})]'


def _ffi(api: Api) -> str:
    """The `ffi` module: the C header's types under their C names, and every function in
    one `extern` block linked against the library."""
    types = [rust.group_comment(h) + rust.enum_alias(api, t) for h, t in headed(api.typed_const_groups)]
    types += rust.type_definitions(api)
    extern = ""
    if api.functions:
        declarations = "\n".join(
            rust.group_comment(h, indent=_BODY)
            + rust.function_docs(fn, indent=_BODY)
            + _BODY
            + rust.signature(api, fn, prefix="pub fn ")
            + ";\n"
            for h, fn in headed(api.function_groups)
        )
        extern = f'\n    {_link_attribute(api)}\n    unsafe extern "C" {{\n{declarations}    }}\n'
    return rust.ffi_module(types, tail=extern)


def _plain_to_string(group: Group[EnumEntry]) -> str:
    """A `match` on the group's constants, one arm per value as `named_values()` names it,
    since a repeated pattern is unreachable and `-D warnings` refuses it."""
    if group.to_string is None:
        return ""
    arms = "".join(
        f'        {k} => "{k}",\n' for k in (naming.unprefixed_const_name(e.name) for e in named_values(group))
    )
    return (
        f"\npub fn {group.to_string}(value: {group.base_type}) -> &'static str {{\n"
        f"    match value {{\n{arms}"
        f'        _ => "{naming.unknown_value_name(None)}",\n'
        "    }\n}\n"
    )


def _bit_to_string(group: Group[BitConst]) -> str:
    """Each single-bit entry present in the value, in document order, joined with `|`, and
    whatever bits remain as one final hex term."""
    if group.to_string is None:
        return ""
    keys = [naming.unprefixed_const_name(e.name) for e in single_bit_entries(group)]
    flags = "".join(
        f'    if value & {k} != 0 {{\n        text += "|{k}";\n        value &= !{k};\n    }}\n' for k in keys
    )
    mutable = "mut " if keys else ""
    return (
        f"\npub fn {group.to_string}({mutable}value: {group.base_type}) -> String {{\n"
        f'    if value == 0 {{\n        return String::from("{naming.NO_FLAGS}");\n    }}\n'
        "    let mut text = String::new();\n"
        f"{flags}"
        "    if value != 0 {\n"
        '        text += &format!("|{value:#x}");\n'
        "    }\n"
        "    text[1..].to_string()\n"
        "}\n"
    )


def _safe_type(api: Api, type_name: str) -> str:
    """The module-scope spelling of a non-memory type: an enum by its UpperCamel name,
    anything else as `rust.value_type()` spells it."""
    if api.kind(type_name) == "enum":
        return naming.upper_camel(type_name)
    return rust.value_type(api, type_name)


def _closure_bound(api: Api, callback: Function) -> str:
    """The closure a method takes for `callback`: a view a slice of bytes or of its element, or
    a union's list its sequence, an enum its enum, a builtin itself; it answers the return
    enum. The views' elided lifetimes are higher-ranked, so a closure keeping one, or a record
    of a sequence, does not compile."""
    params = []
    for p in callback.params:
        if p.is_union:
            params.append(f"{naming.union_sequence(p.type)}<'_>")
        elif p.is_buffer:
            params.append(f"&[{'u8' if p.type == 'memory' else _safe_type(api, p.type)}]")
        else:
            params.append(_safe_type(api, p.type))
    return f"FnMut({', '.join(params)}) -> {naming.upper_camel(callback.returns)}"


def _trampoline(api: Api, callback: Function) -> str:
    """`<c>_trampoline`, which gives the C function calling a frame's closure: on another
    thread than the driving call's it aborts, naming the callback type and the C function;
    where the call's failure is recorded it answers the stop entry, and where an invocation of
    the frame is running it records that as the call's failure and answers the stop entry,
    reaching the closure in neither case; otherwise it reads each view and enum, calls the
    closure and answers its enum, all under `catch_unwind`, a panic recorded as the call's
    failure and answered with the stop entry, so nothing unwinds through the library. It reads
    `thread` and `function` by place and borrows `running` and `failure` by field, borrowing
    only `callback` mutably, so no two invocations hold overlapping references."""
    c_type = naming.type_name(api.namespace, callback.name)
    ffi_return = rust.rust_type(api, callback.returns, path="ffi::")
    stop = (
        f"{naming.upper_camel(callback.returns)}::{naming.upper_camel(api.stop_entry(callback).name)} as {ffi_return}"
    )
    bound = _closure_bound(api, callback)
    c_params = rust.callback_c_params(api, callback, path="ffi::")
    frame_type = f"{naming.CALLBACK_FRAME}<'_, F>"
    views = any(p.is_buffer for p in callback.params)
    safety = (
        [
            "// SAFETY: `running` was clear, so no other borrow of the callback exists; each view is the",
            "// library's pointer and count for this call of the callback.",
        ]
        if views
        else ["// SAFETY: `running` was clear, so no other borrow of the callback exists."]
    )
    reads = [*safety, "let callback = unsafe { &mut (*frame).callback };"]
    for p in callback.params:
        if p.is_union:
            sequence = naming.union_sequence(p.type)
            reads.append(
                f"let {p.name} = unsafe {{ {sequence}::from_c({p.name}, {p.count_name()}, {p.bytes_name()}) }}"
                f'.expect("{c_type} received view {p.name} outside the definition");'
            )
        elif p.is_buffer:
            pointer = f"{p.name}.cast::<u8>()" if p.type == "memory" else p.name
            reads.append(
                f"let {p.name} = unsafe {{ self::{rust.SLICE_HELPERS['in']}({pointer}, {p.count_name()}) }}"
                f'.expect("{c_type} received view {p.name} outside the definition");'
            )
        elif api.kind(p.type) == "enum":
            enum = naming.upper_camel(p.type)
            reads.append(
                f'let {p.name} = {enum}::try_from({p.name}).expect("{c_type} received a {p.name} value '
                f'{naming.type_name(api.namespace, p.type)} does not name");'
            )
    reads.append(f"callback({', '.join(p.name for p in callback.params)})")
    body = [
        f"let frame = {naming.USER_DATA}.cast::<{frame_type}>();",
        "// SAFETY: user_data is the frame the driving call passed beside this function, alive for that",
        "// call; `thread` and `function` are never written, and nothing borrows the whole frame.",
        "if std::thread::current().id() != unsafe { (*frame).thread } {",
        f'    eprintln!("{c_type} called on another thread than the one calling {{}}", unsafe {{ (*frame).function }});',
        "    std::process::abort();",
        "}",
        "// SAFETY: as above, on the driving call's thread; `running` and `failure` are disjoint from",
        "// `callback`, the one field borrowed mutably, below.",
        "let (running, failure) = unsafe { (&(*frame).running, (*frame).failure) };",
        f"if failure.failed.get() {{ return {stop}; }}",
        "if running.replace(true) {",
        "    failure.record(Box::new(format!(",
        f'        "{c_type} called again while a call of it was running in {{}}",',
        "        unsafe { (*frame).function }",
        "    )));",
        f"    return {stop};",
        "}",
        "// UnwindSafe: no consumer code of this driving call runs between a caught panic and its",
        "// resumption, since a recorded failure stops every callback of the call.",
        "let answer = std::panic::catch_unwind(core::panic::AssertUnwindSafe(|| {",
        *(f"    {r}" for r in reads),
        "}));",
        "running.set(false);",
        "match answer {",
        f"    Ok(value) if !failure.failed.get() => value as {ffi_return},",
        f"    Ok(_) => {stop},",
        f"    Err(panic) => {{ failure.record(panic); {stop} }}",
        "}",
    ]
    return (
        f"/// The C function calling a frame's closure as `{c_type}`; the frame is its `user_data`.\n"
        f"fn {naming.trampoline(callback.name)}<F: {bound}>(_frame: &{frame_type}) -> "
        f"{rust.rust_type(api, callback.name, path='ffi::')} {{\n"
        + rust.many_arguments_allow(len(c_params), indent=_METHOD)
        + f'{_METHOD}unsafe extern "C" fn trampoline<F: {bound}>({", ".join(f"{n}: {t}" for t, n in c_params)}) -> '
        f"{ffi_return} {{\n" + "".join(f"{_BODY}{line}\n" for line in body) + f"{_METHOD}}}\n"
        f"{_METHOD}Some(trampoline::<F>)\n"
        "}\n"
    )


def _wrote(api: Api, fn: Function, p: Param) -> str:
    """The panic message of an enum value `fn` wrote through `p` that the enum does not name."""
    fname = naming.function_name(api.namespace, fn.name)
    return f"{fname} wrote a {p.name} value {naming.type_name(api.namespace, p.type)} does not name"


@dataclass
class _Marshalled:
    """A function's parameters as the safe layer renders them around one C call."""

    params: list[str] = field(default_factory=list)  # the Rust signature's `name: type`
    guards: list[str] = field(default_factory=list)  # refusals of an object argument in a driving call, first
    before: list[str] = field(default_factory=list)  # statements before the call
    args: list[str] = field(default_factory=list)  # the C call's arguments, in order
    resume: list[str] = field(default_factory=list)  # statements right after the call, before its result is read
    after: list[str] = field(default_factory=list)  # statements after a successful result
    outs: list[tuple[str, str]] = field(default_factory=list)  # (type, value) of each out the caller receives
    unchecked: list[str] = field(default_factory=list)  # raw handles the caller vouches for


def _marshal(api: Api, fn: Function, params: tuple[Param, ...], *, ctor: bool, ctx: str) -> _Marshalled:
    """`params` of `fn` as signature parameters, locals, call arguments and the conversions
    after a successful call. A buffer is a slice whose length is its count; one that reports
    what it wrote and needs gives the caller a `Filled` of the reports, checked first to be
    within the slice and the need. A non-buffer `out` is a local the call writes and the caller
    receives, unless it is `_optional` outside a constructor, which takes it as an
    `Option`. An enum reached through `_ref` is a reference to the enum, which cannot
    coerce to a pointer to its base type: it travels through a local of that type. An
    opaque by value or `in` is its class by reference where it has one; an opaque the
    library may replace, `out` or `inout`, is the raw handle even where it has a class,
    whose own handle it would orphan. A raw handle the library reads, one without a class
    by value, `in` or `inout` or one with a class `inout`, makes the function unsafe. A
    callback is a closure borrowed for the call, which a frame on the stack holds, its
    `user_data`; the method's frames share one failure record, whose first panic resumes once
    the call returns. An object argument whose class drives a callback is refused while a call
    of it does, as the receiver is, `ctx` naming the method in the panic where the return enum
    has no entry to answer; a released one cannot be passed, `release` consuming it."""
    shapes = {shape.opaque.name: shape for shape in api.classes()}
    classes = {name: naming.upper_camel(shape.opaque.class_name) for name, shape in shapes.items()}
    m = _Marshalled()
    for p in params:
        if p.is_union:
            _marshal_sequence(api, p, into=m)
            continue
        if p.is_buffer:
            _marshal_buffer(api, fn, p, into=m)
            continue
        if p.callback:
            if not m.resume:
                m.before.append(f"let {_FAILURE_LOCAL} = {naming.CALLBACK_FAILURE}::default();")
                m.resume.append(
                    f"if let Some(panic) = {_FAILURE_LOCAL}.panic.take() {{ std::panic::resume_unwind(panic); }}"
                )
            fname = naming.function_name(api.namespace, fn.name)
            m.params.append(f"{p.name}: impl {_closure_bound(api, api.callback(p.type))}")
            m.before.append(
                f"let mut {p.name} = {naming.CALLBACK_FRAME} {{ callback: {p.name}, "
                f'thread: std::thread::current().id(), function: "{fname}", '
                f"running: core::cell::Cell::new(false), failure: &{_FAILURE_LOCAL} }};"
            )
            m.args += [f"self::{naming.trampoline(p.type)}(&{p.name})", f"core::ptr::from_mut(&mut {p.name}).cast()"]
            continue
        kind = api.kind(p.type)
        if kind == "opaque" and p.ref in (None, "in") and p.type in shapes and shapes[p.type].drives():
            m.guards.append(_argument_guard(api, fn, p, cls=classes[p.type], ctx=ctx))
        if _received_out(p, ctor=ctor):
            m.before.append(f"let mut {p.name} = {rust.out_default(api, p.type)}();")
            if kind == "enum":
                enum = naming.upper_camel(p.type)
                m.after.append(f'let {p.name} = {enum}::try_from({p.name}).expect("{_wrote(api, fn, p)}");')
            m.args.append(f"&mut {p.name}")
            m.outs.append((_safe_type(api, p.type), p.name))
        elif _through_raw_local(api, p, ctor=ctor):
            _marshal_enum_ref(api, fn, p, into=m)
        elif kind == "opaque" and p.ref == "in" and p.type in classes:
            if p.optional:
                m.params.append(f"{p.name}: Option<&{classes[p.type]}>")
                m.args.append(f"{p.name}.map_or(core::ptr::null(), |c| &c.handle)")
            else:
                m.params.append(f"{p.name}: &{classes[p.type]}")
                m.args.append(f"&{p.name}.handle")
        elif p.ref is not None:
            if kind == "opaque" and p.ref != "out":
                m.unchecked.append(p.name)
            safe = _safe_type(api, p.type)
            if p.ref == "in":
                m.params.append(f"{p.name}: Option<&{safe}>" if p.optional else f"{p.name}: &{safe}")
                m.args.append(f"{p.name}.map_or(core::ptr::null(), core::ptr::from_ref)" if p.optional else p.name)
            else:
                m.params.append(f"{p.name}: Option<&mut {safe}>" if p.optional else f"{p.name}: &mut {safe}")
                m.args.append(f"{p.name}.map_or(core::ptr::null_mut(), core::ptr::from_mut)" if p.optional else p.name)
        elif kind == "enum":
            m.params.append(f"{p.name}: {naming.upper_camel(p.type)}")
            m.args.append(f"{p.name} as {rust.rust_type(api, p.type, path='ffi::')}")
        elif kind == "opaque" and p.type in classes:
            m.params.append(f"{p.name}: &{classes[p.type]}")
            m.args.append(f"{p.name}.handle")
        else:
            if kind == "opaque":
                m.unchecked.append(p.name)
            m.params.append(f"{p.name}: {_safe_type(api, p.type)}")
            m.args.append(p.name)
    return m


def _argument_guard(api: Api, fn: Function, p: Param, *, cls: str, ctx: str) -> str:
    """The refusal of object argument `p`, of class `cls`, while a call of it drives a
    callback: `Err` with the first non-zero entry of `fn`'s return enum, or where that enum has
    none a panic naming `ctx`, the parameter and the driving C function."""
    entry = api.first_nonzero_entry(fn)
    if entry is not None:
        refused = f"return Err({naming.upper_camel(fn.returns)}::{naming.upper_camel(entry.name)});"
        if p.optional:
            return f"if {p.name}.is_some_and(|p| p.{_IN_CALL}.get().is_some()) {{ {refused} }}"
        return f"if {p.name}.{_IN_CALL}.get().is_some() {{ {refused} }}"
    driving = f"{p.name}.and_then(|p| p.{_IN_CALL}.get())" if p.optional else f"{p.name}.{_IN_CALL}.get()"
    return (
        f"if let Some(driving) = {driving} {{ "
        f'panic!("{ctx}: {p.name} is a {cls} while {{driving}} is in progress on it"); }}'
    )


def _marshal_buffer(api: Api, fn: Function, p: Param, *, into: _Marshalled) -> None:
    """A buffer parameter of `fn` as a slice of bytes or of its element, its count the slice's
    length, a length the count type cannot hold panicking. Each report is a local of the count
    type the call writes; after a successful call the reports are checked against the count
    and each other, a library answering outside them panicking, and become a `Filled`."""
    count, reports = p.count_name(), p.report_names()
    element = "u8" if p.type == "memory" else _safe_type(api, p.type)
    cast = ".cast()" if p.type == "memory" else ""
    if api.kind(p.type) == "enum":  # an `in` array: each enum is its base type
        cast = f".cast::<{rust.rust_type(api, p.type, path='ffi::')}>()"
    if p.ref == "in" and p.optional:
        into.params.append(f"{p.name}: Option<&[{element}]>")
        length = f"{p.name}.map_or(0, <[{element}]>::len)"
        into.args.append(f"{p.name}.map_or(core::ptr::null(), <[{element}]>::as_ptr){cast}")
    elif p.ref == "in":
        into.params.append(f"{p.name}: &[{element}]")
        length = f"{p.name}.len()"
        into.args.append(f"{p.name}.as_ptr(){cast}")
    else:
        into.params.append(f"{p.name}: &mut [{element}]")
        length = f"{p.name}.len()"
        into.args.append(f"{p.name}.as_mut_ptr(){cast}")
    into.before.append(
        f'let {count} = {p.count_type}::try_from({length}).expect("{p.name} is longer than {p.count_type} can count");'
    )
    into.args.append(count)
    if not reports:
        return
    wrote, needed = reports
    fname = naming.function_name(api.namespace, fn.name)
    for report in reports:
        into.before.append(f"let mut {report} = {rust.out_default(api, p.count_type)}();")
        into.args.append(f"&mut {report}")
    into.after.append(
        f'assert!({wrote} <= {count} && {wrote} <= {needed}, "{fname} over-reported {p.name}: '
        'it wrote more than the buffer holds or than the result needs");'
    )
    unheld = f"{fname} reported a size of {p.name} usize cannot hold"
    filled = ", ".join(
        f"{field}: {_usize(p.count_type, report, message=unheld)}"
        for field, report in zip(("wrote", "needed"), reports)
    )
    into.outs.append((naming.FILLED, f"{naming.FILLED} {{ {filled} }}"))


def _marshal_sequence(api: Api, p: Param, *, into: _Marshalled) -> None:
    """A union's list parameter as its sequence, `Option` of it where `_optional` (null, 0 and
    0 for `None`), passed as its pointer, count and byte extent."""
    sequence = naming.union_sequence(p.type)
    if p.optional:
        into.params.append(f"{p.name}: Option<{sequence}<'_>>")
        pointer = f"{p.name}.map_or(core::ptr::null(), |s| s.bytes().as_ptr())"
        count, length = f"{p.name}.map_or(0, |s| s.count())", f"{p.name}.map_or(0, |s| s.bytes().len())"
    else:
        into.params.append(f"{p.name}: {sequence}<'_>")
        pointer, count, length = f"{p.name}.bytes().as_ptr()", f"{p.name}.count()", f"{p.name}.bytes().len()"
    statements, args = rust.sequence_arguments(p, pointer=pointer, count=count, length=length, context="")
    into.before += statements
    into.args += args


def _marshal_enum_ref(api: Api, fn: Function, p: Param, *, into: _Marshalled) -> None:
    """An enum parameter of `fn` that travels through its `<p>_raw` local: its value
    converted into that local of the base type, passed by address, and for a writable one
    converted back after a successful call. An `_optional` `out` travels as an `inout` does."""
    enum = naming.upper_camel(p.type)
    raw = naming.rust_raw_local(p.name)
    ffi_type = rust.rust_type(api, p.type, path="ffi::")
    back = f'{enum}::try_from({{}}).expect("{_wrote(api, fn, p)}")'
    if p.ref == "in" and p.optional:
        into.params.append(f"{p.name}: Option<&{enum}>")
        into.before.append(f"let {raw} = {p.name}.map(|m| *m as {ffi_type});")
        into.args.append(f"{raw}.as_ref().map_or(core::ptr::null(), core::ptr::from_ref)")
    elif p.ref == "in":
        into.params.append(f"{p.name}: &{enum}")
        into.before.append(f"let {raw} = *{p.name} as {ffi_type};")
        into.args.append(f"&{raw}")
    elif p.optional:
        into.params.append(f"{p.name}: Option<&mut {enum}>")
        into.before.append(f"let mut {raw} = {p.name}.as_deref().map(|m| *m as {ffi_type});")
        into.args.append(f"{raw}.as_mut().map_or(core::ptr::null_mut(), core::ptr::from_mut)")
        into.after.append(f"if let (Some(m), Some(v)) = ({p.name}, {raw}) {{ *m = {back.format('v')}; }}")
    else:
        into.params.append(f"{p.name}: &mut {enum}")
        into.before.append(f"let mut {raw} = *{p.name} as {ffi_type};")
        into.args.append(f"&mut {raw}")
        into.after.append(f"*{p.name} = {back.format(raw)};")


def _checked_call(
    api: Api,
    fn: Function,
    args: list[str],
    *,
    safety: str,
    before: list[str],
    after: list[str],
    ok: str,
    resume: Sequence[str] = (),
    drives: bool = False,
) -> str:
    """A method body: `before`, the call under its `safety` comment, `resume`, the result
    converted and checked, `after`, then `ok`, the success value. Where the call `drives` a
    callback, the object's in-call field names the C function for the call's duration."""
    fname = naming.function_name(api.namespace, fn.name)
    ret = naming.upper_camel(fn.returns)
    unnamed = f"{fname} returned a value {naming.type_name(api.namespace, fn.returns)} does not name"
    statements = [
        *before,
        *([f'self.{_IN_CALL}.set(Some("{fname}"));'] if drives else []),
        safety.rstrip("\n"),
        f"let raw = unsafe {{ ffi::{fname}({', '.join(args)}) }};",
        *([f"self.{_IN_CALL}.set(None);"] if drives else []),
        *resume,
        f'let result = {ret}::try_from(raw).expect("{unnamed}");',
        f"if result != {ret}::{naming.upper_camel(api.success_entry(fn).name)} {{ return Err(result); }}",
        *after,
        ok,
    ]
    return "".join(f"{_BODY}{s}\n" for s in statements)


def _in_call_guard(api: Api, fn: Function, *, cls: str) -> list[str]:
    """The statement refusing method `fn` of class `cls` while a call of the object drives a
    callback: `Err` with the first non-zero entry of its return enum, or where that enum has
    none a panic naming the class, the method and the driving C function."""
    entry = api.first_nonzero_entry(fn)
    if entry is not None:
        refused = f"{naming.upper_camel(fn.returns)}::{naming.upper_camel(entry.name)}"
        return [f"if self.{_IN_CALL}.get().is_some() {{ return Err({refused}); }}"]
    return [
        f"if let Some(driving) = self.{_IN_CALL}.get() {{ "
        f'panic!("{cls}::{fn.name} called while {{driving}} is in progress on this {cls}"); }}'
    ]


def _method(
    api: Api,
    fn: Function,
    *,
    name: str,
    receiver: list[str],
    m: _Marshalled,
    returns: str,
    body: str,
    heading: str | None,
) -> str:
    """A method `name` over `fn` with `receiver` before `m`'s parameters, returning
    `Result<returns, R>`, `R` the result enum, under `heading`, the docstring of the group
    `fn` is the first of in its class; unsafe, with a `# Safety` section, where it takes a
    raw handle."""
    safety = [f"`{n}` must be a handle the library issued and has not yet destroyed." for n in m.unchecked]
    qualifier = "pub unsafe fn" if safety else "pub fn"
    params = [*receiver, *m.params]
    return (
        rust.group_comment(heading, indent=_METHOD)
        + rust.function_docs(fn, safety=safety, indent=_METHOD)
        + rust.many_arguments_allow(len(params), indent=_METHOD)
        + f"{_METHOD}{qualifier} {name}({', '.join(params)}) -> "
        + f"Result<{returns}, {naming.upper_camel(fn.returns)}> {{\n"
        + body
        + f"{_METHOD}}}\n"
    )


def _class(api: Api, shape: ClassShape, *, heading: str | None) -> str:
    """The class under `heading`, its opaque ref's group docstring where it is the first of
    that group's classes, each of its functions under its own group's where it is the first
    of that group's here."""
    ns = api.namespace
    opaque, ctor, dtor, cached = shape.opaque, shape.ctor, shape.dtor, shape.cached
    cls = naming.upper_camel(opaque.class_name)
    handle_type = rust.rust_type(api, opaque.name, path="ffi::")
    headings = {fn.name: h for h, fn in headed(api.function_groups, shape.functions())}
    drives = shape.drives()

    in_call = [f"    {_IN_CALL}: core::cell::Cell<Option<&'static str>>,\n"] if drives else []
    fields = "".join([*in_call, *(f"    {p.name}: {_safe_type(api, p.type)},\n" for p in cached)])
    struct = (
        f"{rust.group_comment(heading)}{rust.doc_comment(opaque.docstring)}"
        f"pub struct {cls} {{\n    handle: {handle_type},\n{fields}}}\n"
    )

    m = _marshal(api, ctor, ctor.params, ctor=True, ctx=f"{cls}::create")
    # a ctor out named `handle` initialises the field by shorthand, as clippy requires
    handle = "handle" if shape.handle.name == "handle" else f"handle: {shape.handle.name}"
    initial = [f"{_IN_CALL}: core::cell::Cell::new(None)"] if drives else []
    ok = f"Ok({cls} {{ {', '.join([handle, *initial, *(p.name for p in cached)])} }})"
    members = [
        _method(
            api,
            ctor,
            name="create",
            receiver=[],
            m=m,
            returns=cls,
            heading=headings[ctor.name],
            body=_checked_call(
                api, ctor, m.args, safety=_SAFETY_CREATE, before=[*m.guards, *m.before], after=m.after, ok=ok
            ),
        ),
        f"{_METHOD}pub fn handle(&self) -> {handle_type} {{\n{_BODY}self.handle\n{_METHOD}}}\n",
    ]
    members += [
        (
            f"{_METHOD}pub fn {p.name}(&self) -> &{_safe_type(api, p.type)} {{\n{_BODY}&self.{p.name}\n{_METHOD}}}\n"
            if api.kind(p.type) == "struct"
            else f"{_METHOD}pub fn {p.name}(&self) -> {_safe_type(api, p.type)} {{\n{_BODY}self.{p.name}\n{_METHOD}}}\n"
        )
        for p in cached
    ]
    for fn in shape.methods:
        m = _marshal(api, fn, fn.params[1:], ctor=False, ctx=f"{cls}::{fn.name}")
        types, values = [t for t, _ in m.outs], [v for _, v in m.outs]
        if len(m.outs) == 1:
            returns, ok = types[0], f"Ok({values[0]})"
        else:
            returns, ok = f"({', '.join(types)})", f"Ok(({', '.join(values)}))"
        body = _checked_call(
            api,
            fn,
            ["self.handle", *m.args],
            safety=_SAFETY,
            before=[*(_in_call_guard(api, fn, cls=cls) if drives else []), *m.guards, *m.before],
            after=m.after,
            ok=ok,
            resume=m.resume,
            drives=any(p.callback for p in fn.params),
        )
        members.append(
            _method(
                api,
                fn,
                name=fn.name,
                receiver=["&self"],
                m=m,
                returns=returns,
                body=body,
                heading=headings[fn.name],
            )
        )
    drop = ""
    if dtor is not None:
        release = _checked_call(
            api,
            dtor,
            ["handle"],
            safety=_SAFETY,
            before=["let handle = self.handle;", "core::mem::forget(self);"],
            after=[],
            ok="Ok(())",
        )
        members.append(
            _method(
                api,
                dtor,
                name="release",
                receiver=["self"],
                m=_Marshalled(),
                returns="()",
                body=release,
                heading=headings[dtor.name],
            )
        )
        drop = (
            f"\nimpl Drop for {cls} {{\n{_METHOD}fn drop(&mut self) {{\n{_BODY}if !self.handle.is_null() {{\n"
            f"{_BODY}    {_SAFETY}"
            f"{_BODY}    let _ = unsafe {{ ffi::{naming.function_name(ns, dtor.name)}(self.handle) }};\n"
            f"{_BODY}}}\n{_METHOD}}}\n}}\n"
        )
    unwind_safe = (
        f"\n/// `{_IN_CALL}` is cleared before any panic is resumed, and a panic that escapes with it set\n"
        "/// leaves the object refusing every method: poisoned, never unsound.\n"
        f"impl std::panic::RefUnwindSafe for {cls} {{}}\n"
        if drives
        else ""
    )
    return struct + f"\nimpl {cls} {{\n" + "\n".join(members) + "}\n" + drop + unwind_safe
