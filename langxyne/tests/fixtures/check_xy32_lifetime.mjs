// Runs support_xy32.XY32's Node binding, ./xy_api.mjs beside this file with its declarations,
// against the Rust fake built for wasm32-wasip1 as ./xy.wasm: an object's and a view's lifetime
// against the instance's, one step per run, its first argument:
//   reentry    a call and a release of a port, and the port passed as an argument, from inside
//              its own stream's callback: each the busy error, the stream itself succeeding
//   after      a view, a sequence and a byte view kept past their callback refuse every use,
//              while an element read from a view is a copy valid after it
//   failure    a callback's exception, any value, thrown again by the call once the library
//              returns, the callback not called again; the next call succeeds
//   dead       seek(u32::MAX), whose panic traps the instance: every later call of any of its
//              objects throws naming that trap, while a new instance works; on that instance, the
//              same trap caught inside stream's callback, which then returns normally: stream
//              throws the dead-instance error, the callback run once, and a third object's call
//              names the trap
//   growth     inside stream's callback, recv on another port with a count of 16 MiB, which
//              grows the instance's memory: seen.at(0) and resolve against the arena then read
//              correctly
//   unlocked   support_xy32.XY32_UNHIDDEN's binding, ./xy_api_unhidden.mjs, over the same
//              xy.wasm: a call during its object's own stream callback refused busy through the
//              held mark; after release, a call passing the object reaches the library with the
//              null handle and throws the library's status, and a second release does likewise
//   nested     stream(96), whose callback's seek(96) on a second port has the library call the
//              sink again: the nested call reaches no consumer code, and stream throws naming it
//   foreign    stream(94), whose library calls the sink with a user_data no frame names: the
//              answer is halt, and the function never runs
// Every check throws, so a failure exits 1 naming it.
import process from "node:process";
import { WASI } from "node:wasi";
import { join } from "node:path";
import * as M from "./xy_api.mjs";
import * as U from "./xy_api_unhidden.mjs";
import { check, here, load, refused, stream, streamed, text, throws } from "./check_xy32_shared.mjs";

const lib = M.load(new WASI({ version: "preview1" }));

function reentry() {
  const p = new lib.Port(1);
  const link = new lib.DataLink();
  let entered = false;
  p.stream(1, [], () => {
    if (!entered) {
      entered = true;
      refused(() => p.seek(1 << 20), M.Status.ERR_BUSY);
      refused(() => link.attach(p), M.Status.ERR_BUSY);
      refused(() => p.release(), M.Status.ERR_BUSY);
    }
  });
  check(entered && p.seek(1 << 20) === undefined && link.attach(p) === undefined, "calls after the stream");
  p.release();
}

function after() {
  const p = new lib.Port(1);
  /** @type {unknown[]} */
  const kept = [];
  /** @type {M.Entry[]} */
  const elements = [];
  p.stream(0, [], (seen, fresh, arena) => {
    kept.push(seen, fresh, arena);
    elements.push(seen.at(0));
  });
  const [seen, , arena] = /** @type {[M.View<M.Entry>, M.View<M.Entry>, M.ByteView]} */ (kept);
  const dead = "a view is valid only until its callback returns";
  throws(() => seen.length, Error, dead);
  throws(() => seen.at(0), Error, dead);
  throws(() => [...seen], Error, dead);
  throws(() => M.resolve(new M.Text({ offset: 0, length: 2 }), arena), Error, dead);
  check(elements[0].id === 10, "an element read is a copy valid after its callback");
  /** @type {M.NoteSequence[]} */
  const held = [];
  p.stream_notes(0, (notes) => void held.push(notes));
  throws(() => held[0].length, Error, dead);
  throws(() => held[0].bytes, Error, dead);
  throws(() => held[0].at(0), Error, dead);
  throws(() => [...held[0]], Error, dead);
  p.release();
}

function failure() {
  const p = new lib.Port(1);
  for (const thrown of [new RangeError("the consumer's sink throws on its second call"), "a string", undefined]) {
    let runs = 0;
    let caught = null;
    try {
      p.stream(1, [], () => {
        runs += 1;
        if (runs === 2) {
          throw thrown;
        }
      });
    } catch (error) {
      caught = { error };
    }
    check(caught !== null && caught.error === thrown && runs === 2, `${String(thrown)} thrown again, the sink run twice`);
    const [result, got] = stream(p, 0, []);
    check(result === M.Status.OK && streamed(got, [7], true), "the next stream succeeds");
  }
  p.release();
}

function dead() {
  const p = new lib.Port(1);
  const q = new lib.Port(2);
  const trap = throws(() => p.seek(0xffffffff), Error);
  check(!(trap instanceof M.ResultError), "a trap is not a result");
  for (const call of [() => p.seek(1), () => q.release(), () => new lib.Port(3), () => lib.mint()]) {
    throws(call, Error, `the instance is dead: a call into it threw ${String(trap)}`);
  }
  const fresh = load(join(here, "xy.wasm"));
  new fresh.Port(1).release();

  // a call that dies inside a callback kills the call driving it, whatever the callback answers
  const [r, s, t] = [new fresh.Port(1), new fresh.Port(2), new fresh.Port(3)];
  let runs = 0;
  /** @type {unknown} */
  let seekTrap;
  const died = throws(() => r.stream(1, [], () => {
    runs += 1;
    try {
      s.seek(0xffffffff);
    } catch (error) {
      seekTrap = error;
    }
  }), Error, "the instance is dead: a call into it threw");
  check(seekTrap !== undefined && died.cause === seekTrap && runs === 1, "stream dies of its callback's trapped seek");
  throws(() => t.seek(1), Error, `the instance is dead: a call into it threw ${String(seekTrap)}`);
}

function growth() {
  const p = new lib.Port(1);
  const q = new lib.Port(2);
  const size = 16 * 2 ** 20;
  /** @type {string[]} */
  const read = [];
  p.stream(0, [], (seen, _fresh, arena) => {
    check(q.recv(size).length === size, "a 16 MiB recv");
    const label = M.resolve(seen.at(0).label, arena);
    read.push(String(seen.at(0).id), label === null ? "" : text(label));
  });
  check(read.join() === "10,e0", "the views read after the memory grew");
  p.release();
  q.release();
}

function unlocked() {
  const unhidden = U.load(new WASI({ version: "preview1" }), join(here, "xy.wasm"));
  const p = new unhidden.Port(1);
  const link = new unhidden.DataLink();
  let runs = 0;
  p.stream(1, [], () => {
    if (runs++ === 0) {
      check(throws(() => p.seek(1 << 20), U.ResultError).result === U.Status.ERR_BUSY, "a call in its own callback");
    }
  });
  check(runs === 8, "the stream after its refused call");
  p.release();
  check(throws(() => link.attach(p), U.ResultError).result === U.Status.ERR_OTHER, "a call after release");
  check(throws(() => p.release(), U.ResultError).result === U.Status.ERR_OTHER, "a second release");
}

function nested() {
  const p = new lib.Port(1);
  const q = new lib.Port(2);
  let runs = 0;
  throws(() => p.stream(96, [], () => {
    runs += 1;
    q.seek(96);
  }), Error, "xy_on_batch called again while a call of it was running in xy_stream");
  check(runs === 1, "the nested call reaches no consumer code");
  p.release();
  q.release();
}

function foreign() {
  const p = new lib.Port(1);
  let runs = 0;
  refused(() => p.stream(94, [], () => void (runs += 1)), M.Status.ERR_AGAIN);
  check(runs === 0, "a user_data naming no frame reaches no function");
  p.release();
}

const steps = { reentry, after, failure, dead, growth, unlocked, nested, foreign };
const [step] = process.argv.slice(2);
if (step in steps) {
  steps[/** @type {keyof typeof steps} */ (step)]();
} else {
  throw new Error(`no step ${step}`);
}
