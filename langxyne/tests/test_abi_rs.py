import re
import unittest

from langxyne.emitters import emit_abi_rs, emit_binding_rs
from langxyne.tests import test_binding_rs
from langxyne.tests.support import (
    DOCUMENTED_FUNCTION_GROUPS,
    EXPECTED_ABI,
    EXPECTED_BINDING,
    FIXTURE,
    KITCHEN_SINK,
    MINIMAL,
    NO_WRAPPED_API,
    NOTES,
    UNION_NOT_LISTED,
    UNION_U8_TAG,
    UNIONS,
    UNSPELLED_PRELUDE_STRUCTS,
    assert_matches_expected,
    load,
    mutate,
)

EXPECTED = EXPECTED_ABI
SAFETY = (
    "/// # Safety\n///\n"
    "/// Every pointer argument must be null or valid for the call as the C header declares it, no buffer may "
    "overlap another argument of the same call, and no other thread may read or write a buffer argument during "
    "the call. A panic in the implementation aborts the process.\n"
    '#[unsafe(no_mangle)]\npub unsafe extern "C" fn '
)


def relay(text: str = FIXTURE) -> str:
    return emit_abi_rs.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", project="xy")


class Relay(unittest.TestCase):
    def test_byte_identical_to_expected(self) -> None:
        assert_matches_expected(self, EXPECTED, relay(KITCHEN_SINK))

    def test_enums_and_reexports_are_the_bindings_byte_for_byte(self) -> None:
        text, binding = relay(KITCHEN_SINK), EXPECTED_BINDING.read_text(encoding="utf-8")
        shared = re.search(
            r"^/// call outcome\n#\[repr\(i32\)\].*?pub use ffi::xy_wrap as Wrap;\n", text, re.M | re.S
        ).group(0)
        self.assertIn(shared, binding)

    def test_a_blank_doc_line_follows_the_docstring_only_where_there_is_one(self) -> None:
        text = relay(KITCHEN_SINK)
        self.assertIn("/// release the port\n///\n/// # Safety\n", text)
        self.assertIn("/// buf: bytes to send\n///\n/// # Safety\n", text)
        self.assertIn("}\n\n" + SAFETY + "xy_spend(", text)
        with_param_doc = mutate(FIXTURE, "[function.send]\n", '[function.send]\n_docstring = "- sends"\n')
        self.assertIn("/// - sends\n///\n/// buf: bytes to send\n///\n/// # Safety\n", relay(with_param_doc))

    def test_no_wrapped_api_no_pins_and_no_module(self) -> None:
        text = relay(NO_WRAPPED_API)
        self.assertNotIn("wrapped_api", text)
        self.assertNotIn("assert!", text)

    def test_wrapped_api_module_rendered_without_pins(self) -> None:
        text = relay(mutate(FIXTURE, 'feat_a = "XYD_FEAT_A"\n', ""))
        self.assertIn("pub mod wrapped_api {", text)
        self.assertIn('include!(concat!(env!("OUT_DIR"), "/wrapped_api.rs"));', text)
        self.assertNotIn("assert!", text)


class Validate(unittest.TestCase):
    RULE = "is not snake_case (an uppercase letter or '__'), which rustc requires of it"

    def validate(self, text: str) -> list[str]:
        return emit_abi_rs.validate(load(text))

    def test_rust_keyword_as_name(self) -> None:
        # gen is reserved from edition 2024
        for name in ("match", "crate", "gen"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, "unit = ", f"{name} = ")),
                    [f"rust_abi: function.open_port.{name}: '{name}' is a Rust keyword"],
                )

    def test_a_name_whose_upper_camel_form_is_a_keyword(self) -> None:
        self.assertIn(
            "rust_abi: struct.self_: 'self_' renders as 'Self', a Rust keyword",
            self.validate(FIXTURE + '\n[struct.self_]\nv = "u32"\n'),
        )

    def test_field_parameter_count_or_local_rustc_calls_not_snake_case(self) -> None:
        for needle, replacement, where, names in (
            ("unit = ", "Unit = ", "function.open_port.Unit", ["Unit"]),
            ("bytes = ", "Bytes = ", "struct.stats.Bytes", ["Bytes"]),
            ("buf = ", "buf_ = ", "function.send.buf_", ["buf__count", "buf__local"]),
            ("generation = ", "generation_ = ", "function.open_port.generation_", ["generation__local"]),
        ):
            with self.subTest(names=names):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, needle, replacement)),
                    [f"rust_abi: {where}: '{name}' {self.RULE}" for name in names],
                )

    def test_an_enum_conversion_rustc_calls_not_snake_case_as_the_binding_does(self) -> None:
        for name in ("toString", "name__x"):
            with self.subTest(name=name):
                text = mutate(FIXTURE, '_to_string = "to_string"', f'_to_string = "{name}"')
                message = f"typed_const.status._to_string: '{name}' {self.RULE}"
                self.assertEqual(self.validate(text), [f"rust_abi: {message}"])
                self.assertIn(f"rust: {message}", emit_binding_rs.validate(load(text)))

    def test_an_exported_functions_name_is_exempt(self) -> None:
        self.assertEqual(self.validate(mutate(FIXTURE, "[function.spend]", "[function.Spend]")), [])

    def test_opaque_field_is_not_implemented(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'bytes = "u64"', 'bytes = "token"')),
            ["rust_abi: struct.stats.bytes: a field of opaque_ref type is not implemented for Rust"],
        )

    def test_generated_names_are_refused_as_parameters_the_relay_writes_back(self) -> None:
        for name in emit_abi_rs._GENERATED_NAMES:
            for needle in ('generation = { _type = "u32", _ref = "out" }', 'pstats = { _type = "stats", _ref = "out"'):
                with self.subTest(name=name, needle=needle):
                    old = needle.split(" ")[0]
                    self.assertEqual(
                        self.validate(mutate(FIXTURE, needle, needle.replace(old, name, 1))),
                        [f"rust_abi: function.open_port.{name}: '{name}' is a name the generated code uses"],
                    )

    def test_names_the_body_reaches_only_before_its_result_or_through_a_path_are_not_refused(self) -> None:
        # by value, `in`, a buffer; the helpers are called through `self::` and the pin is a const
        for needle, name in (
            ('unit = "u32"', "result"),
            ("cfg = { _type", "result"),
            ("buf = { _type", "result"),
            ('unit = "u32"', "implementation"),
            ("buf = { _type", "c_slice"),
            ("data = { _type", "c_slice_mut"),
            ("pdst = { _type", "c_out_slice"),
            ("pdst = { _type", "c_len"),
        ):
            with self.subTest(name=name, needle=needle):
                text = mutate(KITCHEN_SINK, needle, needle.replace(needle.split(" ")[0], name, 1))
                self.assertEqual(self.validate(text), [])

    def test_a_parameter_named_like_another_parameters_local(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'unit = "u32"', 'pport_local = "u32"')),
            ["rust_abi: function.open_port.pport_local: 'pport_local' is a name the generated code uses"],
        )
        for report in ("items_wrote", "items_needed"):
            with self.subTest(report=report):
                local = f"{report}_local"
                self.assertEqual(
                    self.validate(mutate(KITCHEN_SINK, "labels = {", f'{local} = "u32"\nlabels = {{')),
                    [f"rust_abi: function.list.{local}: '{local}' is a name the generated code uses"],
                )

    def test_a_callbacks_wrapper_is_a_module_scope_name_and_renders_no_keyword(self) -> None:
        for text, message in (
            (
                KITCHEN_SINK + '\n[struct.on_batch_]\nv = "u32"\n',
                "module scope: OnBatch would be defined more than once, by struct.on_batch_ and callback.on_batch",
            ),
            (
                mutate(KITCHEN_SINK, "[callback.on_batch]", "[callback.ok]").replace('"on_batch"', '"ok"'),
                "module scope: Ok would be defined more than once, by the Rust prelude and callback.ok",
            ),
            (
                mutate(KITCHEN_SINK, "[callback.on_batch]", "[callback.self_]").replace('"on_batch"', '"self_"'),
                "callback.self_: 'self_' renders as 'Self', a Rust keyword",
            ),
        ):
            with self.subTest(message=message):
                self.assertIn(f"rust_abi: {message}", self.validate(text))

    def test_a_parameter_named_like_a_callbacks_local(self) -> None:
        self.assertEqual(
            self.validate(mutate(KITCHEN_SINK, 'batch = "u32"\ncuts = ', 'sink_local = "u32"\ncuts = ')),
            ["rust_abi: function.stream.sink_local: 'sink_local' is a name the generated code uses"],
        )

    def test_a_callback_types_parameter_or_count_rustc_calls_not_snake_case(self) -> None:
        for needle, replacement, where, name in (
            ('last = "u32"', 'Last = "u32"', "callback.on_batch.Last", "Last"),
            ("arena = {", "arena_ = {", "callback.on_batch.arena_", "arena__count"),
        ):
            with self.subTest(name=name):
                self.assertIn(
                    f"rust_abi: {where}: '{name}' {self.RULE}", self.validate(mutate(KITCHEN_SINK, needle, replacement))
                )

    def test_the_text_type_is_a_module_scope_name_where_a_field_is_text(self) -> None:
        self.assertEqual(
            self.validate(KITCHEN_SINK + '\n[struct.text_]\nv = "u32"\n'),
            [
                "rust_abi: module scope: Text would be defined more than once, by struct.text_ and the builtin type "
                "text"
            ],
        )
        self.assertEqual(self.validate(FIXTURE + '\n[struct.text_]\nv = "u32"\n'), [])

    def test_the_out_slice_is_a_module_scope_name_where_a_buffer_is_out(self) -> None:
        struct = '\n[struct.out_slice]\nv = "u32"\n'
        self.assertEqual(
            self.validate(KITCHEN_SINK + struct),
            [
                "rust_abi: module scope: OutSlice would be defined more than once, by struct.out_slice and the "
                "relay's buffer helper"
            ],
        )
        self.assertEqual(self.validate(FIXTURE + struct), [])

    def test_module_scope_collisions(self) -> None:
        for text, message in (
            (
                FIXTURE + '\n[struct.none]\nv = "u32"\n',
                "None would be defined more than once, by the Rust prelude and struct.none",
            ),
            (
                FIXTURE + '\n[struct.option]\nv = "u32"\n',
                "Option would be defined more than once, by the Rust prelude and struct.option",
            ),
            (
                FIXTURE + '\n[struct.result]\nv = "u32"\n',
                "Result would be defined more than once, by the Rust prelude and struct.result",
            ),
            # a boxed scalar is a tuple struct, so its re-export takes the value namespace the patterns reach too
            (
                FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.err]\n_base_type = "u32"\n',
                "Err would be defined more than once, by the Rust prelude and boxed_scalar.err",
            ),
            (
                FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.ok]\n_base_type = "u32"\n',
                "Ok would be defined more than once, by the Rust prelude and boxed_scalar.ok",
            ),
            (
                FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.some]\n_base_type = "u32"\n',
                "Some would be defined more than once, by the Rust prelude and boxed_scalar.some",
            ),
            (
                mutate(
                    mutate(FIXTURE, '_namespace = "xy"', '_namespace = "c"'), "[function.spend]", "[function.slice]"
                ),
                "c_slice would be defined more than once, by the relay's buffer helper and function.slice",
            ),
            (
                mutate(mutate(FIXTURE, '_namespace = "xy"', '_namespace = "c"'), "[function.spend]", "[function.len]"),
                "c_len would be defined more than once, by the relay's buffer helper and function.len",
            ),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.validate(text), [f"rust_abi: module scope: {message}"])

    def test_helper_names_are_refused_only_where_emitted(self) -> None:
        text = (
            MINIMAL.replace('_namespace = "xy"', '_namespace = "c"')
            + '\n[[typed_const]]\n[typed_const.status]\nok = 0\n\n[[function]]\n[function.len]\n_return = "status"\n'
        )
        self.assertEqual(self.validate(text), [])

    def test_prelude_names_the_relay_does_not_spell_are_not_refused(self) -> None:
        self.assertEqual(self.validate(FIXTURE + UNSPELLED_PRELUDE_STRUCTS), [])

    def test_enum_collisions_are_the_bindings(self) -> None:
        text = mutate(FIXTURE, '_to_string = "to_string"', '_to_string = "try_from"')
        message = (
            "enum Status: try_from would be defined more than once, by the generated TryFrom conversion and "
            "typed_const.status._to_string"
        )
        self.assertEqual(self.validate(text), [f"rust_abi: {message}"])
        self.assertEqual(emit_binding_rs.validate(load(text)), [f"rust: {message}"])


class Unions(unittest.TestCase):
    """A union declaring `_mixed_type_list` renders the binding's walk and, the owned side, a
    buffer that writes each record's tag and size itself; a list reaches the implementation
    as an `Option` of its sequence and a callback's wrapper takes the sequence."""

    def test_the_walk_is_the_bindings_byte_for_byte(self) -> None:
        shared = re.search(
            r"^/// Why a walk of a union's list.*?^impl core::iter::FusedIterator for NoteRecords<'_> \{\}\n",
            relay(UNIONS),
            re.M | re.S,
        ).group(0)
        self.assertIn(shared, test_binding_rs.binding(UNIONS))

    def test_the_buffer_and_its_mark(self) -> None:
        text = relay(UNIONS)
        for expected in (
            "#[derive(Default)]\npub struct NoteBuf {\n    words: Vec<u32>,\n    count: u32,\n}\n",
            "#[derive(Clone, Copy)]\npub struct NoteBufMark {\n    word: usize,\n    count: u32,\n}\n",
            "    pub fn new() -> Self {\n",
            "    pub fn push_line(&mut self, record: &NoteLine) {\n",
            "    pub fn push_mark(&mut self, record: &NoteMark) {\n",
            "    pub fn count(&self) -> u32 {\n",
            "    pub fn bytes_len(&self) -> usize {\n",
            "    pub fn capacity_bytes(&self) -> usize {\n",
            "    pub fn mark(&self) -> NoteBufMark {\n",
            "    pub fn view(&self) -> NoteSequence<'_> {\n",
            "    pub fn tail(&self, from: NoteBufMark) -> NoteSequence<'_> {\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_a_push_writes_the_members_tag_and_size_whatever_the_record_holds(self) -> None:
        text = relay(UNIONS)
        for member, tag in (("line", 1), ("mark", 2)):
            with self.subTest(member=member):
                self.assertIn(
                    f"        let mut staged = [0u8; 16];\n"
                    f"        staged[0..2].copy_from_slice(&{tag}u16.to_ne_bytes());\n"
                    "        staged[2..4].copy_from_slice(&16u16.to_ne_bytes());\n"
                    "        staged[4..8].copy_from_slice(&record.head.at.to_ne_bytes());\n",
                    text,
                )
        for field in ("record.head.kind", "record.head.size"):
            with self.subTest(field=field):
                self.assertNotIn(field, text)

    def test_a_push_over_a_u8_tag_writes_the_tag_and_length_by_name_and_keeps_the_u8_between(self) -> None:
        self.assertEqual(emit_abi_rs.validate(load(UNION_U8_TAG)), [])
        text = relay(UNION_U8_TAG)
        for expected in (
            "const _: () =\n    assert!(core::mem::size_of::<NoteHead>() == 4 && core::mem::align_of::<NoteHead>() == 2);\n",
            "#[derive(Default)]\npub struct NoteBuf {\n    words: Vec<u16>,\n    count: u32,\n}\n",
            "        let mut staged = [0u8; 6];\n"
            "        staged[0..1].copy_from_slice(&1u8.to_ne_bytes());\n"
            "        staged[1..2].copy_from_slice(&record.head.flag.to_ne_bytes());\n"
            "        staged[2..4].copy_from_slice(&6u16.to_ne_bytes());\n"
            "        staged[4..6].copy_from_slice(&record.width.to_ne_bytes());\n",
            "        let mut staged = [0u8; 8];\n"
            "        staged[0..1].copy_from_slice(&2u8.to_ne_bytes());\n"
            "        staged[1..2].copy_from_slice(&record.head.flag.to_ne_bytes());\n"
            "        staged[2..4].copy_from_slice(&8u16.to_ne_bytes());\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_a_list_reaches_the_implementation_as_an_option_of_its_sequence(self) -> None:
        text = relay(UNIONS)
        self.assertIn(
            'pub unsafe extern "C" fn xy_replay(\n    notes: *const ffi::xy_note_head,\n    notes_count: u32,\n'
            "    notes_bytes: u32,\n) -> ffi::xy_status {\n"
            "    let notes_local = unsafe { NoteSequence::from_c(notes, notes_count, notes_bytes) };\n"
            "    #[allow(clippy::type_complexity)]\n"
            "    const IMPLEMENTATION: fn(Option<NoteSequence<'_>>) -> Result<(), Status> = crate::replay;\n",
            text,
        )
        optional = relay(mutate(UNIONS, NOTES, NOTES.replace(" }", ", _optional = true }")))
        self.assertIn(
            "    let notes_local = if notes.is_null() {\n        None\n    } else {\n"
            "        unsafe { NoteSequence::from_c(notes, notes_count, notes_bytes) }\n    };\n",
            optional,
        )

    def test_a_callbacks_wrapper_takes_the_sequence_and_passes_its_three_c_parameters(self) -> None:
        text = relay(UNIONS)
        self.assertIn("    pub fn call(&mut self, seen: NoteSequence<'_>, count: u32) -> ffi::xy_flow {\n", text)
        self.assertIn(
            "            (self.callback)(\n                seen.bytes().as_ptr().cast(),\n"
            "                seen_count,\n                seen_bytes,\n",
            text,
        )

    def test_a_union_without_the_property_renders_its_structs_alone(self) -> None:
        text = relay(UNION_NOT_LISTED)
        self.assertIn("pub use ffi::xy_note_line as NoteLine;\n", text)
        for name in (*test_binding_rs.UNION_NAMES, "NoteBuf"):
            with self.subTest(name=name):
                self.assertNotIn(name, text)

    def test_the_buffers_names_are_module_scope_names_and_its_pushes_snake_case(self) -> None:
        self.assertEqual(self.validate(UNIONS), [])
        for struct, name in (("note_buf", "NoteBuf"), ("note_buf_mark", "NoteBufMark")):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(UNIONS + f'\n[[struct]]\n[struct.{struct}]\nv = "u32"\n'),
                    [
                        f"rust_abi: module scope: {name} would be defined more than once, by struct.{struct} and union.note"
                    ],
                )
        self.assertEqual(
            self.validate(mutate(UNIONS, "mark = { _tag", "Mark = { _tag")),
            [f"rust_abi: union.note.Mark: 'push_Mark' {Validate.RULE}"],
        )
        self.assertEqual(
            self.validate(mutate(UNIONS, "mark = { _tag", "line_ = { _tag")),
            ["rust_abi: enum NoteRef: Line would be defined more than once, by union.note.line and union.note.line_"],
        )

    def validate(self, text: str) -> list[str]:
        return emit_abi_rs.validate(load(text))


class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_is_a_line_above_its_first_export(self) -> None:
        text = relay(DOCUMENTED_FUNCTION_GROUPS)
        self.assertIn("\n// port lifecycle\n/// pstats: may be null\n///\n" + SAFETY + "xy_open_port(", text)
        self.assertIn("\n}\n\n/// release the port\n///\n" + SAFETY + "xy_destroy_port(", text)
        self.assertIn("\n// traffic\n/// buf: bytes to send\n///\n" + SAFETY + "xy_send(", text)


if __name__ == "__main__":
    unittest.main()
