"""The Rust ABI relay: the C header's ABI as `no_mangle` functions, each relaying its call
to the implementation's `crate::f` through values the relay owns, regenerated with the
definition while the implementation behind it is written by hand."""

from pathlib import Path

from langxyne import naming
from langxyne.emitters import c, emitter, rust
from langxyne.model import (
    Api,
    Function,
    Param,
    Union,
    WrappedApi,
    duplicate_objections,
    generated_name_objections,
    headed,
)

LABEL = "rust_abi"

_SAFETY = (
    "Every pointer argument must be null or valid for the call as the C header declares it, "
    "no buffer may overlap another argument of the same call, "
    "and no other thread may read or write a buffer argument during the call. "
    "A panic in the implementation aborts the process."
)
_GENERATED_NAMES = ("result",)
"""The local a relay function binds its implementation's result to before the write-backs,
which then reach each `out` and `inout` pointer parameter by its name."""
_PRELUDE_NAMES = ("Err", "None", "Ok", "Option", "Result", "Some")
"""The prelude names the relay spells unqualified, which a module-scope item would shadow."""


def validate(api: Api) -> list[str]:
    """Every objection the relay has to `api`: a name that is a Rust keyword or renders as
    one in UpperCamel; a field, enum conversion, parameter, a parameter's derived parameters
    or `<p>_local`, or a callback type's parameter or its count, rustc's `non_snake_case`
    refuses; a field of opaque type; a parameter the relay writes back named like one of
    `_GENERATED_NAMES`, or any named like another parameter's local; and a name the relay
    would define twice at module scope, a callback's wrapper among them, or in an enum."""
    objections = rust.rust_keyword_objections(api) + rust.camel_keyword_objections(rust.camel_names(api))
    lints = rust.field_names(api) + rust.enum_conversion_names(api)
    lints += [(f"union.{u.name}.{m.name}", rust.push_name(m.name)) for u in api.listed_unions() for m in u.members]
    lints += [pair for cb in api.callbacks for pair in rust.param_names(f"callback.{cb.name}", cb.params)]
    generated = []
    for fn in api.functions:
        pointers = [p for p in fn.params if p.ref is not None or p.callback]
        locals_ = [
            (f"function.{fn.name}.{p.name}", naming.rust_local(name))
            for p in pointers
            for name in (p.name, *p.report_names())
        ]
        lints += rust.param_names(f"function.{fn.name}", fn.params) + locals_
        generated += generated_name_objections(
            ((f"function.{fn.name}.{p.name}", p.name) for p in fn.params),
            {local for _, local in locals_},
        )
        generated += generated_name_objections(
            ((f"function.{fn.name}.{p.name}", p.name) for p in pointers if _written_back(p)), _GENERATED_NAMES
        )
    objections += rust.snake_case_objections(lints)
    objections += rust.opaque_field_objections(api)
    objections += generated
    module = rust.prelude_names(_PRELUDE_NAMES) + rust.module_names(api)
    module += rust.union_module_names(api, relay=True)
    module += [("the relay's buffer helper", name) for name, _ in rust.slice_helpers(_buffer_refs(api))]
    module += [(where, naming.upper_camel(name)) for where, name in rust.callback_names(api)]
    module += [(f"function.{fn.name}", naming.function_name(api.namespace, fn.name)) for fn in api.functions]
    objections += duplicate_objections(module, "module scope")
    objections += rust.enum_member_objections(api)
    objections += rust.union_member_objections(api)
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("rust") / rust.abi_file_name(name)


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The relay, as rustfmt lays it out."""
    blocks = rust.enum_blocks(api)
    blocks.append(rust.reexports(api))
    blocks += rust.union_blocks(api)
    blocks += [_buffer(api, u) for u in api.listed_unions()]
    passed = {p.type for fn in api.functions for p in fn.params if p.is_union}
    blocks += [rust.sequence_constructor(api, u) for u in api.unions if u.name in passed]
    blocks += [text for _, text in rust.slice_helpers(_buffer_refs(api))]
    blocks += [rust.group_comment(h) + _wrapper(api, cb) for h, cb in headed(api.callback_groups)]
    blocks += [rust.group_comment(h) + _relay(api, fn) for h, fn in headed(api.function_groups)]
    if api.wrapped_api is not None:
        blocks.append(_pins(api.namespace, api.wrapped_api))
    return rust.rustfmt(
        f"// {emitter.banner(source_name)}\n\n"
        + rust.ffi_module([*_constants(api), *rust.type_definitions(api)])
        + "".join("\n" + b for b in blocks)
    )


def _buffer_refs(api: Api) -> set[str]:
    """The `_ref` of every function's buffer parameter but a union's list: the slice helpers
    the relay emits."""
    return {p.ref for fn in api.functions for p in fn.params if p.is_buffer and not p.is_union}


# a list's alignment, which every member's size is a multiple of, as the relay buffer's word, so
# the buffer is allocated at the list's alignment
_WORDS = {2: "u16", 4: "u32", 8: "u64"}


def _buffer(api: Api, union: Union) -> str:
    """`union`'s buffer, whose `push_<member>` writes each field of the member's struct in
    declaration order by `to_ne_bytes()` into a staging array of the member's size, the prefix's
    tag and length the member's constant and size whatever the record holds, and folds it into
    words of the list's alignment; its count and extent are its own, and `view()` and
    `tail(mark)` its sequences."""
    n = rust.union_names(union)
    width = api.list_alignment(union)
    word = _WORDS[width]
    tag, length = api.prefix_fields(union)
    pushes = []
    for m in union.members:
        size = api.layout(m.struct)[0]
        head = rust.struct_named(api, m.struct).fields[0].name
        fixed = {
            f"{head}.{tag.name}": f"{next(e.value for e in api.consts if e.name == m.tag)}{tag.type}",
            f"{head}.{length.name}": f"{size}{length.type}",
        }
        scalars = _scalars(api, m.struct)
        writes = "".join(
            f"        staged[{offset}..{offset + api.layout(t)[0]}]"
            f".copy_from_slice(&{fixed.get(path, f'record.{path}')}.to_ne_bytes());\n"
            for path, t, offset in scalars
        )
        # a member that is the prefix alone, of the tag and length only, reads nothing of the record
        record = "record" if any(path not in fixed for path, _, _ in scalars) else "_record"
        pushes.append(
            f"    /// Appends `record` as a `{m.name}`, its `{tag.name}` and `{length.name}` the member's whatever it holds.\n"
            f"    pub fn {rust.push_name(m.name)}(&mut self, {record}: &{naming.upper_camel(m.struct)}) {{\n"
            f"        let mut staged = [0u8; {size}];\n{writes}        self.push(&staged);\n    }}\n"
        )
    lanes = ", ".join(f"record[at + {i}]" if i else "record[at]" for i in range(width))
    return (
        f"/// A sequence of `{union.name}` being written: "
        + ", ".join(f"`{rust.push_name(m.name)}`" for m in union.members)
        + " set the record's tag and\n"
        "/// size; the buffer's words are aligned to the prefix; `view()` and `tail(mark)` are the views.\n"
        f"#[derive(Default)]\npub struct {n.buf} {{\n    words: Vec<{word}>,\n    count: u32,\n}}\n\n"
        f"/// A place in a `{n.buf}`: the word and the count at the time, for `tail`.\n"
        f"#[derive(Clone, Copy)]\npub struct {n.buf_mark} {{\n    word: usize,\n    count: u32,\n}}\n\n"
        f"impl {n.buf} {{\n"
        "    /// An empty buffer.\n"
        "    pub fn new() -> Self {\n        Self::default()\n    }\n\n"
        + "\n".join(pushes)
        + "\n    /// The number of records pushed.\n"
        "    pub fn count(&self) -> u32 {\n        self.count\n    }\n\n"
        "    /// The bytes pushed.\n"
        f"    pub fn bytes_len(&self) -> usize {{\n        self.words.len() * {width}\n    }}\n\n"
        "    /// The bytes the buffer holds before it reallocates.\n"
        f"    pub fn capacity_bytes(&self) -> usize {{\n        self.words.capacity() * {width}\n    }}\n\n"
        "    /// The buffer's end now, for a later `tail`.\n"
        f"    pub fn mark(&self) -> {n.buf_mark} {{\n"
        f"        {n.buf_mark} {{ word: self.words.len(), count: self.count }}\n    }}\n\n"
        "    /// Every record pushed.\n"
        f"    pub fn view(&self) -> {n.sequence}<'_> {{\n"
        f"        self.tail({n.buf_mark} {{ word: 0, count: 0 }})\n    }}\n\n"
        "    /// The records pushed since `from`, a mark of this buffer.\n"
        f"    pub fn tail(&self, from: {n.buf_mark}) -> {n.sequence}<'_> {{\n"
        "        let words = &self.words[from.word..];\n"
        "        // SAFETY: the words are initialised, and bytes have no alignment of their own.\n"
        "        let bytes = unsafe { core::slice::from_raw_parts(words.as_ptr().cast::<u8>(), core::mem::size_of_val(words)) };\n"
        f"        {n.sequence} {{ bytes, count: self.count - from.count }}\n    }}\n\n"
        "    /// Appends one record's bytes as words and counts it; the whole stays within the bytes a `u32`\n"
        "    /// extent counts.\n"
        "    fn push(&mut self, record: &[u8]) {\n"
        "        assert!(\n"
        "            u32::try_from(self.bytes_len() + record.len()).is_ok(),\n"
        f'            "a {n.buf} holds at most u32::MAX bytes"\n'
        "        );\n"
        f"        self.words.reserve(record.len() / {width});\n"
        f"        for at in (0..record.len()).step_by({width}) {{\n"
        f"            self.words.push({word}::from_ne_bytes([{lanes}]));\n"
        "        }\n"
        "        self.count += 1;\n"
        "    }\n"
        "}\n"
    )


def _scalars(api: Api, struct: str) -> list[tuple[str, str, int]]:
    """(path, type, offset) of each scalar `struct` holds, in declaration order, a nested
    struct's and a text's fields by their path through it, a boxed scalar as its `.0`; the
    loader's density rule leaves no byte between them."""
    found = []
    for name, type_name, offset in api.field_offsets(struct):
        kind = api.kind(type_name)
        if kind in ("struct", "text"):
            found += [(f"{name}.{path}", t, offset + o) for path, t, o in _scalars(api, type_name)]
        elif kind == "boxed":
            found.append((f"{name}.0", type_name, offset))
        else:
            found.append((name, type_name, offset))
    return found


def _wrapper(api: Api, callback: Function) -> str:
    """The implementation's handle on a callback the caller passed, `C<'a>`: the C function
    pointer and its `user_data`, private, so the implementation can only call it. Its raw
    pointer keeps it neither `Send` nor `Sync`, so it stays on the call's thread, and the pin's
    higher-ranked lifetime keeps it inside the call. `call` takes the views as slices, a slice
    its count type cannot count being the implementation's own error, which panics."""
    cls = naming.upper_camel(callback.name)
    c_type = naming.type_name(api.namespace, callback.name)
    params, counts, args = ["&mut self"], [], []
    for p in callback.params:
        if p.is_union:
            params.append(f"{p.name}: {naming.union_sequence(p.type)}<'_>")
            statements, passed = rust.sequence_arguments(
                p,
                pointer=f"{p.name}.bytes().as_ptr()",
                count=f"{p.name}.count()",
                length=f"{p.name}.bytes().len()",
                context=f"{c_type}: ",
            )
            counts += statements
            args += passed
        elif p.is_buffer:
            params.append(f"{p.name}: {rust.view_type(api, p)}")
            count = p.count_name()
            counts.append(
                f'let {count} = {p.count_type}::try_from({p.name}.len()).expect("{c_type}: {p.name} is longer than {p.count_type} can count");'
            )
            args += [f"{p.name}.as_ptr(){'.cast()' if p.type == 'memory' else ''}", count]
        else:
            params.append(f"{p.name}: {rust.value_type(api, p.type)}")
            args.append(p.name)
    args.append("self.user_data")
    returns = rust.rust_type(api, callback.returns, path="ffi::")
    return (
        rust.function_docs(callback)
        + f"pub struct {cls}<'a> {{\n"
        + f"    callback: {rust.callback_fn_type(api, callback, path='ffi::')},\n"
        + "    user_data: *mut core::ffi::c_void,\n"
        + "    _call: core::marker::PhantomData<&'a mut ()>,\n"
        + "}\n\n"
        + f"impl {cls}<'_> {{\n"
        + f"    /// Calls `{c_type}` with these views and values, which the implementation may do only during\n"
        + "    /// the call that passed it and on its thread; returns the callback's answer.\n"
        + rust.many_arguments_allow(len(params), indent="    ")
        + f"    pub fn call({', '.join(params)}) -> {returns} {{\n"
        + "".join(f"        {line}\n" for line in counts)
        + "        // SAFETY: the caller passed this callback and its user_data for the call this wrapper is\n"
        + "        // borrowed for, and the wrapper is neither Send nor Sync; each view is a live slice and its length.\n"
        + f"        unsafe {{ (self.callback)({', '.join(args)}) }}\n"
        + "    }\n"
        + "}\n"
    )


def _constants(api: Api) -> list[str]:
    """Every constant as `pub const`, C-named, one block each for the version, each bit
    group, each plain group, each enum (its alias, then its entries) and each string group."""
    ns = api.namespace
    blocks = [rust.version_constant(api, prefixed=True)]
    blocks += [rust.constant_group(api, g, prefixed=True) for g in (*api.bit_const_groups, *api.const_groups)]
    for heading, t in headed(api.typed_const_groups):
        alias = naming.type_name(ns, t.name)
        blocks.append(
            rust.group_comment(heading)
            + rust.enum_alias(api, t)
            + "".join(
                f"{rust.doc_comment(e.docstring)}pub const {naming.const_name(ns, e.name)}: {alias} = "
                f"{c.int_literal(e.value, e.format)};\n"
                for e in t.entries
            )
        )
    blocks += [rust.string_group(api, g, prefixed=True) for g in api.string_const_groups]
    return blocks


def _written_back(p: Param) -> bool:
    """Whether the relay writes `p`'s local back through it after the call: a non-buffer
    `out` or `inout`."""
    return not p.is_buffer and p.ref in ("out", "inout")


def _relay(api: Api, fn: Function) -> str:
    """One export: a local per pointer parameter, `None` where the pointer is null, read
    from the caller for `in` and `inout` and a default for `out`, a buffer's through its
    helper and each of its reports as an `out` of the count's type, a callback's its
    wrapper of the pointer and its `user_data`, `None` where the pointer is null; the implementation
    pinned to its exact signature through a `fn` pointer, so a borrow that outlives the
    call, an `unsafe fn` or a changed signature fails to compile there, and called; each
    non-null `out` and `inout` written back; its result as the C enum."""
    before, args, after = [], [], []

    def written_back(name: str, start: str) -> None:
        local = naming.rust_local(name)
        before.append(f"let mut {local} = (!{name}.is_null()).then({start});")
        args.append(f"{local}.as_mut()")
        after.append(f"if let Some({local}) = {local} {{ unsafe {{ {name}.write({local}) }}; }}")

    for p in fn.params:
        local = naming.rust_local(p.name)
        if p.is_union:
            sequence = naming.union_sequence(p.type)
            value = f"unsafe {{ {sequence}::from_c({p.name}, {p.count_name()}, {p.bytes_name()}) }}"
            if p.optional:  # an absent list stays absent, whatever its count and extent
                value = f"if {p.name}.is_null() {{ None }} else {{ {value} }}"
            before.append(f"let {local} = {value};")
            args.append(local)
        elif p.is_buffer:
            pointer = f"{p.name}.cast::<u8>()" if p.type == "memory" else p.name
            slice = f"unsafe {{ self::{rust.SLICE_HELPERS[p.ref]}({pointer}, {p.count_name()}) }}"
            if p.optional:  # an absent `in` buffer stays absent, whatever its count
                slice = f"if {p.name}.is_null() {{ None }} else {{ {slice} }}"
            before.append(f"let {local} = {slice};")
            args.append(local)
            for report in p.report_names():
                written_back(report, rust.out_default(api, p.count_type))
        elif p.callback:
            wrapper = naming.upper_camel(p.type)
            before.append(
                f"let {local} = {p.name}.map(|callback| {wrapper} {{ callback, user_data: {p.user_data_name()}, "
                "_call: core::marker::PhantomData });"
            )
            args.append(local)
        elif p.ref is None:
            args.append(p.name)
        elif p.ref == "in":
            before.append(f"let {local} = (!{p.name}.is_null()).then(|| unsafe {{ {p.name}.read() }});")
            args.append(f"{local}.as_ref()")
        else:
            written_back(
                p.name, f"|| unsafe {{ {p.name}.read() }}" if p.ref == "inout" else rust.out_default(api, p.type)
            )
    success = naming.const_name(api.namespace, api.success_entry(fn).name)
    pinned = ", ".join(t for _, t in rust.implementation_params(api, fn))
    statements = [
        *before,
        # on every pin, since clippy's type_complexity score cannot be predicted from here
        "#[allow(clippy::type_complexity)]",
        f"const IMPLEMENTATION: fn({pinned}) -> Result<(), {naming.upper_camel(fn.returns)}> = crate::{fn.name};",
        f"let result = IMPLEMENTATION({', '.join(args)});",
        *after,
        f"match result {{ Ok(()) => ffi::{success}, Err(e) => e as {rust.rust_type(api, fn.returns, path='ffi::')}, }}",
    ]
    return (
        rust.function_docs(fn, extra=[f"{p.name}: may be null" for p in fn.params if p.optional], safety=[_SAFETY])
        + "#[unsafe(no_mangle)]\n"
        + rust.signature(api, fn, prefix='pub unsafe extern "C" fn ', path="ffi::")
        + " {\n"
        + "".join(f"    {s}\n" for s in statements)
        + "}\n"
    )


def _pins(namespace: str, wrapped_api: WrappedApi) -> str:
    """The `wrapped_api` module, `bindgen`'s rendering of the wrapped API's C headers, those
    `_headers` names, which the build writes into `OUT_DIR`, then one compile-time assertion
    per pin against it, both sides widened to `i64` so a macro bindgen types wider cannot truncate into a false match.
    """
    asserts = "".join(
        f'const _: () = assert!(ffi::{name} as i64 == wrapped_api::{macro} as i64, "{name} must match {macro}");\n'
        for name, macro in ((naming.const_name(namespace, key), macro) for key, macro in wrapped_api.pins)
    )
    return (
        "// Pins to the wrapped API: the implementation build fails if a pinned constant disagrees with its header\n"
        "pub mod wrapped_api {\n"
        "    #![allow(dead_code, non_camel_case_types, non_snake_case, non_upper_case_globals)]\n"
        '    include!(concat!(env!("OUT_DIR"), "/wrapped_api.rs"));\n'
        "}\n"
        f"\n{asserts}"
    )
