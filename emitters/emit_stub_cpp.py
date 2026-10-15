"""A C++ implementation stub: every function defined, every body `return {};` to be replaced."""

from pathlib import Path

from langxyne import naming
from langxyne.emitters import c, cpp, emitter
from langxyne.model import Api, Function, headed

LABEL = "stub"


def validate(api: Api) -> list[str]:
    """Every objection the stub has to `api`: a name that is a C++ keyword, and a parameter
    named like a type its signatures spell."""
    objections = cpp.cpp_keyword_objections(api) + c.parameter_type_objections(api)
    return [f"{LABEL}: {o}" for o in objections]


def output_path(*, name: str, project: str) -> Path:
    return Path("stub") / f"{name}.cpp"


def companions(api: Api, *, name: str) -> list[tuple[Path, str]]:
    return []


def emit(api: Api, *, source_name: str, name: str, project: str) -> str:
    impl = naming.impl_macro(api.namespace)
    prelude = f"""\
// {emitter.stub_banner(source_name)}
#define {impl}
#include "{name}.h"
#undef {impl}

#include <cerrno>
#include <cstdint>
#include <cstring>
"""
    return prelude + "".join(
        "\n" + (f"// {h}\n" if h else "") + _definition(api, f) for h, f in headed(api.function_groups)
    )


def _definition(api: Api, fn: Function) -> str:
    ns = api.namespace
    voids = "".join(f"  (void){n};\n" for p in fn.params for _, n in c.c_params(api, p))
    return (
        f"{naming.api_macro(ns)} {c.c_type(api, fn.returns)} {naming.function_name(ns, fn.name)}"
        f"({c.param_list(api, fn)}) {{\n"
        f"{voids}"
        "  // replace: not implemented\n"
        "  return {};\n"
        "}\n"
    )
