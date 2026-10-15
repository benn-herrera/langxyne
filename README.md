# README – langxyne

langxyne allows for an API spec comprised of constants, types, structures, and functions to be declared once in a DSL
as the single source of truth. It generates boilerplate code for exposing the API to a set of targeted languages, allowing
for an implementation to be written under that spec in the system language of your choice. Updating all of your bindings
is reduced to editing the spec and implementing your API change once with automation doing the rest. See [THESIS.md](THESIS.md).

## Using this project

The expected use pattern is vendoring rather than as a pip install. Drop it into your project and use it as-is or modify it to suit
your needs. Trying to make this project fit everyone's use case would break one of its core values - it's essentially simple.

## Editor support

`api_def.schema.json` gives a Taplo-backed editor (Zed among them) completion, hover text and key diagnostics in a definition: a consuming repository's `.taplo.toml` can map its own definition paths to it (a `[[rule]]` with `include = ["api/**/*.adef.toml"]` and `schema.path` naming the file), and a definition can carry the Taplo directive `#:schema <path relative to the definition>` on its first line instead.

## Acknowledgements

- [jsonschema](https://github.com/python-jsonschema/jsonschema) - used for optional schema validation of .adef.toml files
- [khronos vulkan](https://github.com/khronosGroup/Vulkan-Docs) - concept of non-coding DSL for single source of truth API definition
