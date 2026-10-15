import unittest

from langxyne.emitters import emit_stub_rs
from langxyne.tests.support import (
    DOCUMENTED_FUNCTION_GROUPS,
    EXPECTED_STUB,
    FIXTURE,
    KITCHEN_SINK,
    UNION_U8_TAG,
    UNIONS,
    assert_matches_expected,
    load,
    mutate,
)

EXPECTED = EXPECTED_STUB


def stub(text: str = FIXTURE) -> str:
    return emit_stub_rs.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", project="xy")


class Stub(unittest.TestCase):
    def test_byte_identical_to_expected(self) -> None:
        assert_matches_expected(self, EXPECTED, stub(KITCHEN_SINK))


class Validate(unittest.TestCase):
    RULE = "is not snake_case (an uppercase letter or '__'), which rustc requires of it"

    def test_rust_keyword_as_name(self) -> None:
        self.assertEqual(
            emit_stub_rs.validate(load(mutate(FIXTURE, "unit = ", "match = "))),
            ["rust_stub: function.open_port.match: 'match' is a Rust keyword"],
        )

    def test_function_or_parameter_name_rustc_calls_not_snake_case(self) -> None:
        for needle, replacement, where, name in (
            ("[function.send]", "[function.Send]", "function.Send", "Send"),
            ("[function.send]", "[function.se__nd]", "function.se__nd", "se__nd"),
            ("unit = ", "Unit = ", "function.open_port.Unit", "Unit"),
            ("unit = ", "u__nit = ", "function.open_port.u__nit", "u__nit"),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    emit_stub_rs.validate(load(mutate(FIXTURE, needle, replacement))),
                    [f"rust_stub: {where}: '{name}' {self.RULE}"],
                )

    def test_a_buffers_reports_are_parameters_rustc_calls_not_snake_case(self) -> None:
        self.assertEqual(
            emit_stub_rs.validate(load(mutate(KITCHEN_SINK, "labels = ", "labels_ = "))),
            [f"rust_stub: function.list.labels_: '{name}' {self.RULE}" for name in ("labels__wrote", "labels__needed")],
        )

    def test_an_import_shadowing_a_prelude_name_or_rendering_a_keyword(self) -> None:
        # the stub imports a struct parameter's re-export and each return enum
        for text, message in (
            (
                mutate(FIXTURE, "[struct.stats]", "[struct.ok]").replace('"stats"', '"ok"'),
                "module scope: Ok would be defined more than once, by the Rust prelude and struct.ok",
            ),
            (
                mutate(FIXTURE, "[struct.stats]", "[struct.option]").replace('"stats"', '"option"'),
                "module scope: Option would be defined more than once, by the Rust prelude and struct.option",
            ),
            (
                mutate(FIXTURE, "[typed_const.status]", "[typed_const.self_]").replace('"status"', '"self_"'),
                "typed_const.self_: 'self_' renders as 'Self', a Rust keyword",
            ),
            (
                mutate(KITCHEN_SINK, "[callback.on_batch]", "[callback.ok]").replace('"on_batch"', '"ok"'),
                "module scope: Ok would be defined more than once, by the Rust prelude and callback.ok",
            ),
        ):
            with self.subTest(message=message):
                self.assertEqual(emit_stub_rs.validate(load(text)), [f"rust_stub: {message}"])

    def test_a_type_the_stub_does_not_import_is_not_refused(self) -> None:
        self.assertEqual(emit_stub_rs.validate(load(FIXTURE + '\n[struct.ok]\nv = "u32"\n')), [])

    def test_names_the_stub_does_not_render_are_not_refused(self) -> None:
        # the namespace, a trailing '_' and the count it brings, a conversion, a struct field
        for needle, replacement in (
            ('_namespace = "xy"', '_namespace = "Xy"'),
            ("buf = ", "buf_ = "),
            ('_to_string = "to_string"', '_to_string = "toString"'),
            ("bytes = ", "Bytes = "),
        ):
            with self.subTest(replacement=replacement):
                self.assertEqual(emit_stub_rs.validate(load(mutate(FIXTURE, needle, replacement))), [])


class Unions(unittest.TestCase):
    def test_a_list_is_an_option_of_its_sequence_imported_from_the_relay(self) -> None:
        text = stub(UNIONS)
        self.assertIn("use abi::{NoteSequence, Status};\n", text)
        self.assertIn("pub fn replay(notes: Option<NoteSequence<'_>>) -> Result<(), Status> {\n", text)

    def test_a_u8_tag_union_renders_its_list_as_any_other(self) -> None:
        self.assertEqual(emit_stub_rs.validate(load(UNION_U8_TAG)), [])
        text = stub(UNION_U8_TAG)
        self.assertIn("use abi::{NoteSequence, Status};\n", text)
        self.assertIn("pub fn replay(notes: Option<NoteSequence<'_>>) -> Result<(), Status> {\n", text)

    def test_the_imported_sequence_is_a_module_scope_name(self) -> None:
        self.assertEqual(emit_stub_rs.validate(load(UNIONS)), [])
        keep = '\n[[struct]]\n[struct.note_sequence]\nv = "u32"\n\n[[function]]\n[function.keep]\n_return = "status"\n'
        self.assertEqual(
            emit_stub_rs.validate(load(UNIONS + keep + 's = { _type = "note_sequence", _ref = "in" }\n')),
            [
                "rust_stub: module scope: NoteSequence would be defined more than once, by struct.note_sequence and "
                "union.note"
            ],
        )


class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_is_a_line_above_its_first_function(self) -> None:
        text = stub(DOCUMENTED_FUNCTION_GROUPS)
        self.assertIn("\n// port lifecycle\npub fn open_port(", text)
        self.assertIn("\n}\n\n/// release the port\npub fn destroy_port(", text)
        self.assertIn("\n// traffic\n/// buf: bytes to send\npub fn send(", text)


if __name__ == "__main__":
    unittest.main()
