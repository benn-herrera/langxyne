# README – langxyne

langxyne allows for an API spec comprised of constants, types, structures, and functions to be declared once in a DSL
as the single source of truth. It generates boilerplate code for exposing the API to a set of targeted languages, allowing
for an implementation to be written under that spec in the system language of your choice. Updating all of your bindings
is reduced to editing the spec and implementing your API change once with automation doing the rest.

## A C header is a rotten single source of truth

A C header is an idiomatic expression of an API. Transforming one idiom to another while also imposing artificial restrictions on the usage of the single source of truth coding language introduces unnecessary complexities and gotchas.

What the generator produces today, eleven outputs among them a Rust binding, a Rust ABI relay, a Rust implementation stub, a Go binding, a Python module and a Node binding over a WASI module, is listed in SPEC.md, "Outputs".

## Editor support

`api_def.schema.json` gives a Taplo-backed editor (Zed among them) completion, hover text and key diagnostics in a definition: a consuming repository's `.taplo.toml` can map its own definition paths to it (a `[[rule]]` with `include = ["api/**/*.adef.toml"]` and `schema.path` naming the file), and a definition can carry the Taplo directive `#:schema <path relative to the definition>` on its first line instead.

## Acknowledgements

[jsonschema](https://github.com/python-jsonschema/jsonschema) - used for optional schema validation of .adef.toml files
[khronos vulkan](https://github.com/khronosGroup/Vulkan-Docs) - concept of non-coding DSL for single source of truth API definition
