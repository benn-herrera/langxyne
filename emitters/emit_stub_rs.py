"""A Rust implementation stub: a crate root that includes the regenerated relay and
defines, for every function, the implementation the relay calls, each body returning
`Ok(())`, to be replaced."""

from pathlib import Path

from langxyne import naming
from langxyne.emitters import emitter, rust
from langxyne.model import Api, Function, duplicate_objections, headed

LABEL = "rust_stub"


def validate(api: Api) -> list[str]:
    """Every objection the Rust stub has to `api`: a name that is a Rust keyword; a
    function or parameter name, a buffer's reports included, that rustc's `non_snake_case`
    refuses, the implementation functions being plain `fn`s; and a name it imports whose UpperCamel rendering is a
    keyword or a prelude name its text spells, which the import would shadow."""
    names = [(f"function.{fn.name}", fn.name) for fn in api.functions]
    # a buffer's reports are parameters of their own here, its count and a callback's user_data are not
    names += [
        (f"function.{fn.name}.{p.name}", name)
        for fn in api.functions
        for p in fn.params
        for name in (p.name, *p.report_names())
    ]
    objections = rust.rust_keyword_objections(api) + rust.snake_case_objections(names)
    imported = _imported(api)
    objections += rust.camel_keyword_objections(imported)
    module = rust.prelude_names() + [(where, naming.upper_camel(name)) for where, name in imported]
    module += _sequences(api)
    objections += duplicate_objections(module, "module scope")
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("stub") / f"{name}.rs"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    """The Rust implementation stub, as rustfmt lays it out."""
    blocks = [f'pub mod abi {{\n    include!(concat!(env!("LANGXYNE_RUST_DIR"), "/{rust.abi_file_name(name)}"));\n}}\n']
    imports = _imports(api)
    if imports:
        blocks.append(f"use abi::{{{', '.join(imports)}}};\n")
    blocks += [rust.group_comment(h) + _definition(api, fn) for h, fn in headed(api.function_groups)]
    return rust.rustfmt(f"// {emitter.stub_banner(source_name)}\n" + "".join("\n" + b for b in blocks))


def _imported(api: Api) -> list[tuple[str, str]]:
    """(where, name) of each type the signatures name from the relay by its UpperCamel
    name: a boxed scalar or struct parameter's re-export, a callback parameter's wrapper,
    and each return enum."""
    used = {
        p.type
        for fn in api.functions
        for p in fn.params
        if p.type != "memory" and api.kind(p.type) in ("boxed", "struct", "callback")
    }
    used |= {fn.returns for fn in api.functions}
    return [(where, name) for where, name in rust.type_names(api) + rust.callback_names(api) if name in used]


def _sequences(api: Api) -> list[tuple[str, str]]:
    """(where, name) of each union's sequence a list parameter's signature names from the relay."""
    used = {p.type for fn in api.functions for p in fn.params if p.is_union}
    return [(f"union.{u.name}", naming.union_sequence(u.name)) for u in api.unions if u.name in used]


def _imports(api: Api) -> list[str]:
    """What the signatures name from the relay: `ffi` for an enum or opaque parameter, and
    `_imported()`'s UpperCamel names and `_sequences()`, in no order: rustfmt sorts the `use`
    list."""
    kinds = {api.kind(p.type) for fn in api.functions for p in fn.params if p.type != "memory"}
    names = [naming.upper_camel(name) for _, name in _imported(api)] + [name for _, name in _sequences(api)]
    return (["ffi"] if kinds & {"enum", "opaque"} else []) + names


def _definition(api: Api, fn: Function) -> str:
    """One implementation function: its docstring lines, the signature the relay pins, and
    a body discarding each parameter, a callback's under the comment stating how it may be
    called, and returning `Ok(())`."""
    params = rust.implementation_params(api, fn)
    callbacks = {p.name for p in fn.params if p.callback}
    discards = "".join(
        (
            f"    // {n}: call it only within this call; never keep it where the handle's state reaches it, "
            "since a handle dereference has no lifetime to stop it\n"
            if n in callbacks
            else ""
        )
        + f"    let _ = {n};\n"
        for n, _ in params
    )
    return (
        rust.function_docs(fn)
        + rust.many_arguments_allow(len(params))
        + f"pub fn {fn.name}({', '.join(f'{n}: {t}' for n, t in params)}) -> Result<(), {naming.upper_camel(fn.returns)}> {{\n"
        + discards
        + "    // replace: not implemented\n"
        + "    Ok(())\n"
        + "}\n"
    )
