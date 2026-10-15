"""The output modules, and the one table the generator reaches them through."""

from langxyne.emitters import (
    emit_abi_rs,
    emit_binding_cpp,
    emit_binding_go,
    emit_binding_lua,
    emit_binding_node,
    emit_binding_py,
    emit_binding_rs,
    emit_c,
    emit_stub_cpp,
    emit_stub_rs,
    emit_wasm_rs,
)
from langxyne.emitters.emitter import Emitter

# Keyed by output token, in the order objections are reported and outputs written.
EMITTERS: dict[str, Emitter] = {
    "h": emit_c,
    "hpp": emit_binding_cpp,
    "lua": emit_binding_lua,
    "stub_cpp": emit_stub_cpp,
    "rs": emit_binding_rs,
    "abi_rs": emit_abi_rs,
    "stub_rs": emit_stub_rs,
    "go": emit_binding_go,
    "py": emit_binding_py,
    "wasm_rs": emit_wasm_rs,
    "node": emit_binding_node,
}
