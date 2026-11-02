import unittest

from langxyne import model
from langxyne.emitters import c, emit_c
from langxyne.tests.support import (
    DOCUMENTED_FUNCTION_GROUPS,
    FIXTURE,
    KITCHEN_SINK,
    NO_WRAPPED_API,
    UNION_NOT_LISTED,
    UNION_U8_TAG,
    UNIONS,
    buffer_expansion,
    header,
    load,
    mutate,
    param_lists,
)


class Preprocessor(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = header(self.api)

    def test_only_permitted_preprocessor_lines(self) -> None:
        allowed = ("#pragma once", "#include", "#if", "#else", "#endif", "# define", "# include", "#define XY_")
        for line in self.text.splitlines():
            if line.startswith("#"):
                self.assertTrue(line.startswith(allowed), line)

    def test_consumer_includes_only_stdint(self) -> None:
        prelude = self.text[: self.text.rindex("#if defined(XY_IMPL)")]
        include_lines = [line for line in prelude.splitlines() if line.startswith(("#include", "# include"))]
        self.assertEqual(include_lines, ["#include <stdint.h>"])


class Pins(unittest.TestCase):
    def test_no_implementation_block_without_a_wrapped_api(self) -> None:
        text = header(load(NO_WRAPPED_API))
        self.assertNotIn("#if defined(XY_IMPL)\n# include", text)
        self.assertNotIn("static_assert", text)

    def test_wrapped_header_included_without_pins(self) -> None:
        text = header(load(mutate(FIXTURE, 'feat_a = "XYD_FEAT_A"\n', "")))
        self.assertIn('#if defined(XY_IMPL)\n# include "xy/driver/xy_ioctl.h"\n', text)
        self.assertNotIn("static_assert", text)

    def test_one_include_per_wrapped_header_in_list_order(self) -> None:
        text = header(
            load(mutate(FIXTURE, '_headers = ["driver/xy_ioctl.h"]', '_headers = ["driver/b.h", "driver/a.h"]'))
        )
        self.assertIn('#if defined(XY_IMPL)\n# include "xy/driver/b.h"\n# include "xy/driver/a.h"\n', text)


class Declarations(unittest.TestCase):
    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = header(self.api)

    def test_type_mapping_follows_the_spec_table(self) -> None:
        rows = (
            (("i8", None), "int8_t"),
            (("u8", None), "uint8_t"),
            (("i16", None), "int16_t"),
            (("u16", None), "uint16_t"),
            (("i32", None), "int32_t"),
            (("u32", None), "uint32_t"),
            (("i64", None), "int64_t"),
            (("u64", None), "uint64_t"),
            (("f32", None), "float"),
            (("f64", None), "double"),
            (("f64", "in"), "const double*"),
            (("i64", "out"), "int64_t*"),
            (("status", None), "xy_status"),
            (("stats", None), "xy_stats"),
            (("port", None), "xy_port"),
            (("offset", None), "xy_offset"),
            (("offset", "in"), "const xy_offset*"),
            (("offset", "out"), "xy_offset*"),
            (("offset", "inout"), "xy_offset*"),
            (("stats", "in"), "const xy_stats*"),
            (("stats", "out"), "xy_stats*"),
            (("stats", "inout"), "xy_stats*"),
            (("u32", "in"), "const uint32_t*"),
            (("u32", "out"), "uint32_t*"),
            (("u32", "inout"), "uint32_t*"),
            (("memory", "in"), "const void*"),
            (("memory", "out"), "void*"),
            (("memory", "inout"), "void*"),
            (("on_batch", None), "xy_on_batch"),
        )
        for (type_name, ref), expected in rows:
            count_type = "u32" if type_name == "memory" else None
            param = model.Param(
                name="p",
                type=type_name,
                ref=ref,
                count_type=count_type,
                optional=False,
                wrote_needed=False,
                docstring=None,
                callback=type_name == "on_batch",
            )
            with self.subTest(type=type_name, ref=ref):
                self.assertEqual(c.param_type(self.api, param), expected)
        # an array is a pointer to its element, whatever counts it, `const` for `in`
        for type_name, ref, expected in (
            ("u16", "out", "uint16_t*"),
            ("offset", "out", "xy_offset*"),
            ("cut", "in", "const xy_cut*"),
        ):
            param = model.Param(
                name="p",
                type=type_name,
                ref=ref,
                count_type="u8",
                optional=False,
                wrote_needed=ref == "out",
                docstring=None,
            )
            with self.subTest(array=type_name):
                self.assertEqual(c.param_type(self.api, param), expected)

    def test_functions_declared_in_document_order_with_parameters_in_order(self) -> None:
        decls = param_lists(self.text, r"XY_API xy_status ")
        self.assertEqual(list(decls), [f.name for f in self.api.functions])
        for f in self.api.functions:
            with self.subTest(function=f.name):
                if f.params:
                    names = [s.rsplit(" ", 1)[1] for s in decls[f.name].split(", ")]
                    expected = [n for p in f.params for n in buffer_expansion(p)]
                    self.assertEqual(names, expected)
                else:
                    self.assertEqual(decls[f.name], "void")

    def test_a_buffer_is_a_pointer_and_count_and_each_report_a_pointer_to_the_count_type(self) -> None:
        decls = param_lists(self.text, r"XY_API xy_status ")
        self.assertEqual(decls["send"], "xy_port hport, const void* buf, uint64_t buf_count")
        self.assertEqual(decls["recv"], "xy_port hport, void* pdst, uint32_t pdst_count")
        self.assertEqual(
            decls["bump"], "xy_port hport, uint32_t* level, xy_stats* tally, void* data, uint32_t data_count"
        )
        self.assertEqual(
            decls["list"],
            "xy_port hport, xy_entry* items, uint64_t items_count, uint64_t* items_wrote, uint64_t* items_needed, "
            "void* labels, uint32_t labels_count, uint32_t* labels_wrote, uint32_t* labels_needed",
        )

    def test_the_text_type_follows_the_boxed_scalars_and_precedes_the_structs_only_where_a_field_is_text(self) -> None:
        typedef = "\ntypedef struct xy_text { uint32_t offset; uint32_t length; } xy_text;\n"
        self.assertLess(self.text.index("typedef struct xy_offset "), self.text.index(typedef))
        self.assertLess(self.text.index(typedef), self.text.index("struct xy_stats {"))
        self.assertNotIn("xy_text", header(load(FIXTURE)))

    def test_a_callback_type_follows_the_last_struct_and_precedes_the_first_function(self) -> None:
        typedef = self.text.index("typedef xy_flow (*xy_on_batch)(")
        self.assertLess(self.text.index("typedef struct xy_entry xy_entry;"), typedef)
        self.assertLess(typedef, self.text.index("XY_API xy_status xy_open_port("))

    def test_untyped_constants_are_macros_in_the_spec_spelling(self) -> None:
        lines = set(self.text.splitlines())
        for expected in (
            "#define XY_API_VERSION UINT32_C(0x01020304)",
            "#define XY_FEAT_A (INT32_C(1) << 0)",
            "#define XY_FEAT_B (INT32_C(1) << 3) /* the b feature */",
            "#define XY_FEAT_AB (XY_FEAT_A | XY_FEAT_B)",
            "#define XY_FEAT_LIT (XY_FEAT_A | INT32_C(4))",
            "#define XY_ACC_AB (XY_ACC_A | XY_ACC_B)",
            "#define XY_MAX_UNITS INT32_C(16)",
            "#define XY_MAX_TOTAL (XY_MAX_UNITS + XY_EXTRA)",
            "#define XY_MAGIC UINT32_C(0xbeef) /* wire magic */",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, lines)

    def test_negative_value_is_the_macro_of_its_magnitude_negated(self) -> None:
        lines = set(self.text.splitlines())
        for expected in (
            "#define XY_NEG (-INT32_C(0x5))",
            "#define XY_LOW (-INT32_C(7))",
            "#define XY_FLOOR (-INT32_C(0x7fffffff) - 1)",
            "#define XY_DIP (XY_MAX_UNITS + (-INT32_C(3)))",
            "  XY_ERR_FLOOR = (-INT32_C(0x7fffffff) - 1)",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, lines)
        decimal = mutate(KITCHEN_SINK, '\nfloor = { _value = -2147483648, _format = "hex" }', "\nfloor = -2147483648")
        decimal_min = header(load(decimal))
        self.assertIn("#define XY_FLOOR (-INT32_C(2147483647) - 1)", decimal_min.splitlines())

    def test_literal_term_renders_from_its_parsed_value(self) -> None:
        text = header(load(mutate(FIXTURE, '["feat_a", "feat_b"]', '["feat_a", "0x1E"]')))
        self.assertIn("#define XY_FEAT_AB (XY_FEAT_A | INT32_C(0x1e))", text.splitlines())

    def test_u32_group_literal_term_takes_the_u32_macro(self) -> None:
        self.assertIn("#define XY_FEAT_ALL (XY_FEAT_ONE | UINT32_C(8))\n", self.text)

    def test_each_constant_group_is_one_run_of_macros_under_its_docstring(self) -> None:
        lines = self.text.splitlines()
        for group in (*self.api.bit_const_groups, *self.api.const_groups):
            first = lines.index(
                next(line for line in lines if line.startswith(f"#define XY_{group.entries[0].name.upper()} "))
            )
            with self.subTest(first=group.entries[0].name):
                self.assertEqual(lines[first - 1], f"/* {group.docstring} */" if group.docstring else "")
                run = lines[first : first + len(group.entries)]
                self.assertEqual(
                    [line.split()[1] for line in run], [f"XY_{entry.name.upper()}" for entry in group.entries]
                )
                self.assertEqual(lines[first + len(group.entries)], "")

    def test_typed_groups_stay_enums(self) -> None:
        self.assertIn("enum xy_status {\n  XY_OK = 0,\n", self.text)
        self.assertIn("typedef enum xy_status xy_status;\n", self.text)
        self.assertIn("enum xy_mode {\n", self.text)
        self.assertNotIn("#define XY_OK", self.text)
        self.assertNotIn("enum {", self.text)

    def test_boxed_scalar_is_a_one_member_struct_under_its_docstring(self) -> None:
        self.assertIn("\n/* a device offset */\ntypedef struct xy_offset { uint64_t value; } xy_offset;\n", self.text)
        self.assertEqual(
            param_lists(self.text, r"XY_API xy_status ")["echo_offset"], "xy_port hport, xy_offset pos, xy_offset* ppos"
        )
        for base_type, c_type in (("i8", "int8_t"), ("u32", "uint32_t"), ("i64", "int64_t")):
            with self.subTest(base_type=base_type):
                text = header(load(mutate(KITCHEN_SINK, '_base_type = "u64"', f'_base_type = "{base_type}"')))
                self.assertIn(f"typedef struct xy_offset {{ {c_type} value; }} xy_offset;\n", text)

    def test_boxed_scalar_precedes_a_struct_holding_it(self) -> None:
        text = header(load(KITCHEN_SINK + '\n[struct.span]\nat = "offset"\n'))
        self.assertIn("struct xy_span {\n\txy_offset at;\n};\n", text)
        self.assertLess(text.index("typedef struct xy_offset "), text.index("struct xy_span {"))

    def test_docstrings_placed_per_spec(self) -> None:
        lines = self.text.splitlines()

        def index_of(fragment: str) -> int:
            return next(i for i, line in enumerate(lines) if fragment in line)

        self.assertEqual(lines[index_of("enum xy_status {") - 1], "/* call outcome */")
        self.assertIn("/* try later */", lines[index_of("XY_ERR_BUSY = 9")])
        self.assertIn("/* items seen */", lines[index_of("uint32_t count;")])
        self.assertIn("buf: bytes to send", lines[index_of("XY_API xy_status xy_send(") - 1])
        self.assertEqual(lines[index_of("XY_API xy_status xy_destroy_port(") - 1], "/* release the port */")

    def test_a_function_groups_docstring_is_a_comment_line_above_its_first_function_and_that_ones_comment(self) -> None:
        text = header(load(DOCUMENTED_FUNCTION_GROUPS))
        self.assertIn("\n/* port lifecycle */\nXY_API xy_status xy_open_port(", text)
        self.assertIn("\n/* release the port */\nXY_API xy_status xy_destroy_port(", text)
        self.assertIn("\n/* traffic */\n/* buf: bytes to send */\nXY_API xy_status xy_send(", text)
        self.assertEqual(text.count("/* port lifecycle */"), 1)


class Validate(unittest.TestCase):
    def test_c_keyword_as_name(self) -> None:
        for text, message in (
            (mutate(FIXTURE, "bytes = ", "int = "), "header: struct.stats.int: 'int' is a C keyword"),
            (
                mutate(FIXTURE, 'unit = "u32"', 'restrict = "u32"'),
                "header: function.open_port.restrict: 'restrict' is a C keyword",
            ),
            (FIXTURE + '\n[function.while]\n_return = "status"\n', "header: function.while: 'while' is a C keyword"),
        ):
            with self.subTest(message=message):
                self.assertIn(message, emit_c.validate(load(text)))

    def test_constant_named_like_a_header_macro(self) -> None:
        for needle, replacement, where, macro in (
            ("feat_a = 0\n", "feat_a = 0\napi = 5\n", "untyped_bit_const.api", "XY_API"),
            ("max_units = 16", "c_api = 16", "untyped_const.c_api", "XY_C_API"),
            ('product = "xy widget"', 'impl = "x"', "string_const.impl", "XY_IMPL"),
            ("err_busy = ", "api = ", "typed_const.status.api", "XY_API"),
        ):
            with self.subTest(where=where):
                self.assertEqual(
                    emit_c.validate(load(mutate(FIXTURE, needle, replacement))),
                    [f"header: {where}: constant {macro} is the header's own macro"],
                )

    def test_typed_enum_value_above_the_i32_maximum_is_not_an_enumerator(self) -> None:
        u32 = mutate(FIXTURE, '_docstring = "call outcome"', '_base_type = "u32"')
        self.assertEqual(
            emit_c.validate(load(mutate(u32, "0x7fffffff", "0x80000000"))),
            ["header: typed_const.status.err_other: value 0x80000000 exceeds 0x7fffffff; a C17 enumerator is an int"],
        )
        self.assertEqual(emit_c.validate(load(u32)), [])

    def test_parameter_named_like_a_type_the_declarations_spell(self) -> None:
        # in a prototype the name would hide the type from every parameter after it
        boxed = FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.offset]\n_base_type = "u64"\n'
        for name in ("uint32_t", "int8_t", "xy_status", "xy_port", "xy_stats", "xy_offset"):
            with self.subTest(name=name):
                self.assertEqual(
                    emit_c.validate(load(mutate(boxed, 'htoken = "token"', f'{name} = "token"'))),
                    [f"header: function.spend.{name}: '{name}' is a name the generated code uses"],
                )
        self.assertEqual(emit_c.validate(load(mutate(FIXTURE, 'htoken = "token"', 'xy_send = "token"'))), [])

    def test_a_parameter_named_like_a_callback_type_is_refused(self) -> None:
        for needle, where in (('htoken = "token"', "function.spend"), ('last = "u32"', "callback.on_batch")):
            with self.subTest(where=where):
                renamed = needle.replace(needle.split(" ")[0], "xy_on_batch", 1)
                self.assertEqual(
                    emit_c.validate(load(mutate(KITCHEN_SINK, needle, renamed))),
                    [f"header: {where}.xy_on_batch: 'xy_on_batch' is a name the generated code uses"],
                )

    def test_a_parameter_named_like_the_text_type_is_refused_only_where_it_is_declared(self) -> None:
        named = 'xy_text = "token"'
        self.assertEqual(
            emit_c.validate(load(mutate(KITCHEN_SINK, 'htoken = "token"', named))),
            ["header: function.spend.xy_text: 'xy_text' is a name the generated code uses"],
        )
        self.assertEqual(emit_c.validate(load(mutate(FIXTURE, 'htoken = "token"', named))), [])

    def test_a_buffers_count_or_report_named_like_a_type_is_refused_as_a_parameter_is(self) -> None:
        for struct in ("count", "wrote", "needed"):
            with self.subTest(struct=struct):
                text = mutate(KITCHEN_SINK, "labels = ", "xy = ") + f'\n[struct.{struct}]\nv = "u32"\n'
                self.assertEqual(
                    emit_c.validate(load(text)),
                    [f"header: function.list.xy: 'xy_{struct}' is a name the generated code uses"],
                )


class UnionList(unittest.TestCase):
    """A union declaring _mixed_type_list: the clause enum, the list's helpers and its parameters."""

    def setUp(self) -> None:
        self.api = load(UNIONS)
        self.text = header(self.api)
        self.lines = self.text.splitlines()

    def test_the_header_renders_a_union(self) -> None:
        self.assertEqual(emit_c.validate(self.api), [])

    def test_each_helper_is_static_inline_with_its_spec_signature(self) -> None:
        # count and extent of the union's one count type, u32 in UNIONS
        u16 = header(load(mutate(UNIONS, '_count = "u32"', '_count = "u16"', every=True))).splitlines()
        for lines, ct in ((self.lines, "uint32_t"), (u16, "uint16_t")):
            for signature in (
                "static inline uint32_t xy_note_member_size(uint16_t tag) {",
                f"static inline xy_union_clause xy_note_record_clause(const xy_note_head* record, {ct} at, {ct} bytes) {{",
                f"static inline const xy_note_head* xy_note_first(const xy_note_head* list, {ct} bytes) {{",
                f"static inline const xy_note_head* xy_note_next(const xy_note_head* list, const xy_note_head* cur, "
                f"{ct} bytes) {{",
                f"static inline xy_union_clause xy_note_well_formed(const xy_note_head* list, {ct} count, {ct} bytes, "
                f"{ct}* index, {ct}* offset) {{",
            ):
                with self.subTest(signature=signature):
                    self.assertIn(signature, lines)

    def test_the_lists_alignment_is_a_macro_of_the_layouts(self) -> None:
        for text, align in ((UNIONS, 4), (UNION_U8_TAG, 2)):
            with self.subTest(align=align):
                self.assertIn(
                    f"/* the list's alignment, the unit of every binding's `at` index */\n"
                    f"#define XY_NOTE_ALIGN UINT32_C({align})\n",
                    header(load(text)),
                )

    def test_the_clause_enum_is_the_six_clauses_in_order_each_trailed_by_its_text(self) -> None:
        start = self.lines.index("enum xy_union_clause {")
        self.assertEqual(
            self.lines[start + 1 : self.lines.index("};", start) + 2],
            [
                "  XY_UNION_OK = 0,",
                "  XY_UNION_HEADER_PAST_EXTENT = 1, /* header past the extent */",
                "  XY_UNION_UNKNOWN_TAG = 2, /* unknown tag */",
                "  XY_UNION_SIZE_NOT_THE_MEMBERS = 3, /* size is not the member's */",
                "  XY_UNION_RECORD_PAST_EXTENT = 4, /* record past the extent */",
                "  XY_UNION_COUNT_NOT_MET = 5, /* count not met */",
                "  XY_UNION_NOT_A_RECORD_START = 6 /* offset is not a record's start */",
                "};",
                "typedef enum xy_union_clause xy_union_clause;",
            ],
        )

    def test_the_clause_text_conversion_follows_the_clause_enum(self) -> None:
        self.assertIn(
            "typedef enum xy_union_clause xy_union_clause;\n"
            "/* the text of `clause`, as every binding's refusal words it; UNKNOWN_UNION_CLAUSE for XY_UNION_OK or a "
            "value no clause has */\n"
            "static inline const char* xy_union_clause_text(xy_union_clause clause) {\n"
            "\tswitch (clause) {\n"
            '\tcase XY_UNION_HEADER_PAST_EXTENT: return "header past the extent";\n'
            '\tcase XY_UNION_UNKNOWN_TAG: return "unknown tag";\n'
            '\tcase XY_UNION_SIZE_NOT_THE_MEMBERS: return "size is not the member\'s";\n'
            '\tcase XY_UNION_RECORD_PAST_EXTENT: return "record past the extent";\n'
            '\tcase XY_UNION_COUNT_NOT_MET: return "count not met";\n'
            '\tcase XY_UNION_NOT_A_RECORD_START: return "offset is not a record\'s start";\n'
            '\tdefault: return "UNKNOWN_UNION_CLAUSE";\n'
            "\t}\n}\n",
            self.text,
        )

    def test_each_tag_and_size_is_a_literal_and_each_size_the_layouts(self) -> None:
        tags = {c.name: c.value for c in self.api.consts}
        for text in (UNIONS, mutate(UNIONS, 'flag = "u32"', 'flag = "u32"\nextra = "u32"')):
            api = load(text)
            lines = header(api).splitlines()
            for m in api.unions[0].members:
                with self.subTest(member=m.name, size=api.layout(m.struct)[0]):
                    case = f"\tcase {tags[m.tag]}: return {api.layout(m.struct)[0]};"
                    self.assertTrue(any(line.startswith(case) for line in lines), case)
        self.assertIn("\tdefault: return 0;", self.lines)
        self.assertIn(
            f"\tif ((uint32_t)(bytes - at) < {self.api.layout('note_head')[0]}) return XY_UNION_HEADER_PAST_EXTENT;",
            self.lines,
        )

    def test_a_members_size_is_trailed_by_its_name_and_its_docstring_where_it_has_one(self) -> None:
        self.assertIn("\tcase 1: return 16; /* line */", self.lines)
        self.assertIn("\tcase 2: return 16; /* mark: a value and its flag */", self.lines)

    def test_a_list_is_the_prefix_pointer_its_count_and_its_extent_of_the_count_type(self) -> None:
        self.assertEqual(
            param_lists(self.text, r"XY_API xy_status ")["replay"],
            "const xy_note_head* notes, uint32_t notes_count, uint32_t notes_bytes",
        )
        self.assertIn(
            "typedef xy_flow (*xy_on_notes)(const xy_note_head* seen, uint32_t seen_count, uint32_t seen_bytes, "
            "uint32_t count, void* user_data);",
            self.lines,
        )
        u16 = header(load(mutate(UNIONS, '_count = "u32"', '_count = "u16"', every=True)))
        self.assertEqual(
            param_lists(u16, r"XY_API xy_status ")["replay"],
            "const xy_note_head* notes, uint16_t notes_count, uint16_t notes_bytes",
        )

    def test_a_u8_tag_types_the_helpers_tag_and_the_length_is_read_by_name(self) -> None:
        api = load(UNION_U8_TAG)
        self.assertEqual(emit_c.validate(api), [])
        lines = header(api).splitlines()
        for line in (
            "static inline uint32_t xy_note_member_size(uint8_t tag) {",
            "\tneed = xy_note_member_size(record->kind);",
            "\tif (record->size != need) return XY_UNION_SIZE_NOT_THE_MEMBERS;",
        ):
            with self.subTest(line=line):
                self.assertIn(line, lines)
        comment = next(line for line in lines if line.startswith("/* A list of note: "))
        self.assertIn("its kind the member's tag and its size the record's byte length, a multiple of 2", comment)

    def test_the_lists_comment_states_the_alignment_the_sizes_and_the_effective_type(self) -> None:
        comment = next(line for line in self.lines if line.startswith("/* A list of note: "))
        for fragment in (
            "a pointer aligned to 4",
            "begins with xy_note_head, its kind the member's tag and its size the record's byte length, a multiple of 4",
            "allocated storage with no declared type",
            "cast to the member's struct, after a switch on kind, has that struct as its effective type",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, comment)

    def test_the_walks_callers_duties_are_stated_above_first(self) -> None:
        self.assertIn(
            "/* xy_note_first, xy_note_next and xy_note_well_formed take `list` as a xy_note_head*, so it is aligned "
            "to 4 by its type; the caller's duties: `list` non-null wherever `bytes` > 0, and valid for `bytes` "
            "bytes; `cur` a record this list's walk returned */\n"
            "/* the first record of the list, or NULL where the list is empty or its first record is malformed */\n"
            "static inline const xy_note_head* xy_note_first(",
            self.text,
        )

    def test_a_callback_type_with_a_view_states_its_views_are_valid_for_that_call_only(self) -> None:
        self.assertIn("/* Its views are valid for that call only. */\ntypedef xy_flow (*xy_on_notes)(", self.text)
        sink = header(load(KITCHEN_SINK))
        typedef = sink.index("typedef xy_flow (*xy_on_batch)(")
        self.assertTrue(
            sink[sink.rindex("/*", 0, typedef) : typedef].endswith(" Its views are valid for that call only. */\n")
        )
        mode = sink.index("(*xy_on_mode)(")
        self.assertNotIn("valid for that call", sink[sink.rindex("\n\n", 0, mode) : mode])

    def test_the_list_follows_the_structs_and_precedes_the_callback_types_under_its_docstrings(self) -> None:
        order = [
            "typedef struct xy_note_mark xy_note_mark;",
            "enum xy_union_clause {",
            "/* what a note is */",
            "/* one note: the struct its head's kind names, head.size bytes long */",
            "/* A list of note: ",
            "static inline uint32_t xy_note_member_size(",
            "typedef xy_flow (*xy_on_notes)(",
        ]
        self.assertEqual([self.text.index(f) for f in order], sorted(self.text.index(f) for f in order))

    def test_the_header_still_includes_stdint_alone(self) -> None:
        self.assertEqual(
            [line for line in self.lines if "#include" in line or "# include" in line], ["#include <stdint.h>"]
        )

    def test_one_clause_enum_serves_every_union(self) -> None:
        twin = mutate(
            UNIONS,
            "\n[[callback]]",
            '\n[union.twin]\n_mixed_type_list = true\nline = { _tag = "kind_line", _type = "note_line" }\n\n[[callback]]',
        )
        text = header(load(twin))
        self.assertEqual(text.count("enum xy_union_clause {"), 1)
        self.assertIn(
            "static inline const xy_note_head* xy_twin_first(const xy_note_head* list, uint32_t bytes) {", text
        )

    def test_a_union_without_mixed_type_list_renders_its_structs_and_nothing_more(self) -> None:
        api = load(UNION_NOT_LISTED)
        text = header(api)
        self.assertEqual(emit_c.validate(api), [])
        self.assertIn("typedef struct xy_note_mark xy_note_mark;", text)
        for absent in ("static inline", "xy_union_clause", "XY_UNION_", "/* one note: ", "/* what a note is */"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, text)

    def test_a_c_identifier_the_list_defines_is_refused_where_the_header_defines_it_too(self) -> None:
        cases = (
            (UNIONS + '\n[function.note_next]\n_return = "status"\n', "function.note_next", "xy_note_next"),
            (
                mutate(UNIONS, "[struct.note_head]", '[struct.note_first]\nv = "u32"\n\n[struct.note_head]'),
                "struct.note_first",
                "xy_note_first",
            ),
            (
                mutate(
                    UNIONS,
                    "[callback.on_notes]",
                    '[callback.note_well_formed]\n_return = "flow"\n\n[callback.on_notes]',
                ),
                "callback.note_well_formed",
                "xy_note_well_formed",
            ),
            (
                UNIONS + '\n[[boxed_scalar]]\n[boxed_scalar.note_member_size]\n_base_type = "u32"\n',
                "boxed_scalar.note_member_size",
                "xy_note_member_size",
            ),
            (
                mutate(UNIONS, "[typed_const.flow]", "[typed_const.union_clause]\nnone = 0\n\n[typed_const.flow]"),
                "typed_const.union_clause",
                "xy_union_clause",
            ),
            (mutate(UNIONS, "kind_mark = 2", "kind_mark = 2\nunion_ok = 3"), "untyped_const.union_ok", "XY_UNION_OK"),
            (
                mutate(UNIONS, "kind_mark = 2", "kind_mark = 2\nnote_align = 3"),
                "untyped_const.note_align",
                "XY_NOTE_ALIGN",
            ),
            (
                UNIONS + '\n[function.union_clause_text]\n_return = "status"\n',
                "function.union_clause_text",
                "xy_union_clause_text",
            ),
            (
                mutate(UNIONS, "err_busy = 9", "err_busy = 9\nunion_unknown_tag = 10"),
                "typed_const.status.union_unknown_tag",
                "XY_UNION_UNKNOWN_TAG",
            ),
        )
        for text, where, ident in cases:
            with self.subTest(where=where):
                self.assertEqual(
                    emit_c.validate(load(text)),
                    [f"header: {where}: C identifier {ident} already defined by union 'note'"],
                )
        free = UNION_NOT_LISTED + '\n[function.note_next]\n_return = "status"\n'
        self.assertEqual(emit_c.validate(load(free)), [])


class ToString(unittest.TestCase):
    """A `_to_string` conversion follows its enum's typedef or its group's macros; edge_xy.c
    checks what each answers."""

    def setUp(self) -> None:
        self.api = load(KITCHEN_SINK)
        self.text = header(self.api)

    def test_an_enums_conversion_follows_its_typedef(self) -> None:
        self.assertIn(
            "typedef enum xy_mode xy_mode;\n"
            "/* the unprefixed name of `value`'s entry; UNKNOWN_MODE for a value no entry has */\n"
            "static inline const char* xy_mode_to_string(xy_mode value) {\n"
            "\tswitch (value) {\n"
            '\tcase XY_FINE: return "FINE";\n'
            '\tcase XY_SLOW: return "SLOW";\n'
            '\tdefault: return "UNKNOWN_MODE";\n'
            "\t}\n}\n",
            self.text,
        )
        self.assertNotIn("xy_flow_to_string", self.text)

    def test_a_plain_groups_conversion_names_each_value_by_its_later_entry(self) -> None:
        text = header(load(mutate(FIXTURE, "max_units = 16\n", "max_units = 16\ntop = 16\n")))
        self.assertIn(
            "#define XY_MAGIC INT32_C(0xbeef) /* wire magic */\n\n"
            "/* the unprefixed name of `value`'s entry, the later where two share it; UNKNOWN for a value no entry "
            "has */\n"
            "static inline const char* xy_limit_to_string(int32_t value) {\n"
            "\tswitch (value) {\n"
            '\tcase XY_TOP: return "TOP";\n'
            '\tcase XY_MAGIC: return "MAGIC";\n'
            '\tdefault: return "UNKNOWN";\n'
            "\t}\n}\n",
            text,
        )

    def test_a_bit_groups_conversion_takes_the_callers_buffer(self) -> None:
        self.assertIn(
            "static inline uint32_t xy_access_to_string(int32_t value, char* text, uint32_t text_count) {\n", self.text
        )
        # each single-bit entry, never the composed acc_ab
        self.assertIn("(uint32_t)XY_ACC_B) != 0", self.text)
        self.assertNotIn("XY_ACC_AB) != 0", self.text)

    def test_the_lua_declarations_carry_no_conversion(self) -> None:
        self.assertNotIn("to_string", c.binding_declarations(self.api))

    def test_a_c_identifier_a_conversion_defines_is_refused_where_the_header_defines_it_too(self) -> None:
        self.assertEqual(
            emit_c.validate(load(KITCHEN_SINK + '\n[function.status_to_string]\n_return = "status"\n')),
            [
                "header: function.status_to_string: C identifier xy_status_to_string already defined by "
                "typed_const.status._to_string"
            ],
        )


if __name__ == "__main__":
    unittest.main()
