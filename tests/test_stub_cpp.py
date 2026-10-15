import re
import unittest

from langxyne.emitters import emit_stub_cpp
from langxyne.tests.support import (
    DOCUMENTED_FUNCTION_GROUPS,
    FIXTURE,
    KITCHEN_SINK,
    UNIONS,
    buffer_expansion,
    load,
    mutate,
)


def stub(text: str = FIXTURE) -> str:
    return emit_stub_cpp.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", project="xy")


class Stub(unittest.TestCase):
    def setUp(self) -> None:
        self.text = stub()

    def test_preprocessor_lines_are_the_impl_guarded_include_then_the_std_headers(self) -> None:
        lines = [line for line in self.text.splitlines() if line.startswith("#")]
        self.assertEqual(
            lines,
            [
                "#define XY_IMPL",
                '#include "xy_api.h"',
                "#undef XY_IMPL",
                "#include <cerrno>",
                "#include <cstdint>",
                "#include <cstring>",
            ],
        )

    def test_every_body_voids_each_parameter_then_returns_default_initialized(self) -> None:
        api = load(KITCHEN_SINK)
        bodies = dict(
            re.findall(
                r"xy_(\w+)\([^)]*\) \{\n((?:  \(void\)\w+;\n)*)  // replace: not implemented\n  return \{\};\n\}\n",
                stub(KITCHEN_SINK),
            )
        )
        self.assertEqual(list(bodies), [f.name for f in api.functions])
        for fn in api.functions:
            with self.subTest(function=fn.name):
                names = [n for p in fn.params for n in buffer_expansion(p)]
                self.assertEqual(bodies[fn.name], "".join(f"  (void){n};\n" for n in names))

    def test_a_unions_list_is_the_headers_pointer_count_and_extent(self) -> None:
        self.assertIn(
            "XY_API xy_status xy_replay(const xy_note_head* notes, uint32_t notes_count, uint32_t notes_bytes) {\n"
            "  (void)notes;\n  (void)notes_count;\n  (void)notes_bytes;\n",
            stub(UNIONS),
        )


class Validate(unittest.TestCase):
    def test_a_union_renders_rather_than_being_refused(self) -> None:
        self.assertEqual(emit_stub_cpp.validate(load(UNIONS)), [])

    def test_cpp_keyword_as_name(self) -> None:
        self.assertEqual(
            emit_stub_cpp.validate(load(mutate(FIXTURE, "unit = ", "class = "))),
            ["stub: function.open_port.class: 'class' is a C++ keyword"],
        )

    def test_parameter_named_like_a_type_its_signatures_spell_as_the_header_refuses(self) -> None:
        self.assertEqual(
            emit_stub_cpp.validate(load(mutate(FIXTURE, 'htoken = "token"', 'uint32_t = "token"'))),
            ["stub: function.spend.uint32_t: 'uint32_t' is a name the generated code uses"],
        )


class GroupDocstring(unittest.TestCase):
    def test_a_function_groups_docstring_is_a_line_above_its_first_definition(self) -> None:
        text = stub(DOCUMENTED_FUNCTION_GROUPS)
        self.assertIn("\n// port lifecycle\nXY_API xy_status xy_open_port(", text)
        self.assertIn("\n\nXY_API xy_status xy_destroy_port(", text)
        self.assertIn("\n// traffic\nXY_API xy_status xy_send(", text)


if __name__ == "__main__":
    unittest.main()
