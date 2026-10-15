# PROJECT := "langxyne"

export PYTHONDONTWRITEBYTECODE := "1"

default:
    @just --list

# Venv layout differs by OS: POSIX puts executables in .venv/bin, Windows in
# .venv/Scripts with .exe suffixes. Resolved here via just's os() builtin.

# PROJECT_ROOT defined by consumer before importing.
VENV := justfile_dir() / ".venv"
PYBIN := if os() == "windows" { "Scripts" } else { "bin" }
EXE := if os() == "windows" { ".exe" } else { "" }
VENV_PYTHON := VENV / PYBIN / "python" + EXE

# Lazy: if the venv's python already exists this is a no-op; a half-built
# venv is repaired by deleting .venv and re-running.
_venv:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ ! -x "{{VENV_PYTHON}}" ]]; then
        python3 -m venv "{{VENV}}"
        "{{VENV_PYTHON}}" -m pip install pip pytest isort black flake8 jsonschema==4.26.0 --upgrade
    fi

[positional-arguments]
[doc("run all tests")]
test *args: _venv
  "{{VENV_PYTHON}}" -m pytest tests "$@"

[doc("run the whole compiled-bindings loop in shell: the C++ and Rust fakes built, the consumers compiled and run against each fake, every must-not-compile build refused at its stderr needle, every byte golden compared; XY_PYTHON names the venv interpreter")]
bindings-test: _venv
	#!/usr/bin/env bash
	set -uo pipefail
	XY_PYTHON="{{VENV_PYTHON}}" "{{justfile_dir() / "tests" / "run-bindings.sh"}}"

[doc("run the compiled-bindings loop (just bindings-test), then, only if it passes, rewrite tests/fixtures/expected_*.rs from support.KITCHEN_SINK; each emitter's validate gates the rewrite")]
regenerate-expected: _venv bindings-test
  PYTHONPATH="{{parent_directory(justfile_dir())}}" "{{VENV_PYTHON}}" "{{justfile_dir() / "tests" / "regenerate_expected.py"}}"

FLAKE8_IGNORE := "E122,E201,E202,E203,E225,E226,E228,E261,E265,E302,E303,E501,E704,E731,W291,W293,W391,W503"
# `*paths` arrives as "$@", each path one word; none given formats the package.
[positional-arguments]
[doc("black-format, isort, flake8 the shipped python packages and the generator, or the given path(s) in place of all four")]
pre-commit *paths: _venv
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ "$#" -eq 0 ]]; then
        black_isort_paths=(.)
        flake8_paths=(.)
    else
        black_isort_paths=("$@")
        flake8_paths=("$@")
    fi
    "{{VENV_PYTHON}}" -m black --line-length=120 "${black_isort_paths[@]}"
    "{{VENV_PYTHON}}" -m isort --profile black --line-length 120 "${black_isort_paths[@]}"
    "{{VENV_PYTHON}}" -m flake8 --exclude=.venv --ignore="{{FLAKE8_IGNORE}}" "${flake8_paths[@]}"
