import unittest

from langxyne import naming
from langxyne.emitters import EMITTERS
from langxyne.tests.support import UNIONS, load


class LibraryFileName(unittest.TestCase):
    def test_each_platform_and_link_mode_names_the_file(self) -> None:
        # SPEC.md's table, for the library named `xy`
        for platform, shared, static in (
            ("linux", "libxy.so", "libxy.a"),
            ("macos", "libxy.dylib", "libxy.a"),
            ("windows", "xy.dll", "libxy.a"),
        ):
            for link, expected in ((naming.SHARED, shared), (naming.STATIC, static)):
                with self.subTest(platform=platform, link=link):
                    self.assertEqual(naming.library_file_name("xy", platform=platform, link=link), expected)

    def test_each_host_platform_has_a_file_name_and_a_loader_variable(self) -> None:
        for platform in naming.HOST_PLATFORMS.values():
            with self.subTest(platform=platform):
                for link in naming.LINK_MODES:
                    naming.library_file_name("xy", platform=platform, link=link)
                self.assertIn(platform, naming.LOADER_PATH_VARIABLES)

    def test_every_table_platform_has_a_goos(self) -> None:
        self.assertEqual(set(naming.GO_OS), set(naming.HOST_PLATFORMS.values()))


class LibraryVariable(unittest.TestCase):
    def test_the_upper_cased_namespace_then_library(self) -> None:
        self.assertEqual(naming.library_variable("xy"), "XY_LIBRARY")


# Each integer type's range, stated apart from the arithmetic that computes it.
INTEGER_RANGES = (
    ("i8", -128, 127),
    ("u8", 0, 255),
    ("i16", -32768, 32767),
    ("u16", 0, 65535),
    ("i32", -2147483648, 2147483647),
    ("u32", 0, 4294967295),
    ("i64", -9223372036854775808, 9223372036854775807),
    ("u64", 0, 18446744073709551615),
)


class IntegerRange(unittest.TestCase):
    def test_each_integer_type_holds_its_range(self) -> None:
        for type_name, low, high in INTEGER_RANGES:
            with self.subTest(type_name=type_name):
                self.assertEqual(naming.integer_range(type_name), (low, high))


class GoExportSymbol(unittest.TestCase):
    def test_the_namespace_then_two_underscores_then_the_callback_type(self) -> None:
        # a function's C name has one underscore after the namespace and a name never begins with one
        self.assertEqual(naming.go_export_symbol("xy", "on_batch"), "xy__on_batch")


def union_spellings(namespace: str, union: str) -> dict[str, list[str]]:
    """Each output rendering a union's list, by its token, and the names `naming` gives it for
    `union` and the clause enum in that output's spelling."""
    clauses = [name for name, _ in naming.UNION_CLAUSES]
    shared = [naming.UNION_CLAUSE_TYPE, naming.UNION_ERROR, naming.union_sequence(union)]
    rust = [*shared, naming.rust_union_ref(union), naming.rust_union_records(union)]
    return {
        "h": [
            naming.type_name(namespace, naming.UNION_CLAUSE),
            naming.const_name(namespace, naming.UNION_OK),
            *(naming.const_name(namespace, naming.union_clause_entry(k)) for k in clauses),
            naming.function_name(namespace, naming.UNION_CLAUSE_TEXT),
            *(naming.union_helper(namespace, union, h) for h in naming.UNION_HELPERS),
        ],
        "hpp": [*shared, naming.UNION_CLAUSE_TEXT],
        "rs": rust,
        "abi_rs": [*rust, naming.rust_union_buf(union), naming.rust_union_buf_mark(union)],
        "go": [
            *shared,
            *(naming.go_enum_entry(naming.UNION_CLAUSE, k) for k in clauses),
            naming.go_union_record(union),
            naming.go_union_walker(union),
            naming.go_union_marker(union),
        ],
        "py": [naming.UNION_ERROR, naming.union_sequence(union)],
        "lua": [naming.lua_union_records(union), naming.lua_union_at(union), naming.lua_union_shape(union)],
    }


class UnionNames(unittest.TestCase):
    def test_each_output_renders_the_clause_texts_and_the_union_names_from_naming(self) -> None:
        api = load(UNIONS)
        for token, names in union_spellings(api.namespace, api.unions[0].name).items():
            text = EMITTERS[token].emit(api, source_name="xy_api.adef.toml", name="xy_api", project="xy")
            for name in names:
                with self.subTest(token=token, name=name):
                    self.assertIn(name, text)
            for clause_text in naming.UNION_CLAUSE_TEXTS.values():
                with self.subTest(token=token, text=clause_text):
                    self.assertIn(clause_text, text)


if __name__ == "__main__":
    unittest.main()
