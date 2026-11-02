import unittest
from pathlib import Path

from langxyne import __main__ as langxyne_main
from langxyne.emitters import EMITTERS
from langxyne.tests.support import FIXTURE, KITCHEN_SINK, TWO_BAD_RETURNS, load, mutate, run_main
from langxyne.tests.support_cli import EVERY_OUTPUT, GenerationCase, output_paths
from langxyne.tests.support_xy32 import FIXTURE32


class Outputs(GenerationCase):
    def test_tokens_are_the_registry_keys_and_each_names_its_path(self) -> None:
        self.assertEqual(
            langxyne_main.TOKENS,
            ("h", "hpp", "lua", "stub_cpp", "rs", "abi_rs", "stub_rs", "go", "py", "wasm_rs", "node"),
        )
        self.assertEqual(tuple(EMITTERS), langxyne_main.TOKENS)
        self.assertEqual(
            output_paths(name="xy_api", project="xy"),
            {
                "h": Path("include/xy/xy_api.h"),
                "hpp": Path("include/xy/xy_api.hpp"),
                "lua": Path("lua/xy_api.lua"),
                "stub_cpp": Path("stub/xy_api.cpp"),
                "rs": Path("rust/xy_api.rs"),
                "abi_rs": Path("rust/xy_api_abi.rs"),
                "stub_rs": Path("stub/xy_api.rs"),
                "go": Path("go/xy_api/xy_api.go"),
                "py": Path("python/xy_api.py"),
                "wasm_rs": Path("rust/xy_api_wasm.rs"),
                "node": Path("node/xy_api.mjs"),
            },
        )

    def test_every_label(self) -> None:
        self.assertEqual(
            [e.LABEL for e in EMITTERS.values()],
            ["header", "wrapper", "lua", "stub", "rust", "rust_abi", "rust_stub", "go", "python", "rust_wasm", "node"],
        )

    def test_writes_only_the_selected_outputs(self) -> None:
        paths = output_paths(name="xy_api", project="xy")
        for text, flags, selected in (
            (FIXTURE, ("--outputs=hpp,stub_cpp",), {"hpp", "stub_cpp"}),
            (FIXTURE, ("--outputs=lua",), {"lua"}),
            (FIXTURE, ("--outputs=stub_rs",), {"stub_rs"}),
            (FIXTURE, ("--outputs=abi_rs",), {"abi_rs"}),
            (FIXTURE, ("--outputs=rs",), {"rs"}),
            (FIXTURE, ("--outputs=go",), {"go"}),
            (FIXTURE, ("--outputs=py",), {"py"}),
            (FIXTURE32, ("--outputs=py,rs,stub_rs,abi_rs,go,stub_cpp,h,lua,hpp,wasm_rs,node",), set(paths)),
            # absent, every output but the shim and the Node binding, so a 64-bit definition generates
            (KITCHEN_SINK, (), set(paths) - {"wasm_rs", "node"}),
        ):
            with self.subTest(flags=flags):
                code, stderr, generated, _ = self.generate(text, *flags)
                self.assertEqual(code, 0, stderr)
                written = {token for token, relpath in paths.items() if (generated / relpath).exists()}
                self.assertEqual(written, selected)
                expected = [generated / paths[t] for t in selected]
                expected += [
                    generated / p for t in selected for p, _ in EMITTERS[t].companions(load(text), name="xy_api")
                ]
                self.assertEqual(
                    sorted(p for p in generated.rglob("*") if p.is_file()),
                    sorted(expected),
                )

    def test_unknown_or_repeated_token_is_a_usage_error_writing_nothing(self) -> None:
        for flag, message in (
            (
                "--outputs=h,js",
                "unknown output 'js' (valid: h, hpp, lua, stub_cpp, rs, abi_rs, stub_rs, go, py, wasm_rs, node)",
            ),
            (
                "--outputs=",
                "unknown output '' (valid: h, hpp, lua, stub_cpp, rs, abi_rs, stub_rs, go, py, wasm_rs, node)",
            ),
            (
                "--outputs=h,lua,h",
                "output 'h' repeated (valid: h, hpp, lua, stub_cpp, rs, abi_rs, stub_rs, go, py, wasm_rs, node)",
            ),
        ):
            with self.subTest(flag=flag):
                code, stderr, generated, _ = self.generate(FIXTURE, flag)
                self.assertEqual(code, 2)
                self.assertIn(message, stderr)
                self.assertFalse(generated.exists())

    def test_only_the_selected_emitters_validate(self) -> None:
        lua_keyword = mutate(FIXTURE, "bytes = ", "end = ")
        code, stderr, *_ = self.generate(lua_keyword, "--outputs=h,hpp")
        self.assertEqual(code, 0, stderr)
        code, stderr, generated, _ = self.generate(lua_keyword, "--outputs=h,lua")
        self.assertEqual(code, 2)
        self.assertIn("lua: struct.stats.end: 'end' is a Lua keyword", stderr)
        self.assertFalse(generated.exists())

    def test_shared_objection_names_only_the_selected_emitters(self) -> None:
        code, stderr, *_ = self.generate(mutate(FIXTURE, "bytes = ", "int = "), "--outputs=h,stub_cpp")
        self.assertEqual(code, 2)
        self.assertEqual(stderr.count("\n"), 1)
        self.assertIn(": header, stub: struct.stats.int: 'int' is a C keyword\n", stderr)

    def test_library_is_required_only_for_the_outputs_that_load_or_link_it(self) -> None:
        no_library = mutate(FIXTURE, '_bound_library = "xy"\n', "")
        code, stderr, *_ = self.generate(no_library, "--outputs=h,hpp,stub_cpp,abi_rs,stub_rs")
        self.assertEqual(code, 0, stderr)
        for flag, labels in (
            ("--outputs=lua", "lua"),
            ("--outputs=rs", "rust"),
            ("--outputs=go", "go"),
            ("--outputs=py", "python"),
            ("--outputs=lua,rs", "lua, rust"),
        ):
            with self.subTest(flag=flag):
                code, stderr, generated, _ = self.generate(no_library, flag)
                self.assertEqual(code, 2)
                self.assertIn(f": {labels}: no library named; set _general._bound_library or --library\n", stderr)
                self.assertFalse(generated.exists())

    def test_a_static_link_is_refused_by_the_lua_python_and_node_modules_alone(self) -> None:
        code, stderr, generated, definition = self.generate(FIXTURE32, "--link=static", EVERY_OUTPUT)
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"langxyne: {definition}: lua: --link=static: the Lua module loads its library at run time and cannot "
                "link it statically",
                f"langxyne: {definition}: python: --link=static: the Python module loads its library at run time and "
                "cannot link it statically",
                f"langxyne: {definition}: node: --link=static: the Node binding loads its module at run time and "
                "cannot link it statically",
            ],
        )
        self.assertFalse(generated.exists())
        code, stderr, *_ = self.generate(FIXTURE, "--link=static", "--outputs=h,hpp")
        self.assertEqual(code, 0, stderr)

    def test_a_static_link_reaches_the_rust_binding(self) -> None:
        code, stderr, generated, _ = self.generate(FIXTURE, "--link=static", "--outputs=rs")
        self.assertEqual(code, 0, stderr)
        rust_text = (generated / "rust" / "xy_api.rs").read_text(encoding="utf-8")
        self.assertIn('#[link(name = "xy", kind = "static", modifiers = "-bundle")]', rust_text)

    def test_unknown_link_mode_is_a_usage_error_writing_nothing(self) -> None:
        code, stderr, generated, _ = self.generate(FIXTURE, "--link=dynamic")
        self.assertEqual(code, 2)
        self.assertIn("--link: invalid choice: 'dynamic'", stderr)
        self.assertFalse(generated.exists())


class Check(GenerationCase):
    """SPEC "Invocation", `--check`."""

    def generated(self) -> tuple[Path, Path]:
        """Generate FIXTURE's default outputs; return (generated directory, definition path)."""
        code, stderr, generated, definition = self.generate(FIXTURE)
        self.assertEqual(code, 0, stderr)
        return generated, definition

    def check(self, definition: Path, generated: Path, *flags: str) -> tuple[int, str]:
        code, _, stderr = run_main(
            [str(definition), "--generated", str(generated), "--project", "xy", "--check", *flags]
        )
        return code, stderr

    def test_every_output_matching_exits_0_with_one_line(self) -> None:
        generated, definition = self.generated()
        code, stderr = self.check(definition, generated)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr.count("\n"), 1)

    def test_an_edited_output_exits_1_naming_it_alone_and_stays_edited(self) -> None:
        generated, definition = self.generated()
        relpath = output_paths(name="xy_api", project="xy")["h"]
        edited = (generated / relpath).read_text(encoding="utf-8") + " "
        (generated / relpath).write_text(edited, encoding="utf-8")
        code, stderr = self.check(definition, generated)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, f"langxyne: xy_api: {relpath} differs\n")
        self.assertEqual((generated / relpath).read_text(encoding="utf-8"), edited)

    def test_a_missing_output_exits_1_naming_it_missing(self) -> None:
        generated, definition = self.generated()
        relpath = output_paths(name="xy_api", project="xy")["rs"]
        (generated / relpath).unlink()
        code, stderr = self.check(definition, generated)
        self.assertEqual(code, 1)
        self.assertEqual(stderr, f"langxyne: xy_api: {relpath} is missing\n")
        self.assertFalse((generated / relpath).exists())

    def test_an_unselected_output_is_not_compared(self) -> None:
        generated, definition = self.generated()
        paths = output_paths(name="xy_api", project="xy")
        (generated / paths["rs"]).unlink()
        code, stderr = self.check(definition, generated, "--outputs=h")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, f"langxyne: xy_api: {paths['h']} under {generated} match\n")

    def test_line_endings_are_aside(self) -> None:
        generated, definition = self.generated()
        path = generated / output_paths(name="xy_api", project="xy")["h"]
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\r\n")
        code, stderr = self.check(definition, generated)
        self.assertEqual(code, 0, stderr)

    def test_an_unreadable_output_exits_2_naming_it(self) -> None:
        generated, definition = self.generated()
        relpath = output_paths(name="xy_api", project="xy")["h"]
        (generated / relpath).unlink()
        (generated / relpath).mkdir()
        code, stderr = self.check(definition, generated)
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith("langxyne: "), stderr)
        self.assertIn(str(relpath), stderr)

    def test_a_refused_definition_exits_2_with_its_objections_and_writes_nothing(self) -> None:
        code, stderr, generated, definition = self.generate(TWO_BAD_RETURNS, "--check")
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.splitlines(),
            [
                f"langxyne: {definition}: function.destroy_port._return: unknown typed_const 'nope'",
                f"langxyne: {definition}: function.spend._return: unknown typed_const 'gone'",
            ],
        )
        self.assertFalse(generated.exists())


if __name__ == "__main__":
    unittest.main()
