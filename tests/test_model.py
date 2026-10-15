import json
import re
import tempfile
import unittest
from pathlib import Path

import jsonschema

from langxyne import model
from langxyne.tests.support import (
    FIXTURE,
    KITCHEN_SINK,
    MINIMAL,
    MIXED_TYPE_LIST,
    NO_WRAPPED_API,
    NOTE_REFS,
    NOTES,
    TWO_BAD_RETURNS,
    UNION_NOT_LISTED,
    UNION_REFUSALS,
    UNION_U8_TAG,
    UNIONS,
    assert_objection,
    buffer_expansion,
    load,
    mutate,
    objections,
)

# What FIXTURE's references to an item that failed report after the item's own objection:
# every function's `_return` names status, three parameters name port, one names stats and
# the pin names feat_a.
STATUS_REFS = [
    f"function.{f}._return: unknown typed_const 'status'" for f in ("open_port", "destroy_port", "send", "spend")
]
PORT_REFS = [f"function.{p}: unknown type 'port'" for p in ("open_port.pport", "destroy_port.hport", "send.hport")]
STATS_REFS = ["function.open_port.pstats: unknown type 'stats'"]
FEAT_A_REFS = ["_wrapped_api._pinned_value.feat_a: pins undefined untyped_bit_const 'feat_a'"]
I32 = "i32 (-2147483648..2147483647)"


class ModelErrors(unittest.TestCase):
    def test_function_named_like_a_type(self) -> None:
        assert_objection(
            self,
            FIXTURE + '\n[function.stats]\n_return = "status"\n',
            "function.stats: C identifier xy_stats already defined by struct.stats",
        )

    def test_struct_named_like_an_opaque_tag(self) -> None:
        assert_objection(
            self,
            FIXTURE + '\n[struct.port_opaque]\nx = "u32"\n',
            "struct.port_opaque: C identifier xy_port_opaque already defined by opaque_ref.port",
        )

    def test_unknown_top_level_table(self) -> None:
        assert_objection(
            self, mutate(FIXTURE, "[opaque_ref.token]", "[opque_ref.token]"), "unknown table(s) [opque_ref]"
        )

    def test_entry_attributes_begin_with_underscore(self) -> None:
        for needle, plain, where, then in (
            ('_value = 9, _docstring = "try later"', "value", "typed_const.status.err_busy", STATUS_REFS),
            ('_type = "u32", _docstring = "items seen"', "type", "struct.stats.count", STATS_REFS),
            ('_type = "stats", _ref = "out", _optional', "type", "function.open_port.pstats", []),
            ('_value = "acme"', "value", "string_const.vendor", []),
        ):
            with self.subTest(where=where):
                text = mutate(FIXTURE, needle, needle.replace(f"_{plain} = ", f"{plain} = ", 1))
                self.assertEqual(objections(text), [f"{where}: '{plain}': entry attributes begin with _", *then])

    def test_unknown_underscore_attribute_names_key_and_context(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, "_value = 3,", '_value = 3, _colour = "red",')),
            ["untyped_bit_const.feat_b: unknown key(s) _colour", *FEAT_A_REFS],
        )
        assert_objection(
            self,
            mutate(FIXTURE, '_ref = "in", ', '_ref = "in", _size = "len", '),
            "function.send.buf: unknown key(s) _size",
        )
        self.assertEqual(
            objections(mutate(FIXTURE, 'bytes = "u64"', 'bytes = { _type = "u64", _max = 1000 }')),
            ["struct.stats.bytes: unknown key(s) _max", *STATS_REFS],
        )
        self.assertEqual(
            objections(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_colour = "red"')),
            ["opaque_ref.port: unknown key(s) _colour", *PORT_REFS],
        )
        assert_objection(
            self, mutate(FIXTURE, "[_general]\n", '[_general]\n_colour = "red"\n'), "_general: unknown key(s) _colour"
        )
        assert_objection(
            self,
            mutate(FIXTURE, "[_wrapped_api]\n", '[_wrapped_api]\n_colour = "red"\n'),
            "_wrapped_api: unknown key(s) _colour",
        )

    def test_opaque_ref_has_only_properties(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, '_ctor = "open_port"', 'ctor = "open_port"')),
            ["opaque_ref.port: 'ctor': an opaque_ref has no members; its properties begin with _", *PORT_REFS],
        )

    def test_naked_values_are_sugar_and_nested_tables_equal_inline_ones(self) -> None:
        api = load()
        for needle, spelled_out in (
            ("ok = 0", "ok = { _value = 0 }"),
            ("feat_a = 0", "feat_a = { _value = 0 }"),
            ('product = "xy widget"', 'product = { _value = "xy widget" }'),
            ('bytes = "u64"', 'bytes = { _type = "u64" }'),
            ('unit = "u32"', 'unit = { _type = "u32" }'),
            ('hport = "port"\nbuf', 'hport = { _type = "port" }\nbuf'),
            (
                'err_other = { _value = 0x7fffffff, _format = "hex" }',
                '[typed_const.status.err_other]\n_value = 0x7fffffff\n_format = "hex"',
            ),
            (
                '[opaque_ref.port]\n_ctor = "open_port"\n_dtor = "destroy_port"',
                'port = { _ctor = "open_port", _dtor = "destroy_port" }',
            ),
        ):
            with self.subTest(needle=needle):
                self.assertEqual(load(mutate(FIXTURE, needle, spelled_out)), api)
        self.assertEqual(
            load(
                mutate(
                    KITCHEN_SINK,
                    '[boxed_scalar.offset]\n_docstring = "a device offset"\n_base_type = "u64"',
                    'offset = { _docstring = "a device offset", _base_type = "u64" }',
                )
            ),
            load(KITCHEN_SINK),
        )

    def test_ref_values(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, '_ref = "in"', '_ref = "both"'),
            "function.send.buf._ref must be one of in, out, inout",
        )
        self.assertEqual([p.ref for p in load().functions[0].params], [None, "out", "out", "out"])

    def test_optional_is_a_boolean(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, "_optional = true", '_optional = "yes"'),
            "function.open_port.pstats._optional must be true or false",
        )
        self.assertTrue(load().functions[0].params[2].optional)

    def test_optional_needs_a_nullable_parameter(self) -> None:
        for text, message in (
            (
                mutate(FIXTURE, 'unit = "u32"', 'unit = { _type = "u32", _optional = true }'),
                "function.open_port.unit._optional: a by-value parameter has no null to pass",
            ),
            (
                mutate(
                    KITCHEN_SINK,
                    'hport = "port"\npdst = { _type = "memory", _ref = "out",',
                    'hport = "port"\npdst = { _type = "memory", _ref = "out", _optional = true,',
                ),
                'function.recv.pdst._optional: a buffer is optional only with _ref = "in"',
            ),
            (
                mutate(
                    KITCHEN_SINK,
                    'data = { _type = "memory", _ref = "inout",',
                    'data = { _type = "memory", _ref = "inout", _optional = true,',
                ),
                'function.bump.data._optional: a buffer is optional only with _ref = "in"',
            ),
        ):
            with self.subTest(message=message):
                assert_objection(self, text, message)
        memory_in = load(
            mutate(FIXTURE, '_ref = "in", _count = "u64"', '_ref = "in", _optional = true, _count = "u64"')
        )
        self.assertTrue(next(f for f in memory_in.functions if f.name == "send").params[1].optional)

    def test_return_enum_needs_zero(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, "ok = 0", "ok = 1")),
            [
                f"function.{f}._return: typed_const 'status' has no zero-valued entry for success"
                for f in ("open_port", "destroy_port", "send", "spend")
            ],
        )

    def test_header_refuses_a_quote_a_backslash_or_a_control_character(self) -> None:
        for replacement in ('_headers = ["driver\\\\', '_headers = ["driver\\"', '_headers = ["driver\\r/'):
            with self.subTest(replacement=replacement):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_headers = ["driver/', replacement),
                    "_wrapped_api._headers[0] must not contain '\"', '\\' or a control character",
                )

    def test_library_is_a_name(self) -> None:
        for name in ("xy", "x-y_2", "_xy", "2xy", "Libxy"):
            with self.subTest(name=name):
                self.assertEqual(
                    load(mutate(FIXTURE, '_bound_library = "xy"', f'_bound_library = "{name}"')).library.name, name
                )

    def test_library_as_a_platform_file_name_is_refused_naming_its_name(self) -> None:
        for file_name in ("libxy.so", "libxy.dylib", "xy.dll", "libxy.dll", "libxy.a"):
            with self.subTest(file_name=file_name):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_bound_library = "xy"', f'_bound_library = "{file_name}"'),
                    f"_general._bound_library: '{file_name}' is a file name; name the library 'xy'",
                )

    def test_library_beginning_with_lib_is_refused_naming_the_rest(self) -> None:
        refusal = "begins with 'lib', which LuaJIT's loader does not add again and a linker does"
        for name, objection in (
            ("libxy", f"'libxy' {refusal}; name the library 'xy'"),
            ("lib", f"'lib' {refusal}"),
            ("liblibxy", f"'liblibxy' {refusal}"),
        ):
            with self.subTest(name=name):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_bound_library = "xy"', f'_bound_library = "{name}"'),
                    f"_general._bound_library: {objection}",
                )

    def test_library_that_is_not_a_name_is_refused(self) -> None:
        # (as TOML writes it, as the objection quotes it)
        for written, quoted in (
            ('"x.y"', "'x.y'"),
            ('"lib/xy"', "'lib/xy'"),
            ('"x y"', "'x y'"),
            ('"-xy"', "'-xy'"),
            ('""', "''"),
            ('"x\\"y"', "'x\"y'"),
            ('"xy\\n"', "'xy\\n'"),
            ('"é"', "'é'"),
            ('"liblibxy.so"', "'liblibxy.so'"),
        ):
            with self.subTest(written=written):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_bound_library = "xy"', f"_bound_library = {written}"),
                    f"_general._bound_library: {quoted} is not a library name: ASCII letters, digits, '_' and '-', not "
                    "beginning with '-'",
                )

    def test_bit_index_fits_the_base_type(self) -> None:
        for base_type, top in (("i32", 30), ("u32", 31)):
            text = mutate(FIXTURE, "[[untyped_bit_const]]\n", f'[[untyped_bit_const]]\n_base_type = "{base_type}"\n')
            for index in (top + 1, -1):
                with self.subTest(base_type=base_type, index=index):
                    self.assertEqual(
                        objections(mutate(text, "_value = 3,", f"_value = {index},")),
                        [
                            f"untyped_bit_const.feat_b: bit index {index} is outside 0..{top} for _base_type {base_type}",
                            *FEAT_A_REFS,
                        ],
                    )
            value = next(
                c for c in load(mutate(text, "_value = 3,", f"_value = {top},")).bit_consts if c.name == "feat_b"
            )
            self.assertEqual(value.value, 1 << top)

    def test_version_bytes_are_0_to_255(self) -> None:
        self.assertEqual(load(mutate(FIXTURE, "[1, 2, 3, 4]", "[255, 255, 255, 255]")).version_value(), 0xFFFFFFFF)
        for version in ("[256, 2, 3, 4]", "[1, 2, 3, -1]"):
            with self.subTest(version=version):
                assert_objection(
                    self,
                    mutate(FIXTURE, "[1, 2, 3, 4]", version),
                    "_general._version must be a list of 4 integers in 0..255",
                )

    def test_docstring_terminators_rejected(self) -> None:
        for terminator in ("*/", "]]"):
            with self.subTest(terminator=terminator):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_docstring = "wire magic"', f'_docstring = "wire {terminator} magic"'),
                    "untyped_const.magic._docstring must not contain '*/' or ']]'",
                )

    def test_docstring_line_break_rejected(self) -> None:
        for escape in ("\\n", "\\r"):
            with self.subTest(escape=escape):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_docstring = "wire magic"', f'_docstring = "wire{escape}magic"'),
                    "untyped_const.magic._docstring must not contain a line break",
                )
        assert_objection(
            self,
            mutate(FIXTURE, '_docstring = "release the port"', '_docstring = """release\nthe port"""'),
            "function.destroy_port._docstring must not contain a line break",
        )

    def test_namespace_is_an_identifier(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, '_namespace = "xy"', '_namespace = "x-y"'),
            "_general._namespace: 'x-y' is not an identifier",
        )
        assert_objection(
            self,
            mutate(FIXTURE, '_namespace = "xy"', "_namespace = 5"),
            "_general._namespace must be an identifier string",
        )

    def test_struct_rules(self) -> None:
        for text, message in (
            (
                FIXTURE + '\n[struct.early]\nx = "late"\n\n[struct.late]\ny = "u32"\n',
                "struct.early.x: struct 'late' must be defined before it is used",
            ),
            (FIXTURE + '\n[struct.empty]\n_docstring = "nothing"\n', "struct.empty: has no fields"),
        ):
            with self.subTest(message=message):
                assert_objection(self, text, message)
        self.assertEqual(
            objections(mutate(FIXTURE, 'bytes = "u64"', 'bytes = "memory"')),
            ["struct.stats.bytes: 'memory' is not a field type", *STATS_REFS],
        )

    def test_typed_const_has_entries(self) -> None:
        assert_objection(
            self, FIXTURE + '\n[typed_const.none]\n_docstring = "nothing"\n', "typed_const.none: has no entries"
        )

    def test_typed_const_entries_have_distinct_values(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, "err_other = { _value = 0x7fffffff", "err_other = { _value = 9")),
            ["typed_const.status.err_other: value 9 already given to typed_const.status.err_busy", *STATUS_REFS],
        )

    def test_wrapped_api_rules(self) -> None:
        for needle, replacement, message in (
            ('_headers = ["driver/xy_ioctl.h"]\n', "", "_wrapped_api._headers must be a non-empty list of strings"),
            (
                'feat_a = "XYD_FEAT_A"',
                'feat_a = "XYD-FEAT-A"',
                "_wrapped_api._pinned_value.feat_a: must be a macro name",
            ),
            ("[_wrapped_api]", "[_driver_data]", "unknown table(s) [_driver_data]"),
            (
                'feat_a = "XYD_FEAT_A"',
                '[_wrapped_api.const_pins]\nfeat_a = "XYD_FEAT_A"',
                "_wrapped_api: unknown key(s) const_pins",
            ),
            (
                '[_wrapped_api._pinned_value]\nfeat_a = "XYD_FEAT_A"',
                '_pinned_value = "x"',
                "_wrapped_api._pinned_value must be a table",
            ),
            ("[_wrapped_api._pinned_value]\n", "", "_wrapped_api: unknown key(s) feat_a"),
            ('feat_a = "XYD_FEAT_A"', '_x = 1\nfeat_a = "XYD_FEAT_A"', "_wrapped_api._pinned_value: unknown key(s) _x"),
            (
                '_headers = ["driver/xy_ioctl.h"]',
                '_header = "driver/xy_ioctl.h"',
                "_wrapped_api: unknown key(s) _header",
            ),
            (
                '_headers = ["driver/xy_ioctl.h"]',
                '_headers = "driver/xy_ioctl.h"',
                "_wrapped_api._headers must be a non-empty list of strings",
            ),
            (
                '_headers = ["driver/xy_ioctl.h"]',
                "_headers = []",
                "_wrapped_api._headers must be a non-empty list of strings",
            ),
            (
                '_headers = ["driver/xy_ioctl.h"]',
                '_headers = ["driver/xy_ioctl.h", 5]',
                "_wrapped_api._headers must be a non-empty list of strings",
            ),
            (
                '_headers = ["driver/xy_ioctl.h"]',
                '_headers = ["driver/xy_ioctl.h", "driver/xy_ioctl.h"]',
                "_wrapped_api._headers[1]: already listed",
            ),
        ):
            with self.subTest(message=message):
                assert_objection(self, mutate(FIXTURE, needle, replacement), message)

    def test_wrapped_api_without_pins_keeps_its_header(self) -> None:
        wrapped = load(mutate(FIXTURE, 'feat_a = "XYD_FEAT_A"\n', "")).wrapped_api
        self.assertEqual((wrapped.headers, wrapped.pins), (("driver/xy_ioctl.h",), ()))
        self.assertIsNone(load(NO_WRAPPED_API).wrapped_api)

    def test_header_is_relative_to_the_project_directory(self) -> None:
        message = (
            "_wrapped_api._headers[0] must be relative to the project directory, not absolute or beginning with '../'"
        )
        for header in ("/work/exercises/xy/driver/xy_ioctl.h", "../xy/driver/xy_ioctl.h"):
            with self.subTest(header=header):
                assert_objection(self, mutate(FIXTURE, '"driver/xy_ioctl.h"', f'"{header}"'), message)
        assert_objection(
            self,
            mutate(FIXTURE, '"driver/xy_ioctl.h"', '"driver/xy_ioctl.h", "../a.h"'),
            message.replace("_headers[0]", "_headers[1]"),
        )
        self.assertEqual(load(mutate(FIXTURE, '"driver/', '"./driver/')).wrapped_api.headers, ("./driver/xy_ioctl.h",))

    def test_typed_const_fits_its_base_type(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, "ok = 0", "ok = 0x80000000")),
            [f"typed_const.status.ok: 2147483648 does not fit {I32}", *STATUS_REFS],
        )
        u32 = mutate(FIXTURE, '_docstring = "call outcome"', '_base_type = "u32"')
        self.assertEqual(
            objections(mutate(u32, "err_busy = { _value = 9", "err_busy = { _value = -9")),
            ["typed_const.status.err_busy: -9 does not fit u32 (0..4294967295)", *STATUS_REFS],
        )
        # above the i32 maximum is the header's objection, not the loader's
        entries = load(mutate(u32, "0x7fffffff", "0xffffffff")).typed_consts[0].entries
        self.assertEqual(next(e for e in entries if e.name == "err_other").value, 2**32 - 1)

    def test_untyped_value_fits_its_group_base_type(self) -> None:
        for base_type, low, high in (("i32", -(2**31), 2**31 - 1), ("u32", 0, 2**32 - 1)):
            text = mutate(FIXTURE, "[[untyped_const]]\n", f'[[untyped_const]]\n_base_type = "{base_type}"\n')
            for bad in (low - 1, high + 1):
                with self.subTest(base_type=base_type, value=bad):
                    assert_objection(
                        self,
                        mutate(text, "max_units = 16", f"max_units = {bad}"),
                        f"untyped_const.max_units: {bad} does not fit {base_type} ({low}..{high})",
                    )
            for good in (low, high):
                with self.subTest(base_type=base_type, value=good):
                    self.assertEqual(load(mutate(text, "max_units = 16", f"max_units = {good}")).consts[0].value, good)

    def test_sum_and_its_literal_terms_fit_the_base_type(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x7fffffff", "max_units"]'),
            f"untyped_const.big: 2147483663 does not fit {I32}",
        )
        assert_objection(
            self,
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x80000000", "-1"]'),
            f"untyped_const.big: term 0x80000000: 2147483648 does not fit {I32}",
        )
        self.assertEqual(
            objections(mutate(FIXTURE, '["feat_a", "feat_b"]', '["feat_a", "0x80000000"]')),
            [f"untyped_bit_const.feat_ab: term 0x80000000: 2147483648 does not fit {I32}", *FEAT_A_REFS],
        )

    def test_sum_running_total_fits_the_base_type_term_by_term(self) -> None:
        # the final value fits; the total after the second term does not
        assert_objection(
            self,
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x7fffffff", "max_units", "-16"]'),
            f"untyped_const.big: the running sum after term max_units: 2147483663 does not fit {I32}",
        )
        assert_objection(
            self,
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nlow = ["-0x80000000", "-1", "1"]'),
            f"untyped_const.low: the running sum after term -1: -2147483649 does not fit {I32}",
        )
        # the same terms in an order whose every running total fits
        text = mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbig = ["0x7fffffff", "-16", "max_units"]')
        self.assertEqual(next(c for c in load(text).consts if c.name == "big").value, 2**31 - 1)

    def test_sum_terms_share_its_base_type(self) -> None:
        u32_bits = '\n[[untyped_bit_const]]\n_base_type = "u32"\nfeat_c = 0\n'
        assert_objection(
            self,
            mutate(FIXTURE, "\n[[untyped_const]]", u32_bits + 'feat_x = ["feat_c", "feat_b"]\n\n[[untyped_const]]'),
            "untyped_bit_const.feat_x (u32) composes untyped_bit_const.feat_b (i32): a sum's terms share its _base_type",
        )
        u32_plain = '\n[[untyped_const]]\n_base_type = "u32"\nwire = ["max_units"]\n'
        assert_objection(
            self,
            mutate(FIXTURE, "\n[[string_const]]", u32_plain + "\n[[string_const]]"),
            "untyped_const.wire (u32) composes untyped_const.max_units (i32): a sum's terms share its _base_type",
        )

    def test_sum_may_name_an_earlier_group_of_the_same_base_type(self) -> None:
        text = mutate(
            FIXTURE, "\n[[untyped_const]]", '\n[[untyped_bit_const]]\nfeat_x = ["feat_b", "1"]\n\n[[untyped_const]]'
        )
        text = mutate(text, "\n[[string_const]]", '\n[[untyped_const]]\ntotal = ["max_units", "4"]\n\n[[string_const]]')
        api = load(text)
        self.assertEqual(next(c for c in api.bit_consts if c.name == "feat_x").value, 9)
        self.assertEqual(next(c for c in api.consts if c.name == "total").value, 20)

    def test_builtin_shadow(self) -> None:
        assert_objection(self, FIXTURE + '\n[struct.u32]\nx = "u64"\n', "struct.u32: shadows builtin type u32")

    def test_constant_uniqueness(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, "feat_a = 0\n", "feat_a = 0\napi_version = 5\n"),
            "untyped_bit_const.api_version: C identifier XY_API_VERSION already defined by the API version constant",
        )
        assert_objection(
            self,
            mutate(FIXTURE, "ok = 0\n", "ok = 0\nfeat_a = 4\n"),
            "typed_const.status.feat_a: C identifier XY_FEAT_A already defined by untyped_bit_const.feat_a",
        )

    def test_string_const_rejects_control_characters(self) -> None:
        for escape in ("\\n", "\\r", "\\t", "\\u0000", "\\u001b", "\\u007f"):
            with self.subTest(escape=escape):
                assert_objection(
                    self,
                    mutate(FIXTURE, 'product = "xy widget"', f'product = "xy{escape}widget"'),
                    "string_const.product: value must not contain '\"', '\\' or a control character",
                )

    def test_ctor_cannot_cache_an_out_buffer(self) -> None:
        for element in ("memory", "u32"):
            with self.subTest(element=element):
                assert_objection(
                    self,
                    mutate(
                        FIXTURE,
                        'generation = { _type = "u32", _ref = "out" }',
                        'generation = { _type = "u32", _ref = "out" }\n'
                        f'blob = {{ _type = "{element}", _ref = "out", _count = "u32" }}',
                    ),
                    "opaque_ref.port._ctor: function.open_port.blob: a constructor cannot cache an out buffer",
                )

    def test_ctor_has_no_inout_parameter(self) -> None:
        assert_objection(
            self,
            mutate(
                FIXTURE,
                'generation = { _type = "u32", _ref = "out" }',
                'generation = { _type = "u32", _ref = "inout" }',
            ),
            "opaque_ref.port._ctor: function.open_port.generation: a constructor has no inout parameter",
        )

    def test_underscore_keys_are_properties_not_members(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, "bytes = ", "_bytes = ")), ["struct.stats: unknown key(s) _bytes", *STATS_REFS]
        )
        assert_objection(
            self, mutate(FIXTURE, "max_units = ", "_max_units = "), "untyped_const[0]: unknown key(s) _max_units"
        )
        assert_objection(self, mutate(FIXTURE, "unit = ", "_unit = "), "function.open_port: unknown key(s) _unit")
        self.assertEqual(
            objections(mutate(FIXTURE, "ok = 0", "_ok = 0")), ["typed_const.status: unknown key(s) _ok", *STATUS_REFS]
        )
        assert_objection(
            self, mutate(FIXTURE, 'product = "xy', '_product = "xy'), "string_const[0]: unknown key(s) _product"
        )
        assert_objection(
            self,
            mutate(FIXTURE, '_return = "status"\nunit', "unit"),
            "function.open_port: missing '_return' naming a typed_const",
        )

    def test_docstring_is_a_member_name(self) -> None:
        load(mutate(FIXTURE, "bytes = ", "docstring = "))

    def test_undecodable_definition_is_a_definition_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xy_api.adef.toml"
            path.write_bytes(b'[_general]\n_namespace = "\xff"\n')  # deliberately not UTF-8
            with self.assertRaises(model.DefinitionError):
                model.load(path)

    def test_single_table_constants_are_rejected(self) -> None:
        for key in ("untyped_const", "untyped_bit_const", "string_const"):
            with self.subTest(key=key):
                assert_objection(
                    self,
                    mutate(NO_WRAPPED_API, f"[[{key}]]", f"[{key}]"),
                    f"[{key}] must be an array of tables, [[{key}]]",
                )

    def test_string_group_has_no_base_type(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, "[[string_const]]", '[[string_const]]\n_base_type = "u32"'),
            "string_const[0]: unknown key(s) _base_type",
        )

    def test_empty_group_is_rejected(self) -> None:
        text = mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_docstring = "none"\n\n[[untyped_const]]\n')
        assert_objection(self, text, "untyped_const[0]: has no entries")

    def test_base_type(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_base_type = "u64"\n'),
            "untyped_const[0]._base_type must be one of i32, u32",
        )
        self.assertEqual(
            objections(mutate(FIXTURE, '_docstring = "call outcome"', '_base_type = "int"')),
            ["typed_const.status._base_type must be one of i32, u32", *STATUS_REFS],
        )

        u32 = '[[untyped_const]]\n_base_type = "u32"\n'
        self.assertEqual(load(mutate(FIXTURE, "[[untyped_const]]\n", u32)).const_groups[0].base_type, "u32")

    def test_float_constants_are_not_implemented(self) -> None:
        for text, message in (
            (
                mutate(FIXTURE, "max_units = 16", "max_units = 1.5"),
                "untyped_const.max_units: f64 constants are not implemented",
            ),
            (
                mutate(FIXTURE, "[[untyped_const]]\n", '[[untyped_const]]\n_base_type = "f32"\n'),
                "untyped_const[0]._base_type: f32 constants are not implemented",
            ),
        ):
            with self.subTest(message=message), self.assertRaises(model.NotImplementedDefinition) as caught:
                load(text)
            self.assertEqual(str(caught.exception), message)

    def test_float_bit_flags_and_enums_are_errors(self) -> None:
        for needle, replacement in (
            ("[[untyped_bit_const]]\n", '[[untyped_bit_const]]\n_base_type = "f64"\n'),
            ('_docstring = "call outcome"', '_base_type = "f64"'),
        ):
            with self.subTest(replacement=replacement):
                with self.assertRaises(model.DefinitionError) as caught:
                    load(mutate(FIXTURE, needle, replacement))
                self.assertNotIsInstance(caught.exception, model.NotImplementedDefinition)
                self.assertIn("_base_type must be one of i32, u32", str(caught.exception))

    def test_unknown_type(self) -> None:
        assert_objection(
            self, mutate(FIXTURE, 'unit = "u32"', 'unit = "u128"'), "function.open_port.unit: unknown type 'u128'"
        )

    def test_unknown_return_type(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, '_docstring = "release the port"\n_return = "status"', '_return = "nope"'),
            "function.destroy_port._return: unknown typed_const 'nope'",
        )

    def test_duplicate_type_name_across_categories(self) -> None:
        assert_objection(
            self, FIXTURE + "\n[opaque_ref.stats]\n", "struct.stats: type name already defined in opaque_ref"
        )

    def test_pin_names_undefined_constant(self) -> None:
        assert_objection(
            self,
            FIXTURE + 'feat_z = "XY_FEAT_Z"\n',
            "_wrapped_api._pinned_value.feat_z: pins undefined untyped_bit_const 'feat_z'",
        )

    def test_composed_constant_must_be_earlier(self) -> None:
        text = mutate(NO_WRAPPED_API, '["feat_a", "feat_b"]', '["feat_a", "feat_c"]')
        assert_objection(
            self,
            text,
            "untyped_bit_const.feat_ab: composes unknown constant 'feat_c' (only earlier untyped_bit_const entries or literals)",
        )

    def test_bit_sum_refuses_overlapping_terms(self) -> None:
        assert_objection(
            self,
            mutate(NO_WRAPPED_API, '["feat_a", "feat_b"]', '["feat_a", "1"]'),
            "untyped_bit_const.feat_ab: feat_a and 1 share bits",
        )

    def test_composed_term_must_be_a_literal_or_known_entry(self) -> None:
        assert_objection(
            self,
            mutate(NO_WRAPPED_API, '["feat_a", "feat_b"]', '["feat_a", "bogus"]'),
            "untyped_bit_const.feat_ab: composes unknown constant 'bogus' (only earlier untyped_bit_const entries or literals)",
        )
        assert_objection(
            self,
            mutate(FIXTURE, "max_units = 16", 'max_units = 16\nbad = ["bogus"]'),
            "untyped_const.bad: composes unknown constant 'bogus' (only earlier untyped_const entries or literals)",
        )

    def test_literal_term_is_decimal_or_0x_hex_with_an_optional_minus(self) -> None:
        for term, value, fmt in (
            ("4", 4, "dec"),
            ("-4", -4, "dec"),
            ("0x1f", 31, "hex"),
            ("0x1F", 31, "hex"),
            ("-0x3", -3, "hex"),
            ("0", 0, "dec"),
        ):
            with self.subTest(term=term):
                api = load(mutate(FIXTURE, "max_units = 16", f'max_units = 16\ntotal = ["max_units", "{term}"]'))
                total = next(c for c in api.consts if c.name == "total")
                self.assertEqual(total.parts, ("max_units", model.LiteralTerm(value, fmt)))
                self.assertEqual(total.value, 16 + value)
        for term in ("0o17", "0b11", "1_000", "+5", " 5", "5 ", "0X1F", "0x", "-", "--1", "1e3"):
            with self.subTest(term=term):
                assert_objection(
                    self,
                    mutate(FIXTURE, "max_units = 16", f'max_units = 16\ntotal = ["max_units", "{term}"]'),
                    f"untyped_const.total: term '{term}' is neither an entry name nor a literal (decimal or 0x-prefixed, "
                    "an optional leading '-')",
                )

    def test_composed_entry_dict_form_equals_naked_list(self) -> None:
        api = load(KITCHEN_SINK)
        naked = mutate(KITCHEN_SINK, 'feat_lit = { _value = ["feat_a", "4"] }', 'feat_lit = ["feat_a", "4"]')
        self.assertEqual(load(naked), api)

    def test_memory_needs_a_ref(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_ref = "in", ', ""), "function.send.buf: a buffer needs _ref")

    def test_memory_count(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, '_count = "u64", ', ""),
            "function.send.buf: a 'memory' parameter requires _count, one of u8, u16, u32, u64",
        )
        for count in ("port", "i64", "f64"):
            with self.subTest(count=count):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_count = "u64"', f'_count = "{count}"'),
                    "function.send.buf: a 'memory' parameter requires _count, one of u8, u16, u32, u64",
                )
        assert_objection(
            self,
            mutate(FIXTURE, 'unit = "u32"', 'unit = { _type = "u32", _count = "u32" }'),
            "function.open_port.unit: a buffer needs _ref",
        )
        for count in ("port", "i64", "f64"):
            with self.subTest(array_count=count):
                assert_objection(
                    self,
                    mutate(FIXTURE, 'unit = "u32"', f'unit = {{ _type = "u32", _ref = "out", _count = "{count}" }}'),
                    "function.open_port.unit._count must be one of u8, u16, u32, u64",
                )
        assert_objection(
            self,
            mutate(FIXTURE, 'hport = "port"\nbuf', 'buf_count = "u32"\nbuf'),
            "function.send.buf: its count parameter buf_count is already a parameter",
        )
        self.assertEqual(load().functions[2].params[1].count_type, "u64")

    def test_missing_general(self) -> None:
        assert_objection(self, "[function]\n", "missing [_general] table")

    def test_unknown_format(self) -> None:
        self.assertEqual(
            objections(mutate(FIXTURE, '_format = "hex" }\n\n[[opaque', '_format = "oct" }\n\n[[opaque')),
            ["typed_const.status.err_other._format must be one of dec, hex", *STATUS_REFS],
        )

    def test_ctor_needs_one_out_of_the_opaque(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, '_ctor = "open_port"', '_ctor = "send"'),
            "opaque_ref.port._ctor: 'send' must name a function with exactly one port parameter of _ref \"out\"",
        )

    def test_ctor_and_dtor_are_function_names(self) -> None:
        for key in ("_ctor", "_dtor"):
            with self.subTest(key=key):
                self.assertEqual(
                    objections(mutate(FIXTURE, f'{key} = "', f'{key} = 5 # "')),
                    [f"opaque_ref.port.{key} must be a function name", *PORT_REFS],
                )

    def test_dtor_takes_only_the_opaque(self) -> None:
        for dtor in ("send", "nope"):
            with self.subTest(dtor=dtor):
                assert_objection(
                    self,
                    mutate(FIXTURE, '_dtor = "destroy_port"', f'_dtor = "{dtor}"'),
                    f"opaque_ref.port._dtor: '{dtor}' must name a function whose only parameter is a port by value",
                )

    def test_dtor_requires_ctor(self) -> None:
        assert_objection(self, mutate(FIXTURE, '_ctor = "open_port"\n', ""), "opaque_ref.port._dtor: requires _ctor")

    def test_hides_pointer_is_an_opaque_ref_boolean_defaulting_false(self) -> None:
        def port(value: str) -> str:
            return mutate(FIXTURE, '_dtor = "destroy_port"', f'_dtor = "destroy_port"\n_hides_pointer = {value}')

        for value, expected in (("true", True), ("false", False)):
            self.assertIs(load(port(value)).opaque_refs[0].hides_pointer, expected)
        self.assertIs(load().opaque_refs[0].hides_pointer, False)
        self.assertEqual(
            objections(port('"yes"')),
            ["opaque_ref.port._hides_pointer must be true or false", *PORT_REFS],
        )
        self.assertEqual(
            objections(mutate(FIXTURE, "[struct.stats]\n", "[struct.stats]\n_hides_pointer = true\n")),
            ["struct.stats: unknown key(s) _hides_pointer", *STATS_REFS],
        )

    def test_string_const_rejects_a_quote(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, 'product = "xy widget"', "product = 'xy \"widget\"'"),
            "string_const.product: value must not contain '\"', '\\' or a control character",
        )

    def test_plain_and_string_constants_share_the_constant_namespace(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, "max_units = 16", "ok = 16"),
            "typed_const.status.ok: C identifier XY_OK already defined by untyped_const.ok",
        )
        assert_objection(
            self,
            mutate(FIXTURE, 'product = "xy widget"', 'max_units = "x"'),
            "string_const.max_units: C identifier XY_MAX_UNITS already defined by untyped_const.max_units",
        )

    def test_to_string_is_a_name(self) -> None:
        for needle, value, message, then in (
            (
                '_to_string = "to_string"',
                '"_x"',
                "typed_const.status._to_string: '_x': a key beginning with '_' is a property, not a name",
                STATUS_REFS,
            ),
            ('_to_string = "to_string"', "5", "typed_const.status._to_string must be an identifier", STATUS_REFS),
            (
                '_to_string = "feat_to_string"',
                '"9x"',
                "untyped_bit_const[0]._to_string: '9x' is not an identifier",
                FEAT_A_REFS,
            ),
            ('_to_string = "limit_to_string"', '"a-b"', "untyped_const[0]._to_string: 'a-b' is not an identifier", []),
        ):
            with self.subTest(message=message):
                self.assertEqual(objections(mutate(FIXTURE, needle, f"_to_string = {value}")), [message, *then])

    def test_string_group_has_no_to_string(self) -> None:
        assert_objection(
            self,
            mutate(FIXTURE, "[[string_const]]\n", '[[string_const]]\n_to_string = "product_to_string"\n'),
            "string_const[0]: unknown key(s) _to_string",
        )

    def test_class_must_be_an_identifier(self) -> None:
        assert_objection(
            self,
            FIXTURE + '\n[opaque_ref.spare]\n_class = "a-b"\n',
            "opaque_ref.spare._class: 'a-b' is not an identifier",
        )
        assert_objection(
            self, FIXTURE + "\n[opaque_ref.spare]\n_class = 5\n", "opaque_ref.spare._class must be an identifier"
        )

    def test_class_is_lowercase(self) -> None:
        assert_objection(
            self,
            FIXTURE + '\n[opaque_ref.spare]\n_class = "DataLink"\n',
            "opaque_ref.spare._class: 'DataLink' must be lowercase; each binding applies its own casing",
        )
        self.assertEqual(
            load(mutate(FIXTURE, '_dtor = "destroy_port"', '_dtor = "destroy_port"\n_class = "link_2"'))
            .opaque_refs[0]
            .class_name,
            "link_2",
        )


class CollectedErrors(unittest.TestCase):
    def test_independent_errors_in_different_items_all_report_in_document_order(self) -> None:
        self.assertEqual(
            objections(TWO_BAD_RETURNS),
            [
                "function.destroy_port._return: unknown typed_const 'nope'",
                "function.spend._return: unknown typed_const 'gone'",
            ],
        )

    def test_errors_in_one_function_all_report_in_document_order(self) -> None:
        text = mutate(
            mutate(FIXTURE, 'unit = "u32"', 'unit = "u128"'),
            'generation = { _type = "u32", _ref = "out" }',
            'generation = { _type = "u32", _ref = "both" }',
        )
        self.assertEqual(
            objections(text),
            [
                "function.open_port.unit: unknown type 'u128'",
                "function.open_port.generation._ref must be one of in, out, inout",
            ],
        )

    def test_order_is_the_documents_not_the_loaders(self) -> None:
        # the loader reads typed_const before struct; the document writes struct first
        text = MINIMAL + '\n[[struct]]\n[struct.s]\nx = "nope"\n\n[[typed_const]]\n[typed_const.e]\nok = "zero"\n'
        self.assertEqual(
            objections(text),
            [
                "struct.s.x: unknown type 'nope'",
                "typed_const.e.ok: value must be an integer",
            ],
        )

    def test_a_failure_leaving_nothing_to_parse_stops_alone(self) -> None:
        for text, message in (
            (mutate(TWO_BAD_RETURNS, "[opaque_ref.token]", "[opque_ref.token]"), "unknown table(s) [opque_ref]"),
            (
                mutate(TWO_BAD_RETURNS, '_namespace = "xy"', '_namespace = "x-y"'),
                "_general._namespace: 'x-y' is not an identifier",
            ),
        ):
            with self.subTest(message=message):
                self.assertEqual(objections(text), [message])


BOXED = FIXTURE + '\n[[boxed_scalar]]\n[boxed_scalar.offset]\n_base_type = "u64"\n'


class BoxedScalar(unittest.TestCase):
    def test_usable_with_any_ref_optional_as_a_scalar_and_as_a_struct_field(self) -> None:
        text = BOXED + (
            '\n[struct.span]\nat = "offset"\n'
            '\n[function.move]\n_return = "status"\nsrc = { _type = "offset", _ref = "in", _optional = true }\n'
            'dst = { _type = "offset", _ref = "inout" }\n'
        )
        api = load(text)
        self.assertEqual(next(s for s in api.structs if s.name == "span").fields[0].type, "offset")
        move = next(f for f in api.functions if f.name == "move")
        self.assertEqual([(p.ref, p.optional) for p in move.params], [("in", True), ("inout", False)])

    def test_base_type_is_any_integer_builtin_and_required(self) -> None:
        for base_type in ("i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"):
            with self.subTest(base_type=base_type):
                api = load(mutate(BOXED, '_base_type = "u64"', f'_base_type = "{base_type}"'))
                self.assertEqual(api.boxed_scalars[0].base_type, base_type)
        message = "boxed_scalar.offset._base_type is required, one of i8, u8, i16, u16, i32, u32, i64, u64"
        for value in ('"f64"', '"memory"', '"status"', "8", '["u64"]'):
            with self.subTest(value=value):
                assert_objection(self, mutate(BOXED, '_base_type = "u64"', f"_base_type = {value}"), message)
        assert_objection(self, mutate(BOXED, '_base_type = "u64"', '_docstring = "no base"'), message)

    def test_has_only_properties(self) -> None:
        assert_objection(
            self,
            mutate(BOXED, '_base_type = "u64"', '_base_type = "u64"\nvalue = "u64"'),
            "boxed_scalar.offset: 'value': a boxed_scalar has no members; its properties begin with _",
        )
        assert_objection(
            self,
            mutate(BOXED, '_base_type = "u64"', '_base_type = "u64"\n_class = "x"'),
            "boxed_scalar.offset: unknown key(s) _class",
        )

    def test_refused_as_return(self) -> None:
        assert_objection(
            self,
            BOXED + '\n[function.where]\n_return = "offset"\n',
            "function.where._return: unknown typed_const 'offset'",
        )

    def test_shares_the_type_namespace_and_the_c_identifiers(self) -> None:
        assert_objection(
            self, BOXED + '\n[struct.offset]\nx = "u32"\n', "struct.offset: type name already defined in boxed_scalar"
        )
        assert_objection(
            self,
            mutate(BOXED, "[boxed_scalar.offset]", "[boxed_scalar.port]"),
            "boxed_scalar.port: type name already defined in opaque_ref",
        )
        assert_objection(
            self,
            mutate(BOXED, "[boxed_scalar.offset]", "[boxed_scalar.u64]"),
            "boxed_scalar.u64: shadows builtin type u64",
        )
        assert_objection(
            self,
            BOXED + '\n[function.offset]\n_return = "status"\n',
            "function.offset: C identifier xy_offset already defined by boxed_scalar.offset",
        )


class Groups(unittest.TestCase):
    def test_a_named_kind_written_without_groups_is_refused(self) -> None:
        for kind in ("typed_const", "opaque_ref", "boxed_scalar", "struct", "function"):
            with self.subTest(kind=kind):
                assert_objection(self, MINIMAL + f"\n[{kind}.x]\n", f"[{kind}] must be an array of tables, [[{kind}]]")

    def test_a_group_without_members_is_refused_by_its_index(self) -> None:
        assert_objection(self, FIXTURE + '\n[[function]]\n_docstring = "none"\n', "function[1]: has no entries")

    def test_a_named_kinds_group_has_only_a_docstring(self) -> None:
        assert_objection(
            self, mutate(FIXTURE, "[[struct]]\n", '[[struct]]\n_colour = "red"\n'), "struct[0]: unknown key(s) _colour"
        )

    def test_a_group_docstring_has_no_line_break(self) -> None:
        assert_objection(
            self,
            FIXTURE + '\n[[function]]\n_docstring = "a\\nb"\n[function.reset]\n_return = "status"\n',
            "function[1]._docstring must not contain a line break",
        )

    def test_an_item_name_is_unique_across_its_kinds_groups(self) -> None:
        assert_objection(
            self,
            FIXTURE + '\n[[function]]\n[function.spend]\n_return = "status"\n',
            "function.spend: already defined in function[0]",
        )

    def test_an_item_body_is_a_table(self) -> None:
        assert_objection(
            self, mutate(FIXTURE, "[[function]]\n", "[[function]]\nreset = 5\n"), "function.reset must be a table"
        )


# BOXED with a struct holding a text field and a function of an out array of each element
# kind the generator produces, two of them reporting what they wrote and need.
ARRAYS = BOXED + (
    '\n[struct.entry]\nid = "u32"\nlabel = "text"\n'
    '\n[function.list]\n_return = "status"\nhport = "port"\n'
    'ids = { _type = "u16", _ref = "out", _count = "u8" }\n'
    'spots = { _type = "offset", _ref = "out", _count = "u32" }\n'
    'items = { _type = "entry", _ref = "out", _count = "u64", _wrote_needed = true }\n'
    'labels = { _type = "memory", _ref = "out", _count = "u32", _wrote_needed = true }\n'
)
IDS = 'ids = { _type = "u16", _ref = "out", _count = "u8" }'


class Buffers(unittest.TestCase):
    def test_an_out_array_of_a_builtin_boxed_scalar_or_struct_loads_as_its_element(self) -> None:
        params = next(f for f in load(ARRAYS).functions if f.name == "list").params[1:]
        self.assertEqual(
            [(p.type, p.ref, p.count_type, p.wrote_needed) for p in params],
            [
                ("u16", "out", "u8", False),
                ("offset", "out", "u32", False),
                ("entry", "out", "u64", True),
                ("memory", "out", "u32", True),
            ],
        )

    def test_an_in_array_of_a_builtin_boxed_scalar_struct_or_enum_loads_as_its_element(self) -> None:
        for element in ("u16", "offset", "entry", "status"):
            for optional in (False, True):
                with self.subTest(element=element, optional=optional):
                    ids = f'ids = {{ _type = "{element}", _ref = "in", _count = "u8", _optional = {str(optional).lower()} }}'
                    ids_param = next(f for f in load(mutate(ARRAYS, IDS, ids)).functions if f.name == "list").params[1]
                    self.assertEqual(
                        (ids_param.type, ids_param.ref, ids_param.count_type, ids_param.optional),
                        (element, "in", "u8", optional),
                    )

    def test_arrays_the_generator_does_not_produce_are_not_implemented(self) -> None:
        text_parameter = "function.list.ids: a text parameter is not implemented; text is a struct field type"
        for replacement, message in (
            (
                IDS.replace('"out"', '"inout"'),
                'function.list.ids: an array with _ref = "inout" is not implemented, only "in" or "out"',
            ),
            (
                IDS.replace('"u16"', '"status"'),
                "function.list.ids: an array of typed_const 'status' is not implemented",
            ),
            (IDS.replace('"u16"', '"token"'), "function.list.ids: an array of opaque_ref 'token' is not implemented"),
            (
                IDS.replace('"u16"', '"token"').replace('"out"', '"in"'),
                "function.list.ids: an array of opaque_ref 'token' is not implemented",
            ),
            (IDS.replace('"u16"', '"text"'), text_parameter),
            ('ids = "text"', text_parameter),
            ('ids = { _type = "text", _ref = "in" }', text_parameter),
        ):
            with self.subTest(replacement=replacement):
                assert_objection(self, mutate(ARRAYS, IDS, replacement), message)

    def test_an_array_is_optional_only_as_any_buffer_is(self) -> None:
        assert_objection(
            self,
            mutate(ARRAYS, IDS, IDS.replace('_ref = "out"', '_ref = "out", _optional = true')),
            'function.list.ids._optional: a buffer is optional only with _ref = "in"',
        )

    def test_wrote_needed_is_a_boolean_on_an_out_buffer_only(self) -> None:
        refusal = '._wrote_needed: only an "out" buffer reports what it wrote and needs'
        for needle, replacement, where in (
            ('unit = "u32"', 'unit = { _type = "u32", _wrote_needed = true }', "function.open_port.unit"),
            ('_ref = "in", _count = "u64"', '_ref = "in", _count = "u64", _wrote_needed = true', "function.send.buf"),
            ('_type = "memory", _ref = "out"', '_type = "memory", _ref = "inout"', "function.list.labels"),
            (
                'generation = { _type = "u32", _ref = "out" }',
                'generation = { _type = "u32", _ref = "out", _wrote_needed = true }',
                "function.open_port.generation",
            ),
        ):
            with self.subTest(where=where):
                assert_objection(self, mutate(ARRAYS, needle, replacement), where + refusal)
        assert_objection(
            self,
            mutate(ARRAYS, '_count = "u64", _wrote_needed = true', '_count = "u64", _wrote_needed = "yes"'),
            "function.list.items._wrote_needed must be true or false",
        )

    def test_text_is_a_builtin_struct_field_type(self) -> None:
        entry = next(s for s in load(ARRAYS).structs if s.name == "entry")
        self.assertEqual([f.type for f in entry.fields], ["u32", "text"])
        assert_objection(self, FIXTURE + '\n[struct.text]\nx = "u32"\n', "struct.text: shadows builtin type text")

    def test_a_parameter_named_like_a_buffers_report_is_refused_naming_both(self) -> None:
        for name in ("items_wrote", "items_needed"):
            with self.subTest(name=name):
                assert_objection(
                    self,
                    mutate(ARRAYS, "labels = {", f'{name} = "u32"\nlabels = {{'),
                    f"function.list.items: its report parameter {name} is already a parameter",
                )

    def test_a_function_named_text_collides_with_the_text_type_where_a_field_is_text(self) -> None:
        function = '\n[function.text]\n_return = "status"\n'
        assert_objection(
            self, ARRAYS + function, "function.text: C identifier xy_text already defined by the builtin type text"
        )
        self.assertEqual(objections(FIXTURE + function), [])


# BOXED with an enum a callback answers and a callback type taking a view of each element kind
# a view may have and a value of each by-value kind; STREAM adds a method passing one.
SEEN = 'seen = { _type = "stats", _ref = "in", _count = "u64" }'
CALLBACK = BOXED + (
    "\n[typed_const.flow]\ngo = 0\nhalt = 1\n"
    '\n[[callback]]\n[callback.on_batch]\n_return = "flow"\n'
    f"{SEEN}\n"
    'spots = { _type = "offset", _ref = "in", _count = "u8" }\n'
    'ids = { _type = "u16", _ref = "in", _count = "u32" }\n'
    'arena = { _type = "memory", _ref = "in", _count = "u32" }\n'
    'mode = "status"\n'
    'last = "u32"\n'
)
SINK = 'sink = "on_batch"'
STREAM = CALLBACK + f'\n[function.stream]\n_return = "status"\nhport = "port"\n{SINK}\n'


class Callbacks(unittest.TestCase):
    def test_a_callback_loads_with_its_parameters_in_order_and_a_function_passes_it_by_value(self) -> None:
        api = load(STREAM)
        (on_batch,) = api.callbacks
        self.assertEqual(
            [(p.name, p.type, p.ref, p.count_type) for p in on_batch.params],
            [
                ("seen", "stats", "in", "u64"),
                ("spots", "offset", "in", "u8"),
                ("ids", "u16", "in", "u32"),
                ("arena", "memory", "in", "u32"),
                ("mode", "status", None, None),
                ("last", "u32", None, None),
            ],
        )
        sink = next(f for f in api.functions if f.name == "stream").params[1]
        self.assertEqual(
            (sink.type, sink.ref, sink.callback, sink.derived_names()), ("on_batch", None, True, ("sink_user_data",))
        )

    def test_a_callback_parameter_takes_no_optional_or_wrote_needed(self) -> None:
        for attribute in ("_optional", "_wrote_needed"):
            with self.subTest(attribute=attribute):
                assert_objection(
                    self,
                    mutate(CALLBACK, SEEN, SEEN.replace(" }", f", {attribute} = true }}")),
                    f"callback.on_batch.seen: unknown key(s) {attribute}",
                )

    def test_callback_parameters_the_generator_does_not_produce_are_not_implemented(self) -> None:
        where = "callback.on_batch.seen"
        for replacement, message in (
            ('seen = "stats"', "a struct 'stats' by value is not implemented in a callback"),
            ('seen = "offset"', "a boxed_scalar 'offset' by value is not implemented in a callback"),
            ('seen = "token"', "an opaque_ref 'token' is not implemented in a callback"),
            (
                'seen = { _type = "token", _ref = "in", _count = "u64" }',
                "an array of opaque_ref 'token' is not implemented",
            ),
            (
                'seen = { _type = "status", _ref = "in", _count = "u64" }',
                "an array of typed_const 'status' is not implemented",
            ),
            *(
                (
                    f'seen = {{ _type = "{t}", _ref = "{ref}"{count} }}',
                    f'a callback parameter with _ref = "{ref}" is not implemented, only a buffer with _ref = "in"',
                )
                for t, ref, count in (
                    ("u32", "in", ""),
                    ("u32", "out", ""),
                    ("stats", "inout", ""),
                    ("stats", "out", ', _count = "u64"'),
                    ("memory", "inout", ', _count = "u64"'),
                )
            ),
            ('seen = "text"', "a text parameter is not implemented; text is a struct field type"),
            ('seen = "on_batch"', "callback 'on_batch' as a callback's parameter is not implemented"),
        ):
            with self.subTest(replacement=replacement):
                assert_objection(self, mutate(CALLBACK, SEEN, replacement), f"{where}: {message}")

    def test_callback_refusals(self) -> None:
        for text, message in (
            (
                mutate(CALLBACK, 'last = "u32"', 'user_data = "u32"'),
                "callback.on_batch.user_data: 'user_data' is the C callback type's own last parameter",
            ),
            (
                mutate(CALLBACK, "go = 0\nhalt = 1\n", "go = 0\n"),
                "callback.on_batch._return: typed_const 'flow' has no non-zero entry to stop with",
            ),
            (
                mutate(CALLBACK, "go = 0\nhalt = 1\n", "halt = 1\n"),
                "callback.on_batch._return: typed_const 'flow' has no zero-valued entry for success",
            ),
            (
                mutate(CALLBACK, 'last = "u32"', 'seen_count = "u32"'),
                "callback.on_batch.seen: its count parameter seen_count is already a parameter",
            ),
        ):
            with self.subTest(message=message):
                assert_objection(self, text, message)

    def test_a_callback_type_is_a_by_value_parameter_of_a_function_and_nothing_else(self) -> None:
        for text, message in (
            (
                STREAM + '\n[struct.hook]\ncb = "on_batch"\n',
                "struct.hook.cb: a field of callback 'on_batch' is not implemented",
            ),
            (
                mutate(STREAM, SINK, 'sink = { _type = "on_batch", _ref = "in", _count = "u8" }'),
                "function.stream.sink: an array of callback 'on_batch' is not implemented",
            ),
            (
                mutate(STREAM, SINK, 'sink = { _type = "on_batch", _ref = "in" }'),
                "function.stream.sink: a callback is passed by value",
            ),
            (
                mutate(STREAM, 'unit = "u32"', f'unit = "u32"\n{SINK}'),
                "opaque_ref.port._ctor: function.open_port.sink: a constructor's callback parameter is not implemented",
            ),
        ):
            with self.subTest(message=message):
                assert_objection(self, text, message)

    def test_a_callback_parameters_user_data_is_refused_as_another_parameter_naming_both(self) -> None:
        assert_objection(
            self,
            mutate(STREAM, SINK, f'{SINK}\nsink_user_data = "u32"'),
            "function.stream.sink: its user_data parameter sink_user_data is already a parameter",
        )

    def test_a_callback_shares_the_type_namespace_and_the_c_identifiers(self) -> None:
        for text, message in (
            (
                mutate(CALLBACK, "[callback.on_batch]", "[callback.stats]"),
                "callback.stats: type name already defined in struct",
            ),
            (mutate(CALLBACK, "[callback.on_batch]", "[callback.u32]"), "callback.u32: shadows builtin type u32"),
            (
                STREAM + '\n[function.on_batch]\n_return = "status"\n',
                "function.on_batch: C identifier xy_on_batch already defined by callback.on_batch",
            ),
        ):
            with self.subTest(message=message):
                assert_objection(self, text, message)


class Unions(unittest.TestCase):
    def assert_refused(self, rule: str) -> None:
        text, expected = UNION_REFUSALS[rule]
        self.assertEqual(objections(text), expected)

    def test_a_union_loads_with_its_members_in_order_and_its_prefix_inferred(self) -> None:
        api = load(UNIONS)
        (note,) = api.unions
        self.assertEqual(
            (note.name, note.prefix, [(m.name, m.tag, m.struct, m.docstring) for m in note.members]),
            (
                "note",
                "note_head",
                [("line", "kind_line", "note_line", None), ("mark", "kind_mark", "note_mark", "a value and its flag")],
            ),
        )
        self.assertEqual((api.kind("note"), api.union_groups[0].docstring), ("union", "what a note is"))
        self.assertIn(("union.note.mark", "mark"), api.names())

    def test_a_counted_union_parameter_is_a_sequence_of_pointer_count_and_extent(self) -> None:
        api = load(mutate(UNIONS, NOTES, NOTES.replace(" }", ", _optional = true }")))
        for fn in (*api.callbacks, *api.functions):
            param, *_ = fn.params
            with self.subTest(param=f"{fn.name}.{param.name}"):
                self.assertEqual((param.type, param.ref, param.count_type), ("note", "in", "u32"))
                self.assertTrue(param.is_union and param.is_buffer)
                self.assertEqual([param.name, *param.derived_names()], buffer_expansion(param))
        self.assertTrue(api.functions[0].params[0].optional)

    def test_layout_is_the_c_layout(self) -> None:
        api = load(UNIONS)
        self.assertEqual(
            {name: api.layout(name) for name in ("note_head", "note_line", "note_mark", "text", "u16", "f64", "flow")},
            {
                "note_head": (8, 4),
                "note_line": (16, 4),
                "note_mark": (16, 4),
                "text": (8, 4),
                "u16": (2, 2),
                "f64": (8, 8),
                "flow": (4, 4),
            },
        )
        self.assertEqual(load(KITCHEN_SINK).layout("wrap"), (24, 8))  # stats { u32, u64 } then a u32
        self.assertEqual(load(mutate(KITCHEN_SINK, '_base_type = "u64"', '_base_type = "u8"')).layout("offset"), (1, 1))

    def test_mixed_type_list_is_a_union_boolean_defaulting_false(self) -> None:
        self.assertTrue(load(UNIONS).unions[0].mixed_type_list)
        uncounted = mutate(
            mutate(UNIONS, NOTES, 'notes = "u32"'),
            'seen = { _type = "note", _ref = "in", _count = "u32" }',
            'seen = "u32"',
        )
        self.assertFalse(load(mutate(uncounted, f"{MIXED_TYPE_LIST}\n", "")).unions[0].mixed_type_list)
        self.assert_refused("a mixed type list that is not a boolean")

    def test_only_a_mixed_type_list_is_a_counted_parameters_type(self) -> None:
        self.assert_refused("a counted parameter of a union not a mixed type list")

    def test_every_counted_parameter_of_a_union_shares_its_count_type_u32_where_none_counts_it(self) -> None:
        self.assertEqual(load(UNIONS).unions[0].count_type, "u32")
        u16 = mutate(UNIONS, '_count = "u32"', '_count = "u16"', every=True)
        self.assertEqual(load(u16).unions[0].count_type, "u16")
        self.assertEqual(load(UNION_NOT_LISTED).unions[0].count_type, "u32")
        self.assert_refused("a second count type for one union")

    def test_the_shape_rule_holds_of_a_union_that_is_no_mixed_type_list(self) -> None:
        text, expected = UNION_REFUSALS["a prefix with padding"]
        without = mutate(text, f"{MIXED_TYPE_LIST}\n", "")
        self.assertEqual(objections(without)[0], expected[0])

    def test_a_union_names_a_member(self) -> None:
        self.assert_refused("no member")

    def test_a_member_is_a_tag_and_a_type(self) -> None:
        for rule in ("a member without _type", "a member as a naked value", "a member's unknown key"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_tag_is_an_untyped_const_entry(self) -> None:
        self.assert_refused("a tag naming no untyped_const entry")

    def test_a_type_is_a_struct_defined_before_the_union(self) -> None:
        for rule in ("a type naming no struct", "a type of another category"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_every_member_begins_with_one_struct_the_prefix(self) -> None:
        for rule in ("members beginning with different structs", "a member not beginning with a struct"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_the_prefix_is_a_tag_then_any_u8_fields_then_the_length(self) -> None:
        head = 'kind = "u16"\nsize = "u16"\nat = "u32"'
        for fields, expected in (
            (head, ("kind", "u16", "size", "u16")),
            ('kind = "u32"\nsize = "u32"', ("kind", "u32", "size", "u32")),
            ('kind = "u8"\na = "u8"\nb = "u8"\nc = "u8"\nsize = "u32"', ("kind", "u8", "size", "u32")),
        ):
            with self.subTest(fields=fields):
                api = load(mutate(UNIONS, head, fields))
                (note,) = api.unions
                tag, length = api.prefix_fields(note)
                self.assertEqual((note.tag_field, tag.type, note.length_field, length.type), expected)
                self.assertEqual((tag.name, length.name), (note.tag_field, note.length_field))
        api = load(UNION_U8_TAG)
        self.assertEqual(
            [(f.name, f.type) for f in api.prefix_fields(api.unions[0])], [("kind", "u8"), ("size", "u16")]
        )

    def test_the_prefix_refuses_a_tag_or_length_of_another_type(self) -> None:
        for rule in (
            "a prefix whose tag and length are signed",
            "a prefix whose length is u8",
            "a prefix whose first field after a u8 tag is a struct",
            "a prefix read one level deep",
        ):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_u8_tag_holds_a_tag_up_to_255(self) -> None:
        self.assertEqual(objections(mutate(UNION_U8_TAG, "kind_mark = 2", "kind_mark = 255")), [])
        self.assertEqual(
            objections(mutate(UNION_U8_TAG, "kind_mark = 2", "kind_mark = 256")),
            ["union.note.mark._tag: kind_mark's value 256 does not fit note_head.kind (u8)", *NOTE_REFS],
        )

    def test_a_u32_prefix_holds_what_a_u16_one_does_not(self) -> None:
        text, _ = UNION_REFUSALS["a tag the tag field cannot hold"]
        self.assertEqual(objections(mutate(text, 'kind = "u16"\nsize = "u16"', 'kind = "u32"\nsize = "u32"')), [])

    def test_the_tag_fits_the_tag_field(self) -> None:
        self.assert_refused("a tag the tag field cannot hold")

    def test_no_two_members_share_a_tag_or_a_struct(self) -> None:
        for rule in ("two members of one tag", "two members of one tag value", "two members of one struct"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_member_has_the_prefixs_alignment(self) -> None:
        self.assert_refused("a member aligned past the prefix")

    def test_a_member_and_the_prefix_are_each_a_whole_multiple_of_the_lists_alignment(self) -> None:
        for rule in ("a member short of the list's alignment", "a prefix short of the list's alignment"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_member_and_the_prefix_have_no_padding(self) -> None:
        for rule in ("a member with padding", "a prefix with padding", "a u8 field between a u16 tag and the length"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_member_is_laid_out_alike_on_every_target(self) -> None:
        self.assert_refused("a member holding an opaque ref")

    def test_a_members_size_fits_the_length_field(self) -> None:
        self.assert_refused("a member the length field cannot count")

    def test_a_union_parameter_is_a_sequence_with_ref_in(self) -> None:
        for rule in ("a union in without _count", "a union out", "a union inout"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_union_is_not_a_field_or_a_by_value_parameter(self) -> None:
        for rule in ("a union field", "a union by value", "a union by value in a callback"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_sequences_derived_names_are_free(self) -> None:
        for rule in ("a parameter named like the extent", "a parameter named like the count"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)

    def test_a_union_shares_the_type_namespace(self) -> None:
        for rule in ("a struct named like a union", "a union named like a builtin"):
            with self.subTest(rule=rule):
                self.assert_refused(rule)


class Shape(unittest.TestCase):
    def test_success_entry_is_the_zero_valued_one(self) -> None:
        text = mutate(FIXTURE, "ok = 0\nerr_busy = { _value = 9", "err_busy = { _value = 9")
        api = load(
            mutate(
                text,
                'err_other = { _value = 0x7fffffff, _format = "hex" }',
                'err_other = { _value = 0x7fffffff, _format = "hex" }\nfine = 0',
            )
        )
        self.assertEqual(api.success_entry(api.functions[0]).name, "fine")


class Uses64Bit(unittest.TestCase):
    def test_the_kitchen_sink_uses_64_bit(self) -> None:
        self.assertTrue(load(KITCHEN_SINK).uses_64_bit())

    def test_a_definition_with_the_64_bit_value_positions_stripped_does_not(self) -> None:
        # FIXTURE's every value position is its one u64 field; `send.buf`'s `_count = "u64"`
        # is a count width, not a value, and the field gone it must not hold the predicate.
        self.assertFalse(load(mutate(FIXTURE, 'bytes = "u64"', 'bytes = "u32"')).uses_64_bit())


class SchemaEnforcement(unittest.TestCase):
    """`model.load()` runs `api_def.schema.json` ahead of the loader where jsonschema imports;
    these catch drift between it and the loader."""

    def load_text(self, text: str) -> model.Api:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "xy_api.adef.toml"
        path.write_text(text, encoding="utf-8")
        return model.load(path)

    def test_the_schema_is_a_valid_draft_2020_12_schema(self) -> None:
        schema = json.loads((Path(model.__file__).parent / "api_def.schema.json").read_text(encoding="utf-8"))
        jsonschema.validators.Draft202012Validator.check_schema(schema)

    def test_every_hint_the_loader_names_is_declared_in_the_schema(self) -> None:
        source = Path(model.__file__).read_text(encoding="utf-8")
        named = set(re.findall(r'"(_[a-z_]+)"', source))
        schema = json.loads((Path(model.__file__).parent / "api_def.schema.json").read_text(encoding="utf-8"))
        declared: set[str] = set()

        def collect(node: object) -> None:
            if isinstance(node, dict):
                declared.update(node.get("properties", {}))
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(schema)
        self.assertEqual(sorted(named - declared), [])

    def test_a_hint_misspelled_is_refused_at_load_naming_the_key(self) -> None:
        text = mutate(FIXTURE, 'bytes = "u64"', 'bytes = { _type = "u64", _maxx = 5 }')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "xy_api.adef.toml"
        path.write_text(text, encoding="utf-8")
        with self.assertRaises(model.DefinitionError) as caught:
            model.load(path)
        refusals = [str(o) for o in caught.exception.objections()]
        self.assertTrue(any("_maxx" in r and "/struct/0/stats/bytes" in r for r in refusals), refusals)

    def test_every_fixture_loads_through_the_schema_gate(self) -> None:
        for name, text in (
            ("FIXTURE", FIXTURE),
            ("KITCHEN_SINK", KITCHEN_SINK),
            ("MINIMAL", MINIMAL),
            ("UNIONS", UNIONS),
        ):
            with self.subTest(name=name):
                self.load_text(text)


if __name__ == "__main__":
    unittest.main()
