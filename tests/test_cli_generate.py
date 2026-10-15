import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from langxyne import __main__ as langxyne_main
from langxyne.emitters import (
    emit_abi_rs,
    emit_binding_cpp,
    emit_binding_go,
    emit_binding_lua,
    emit_binding_node,
    emit_binding_py,
    emit_binding_rs,
    emit_c,
    emit_stub_cpp,
    emit_stub_rs,
    emit_wasm_rs,
)
from langxyne.tests.support import (
    FIXTURE,
    KITCHEN_SINK,
    TWO_BAD_RETURNS,
    UNION_REFUSALS,
    load,
    mutate,
    run_main,
)
from langxyne.tests.support_cli import EVERY_OUTPUT, GenerationCase, output_paths, run, write
from langxyne.tests.support_xy32 import FIXTURE32

# Definition file names a banner cannot carry: a quote, which ends a string, and a line break,
# which ends a line comment.
BANNER_REFUSED_FILE_NAMES = ('x"y.adef.toml', "x\ny.adef.toml")

# Definitions the schema pass refuses, each with the first objection the loader has to it alone.
SCHEMA_REFUSED = (
    (
        mutate(KITCHEN_SINK, 'id = "u32"\nlabel = "text"', 'id = "u32"\nlabel = { _type = "text", _max = 5 }'),
        "struct.entry.label: unknown key(s) _max",
    ),
    (
        mutate(FIXTURE, 'bytes = "u64"', 'bytes = { _type = "u64", _maxx = 5 }'),
        "struct.stats.bytes: unknown key(s) _maxx",
    ),
    (UNION_REFUSALS["a member's unknown key"][0], "union.note.line: unknown key(s) _ref"),
)

# The CLI in a fresh interpreter to which jsonschema is unimportable.
WITHOUT_JSONSCHEMA = (
    'import sys; sys.modules["jsonschema"] = None; from langxyne.__main__ import main; sys.exit(main(sys.argv[1:]))'
)


class Generate(GenerationCase):
    def test_writes_every_output_equal_to_its_emitter_and_reports_one_line(self) -> None:
        code, stderr, generated, _ = self.generate(FIXTURE32, EVERY_OUTPUT)
        self.assertEqual(code, 0)
        api = load(FIXTURE32)
        modules = {
            "h": emit_c,
            "hpp": emit_binding_cpp,
            "lua": emit_binding_lua,
            "stub_cpp": emit_stub_cpp,
            "rs": emit_binding_rs,
            "abi_rs": emit_abi_rs,
            "stub_rs": emit_stub_rs,
            "go": emit_binding_go,
            "py": emit_binding_py,
            "wasm_rs": emit_wasm_rs,
            "node": emit_binding_node,
        }
        for token, relpath in output_paths(name="xy_api", project="xy").items():
            with self.subTest(output=str(relpath)):
                expected = modules[token].emit(api, source_name="xy_api.adef.toml", name="xy_api", project="xy")
                self.assertEqual((generated / relpath).read_text(encoding="utf-8"), expected)
                self.assertIn(str(relpath), stderr)
        self.assertEqual(stderr.count("\n"), 1)

    def test_definition_name_must_end_in_the_suffix(self) -> None:
        code, stderr, generated, definition = self.generate(FIXTURE, file_name="xy_api.toml")
        self.assertEqual(code, 2)
        self.assertEqual(stderr, f"langxyne: {definition}: file name must end in .adef.toml\n")
        self.assertFalse(generated.exists())

    def test_name_not_the_file_name_names_every_output(self) -> None:
        code, stderr, generated, _ = self.generate(FIXTURE, file_name="anything.adef.toml")
        self.assertEqual(code, 0, stderr)
        paths = output_paths(name="xy_api", project="xy")
        self.assertEqual(
            sorted(p for p in generated.rglob("*") if p.is_file()),
            sorted([generated / paths[t] for t in langxyne_main.DEFAULT_TOKENS] + [generated / "lua" / "i64.lua"]),
        )

    def test_name_is_a_required_identifier(self) -> None:
        for text, message in (
            (mutate(FIXTURE, '_name = "xy_api"\n', ""), "schema: /_general: '_name' is a required property"),
            (
                mutate(FIXTURE, '_name = "xy_api"', '_name = "xy-api"'),
                "schema: /_general/_name: 'xy-api' does not match '^[A-Za-z][A-Za-z0-9_]*$' (line 3: _name = \"xy-api\")",
            ),
        ):
            with self.subTest(message=message):
                code, stderr, generated, definition = self.generate(text)
                self.assertEqual(code, 2)
                self.assertEqual(stderr, f"langxyne: {definition}: {message}\n")
                self.assertFalse(generated.exists())

    def test_not_implemented_exits_2_saying_so(self) -> None:
        code, stderr, generated, definition = self.generate(mutate(FIXTURE, "max_units = 16", "max_units = 1.5"))
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr,
            f"langxyne: {definition}: schema: /untyped_const/0/max_units: 1.5 is not valid under any of the given schemas (line 15: max_units = 1.5)\n",
        )
        self.assertFalse(generated.exists())

    def test_max_on_a_text_field_is_an_unknown_key_exit_2_writing_nothing(self) -> None:
        code, stderr, generated, definition = self.generate(
            mutate(KITCHEN_SINK, 'id = "u32"\nlabel = "text"', 'id = "u32"\nlabel = { _type = "text", _max = 5 }')
        )
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr,
            f"langxyne: {definition}: schema: /struct/0/entry/label: {{'_type': 'text', '_max': 5}} is not valid under"
            ' any of the given schemas (line 102: label = { _type = "text", _max = 5 })\n',
        )
        self.assertFalse(generated.exists())

    def test_without_jsonschema_the_loader_alone_refuses_what_the_schema_does(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
        for text, message in SCHEMA_REFUSED:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                definition = write(Path(tmp) / "xy_api.adef.toml", text)
                generated = Path(tmp) / "generated"
                argv = [definition, "--generated", generated, "--project", "xy"]
                result = run([sys.executable, "-c", WITHOUT_JSONSCHEMA, *argv], env=env)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stderr.splitlines()[0], f"langxyne: {definition}: {message}")
                self.assertFalse(generated.exists())

    def test_no_schema_skips_the_schema_pass_leaving_the_loaders_objection(self) -> None:
        for text, message in SCHEMA_REFUSED:
            with self.subTest(message=message):
                code, stderr, generated, definition = self.generate(text, "--no-schema")
                self.assertEqual(code, 2)
                self.assertEqual(stderr.splitlines()[0], f"langxyne: {definition}: {message}")
                self.assertFalse(generated.exists())
                code, stdout, stderr = run_main(["gendeps", "--no-schema", str(definition)])
                self.assertEqual((code, stdout), (2, ""))
                self.assertEqual(stderr.splitlines()[0], f"langxyne: {definition}: {message}")

    def test_the_schema_refuses_a_union_members_unknown_key_naming_its_pointer(self) -> None:
        text = UNION_REFUSALS["a member's unknown key"][0]
        line = next(n for n, t in enumerate(text.splitlines(), 1) if t.startswith("line = "))
        code, stderr, generated, definition = self.generate(text)
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"langxyne: {definition}: schema: /union/0/note/line: Additional properties are not allowed ('_ref' was"
                f" unexpected) (line {line}: {text.splitlines()[line - 1]})"
            ],
        )
        self.assertFalse(generated.exists())

    def test_every_union_refusal_is_the_loaders_under_no_schema(self) -> None:
        for rule, (text, expected) in UNION_REFUSALS.items():
            with self.subTest(rule=rule):
                code, stderr, generated, definition = self.generate(text, "--no-schema")
                self.assertEqual(code, 2)
                self.assertEqual(stderr.splitlines(), [f"langxyne: {definition}: {o}" for o in expected])
                self.assertFalse(generated.exists())

    def test_definition_error_exit_2_writes_nothing(self) -> None:
        code, stderr, generated, definition = self.generate("")
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith(f"langxyne: {definition}: "))
        self.assertEqual(stderr.count("\n"), 1)
        self.assertFalse(generated.exists())

    def test_every_loader_objection_is_its_own_line_and_nothing_written(self) -> None:
        code, stderr, generated, definition = self.generate(TWO_BAD_RETURNS)
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"langxyne: {definition}: function.destroy_port._return: unknown typed_const 'nope'",
                f"langxyne: {definition}: function.spend._return: unknown typed_const 'gone'",
            ],
        )
        self.assertFalse(generated.exists())

    def test_every_emitter_objection_is_reported_in_one_run_and_nothing_written(self) -> None:
        text = mutate(mutate(FIXTURE, "bytes = ", "int = "), 'unit = "u32"', 'result = "u32"')
        code, stderr, generated, definition = self.generate(text)
        self.assertEqual(code, 2)
        # an objection shared by several emitters is one line naming them, in order of first appearance
        self.assertEqual(
            stderr.splitlines(),
            [
                f"langxyne: {definition}: header, wrapper, stub: struct.stats.int: 'int' is a C keyword",
                f"langxyne: {definition}: wrapper, lua, rust: function.open_port.result: 'result' is a name the generated code uses",
            ],
        )
        self.assertFalse(generated.exists())

    def test_library_flag_overrides_the_definition(self) -> None:
        code, _, generated, _ = self.generate(FIXTURE, "--library", "z")
        self.assertEqual(code, 0)
        lua_text = (generated / "lua" / "xy_api.lua").read_text(encoding="utf-8")
        self.assertIn('ffi.load("z")', lua_text)
        rust_text = (generated / "rust" / "xy_api.rs").read_text(encoding="utf-8")
        self.assertIn('#[link(name = "z")]', rust_text)

    def test_project_flag_is_held_to_the_literal_text_rule_and_must_name_a_directory(self) -> None:
        literal = "--project must not contain '\"', '\\' or a control character"
        for project, message in (('x"y', literal), ("x\\y", literal), ("", "--project must name a directory")):
            with self.subTest(project=project):
                code, stderr, generated, definition = self.generate(FIXTURE, "--project", project)
                self.assertEqual(code, 2)
                self.assertEqual(stderr, f"langxyne: {definition}: {message}\n")
                self.assertFalse(generated.exists())

    def test_library_flag_gets_the_definition_library_check_and_must_name_a_library(self) -> None:
        # the definition names no library, and a refused flag draws no objection of its absence
        no_library = mutate(FIXTURE, '_bound_library = "xy"\n', "")
        rule = "is not a library name: ASCII letters, digits, '_' and '-', not beginning with '-'"
        for library, message in (
            ("libz.so", "--library: 'libz.so' is a file name; name the library 'z'"),
            ("z/y", f"--library: 'z/y' {rule}"),
            ("", "--library must name a library"),
        ):
            with self.subTest(library=library):
                code, stderr, generated, definition = self.generate(no_library, f"--library={library}")
                self.assertEqual(code, 2)
                self.assertEqual(stderr, f"langxyne: {definition}: {message}\n")
                self.assertFalse(generated.exists())

    def test_a_library_flag_objection_is_reported_beside_the_definitions(self) -> None:
        code, stderr, generated, definition = self.generate(TWO_BAD_RETURNS, "--library", "")
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"langxyne: {definition}: function.destroy_port._return: unknown typed_const 'nope'",
                f"langxyne: {definition}: function.spend._return: unknown typed_const 'gone'",
                f"langxyne: {definition}: --library must name a library",
            ],
        )
        self.assertFalse(generated.exists())
        code, stderr, generated, definition = self.generate(mutate(FIXTURE, "bytes = ", "int = "), "--library", "")
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"langxyne: {definition}: header, wrapper, stub: struct.stats.int: 'int' is a C keyword",
                f"langxyne: {definition}: --library must name a library",
            ],
        )
        self.assertFalse(generated.exists())

    def test_missing_library_exits_2_with_nothing_written(self) -> None:
        code, stderr, generated, _ = self.generate(mutate(FIXTURE, '_bound_library = "xy"\n', ""))
        self.assertEqual(code, 2)
        self.assertIn(": lua, rust, go, python: no library named; set _general._bound_library or --library\n", stderr)
        self.assertFalse(generated.exists())

    def test_the_go_output_needs_gofmt_and_without_it_nothing_is_written(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": ""}):
            code, stderr, generated, _ = self.generate(FIXTURE, "--outputs=h,go")
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "langxyne: gofmt is required for the Go output and was not found on PATH\n")
        self.assertFalse(generated.exists())

    def test_rust_outputs_need_rustfmt_and_without_it_nothing_is_written(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": ""}):
            for outputs in ("h,stub_rs", "rs,lua"):
                with self.subTest(outputs=outputs):
                    code, stderr, generated, _ = self.generate(FIXTURE, f"--outputs={outputs}")
                    self.assertEqual(code, 2)
                    self.assertEqual(
                        stderr, "langxyne: rustfmt is required for the Rust outputs and was not found on PATH\n"
                    )
                    self.assertFalse(generated.exists())

    def test_a_failing_rustfmt_exits_2_with_its_error_and_nothing_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rustfmt = Path(tmp) / "rustfmt"
            rustfmt.write_text("#!/bin/sh\necho 'rustfmt: cannot format' >&2\nexit 1\n", encoding="utf-8")
            rustfmt.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": tmp}):
                code, stderr, generated, _ = self.generate(FIXTURE)
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "langxyne: rustfmt failed on a Rust output: rustfmt: cannot format\n")
        self.assertFalse(generated.exists())

    def test_every_output_starts_with_a_generated_banner_naming_the_source(self) -> None:
        code, _, generated, _ = self.generate(FIXTURE32, EVERY_OUTPUT)
        self.assertEqual(code, 0)
        for token, relpath in output_paths(name="xy_api", project="xy").items():
            first_line = (generated / relpath).read_text(encoding="utf-8").splitlines()[0]
            with self.subTest(output=str(relpath)):
                if token == "go":
                    # the form Go's tools recognise
                    self.assertEqual(first_line, "// Code generated by langxyne from xy_api.adef.toml; DO NOT EDIT.")
                else:
                    self.assertIn("GENERATED by langxyne from xy_api.adef.toml", first_line)

    def test_a_definition_file_name_no_banner_can_carry_exits_2_writing_nothing(self) -> None:
        for file_name in BANNER_REFUSED_FILE_NAMES:
            with self.subTest(file_name=file_name):
                code, stderr, generated, definition = self.generate(FIXTURE, file_name=file_name)
                self.assertEqual(code, 2)
                self.assertEqual(
                    stderr,
                    f"langxyne: {definition}: the definition's file name must not contain '\"', '\\' or a control "
                    "character\n",
                )
                self.assertFalse(generated.exists())


if __name__ == "__main__":
    unittest.main()
