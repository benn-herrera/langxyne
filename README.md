# README – langxyne

langxyne allows for an API spec comprised of constants, types, structures, and functions to be declared once in a DSL
as the single source of truth. It generates boilerplate code for exposing the API to a set of targeted languages, allowing
for an implementation to be written under that spec in the system language of your choice. Updating all of your bindings
is reduced to editing the spec and implementing your API change once with automation doing the rest. See [THESIS.md](THESIS.md).

## Requirements and Supported Platforms

Python 3.11 or later. `rustfmt` on `PATH` for the Rust outputs and `gofmt` for the Go output; a run that selects one without it exits 2 and writes nothing. The optional `jsonschema` package adds a schema check of each definition. Make-driven builds (`gendeps`) need GNU make 4.3 or later.

## Using this project

The project is meant to stay simple: use it as-is or modify it to suit your needs. Trying to make it fit everyone's use case would break one of its core values. Two ways to take it:

- **Install it.** `pip install git+https://github.com/benn-herrera/langxyne`, or `pip install "langxyne[schema] @ git+https://github.com/benn-herrera/langxyne"` to add `jsonschema`. This provides the `langxyne` command and `python3 -m langxyne`.
- **Vendor it.** Copy the `langxyne/` package directory into your project and run `python3 -m langxyne` with the directory that contains `langxyne/` importable (for example `PYTHONPATH=third_party python3 -m langxyne ...` for `third_party/langxyne/`). Edit the copy freely.

## Quick Start Guide

```sh
langxyne api/my_api.adef.toml --generated gen --project my_api --outputs=h,hpp
```

Writes the C header and C++ wrapper under `gen/`. The modes, outputs and flags are in [SPEC.md](SPEC.md) "Invocation"; how the generator is built is in [ARCHITECTURE.md](ARCHITECTURE.md).

A make-driven build includes the fragment `langxyne gendeps api/my_api.adef.toml` prints, after defining `GEN`, `BASE` and `LANGXYNE`. For a vendored copy `LANGXYNE` is the directory containing `langxyne/`; for an installed package it may be empty.

## Development

`just test` runs the unit tests (pytest over `langxyne/tests`). `just bindings-test` builds and runs the generated bindings against fakes; the host tools it needs are listed in [ARCHITECTURE.md](ARCHITECTURE.md) "Tests". `just regenerate-expected` rewrites the Rust goldens after `bindings-test` passes; `just pre-commit` formats and lints `langxyne/`.

## Editor support

`api_def.schema.json` gives a Taplo-backed editor (Zed among them) completion, hover text and key diagnostics in a definition. It is at `langxyne/assets/api_def.schema.json` in a vendored copy; for an installed package, `langxyne dump-schema > api_def.schema.json` writes it where you choose. A consuming repository's `.taplo.toml` can map its own definition paths to the file (a `[[rule]]` with `include = ["api/**/*.adef.toml"]` and `schema.path` naming it), and a definition can carry the Taplo directive `#:schema <path relative to the definition>` on its first line instead.

## Third Party Acknowledgements

- [jsonschema](https://github.com/python-jsonschema/jsonschema), Julian Berman and contributors, MIT - used for optional schema validation of .adef.toml files
- [khronos vulkan](https://github.com/khronosGroup/Vulkan-Docs) - concept of non-coding DSL for single source of truth API definition
