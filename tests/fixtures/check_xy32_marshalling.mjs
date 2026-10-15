// Runs support_xy32.XY32's Node binding, ./xy_api.mjs beside this file with its declarations,
// against the Rust fake built for wasm32-wasip1 as ./xy.wasm: what each call passes and returns,
// one step per run, its first argument:
//   constants  NAME=value for every constant the module exports, which run-bindings.sh compares
//              with the model's, after the conversions' answers are checked
//   calls      every function's marshalling: the constructor's cached outs and its refusal; raw
//              handles only an instance issues; bytes, counts and structs in, out and inout; an
//              argument outside its type refused naming its parameter, an enum of the wrong type
//              a TypeError and one no entry names a RangeError, before anything is
//              allocated; an argument copied at its check, whatever a later check's accessor
//              does to its buffer; an out buffer past 2**31 - 1 bytes refused; optional
//              parameters; buffers with reports, over-reports refused;
//              arrays in (stream's cuts) and out (list's items); notify's two callbacks and an
//              unnamed enum passed to one; answers that are not an integer of the return enum's
//              base type; resolve over bytes and a byte view; release, use after it, a second
//              release, `using`, and an object argument released
//   load       xy.wasm a WASI reactor, exporting _initialize and no _start; the module from an
//              absolute path; a relative one refused; a missing file refused
//   notes      stream_notes for batch 2, 4 and 0, as check_xy.py's `notes`: the batch-2 stream's
//              records on stdout, every record walked and found again by `at` in units of the
//              list's alignment, at of a byte inside a record and of the extent refused, a
//              fractional index refused as not an integer
//   notes N    for N of 101 to 106, check_xy.py's exit status: 100 against this fake, which
//              refuses no record
//   stack      stream, whose _stack_mb names max_units, on a worker thread of this file 1 MiB
//              below that stack, refused naming both sizes before its arguments are checked,
//              and on one at it, where it runs
// Every check throws, so a failure exits 1 naming it.
import { readFileSync, writeSync } from "node:fs";
import process from "node:process";
import { WASI } from "node:wasi";
import { join } from "node:path";
import { Worker, isMainThread, workerData } from "node:worker_threads";
import * as M from "./xy_api.mjs";
import { check, here, load, out, refused, stream, streamed, text, throws } from "./check_xy32_shared.mjs";

const lib = M.load(new WASI({ version: "preview1" }));

function constants() {
  check(M.status_to_string(9) === "ERR_BUSY" && M.status_to_string(12345) === "UNKNOWN_STATUS", "status_to_string");
  check(M.mode_to_string(1) === "SLOW", "mode_to_string");
  check(M.access_to_string(3) === "ACC_A|ACC_B" && M.access_to_string(0) === "NONE", "access_to_string");
  check(M.access_to_string(9) === "ACC_A|0x8" && M.access_to_string(-1) === "ACC_A|ACC_B|0xfffffffc", "leftover bits");
  check(M.limit_to_string(M.NEG) === "NEG" && M.limit_to_string(99) === "UNKNOWN", "limit_to_string");
  for (const [name, value] of Object.entries(M)) {
    if (/^[A-Z][A-Z0-9_]*$/.test(name) && (typeof value === "number" || typeof value === "string")) {
      out(`${name}=${value}`);
    }
  }
}

function calls() {
  refused(() => new lib.Port(99), M.Status.ERR_BUSY);
  const p = new lib.Port(3);
  check(p.pstats.count === 3 && p.pstats.bytes === 1 << 20 && p.generation === 7, "cached outs");
  check(p.pwrap.inner.count === 3 && p.pwrap.n === 11, "a nested struct out");
  const minted = lib.mint();
  check(minted instanceof M.TokenHandle, "mint");
  const token = /** @type {M.TokenHandle} */ (minted);
  check(lib.spend(token) === undefined, "spend");
  check(lib.reset() === undefined, "reset");
  // @ts-expect-error a raw handle is one an instance issued, never a number
  throws(() => lib.spend(0x41), TypeError, "htoken must be a TokenHandle");
  // @ts-expect-error nor another opaque's
  throws(() => lib.spend(p.handle), TypeError, "htoken");
  // @ts-expect-error nor one made
  throws(() => new M.TokenHandle(), TypeError);
  const foreign = /** @type {M.TokenHandle} */ (load(join(here, "xy.wasm")).mint());
  throws(() => lib.spend(foreign), TypeError, "this instance issued");

  check(p.send(new Uint8Array(4)) === undefined && p.send(new ArrayBuffer(4)) === undefined, "send");
  refused(() => p.send(new Uint8Array(3)), M.Status.ERR_BUSY);
  check(text(p.recv(5)) === "rr\0rr", "recv");
  check(p.configure({ count: 5, bytes: 0 }, 6, M.Mode.SLOW, token) === undefined, "configure");
  // an argument outside its type is refused naming its parameter, before anything is allocated
  throws(() => p.recv(2 ** 32), RangeError, "pdst_count");
  throws(() => p.recv(-1), RangeError, "pdst_count");
  throws(() => p.seek(2 ** 32), RangeError, "offset");
  // @ts-expect-error a mode no entry names
  throws(() => p.configure({ count: 5, bytes: 0 }, 6, 7, token), RangeError, "mode");
  // @ts-expect-error a mode of the wrong type
  throws(() => p.configure({ count: 5, bytes: 0 }, 6, "1", token), TypeError, "mode");
  // @ts-expect-error a cut no entry names
  throws(() => p.stream(0, [2 ** 32 + 1], () => undefined), RangeError, "cuts");
  // @ts-expect-error a count of the wrong type
  throws(() => p.recv("3"), TypeError, "pdst_count");
  // @ts-expect-error a struct field of the wrong type
  throws(() => p.configure({ count: "5", bytes: 0 }, 6, M.Mode.SLOW, token), TypeError, "cfg.count");

  const [stats, count, link] = p.stats_of();
  check(stats.count === 42 && count === 43 && link instanceof M.LinkHandle, "stats_of");
  const [level, data, tally] = p.bump(4, new Uint8Array([97, 98, 99]), new M.Stats({ count: 5 }));
  check(level === 5 && tally.count === 10 && text(data) === "bcd", "bump");
  // data is copied at its check: tally's accessor, read after it, grows, shrinks or detaches its buffer
  for (const [what, change] of /** @type {[string, (buffer: ArrayBuffer) => unknown][]} */ ([
    ["grown", (buffer) => buffer.resize(8)],
    ["shrunk", (buffer) => buffer.resize(1)],
    ["detached", (buffer) => buffer.transfer()],
  ])) {
    const buffer = new ArrayBuffer(3, { maxByteLength: 8 });
    const bytes = new Uint8Array(buffer);
    bytes.set([97, 98, 99]);
    const changing = { get count() { change(buffer); return 5; }, bytes: 0 };
    const [, bumped] = p.bump(4, bytes, changing);
    check(text(bumped) === "bcd", `bump's data ${what} after its check`);
  }
  throws(() => p.list(2 ** 30 + 1, 0), RangeError, "Port.list: items would pass 2147483647 bytes");
  check(p.seek(1 << 20) === undefined, "seek");
  refused(() => p.seek(48), M.Status.ERR_BUSY);
  const [next, delta] = p.tune(-3, -(1 << 20), 200, 0.5);
  check(next === -(1 << 20) - 1 && delta === -4, "tune");
  check(p.annotate(null) === undefined && p.annotate({ count: 7, bytes: 0 }) === undefined, "annotate");
  refused(() => p.annotate({ count: 1, bytes: 0 }), M.Status.ERR_BUSY);
  const [mode, noLevel, peek] = p.probe(null, null, null);
  check(mode === M.Mode.SLOW && noLevel === null && peek === 9, "probe's absent arguments");
  check(p.probe(new Uint8Array(2), 3, 4)[1] === 5, "probe's present arguments");
  refused(() => p.probe(new Uint8Array(0), null, null), M.Status.ERR_BUSY);
  check(p.echo_offset(77) === 77, "a boxed scalar is its base value");

  // buffers with reports, and an array out
  const empty = p.list(0, 0);
  check(empty[0].length === 0 && empty[1] === 0 && empty[2] === 3 && empty[4] === 0 && empty[5] === 6, "list(0, 0)");
  const [items, itemsWrote, , labels] = p.list(1, 2);
  const label = M.resolve(items[0].label, labels);
  check(itemsWrote === 1 && items[0].id === 10 && text(labels) === "e0" && label !== null && text(label) === "e0", "list(1, 2)");
  const all = p.list(5, 8);
  check(all[0].length === 5 && JSON.stringify(all.slice(1, 3)) === "[3,3]" && text(all[3]) === "e0e1e2", "list(5, 8)");
  for (const [itemsCount, labelsCount, buffer] of /** @type {[number, number, string][]} */ ([[4, 6, "items"], [6, 6, "items"], [3, 5, "labels"]])) {
    throws(() => p.list(itemsCount, labelsCount), Error, `xy_list over-reported ${buffer}`);
  }

  // an array in: cuts end batches
  for (const [batch, cuts, fresh] of /** @type {[number, M.Cut[], number[]][]} */ ([
    [1, [], [1, 1, 1, 1, 1, 1, 1, 0]],
    [3, [], [3, 3, 1]],
    [0, [], [7]],
    [3, [M.Cut.AFTER_ONE, M.Cut.AFTER_FOUR], [2, 3, 2]],
    [0, [M.Cut.AFTER_FOUR], [5, 2]],
  ])) {
    const [result, got, views] = stream(p, batch, cuts);
    check(result === M.Status.OK && views && streamed(got, fresh, true), `stream(${batch}, [${cuts}])`);
  }
  const [halted, haltedCalls] = stream(p, 1, [], 3);
  check(halted === M.Status.ERR_AGAIN && streamed(haltedCalls, [1, 1, 1], false), "a halt stops the stream");
  throws(() => p.stream(1, [], /** @type {any} */ (42)), TypeError, "sink must be a function");

  /** @type {number[]} */
  const firsts = [];
  /** @type {number[]} */
  const seconds = [];
  check(p.notify(1, (m) => void firsts.push(m), (m) => void seconds.push(m)) === undefined, "notify");
  check(firsts.join() === `${M.Mode.SLOW}` && seconds.join() === `${M.Mode.SLOW}`, "notify's modes");
  throws(() => p.notify(7, () => void firsts.push(0), () => void seconds.push(0)), Error, "xy_on_mode received a mode value");
  check(firsts.length === 1 && seconds.length === 1, "an unnamed enum reaches no function");
  for (const answer of [0.5, 2 ** 40, true, null]) {
    let runs = 0;
    const sink = /** @type {M.OnBatch} */ (() => (runs++, /** @type {any} */ (answer)));
    throws(() => p.stream(0, [], sink), TypeError, "xy_on_batch: the function answered");
    check(runs === 1, `the answer ${answer} ends the calls`);
  }

  const e0e1 = Uint8Array.from("e0e1", (c) => c.charCodeAt(0));
  const run = M.resolve(new M.Text({ offset: 2, length: 2 }), e0e1);
  check(run !== null && text(run) === "e1" && M.resolve(new M.Text({ offset: 2, length: 3 }), e0e1) === null, "resolve");
  /** @type {string[]} */
  const resolved = [];
  p.stream(0, [], (seen, _fresh, arena) => {
    const one = M.resolve(seen.at(1).label, arena);
    resolved.push(one === null ? "" : text(one), text(arena.slice(2, 4)), String(arena.at(0)));
  });
  check(resolved.join() === "e1,e1,101", "resolve against a byte view while its callback runs");

  const linked = new lib.DataLink();
  check(linked.handle !== null && linked.attach(p) === undefined, "attach");
  const handle = p.handle;
  check(p.release() === undefined && p.handle === null && handle !== null && handle.value === null, "release");
  throws(() => p.send(new Uint8Array(4)), Error, "Port used after destroy_port");
  throws(() => linked.attach(p), Error, "hport is a Port used after destroy_port");
  throws(() => p.release(), Error, "Port used after destroy_port");
  /** @type {M.Port | undefined} */
  let kept;
  {
    using q = new lib.Port(1);
    kept = q;
    check(q.generation === 7, "using");
  }
  check(kept.handle === null, "using releases at its block's end");
}

function paths() {
  const exported = WebAssembly.Module.exports(new WebAssembly.Module(readFileSync(join(here, "xy.wasm")))).map((e) => e.name);
  check(exported.includes("_initialize") && !exported.includes("_start"), "xy.wasm is a reactor");
  const absolute = load(join(here, "xy.wasm"));
  new absolute.Port(1).release();
  throws(() => load("xy.wasm"), TypeError, "absolute path");
  throws(() => load(join(here, "absent", "xy.wasm")), Error, "cannot load the module of the library xy");
}

/** stream, whose _stack_mb names max_units, on a worker 1 MiB below that stack and on one at it. */
function stack() {
  for (const stackSizeMb of [M.MAX_UNITS - 1, M.MAX_UNITS]) {
    const worker = new Worker(join(here, "check_xy32_marshalling.mjs"), { workerData: stackSizeMb, resourceLimits: { stackSizeMb } });
    worker.on("error", (error) => {
      writeSync(2, `worker of ${stackSizeMb} MiB: ${String(error)}\n`);
      process.exitCode = 1;
    });
  }
}

/** The worker's half of `stack`, on a thread whose stack is `stackSizeMb`. @param {number} stackSizeMb */
function streamOnWorker(stackSizeMb) {
  const p = new lib.Port(1);
  let runs = 0;
  const sink = () => void (runs += 1);
  if (stackSizeMb < M.MAX_UNITS) {
    // refused ahead of its arguments' checks, so before anything is allocated
    const needle = `Port.stream needs a stack of ${M.MAX_UNITS} MiB; this worker thread's is ${stackSizeMb} MiB`;
    throws(() => p.stream(-1, [], sink), RangeError, needle);
    check(runs === 0, "a refused stream calls no sink");
  } else {
    check(p.stream(0, [], sink) === undefined && runs === 1, "stream runs on a worker of its stack");
  }
  p.release();
}

/** @param {M.NoteLine | M.NoteMark} record */
function noteText(record) {
  const head = record.head;
  if (record instanceof M.NoteLine) {
    return `line ${head.kind} ${head.size} ${head.at} ${record.label.offset} ${record.label.length}`;
  }
  return `mark ${head.kind} ${head.size} ${head.at} ${record.value} ${record.flag}`;
}

/** @param {M.NoteSequence} sequence @returns {[number, string][]} */
function walk(sequence) {
  /** @type {[number, string][]} */
  const notes = [];
  let offset = 0;
  for (const record of sequence) {
    notes.push([offset, noteText(record)]);
    offset += record.head.size;
  }
  return notes;
}

/** @param {M.NoteSequence} seen @param {number} offset */
function notAStart(seen, offset) {
  const error = throws(() => seen.at(offset / M.NOTE_ALIGN), M.UnionError, "offset is not a record's start");
  check(error.message.startsWith("xy_on_notes received view seen refused at record"), error.message);
  return [error.index, error.offset];
}

function notes() {
  const p = new lib.Port(3);
  for (const [batch, counts] of /** @type {[number, number[]][]} */ ([[2, [2, 2, 2]], [4, [4, 2]], [0, [6]]])) {
    /** @type {[number, string][]} */
    const kept = [];
    /** @type {number[]} */
    const freshCounts = [];
    p.stream_notes(batch, (seen, fresh) => {
      freshCounts.push(fresh.length);
      const seenNotes = walk(seen);
      const before = seen.bytes - fresh.bytes;
      kept.push(.../** @type {[number, string][]} */ (walk(fresh).map(([offset, line]) => [before + offset, line])));
      check(JSON.stringify(seenNotes) === JSON.stringify(kept) && seen.length === kept.length, "fresh is seen's tail");
      for (const [offset, line] of kept) {
        check(noteText(seen.at(offset / M.NOTE_ALIGN)) === line, `seen.at(${offset / M.NOTE_ALIGN})`);
      }
      for (const [offset, line] of walk(fresh)) {
        check(noteText(fresh.at(offset / M.NOTE_ALIGN)) === line, `fresh.at(${offset / M.NOTE_ALIGN})`);
      }
      check(JSON.stringify(notAStart(seen, 4)) === "[1,4]", "at inside a record");
      check(JSON.stringify(notAStart(seen, seen.bytes)) === JSON.stringify([seen.length, seen.bytes]), "at the extent");
      throws(() => seen.at(0.5), TypeError, "a sequence's index is an integer");
    });
    check(freshCounts.join() === counts.join(), `stream_notes(${batch})`);
    if (batch === 2) {
      kept.forEach(([, line]) => out(line));
    }
  }
  p.release();
}

/** @param {string} selector */
function refusedNotes(selector) {
  if (!/^[0-9]+$/.test(selector) || Number(selector) > 255) {
    return 100;
  }
  let refusals = 0;
  const p = new lib.Port(3);
  /** @type {number} */
  let result = M.Status.OK;
  try {
    p.stream_notes(Number(selector), (seen, fresh) => {
      for (const sequence of [seen, fresh]) {
        try {
          walk(sequence);
          sequence.at(16 / M.NOTE_ALIGN);
        } catch (error) {
          refusals += error instanceof M.UnionError ? 1 : 0;
        }
      }
      return refusals ? M.Flow.HALT : undefined;
    });
  } catch (error) {
    result = throws(() => { throw error; }, M.ResultError).result;
  }
  p.release();
  return result === M.Status.ERR_AGAIN && refusals ? Number(selector) : 100;
}

const steps = { constants, calls, load: paths, notes, stack };
const [step, selector] = process.argv.slice(2);
if (!isMainThread) {
  streamOnWorker(/** @type {number} */ (workerData));
} else if (step === "notes" && selector !== undefined) {
  process.exitCode = refusedNotes(selector);
} else if (step in steps) {
  steps[/** @type {keyof typeof steps} */ (step)]();
} else {
  throw new Error(`no step ${step}`);
}
