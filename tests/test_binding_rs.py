import unittest

from langxyne.emitters import emit_binding_rs
from langxyne.tests.support import (
    DOCUMENTED_FUNCTION_GROUPS,
    EXPECTED_BINDING,
    FIXTURE,
    KITCHEN_SINK,
    NOTES,
    REFS,
    UNION_NOT_LISTED,
    UNION_U8_TAG,
    UNIONS,
    assert_matches_expected,
    load,
    mutate,
)

EXPECTED = EXPECTED_BINDING

# UNIONS with an object whose methods drive on_notes and take a list, which the binding
# renders only on a class
UNIONS_ON_A_CLASS = UNIONS + (
    '\n[[opaque_ref]]\n[opaque_ref.log]\n_ctor = "open_log"\n\n'
    '[function.open_log]\n_return = "status"\nhlog = { _type = "log", _ref = "out" }\n\n'
    '[function.walk]\n_return = "status"\nhlog = "log"\nsink = "on_notes"\n\n'
    f'[function.write]\n_return = "status"\nhlog = "log"\n{NOTES}\n'
    'maybe = { _type = "note", _ref = "in", _count = "u32", _optional = true }\n'
)
UNION_NAMES = ("NoteSequence", "NoteRef", "NoteRecords", "UnionError", "UnionClause", "from_c")


def binding(text: str = FIXTURE) -> str:
    return emit_binding_rs.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", project="xy")


class Binding(unittest.TestCase):
    def test_byte_identical_to_expected(self) -> None:
        assert_matches_expected(self, EXPECTED, binding(KITCHEN_SINK))

    def test_plain_conversion_names_the_last_entry_of_a_shared_value(self) -> None:
        text = binding(mutate(KITCHEN_SINK, "extra = 4\n", "extra = 16\n"))
        self.assertIn('        EXTRA => "EXTRA",\n', text)
        self.assertNotIn("MAX_UNITS =>", text)

    def test_an_enums_conversion_is_its_display(self) -> None:
        self.assertIn(
            '            Status::ErrFloor => "ERR_FLOOR",\n        }\n    }\n}\n\n'
            "impl core::fmt::Display for Status {\n"
            "    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {\n"
            "        f.write_str(Status::to_string(*self))\n    }\n}\n",
            binding(KITCHEN_SINK),
        )
        self.assertNotIn("Display", binding(mutate(FIXTURE, '_to_string = "to_string"\n', "")))


class GeneratedTypes(unittest.TestCase):
    def test_no_text_where_no_field_is_text_and_no_filled_where_no_method_renders_a_reported_buffer(self) -> None:
        # fill has no class, so only the ffi block renders its reported buffer
        fill = (
            '\n[function.fill]\n_return = "status"\n'
            'buf = { _type = "memory", _ref = "out", _count = "u32", _wrote_needed = true }\n'
        )
        text = binding(FIXTURE + fill)
        for absent in ("Filled", "Text"):
            self.assertNotIn(absent, text)


class OpaqueByReference(unittest.TestCase):
    """An opaque `in` is its class by reference where it has one, passing the address of
    its handle; an `inout` is the raw handle even with a class, and a raw handle the
    library reads makes the method unsafe."""

    def setUp(self) -> None:
        self.text = binding(REFS)

    def test_an_in_with_a_class_is_the_class_by_reference_and_safe(self) -> None:
        self.assertIn(
            "    pub fn link_to(&self, peer: &DataLink, maybe: Option<&DataLink>) -> Result<(), Status> {\n",
            self.text,
        )
        self.assertIn(
            "            ffi::xy_link_to(\n"
            "                self.handle,\n"
            "                &peer.handle,\n"
            "                maybe.map_or(core::ptr::null(), |c| &c.handle),\n"
            "            )\n",
            self.text,
        )

    def test_an_inout_with_a_class_is_the_raw_handle_and_unsafe(self) -> None:
        self.assertIn(
            "    /// # Safety\n    ///\n"
            "    /// `cur` must be a handle the library issued and has not yet destroyed.\n"
            "    pub unsafe fn relink(&self, cur: &mut ffi::xy_link) -> Result<(), Status> {\n",
            self.text,
        )
        self.assertIn("        let raw = unsafe { ffi::xy_relink(self.handle, cur) };\n", self.text)

    def test_an_in_without_a_class_is_the_raw_handle_and_unsafe(self) -> None:
        self.assertIn(
            "    /// # Safety\n    ///\n"
            "    /// `tok` must be a handle the library issued and has not yet destroyed.\n"
            "    pub unsafe fn lend(&self, tok: &ffi::xy_token) -> Result<(), Status> {\n",
            self.text,
        )
        self.assertIn("        let raw = unsafe { ffi::xy_lend(self.handle, tok) };\n", self.text)


class EnumByReference(unittest.TestCase):
    """An enum reached through `_ref` is converted back only after a successful call."""

    def setUp(self) -> None:
        self.text = binding(REFS)

    def test_writable_ones_are_written_back_after_the_check(self) -> None:
        self.assertIn(
            "            return Err(result);\n        }\n"
            '        *cur = Mode::try_from(cur_raw).expect("xy_steer wrote a cur value xy_mode does not name");\n'
            "        if let (Some(m), Some(v)) = (seen, seen_raw) {\n"
            '            *m = Mode::try_from(v).expect("xy_steer wrote a seen value xy_mode does not name");\n'
            "        }\n"
            "        if let (Some(m), Some(v)) = (last, last_raw) {\n"
            '            *m = Mode::try_from(v).expect("xy_steer wrote a last value xy_mode does not name");\n'
            "        }\n"
            "        Ok(())\n",
            self.text,
        )


class InCall(unittest.TestCase):
    def test_a_method_whose_enum_has_no_nonzero_entry_panics_while_a_call_drives_a_callback(self) -> None:
        ping = '\n[[typed_const]]\n[typed_const.ack]\nacked = 0\n\n[function.ping]\n_return = "ack"\nhport = "port"\n'
        self.assertIn(
            "    pub fn ping(&self) -> Result<(), Ack> {\n"
            "        if let Some(driving) = self._in_call.get() {\n"
            '            panic!("Port::ping called while {driving} is in progress on this Port");\n'
            "        }\n",
            binding(KITCHEN_SINK + ping),
        )
        self.assertNotIn("_in_call", binding(FIXTURE))


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_binding_rs.validate(load(text))

    def test_rust_keyword_as_name(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "unit = ", "match = ")),
            ["rust: function.open_port.match: 'match' is a Rust keyword"],
        )

    def test_name_rustc_calls_not_snake_case(self) -> None:
        rule = "is not snake_case (an uppercase letter or '__'), which rustc requires of it"
        enum_local = mutate(
            REFS, 'cur = { _type = "mode", _ref = "inout" }', 'cur_ = { _type = "mode", _ref = "inout" }'
        )
        for text, where, name in (
            (mutate(FIXTURE, "[function.send]", "[function.Send]"), "function.Send", "Send"),
            (mutate(FIXTURE, "[function.send]", "[function.se__nd]"), "function.se__nd", "se__nd"),
            (mutate(FIXTURE, "unit = ", "Unit = "), "function.open_port.Unit", "Unit"),
            (mutate(FIXTURE, "bytes = ", "Bytes = "), "struct.stats.Bytes", "Bytes"),
            (mutate(FIXTURE, "bytes = ", "by__tes = "), "struct.stats.by__tes", "by__tes"),
            (mutate(FIXTURE, "buf = ", "buf_ = "), "function.send.buf_", "buf__count"),
            (enum_local, "function.steer.cur_", "cur__raw"),
            (
                mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "limitToString"'),
                "untyped_const[0]._to_string",
                "limitToString",
            ),
            (
                mutate(FIXTURE, '_to_string = "to_string"', '_to_string = "toString"'),
                "typed_const.status._to_string",
                "toString",
            ),
        ):
            with self.subTest(name=name):
                self.assertIn(f"rust: {where}: '{name}' {rule}", self.validate(text))

    def test_names_rustc_exempts_are_not_refused(self) -> None:
        # an extern-block function's name and the namespace in it; a parameter only the
        # extern block renders; a method's first parameter, which `self` replaces
        for needle, replacement in (
            ('_namespace = "xy"', '_namespace = "Xy"'),
            ('_namespace = "xy"', '_namespace = "xy_"'),
            ("[function.spend]", "[function.Spend]"),
            ('htoken = "token"', 'hToken = "token"'),
            ('[function.send]\n_return = "status"\nhport = ', '[function.send]\n_return = "status"\nhPort = '),
            ('[function.send]\n_return = "status"\nhport = ', '[function.send]\n_return = "status"\nhandle = '),
        ):
            with self.subTest(replacement=replacement):
                self.assertEqual(self.validate(mutate(FIXTURE, needle, replacement)), [])

    def test_a_name_whose_upper_camel_form_is_a_keyword(self) -> None:
        for text, where in (
            (FIXTURE + '\n[struct.self_]\nv = "u32"\n', "struct.self_"),
            (mutate(FIXTURE, "ok = 0\n", "ok = 0\nself_ = 3\n"), "typed_const.status.self_"),
            (FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.self_]\n_base_type = "u8"\n', "boxed_scalar.self_"),
        ):
            with self.subTest(where=where):
                self.assertIn(f"rust: {where}: 'self_' renders as 'Self', a Rust keyword", self.validate(text))

    def test_opaque_field_is_not_implemented(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'bytes = "u64"', 'bytes = "token"')),
            ["rust: struct.stats.bytes: a field of opaque_ref type is not implemented for Rust"],
        )

    def test_generated_names_are_refused_as_parameters_a_class_renders(self) -> None:
        for name in emit_binding_rs._GENERATED_NAMES:
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(FIXTURE, 'unit = "u32"', f'{name} = "u32"')),
                    [f"rust: function.open_port.{name}: '{name}' is a name the generated code uses"],
                )
                # spend has no class, so only the extern block renders its parameter
                self.assertEqual(self.validate(mutate(FIXTURE, 'htoken = "token"', f'{name} = "token"')), [])

    def test_names_the_class_reaches_only_through_a_path_or_a_field_are_not_refused(self) -> None:
        boxed = FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.offset]\n_base_type = "u64"\n'
        for text in (
            *(
                mutate(boxed, 'unit = "u32"', f'{name} = "u32"')
                for name in (
                    "ffi",
                    "handle",
                    "core",
                    "xy_send",
                    "xy_port",
                    "xy_port_opaque",
                    "xy_status",
                    "u32",
                    "f64",
                    "xy_offset",
                )
            ),
            mutate(boxed, 'pport = { _type = "port"', 'handle = { _type = "port"'),
            mutate(boxed, "[function.send]", "[function.xy_stats]"),
            mutate(boxed, "[function.send]", "[function.u32]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.validate(text), [])

    def test_an_enum_local_is_refused_as_a_parameter_of_its_function(self) -> None:
        want = 'want = { _type = "mode", _ref = "in" }\n'
        self.assertEqual(
            self.validate(mutate(REFS, want, want + 'want_raw = "u32"\n')),
            ["rust: function.steer.want_raw: 'want_raw' is a name the generated code uses"],
        )
        # an enum `out` the caller receives is a local of its own name, with no `_raw` one
        peek = '\n[function.peek]\n_return = "status"\nhport = "port"\nst = { _type = "status", _ref = "out" }\nst_raw = "u32"\n'
        self.assertEqual(self.validate(FIXTURE + peek), [])

    def test_module_scope_collisions(self) -> None:
        for text, message in (
            (
                mutate(FIXTURE, "[[untyped_const]]\n", "[[untyped_const]]\nx = 1\n") + '\n[struct.x]\nv = "u32"\n',
                "X would be defined more than once, by untyped_const.x and struct.x",
            ),
            (
                mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "feat_to_string"'),
                "feat_to_string would be defined more than once, by untyped_bit_const[0]._to_string and untyped_const[0]._to_string",
            ),
            (
                FIXTURE
                + '\n[opaque_ref.h]\n_ctor = "mk"\n_class = "port"\n[function.mk]\n_return = "status"\np = { _type = "h", _ref = "out" }\n',
                "Port would be defined more than once, by opaque_ref.port._class and opaque_ref.h._class",
            ),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.validate(text), [f"rust: module scope: {message}"])

    def test_callback_items_are_module_scope_names_where_generated(self) -> None:
        for name, definer in (
            ("c_len", "the binding's view helper"),
            ("c_slice", "the binding's view helper"),
            ("on_batch_trampoline", "callback.on_batch"),
        ):
            with self.subTest(name=name):
                text = mutate(KITCHEN_SINK, '_to_string = "limit_to_string"', f'_to_string = "{name}"')
                self.assertEqual(
                    self.validate(text),
                    [
                        f"rust: module scope: {name} would be defined more than once, by "
                        f"untyped_const[0]._to_string and {definer}"
                    ],
                )
                self.assertEqual(
                    self.validate(mutate(FIXTURE, '_to_string = "limit_to_string"', f'_to_string = "{name}"')), []
                )
        for struct, name, definer in (
            ("callback_frame", "CallbackFrame", "the binding's callback frame"),
            ("callback_failure", "CallbackFailure", "the binding's callback failure"),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(KITCHEN_SINK + f'\n[struct.{struct}]\nv = "u32"\n'),
                    [f"rust: module scope: {name} would be defined more than once, by struct.{struct} and {definer}"],
                )
                self.assertEqual(self.validate(FIXTURE + f'\n[struct.{struct}]\nv = "u32"\n'), [])

    def test_a_callback_parameter_named_like_a_name_its_trampoline_uses(self) -> None:
        for name in ("frame", "running", "failure", "answer", "callback", "value", "panic"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(KITCHEN_SINK, 'last = "u32"', f'{name} = "u32"')),
                    [f"rust: callback.on_batch.{name}: '{name}' is a name the generated code uses"],
                )

    def test_a_callback_parameter_brings_no_user_data_name_to_the_lint(self) -> None:
        # `sink__user_data` would fail the lint, but the binding renders no `p_user_data`
        self.assertEqual(self.validate(mutate(KITCHEN_SINK, 'sink = "on_batch"', 'sink_ = "on_batch"')), [])

    def test_a_rendered_callbacks_names_rustc_calls_not_snake_case(self) -> None:
        rule = "is not snake_case (an uppercase letter or '__'), which rustc requires of it"
        renamed = mutate(KITCHEN_SINK, "[callback.on_batch]", "[callback.onBatch]")
        for text, where, name in (
            (mutate(KITCHEN_SINK, 'last = "u32"', 'Last = "u32"'), "callback.on_batch.Last", "Last"),
            (mutate(KITCHEN_SINK, "arena = {", "arena_ = {"), "callback.on_batch.arena_", "arena__count"),
            (mutate(renamed, 'sink = "on_batch"', 'sink = "onBatch"'), "callback.onBatch", "onBatch_trampoline"),
        ):
            with self.subTest(where=where):
                self.assertEqual(self.validate(text), [f"rust: {where}: '{name}' {rule}"])

    def test_text_and_filled_are_module_scope_names_where_generated(self) -> None:
        filled = "the generated struct of a reported buffer"
        for text, message in (
            (
                KITCHEN_SINK + '\n[struct.text_]\nv = "u32"\n',
                "Text would be defined more than once, by struct.text_ and the builtin type text",
            ),
            (
                KITCHEN_SINK + '\n[struct.filled]\nv = "u32"\n',
                f"Filled would be defined more than once, by struct.filled and {filled}",
            ),
            (
                mutate(KITCHEN_SINK, '_class = "data_link"', '_class = "filled"'),
                f"Filled would be defined more than once, by {filled} and opaque_ref.link._class",
            ),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.validate(text), [f"rust: module scope: {message}"])
        self.assertEqual(self.validate(FIXTURE + '\n[struct.text_]\nv = "u32"\n[struct.filled]\nv = "u32"\n'), [])

    def test_each_prelude_name_the_binding_spells_is_refused_at_module_scope(self) -> None:
        for name in emit_binding_rs._PRELUDE_NAMES:
            with self.subTest(name=name):
                snake = "".join(f"_{ch.lower()}" if ch.isupper() else ch for ch in name).lstrip("_")
                self.assertEqual(
                    self.validate(FIXTURE + f'\n[struct.{snake}]\nv = "u32"\n'),
                    [
                        f"rust: module scope: {name} would be defined more than once, by the Rust prelude and struct.{snake}"
                    ],
                )

    def test_enums_conversions_never_collide_with_a_groups(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "to_string"')), []
        )

    def test_enum_collisions(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "ok = 0\n", "ok = 0\nerr__busy = 3\n")),
            [
                "rust: enum Status: ErrBusy would be defined more than once, by typed_const.status.err__busy and "
                "typed_const.status.err_busy"
            ],
        )
        self.assertEqual(
            self.validate(mutate(FIXTURE, '_to_string = "to_string"', '_to_string = "try_from"')),
            [
                "rust: enum Status: try_from would be defined more than once, by the generated TryFrom conversion and "
                "typed_const.status._to_string"
            ],
        )

    def test_class_collisions(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.release]")),
            [
                "rust: class Port: release would be defined more than once, by the class's own member and function.release"
            ],
        )
        self.assertEqual(
            self.validate(
                mutate(
                    FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'send = { _type = "u32", _ref = "out" }'
                )
            ),
            ["rust: class Port: send would be defined more than once, by function.send and function.open_port.send"],
        )
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.create]")),
            ["rust: class Port: create would be defined more than once, by the class's own member and function.create"],
        )

    def test_release_is_a_method_name_when_no_release_is_generated(self) -> None:
        text = mutate(mutate(FIXTURE, '_dtor = "destroy_port"\n', ""), "[function.send]", "[function.release]")
        self.assertEqual(self.validate(text), [])


class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_heads_its_first_function_in_ffi_and_a_class(self) -> None:
        text = binding(DOCUMENTED_FUNCTION_GROUPS)
        for expected in (
            "\n        // port lifecycle\n        pub fn xy_open_port(",
            "\n        // traffic\n        /// buf: bytes to send\n        pub fn xy_send(",
            "\n    // port lifecycle\n    pub fn create(",
            "\n    // traffic\n    /// buf: bytes to send\n    pub fn send(",
            "\n    /// release the port\n    pub fn release(",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)


class Unions(unittest.TestCase):
    """A union declaring `_mixed_type_list` renders its ref enum, sequence and walk; its list
    reaches a closure as the sequence and a method as the sequence or an `Option` of it."""

    def test_a_list_union_renders_its_ref_enum_sequence_and_records(self) -> None:
        text = binding(UNIONS)
        for expected in (
            "// what a note is\n/// one note: the struct its head's kind names, head.size bytes long\n"
            "#[derive(Clone, Copy, Debug)]\npub enum NoteRef<'a> {\n    Line(&'a NoteLine),\n"
            "    /// a value and its flag\n    Mark(&'a NoteMark),\n}\n",
            "#[derive(Clone, Copy)]\npub struct NoteSequence<'a> {\n    bytes: &'a [u8],\n    count: u32,\n}\n",
            "    pub fn count(&self) -> u32 {\n",
            "    pub fn bytes(&self) -> &'a [u8] {\n",
            "    pub fn records(&self) -> NoteRecords<'a> {\n",
            "/// The list's alignment, the unit of `NoteSequence::at`'s index.\npub const NOTE_ALIGN: usize = 4;\n",
            "    pub fn at(&self, index: u32) -> Result<NoteRef<'a>, UnionError> {\n"
            "        let offset = index.saturating_mul(NOTE_ALIGN as u32);\n",
            "impl<'a> Iterator for NoteRecords<'a> {\n    type Item = Result<NoteRef<'a>, UnionError>;\n",
            "impl core::iter::FusedIterator for NoteRecords<'_> {}\n",
            "pub struct UnionError {\n    pub index: u32,\n    pub offset: u32,\n    pub clause: UnionClause,\n}\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_the_six_clauses_from_one_and_their_texts(self) -> None:
        text = binding(UNIONS)
        clauses = (
            ("HeaderPastExtent", "header past the extent"),
            ("UnknownTag", "unknown tag"),
            ("SizeNotTheMembers", "size is not the member's"),
            ("RecordPastExtent", "record past the extent"),
            ("CountNotMet", "count not met"),
            ("NotARecordStart", "offset is not a record's start"),
        )
        self.assertIn("#[repr(i32)]\n#[derive(Clone, Copy, Debug, PartialEq, Eq)]\npub enum UnionClause {\n", text)
        self.assertIn("    HeaderPastExtent = 1,\n", text)
        self.assertIn(
            "".join(f'            UnionClause::{variant} => "{clause}",\n' for variant, clause in clauses), text
        )
        self.assertIn('"record {} at offset {}: {}",\n            self.index, self.offset, self.clause\n', text)

    def test_the_prefix_and_each_member_are_held_to_the_loaders_layout(self) -> None:
        text = binding(UNIONS)
        for struct in ("NoteHead", "NoteLine", "NoteMark"):
            size = 8 if struct == "NoteHead" else 16
            with self.subTest(struct=struct):
                self.assertIn(
                    f"const _: () =\n    assert!(core::mem::size_of::<{struct}>() == {size} && "
                    f"core::mem::align_of::<{struct}>() == 4);\n",
                    text,
                )

    def test_a_u8_tag_prefix_is_held_to_its_layout_and_read_by_name(self) -> None:
        self.assertEqual(emit_binding_rs.validate(load(UNION_U8_TAG)), [])
        text = binding(UNION_U8_TAG)
        for expected in (
            "const _: () =\n    assert!(core::mem::size_of::<NoteHead>() == 4 && core::mem::align_of::<NoteHead>() == 2);\n",
            "        let size = match head.kind {\n            1 => 6,\n            2 => 8,\n",
            "        if head.size as usize != size {\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_a_list_is_the_c_functions_pointer_to_the_prefix_count_and_extent(self) -> None:
        self.assertIn(
            "        pub fn xy_replay(\n            notes: *const xy_note_head,\n            notes_count: u32,\n"
            "            notes_bytes: u32,\n        ) -> xy_status;\n",
            binding(UNIONS),
        )

    def test_a_callbacks_list_reaches_the_closure_as_the_sequence_of_its_three_c_parameters(self) -> None:
        text = binding(UNIONS_ON_A_CLASS)
        self.assertIn(
            '    unsafe extern "C" fn trampoline<F: FnMut(NoteSequence<\'_>, u32) -> Flow>(\n'
            "        seen: *const ffi::xy_note_head,\n        seen_count: u32,\n        seen_bytes: u32,\n",
            text,
        )
        self.assertIn(
            "            let seen = unsafe { NoteSequence::from_c(seen, seen_count, seen_bytes) }\n"
            '                .expect("xy_on_notes received view seen outside the definition");\n',
            text,
        )
        self.assertIn(
            "    pub fn walk(&self, sink: impl FnMut(NoteSequence<'_>, u32) -> Flow) -> Result<(), Status> {\n", text
        )

    def test_a_methods_list_is_its_sequence_passed_as_pointer_count_and_extent(self) -> None:
        text = binding(UNIONS_ON_A_CLASS)
        self.assertIn("        notes: NoteSequence<'_>,\n        maybe: Option<NoteSequence<'_>>,\n", text)
        self.assertIn(
            "                notes.bytes().as_ptr().cast(),\n                notes_count,\n                notes_bytes,\n"
            "                maybe\n                    .map_or(core::ptr::null(), |s| s.bytes().as_ptr())\n"
            "                    .cast(),\n                maybe_count,\n                maybe_bytes,\n",
            text,
        )

    def test_a_union_without_the_property_renders_its_structs_alone(self) -> None:
        text = binding(UNION_NOT_LISTED)
        self.assertIn("pub use ffi::xy_note_line as NoteLine;\n", text)
        for name in UNION_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(name, text)

    def test_its_module_scope_names_are_refused_where_rendered(self) -> None:
        for struct, name, definer in (
            ("note_sequence", "NoteSequence", "union.note"),
            ("note_ref", "NoteRef", "union.note"),
            ("note_records", "NoteRecords", "union.note"),
            ("union_error", "UnionError", "the generated union error"),
            ("union_clause", "UnionClause", "the generated union clause"),
        ):
            with self.subTest(name=name):
                extra = f'\n[[struct]]\n[struct.{struct}]\nv = "u32"\n'
                self.assertEqual(
                    emit_binding_rs.validate(load(UNIONS + extra)),
                    [f"rust: module scope: {name} would be defined more than once, by struct.{struct} and {definer}"],
                )
                self.assertEqual(emit_binding_rs.validate(load(UNION_NOT_LISTED + extra)), [])
        self.assertEqual(
            emit_binding_rs.validate(load(mutate(UNIONS, "kind_mark = 2", "kind_mark = 2\nnote_align = 3"))),
            ["rust: module scope: NOTE_ALIGN would be defined more than once, by untyped_const.note_align and union.note"],
        )
        # the relay's buffer, which the binding does not render
        self.assertEqual(emit_binding_rs.validate(load(UNIONS + '\n[[struct]]\n[struct.note_buf]\nv = "u32"\n')), [])

    def test_its_members_are_variants_of_the_ref_enum(self) -> None:
        self.assertEqual(emit_binding_rs.validate(load(UNIONS_ON_A_CLASS)), [])
        self.assertEqual(
            emit_binding_rs.validate(load(mutate(UNIONS, "mark = { _tag", "line_ = { _tag"))),
            ["rust: enum NoteRef: Line would be defined more than once, by union.note.line and union.note.line_"],
        )
        self.assertEqual(
            emit_binding_rs.validate(load(mutate(UNIONS, "mark = { _tag", "self_ = { _tag"))),
            ["rust: union.note.self_: 'self_' renders as 'Self', a Rust keyword"],
        )


if __name__ == "__main__":
    unittest.main()
