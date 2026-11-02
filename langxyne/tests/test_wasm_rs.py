import unittest
from pathlib import Path

from langxyne.emitters import EMITTERS, emit_wasm_rs
from langxyne.tests.support import FIXTURES, MINIMAL, assert_matches_expected, load, mutate, objections
from langxyne.tests.support_xy32 import XY32

EXPECTED = FIXTURES / "expected_wasm_xy32.rs"


def shim(text: str = XY32) -> str:
    return emit_wasm_rs.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", project="xy")


class Shim(unittest.TestCase):
    def test_byte_identical_to_expected(self) -> None:
        assert_matches_expected(self, EXPECTED, shim())

    def test_beside_the_relay(self) -> None:
        self.assertEqual(emit_wasm_rs.output_path(name="xy_api", project="xy"), Path("rust/xy_api_wasm.rs"))

    def test_no_callback_type_no_import(self) -> None:
        text = shim(MINIMAL)
        self.assertIn('pub extern "C" fn xy__alloc(size: usize, align: usize) -> *mut u8 {', text)
        self.assertNotIn('extern "C" {', text)


class Validate(unittest.TestCase):
    def test_xy32_draws_no_objection_from_the_loader_or_either_new_emitter(self) -> None:
        self.assertEqual(objections(XY32), [])
        api = load(XY32)
        for token in ("wasm_rs", "node"):
            with self.subTest(token=token):
                self.assertEqual(EMITTERS[token].validate(api), [])

    def test_a_callback_parameter_that_is_a_rust_keyword(self) -> None:
        text = mutate(XY32, '_return = "flow"\nmode = "mode"', '_return = "flow"\nmatch = "mode"')
        self.assertEqual(
            emit_wasm_rs.validate(load(text)), ["rust_wasm: callback.on_mode.match: 'match' is a Rust keyword"]
        )
