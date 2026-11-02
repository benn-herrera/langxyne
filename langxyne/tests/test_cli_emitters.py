import inspect
import io
import os
import re
import tokenize
import unittest
from pathlib import Path

from langxyne.emitters import EMITTERS
from langxyne.tests.support import UNIONS, load


class EmitterShape(unittest.TestCase):
    def test_every_emitter_module_defines_only_the_protocol(self) -> None:
        for token, emitter in EMITTERS.items():
            with self.subTest(token=token):
                defined_here = {
                    name
                    for name, value in vars(emitter).items()
                    if not name.startswith("_")
                    and not inspect.ismodule(value)
                    and getattr(value, "__module__", emitter.__name__) == emitter.__name__
                }
                self.assertEqual(defined_here, {"LABEL", "validate", "output_path", "emit", "companions"})


class Unions(unittest.TestCase):
    def test_every_emitter_renders_a_union_or_refuses_it_by_name(self) -> None:
        api = load(UNIONS)
        for token, emitter in EMITTERS.items():
            with self.subTest(token=token):
                self.assertIn(emitter.validate(api), ([], [f"{emitter.LABEL}: union 'note' is not implemented"]))


def generator_sources() -> dict[str, str]:
    """The text of every `*.py` of the package outside `tests` and `.venv`, by its path
    relative to the package."""
    package = Path(__file__).resolve().parents[1]
    sources = {}
    for directory, dirnames, filenames in os.walk(package):
        dirnames[:] = [d for d in dirnames if d not in ("tests", ".venv")]
        for filename in filenames:
            if filename.endswith(".py"):
                path = Path(directory) / filename
                sources[path.relative_to(package).as_posix()] = path.read_text(encoding="utf-8")
    return sources


class HostIndependence(unittest.TestCase):
    """SPEC "The library": the same definition and flags generate the same text on every host."""

    def test_no_module_reads_the_host_platform(self) -> None:
        # code tokens, so the text an emitter renders, a string literal, is not a read; but an
        # f-string's replacement field is code, which Python 3.11 tokenizes as one STRING token
        reads = {("sys", ".", "platform"), ("os", ".", "name")}
        imports = {("import", "os"), ("import", "platform"), ("from", "os"), ("from", "platform")}
        read_in_text = re.compile(r"(?<![\w.])(?:sys\.platform|os\.name)\b")
        found = []
        for path, text in generator_sources().items():
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            code = [t for t in tokens if t.type in (tokenize.NAME, tokenize.OP)]
            for i, token in enumerate(code):
                words = tuple(t.string for t in code[i : i + 3])
                if words in reads or words[:2] in imports:
                    found.append(f"{path}:{token.start[0]}: {' '.join(words)}")
            for token in tokens:
                prefix = re.match(r"\w*", token.string).group()
                if token.type == tokenize.STRING and "f" in prefix.lower() and read_in_text.search(token.string):
                    found.append(f"{path}:{token.start[0]}: {token.string}")
        self.assertEqual(found, [])

    def test_only_naming_spells_a_library_file(self) -> None:
        file_name = re.compile(r"\.(?:so|dylib|dll)\b|\.a\"")
        self.assertEqual({path for path, text in generator_sources().items() if file_name.search(text)}, {"naming.py"})


if __name__ == "__main__":
    unittest.main()
