"""XY32, KITCHEN_SINK at 32 bits, and its fake, for the outputs a 64-bit type has no place in:
the Node binding and the wasm shim beside the relay it loads; XY32 with an unlocked port;
FIXTURE at 32 bits; and what the loop's round trip over consuming definitions needs of the two
outputs."""

from langxyne.emitters import EMITTERS
from langxyne.tests.support import FIXTURE, FIXTURES, KITCHEN_SINK, load, mutate

# FIXTURE at 32 bits, which every output renders: the definition generation's tests select every
# output over.
FIXTURE32 = mutate(FIXTURE, '"u64"', '"u32"', every=True)

# u32 and i32 hold no 1 << 40, the value seek accepts, tune's big and the stats' bytes; their
# 32-bit counterparts take 1 << 20, so the docstrings say what the fake does. bump takes data
# before tally, so a struct accessor read at tally's check runs after data's; stream needs a
# stack of max_units MiB.
_BUMP_TALLY = 'tally = { _type = "stats", _ref = "inout" }\n'
_BUMP_DATA = 'data = { _type = "memory", _ref = "inout", _count = "u32" }\n'
_STREAM_CUTS = 'cuts = { _type = "cut", _ref = "in", _count = "u32" }\n'
XY32 = mutate(
    mutate(
        mutate(
            mutate(mutate(KITCHEN_SINK, '"u64"', '"u32"', every=True), '"i64"', '"i32"', every=True),
            "1 << 40",
            "1 << 20",
            every=True,
        ),
        _BUMP_TALLY + _BUMP_DATA,
        _BUMP_DATA + _BUMP_TALLY,
    ),
    _STREAM_CUTS,
    '_stack_mb = "max_units"\n' + _STREAM_CUTS,
)

# XY32 with its port's _hides_pointer unset, as UNHIDDEN_PORT is made from KITCHEN_SINK: the same
# C ABI, so its Node binding loads XY32's module.
XY32_UNHIDDEN = mutate(XY32, ", _hides_pointer = true }", " }")


def fake_xy32() -> str:
    """fake_xy.rs under XY32's substitutions, the shim included beside the relay for a wasm
    build, so seek(u32::MAX) panics; written into the loop's scratch, never tracked."""
    text = (FIXTURES / "fake_xy.rs").read_text(encoding="utf-8")
    text = mutate(text, "u64", "u32", every=True)
    text = mutate(text, "i64", "i32", every=True)
    text = mutate(text, "1 << 40", "1 << 20", every=True)
    text = mutate(text, "0x100_0000_0000", "0x10_0000")
    # u64::from(ENTRIES) widened a u32; as u32 it is the conversion clippy refuses as useless
    text = mutate(text, "u32::from(ENTRIES)", "ENTRIES")
    text = mutate(
        text,
        "    tally: Option<&mut Stats>,\n    data: Option<&mut [u8]>,\n",
        "    data: Option<&mut [u8]>,\n    tally: Option<&mut Stats>,\n",
    )
    return with_shim(text, "xy_api")


def round_trip_outputs(text: str) -> str:
    """The `--outputs` the consuming definitions' round trip generates definition `text` with:
    every output, `wasm_rs` and `node` among them, but the Node binding where its every objection
    to the definition is that it is not implemented; any other objection fails the generation."""
    objections = EMITTERS["node"].validate(load(text))
    unimplemented = bool(objections) and all(o.endswith("is not implemented") for o in objections)
    return ",".join(t for t in EMITTERS if t != "node" or not unimplemented)


def with_shim(crate_root: str, name: str) -> str:
    """`crate_root`, a fake or a stub including the relay of the definition `name`, with the wasm
    shim included beside the relay for a wasm build, as SPEC.md's shim section states."""
    return mutate(
        crate_root,
        f'"/{name}_abi.rs"));\n',
        f'"/{name}_abi.rs"));\n'
        '    #[cfg(target_family = "wasm")]\n'
        f'    include!(concat!(env!("LANGXYNE_RUST_DIR"), "/{name}_wasm.rs"));\n',
    )
