"""Rewrites the four Rust goldens, tests/fixtures/expected_*.rs, through the emitters, the binding,
relay and stub from support.KITCHEN_SINK and the wasm shim from support_xy32.XY32, each through the
test module that compares it, so a golden's definition has one home. Writing a golden proves
nothing: the compiled checks that build it prove it, and a reader reviews its diff. It writes
nothing unless every emitter's validate passes and all four render."""

import difflib
import logging

from langxyne.emitters import emit_abi_rs, emit_binding_rs, emit_stub_rs, emit_wasm_rs
from langxyne.tests import support, test_abi_rs, test_binding_rs, test_stub_rs, test_wasm_rs
from langxyne.tests.support import KITCHEN_SINK
from langxyne.tests.support_xy32 import XY32


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    api = support.load(KITCHEN_SINK)
    objections = [o for module in (emit_binding_rs, emit_abi_rs, emit_stub_rs) for o in module.validate(api)]
    objections += emit_wasm_rs.validate(support.load(XY32))
    for objection in objections:
        logging.error("%s", objection)
    if objections:
        raise SystemExit(2)
    rendered = [
        (test_binding_rs.EXPECTED, test_binding_rs.binding(KITCHEN_SINK)),
        (test_abi_rs.EXPECTED, test_abi_rs.relay(KITCHEN_SINK)),
        (test_stub_rs.EXPECTED, test_stub_rs.stub(KITCHEN_SINK)),
        (test_wasm_rs.EXPECTED, test_wasm_rs.shim(XY32)),
    ]
    for path, new in rendered:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old == new:
            logging.info("regenerate-expected: %s unchanged", path.name)
            continue
        diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        path.write_text(new, encoding="utf-8")
        logging.info("regenerate-expected: %s: %d lines removed, %d added", path.name, removed, added)


if __name__ == "__main__":
    main()
