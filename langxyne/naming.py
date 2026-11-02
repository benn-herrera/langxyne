"""Target-language names derived from an API namespace and definition names, and a library's
file name per platform and link mode."""

from dataclasses import dataclass

# Every builtin scalar type and its C spelling: the one map the model and every emitter read.
BUILTIN_C_TYPES = {
    "i8": "int8_t",
    "u8": "uint8_t",
    "i16": "int16_t",
    "u16": "uint16_t",
    "i32": "int32_t",
    "u32": "uint32_t",
    "i64": "int64_t",
    "u64": "uint64_t",
    "f32": "float",
    "f64": "double",
}


def integer_range(type_name: str) -> tuple[int, int]:
    """The least and greatest value of the integer type `type_name`, `i8` through `u64`:
    `(-128, 127)` for `i8`."""
    bits = int(type_name[1:])
    if type_name.startswith("i"):
        return -(2 ** (bits - 1)), 2 ** (bits - 1) - 1
    return 0, 2**bits - 1


@dataclass(frozen=True)
class BaseCType:
    c_type: str  # the fixed-width C type
    const_macro: str  # the <stdint.h> macro that gives an integer literal that type
    min_value: int  # the least value the type holds
    max_value: int  # the greatest value the type holds


# A constant group's or enum's `_base_type`, first the default, and its C spellings and range.
BASE_C_TYPES = {
    "i32": BaseCType("int32_t", "INT32_C", *integer_range("i32")),
    "u32": BaseCType("uint32_t", "UINT32_C", *integer_range("u32")),
}
VERSION_KEY = "api_version"

# The builtin struct field type of a run of bytes in an arena, and its layout: its fields in
# order, each with its builtin type. Every output renders the type from these.
TEXT = "text"
TEXT_OFFSET = "offset"
TEXT_LENGTH = "length"
TEXT_FIELDS = ((TEXT_OFFSET, "u32"), (TEXT_LENGTH, "u32"))

# The generated function resolving a text against an arena, in each binding that has one.
RESOLVE = "resolve"

# The Rust binding's and the Go binding's struct of what a reported buffer wrote and needs.
FILLED = "Filled"

# The Rust relay's handle on an `out` buffer, which writes nothing until the implementation takes it.
OUT_SLICE = "OutSlice"

# The Python module's exception class, raised for a result other than the zero entry.
ERROR = "Error"

# A C callback type's own last parameter, through which the library hands back what the
# caller passed beside the callback.
USER_DATA = "user_data"

# The Rust binding's struct holding one callback for the driving call that passed it.
CALLBACK_FRAME = "CallbackFrame"
# The Rust binding's struct recording what failed during one driving call, shared by its frames.
CALLBACK_FAILURE = "CallbackFailure"

# `--link`'s values: how a consumer's build links the library.
SHARED = "shared"
STATIC = "static"
LINK_MODES = (SHARED, STATIC)
DEFAULT_LINK = SHARED

# A library file's (prefix, suffix) by platform and link mode: the one place a library file's
# name is spelled. Windows is the GNU toolchain's, the one cgo links with.
_LIBRARY_FILES = {
    ("linux", SHARED): ("lib", ".so"),
    ("linux", STATIC): ("lib", ".a"),
    ("macos", SHARED): ("lib", ".dylib"),
    ("macos", STATIC): ("lib", ".a"),
    ("windows", SHARED): ("", ".dll"),
    ("windows", STATIC): ("lib", ".a"),
    ("wasi", SHARED): ("", ".wasm"),
}
# Each value Python's `sys` module reports as the host's platform, to the table's platform.
HOST_PLATFORMS = {"linux": "linux", "darwin": "macos", "win32": "windows"}
# The environment variable each platform's loader searches for a shared library by its file name.
LOADER_PATH_VARIABLES = {"linux": "LD_LIBRARY_PATH", "macos": "DYLD_LIBRARY_PATH", "windows": "PATH"}
# Each table platform's GOOS, the name a Go build constraint and a `#cgo` line give it.
GO_OS = {"linux": "linux", "macos": "darwin", "windows": "windows"}


def type_name(namespace: str, name: str) -> str:
    """C name of an enum, struct, opaque ref or typedef: `tcdl_result`."""
    return f"{namespace}_{name}"


def function_name(namespace: str, name: str) -> str:
    """C name of a function: `tcdl_create_device`."""
    return f"{namespace}_{name}"


def count_param(name: str) -> str:
    """The count parameter a buffer expands to beside itself, of elements (bytes for `memory`):
    `psrc_count`."""
    return f"{name}_count"


def bytes_param(name: str) -> str:
    """The byte extent a sequence of a union's members expands to after its count: `seen_bytes`."""
    return f"{name}_bytes"


def wrote_param(name: str) -> str:
    """The report through which the callee says how much of a `_wrote_needed` buffer it
    wrote: `items_wrote`."""
    return f"{name}_wrote"


def needed_param(name: str) -> str:
    """The report through which the callee says how much the whole result of a
    `_wrote_needed` buffer needs: `items_needed`."""
    return f"{name}_needed"


def user_data_param(name: str) -> str:
    """The `user_data` pointer a callback parameter brings beside itself, which the library
    passes back to the callback: `sink_user_data`."""
    return f"{name}_{USER_DATA}"


def trampoline(name: str) -> str:
    """What a binding reaches the C function calling a consumer's code through: in the Rust
    binding and the Lua module, the function per callback type `name`; in the C++ wrapper,
    the local per callback parameter `name`: `on_batch_trampoline`."""
    return f"{name}_trampoline"


def cpp_template_param(name: str) -> str:
    """The C++ wrapper's template parameter of a method's callback parameter `name`, which
    no UpperCamel name (no `_`) and no constant (no lowercase letter) can be: `F_sink`."""
    return f"F_{name}"


def cpp_call_state(name: str) -> str:
    """The C++ wrapper's local holding a callback parameter `name`'s callable and the driving
    call's thread: `sink_call`."""
    return f"{name}_call"


def cpp_trampoline_param(index: int) -> str:
    """The C++ wrapper's name of a trampoline's parameter at `index`, by position so that none
    shadows a parameter of the method around it: `v0`."""
    return f"v{index}"


def const_name(namespace: str, name: str) -> str:
    """C name of a constant: `TCDL_ERR_NO_DEVICE`."""
    return f"{namespace.upper()}_{name.upper()}"


def unprefixed_const_name(name: str) -> str:
    """A constant's name with no namespace prefix, the rule the Lua module (whose module
    table is the namespace) and the C++ wrapper (whose C++ namespace already is) share:
    `ERR_NO_DEVICE`."""
    return name.upper()


def flat_to_string(name: str, *, typename: str | None) -> str:
    """A `_to_string` conversion's name in a flat module, the Lua module's and the Python
    module's: an enum's is prefixed with its type name, since neither overloads
    (`result_to_string`); a nameless group's is `name` as-is. C++ uses `name` as-is for
    both, overloading an enum's on its type."""
    return name if typename is None else f"{typename}_{name}"


def lua_lookup_table(conversion: str) -> str:
    """The module-local table a Lua lookup conversion reads, from the conversion's Lua
    name: `status_to_string_names`."""
    return f"{conversion}_names"


def cpp_member(name: str) -> str:
    """The C++ wrapper's private data member holding the value `name`: `info_`."""
    return f"{name}_"


def rust_raw_local(name: str) -> str:
    """The Rust binding's local holding an enum parameter `name` as its base integer for
    the C call: `mode_raw`."""
    return f"{name}_raw"


def rust_local(name: str) -> str:
    """The Rust relay's local holding what a pointer parameter `name` reaches the
    implementation through: `pstats_local`."""
    return f"{name}_local"


def library_file_name(name: str, *, platform: str, link: str) -> str:
    """The file library `name` is on `platform` under `link`: `xy` -> `libxy.dylib` on macOS, shared."""
    prefix, suffix = _LIBRARY_FILES[platform, link]
    return f"{prefix}{name}{suffix}"


def library_file_stem(file_name: str) -> str | None:
    """The library name `file_name` holds: `file_name` without the first of the table's
    suffixes it ends with, then without the table's prefix `lib` where what remains begins
    with it (`libxy.dll` -> `xy`, `libxy.so` -> `xy`, `liblibxy.so` -> `libxy`); `None`
    where it ends with no suffix or nothing remains."""
    suffix = next((s for _, s in _LIBRARY_FILES.values() if file_name.endswith(s)), None)
    if suffix is None:
        return None
    (prefix,) = {p for p, _ in _LIBRARY_FILES.values() if p}
    return file_name.removesuffix(suffix).removeprefix(prefix) or None


def unknown_value_name(typename: str | None) -> str:
    """What a conversion returns for a value no entry has: `UNKNOWN_RESULT` for an enum,
    `UNKNOWN` for a nameless group."""
    return "UNKNOWN" if typename is None else f"UNKNOWN_{typename.upper()}"


# What a bit group's conversion returns for zero.
NO_FLAGS = "NONE"


def version_const(namespace: str) -> str:
    """C name of the version constant: `TCDL_API_VERSION`."""
    return const_name(namespace, VERSION_KEY)


def opaque_struct(namespace: str, name: str) -> str:
    """The incomplete struct an opaque ref points to: `tcdl_handle_opaque`."""
    return f"{namespace}_{name}_opaque"


def c_api_macro(namespace: str) -> str:
    """The header's linkage macro, `extern "C"` under C++: `TCDL_C_API`."""
    return f"{namespace.upper()}_C_API"


def api_macro(namespace: str) -> str:
    """The macro before each function declaration, adding visibility for the implementation: `TCDL_API`."""
    return f"{namespace.upper()}_API"


def impl_macro(namespace: str) -> str:
    """The macro the implementation defines before including the header: `TCDL_IMPL`."""
    return f"{namespace.upper()}_IMPL"


def upper_camel(name: str) -> str:
    """`my_ns` -> `MyNs`."""
    return "".join(part.capitalize() for part in name.split("_"))


def go_exported(name: str) -> str:
    """The Go binding's exported name of a definition name, UpperCamel: `max_units` -> `MaxUnits`."""
    return upper_camel(name)


def go_enum_entry(enum: str, entry: str) -> str:
    """The Go binding's constant of entry `entry` of enum `enum`, the enum's name before the
    entry's, as Go has no enum scope: `StatusErrBusy`."""
    return upper_camel(enum) + upper_camel(entry)


def handle_type(opaque: str) -> str:
    """The Go binding's type and the Python module's class of an opaque ref's raw handle:
    `PortHandle`."""
    return upper_camel(opaque) + "Handle"


def library_variable(namespace: str) -> str:
    """The environment variable naming the absolute path the Python module loads its library
    from in place of the file beside it: `XY_LIBRARY`."""
    return f"{namespace.upper()}_LIBRARY"


def go_constructor(class_name: str) -> str:
    """The Go binding's function creating an object of class `class_name`: `NewPort`."""
    return "New" + upper_camel(class_name)


def go_export_symbol(namespace: str, callback: str) -> str:
    """The C symbol of the Go binding's exported function calling a consumer's func as
    callback type `callback`: `xy__on_batch`. No definition's C name is it, a definition name
    never beginning with `_`."""
    return f"{namespace}__{callback}"


# The wasm shim's exports and imports, each its namespace then `__`, which no definition's C
# name begins with, a definition name never beginning with `_`; the words after it keep the
# allocator pair apart from every callback type's two names.
def wasm_alloc(namespace: str) -> str:
    """The wasm shim's export allocating a block of a size and alignment: `xy__alloc`."""
    return f"{namespace}__alloc"


def wasm_free(namespace: str) -> str:
    """The wasm shim's export releasing a block `wasm_alloc()` gave, by its size and alignment:
    `xy__free`."""
    return f"{namespace}__free"


def wasm_callback_address(namespace: str, callback: str) -> str:
    """The wasm shim's export answering the address of callback type `callback`'s import, which
    the C ABI takes as the callback's pointer: `xy__address_on_batch`."""
    return f"{namespace}__address_{callback}"


def wasm_callback_import(namespace: str, callback: str) -> str:
    """The wasm module's import, a function the Node binding provides, that the library calls as
    callback type `callback`: `xy__call_on_batch`."""
    return f"{namespace}__call_{callback}"


def wasm_import_module(namespace: str) -> str:
    """The wasm import module holding every `wasm_callback_import()`: `xy__callbacks`."""
    return f"{namespace}__callbacks"


# The Node binding's own names at its module scope: the loader, what it returns and what it takes,
# the views a callback receives, and the error of a result other than the zero entry.
NODE_LOAD = "load"
NODE_LIBRARY = "Library"
NODE_WASI = "Wasi"
NODE_VIEW = "View"
NODE_BYTE_VIEW = "ByteView"
NODE_ERROR = "ResultError"
NODE_NAMES = (NODE_LOAD, NODE_LIBRARY, NODE_WASI, NODE_VIEW, NODE_BYTE_VIEW, NODE_ERROR)
# The loader's parameters, in scope where it defines the library's classes and free functions.
NODE_LOAD_PARAMS = ("wasi", "path")


def node_constructor_type(class_name: str) -> str:
    """The Node binding's declared type of class `class_name`'s constructor, `class_name` being
    its UpperCamel rendering: `PortConstructor`."""
    return f"{class_name}Constructor"


# Why a walk of a union's list refused it, in the clause enum's order from 1: each clause's name,
# from which every output spells its entry, and its text, every binding's refusal's words.
UNION_CLAUSES = (
    ("header_past_extent", "header past the extent"),
    ("unknown_tag", "unknown tag"),
    ("size_not_the_members", "size is not the member's"),
    ("record_past_extent", "record past the extent"),
    ("count_not_met", "count not met"),
    ("not_a_record_start", "offset is not a record's start"),
)
UNION_CLAUSE_TEXTS = dict(UNION_CLAUSES)
# The clause enum: `ns_union_clause` in C; `UnionClause` in the C++ wrapper, the Rust files and
# the Go binding.
UNION_CLAUSE = "union_clause"
UNION_CLAUSE_TYPE = upper_camel(UNION_CLAUSE)
# The clause enum's zero entry, a walk that refused nothing: `NS_UNION_OK`.
UNION_OK = "union_ok"
# The clause-to-text conversion: `ns_union_clause_text` in C, `ns::union_clause_text` in C++.
UNION_CLAUSE_TEXT = "union_clause_text"
# Where a walk of a union's list refused it, in the C++ wrapper, the Rust files, the Go binding
# and the Python module.
UNION_ERROR = "UnionError"
# The header's list helpers of a union declaring `_mixed_type_list`, each `ns_<union>_<helper>`.
UNION_HELPERS = ("member_size", "record_clause", "first", "next", "well_formed")


def union_clause_entry(clause: str) -> str:
    """The clause enum's entry of clause `clause` of `UNION_CLAUSES`, before its namespace
    prefix: `union_unknown_tag`."""
    return f"union_{clause}"


def union_helper(namespace: str, union: str, helper: str) -> str:
    """The C name of one of `UNION_HELPERS` of union `union`: `xy_note_first`."""
    return function_name(namespace, f"{union}_{helper}")


def union_sequence(union: str) -> str:
    """A list of union `union`'s members in the C++ wrapper, the Rust files, the Go binding and
    the Python module: `NoteSequence`."""
    return f"{upper_camel(union)}Sequence"


def union_align(union: str) -> str:
    """The constant of union `union`'s list alignment, the unit of every binding's `at`, before
    each output's casing of a constant: `note_align`."""
    return f"{union}_align"


def rust_union_ref(union: str) -> str:
    """The Rust files' enum of a record of union `union`: `NoteRef`."""
    return f"{upper_camel(union)}Ref"


def rust_union_records(union: str) -> str:
    """The Rust files' iterator over a list of union `union`: `NoteRecords`."""
    return f"{upper_camel(union)}Records"


def rust_union_buf(union: str) -> str:
    """The Rust relay's buffer building a list of union `union`: `NoteBuf`."""
    return f"{upper_camel(union)}Buf"


def rust_union_buf_mark(union: str) -> str:
    """The Rust relay's place in a `rust_union_buf()`: `NoteBufMark`."""
    return f"{upper_camel(union)}BufMark"


def go_union_record(union: str) -> str:
    """The Go binding's interface of a record of union `union`: `NoteRecord`."""
    return f"{go_exported(union)}Record"


def go_union_walker(union: str) -> str:
    """The Go binding's walker of a list of union `union`: `NoteWalker`."""
    return f"{go_exported(union)}Walker"


def go_union_marker(union: str) -> str:
    """The unexported method of the Go binding's `go_union_record()` that each member's struct
    has: `_note_record`."""
    return f"_{union}_record"


def lua_union_records(union: str) -> str:
    """The Lua module's field iterating a list of union `union`: `note_records`."""
    return f"{union}_records"


def lua_union_at(union: str) -> str:
    """The Lua module's field resolving an offset in a list of union `union`: `note_at`."""
    return f"{union}_at"


def lua_union_shape(union: str) -> str:
    """The Lua module's local holding union `union`'s prefix, members and sizes: `note_union`."""
    return f"{union}_union"
