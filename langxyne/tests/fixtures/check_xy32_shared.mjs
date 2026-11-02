// What check_xy32_marshalling.mjs and check_xy32_lifetime.mjs share: their checks, the loader of
// support_xy32.XY32's Node binding, ./xy_api.mjs beside them, and port.stream as their steps run it.
import { writeSync } from "node:fs";
import { WASI } from "node:wasi";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import * as M from "./xy_api.mjs";

export const here = dirname(fileURLToPath(import.meta.url));

/** @param {string} line */
export function out(line) {
  writeSync(1, `${line}\n`);
}

/** @param {boolean} condition @param {string} what */
export function check(condition, what) {
  if (!condition) {
    throw new Error(`check failed: ${what}`);
  }
}

/**
 * What `call` throws, which must be an instance of `kind`, its message holding `needle`.
 * @param {() => unknown} call @param {Function} kind @param {string} [needle]
 * @returns {any}
 */
export function throws(call, kind, needle = "") {
  try {
    call();
  } catch (error) {
    check(error instanceof kind, `${String(error)} is a ${kind.name}`);
    check(String(/** @type {Error} */ (error).message).includes(needle), `${String(error)} holds ${needle}`);
    return error;
  }
  throw new Error(`check failed: ${String(call)} did not throw`);
}

/** @param {() => unknown} call @param {number} result */
export function refused(call, result) {
  check(throws(call, M.ResultError).result === result, `${String(call)} refused with ${result}`);
}

/** @param {string} path @returns {M.Library} */
export function load(path) {
  return M.load(new WASI({ version: "preview1" }), path);
}

/** @param {Uint8Array} bytes */
export function text(bytes) {
  return String.fromCharCode(...bytes);
}

/**
 * stream(batch, cuts), its sink answering halt on call `haltOn`: the result, each call's (seen,
 * fresh, last) counts, and whether every view held what the fake promises.
 * @param {M.Port} port @param {number} batch @param {M.Cut[]} cuts @param {number} [haltOn]
 * @returns {[number, number[][], boolean]}
 */
export function stream(port, batch, cuts, haltOn) {
  /** @type {number[][]} */
  const calls = [];
  let views = true;
  try {
    port.stream(batch, cuts, (seen, fresh, arena, last) => {
      calls.push([seen.length, fresh.length, last]);
      fresh.slice().forEach((entry, i) => {
        views &&= entry.id === seen.at(seen.length - fresh.length + i).id;
      });
      let i = 0;
      for (const entry of seen) {
        const label = M.resolve(entry.label, arena);
        views &&= label !== null && text(label) === `e${i++}`;
      }
      views &&= M.resolve(new M.Text({ offset: arena.length, length: 2 }), arena) === null;
      return calls.length === haltOn ? M.Flow.HALT : undefined;
    });
  } catch (error) {
    return [throws(() => { throw error; }, M.ResultError).result, calls, views];
  }
  return [M.Status.OK, calls, views];
}

/** @param {number[][]} calls @param {number[]} fresh @param {boolean} final */
export function streamed(calls, fresh, final) {
  let seen = 0;
  const expected = fresh.map((count, i) => [(seen += count), count, final && i === fresh.length - 1 ? 1 : 0]);
  return JSON.stringify(calls) === JSON.stringify(expected);
}
