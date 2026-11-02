import ast
import ctypes
import dataclasses
import os
import unittest
from unittest import mock

from langxyne import model, naming
from langxyne.emitters import emit_binding_py
from langxyne.tests.support import FIXTURE, MIXED_TYPE_LIST, NOTES, UNION_U8_TAG, UNIONS, load, mutate


def module(text: str = FIXTURE) -> str:
    return emit_binding_py.emit(load(text), source_name="xy_api.adef.toml", name="xy_api", project="xy")


# The six clauses a walk of a union's list refuses with, in SPEC.md's words.
CLAUSES = (
    "header past the extent",
    "unknown tag",
    "size is not the member's",
    "record past the extent",
    "count not met",
    "offset is not a record's start",
)
# UNIONS' union without `_mixed_type_list`, and so without the callback and function taking its list.
FAMILY = mutate(UNIONS[: UNIONS.index("[[callback]]")], f"{MIXED_TYPE_LIST}\n", "")


class Load(unittest.TestCase):
    def test_every_platform_loads_its_shared_file(self) -> None:
        # SPEC.md's table, by the value Python's sys module reports as the platform
        assignment = next(
            node for node in ast.parse(module()).body if isinstance(node, ast.Assign) and node.targets[0].id == "_FILES"
        )
        self.assertEqual(
            ast.literal_eval(assignment.value), {"linux": "libxy.so", "darwin": "libxy.dylib", "win32": "xy.dll"}
        )

    def test_a_static_link_is_refused(self) -> None:
        api = load()
        api = dataclasses.replace(api, library=model.Library(name=api.library.name, link=naming.STATIC))
        self.assertEqual(
            emit_binding_py.validate(api),
            ["python: --link=static: the Python module loads its library at run time and cannot link it statically"],
        )


# (definition, the one objection the Python module has to it)
REFUSALS = (
    (
        mutate(FIXTURE, "buf = {", "lambda = {"),
        "python: function.send.lambda: 'lambda' is a Python keyword",
    ),
    (
        mutate(FIXTURE, "buf = {", "self = {"),
        "python: function.send.self: 'self' is a name the generated code uses",
    ),
    (
        # a field of a ctypes structure hides the classmethod of its name, which the module calls
        mutate(FIXTURE, "bytes = ", "from_buffer_copy = "),
        "python: struct.stats.from_buffer_copy: 'from_buffer_copy' is a name the generated code uses",
    ),
    (
        FIXTURE + '\n[[struct]]\n[struct.error]\nv = "u32"\n',
        "python: module scope: Error would be defined more than once, by struct.error and the module's "
        "exception class",
    ),
    (
        UNIONS + '\n[[struct]]\n[struct.note_sequence]\nv = "u32"\n',
        "python: struct.note_sequence: module scope name NoteSequence already defined by union 'note'",
    ),
    (
        mutate(UNIONS, "kind_mark = 2", "kind_mark = 2\nnote_align = 3"),
        "python: untyped_const.note_align: module scope name NOTE_ALIGN already defined by union 'note'",
    ),
    (
        UNIONS + '\n[[struct]]\n[struct.union_error]\nv = "u32"\n',
        "python: struct.union_error: module scope name UnionError already defined by union 'note'",
    ),
)


class Validate(unittest.TestCase):
    def test_each_refusal_names_what_it_refuses(self) -> None:
        for text, message in REFUSALS:
            with self.subTest(message=message):
                self.assertEqual(emit_binding_py.validate(load(text)), [message])


class Unions(unittest.TestCase):
    """A union declaring `_mixed_type_list`: its sequence class, which a callback's view of its
    list is and a function's list takes, each the three C parameters."""

    def setUp(self) -> None:
        self.text = module(UNIONS)

    def test_the_module_has_no_objection_and_compiles(self) -> None:
        self.assertEqual(emit_binding_py.validate(load(UNIONS)), [])
        compile(self.text, "xy_api.py", "exec")

    def test_the_sequence_class_names_each_members_structure_and_size_by_its_tag(self) -> None:
        self.assertIn("\n# the list's alignment, the unit of NoteSequence.at's index\nNOTE_ALIGN = 4\n", self.text)
        self.assertIn(
            "class NoteSequence(_Sequence):\n"
            '    "one note: the struct its head\'s kind names, head.size bytes long"\n'
            "    __slots__ = ()\n"
            "    _PREFIX, _PREFIX_SIZE, _ALIGN = NoteHead, 8, NOTE_ALIGN\n"
            '    _TAG, _LENGTH = "kind", "size"\n'
            "    _MEMBERS = {KIND_LINE: (NoteLine, 16), KIND_MARK: (NoteMark, 16)}\n",
            self.text,
        )

    def test_a_u8_tag_prefix_names_its_tag_and_length_fields(self) -> None:
        self.assertEqual(emit_binding_py.validate(load(UNION_U8_TAG)), [])
        self.assertIn("\nNOTE_ALIGN = 2\n", module(UNION_U8_TAG))
        self.assertIn(
            "    _PREFIX, _PREFIX_SIZE, _ALIGN = NoteHead, 4, NOTE_ALIGN\n"
            '    _TAG, _LENGTH = "kind", "size"\n'
            "    _MEMBERS = {KIND_LINE: (NoteLine, 6), KIND_MARK: (NoteMark, 8)}\n",
            module(UNION_U8_TAG),
        )

    def test_a_refusal_is_a_union_error_naming_the_record_its_offset_and_the_clause(self) -> None:
        self.assertIn("class UnionError(RuntimeError):", self.text)
        self.assertIn('f"{what} refused at record {index}, offset {offset}: {clause}"', self.text)
        self.assertIn("self.index, self.offset, self.clause = index, offset, clause", self.text)
        for clause in CLAUSES:
            with self.subTest(clause=clause):
                self.assertIn(f'"{clause}"', self.text)

    def test_a_callbacks_view_is_a_sequence_of_its_three_c_parameters(self) -> None:
        self.assertIn(
            "_on_notes_c_type = _ctypes.CFUNCTYPE(_ctypes.c_int32, _ctypes.c_void_p, _ctypes.c_uint32, "
            "_ctypes.c_uint32, _ctypes.c_uint32, _ctypes.c_void_p)\n",
            self.text,
        )
        self.assertIn('views.append(NoteSequence(a0, a1, a2, "xy_on_notes received view seen"))', self.text)
        self.assertIn("answer = fn(views[0], a3)", self.text)

    def test_a_functions_list_is_a_sequence_passed_as_its_three_c_parameters(self) -> None:
        self.assertIn("_lib.xy_replay.argtypes = (_ctypes.c_void_p, _ctypes.c_uint32, _ctypes.c_uint32)\n", self.text)
        self.assertIn(
            "def replay(notes):\n"
            "    if not isinstance(notes, NoteSequence):\n"
            '        raise TypeError("replay: notes must be a NoteSequence")\n'
            "    _l_notes, _c_notes, _b_notes = notes._c_arguments()\n"
            "    _raw = _lib.xy_replay(_l_notes, _c_notes, _b_notes)\n",
            self.text,
        )
        optional = module(mutate(UNIONS, NOTES, NOTES.replace(" }", ", _optional = true }")))
        self.assertIn(
            "    _l_notes, _c_notes, _b_notes = (None, 0, 0) if notes is None else notes._c_arguments()\n", optional
        )

    def test_a_union_without_the_property_renders_its_structures_alone(self) -> None:
        self.assertEqual(emit_binding_py.validate(load(FAMILY)), [])
        text = module(FAMILY)
        self.assertIn("class NoteMark(_ctypes.Structure):", text)
        for absent in ("Sequence", "UnionError", "_MEMBERS"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, text)


class SequenceWalk(unittest.TestCase):
    """UNIONS' rendered module, loaded with its library stubbed, its `NoteSequence` built over
    lines in memory: `at`, in units of the list's alignment, against the count."""

    LINE = 16  # note_line's size, 4 units of the list's alignment, 4

    def setUp(self) -> None:
        self.m: dict = {"__name__": "xy_api", "__file__": "/xy/xy_api.py"}
        with mock.patch("ctypes.CDLL"), mock.patch.dict(os.environ, {"XY_LIBRARY": "/xy/libxy"}):
            exec(compile(module(UNIONS), "xy_api.py", "exec"), self.m)
        self.memory = (ctypes.c_uint32 * 16)()
        self.base = ctypes.addressof(self.memory)
        for i in range(3):
            line = self.m["NoteLine"].from_address(self.base + i * self.LINE)
            line.head.kind, line.head.size, line.label.offset = self.m["KIND_LINE"], self.LINE, i

    def sequence(self, address: int | None, count: int, extent: int):
        return self.m["NoteSequence"](address, count, extent, "xy_on_notes received view seen")

    def refusal(self, sequence, index: int) -> tuple[int, int, str]:
        with self.assertRaises(self.m["UnionError"]) as caught:
            sequence.at(index)
        return caught.exception.index, caught.exception.offset, caught.exception.clause

    def test_at_refuses_the_record_whose_index_is_the_count_before_its_offset(self) -> None:
        self.assertEqual(self.refusal(self.sequence(self.base, 1, 2 * self.LINE), 4), (1, 16, "count not met"))
        self.assertEqual(self.refusal(self.sequence(self.base, 1, 3 * self.LINE), 8), (1, 16, "count not met"))
        self.assertEqual(self.refusal(self.sequence(self.base, 0, self.LINE), 0), (0, 0, "count not met"))

    def test_at_lands_on_the_record_at_its_index_times_the_lists_alignment(self) -> None:
        sequence = self.sequence(self.base, 2, 2 * self.LINE)
        self.assertEqual([sequence.at(0).label.offset, sequence.at(4).label.offset], [0, 1])
        self.assertEqual(self.refusal(sequence, 1), (1, 4, "offset is not a record's start"))
        self.assertEqual(self.refusal(sequence, 8), (2, 32, "offset is not a record's start"))


if __name__ == "__main__":
    unittest.main()
