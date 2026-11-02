"""What the CLI's test modules share: a program run under a bound, a file written, each output's
path, and generation of a definition under a fresh directory."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from langxyne import __main__ as langxyne_main
from langxyne.emitters import EMITTERS
from langxyne.tests.support import run_main

# the bound a hung generated program meets, so `just test` cannot hang
RUN_TIMEOUT_S = 300

# the flag selecting every output, the shim and the Node binding among them
EVERY_OUTPUT = "--outputs=" + ",".join(langxyne_main.TOKENS)


def run(args: list[str | Path], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("timeout", RUN_TIMEOUT_S)
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kwargs)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def output_paths(*, name: str, project: str) -> dict[str, Path]:
    """Every output token and its path relative to the generated directory, as its
    emitter states it."""
    return {token: emitter.output_path(name=name, project=project) for token, emitter in EMITTERS.items()}


class GenerationCase(unittest.TestCase):
    def generate(self, text: str, *flags: str, file_name: str = "xy_api.adef.toml") -> tuple[int, str, Path, Path]:
        """Run generation of `text`, written as `file_name` under a fresh directory; return
        (exit code, stderr, generated directory, definition path). The directory is removed
        at the end of the test."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        definition = Path(tmp.name) / file_name
        definition.write_text(text, encoding="utf-8")
        generated = Path(tmp.name) / "generated"
        code, _, stderr = run_main([str(definition), "--generated", str(generated), "--project", "xy", *flags])
        return code, stderr, generated, definition
