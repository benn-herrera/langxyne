import re
import unittest

from langxyne.emitters import emit_binding_cpp
from langxyne.tests.support import (
    DOCUMENTED_FUNCTION_GROUPS,
    FIXTURE,
    KITCHEN_SINK,
    MINIMAL,
    NOTES,
    UNION_NOT_LISTED,
    UNION_U8_TAG,
    UNIONS,
    load,
    mutate,
)

# UNIONS with a class, desk, one method taking the union's list and one driving its callback.
DESK = (
    mutate(
        UNIONS,
        f'[function.replay]\n_return = "status"\n{NOTES}\n',
        '[function.open_desk]\n_return = "status"\nd = { _type = "desk", _ref = "out" }\n\n'
        f'[function.replay]\n_return = "status"\nhdesk = "desk"\n{NOTES}\n\n'
        '[function.watch]\n_return = "status"\nhdesk = "desk"\nsink = "on_notes"\n',
    )
    + '\n[[opaque_ref]]\n[opaque_ref.desk]\n_ctor = "open_desk"\n'
)


def wrapper(text: str = FIXTURE) -> str:
    return emit_binding_cpp.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", project="xy")


class Wrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.text = wrapper()

    def test_includes_the_c_header_then_only_standard_headers(self) -> None:
        includes = [line for line in self.text.splitlines() if line.startswith("#include")]
        self.assertEqual(includes[0], '#include "xy_api.h"')
        for include in includes[1:]:
            self.assertRegex(include, r"#include <\w+>")
        self.assertTrue(self.text.rstrip().endswith("}  // namespace xy"))

    def test_no_exceptions_no_allocation(self) -> None:
        for absent in ("throw", "new ", "malloc", "iostream"):
            self.assertNotIn(absent, self.text)

    def test_no_text_alias_resolver_or_their_headers_where_no_field_is_text(self) -> None:
        for absent in ("Text", "resolve", "<optional>", "<string_view>"):
            self.assertNotIn(absent, self.text)

    def test_no_callback_headers_where_no_class_renders_a_callback(self) -> None:
        for absent in ("<thread>", "<cstdio>", "<cstdlib>", "<memory>", "<type_traits>"):
            self.assertNotIn(absent, self.text)

    def test_class_only_for_opaque_with_ctor(self) -> None:
        self.assertIn("class Port {\n", self.text)
        self.assertNotIn("class Token", self.text)
        self.assertNotIn("xy_spend", self.text)

    def test_no_dtor_no_release(self) -> None:
        text = wrapper(mutate(FIXTURE, '_dtor = "destroy_port"\n', ""))
        self.assertNotIn("~Port", text)
        self.assertNotIn("release()", text)
        self.assertIn("  [[nodiscard]] Status destroy_port() {\n", text)

    def test_references_by_ref(self) -> None:
        text = wrapper(KITCHEN_SINK)
        self.assertIn(
            "  [[nodiscard]] Status configure(const Stats& cfg, const uint32_t& limit, Mode mode, xy_token who) {\n",
            text,
        )
        self.assertIn("  [[nodiscard]] Status stats_of(Stats& out, uint32_t& pcount, xy_link& plink) {\n", text)
        self.assertIn(
            "  [[nodiscard]] Status bump(uint32_t& level, Stats& tally, void* data, uint32_t data_count) {\n", text
        )
        self.assertIn("  [[nodiscard]] Status send(const void* buf, uint64_t buf_count) {\n", text)
        self.assertIn("    return Status(xy_send(handle_, buf, buf_count));\n", text)


class BoxedScalar(unittest.TestCase):
    def setUp(self) -> None:
        self.text = wrapper(KITCHEN_SINK)

    def test_methods_take_it_as_the_c_signature_does(self) -> None:
        self.assertIn("  [[nodiscard]] Status echo_offset(Offset pos, Offset& ppos) {\n", self.text)
        self.assertIn("    return Status(xy_echo_offset(handle_, pos, &ppos));\n", self.text)
        text = wrapper(
            KITCHEN_SINK
            + (
                '\n[function.move]\n_return = "status"\nhport = "port"\n'
                'src = { _type = "offset", _ref = "in" }\ndst = { _type = "offset", _ref = "inout", _optional = true }\n'
            )
        )
        self.assertIn("  [[nodiscard]] Status move(const Offset& src, Offset* dst = nullptr) {\n", text)
        self.assertIn("    return Status(xy_move(handle_, &src, dst));\n", text)


class OptionalParam(unittest.TestCase):
    def test_default_omitted_when_a_non_optional_parameter_follows(self) -> None:
        text = wrapper(
            mutate(
                KITCHEN_SINK,
                'limit = { _type = "u32", _ref = "in" }',
                'limit = { _type = "u32", _ref = "in", _optional = true }',
            )
        )
        self.assertIn(
            "  [[nodiscard]] Status configure(const Stats& cfg, const uint32_t* limit, Mode mode, xy_token who) {\n",
            text,
        )


class BaseTypes(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = wrapper(KITCHEN_SINK)

    def test_untyped_constants_are_auto_from_the_header_macro_under_their_docstring(self) -> None:
        types = {name: c_type for c_type, name in re.findall(r"^inline constexpr (.+) (\w+) = ", self.text, re.M)}
        expected = {"API_VERSION": "auto"}
        lines = self.text.splitlines()
        for group in (*self.api.bit_const_groups, *self.api.const_groups):
            expected |= {c.name.upper(): "auto" for c in group.entries}
            key = group.entries[0].name.upper()
            first = lines.index(f"inline constexpr auto {key} = XY_{key};")
            self.assertEqual(lines[first - 1], f"// {group.docstring}" if group.docstring else "")
        expected |= {c.name.upper(): "const char*" for c in self.api.string_consts}
        self.assertEqual(types, expected)


class InCall(unittest.TestCase):
    def test_a_method_whose_enum_has_no_nonzero_entry_aborts_while_a_call_drives_a_callback(self) -> None:
        ping = '\n[[typed_const]]\n[typed_const.ack]\nacked = 0\n\n[function.ping]\n_return = "ack"\nhport = "port"\n'
        self.assertIn(
            "  [[nodiscard]] Ack ping() {\n"
            "    if (_in_call) {\n"
            '      std::fputs("xy::Port::ping called while ", stderr);\n'
            "      std::fputs(_in_call, stderr);\n"
            '      std::fputs(" is in progress on it\\n", stderr);\n'
            "      std::abort();\n"
            "    }\n",
            wrapper(KITCHEN_SINK + ping),
        )

    def test_the_destructor_and_the_moves_abort_while_a_call_drives_a_callback(self) -> None:
        text = wrapper(KITCHEN_SINK)
        for member, words, field in (
            ("  ~Port() {\n", "destroyed", "_in_call"),
            ("  Port(Port&& other) noexcept\n", "moved", "other._in_call"),
            ("  Port& operator=(Port&& other) noexcept {\n", "moved into", "_in_call"),
            ("  Port& operator=(Port&& other) noexcept {\n", "moved", "other._in_call"),
        ):
            with self.subTest(member=member, words=words):
                body = text[text.index(member) : text.index("\n  }\n", text.index(member))]
                self.assertIn(
                    f"    if ({field}) {{\n"
                    f'      std::fputs("xy::Port {words} while ", stderr);\n'
                    f"      std::fputs({field}, stderr);\n",
                    body,
                )
        self.assertNotIn("_in_call", wrapper(FIXTURE))


class Validate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_binding_cpp.validate(load(text))

    def test_cpp_keyword_as_name(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "unit = ", "class = "), "wrapper: function.open_port.class: 'class' is a C++ keyword"),
            (
                mutate(FIXTURE, "count = { _type", "template = { _type"),
                "wrapper: struct.stats.template: 'template' is a C++ keyword",
            ),
            (FIXTURE + '\n[function.new]\n_return = "status"\n', "wrapper: function.new: 'new' is a C++ keyword"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, self.validate(text))

    def test_generated_names_are_refused_as_parameters(self) -> None:
        for needle, name, where in (
            ('unit = "u32"', "result", "function.open_port.result"),
            ('unit = "u32"', "status", "function.open_port.status"),
            ("buf = { _type", "handle", "function.send.handle"),
            ("buf = { _type", "handle_", "function.send.handle_"),
        ):
            with self.subTest(name=name):
                replacement = needle.replace(needle.split(" ")[0], name, 1)
                self.assertEqual(
                    self.validate(mutate(FIXTURE, needle, replacement)),
                    [f"wrapper: {where}: '{name}' is a name the generated code uses"],
                )

    def test_parameters_no_class_renders_are_not_refused(self) -> None:
        # spend has no class; send's first parameter is the handle the object holds
        for needle, old in (('htoken = "token"', "htoken"), ('[function.send]\n_return = "status"\nhport = ', "hport")):
            for name in ("result", "status", "handle", "handle_", "xy_send", "Stats"):
                with self.subTest(needle=needle, name=name):
                    self.assertEqual(self.validate(mutate(FIXTURE, needle, needle.replace(old, name))), [])

    def test_a_parameter_named_like_a_c_type_is_refused_wherever_it_is_as_the_header_refuses_it(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, 'htoken = "token"', 'xy_status = "token"')),
            ["wrapper: function.spend.xy_status: 'xy_status' is a name the generated code uses"],
        )

    def test_rendered_names_are_refused_as_parameters(self) -> None:
        boxed = FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.offset]\n_base_type = "u64"\n'
        for name in ("xy_send", "xy_port", "xy_status", "Port", "Stats", "Status", "uint32_t", "xy_offset", "Offset"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(boxed, 'unit = "u32"', f'{name} = "u32"')),
                    [f"wrapper: function.open_port.{name}: '{name}' is a name the generated code uses"],
                )

    def test_a_buffers_derived_parameter_named_like_the_c_function_its_method_calls(self) -> None:
        text = (
            FIXTURE + '\n[function.item_count]\n_return = "status"\nhport = "port"\n'
            'xy_item = { _type = "memory", _ref = "out", _count = "u32" }\n'
        )
        self.assertEqual(
            self.validate(text),
            ["wrapper: function.item_count.xy_item: 'xy_item_count' is a name the generated code uses"],
        )

    def test_names_a_callback_method_binds_are_refused_as_its_parameters(self) -> None:
        for name in ("call", "answer", "stderr", "v0", "v7", "sink_call", "sink_trampoline", "F_sink"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.validate(mutate(KITCHEN_SINK, 'batch = "u32"\ncuts = ', f'{name} = "u32"\ncuts = ')),
                    [f"wrapper: function.stream.{name}: '{name}' is a name the generated code uses"],
                )
        # a method without a callback binds none of them
        self.assertEqual(self.validate(mutate(KITCHEN_SINK, 'offset = "u64"', 'call = "u64"')), [])

    def test_a_callback_parameters_template_parameter_named_like_a_rendered_name(self) -> None:
        text = (
            MINIMAL.replace('_namespace = "xy"', '_namespace = "F"')
            + "\n[[typed_const]]\n[typed_const.status]\nok = 0\nhalt = 1\n"
            + '\n[[opaque_ref]]\n[opaque_ref.port]\n_ctor = "open"\n'
            + '\n[[struct]]\n[struct.sink]\nv = "u32"\n'
            + '\n[[callback]]\n[callback.tick]\n_return = "status"\n'
            + '\n[[function]]\n[function.open]\n_return = "status"\np = { _type = "port", _ref = "out" }\n'
            + '\n[function.run]\n_return = "status"\nh = "port"\nsink = "tick"\n'
        )
        self.assertEqual(
            self.validate(text), ["wrapper: function.run.sink: 'F_sink' is a name the generated code uses"]
        )

    def test_rendered_names_are_refused_as_methods(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.Stats]")),
            ["wrapper: function.Stats: 'Stats' is a name the generated code uses"],
        )

    def test_member_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "[function.send]", "[function.release]")),
            [
                "wrapper: class Port: release would be defined more than once, by the class's own member and function.release"
            ],
        )
        self.assertEqual(
            self.validate(
                mutate(
                    FIXTURE, 'generation = { _type = "u32", _ref = "out" }', 'send = { _type = "u32", _ref = "out" }'
                )
            ),
            ["wrapper: class Port: send would be defined more than once, by function.send and function.open_port.send"],
        )

    def test_release_is_a_method_name_when_no_release_is_generated(self) -> None:
        text = mutate(mutate(FIXTURE, '_dtor = "destroy_port"\n', ""), "[function.send]", "[function.release]")
        self.assertEqual(self.validate(text), [])

    def test_enum_class_entry_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(FIXTURE, "ok = 0\n", "ok = 0\nerr__busy = 3\n")),
            [
                "wrapper: enum class Status: ErrBusy would be defined more than once, by typed_const.status.err__busy and "
                "typed_const.status.err_busy"
            ],
        )

    def test_class_collision(self) -> None:
        self.assertEqual(
            self.validate(mutate(KITCHEN_SINK, '_class = "data_link"', '_class = "port"')),
            [
                "wrapper: namespace xy: Port would be defined more than once, by opaque_ref.port._class and "
                "opaque_ref.link._class"
            ],
        )

    def test_namespace_collision(self) -> None:
        text = mutate(FIXTURE, "[[untyped_const]]\n", "[[untyped_const]]\nx = 1\n") + '\n[struct.x]\nv = "u32"\n'
        self.assertEqual(
            self.validate(text),
            ["wrapper: namespace xy: X would be defined more than once, by untyped_const.x and struct.x"],
        )

    def test_boxed_scalar_alias_is_in_the_namespace_list(self) -> None:
        text = FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.offset]\n_base_type = "u64"\n\n[struct.Offset]\nv = "u32"\n'
        self.assertEqual(
            self.validate(text),
            ["wrapper: namespace xy: Offset would be defined more than once, by boxed_scalar.offset and struct.Offset"],
        )

    def test_the_text_alias_and_resolver_are_in_the_namespace_list_where_a_field_is_text(self) -> None:
        for needle, replacement, message in (
            (
                '_class = "data_link"',
                '_class = "text"',
                "Text would be defined more than once, by the builtin type text and opaque_ref.link._class",
            ),
            (
                '_to_string = "limit_to_string"',
                '_to_string = "resolve"',
                "resolve would be defined more than once, by the generated text resolver and untyped_const[0]._to_string",
            ),
        ):
            with self.subTest(replacement=replacement):
                self.assertEqual(
                    self.validate(mutate(KITCHEN_SINK, needle, replacement)), [f"wrapper: namespace xy: {message}"]
                )
        self.assertEqual(self.validate(mutate(FIXTURE, '_to_string = "limit_to_string"', '_to_string = "resolve"')), [])

    def test_conversion_collisions(self) -> None:
        for needle, name, message in (
            (
                '_to_string = "limit_to_string"',
                "to_string",
                "to_string would be defined more than once, by untyped_const[0]._to_string and typed_const.status._to_string",
            ),
            (
                '_to_string = "feat_to_string"',
                "limit_to_string",
                "limit_to_string would be defined more than once, by untyped_bit_const[0]._to_string and untyped_const[0]._to_string",
            ),
            (
                '_to_string = "limit_to_string"',
                "Stats",
                "Stats would be defined more than once, by struct.stats and untyped_const[0]._to_string",
            ),
        ):
            with self.subTest(message=message):
                text = mutate(FIXTURE, needle, f'_to_string = "{name}"')
                self.assertEqual(self.validate(text), [f"wrapper: namespace xy: {message}"])


MARK_MEMBER_LINE = 'mark = { _tag = "kind_mark", _type = "note_mark", _docstring = "a value and its flag" }\n'
# UNIONS with a second listed union, tick, whose prefix is a struct of its own.
TICK = mutate(
    mutate(
        UNIONS,
        "[[union]]\n",
        '[struct.tick_head]\nkind = "u32"\nsize = "u32"\n\n[struct.tick_beat]\nhead = "tick_head"\n\n[[union]]\n',
    ),
    MARK_MEMBER_LINE,
    MARK_MEMBER_LINE + '\n[union.tick]\n_mixed_type_list = true\nbeat = { _tag = "kind_line", _type = "tick_beat" }\n',
)


class Unions(unittest.TestCase):
    def setUp(self) -> None:
        self.text = wrapper(DESK)

    def test_the_clause_enum_class_over_the_c_enum_and_the_error(self) -> None:
        self.assertIn(
            "enum class UnionClause : int32_t {\n"
            "  HeaderPastExtent = XY_UNION_HEADER_PAST_EXTENT,  // header past the extent\n"
            "  UnknownTag = XY_UNION_UNKNOWN_TAG,  // unknown tag\n"
            "  SizeNotTheMembers = XY_UNION_SIZE_NOT_THE_MEMBERS,  // size is not the member's\n"
            "  RecordPastExtent = XY_UNION_RECORD_PAST_EXTENT,  // record past the extent\n"
            "  CountNotMet = XY_UNION_COUNT_NOT_MET,  // count not met\n"
            "  NotARecordStart = XY_UNION_NOT_A_RECORD_START,  // offset is not a record's start\n"
            "};\n",
            self.text,
        )
        error = "struct UnionError {{\n  {t} index;\n  {t} offset;\n  UnionClause clause;\n}};\n"
        self.assertIn(error.format(t="uint32_t"), self.text)
        self.assertIn(error.format(t="uint64_t"), wrapper(mutate(DESK, '_count = "u32"', '_count = "u64"', every=True)))
        self.assertEqual(wrapper(TICK).count("enum class UnionClause"), 1)

    def test_the_clause_text_conversion_is_a_switch_over_the_enum_class(self) -> None:
        self.assertIn(
            "\ninline const char* union_clause_text(UnionClause value) {\n"
            "  switch (value) {\n"
            '    case UnionClause::HeaderPastExtent: return "header past the extent";\n'
            '    case UnionClause::UnknownTag: return "unknown tag";\n'
            '    case UnionClause::SizeNotTheMembers: return "size is not the member\'s";\n'
            '    case UnionClause::RecordPastExtent: return "record past the extent";\n'
            '    case UnionClause::CountNotMet: return "count not met";\n'
            '    case UnionClause::NotARecordStart: return "offset is not a record\'s start";\n'
            "  }\n"
            '  return "UNKNOWN_UNION_CLAUSE";\n'
            "}\n",
            self.text,
        )

    def test_the_sequence_is_a_range_over_the_prefix_of_the_unions_count_type(self) -> None:
        for count_type, c_type in (("u32", "uint32_t"), ("u16", "uint16_t")):
            with self.subTest(count_type=count_type):
                text = wrapper(mutate(DESK, '_count = "u32"', f'_count = "{count_type}"', every=True))
                start = text.index("\nclass NoteSequence {\n")
                body = text[start : text.index("\n};\n", text.index("\n  };\n", start) + 1)]
                for line in (
                    "    using iterator_category = std::forward_iterator_tag;\n",
                    "    using reference = const NoteHead&;\n",
                    f"  NoteSequence(const NoteHead* list, {c_type} count, {c_type} bytes) noexcept",
                    "  [[nodiscard]] const NoteHead* data() const noexcept {",
                    f"  [[nodiscard]] {c_type} count() const noexcept {{",
                    f"  [[nodiscard]] {c_type} bytes() const noexcept {{",
                    "  [[nodiscard]] iterator begin() const noexcept {",
                    "  [[nodiscard]] iterator end() const noexcept {",
                    "  [[nodiscard]] std::optional<UnionError> error() const noexcept {",
                    f"  // the list's alignment, the unit of at()'s index\n  static constexpr {c_type} align = 4;\n",
                    f"  [[nodiscard]] const NoteHead* at({c_type} index) const noexcept {{\n"
                    "    error_.reset();\n"
                    f"    const {c_type} offset = index <= {c_type}({c_type}(-1) / align) ? {c_type}(index * align) : "
                    f"{c_type}(-1);\n",
                ):
                    self.assertIn(line, body)

    def test_as_is_checked_on_the_tag_and_compiles_only_for_a_member(self) -> None:
        self.assertIn(
            "\n// the record as member T, or nullptr where its tag is another member's; T must be a member of note\n"
            "template <class T>\n"
            "[[nodiscard]] const T* as(const NoteHead& record) noexcept {\n"
            '  static_assert(std::is_same_v<T, NoteLine> || std::is_same_v<T, NoteMark>, "T must be a member of union note");\n',
            self.text,
        )

    def test_a_u8_tag_types_as_and_the_length_is_read_by_name(self) -> None:
        self.assertEqual(emit_binding_cpp.validate(load(UNION_U8_TAG)), [])
        text = wrapper(UNION_U8_TAG)
        for expected in (
            "  constexpr uint8_t tag =\n"
            "      std::is_same_v<T, NoteLine> ? uint8_t(KIND_LINE) :\n      uint8_t(KIND_MARK);\n"
            "  return record.kind == tag ? reinterpret_cast<const T*>(&record) : nullptr;\n",
            "      offset_ = uint32_t(offset_ + record_->size);\n",
            "      here = uint32_t(here + record->size);\n",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_one_as_per_prefix(self) -> None:
        text = wrapper(TICK)
        self.assertIn("[[nodiscard]] const T* as(const NoteHead& record) noexcept {\n", text)
        self.assertIn("[[nodiscard]] const T* as(const TickHead& record) noexcept {\n", text)

    def test_a_callable_receives_a_lists_view_as_its_sequence(self) -> None:
        self.assertIn("(*call.callable)(NoteSequence(v0, v1, v2), v3)", self.text)

    def test_the_sequence_states_its_callers_duties(self) -> None:
        self.assertIn(
            "// the records of a sequence a callback receives are valid for that call of the callback only;\n"
            "// incrementing an iterator equal to end(), a walk ended or refused, is undefined, as for any forward "
            "iterator\n"
            "class NoteSequence {\n",
            self.text,
        )

    def test_a_methods_list_parameter_is_a_sequence_passed_as_the_three_c_parameters(self) -> None:
        self.assertIn("  [[nodiscard]] Status replay(NoteSequence notes) {\n", self.text)
        self.assertIn("    return Status(xy_replay(handle_, notes.data(), notes.count(), notes.bytes()));\n", self.text)

    def test_the_sequence_headers_follow_the_aliases_and_precede_the_classes(self) -> None:
        for header in ("<cstddef>", "<iterator>", "<optional>", "<type_traits>"):
            self.assertIn(f"#include {header}\n", wrapper(UNIONS))
        self.assertLess(self.text.index("using NoteMark = xy_note_mark;"), self.text.index("enum class UnionClause"))
        self.assertLess(self.text.index("// what a note is\n// one note:"), self.text.index("class NoteSequence {"))
        self.assertLess(self.text.index("const T* as("), self.text.index("class Desk {"))

    def test_a_union_without_the_property_renders_its_structs_and_nothing_more(self) -> None:
        text = wrapper(UNION_NOT_LISTED)
        self.assertIn(
            "using NoteHead = xy_note_head;\nusing NoteLine = xy_note_line;\nusing NoteMark = xy_note_mark;\n", text
        )
        for absent in ("Sequence", "Union", " as(", "<iterator>", "<cstddef>", "<type_traits>"):
            self.assertNotIn(absent, text)


class UnionValidate(unittest.TestCase):
    def validate(self, text: str) -> list[str]:
        return emit_binding_cpp.validate(load(text))

    def test_a_union_renders_rather_than_being_refused(self) -> None:
        for text in (UNIONS, DESK, TICK, UNION_NOT_LISTED):
            self.assertEqual(self.validate(text), [])

    def test_the_union_names_are_free_in_the_namespace(self) -> None:
        for text, message in (
            (
                UNIONS + '\n[struct.note_sequence]\nv = "u32"\n',
                "NoteSequence would be defined more than once, by struct.note_sequence and union.note",
            ),
            (
                UNIONS + '\n[struct.union_error]\nv = "u32"\n',
                "UnionError would be defined more than once, by struct.union_error and the generated union error",
            ),
            (
                mutate(UNIONS, "[typed_const.flow]\n", "[typed_const.union_clause]\nnone = 0\n\n[typed_const.flow]\n"),
                "UnionClause would be defined more than once, by typed_const.union_clause and the generated union clause",
            ),
            (
                mutate(UNIONS, "kind_mark = 2\n", 'kind_mark = 2\n_to_string = "as"\n'),
                "as would be defined more than once, by union.note and untyped_const[0]._to_string",
            ),
            (
                mutate(UNIONS, "kind_mark = 2\n", 'kind_mark = 2\n_to_string = "union_clause_text"\n'),
                "union_clause_text would be defined more than once, by the generated union clause text and "
                "untyped_const[0]._to_string",
            ),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.validate(text), [f"wrapper: namespace xy: {message}"])

    def test_two_unions_of_one_prefix_are_refused_at_as(self) -> None:
        text = mutate(
            UNIONS,
            MARK_MEMBER_LINE,
            MARK_MEMBER_LINE
            + '\n[union.other]\n_mixed_type_list = true\nline = { _tag = "kind_line", _type = "note_line" }\n',
        )
        self.assertEqual(
            self.validate(text),
            [
                "wrapper: namespace xy: as(const NoteHead&) would be defined more than once, by union.note and union.other"
            ],
        )

    def test_a_sequence_class_is_a_rendered_name(self) -> None:
        self.assertEqual(
            self.validate(mutate(DESK, f'hdesk = "desk"\n{NOTES}', f'hdesk = "desk"\n{NOTES}\nNoteSequence = "u32"')),
            ["wrapper: function.replay.NoteSequence: 'NoteSequence' is a name the generated code uses"],
        )


CONVERSION = re.compile(r"^inline (const char\*|std::string) (\w+)\((\w+) value\) \{$", re.M)


class ToString(unittest.TestCase):
    def test_only_groups_with_the_property_have_a_conversion(self) -> None:
        self.assertEqual(
            [name for _, name, param in CONVERSION.findall(wrapper(KITCHEN_SINK))],
            ["access_to_string", "limit_to_string", "to_string", "to_string", "union_clause_text"],
        )
        text = FIXTURE
        for needle in (
            '_to_string = "feat_to_string"\n',
            '_to_string = "limit_to_string"\n',
            '_to_string = "to_string"\n',
        ):
            text = mutate(text, needle, "")
        text = wrapper(text)
        self.assertEqual(CONVERSION.findall(text), [])
        self.assertNotIn("#include <string>", text)
        self.assertNotIn("#include <charconv>", text)

    def test_parameter_is_the_group_base_type(self) -> None:
        text = wrapper(
            mutate(
                KITCHEN_SINK, '_base_type = "u32"\nmagic', '_base_type = "u32"\n_to_string = "wire_to_string"\nmagic'
            )
        )
        self.assertIn(("std::string", "wire_to_string", "uint32_t"), CONVERSION.findall(text))

    def test_switch_names_the_last_entry_of_a_plain_group_shared_value(self) -> None:
        text = wrapper(mutate(KITCHEN_SINK, "extra = 4\n", "extra = 16\n"))
        self.assertIn('    case EXTRA: return "EXTRA";\n', text)
        self.assertNotIn("case MAX_UNITS:", text)
        self.assertIn('return "UNKNOWN";', text)
        self.assertIn('    case Status::ErrBusy: return "ERR_BUSY";\n', text)
        self.assertIn('return "UNKNOWN_STATUS";', text)


class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_heads_its_first_function_in_a_class(self) -> None:
        text = wrapper(DOCUMENTED_FUNCTION_GROUPS)
        self.assertIn("\n  // port lifecycle\n  [[nodiscard]] static Port create(", text)
        self.assertIn("\n  // traffic\n  // buf: bytes to send\n  [[nodiscard]] Status send(", text)
        self.assertIn("\n  // release the port\n  [[nodiscard]] Status release()", text)


if __name__ == "__main__":
    unittest.main()
