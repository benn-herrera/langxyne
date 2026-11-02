"""Runs support.KITCHEN_SINK's Python module (argv[1]) against either fake's shared library `xy`.

Prints NAME=value for every constant; every check is an assert, so a failure exits nonzero
naming its line. Beside check_xy.lua's steps: configure and spend take mint()'s token; a handle
argument that is an int, another opaque's handle or the null TokenHandle, and a TokenHandle made
from a value, are refused; copying, deep-copying or pickling a Port or a raw handle raises
TypeError, a Port takes no new attribute, its docstring says its calls are mutually exclusive and
a DataLink's, which has no dtor, that it is not safe for concurrent use; an int, enum or count
outside its type raises ValueError naming its parameter, a count or struct of the wrong type
TypeError; a memory inout counts bytes; a port released while stream's
cuts are converted is refused before the call. The list capacities (items,
labels) of consumer_xy.rs's codes 21 to 28; stream as its codes 30 to 37; 38 a callable raising on
its second call: stream raises that same exception object, the callable having run exactly twice,
and a following stream(0) succeeds; a non-callable sink raises TypeError naming it; a callable
raising KeyboardInterrupt on its first call: stream raises the same object, the callable having
run once, and a following stream(0) succeeds; a view kept past its callback raises ValueError on
use; an element read from a view is a copy valid after the call; a view read on another thread
raises ValueError; call_during_call: seek(1 << 40) on a port, and attach(p) on a DataLink, each
raise Error(Status.ERR_BUSY) without reaching the library, from inside stream(1)'s callable and
from another thread while it blocks there on an Event, and succeed after the stream;
release_during_call: release() the same, send succeeding after the stream; 42 notify(1) calls
each callable once with Mode.SLOW; 43 notify(1) whose first callable raises: second never runs, and the exception is
raised, first having run once; 44 notify(7): a RuntimeError naming xy_on_mode and mode is raised,
neither callable having run; 45 stream(98), whose library calls the sink eight times whatever it
answers, with a callable raising on its second call: it runs twice, its exception is raised, and
seek(98) then succeeds, the library having seen a stop; 46 a callable answering 0.5, 2**40 or True
raises TypeError naming xy_on_batch, having run once; 47 resolve reads a bytes arena and a byte
view while its callback runs, within its count; call_after_release: the handle read before it is
null, and send and attach(p) raise ValueError; release_twice: the second release raises
ValueError; context_manager: a with block releases its port, a release after it raises
ValueError, and an exception raised inside it propagates, the port released. Every non-zero
named result raises Error, its result the enum.

With a second argument, one step for run-bindings.sh alone: "open", a port opened and released;
"select", seek(12345); "nested",
under the C++ fake, stream(96)'s callable calling seek(96) on a second port, during which the
library calls the sink again: answered stop without reaching the callable, and stream raises
naming the nested call; "nested95", under the C++ fake, the same through stream(95), whose library
goes on calling the sink: the callable ran once, and seek(95) succeeds, the library having seen
its first call answered stop; "outside", under the C++ fake, stream(97), whose library passes a
null view with a count of 1: stream raises RuntimeError naming xy_on_batch and fresh;
"off_thread", under the C++ fake, stream(99), whose library calls the sink from a thread of its
own: stream raises naming xy_on_batch and xy_stream, the callable never called; "unhidden", the
module of support.UNHIDDEN_PORT, whose Port has no lock: its docstring says it is not safe for
concurrent use, seek from inside stream(1)'s callable raises Error(Status.ERR_BUSY), a with block
releases it, clearing its handle, and a release after that reaches the library, which answers
the null handle ERR_OTHER; "notes", consumer_xy.cpp's 50 to 53 against either fake: stream_notes
for batch 2, 4 and 0, after calls of 2, 2, 2 notes (of 4, 2; of 6), each view's NoteSequence
walked to its count with no refusal and each record printed by its structure's class; at each
call fresh's records are seen's last ones by value, the counts add up, every offset recorded so
far resolves through seen.at to its record and each of fresh's through fresh.at, each offset in
units of the list's alignment, and seen.at of byte 4 and of its extent raise UnionError, "offset is not a record's start", at the record after
the offset; nothing outlives a call but offsets and lines, and a NoteSequence kept past its
callback raises ValueError on use. Its stdout is the batch-2 stream's records, one line each, as
consumer_xy.cpp writes them. "notes <selector>", 101 to 105, against the C++ fake: the stream's
second call is refused in both views, each refusal raised as UnionError naming its view, index,
offset and clause and written on stderr as `xy_on_notes: <view>: record <i> at offset <o>:
<clause>`, the callable answering Flow.HALT, and the process exits with the selector; 100 where the
selector is not a decimal number below 256, no view was refused, the stream did not raise
Error(Status.ERR_AGAIN), or seen's refusal is not fresh's past the earlier records.
"notes 106", against the C++ fake: seen.at of byte 16, the record past seen's count, raises
UnionError, written on stderr as raised, the callable answering Flow.HALT, and the process exits
106; 100 where at did not raise or the stream did not raise Error(Status.ERR_AGAIN).
"""

import array
import copy
import gc
import importlib.util
import pickle
import sys
import threading

spec = importlib.util.spec_from_file_location("xy_api", sys.argv[1])
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def raises(kind, call, *args):
    """The exception `call(*args)` raises, which must be a `kind`."""
    try:
        call(*args)
    except kind as e:
        return e
    raise AssertionError(f"{call} did not raise {kind.__name__}")


def stream(port, batch, cuts, halt_on=None):
    """stream(batch, cuts), its sink answering halt on call `halt_on`: the exception it raised or
    None, each call's (seen, fresh, last) counts, and whether every view held what the fakes
    promise."""
    calls, views = [], [True]

    def sink(seen, fresh, arena, last):
        calls.append((len(seen), len(fresh), last))
        for i in range(len(fresh)):
            views[0] = views[0] and fresh[i].id == seen[len(seen) - len(fresh) + i].id
        for i, entry in enumerate(seen):
            views[0] = views[0] and M.resolve(entry.label, arena) == f"e{i}".encode()
        views[0] = views[0] and M.resolve(M.Text(len(arena), 2), arena) is None
        return M.Flow.HALT if len(calls) == halt_on else None

    try:
        port.stream(batch, cuts, sink)
    except M.Error as e:
        return e.result, calls, views[0]
    return None, calls, views[0]


def streamed(calls, fresh, final):
    """Whether `calls` hold the fresh counts `fresh`, seen counting them up, the last one alone
    final where `final`."""
    seen, expected = 0, []
    for i, count in enumerate(fresh):
        seen += count
        expected.append((seen, count, 1 if final and i == len(fresh) - 1 else 0))
    return calls == expected


def during_call(port, attempt):
    """The two Errors `attempt()` raises, once from inside port.stream(1)'s callback and once from
    another thread while that callback blocks on an Event; the stream itself succeeds."""
    entered, leave, inside, done = threading.Event(), threading.Event(), [], []

    def sink(*_):
        if not entered.is_set():
            inside.append(raises(M.Error, attempt))
            entered.set()
            leave.wait(10)

    runner = threading.Thread(target=lambda: done.append(port.stream(1, [], sink)))
    runner.start()
    try:
        assert entered.wait(10)
        outside = raises(M.Error, attempt)
    finally:
        leave.set()
        runner.join()
    assert done == [None], done
    return inside[0], outside


def call_during_call():
    """A call on a port, or a port passed as an argument, while a call of it runs raises busy."""
    p, link = M.Port(1), M.DataLink()
    for attempt in (lambda: p.seek(1 << 40), lambda: link.attach(p)):
        assert all(e.result is M.Status.ERR_BUSY for e in during_call(p, attempt))
    assert p.seek(1 << 40) is None and link.attach(p) is None
    p.release()


def release_during_call():
    """A release while a call of the port runs raises busy and releases nothing."""
    p = M.Port(1)
    assert all(e.result is M.Status.ERR_BUSY for e in during_call(p, p.release))
    assert p.send(b"abcd") is None
    p.release()


def call_after_release(p, link):
    """After release the one handle every holder reads is null, and every use raises ValueError."""
    handle = p.handle
    assert p.release() is None
    assert handle.value is None
    assert "Port used after destroy_port" in str(raises(ValueError, p.send, b"abcd"))
    assert "hport is a Port used after destroy_port" in str(raises(ValueError, link.attach, p))


def release_twice():
    """A second release raises ValueError, never reaching the library, which answers ERR_OTHER."""
    p = M.Port(1)
    assert p.release() is None
    assert "Port used after destroy_port" in str(raises(ValueError, p.release))


def context_manager():
    """A with block releases its port at its end, after which release raises; an exception
    raised inside the block propagates, the port released."""
    with M.Port(1) as q:
        assert q.generation == 7
    assert q.handle is None
    assert "Port used after destroy_port" in str(raises(ValueError, q.release))
    failure, held = KeyError("raised inside the block"), []

    def inside():
        with M.Port(1) as r:
            held.append(r)
            raise failure

    assert raises(KeyError, inside) is failure and held[0].handle is None


def checks():
    for name, value in vars(M).items():
        if name.isupper() and not name.startswith("_") and type(value) in (int, str):
            print(f"{name}={value}")

    assert M.status_to_string(9) == "ERR_BUSY"
    assert M.status_to_string(12345) == "UNKNOWN_STATUS"
    assert M.mode_to_string(1) == "SLOW"
    assert M.access_to_string(3) == "ACC_A|ACC_B"
    assert M.access_to_string(1) == "ACC_A"
    assert M.access_to_string(0) == "NONE"
    assert M.access_to_string(9) == "ACC_A|0x8"
    assert M.access_to_string(-1) == "ACC_A|ACC_B|0xfffffffc"
    assert M.limit_to_string(16) == "MAX_UNITS"
    assert M.limit_to_string(M.NEG) == "NEG"
    assert M.limit_to_string(M.FLOOR) == "FLOOR"
    assert M.limit_to_string(99) == "UNKNOWN"
    token = M.mint()
    assert isinstance(token, M.TokenHandle) and M.spend(token) is None
    assert M.reset() is None

    assert raises(M.Error, M.Port, 99).result is M.Status.ERR_BUSY

    p = M.Port(3)
    assert p.pstats.count == 3 and p.pstats.bytes == 1 << 40 and p.generation == 7
    assert p.pwrap.inner.count == 3 and p.pwrap.n == 11

    # a handle argument is a raw handle the module issued for its opaque, never an int or another's
    raises(TypeError, M.spend, 0x41)
    raises(TypeError, M.spend, p.handle)
    raises(TypeError, M.TokenHandle, 0x41)
    assert "htoken is a null TokenHandle" in str(raises(ValueError, M.spend, M.TokenHandle()))
    # an object owns its handle, and a raw handle is the module's alone
    for copying in (copy.copy, copy.deepcopy, pickle.dumps):
        raises(TypeError, copying, p)
        raises(TypeError, copying, token)
    raises(AttributeError, setattr, p, "x", 1)
    assert M.Port.__doc__.endswith(
        "Its calls are mutually exclusive: a call or a release during another call of the same object, "
        "from a callback or another thread, raises rather than waits."
    )
    assert M.DataLink.__doc__.endswith("Not safe for concurrent use: one thread at a time.")
    raises(TypeError, p.configure, "x", 6, M.Mode.SLOW, token)

    assert p.send(b"abcd") is None
    assert p.send(bytearray(b"abcd")) is None
    assert raises(M.Error, p.send, b"abc").result is M.Status.ERR_BUSY
    assert p.recv(5) == b"rr\0rr"
    assert p.configure(M.Stats(count=5), 6, M.Mode.SLOW, token) is None
    raises(TypeError, p.send, 42)
    # an argument outside its type is refused naming its parameter, before anything is allocated
    for call, args, parameter in (
        (p.recv, (2**32,), "pdst_count"),
        (p.recv, (-1,), "pdst_count"),
        (p.list, (2**64, 0), "items_count"),
        (p.seek, (2**64 + 96,), "offset"),
        (p.configure, (M.Stats(count=5), 6, 7, token), "mode"),
        (p.stream, (0, [2**32 + 1], lambda *_: None), "cuts"),
    ):
        assert parameter in str(raises(ValueError, call, *args)), (call, args)
    raises(TypeError, p.recv, "3")

    out, count, link = p.stats_of()
    assert out.count == 42 and count == 43 and link is not None

    level, tally, data = p.bump(4, M.Stats(count=5), b"abc")
    assert level == 5 and tally.count == 10 and data == b"bcd"
    # a memory inout counts bytes, whatever the item size of the bytes-like value
    assert p.bump(4, M.Stats(count=5), array.array("H", [0x6261, 0x63]))[2] == b"bcd\x01"

    assert p.seek(1 << 40) is None
    assert raises(M.Error, p.seek, 48).result is M.Status.ERR_BUSY
    assert p.tune(-3, -(1 << 40), 200, 0.5) == (-(1 << 40) - 1, -4)
    assert raises(M.Error, p.tune, -3, -(1 << 40), 199, 0.5).result is M.Status.ERR_BUSY

    assert p.annotate(None) is None
    assert p.annotate(M.Stats(count=7)) is None
    assert raises(M.Error, p.annotate, M.Stats(count=1)).result is M.Status.ERR_BUSY

    # _optional memory in, scalar in and scalar inout: None passes through as a null pointer
    mode, no_level, peek = p.probe(None, None, None)
    assert mode is M.Mode.SLOW and no_level is None and peek == 9
    assert p.probe(b"ab", 3, 4)[1] == 5
    assert raises(M.Error, p.probe, b"abc", None, None).result is M.Status.ERR_BUSY
    # an empty bytes-like value is a present, zero-length payload, which the fake refuses
    assert raises(M.Error, p.probe, b"", None, None).result is M.Status.ERR_BUSY

    # a boxed scalar: the caller passes and receives its base type's value
    assert p.echo_offset(1 << 40) == 1 << 40

    items, items_wrote, items_needed, labels, labels_wrote, labels_needed = p.list(0, 0)
    assert len(items) == 0 and items_wrote == 0 and items_needed == 3
    assert labels == b"" and labels_wrote == 0 and labels_needed == 6
    items, items_wrote, _, labels, _, _ = p.list(1, 2)
    assert items_wrote == 1 and items[0].id == 10 and labels == b"e0" and M.resolve(items[0].label, labels) == b"e0"
    items, items_wrote, _, labels, _, _ = p.list(2, 3)
    assert items_wrote == 2 and items[1].id == 11 and labels == b"e0e" and M.resolve(items[1].label, labels) is None
    items, _, _, labels, _, _ = p.list(3, 6)
    assert [M.resolve(items[i].label, labels) for i in range(3)] == [b"e0", b"e1", b"e2"]
    assert p.list(5, 8)[1:] == (3, 3, b"e0e1e2", 6, 6)
    for items_count, labels_count, buffer in ((4, 6, "items"), (6, 6, "items"), (3, 5, "labels")):
        assert f"xy_list over-reported {buffer}" in str(raises(RuntimeError, p.list, items_count, labels_count))

    result, calls, views = stream(p, 1, [])
    assert result is None and views and streamed(calls, [1, 1, 1, 1, 1, 1, 1, 0], True)
    result, calls, _ = stream(p, 3, [])
    assert result is None and streamed(calls, [3, 3, 1], True)
    result, calls, _ = stream(p, 0, [])
    assert result is None and streamed(calls, [7], True)
    result, calls, _ = stream(p, 3, [M.Cut.AFTER_ONE, M.Cut.AFTER_FOUR])
    assert result is None and streamed(calls, [2, 3, 2], True)
    result, calls, _ = stream(p, 0, [M.Cut.AFTER_FOUR])
    assert result is None and streamed(calls, [5, 2], True)
    result, calls, _ = stream(p, 1, [], 3)
    assert result is M.Status.ERR_AGAIN and streamed(calls, [1, 1, 1], False)
    result, calls, _ = stream(p, 3, [], 1)
    assert result is M.Status.ERR_AGAIN and streamed(calls, [3], False)
    result, calls, views = stream(p, 3, [])
    assert views and len(calls) == 3

    runs, failure = [0], ValueError("the consumer's sink raises on its second call")

    def failing(*_):
        runs[0] += 1
        if runs[0] == 2:
            raise failure

    assert raises(ValueError, p.stream, 1, [], failing) is failure and runs[0] == 2
    result, calls, _ = stream(p, 0, [])
    assert result is None and streamed(calls, [7], True)
    assert "sink" in str(raises(TypeError, p.stream, 1, [], 42))

    # any BaseException is the call's failure, raised again as the same object
    interrupts, interrupt = [], KeyboardInterrupt()

    def interrupted(*_):
        interrupts.append(None)
        raise interrupt

    assert raises(KeyboardInterrupt, p.stream, 1, [], interrupted) is interrupt and len(interrupts) == 1
    result, calls, _ = stream(p, 0, [])
    assert result is None and streamed(calls, [7], True)

    kept = []
    assert p.stream(0, [], lambda seen, fresh, arena, last: kept.append(arena)) is None
    raises(ValueError, len, kept[0])
    raises(ValueError, M.resolve, M.Text(0, 2), kept[0])
    # an element read from a view is a copy of its own, valid after the call
    elements = []
    assert p.stream(0, [], lambda seen, fresh, arena, last: elements.append(seen[0])) is None
    assert elements[0]._b_base_ is None and elements[0].id == 10
    # a view read on another thread than its callback's is refused
    elsewhere = []

    def reading_elsewhere(seen, fresh, arena, last):
        def read():
            try:
                len(seen)
            except ValueError as e:
                elsewhere.append(e)

        reader = threading.Thread(target=read)
        reader.start()
        reader.join()

    assert p.stream(0, [], reading_elsewhere) is None and len(elsewhere) == 1

    call_during_call()
    release_during_call()
    link = M.DataLink()
    raises(TypeError, link.attach, p.handle)

    firsts, seconds = [], []
    assert p.notify(1, firsts.append, seconds.append) is None
    assert firsts == [M.Mode.SLOW] and seconds == [M.Mode.SLOW]
    first_runs, second_runs = [0], [0]

    def first(mode):
        first_runs[0] += 1
        raise KeyError("the consumer's first callback raises")

    def second(mode):
        second_runs[0] += 1

    raises(KeyError, p.notify, 1, first, second)
    assert first_runs == [1] and second_runs == [0]
    first_runs[0] = 0
    message = str(raises(RuntimeError, p.notify, 7, first, second))
    assert "xy_on_mode" in message and "mode" in message and first_runs == [0] and second_runs == [0]

    # batch 98 calls the sink eight times whatever it answers
    runs[0] = 0
    assert raises(ValueError, p.stream, 98, [], failing) is failure and runs[0] == 2
    assert p.seek(98) is None

    answers = []

    def fraction(*_):
        answers.append(0.5)
        return 0.5

    assert "xy_on_batch" in str(raises(TypeError, p.stream, 0, [], fraction)) and len(answers) == 1
    for answer in (2**40, True):
        assert "xy_on_batch" in str(raises(TypeError, p.stream, 0, [], lambda *_, answer=answer: answer)), answer

    assert M.resolve(M.Text(2, 2), b"e0e1") == b"e1"
    assert M.resolve(M.Text(2, 2), b"e0e") is None
    resolved = []

    def resolving(seen, fresh, arena, last):
        resolved.append((M.resolve(seen[1].label, arena), arena[2:4], arena[0]))

    assert p.stream(0, [], resolving) is None and resolved == [(b"e1", b"e1", ord("e"))]

    call_after_release(p, link)
    release_twice()

    # a handle's state is checked after every conversion, which may run the consumer's code
    r = M.Port(1)

    def releasing_cuts():
        r.release()
        yield M.Cut.AFTER_ONE

    assert "destroy_port" in str(raises(ValueError, r.stream, 0, releasing_cuts(), lambda *_: None))

    assert M.DataLink().handle is not None

    ports = [M.Port(i) for i in range(1, 5)]
    del ports
    gc.collect()
    context_manager()
    M.Port(2).release()


def note_text(record):
    """A record's line of stdout's text form, by its structure's class."""
    head = record.head
    if isinstance(record, M.NoteLine):
        return f"line {head.kind} {head.size} {head.at} {record.label.offset} {record.label.length}"
    if isinstance(record, M.NoteMark):
        return f"mark {head.kind} {head.size} {head.at} {record.value} {record.flag}"
    raise AssertionError(f"{record!r} is no member of note")


def walk(sequence):
    """Each record's (offset, line), in order, as far as the walk went, and the UnionError it
    raised, None where it raised none."""
    notes, offset = [], 0
    try:
        for record in sequence:
            notes.append((offset, note_text(record)))
            offset += record.head.size
    except M.UnionError as error:
        return notes, error
    return notes, None


def refusal_names(error, view):
    """Whether `error`'s message names on_notes' view, the record's index and offset and the clause."""
    clause = f"refused at record {error.index}, offset {error.offset}: {error.clause}"
    return str(error) == f"xy_on_notes received view {view} {clause}"


def note_at(sequence, offset):
    """The record `sequence.at` finds at byte `offset`, which it takes in units of the list's
    alignment."""
    return sequence.at(offset // M.NOTE_ALIGN)


def not_a_start(seen, offset):
    """The (index, offset, clause) of the UnionError seen's at raises at byte `offset`, naming them."""
    error = raises(M.UnionError, note_at, seen, offset)
    assert refusal_names(error, "seen"), error
    return error.index, error.offset, error.clause


def check_notes(seen, fresh, kept):
    """One call of stream_notes' callable: `kept` holds every (offset, line) earlier calls
    delivered, at its offset in seen, and gains fresh's."""
    seen_notes, seen_error = walk(seen)
    fresh_notes, fresh_error = walk(fresh)
    assert seen_error is None and fresh_error is None, (seen_error, fresh_error)
    before = seen.bytes - fresh.bytes
    assert before >= 0 and len(seen) == len(kept) + len(fresh) and len(fresh_notes) == len(fresh)
    # fresh is seen's tail: its records are seen's last ones, compared by value since each is a copy
    assert [(before + offset, text) for offset, text in fresh_notes] == seen_notes[len(kept) :]
    kept += [(before + offset, text) for offset, text in fresh_notes]
    assert seen_notes == kept
    assert all(note_text(note_at(seen, offset)) == text for offset, text in kept)
    assert all(note_text(note_at(fresh, offset)) == text for offset, text in fresh_notes)
    clause = "offset is not a record's start"
    assert not_a_start(seen, 4) == (1, 4, clause)
    assert not_a_start(seen, seen.bytes) == (len(seen), seen.bytes, clause)


def notes():
    """stream_notes for batch 2, 4 and 0, every call checked; the batch-2 stream's lines on stdout."""
    p = M.Port(3)
    for batch, calls in ((2, [2, 2, 2]), (4, [4, 2]), (0, [6])):
        kept, fresh_counts = [], []

        def sink(seen, fresh, kept=kept, fresh_counts=fresh_counts):
            fresh_counts.append(len(fresh))
            check_notes(seen, fresh, kept)

        assert p.stream_notes(batch, sink) is None and fresh_counts == calls, (batch, fresh_counts)
        if batch == 2:
            for _, text in kept:
                print(text)
    held = []
    assert p.stream_notes(0, lambda seen, fresh: held.append(seen)) is None
    message = "a view is valid only on its callback's thread, until its callback returns"
    for use in (len, list, lambda sequence: sequence.at(0), lambda sequence: sequence.bytes):
        assert str(raises(ValueError, use, held[0])) == message
    p.release()


def refused_notes(selector):
    """The `notes <selector>` step's exit status."""
    if not selector.isdecimal() or int(selector) > 255:
        return 100
    refusals, earlier = {}, []

    def sink(seen, fresh):
        walked = {"seen": walk(seen)[1], "fresh": walk(fresh)[1]}
        if walked["seen"] is None and walked["fresh"] is None:
            return None
        for view, error in walked.items():
            if error is not None:
                print(
                    f"xy_on_notes: {view}: record {error.index} at offset {error.offset}: {error.clause}",
                    file=sys.stderr,
                )
                refusals[view] = error
        earlier.append((len(seen) - len(fresh), seen.bytes - fresh.bytes))
        return M.Flow.HALT

    p = M.Port(3)
    try:
        p.stream_notes(int(selector), sink)
        result = M.Status.OK
    except M.Error as error:
        result = error.result
    p.release()
    seen, fresh = refusals.get("seen"), refusals.get("fresh")
    if result is not M.Status.ERR_AGAIN or seen is None or fresh is None:
        return 100
    [(earlier_count, earlier_bytes)] = earlier
    shifted = (earlier_count + fresh.index, earlier_bytes + fresh.offset, fresh.clause)
    if (
        not all(refusal_names(e, view) for view, e in refusals.items())
        or (seen.index, seen.offset, seen.clause) != shifted
    ):
        return 100
    return int(selector)


def at_past_count():
    """The `notes 106` step's exit status."""
    refusals = []

    def sink(seen, fresh):
        try:
            note_at(seen, 16)
        except M.UnionError as error:
            print(error, file=sys.stderr)
            refusals.append(error)
        return M.Flow.HALT

    p = M.Port(3)
    try:
        p.stream_notes(106, sink)
        result = M.Status.OK
    except M.Error as error:
        result = error.result
    p.release()
    return 106 if result is M.Status.ERR_AGAIN and refusals else 100


def step(name):
    if name == "open":
        M.Port(3).release()
    elif name == "select":
        # a named result other than ok is the library's answer; an unnamed one raises RuntimeError
        try:
            M.Port(3).seek(12345)
        except M.Error:
            pass
    elif name == "nested":
        p, q, runs = M.Port(1), M.Port(2), []

        def sink(*_):
            runs.append(q.seek(96))

        message = str(raises(RuntimeError, p.stream, 96, [], sink))
        assert runs == [None], runs
        assert message == "xy_on_batch called again while a call of it was running in xy_stream", message
    elif name == "nested95":
        p, q, runs = M.Port(1), M.Port(2), []

        def sink(*_):
            runs.append(q.seek(96))

        message = str(raises(RuntimeError, p.stream, 95, [], sink))
        assert runs == [None], runs
        assert message == "xy_on_batch called again while a call of it was running in xy_stream", message
        # the library saw its first call answered stop, though the callable answered None
        assert p.seek(95) is None
    elif name == "outside":
        message = str(raises(RuntimeError, M.Port(3).stream, 97, [], lambda *_: None))
        assert "xy_on_batch" in message and "fresh" in message, message
    elif name == "off_thread":
        runs = []
        message = str(raises(RuntimeError, M.Port(3).stream, 99, [], runs.append))
        assert not runs and message == "xy_on_batch called on another thread than the one calling xy_stream", message
    elif name == "unhidden":
        assert M.Port.__doc__.endswith("Not safe for concurrent use: one thread at a time.")
        p, inside = M.Port(1), []

        def sink(*_):
            if not inside:
                inside.append(raises(M.Error, p.seek, 1 << 40))

        assert p.stream(1, [], sink) is None and inside[0].result is M.Status.ERR_BUSY
        with p:
            pass
        assert p.handle.value is None
        assert raises(M.Error, p.release).result is M.Status.ERR_OTHER
    elif name == "notes":
        notes()
    else:
        raise AssertionError(f"no step {name}")


if len(sys.argv) > 3 and sys.argv[2] == "notes":
    sys.exit(at_past_count() if sys.argv[3] == "106" else refused_notes(sys.argv[3]))
elif len(sys.argv) > 2:
    step(sys.argv[2])
else:
    checks()
