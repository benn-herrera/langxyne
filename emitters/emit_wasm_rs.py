"""The wasm shim: what the Node binding needs of a library built for WASI beyond the relay's C
ABI, an allocator pair to marshal a call's arguments in linear memory and, per callback type,
the address of a function the binding provides as the module's import. A crate includes it
beside the relay, in the same module, for its wasm build alone."""

from pathlib import Path

from langxyne import naming
from langxyne.emitters import emitter, rust
from langxyne.model import Api, Function, headed

LABEL = "rust_wasm"


def validate(api: Api) -> list[str]:
    """Every objection the shim has to `api`: a callback type's parameter, or what it brings
    beside itself, that is a Rust keyword, each a parameter of the shim's import of it."""
    objections = [
        f"{where}: '{name}' is a Rust keyword"
        for cb in api.callbacks
        for where, name in rust.param_names(f"callback.{cb.name}", cb.params)
        if name in rust.RUST_KEYWORDS
    ]
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("rust") / f"{name}_wasm.rs"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The shim, as rustfmt lays it out: the allocator pair, then each callback type's import
    and the export answering its address, under its group's comment."""
    ns = api.namespace
    alloc, free = naming.wasm_alloc(ns), naming.wasm_free(ns)
    blocks = [
        f"/// Allocates a block of `size` bytes at `align` for the Node binding to marshal a call in, a block\n"
        f"/// of 0 bytes being one of 1; null where `align` is not a power of two, the size rounded up to\n"
        f"/// it exceeds `isize::MAX`, or the allocation fails.\n"
        f'#[unsafe(no_mangle)]\npub extern "C" fn {alloc}(size: usize, align: usize) -> *mut u8 {{\n'
        "    match core::alloc::Layout::from_size_align(size.max(1), align) {\n"
        "        // SAFETY: the layout's size is at least 1.\n"
        "        Ok(layout) => unsafe { std::alloc::alloc(layout) },\n"
        "        Err(_) => core::ptr::null_mut(),\n"
        "    }\n"
        "}\n",
        f"/// Releases a block `{alloc}` gave; a null `block` is no block.\n"
        "///\n/// # Safety\n///\n"
        f"/// `block` is null or a block `{alloc}` gave for this `size` and `align`, not released since.\n"
        f'#[unsafe(no_mangle)]\npub unsafe extern "C" fn {free}(block: *mut u8, size: usize, align: usize) {{\n'
        "    if block.is_null() {\n        return;\n    }\n"
        "    if let Ok(layout) = core::alloc::Layout::from_size_align(size.max(1), align) {\n"
        "        // SAFETY: the caller names a block the allocator gave for this layout, not released since.\n"
        "        unsafe { std::alloc::dealloc(block, layout) };\n"
        "    }\n"
        "}\n",
    ]
    if api.callbacks:
        imports = "".join(
            rust.group_comment(h, indent="    ") + _import(api, cb) for h, cb in headed(api.callback_groups)
        )
        blocks.append(
            f'#[link(wasm_import_module = "{naming.wasm_import_module(ns)}")]\nunsafe extern "C" {{\n{imports}}}\n'
        )
        blocks += [rust.group_comment(h) + _address(api, cb) for h, cb in headed(api.callback_groups)]
    return rust.rustfmt(f"// {emitter.banner(source_name)}\n\n" + "\n".join(blocks))


def _import(api: Api, callback: Function) -> str:
    """The import the library calls as `callback`, a function the Node binding provides."""
    params = ", ".join(f"{n}: {t}" for t, n in rust.callback_c_params(api, callback, path="ffi::"))
    returns = rust.rust_type(api, callback.returns, path="ffi::")
    return (
        rust.doc_comment(callback.docstring, indent="    ")
        + f"    fn {naming.wasm_callback_import(api.namespace, callback.name)}({params}) -> {returns};\n"
    )


def _address(api: Api, callback: Function) -> str:
    """The export answering `callback`'s import's address, the pointer the C ABI takes."""
    c_type = naming.type_name(api.namespace, callback.name)
    target = naming.wasm_callback_import(api.namespace, callback.name)
    return (
        f"/// The address of `{target}`, the Node binding's `{c_type}`, which it passes as the callback.\n"
        f'#[unsafe(no_mangle)]\npub extern "C" fn {naming.wasm_callback_address(api.namespace, callback.name)}()'
        f" -> ffi::{c_type} {{\n    Some({target})\n}}\n"
    )
