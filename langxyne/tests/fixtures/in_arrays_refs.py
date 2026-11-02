"""Runs support.REFS's Python module (argv[1]) against refs_notes_library(): note's `in` array of a
struct, its elements instances, and of a boxed scalar, its elements the base type's values, reach
the library as given; observe hands its callable a view of boxed scalars whose elements are the
base type's values; Port(7), whose library writes a generation no Mode entry names, raises naming
it and releases the handle it made: the library's report of the release precedes this program's
"collected" on stderr."""

import gc
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("xy_api", sys.argv[1])
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

p = M.Port(1)
assert p.note([M.Stats(count=1, bytes=2), M.Stats(count=3, bytes=4)], [1, 2]) is None
assert p.note(None, []) is None
try:
    p.note([M.Stats(count=1, bytes=2)], [1, 2])
except M.Error as e:
    assert e.result is M.Status.ERR_BUSY
else:
    raise AssertionError("note took notes the library did not receive")

seen = []
assert M.observe(lambda spots, blob, mode: seen.append((list(spots), len(blob), mode))) is None
assert seen == [([1, 2], 0, M.Mode.FINE)], seen
assert all(type(spot) is int for spot in seen[0][0]), seen

try:
    M.Port(7)
except RuntimeError as e:
    assert "generation" in str(e), e
else:
    raise AssertionError("a generation no Mode entry names was taken")
gc.collect()
print("collected", file=sys.stderr, flush=True)
