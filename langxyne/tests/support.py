"""Definitions and helpers shared by the langxyne tests."""

import contextlib
import difflib
import io
import re
import tomllib
import unittest
from pathlib import Path

from langxyne import __main__ as langxyne_main
from langxyne import model, naming
from langxyne.emitters import emit_c

# The reference resources the tests read beside their code: the programs the compiled checks
# build and run, and the three Rust goldens.
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXPECTED_BINDING = FIXTURES / "expected_binding_xy.rs"
EXPECTED_ABI = FIXTURES / "expected_abi_xy.rs"
EXPECTED_STUB = FIXTURES / "expected_stub_xy.rs"

FIXTURE = """
[_general]
_name = "xy_api"
_namespace = "xy"
_version = [1, 2, 3, 4]
_bound_library = "xy"

[[untyped_bit_const]]
feat_a = 0
feat_b = { _value = 3, _docstring = "the b feature" }
feat_ab = { _value = ["feat_a", "feat_b"], _format = "hex" }
_to_string = "feat_to_string"

[[untyped_const]]
max_units = 16
magic = { _value = 0xbeef, _format = "hex", _docstring = "wire magic" }
_to_string = "limit_to_string"

[[string_const]]
product = "xy widget"
vendor = { _value = "acme", _docstring = "who made it" }

[[typed_const]]
[typed_const.status]
_docstring = "call outcome"
_to_string = "to_string"
ok = 0
err_busy = { _value = 9, _docstring = "try later" }
err_other = { _value = 0x7fffffff, _format = "hex" }

[[opaque_ref]]
[opaque_ref.port]
_ctor = "open_port"
_dtor = "destroy_port"

[opaque_ref.token]

[[struct]]
[struct.stats]
count = { _type = "u32", _docstring = "items seen" }
bytes = "u64"

[[function]]
[function.open_port]
_return = "status"
unit = "u32"
pport = { _type = "port", _ref = "out" }
pstats = { _type = "stats", _ref = "out", _optional = true }
generation = { _type = "u32", _ref = "out" }

[function.destroy_port]
_docstring = "release the port"
_return = "status"
hport = "port"

[function.send]
_return = "status"
hport = "port"
buf = { _type = "memory", _ref = "in", _count = "u64", _docstring = "bytes to send" }

[function.spend]
_return = "status"
htoken = "token"

[_wrapped_api]
_headers = ["driver/xy_ioctl.h"]
[_wrapped_api._pinned_value]
feat_a = "XYD_FEAT_A"
"""

# Every feature the compiled checks exercise, FIXTURE's items among them (its bit-group
# conversion on a group of its own, access_to_string); the fakes and the consumers under
# FIXTURES are written against it. Its port sets _hides_pointer; UNHIDDEN_PORT does not.
KITCHEN_SINK = """
[_general]
_name = "xy_api"
_namespace = "xy"
_version = [1, 2, 3, 4]
_bound_library = "xy"

[[untyped_bit_const]]
_docstring = "feature flags"
feat_a = 0
feat_b = { _value = 3, _docstring = "the b feature" }
feat_ab = { _value = ["feat_a", "feat_b"], _format = "hex" }
feat_lit = { _value = ["feat_a", "4"] }

[[untyped_bit_const]]
_base_type = "u32"
feat_one = 0
feat_all = ["feat_one", "8"]

[[untyped_bit_const]]
_docstring = "access flags"
_to_string = "access_to_string"
acc_a = 0
acc_b = 1
acc_ab = ["acc_a", "acc_b"]

[[untyped_const]]
_docstring = "limits"
_to_string = "limit_to_string"
max_units = 16
extra = 4
max_total = ["max_units", "extra"]
neg = { _value = -5, _format = "hex" }
low = -7
floor = { _value = -2147483648, _format = "hex" }
dip = ["max_units", "-3"]

[[untyped_const]]
_docstring = "wire values"
_base_type = "u32"
magic = { _value = 0xbeef, _format = "hex", _docstring = "wire magic" }

[[string_const]]
product = "xy widget"
vendor = { _value = "acme", _docstring = "who made it" }

[[typed_const]]
[typed_const.status]
_docstring = "call outcome"
_to_string = "to_string"
ok = 0
err_busy = { _value = 9, _docstring = "try later" }
err_other = { _value = 0x7fffffff, _format = "hex" }
err_again = 10
err_unsupported = 12
err_floor = { _value = -2147483648, _format = "hex" }

[typed_const.mode]
_base_type = "u32"
_to_string = "to_string"
fine = 0
slow = 1

[typed_const.flow]
_docstring = "what a batch sink answers"
go = 0
halt = 1

[typed_const.cut]
_base_type = "u32"
_docstring = "a batch also ends after the entry at this index"
after_one = 1
after_four = 4

[[opaque_ref]]
port = { _docstring = "a port", _ctor = "open_port", _dtor = "destroy_port", _hides_pointer = true }

[opaque_ref.token]

[opaque_ref.link]
_ctor = "open_link"
_class = "data_link"

[[boxed_scalar]]
[boxed_scalar.offset]
_docstring = "a device offset"
_base_type = "u64"

[[struct]]
[struct.stats]
_docstring = "counters"
count = { _type = "u32", _docstring = "items seen" }
bytes = "u64"

[struct.wrap]
inner = "stats"
[struct.wrap.n]
_type = "u32"

[struct.entry]
id = "u32"
label = "text"

[[callback]]
[callback.on_batch]
_docstring = "every entry so far, those new since the last call, their labels' arena so far, and 1 on the final call"
_return = "flow"
seen = { _type = "entry", _ref = "in", _count = "u64" }
fresh = { _type = "entry", _ref = "in", _count = "u64" }
arena = { _type = "memory", _ref = "in", _count = "u32" }
last = "u32"

[callback.on_mode]
_docstring = "a mode the library reports"
_return = "flow"
mode = "mode"

[[function]]
[function.open_port]
_return = "status"
unit = "u32"
pport = { _type = "port", _ref = "out" }
pstats = { _type = "stats", _ref = "out", _optional = true }
generation = { _type = "u32", _ref = "out" }
pwrap = { _type = "wrap", _ref = "out" }

[function.destroy_port]
_docstring = "release the port"
_return = "status"
hport = "port"

[function.send]
_return = "status"
hport = "port"
buf = { _type = "memory", _ref = "in", _count = "u64", _docstring = "bytes to send" }

[function.spend]
_return = "status"
htoken = "token"

[function.recv]
_return = "status"
hport = "port"
pdst = { _type = "memory", _ref = "out", _count = "u32" }

[function.configure]
_return = "status"
hport = "port"
cfg = { _type = "stats", _ref = "in" }
limit = { _type = "u32", _ref = "in" }
mode = "mode"
who = "token"

[function.stats_of]
_return = "status"
hport = "port"
out = { _type = "stats", _ref = "out" }
pcount = { _type = "u32", _ref = "out" }
plink = { _type = "link", _ref = "out" }

[function.bump]
_docstring = "level + 1, tally.count * 2, each byte of data + 1"
_return = "status"
hport = "port"
level = { _type = "u32", _ref = "inout" }
tally = { _type = "stats", _ref = "inout" }
data = { _type = "memory", _ref = "inout", _count = "u32" }

[function.open_link]
_return = "status"
plink = { _type = "link", _ref = "out" }

[function.attach]
_docstring = "ok for a non-null link and port, else err_other"
_return = "status"
hlink = "link"
hport = "port"

[function.mint]
_docstring = "ptoken = a token the library holds"
_return = "status"
ptoken = { _type = "token", _ref = "out" }

[function.annotate]
_docstring = "ok iff note is absent or note.count == 7"
_return = "status"
hport = "port"
note = { _type = "stats", _ref = "in", _optional = true }

[function.reset]
_return = "status"

[function.seek]
_docstring = "ok for 1 << 40; ok for 98 where the last batch-98 stream received an answer other than go, else err_again; for 96 during a batch-95 or batch-96 stream, calls that stream's sink once with empty views and answers ok; for 95, ok where the last batch-95 stream's first call was answered other than go, else err_again (the C++ fake only)"
_return = "status"
hport = "port"
offset = "u64"

[function.tune]
_docstring = "pnext = big - 1, pdelta = delta - 1; ok iff delta == -3, big == -(1 << 40), small == 200, scale == 0.5"
_return = "status"
hport = "port"
delta = "i32"
big = "i64"
small = "u8"
scale = "f64"
pnext = { _type = "i64", _ref = "out" }
pdelta = { _type = "i32", _ref = "out" }

[function.probe]
_docstring = "pmode = slow, level + 1 and ppeek = 9 where given; ok iff payload is absent or 2 bytes and limit is absent or 3"
_return = "status"
hport = "port"
pmode = { _type = "mode", _ref = "out" }
payload = { _type = "memory", _ref = "in", _count = "u32", _optional = true }
limit = { _type = "u32", _ref = "in", _optional = true }
level = { _type = "u32", _ref = "inout", _optional = true }
ppeek = { _type = "u32", _ref = "out", _optional = true }

[function.echo_offset]
_docstring = "ppos = pos"
_return = "status"
hport = "port"
pos = "offset"
ppos = { _type = "offset", _ref = "out" }

[function.list]
_docstring = "entries e0..e2 (id 10 + i, label 'e<i>' at 2i) and their labels' arena 'e0e1e2', each as much as its buffer holds; lies at items capacity 4 (wrote 5, needed 9) and 6 (wrote 4), and at labels capacity 5 (wrote 7)"
_return = "status"
hport = "port"
items = { _type = "entry", _ref = "out", _count = "u64", _wrote_needed = true }
labels = { _type = "memory", _ref = "out", _count = "u32", _wrote_needed = true }

[function.stream]
_docstring = "entries e0..e6 (id 10 + i, label 'e<i>' at 2i) to sink: a batch when it holds batch entries (0: never) or a cut ends it, then a final call with the remainder, possibly empty; a sink answer other than go stops it with err_again; batch 99 calls sink from another thread (the C++ fake only); batch 98 delivers batches of 1 whatever the sink answers, err_again where any answer was not go; batch 97 (the C++ fake only) passes a null fresh with a count of 1 on its first call; batch 96 (the C++ fake only) lets seek(96) on any port call the sink again while it runs; batch 95 (the C++ fake only) lets seek(96) call the sink again as batch 96 does and delivers batches of 1 whatever the sink answers, err_again where any answer was not go"
_return = "status"
hport = "port"
batch = "u32"
cuts = { _type = "cut", _ref = "in", _count = "u32" }
sink = "on_batch"

[function.notify]
_docstring = "calls first with sent as the mode, then second, whatever either answers; err_again where either answered other than go"
_return = "status"
hport = "port"
sent = "u32"
first = "on_mode"
second = "on_mode"

[_wrapped_api]
_headers = ["driver/xy_ioctl.h"]
[_wrapped_api._pinned_value]
feat_a = "XYD_FEAT_A"

[[untyped_const]]
_docstring = "what a note's head.kind names"
_base_type = "u32"
kind_line = 1
kind_mark = 2

[[struct]]
[struct.note_head]
kind = "u16"
size = "u16"
at = "u32"

[struct.note_line]
head = "note_head"
label = "text"

[struct.note_mark]
head = "note_head"
value = "i32"
flag = "u32"

[[union]]
[union.note]
_docstring = "one note: the struct its head's kind names, head.size bytes long"
_mixed_type_list = true
line = { _tag = "kind_line", _type = "note_line" }
mark = { _tag = "kind_mark", _type = "note_mark", _docstring = "a value and its flag" }

[[callback]]
[callback.on_notes]
_docstring = "every note so far and those new since the last call"
_return = "flow"
seen = { _type = "note", _ref = "in", _count = "u32" }
fresh = { _type = "note", _ref = "in", _count = "u32" }

[[function]]
[function.stream_notes]
_docstring = "notes n0..n5 to sink, batch of them a call (0: all six in one), the last call holding the remainder; a sink answer other than go stops it with err_again; a batch above 6 is err_unsupported"
_return = "status"
hport = "port"
batch = "u32"
sink = "on_notes"
"""

# SPEC.md's `_base_type` spellings, stated independently of naming.BASE_C_TYPES.
C_BASE_TYPES = {"i32": "int32_t", "u32": "uint32_t"}

MINIMAL = '[_general]\n_name = "xy_api"\n_namespace = "xy"\n_version = [0,0,0,1]\n'


def load(text: str = FIXTURE) -> model.Api:
    return model.from_dict(tomllib.loads(text))


def objections(text: str) -> list[str]:
    """Every objection the loader has to definition `text`, in order; none where it loads."""
    try:
        load(text)
    except model.DefinitionError as e:
        return [str(o) for o in e.objections()]
    return []


def assert_objection(test: unittest.TestCase, text: str, message: str) -> None:
    """The loader refuses definition `text` with `message` and nothing else."""
    test.assertEqual(objections(text), [message])


def assert_matches_expected(test: unittest.TestCase, expected: Path, actual: str) -> None:
    """`actual` is the text of the file `expected`, byte for byte, else a unified diff."""
    text = expected.read_text(encoding="utf-8")
    if actual != text:
        test.fail(
            "".join(
                difflib.unified_diff(
                    text.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    expected.name,
                    "emitted",
                )
            )
        )


def header(api: model.Api) -> str:
    """`api`'s C header, as generation writes it from xy_api.adef.toml."""
    return emit_c.emit(api, source_name="xy_api.adef.toml", name="xy_api", project="xy")


def mutate(text: str, needle: str, replacement: str, *, every: bool = False) -> str:
    """`text` with `needle` replaced: its one occurrence, or with `every` each of them. A
    needle that no longer matches, or that matches more than once without `every`, fails
    loudly."""
    count = text.count(needle)
    assert count >= 1 if every else count == 1, f"fixture holds {count} of {needle!r}"
    return text.replace(needle, replacement)


# KITCHEN_SINK with its port's _hides_pointer unset: the same C ABI, so either fake serves it.
UNHIDDEN_PORT = mutate(KITCHEN_SINK, ", _hides_pointer = true }", " }")

# FIXTURE with two independent loader errors: two functions whose _return names no
# typed_const, one of them port's _dtor.
TWO_BAD_RETURNS = mutate(
    mutate(FIXTURE, '_docstring = "release the port"\n_return = "status"', '_return = "nope"'),
    '_return = "status"\nhtoken',
    '_return = "gone"\nhtoken',
)

# FIXTURE without its [_wrapped_api], the last table.
NO_WRAPPED_API = FIXTURE[: FIXTURE.index("[_wrapped_api]")]

# FIXTURE with its functions in two documented groups: open_port and destroy_port, port's
# ctor and dtor, under "port lifecycle", then send and spend under "traffic".
DOCUMENTED_FUNCTION_GROUPS = mutate(
    mutate(FIXTURE, "[[function]]\n", '[[function]]\n_docstring = "port lifecycle"\n'),
    "\n[function.send]\n",
    '\n[[function]]\n_docstring = "traffic"\n[function.send]\n',
)

# KITCHEN_SINK with what only the Rust outputs' compile gates and a Rust stub built as the
# library exercise: the constructor caching an enum `out`; a method taking an enum by every
# `_ref` the binding passes through a local of the enum's base type; methods taking an opaque
# through `_ref`, `link` with a class and `token` without; a method of `&self` and seven
# parameters, so a stub fn of eight, where clippy's too_many_arguments begins; a buffer
# whose count type cannot count every slice; reported buffers counted in u8 and u16,
# whose reports convert to usize infallibly, beside an unreported array of a boxed scalar; an
# `_optional` struct `in` array and a boxed scalar `in` array; a callback type taking a u8-counted
# view of a boxed scalar, a u64-counted byte view and an enum by value; a method taking two
# callbacks of different types; and a function no class renders taking a callback.
REFS = (
    mutate(
        KITCHEN_SINK, 'generation = { _type = "u32", _ref = "out" }', 'generation = { _type = "mode", _ref = "out" }'
    )
    + """
[function.steer]
_return = "status"
hport = "port"
want = { _type = "mode", _ref = "in" }
cur = { _type = "mode", _ref = "inout" }
hint = { _type = "mode", _ref = "in", _optional = true }
seen = { _type = "mode", _ref = "inout", _optional = true }
last = { _type = "mode", _ref = "out", _optional = true }

[function.link_to]
_return = "status"
hport = "port"
peer = { _type = "link", _ref = "in" }
maybe = { _type = "link", _ref = "in", _optional = true }

[function.relink]
_return = "status"
hport = "port"
cur = { _type = "link", _ref = "inout" }

[function.lend]
_return = "status"
hport = "port"
tok = { _type = "token", _ref = "in" }

[function.wide]
_return = "status"
hport = "port"
a0 = "u8"
a1 = "u8"
a2 = "u8"
a3 = "u8"
a4 = "u8"
a5 = "u8"
a6 = "u8"

[function.send_short]
_return = "status"
hport = "port"
buf = { _type = "memory", _ref = "in", _count = "u8" }

[function.gather]
_return = "status"
hport = "port"
shorts = { _type = "u16", _ref = "out", _count = "u8", _wrote_needed = true }
blob = { _type = "memory", _ref = "out", _count = "u16", _wrote_needed = true }
spots = { _type = "offset", _ref = "out", _count = "u32" }

[function.note]
_return = "status"
hport = "port"
notes = { _type = "stats", _ref = "in", _count = "u16", _optional = true }
spots = { _type = "offset", _ref = "in", _count = "u32" }

[function.watch]
_return = "status"
hport = "port"
first = "on_batch"
second = "on_spots"

[function.observe]
_return = "status"
sink = "on_spots"

[[callback]]
[callback.on_spots]
_return = "flow"
spots = { _type = "offset", _ref = "in", _count = "u8" }
blob = { _type = "memory", _ref = "in", _count = "u64" }
mode = "mode"
"""
)


# Five structs whose UpperCamel re-exports take prelude names the relay does not spell, so
# its module-scope check must not refuse them: Default, Drop, String, ToString, TryFrom.
UNSPELLED_PRELUDE_STRUCTS = "".join(
    f'\n[struct.{name}]\nv = "u32"\n' for name in ("default", "drop", "string", "to_string", "try_from")
)
UNSPELLED_PRELUDE = KITCHEN_SINK + UNSPELLED_PRELUDE_STRUCTS

# The scratch definitions tests/run-bindings.sh generates one case each: bit 31 of a u32 group,
# which the header and the wrapper carry and wide_xy.cpp proves (the Lua emitter refuses it);
# a parameter named like a trampoline; a relay regenerated with a moved-on `whence`, which
# fails the stub built over it; and stream's sink before its cuts, so the cuts that fail to
# convert follow the callback.
BIT_THIRTY_ONE = mutate(
    KITCHEN_SINK,
    '_base_type = "u32"\nfeat_one = 0',
    '_base_type = "u32"\n_to_string = "wide_to_string"\nfeat_one = 31',
)
TRAMPOLINE_PARAM = mutate(KITCHEN_SINK, 'batch = "u32"\ncuts = ', 'on_batch_trampoline = "u32"\ncuts = ')
RELAY_WITH_WHENCE = mutate(KITCHEN_SINK, 'offset = "u64"\n', 'offset = "u64"\nwhence = "u32"\n')
CUTS_AFTER_SINK = mutate(
    KITCHEN_SINK,
    'cuts = { _type = "cut", _ref = "in", _count = "u32" }\nsink = "on_batch"\n',
    'sink = "on_batch"\ncuts = { _type = "cut", _ref = "in", _count = "u32" }\n',
)


LINE_MEMBER = 'line = { _tag = "kind_line", _type = "note_line" }'
MARK_MEMBER = 'mark = { _tag = "kind_mark", _type = "note_mark", _docstring = "a value and its flag" }'
NOTES = 'notes = { _type = "note", _ref = "in", _count = "u32" }'
MIXED_TYPE_LIST = "_mixed_type_list = true"

# A two-member tagged union over an 8-byte prefix, note_head, whose members are 16 bytes each,
# lying in a list: a sequence of it is a callback's view and a function's `in` parameter.
UNIONS = f"""
[_general]
_name = "xy_api"
_namespace = "xy"
_version = [1, 2, 3, 4]
_bound_library = "xy"

[[untyped_const]]
_base_type = "u32"
kind_line = 1
kind_mark = 2

[[typed_const]]
[typed_const.status]
ok = 0
err_busy = 9

[typed_const.flow]
go = 0
halt = 1

[[struct]]
[struct.note_head]
kind = "u16"
size = "u16"
at = "u32"

[struct.note_line]
head = "note_head"
label = "text"

[struct.note_mark]
head = "note_head"
value = "i32"
flag = "u32"

[[union]]
_docstring = "what a note is"
[union.note]
_docstring = "one note: the struct its head's kind names, head.size bytes long"
{MIXED_TYPE_LIST}
{LINE_MEMBER}
{MARK_MEMBER}

[[callback]]
[callback.on_notes]
_return = "flow"
seen = {{ _type = "note", _ref = "in", _count = "u32" }}
count = "u32"

[[function]]
[function.replay]
_return = "status"
{NOTES}
"""

# UNIONS with its union declaring no _mixed_type_list, and so with no counted parameter of it: a
# family of structs sharing a prefix and nothing more.
UNION_NOT_LISTED = mutate(
    mutate(mutate(UNIONS, f"{MIXED_TYPE_LIST}\n", ""), 'seen = { _type = "note", _ref = "in", _count = "u32" }\n', ""),
    f"{NOTES}\n",
    "",
)

# UNIONS over a 4-byte prefix aligned to 2, a u8 tag, a u8 flag, then a u16 length, so the length
# is the prefix's third field and the tag and length differ in type; its members are 6 and 8 bytes.
UNION_U8_TAG = mutate(
    UNIONS,
    'kind = "u16"\nsize = "u16"\nat = "u32"\n\n[struct.note_line]\nhead = "note_head"\nlabel = "text"\n\n'
    '[struct.note_mark]\nhead = "note_head"\nvalue = "i32"\nflag = "u32"\n',
    'kind = "u8"\nflag = "u8"\nsize = "u16"\n\n[struct.note_line]\nhead = "note_head"\nwidth = "u16"\n\n'
    '[struct.note_mark]\nhead = "note_head"\nvalue = "i16"\nflag = "u16"\n',
)

# What UNIONS' references to its union report after the union's own objection where it fails.
NOTE_REFS = ["callback.on_notes.seen: unknown type 'note'", "function.replay.notes: unknown type 'note'"]

# The prefix rule as the loader words its refusal, after `union.<u>: prefix '<struct>' `.
PREFIX_RULE = "must begin with the tag, u8, u16 or u32, then any u8 fields, then the record's byte length, u16 or u32"


def _struct_of_bytes(size: int) -> str:
    """Struct tables of which the last, `w<n>`, is `size` bytes of `u32`s, `size` a power of
    two from 8, each doubling the one before it."""
    tables = ['[struct.w0]\na = "u32"\nb = "u32"\n']
    while 8 << (len(tables) - 1) < size:
        n = len(tables)
        tables.append(f'[struct.w{n}]\na = "w{n - 1}"\nb = "w{n - 1}"\n')
    return "\n".join(tables) + "\n"


# Each loader rule of a union, UNIONS edited to break it, and every objection the loader then has.
UNION_REFUSALS: dict[str, tuple[str, list[str]]] = {
    "a mixed type list that is not a boolean": (
        mutate(UNIONS, MIXED_TYPE_LIST, '_mixed_type_list = "yes"'),
        ["union.note._mixed_type_list must be true or false", *NOTE_REFS],
    ),
    "a counted parameter of a union not a mixed type list": (
        mutate(UNIONS, f"{MIXED_TYPE_LIST}\n", ""),
        [
            "callback.on_notes.seen: a counted parameter needs union 'note' to declare _mixed_type_list = true",
            "function.replay.notes: a counted parameter needs union 'note' to declare _mixed_type_list = true",
        ],
    ),
    "no member": (
        mutate(UNIONS, f"{LINE_MEMBER}\n{MARK_MEMBER}\n", ""),
        ["union.note: names no member", *NOTE_REFS],
    ),
    "a member without _type": (
        mutate(UNIONS, LINE_MEMBER, 'line = { _tag = "kind_line" }'),
        ["union.note.line: a member needs _tag and _type", *NOTE_REFS],
    ),
    "a member as a naked value": (
        mutate(UNIONS, LINE_MEMBER, 'line = "note_line"'),
        ["union.note.line: a member needs _tag and _type", *NOTE_REFS],
    ),
    "a member's unknown key": (
        mutate(UNIONS, LINE_MEMBER, LINE_MEMBER.replace(" }", ', _ref = "in" }')),
        ["union.note.line: unknown key(s) _ref", *NOTE_REFS],
    ),
    "a tag naming no untyped_const entry": (
        mutate(UNIONS, '_tag = "kind_line"', '_tag = "go"'),
        ["union.note.line._tag: 'go' is not an untyped_const entry", *NOTE_REFS],
    ),
    "a type naming no struct": (
        mutate(UNIONS, '_type = "note_line"', '_type = "note_nope"'),
        ["union.note.line._type: struct 'note_nope' must be defined before it is used", *NOTE_REFS],
    ),
    "a type of another category": (
        mutate(UNIONS, '_type = "note_line"', '_type = "flow"'),
        ["union.note.line._type: 'flow' is not a struct", *NOTE_REFS],
    ),
    "members beginning with different structs": (
        mutate(
            UNIONS,
            '[struct.note_line]\nhead = "note_head"',
            '[struct.note_alt]\nkind = "u16"\nsize = "u16"\nat = "u32"\n\n[struct.note_line]\nhead = "note_alt"',
        ),
        [
            "union.note: members must begin with one struct; line begins with 'note_alt' and mark with 'note_head'",
            *NOTE_REFS,
        ],
    ),
    "a member not beginning with a struct": (
        mutate(UNIONS, 'head = "note_head"\nlabel = "text"', 'label = "text"\nhead = "note_head"'),
        ["union.note.line._type: struct 'note_line' must begin with a struct field", *NOTE_REFS],
    ),
    "a u8 field between a u16 tag and the length": (
        mutate(UNIONS, 'kind = "u16"\nsize = "u16"', 'kind = "u16"\nflag = "u8"\nsize = "u16"'),
        ["union.note: struct 'note_head' has padding after field 'flag'; a member has none", *NOTE_REFS],
    ),
    "a prefix whose tag and length are signed": (
        mutate(UNIONS, 'kind = "u16"\nsize = "u16"', 'kind = "i16"\nsize = "i16"'),
        [f"union.note: prefix 'note_head' {PREFIX_RULE}", *NOTE_REFS],
    ),
    "a prefix whose length is u8": (
        mutate(UNIONS, 'kind = "u16"\nsize = "u16"\nat = "u32"', 'kind = "u8"\nsize = "u8"'),
        [f"union.note: prefix 'note_head' {PREFIX_RULE}", *NOTE_REFS],
    ),
    "a prefix whose first field after a u8 tag is a struct": (
        mutate(
            mutate(UNIONS, "[struct.note_head]", '[struct.note_origin]\nx = "u16"\n\n[struct.note_head]'),
            'kind = "u16"\nsize = "u16"\nat = "u32"',
            'kind = "u8"\norigin = "note_origin"',
        ),
        [f"union.note: prefix 'note_head' {PREFIX_RULE}", *NOTE_REFS],
    ),
    "a prefix read one level deep": (
        mutate(
            mutate(UNIONS, "[struct.note_line]", '[struct.note_wrap]\ninner = "note_head"\n\n[struct.note_line]'),
            'head = "note_head"',
            'head = "note_wrap"',
            every=True,
        ),
        [f"union.note: prefix 'note_wrap' {PREFIX_RULE}", *NOTE_REFS],
    ),
    "a tag the tag field cannot hold": (
        mutate(UNIONS, "kind_line = 1", "kind_line = 70000"),
        ["union.note.line._tag: kind_line's value 70000 does not fit note_head.kind (u16)", *NOTE_REFS],
    ),
    "two members of one tag": (
        mutate(UNIONS, '_tag = "kind_mark"', '_tag = "kind_line"'),
        ["union.note.mark._tag: kind_line is already union.note.line's tag", *NOTE_REFS],
    ),
    "two members of one tag value": (
        mutate(UNIONS, "kind_mark = 2", "kind_mark = 1"),
        ["union.note.mark._tag: kind_mark's value 1 is already union.note.line's tag, kind_line", *NOTE_REFS],
    ),
    "two members of one struct": (
        mutate(UNIONS, '_type = "note_mark"', '_type = "note_line"'),
        ["union.note.mark._type: struct 'note_line' is already union.note.line's struct", *NOTE_REFS],
    ),
    "a member aligned past the prefix": (
        mutate(UNIONS, 'value = "i32"', 'value = "i64"'),
        [
            "union.note.mark: struct 'note_mark' has alignment 8 (field 'value' is i64); a member of 'note' has the"
            " prefix's alignment, 4",
            *NOTE_REFS,
        ],
    ),
    "a member with padding": (
        mutate(UNIONS, 'value = "i32"', 'value = "u16"'),
        ["union.note.mark: struct 'note_mark' has padding after field 'value'; a member has none", *NOTE_REFS],
    ),
    "a prefix with padding": (
        mutate(UNIONS, 'at = "u32"', 'gap = "u8"\nat = "u32"'),
        ["union.note: struct 'note_head' has padding after field 'gap'; a member has none", *NOTE_REFS],
    ),
    "a member short of the list's alignment": (
        mutate(
            mutate(UNIONS, "[struct.note_line]", f"{_struct_of_bytes(32)}[struct.note_line]"),
            'value = "i32"\nflag = "u32"',
            'value = "w2"\nflag = "u32"\ntail = "u16"',
        ),
        ["union.note.mark: struct 'note_mark' is 46 bytes, not a multiple of the list's alignment, 4", *NOTE_REFS],
    ),
    "a prefix short of the list's alignment": (
        mutate(UNIONS, 'at = "u32"', 'at = "u8"'),
        ["union.note: prefix 'note_head' is 5 bytes, not a multiple of the list's alignment, 2", *NOTE_REFS],
    ),
    "a member holding an opaque ref": (
        mutate(UNIONS, 'flag = "u32"', 'flag = "token"') + "\n[[opaque_ref]]\n[opaque_ref.token]\n",
        [
            "union.note.mark: struct 'note_mark' has field 'flag' of opaque_ref 'token', whose size is each target's;"
            " a member has one layout on every target",
            *NOTE_REFS,
        ],
    ),
    "a member the length field cannot count": (
        mutate(
            UNIONS,
            '[struct.note_line]\nhead = "note_head"\nlabel = "text"',
            f'{_struct_of_bytes(65536)}[struct.note_line]\nhead = "note_head"\nlabel = "w13"',
        ),
        ["union.note.line: struct 'note_line' of 65544 bytes does not fit note_head.size (u16)", *NOTE_REFS],
    ),
    "a union in without _count": (
        mutate(UNIONS, NOTES, 'notes = { _type = "note", _ref = "in" }'),
        ['function.replay.notes: a union is passed as a list; it needs _ref = "in" and _count'],
    ),
    "a union out": (
        mutate(UNIONS, NOTES, NOTES.replace('"in"', '"out"')),
        ['function.replay.notes: a union with _ref = "out" is not implemented, only "in"'],
    ),
    "a union inout": (
        mutate(UNIONS, NOTES, NOTES.replace('"in"', '"inout"')),
        ['function.replay.notes: a union with _ref = "inout" is not implemented, only "in"'],
    ),
    "a union by value": (
        mutate(UNIONS, NOTES, 'notes = "note"'),
        ["function.replay.notes: union 'note' by value is not implemented"],
    ),
    "a union by value in a callback": (
        mutate(UNIONS, 'seen = { _type = "note", _ref = "in", _count = "u32" }', 'seen = "note"'),
        ["callback.on_notes.seen: union 'note' by value is not implemented in a callback"],
    ),
    "a union field": (
        UNIONS + '\n[[struct]]\n[struct.holder]\nn = "note"\n',
        ["struct.holder.n: a field of union 'note' is not implemented"],
    ),
    "a parameter named like the extent": (
        mutate(UNIONS, NOTES, f'{NOTES}\nnotes_bytes = "u32"'),
        ["function.replay.notes: its extent parameter notes_bytes is already a parameter"],
    ),
    "a parameter named like the count": (
        mutate(UNIONS, NOTES, f'{NOTES}\nnotes_count = "u32"'),
        ["function.replay.notes: its count parameter notes_count is already a parameter"],
    ),
    "a struct named like a union": (
        UNIONS + '\n[[struct]]\n[struct.note]\nx = "u32"\n',
        ["struct.note: type name already defined in union"],
    ),
    "a union named like a builtin": (
        mutate(UNIONS, "[union.note]", "[union.u32]"),
        ["union.u32: shadows builtin type u32", *NOTE_REFS],
    ),
    "a second count type for one union": (
        mutate(UNIONS, NOTES, NOTES.replace('"u32"', '"u16"')),
        [
            "function.replay.notes: union 'note' is counted by u16 here and by u32 at callback.on_notes.seen; "
            "one count type per union"
        ],
    ),
}


def buffer_expansion(param: model.Param) -> list[str]:
    """The C parameter names `param` becomes, as SPEC.md "Naming" states them independently of
    the model: a buffer `p` is `p`, `p_count`, and with `_wrote_needed` `p_wrote`, `p_needed`;
    a union's list `p` is `p`, `p_count`, `p_bytes`; a callback `p` is `p`, `p_user_data`."""
    if param.callback:
        return [param.name, f"{param.name}_user_data"]
    if param.count_type is None:
        return [param.name]
    if param.is_union:
        return [param.name, f"{param.name}_count", f"{param.name}_bytes"]
    reports = [f"{param.name}_wrote", f"{param.name}_needed"] if param.wrote_needed else []
    return [param.name, f"{param.name}_count", *reports]


def param_lists(text: str, pattern: str) -> dict[str, str]:
    """Function name -> parameter list text, for every `<pattern>xy_<f>(<params>)` in text."""
    return dict(re.findall(pattern + r"xy_(\w+)\(([^)]*)\)", text))


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI with `argv` (no program name); return (exit code, stdout, stderr). A
    usage error exits through argparse's `SystemExit`, whose code is returned the same."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = langxyne_main.main(argv)
        except SystemExit as e:
            code = e.code
    return code, stdout.getvalue(), stderr.getvalue()


def expected_constants(api: model.Api) -> dict[str, int | str]:
    """Every constant's unprefixed name and value, read from the model's own resolved
    values (a composed entry's sum was already computed, and a bit group's overlap-
    checked, by the loader), and each listed union's list alignment."""
    out: dict[str, int | str] = {"API_VERSION": api.version_value()}
    out |= {c.name.upper(): c.value for c in api.bit_consts}
    out |= {c.name.upper(): c.value for c in api.consts}
    out |= {e.name.upper(): e.value for t in api.typed_consts for e in t.entries}
    out |= {c.name.upper(): c.value for c in api.string_consts}
    out |= {naming.union_align(u.name).upper(): api.list_alignment(u) for u in api.listed_unions()}
    return out


# The fake_xy.rs variants whose builds tests/run-bindings.sh must refuse at their pins: three
# spellings of send the relay's fn-pointer pin refuses (its lifetime, its safety, its arity),
# and stream's sink moved to another thread, which its wrapper holding a raw pointer is not
# Send to reach.
FAKE_VARIANTS = {
    "static": (
        "pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>)",
        "pub fn send(hport: ffi::xy_port, buf: Option<&'static [u8]>)",
    ),
    "unsafe": (
        "pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>)",
        "pub unsafe fn send(hport: ffi::xy_port, buf: Option<&[u8]>)",
    ),
    "extra": (
        "pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>)",
        "pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>, _extra: u32)",
    ),
    "spawn": (
        "let Some(mut sink) = sink else {",
        "std::thread::scope(|s| { s.spawn(move || drop(sink)); });\n    let Some(mut sink) = sink else {",
    ),
}


def fake_variant(name: str) -> str:
    """fake_xy.rs with variant `name`'s one-line edit applied; its cdylib build fails at the
    needle tests/run-bindings.sh pins beside the name."""
    needle, replacement = FAKE_VARIANTS[name]
    return mutate((FIXTURES / "fake_xy.rs").read_text(encoding="utf-8"), needle, replacement)


def notes_stub(stub: str) -> str:
    """REFS's stub text with four functions' bodies replaced from fixtures, built by
    tests/run-bindings.sh over REFS's relay as the shared library `xy`: `open_port` gives a
    non-null handle, and for unit 7 a generation no `Mode` entry names
    (`refs_notes_open_port.rs`); `destroy_port` reports each port it releases on stderr
    (`refs_notes_destroy_port.rs`); `note` answers ok only for the notes (count,
    bytes) (1, 2), (3, 4) with the spots 1, 2, or for no notes with no spots, else err_busy
    (`refs_notes_note.rs`), so a binding's `in` arrays of a struct and of a boxed scalar are
    checked by what the library receives; and `observe` calls its sink once with the spots 1, 2
    (`refs_notes_observe.rs`), so a view of a boxed scalar is checked by what the binding hands
    its consumer."""
    sink_note = (
        "    // sink: call it only within this call; never keep it where the handle's state reaches it, since a "
        "handle dereference has no lifetime to stop it\n"
    )
    destroy = "pub fn destroy_port(hport: ffi::xy_port) -> Result<(), Status> {\n"
    # (the text replaced, what of it is kept before the fixture's body, the fixture)
    for needle, kept, fixture in (
        ("    let _ = pport;\n    let _ = pstats;\n    let _ = generation;\n", "", "refs_notes_open_port.rs"),
        (f"{destroy}    let _ = hport;\n", destroy, "refs_notes_destroy_port.rs"),
        (
            "    let _ = notes;\n    let _ = spots;\n    // replace: not implemented\n    Ok(())\n",
            "",
            "refs_notes_note.rs",
        ),
        # observe's body alone follows its signature's brace directly, stream's ending the same way
        (
            f"{{\n{sink_note}    let _ = sink;\n    // replace: not implemented\n    Ok(())\n",
            "{\n",
            "refs_notes_observe.rs",
        ),
    ):
        stub = mutate(stub, needle, kept + (FIXTURES / fixture).read_text(encoding="utf-8"))
    return stub


def values_tu(text: str = KITCHEN_SINK) -> str:
    """Asserts every constant's value, and every bit and plain constant's type, the one
    its group's `_base_type` names."""
    api = load(text)
    lines = ['#include "xy_api.h"']
    for key, value in expected_constants(api).items():
        name = f"XY_{key}"
        if isinstance(value, str):
            lines.append(f'_Static_assert(sizeof({name}) == {len(value) + 1}, "{name}");')
        else:
            lines.append(f'_Static_assert({name} == ({value}), "{name}");')
    for group in (*api.bit_const_groups, *api.const_groups):
        for c in group.entries:
            name = f"XY_{c.name.upper()}"
            lines.append(
                f'_Static_assert(_Generic({name}, {C_BASE_TYPES[group.base_type]}: 1, default: 0), "{name} type");'
            )
    lines.append("int main(void) { return 0; }")
    return "\n".join(lines) + "\n"


def layout_program(text: str) -> str:
    """A C program over `text`'s api printing each boxed scalar's, the text type's and each
    struct's size, `<Name> <size>`, and each field's offset, `<Name>.<field> <offset>`, Name its
    UpperCamel name. It compiles only where every union's prefix and member structs have the
    size and alignment `Api.layout()` gives and each field the offset the model's density
    places it at, the sum of the sizes before it."""
    api = load(text)
    rows = [(b.name, ["value"]) for b in api.boxed_scalars]
    if api.uses_text():
        rows.append((naming.TEXT, [n for n, _ in naming.TEXT_FIELDS]))
    rows += [(s.name, [f.name for f in s.fields]) for s in api.structs]
    lines = ["#include <stddef.h>", "#include <stdio.h>", '#include "xy_api.h"']
    structs = {s.name: s for s in api.structs}
    for union in api.unions:
        for name in dict.fromkeys((union.prefix, *(m.struct for m in union.members))):
            c_name, (size, align) = f"xy_{name}", api.layout(name)
            lines.append(f'_Static_assert(sizeof({c_name}) == {size} && _Alignof({c_name}) == {align}, "{c_name}");')
            offset = 0
            for f in structs[name].fields:
                lines.append(f'_Static_assert(offsetof({c_name}, {f.name}) == {offset}, "{c_name}.{f.name}");')
                offset += api.layout(f.type)[0]
    lines.append("int main(void) {")
    for name, fields in rows:
        c_name, camel = f"xy_{name}", naming.upper_camel(name)
        lines.append(f'  printf("{camel} %zu\\n", sizeof({c_name}));')
        lines += [f'  printf("{camel}.{f} %zu\\n", offsetof({c_name}, {f}));' for f in fields]
    return "\n".join([*lines, "  return 0;", "}"]) + "\n"


def go_constants_main(text: str, module: str) -> str:
    """main.go printing every constant of `text` as `key=value`, each name the one naming's
    own rules give it, the binding imported as package `xy_api` of module `module`."""
    api = load(text)
    names = {naming.unprefixed_const_name(naming.VERSION_KEY): naming.go_exported(naming.VERSION_KEY)}
    names |= {
        naming.unprefixed_const_name(name): naming.go_exported(name)
        for _, name in api.constant_names(enum_entries=False)
    }
    names |= {
        naming.unprefixed_const_name(e.name): naming.go_enum_entry(t.name, e.name)
        for t in api.typed_consts
        for e in t.entries
    }
    names |= {
        naming.unprefixed_const_name(naming.union_align(u.name)): naming.go_exported(naming.union_align(u.name))
        for u in api.listed_unions()
    }
    expected = expected_constants(api)
    # %d of an enum entry is its value, where %v would be its String()
    prints = "".join(
        f'\tfmt.Printf("{key}={"%s" if isinstance(expected[key], str) else "%d"}\\n", xy_api.{go})\n'
        for key, go in names.items()
    )
    return f'package main\n\nimport (\n\t"fmt"\n\n\t"{module}/xy_api"\n)\n\nfunc main() {{\n{prints}}}\n'
