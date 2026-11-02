import dataclasses
import unittest

from langxyne import model, naming
from langxyne.emitters import emit_binding_go
from langxyne.tests.support import FIXTURE, KITCHEN_SINK, NOTES, UNION_NOT_LISTED, UNION_U8_TAG, UNIONS, load, mutate


def package(text: str = FIXTURE, *, link: str = naming.SHARED) -> str:
    api = load(text)
    api = dataclasses.replace(api, library=model.Library(name=api.library.name, link=link))
    return emit_binding_go.emit(api, source_name="xy_api.adef.toml", name="xy_api", project="xy")


# Each platform's static link flag, as SPEC.md's Go section states it for the library `xy`.
STATIC_LINK_FLAGS = (("linux", "-l:libxy.a"), ("darwin", "-lxy"), ("windows", "-l:libxy.a"))

_PORT = '[opaque_ref.port]\n_ctor = "open_port"\n'
# (definition, the one objection the Go binding has to it)
REFUSALS = (
    (
        mutate(FIXTURE, "buf = {", "func = {"),
        "go: function.send.func: 'func' is a Go keyword",
    ),
    (
        mutate(FIXTURE, "buf = {", "len = {"),
        "go: function.send.len: 'len' is a name the generated code uses",
    ),
    (
        mutate(FIXTURE, "buf = {", "Stats = {"),
        "go: function.send.Stats: 'Stats' is a name the generated code uses",
    ),
    (
        # a result local is declared by its Go type, which the parameter would shadow
        mutate(FIXTURE, 'htoken = "token"', 'uint32 = "u32"\npcount = { _type = "u32", _ref = "out" }'),
        "go: function.spend.uint32: 'uint32' is a name the generated code uses",
    ),
    (
        mutate(FIXTURE, _PORT, _PORT + '_class = "c"\n'),
        'go: package scope: C would be defined more than once, by import "C" and opaque_ref.port._class',
    ),
    (
        FIXTURE + '\n[[struct]]\n[struct.status_ok]\nv = "u32"\n',
        "go: package scope: StatusOk would be defined more than once, by typed_const.status.ok and " "struct.status_ok",
    ),
    (
        mutate(FIXTURE, 'generation = { _type = "u32"', 'send = { _type = "u32"'),
        "go: class Port: Send would be defined more than once, by function.send and function.open_port.send",
    ),
    (
        UNIONS + '\n[struct.note_walker]\nv = "u32"\n',
        "go: struct.note_walker: package scope name NoteWalker already defined by union 'note'",
    ),
    (
        UNIONS + '\n[struct.union_error]\nv = "u32"\n',
        "go: struct.union_error: package scope name UnionError already defined by union 'note'",
    ),
    (
        mutate(UNIONS, "kind_mark = 2", "kind_mark = 2\nnote_align = 3"),
        "go: untyped_const.note_align: package scope name NoteAlign already defined by union 'note'",
    ),
    (
        UNIONS + '\n[function.note_record]\n_return = "status"\n',
        "go: function.note_record: package scope name NoteRecord already defined by union 'note'",
    ),
    (
        mutate(UNIONS, "kind_mark = 2", "kind_mark = 2\nunion_clause_unknown_tag = 3"),
        "go: untyped_const.union_clause_unknown_tag: package scope name UnionClauseUnknownTag already defined by "
        "union 'note'",
    ),
    (
        mutate(UNIONS, NOTES, f'{NOTES}\nNoteSequence = "u32"'),
        "go: function.replay.NoteSequence: 'NoteSequence' is a name the generated code uses",
    ),
)


class Link(unittest.TestCase):
    """The only check of the Linux and Windows lines on a macOS host."""

    def test_a_shared_link_names_the_library(self) -> None:
        self.assertIn("\n// #cgo LDFLAGS: -lxy\n", package())

    def test_a_static_link_names_the_archive_where_the_linker_takes_a_file_name(self) -> None:
        text = package(link=naming.STATIC)
        for goos, flag in STATIC_LINK_FLAGS:
            with self.subTest(goos=goos):
                self.assertIn(f"\n// #cgo {goos} LDFLAGS: {flag}\n", text)
        self.assertNotIn("\n// #cgo LDFLAGS:", text)


# Each rule SPEC.md's Go section has a doc comment state, as a line of the package of FIXTURE or,
# for a callback type's, KITCHEN_SINK.
DOC_LINES = (
    (FIXTURE, "// Converting an integer no entry names to Status is not refused: the library receives it as it is.\n"),
    (
        FIXTURE,
        "// A Port is not safe for concurrent use, and must not be copied: pass *Port; go vet reports a copy. Its "
        "methods panic once it is released, and Handle's value is the library's only until then.\n",
    ),
    (
        KITCHEN_SINK,
        "// until it returns: keep indices into it, never the slice. Each slice is read-only: writing\n"
        "// through one, or appending to a slice that shares its memory, is a consumer error the library\n"
        "// cannot detect.",
    ),
)


class Docs(unittest.TestCase):
    def test_each_rule_a_doc_comment_states_is_rendered(self) -> None:
        for text, line in DOC_LINES:
            with self.subTest(line=line):
                self.assertIn(line, package(text))

    def test_a_static_link_documents_the_package_with_what_ld64_takes(self) -> None:
        self.assertIn(
            "\n// On macOS the linker takes libxy.dylib before libxy.a from the same directory, so the directory "
            "CGO_LDFLAGS names must hold the archive and no libxy.dylib.\npackage xy_api\n",
            package(link=naming.STATIC),
        )
        self.assertNotIn("On macOS", package())


class Preamble(unittest.TestCase):
    def test_no_header_is_included_and_no_function_exported_without_a_callback(self) -> None:
        text = package()
        self.assertNotIn('#include "', text)
        self.assertNotIn("//export", text)


class Validate(unittest.TestCase):
    def test_each_refusal_names_what_it_refuses(self) -> None:
        for text, message in REFUSALS:
            with self.subTest(message=message):
                self.assertEqual(emit_binding_go.validate(load(text)), [message])

    def test_a_union_is_rendered_with_or_without_the_property(self) -> None:
        for text in (UNIONS, UNION_NOT_LISTED):
            with self.subTest(listed=text is UNIONS):
                self.assertEqual(emit_binding_go.validate(load(text)), [])


# UNIONS with every count of its union by `u16`, and by `u64`.
UNIONS_U16 = UNIONS.replace('_count = "u32"', '_count = "u16"')
UNIONS_U64 = UNIONS.replace('_count = "u32"', '_count = "u64"')

# The forms SPEC.md's Go section states for a union declaring `_mixed_type_list`, each as a run of
# lines of the package of UNIONS.
UNION_FORMS = (
    "type UnionClause int32\n",
    *(
        f"\t// {text}\n\tUnionClause{variant} UnionClause = {value}\n"
        for value, (variant, text) in enumerate(
            (
                ("HeaderPastExtent", "header past the extent"),
                ("UnknownTag", "unknown tag"),
                ("SizeNotTheMembers", "size is not the member's"),
                ("RecordPastExtent", "record past the extent"),
                ("CountNotMet", "count not met"),
                ("NotARecordStart", "offset is not a record's start"),
            ),
            start=1,
        )
    ),
    '\tcase UnionClauseSizeNotTheMembers:\n\t\treturn "size is not the member\'s"\n',
    "type UnionError struct {\n\tIndex  uint32\n\tOffset uint32\n\tClause UnionClause\n}\n",
    "func (_e *UnionError) Error() string {\n"
    '\treturn "record " + _strconv.FormatUint(uint64(_e.Index), 10) + " at offset " + '
    '_strconv.FormatUint(uint64(_e.Offset), 10) + ": " + _e.Clause.String()\n}\n',
    "type NoteRecord interface {\n\t_note_record()\n}\n",
    "func (*NoteLine) _note_record() {}\n",
    "// mark: a value and its flag\nfunc (*NoteMark) _note_record() {}\n",
    "type NoteSequence struct {\n\t_bytes []byte\n\t_count uint32\n}\n",
    "func (_s NoteSequence) Count() uint32 {\n",
    "func (_s NoteSequence) Bytes() []byte {\n",
    "func (_s NoteSequence) Walk() *NoteWalker {\n",
    "func (_w *NoteWalker) Next() (NoteRecord, bool) {\n",
    "func (_w *NoteWalker) Err() error {\n",
    # the list's alignment, the unit of At's index
    "// NoteAlign is the list's alignment, the unit of NoteSequence.At's index.\nconst NoteAlign = 4\n",
    "func (_s NoteSequence) At(index uint32) (NoteRecord, error) {\n\toffset := ^uint32(0)\n"
    "\tif index <= offset/NoteAlign {\n\t\toffset = index * NoteAlign\n\t}\n",
    # the layout assertions, every figure the layout model's
    "var _ [0]struct{} = [unsafe.Sizeof(NoteHead{}) - 8]struct{}{}\n"
    "var _ [0]struct{} = [unsafe.Alignof(NoteHead{}) - 4]struct{}{}\n"
    "var _ [0]struct{} = [unsafe.Sizeof(NoteLine{}) - 16]struct{}{}\n"
    "var _ [0]struct{} = [unsafe.Alignof(NoteLine{}) - 4]struct{}{}\n"
    "var _ [0]struct{} = [unsafe.Sizeof(NoteMark{}) - 16]struct{}{}\n"
    "var _ [0]struct{} = [unsafe.Alignof(NoteMark{}) - 4]struct{}{}\n",
    # the walk reads a prefix only once its 8 bytes remain, a member's size by its tag's value
    "\tcase _index < _s._count && _left >= 8:\n",
    "\t\tcase 1: // line\n\t\t\t_size = 16\n\t\tcase 2: // mark\n\t\t\t_size = 16\n",
    "\t\tcase _head.Kind == 1:\n\t\t\treturn (*NoteLine)(unsafe.Pointer(_head)), _size, nil\n"
    "\t\tdefault:\n\t\t\treturn (*NoteMark)(unsafe.Pointer(_head)), _size, nil\n",
    # a callback's view and a function's list, each the three C parameters
    "type OnNotes func(seen NoteSequence, count uint32) Flow\n",
    "func xy__on_notes(_a0 *C.xy_note_head, _a1 C.uint32_t, _a2 C.uint32_t, _a3 C.uint32_t, _a4 unsafe.Pointer) ",
    "\tif (_a0 == nil && (_a1 != 0 || _a2 != 0)) || uintptr(unsafe.Pointer(_a0))%unsafe.Alignof(NoteHead{}) != 0 {\n"
    '\t\tpanic("xy_on_notes received view seen outside the definition")\n\t}\n'
    "\t_v0 := NoteSequence{_bytes: unsafe.Slice((*byte)(unsafe.Pointer(_a0)), _a2), _count: uint32(_a1)}\n"
    "\t_answer = C.xy_flow(_f._fn(_v0, uint32(_a3)))\n",
    "func Replay(notes NoteSequence) error {\n"
    "\t_raw := C.xy_replay((*C.xy_note_head)(_data(notes._bytes)), C.uint32_t(notes._count), "
    "C.uint32_t(len(notes._bytes)))\n",
)


class Unions(unittest.TestCase):
    def test_a_listed_union_renders_each_form_the_spec_states(self) -> None:
        text = package(UNIONS)
        for form in UNION_FORMS:
            with self.subTest(form=form):
                self.assertIn(form, text)

    def test_the_sequence_counts_by_the_unions_count_type(self) -> None:
        text = package(UNIONS_U16)
        for form in (
            "\t_count uint16\n",
            "func (_s NoteSequence) Count() uint16 {\n",
            "func (_s NoteSequence) At(index uint16) (NoteRecord, error) {\n",
            "_count: uint16(_a1)}\n",
            "C.uint16_t(notes._count), C.uint16_t(len(notes._bytes))",
            "\tIndex  uint32\n\tOffset uint32\n",
        ):
            with self.subTest(form=form):
                self.assertIn(form, text)

    def test_a_u8_tag_prefix_is_held_to_its_layout_and_read_by_name(self) -> None:
        self.assertEqual(emit_binding_go.validate(load(UNION_U8_TAG)), [])
        text = package(UNION_U8_TAG)
        for form in (
            "var _ [0]struct{} = [unsafe.Sizeof(NoteHead{}) - 4]struct{}{}\n",
            "var _ [0]struct{} = [unsafe.Alignof(NoteHead{}) - 2]struct{}{}\n",
            "\t\tswitch _head.Kind {\n",
            "\t\tcase int(_head.Size) != _size:\n",
            "\t\tcase _head.Kind == 1:\n",
        ):
            with self.subTest(form=form):
                self.assertIn(form, text)

    def test_a_union_counted_by_u64_widens_the_errors_position(self) -> None:
        self.assertIn("\tIndex  uint64\n\tOffset uint64\n", package(UNIONS_U64))

    def test_an_optional_list_passes_null_for_the_zero_sequence(self) -> None:
        optional = mutate(UNIONS, NOTES, NOTES.replace(" }", ", _optional = true }"))
        self.assertIn("(*C.xy_note_head)(_data_or_nil(notes._bytes))", package(optional))

    def test_a_union_without_the_property_renders_its_structs_alone(self) -> None:
        text = package(UNION_NOT_LISTED)
        self.assertIn("type NoteMark struct {\n", text)
        for name in ("UnionClause", "UnionError", "NoteSequence", "NoteRecord", "NoteWalker", "_note_record"):
            with self.subTest(name=name):
                self.assertNotIn(name, text)


if __name__ == "__main__":
    unittest.main()
