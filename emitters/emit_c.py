"""The C header."""

from pathlib import Path

from langxyne import model, naming
from langxyne.emitters import c, emitter
from langxyne.model import Api

LABEL = "header"


def validate(api: Api) -> list[str]:
    """Every objection the header has to `api`: a name that is a C keyword, a parameter
    named like a type the declarations spell, a constant whose C name is one of the
    header's own macros, a typed enum value above the `int32_t` maximum, which a C17
    enumerator cannot hold, and a C identifier a union's list defines too."""
    objections = [f"{where}: '{name}' is a C keyword" for where, name in api.names() if name in c.C_KEYWORDS]
    objections += c.parameter_type_objections(api)
    macros = c.header_macros(api.namespace)
    objections += [
        f"{where}: constant {naming.const_name(api.namespace, name)} is the header's own macro"
        for where, name in api.constant_names()
        if naming.const_name(api.namespace, name) in macros
    ]
    enumerator_max = naming.BASE_C_TYPES["i32"].max_value
    objections += [
        f"typed_const.{t.name}.{e.name}: value 0x{e.value:x} exceeds 0x{enumerator_max:x}; "
        "a C17 enumerator is an int"
        for t in api.typed_consts
        for e in t.entries
        if e.value > enumerator_max
    ]
    objections += _union_name_objections(api)
    return [f"{LABEL}: {o}" for o in objections]


def _union_name_objections(api: Api) -> list[str]:
    """A constant, typedef or function of the header whose C identifier is one a union's list
    defines (`c.union_names()`), naming the union, as the loader words a C identifier defined
    twice."""
    generated = c.union_names(api)
    if not generated:
        return []
    return [
        f"{where}: C identifier {ident} already defined by {first}"
        for ident, (first, *later) in model.duplicates(generated + api.c_identifiers()).items()
        for where in later
    ]


def output_path(*, name: str, project: str) -> Path:
    return Path("include") / project / f"{name}.h"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    ns = api.namespace
    c_api, api_macro, impl = naming.c_api_macro(ns), naming.api_macro(ns), naming.impl_macro(ns)
    prelude = f"""\
/* {emitter.banner(source_name)} */
#pragma once

#include <stdint.h>

#if defined(__cplusplus)
# define {c_api} extern "C"
#else
# define {c_api}
#endif

#if defined({impl})
# define {api_macro} {c_api} __attribute__((visibility("default")))
#else
# define {api_macro} {c_api}
#endif

"""
    text = prelude + c.declarations(api, function_prefix=f"{api_macro} ")
    if api.wrapped_api is not None:
        asserts = "".join(
            f"static_assert({naming.const_name(ns, key)} == {macro}, "
            f'"{naming.const_name(ns, key)} must match {macro}");\n'
            for key, macro in api.wrapped_api.pins
        )
        includes = "".join(f'# include "{project}/{header}"\n' for header in api.wrapped_api.headers)
        text += f"""\

#if defined({impl})
{includes}/* Pins to the wrapped API: the implementation build fails if a pinned constant disagrees with its header */
# include <assert.h>
{asserts}#endif
"""
    return text
