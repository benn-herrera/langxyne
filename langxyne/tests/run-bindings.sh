#!/usr/bin/env bash
# run-bindings.sh — the whole compiled-bindings loop of langxyne in shell: the C++ and Rust
# fakes of support.KITCHEN_SINK built, the consumers compiled (C, C++, Go with its cgocheck2
# variant, Rust at each edition), every self-verifying program under tests/fixtures/ run
# against each fake, every must-not-compile build refused at its stderr needle (`grep -F`),
# and every byte golden compared with `cmp -s`, its `diff -u` printed on mismatch. It takes no
# arguments: it resolves the fake directories itself and builds each artifact before the run
# that names it. Python appears only as the generator under test and as the venv interpreter that runs the
# Python fixtures and emits the sources support computes (XY_PYTHON). This file holds the setup
# and the helpers, and sources the cases, one part per output family in this order:
# run-bindings-c.sh (the fakes, C and C++), -lua.sh, -rust.sh, -go.sh, -python.sh, -static.sh,
# -node.sh and -definitions.sh.
#
# Prints `<what>: ok` per case and `<what>: FAIL <detail>` per failure, the stderr tail of
# the failing command beneath each FAIL; a summary count line ends the output. Exits 1 when
# any case failed, 2 when the loop itself cannot run: an absent tool, XY_PYTHON, or a
# generator that fails to produce a tree.
#
# The run matrix, against the C++ fake (the tree's own directory) and the Rust fake (rsfake/):
#   edge            bare, panic (abort)                     rust fake
#   consumer      bare (cpp, rust); nested — via lying    cpp, rust fakes
#   lying         nested; off_thread (abort)              cpp fake
#   wide          bit 31's header and wrapper             its own scratch tree
#   consumer_rs   each edition, both fakes                cpp, rust fakes
#   check_xy.lua  constants; check_i64_xy.lua i64; lying_xy, gc_xy bare; gc_error exit 1;
#                 failed_argument on its swapped-order module, both fakes
#   in_arrays_refs.lua / .py, ctor_refs.go                the refs notes fake
#   consumer_go   bare and cgocheck2 both fakes; nested, nested95 cpp; select, foreign,
#                 outside with their exit and stderr pins; constants stdout vs the model
#   check_xy.py   constants both fakes; nested, nested95, outside, off_thread cpp; select
#                 its asymmetry; open beside/alone/holding; unhidden on its UNHIDDEN_PORT module
#   refs_enums_xy.rs exit 0, refs_slice_xy.rs its panic text   the refs stub fake
#   consumer_static, consumer_go_static   linked against libxy.a alone, run with no loader var
#   check_xy32_marshalling.mjs, check_xy32_lifetime.mjs  support_xy32.XY32's Node binding over
#                 fake_xy32.rs, support_xy32.fake_xy32() written into its scratch tree and built
#                 with the relay and the wasm shim for wasm32-wasip1 as xy.wasm beside the module,
#                 a WASI reactor linking wasi-libc's crt1-reactor.o, clippy at each edition; both
#                 programs, with their shared module check_xy32_shared.mjs, type-checked by tsc
#                 against the emitted declarations and node_xy32.d.ts, then each step run by
#                 node: marshalling's constants vs the model, calls, load, stack (stream on two
#                 workers), notes vs notes_xy.txt, notes 101 to 106 exit 100; lifetime's
#                 reentry, after, failure, growth, unlocked (over XY32_UNHIDDEN's binding),
#                 nested, foreign, dead (seek(u32::MAX)'s panic on stderr)
# The notes cases (stream_notes' views): consumer_xy.cpp's bare run, and `notes` of edge_xy.c,
# consumer_xy.rs at each edition, consumer_xy.go (bare, and cgocheck2 for the stdout alone),
# check_xy.lua and check_xy.py, print the six lines of fixtures/notes_xy.txt, compared in order,
# against both fakes; `notes 101` to `notes 105` exit with the selector against the C++ fake,
# its two refusals on stderr at their needles, and 100 against the Rust fake; `notes 106` exits
# 106 against the C++ fake, at's refusal of seen's record past its count (edge_xy.c's, well_formed's)
# on stderr at that program's needle, and 100 against the Rust fake. not_member_xy.cpp
# and keep_note_xy.rs are the must-not-compile pins.
# Scratch trees the loop generates for one case each: BIT_THIRTY_ONE (h,hpp + wide),
# TRAMPOLINE_PARAM (rs, clippy lib each edition), RELAY_WITH_WHENCE (abi_rs; its stub refused),
# UNSPELLED_PRELUDE (abi_rs,stub_rs; the stub clean), CUTS_AFTER_SINK (h,lua), UNHIDDEN_PORT
# (py), the static bindings, the Go vet set (KITCHEN_SINK, REFS, MINIMAL), XY32 (every
# output) and XY32_UNHIDDEN (node). KITCHEN_SINK and REFS hold 64-bit types, which the Node binding refuses, so their
# trees take every output but the shim and the Node binding. Every Rust
# gate is clippy at each edition the generated Rust holds; builds that only produce an
# artifact, or must fail at a pin, are rustc at the newest. Every consuming definition
# round-trips too: generation, C/C++ syntax, luajit -bl, rustfmt, clippy cdylib and lib at
# each edition, the stub with the shim beside its relay as a wasm32-wasip1 cdylib under clippy
# at each edition, node --check of the Node module and tsc over its declarations, over the
# consuming repository's tree LANGXYNE_DEFINITIONS names, else over tests/fixtures/definitions/.
#
# bash 3.2. XY_PYTHON names the venv interpreter; the host tools: clang, clang++, ar,
# bindgen, clippy-driver, go, luajit, node, rustc with the wasm32-wasip1 target's std, rustfmt,
# tsc. The scratch tree goes under
# LANGXYNE_SCRATCH where set, else under mktemp -d's directory, and is kept when the run fails.
# shellcheck source-path=SCRIPTDIR
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
[[ -n "${XY_PYTHON:-}" && -x "${XY_PYTHON}" ]] || { printf 'run-bindings: XY_PYTHON names the venv interpreter and is absent\n' >&2; exit 2; }
missing=()
for tool in clang clang++ ar bindgen clippy-driver go luajit node rustc rustfmt tsc; do
  command -v "${tool}" >/dev/null || missing+=("${tool}")
done
if [[ "${#missing[@]}" -gt 0 ]]; then printf 'run-bindings: missing on PATH: %s\n' "${missing[*]}" >&2; exit 2; fi
# the target the shim and the Node binding's module build for, whose std rustc must have
WASM_TARGET=wasm32-wasip1
wasm_std="$(rustc --print target-libdir --target "${WASM_TARGET}" 2>/dev/null)"
if ! compgen -G "${wasm_std:-/nonexistent}/libstd-*.rlib" >/dev/null; then
  printf 'run-bindings: rustc has no %s std; install the target\n' "${WASM_TARGET}" >&2
  exit 2
fi
go_version="$(go env GOVERSION 2>/dev/null)"
# the floor whose `go vet` holds the Go binding to the stdversion analyzer
go_floor=123
go_num="$(printf '%s' "${go_version}" | sed -E 's/^go([0-9]+)\.([0-9]+).*$/\1*100+\2/')"
go_at="$((${go_num:-0}))"
if [[ "${go_at}" -lt "${go_floor}" ]]; then printf 'run-bindings: go is %s; the Go checks need go1.23 or later, whose vet checks stdversion\n' "${go_version}" >&2; exit 2; fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fixtures="${here}/fixtures"
wrapped="${fixtures}/wrapped"
header="${wrapped}/xy/driver/xy_ioctl.h"
bad_header="${fixtures}/wrapped_bad/xy/driver/xy_ioctl.h"
pythonpath="$(dirname "$(dirname "${here}")")"
export PYTHONPATH="${pythonpath}"
case "$(uname -s)" in
  Darwin) loader=DYLD_LIBRARY_PATH; so=libxy.dylib; dylib_suffix=dylib ;;
  Linux) loader=LD_LIBRARY_PATH; so=libxy.so; dylib_suffix=so ;;
  *) printf 'run-bindings: no loader variable or library name for %s\n' "$(uname -s)" >&2; exit 2 ;;
esac
gomod=xy_consumer  # the module the Go consumer imports the binding's package from
# the editions the generated Rust holds, and the newest the failing and run-only builds use
EDITIONS=(2021 2024)
EDITION=2024
# every output but the wasm shim and the Node binding, the selection of a definition holding 64-bit types
NATIVE_OUTPUTS=h,hpp,lua,stub_cpp,rs,abi_rs,stub_rs,go,py
ALL_OUTPUTS="${NATIVE_OUTPUTS},wasm_rs,node"
if [[ -n "${LANGXYNE_SCRATCH:-}" ]]; then
  mkdir -p "${LANGXYNE_SCRATCH}" && work="$(mktemp -d "${LANGXYNE_SCRATCH}/run-bindings.XXXXXX")"
else
  work="$(mktemp -d)"
fi || { printf 'run-bindings: no scratch directory\n' >&2; exit 2; }
trap 'if [[ "${?}" -eq 0 ]]; then command rm -rf "${work}"; else printf "run-bindings: scratch kept at %s\n" "${work}" >&2; fi' EXIT
capture="${work}/capture"
mkdir -p "${capture}"
checks=0
failures=0
needles=()  # stderr needles the next run_case must see; run_case clears them

function ok() { checks=$((checks + 1)); printf '%s: ok\n' "${1}"; }
function fail() { # <label> <detail>: the FAIL line; returns 1, so a failed case is a failed command
  checks=$((checks + 1)); failures=$((failures + 1))
  printf '%s: FAIL %s\n' "${1}" "${2}"
  return 1
}
function fail_cmd() { # <label> <detail>: the FAIL line, then the captured stderr to diagnose by
  fail "${1}" "${2}"
  tail -n 20 "${capture}/err" | sed 's/^/    /'
  return 1
}

function attempt() { local rc=0; "${@}" </dev/null >"${capture}/out" 2>"${capture}/err" || rc="${?}"; return "${rc}"; }
function attempt_in() { local dir="${1}"; shift; ( cd "${dir}" && attempt "${@}" ); }

function searched() { # <fake-dir>: the loader's env assignment, the inherited search behind it
  if [[ -n "${!loader-}" ]]; then printf '%s=%s:%s' "${loader}" "${1}" "${!loader}"; else printf '%s=%s' "${loader}" "${1}"; fi
}
function lua_search() { # <binding-dir>: LUA_PATH's env assignment, that directory's ?.lua first
  printf 'LUA_PATH=%s/?.lua;%s' "${1}" "${LUA_PATH}"
}
function fake_of() { # <cpp|rust>: the directory holding that fake's library
  [[ "${1}" == cpp ]] && printf '%s' "${root}" || printf '%s' "${rsfake}"
}

# run_case <label> <pin> <want> -- <cmd...>: run one case. pin none: exit 0; rc: exit is
# <want>, an integer, or any nonzero when <want> is nz; constants: exit 0 and stdout sorted
# equals the model's constants; golden: exit 0 and stdout sorted equals file <want>; stdout:
# exit 0 and stdout, in order, equals file <want>; i64: stdout exactly "i64 ok". While the global needles is nonempty stderr must hold each, and
# run_case consumes them.
function run_case() {
  local label="${1}" pin="${2}" want="${3}" rc=0 needle
  shift 3
  [[ "${1}" == "-" ]] && shift  # the want placeholder of the pins that read no want
  [[ "${1}" == "--" ]] || { fail "${label}" "internal: no -- before the command"; return; }
  shift
  attempt "${@}" || rc="${?}"
  local found=()
  for needle in ${needles[@]+"${needles[@]}"}; do
    grep -Fq -- "${needle}" "${capture}/err" || found+=("${needle}")
  done
  needles=()
  if [[ "${pin}" == "rc" ]]; then
    if [[ "${want}" == "nz" ]]; then
      [[ "${rc}" -ne 0 ]] || { fail_cmd "${label}" "exit 0, must not"; return; }
    elif [[ "${rc}" -ne "${want}" ]]; then
      fail_cmd "${label}" "exit=${rc}, want ${want}"
      return
    fi
  elif [[ "${rc}" -ne 0 ]]; then
    fail_cmd "${label}" "exit=${rc}"
    return
  fi
  if [[ "${#found[@]}" -gt 0 ]]; then fail_cmd "${label}" "no needle: ${found[*]}"; return; fi
  case "${pin}" in
    none|rc) ok "${label}" ;;
    constants) sort "${capture}/out" >"${capture}/got"; golden_cmp "${label}" "${work}/constants" "${capture}/got" ;;
    golden) sort "${capture}/out" >"${capture}/got"; golden_cmp "${label}" "${want}" "${capture}/got" ;;
    stdout) golden_cmp "${label}" "${want}" "${capture}/out" ;;
    i64)
      if [[ "$(cat "${capture}/out")" == "i64 ok" ]]; then ok "${label}"; else fail "${label}" "stdout: $(head -n 1 "${capture}/out")"; fi ;;
  esac
}

# refuse_case <label> <needle>... -- <cmd...>: the build must fail, and at every needle
# (pinned verbatim from the suite's asserts).
function refuse_case() {
  local label="${1}" rc=0 name missing=()
  shift
  local pinned=()
  while [[ "${1}" != "--" ]]; do pinned+=("${1}"); shift; done
  shift
  attempt "${@}" || rc="${?}"
  if [[ "${rc}" -eq 0 ]]; then fail_cmd "${label}" "compiled, must not"; return; fi
  for name in "${pinned[@]}"; do grep -Fq -- "${name}" "${capture}/err" || missing+=("${name}"); done
  if [[ "${#missing[@]}" -gt 0 ]]; then fail_cmd "${label}" "no needle: ${missing[*]}"; return; fi
  ok "${label}"
}

function golden_cmp() { # <label> <want> <got>: cmp -s, the diff -u printed on mismatch
  if cmp -s "${2}" "${3}"; then ok "${1}"; return; fi
  fail "${1}" "stdout differs from the golden"
  diff -u "${2}" "${3}"
  return 1
}

# The notes cases, one set per consumer. runner is a function: `<runner> <fake> [arg...] notes
# [selector]` runs the program against that fake. notes_golden: `notes` prints the six lines of
# notes_xy.txt against either fake. notes_refused: selectors 101 to 105 against the C++ fake exit
# with the selector and write both views' refusals at the clause the selector names to stderr;
# against the Rust fake, which refuses nothing, exit 100.
note_clauses=('header past the extent' 'unknown tag' "size is not the member's" 'record past the extent' 'count not met')
function notes_golden() { # <program> <runner> [arg...]
  local program="${1}" runner="${2}" fake
  shift 2
  for fake in cpp rust; do
    run_case "${program} (notes, ${fake} fake)" stdout "${fixtures}/notes_xy.txt" -- "${runner}" "${fake}" ${@+"${@}"} notes
  done
}
function notes_refused() { # <program> <runner> [arg...]
  local program="${1}" runner="${2}" selector clause
  shift 2
  for selector in 101 102 103 104 105; do
    clause="${note_clauses[$((selector - 101))]}"
    needles=("xy_on_notes: seen: record 3 at offset 48: ${clause}" "xy_on_notes: fresh: record 1 at offset 16: ${clause}")
    run_case "${program} (notes ${selector}, cpp fake)" rc "${selector}" - -- "${runner}" cpp ${@+"${@}"} notes "${selector}"
    run_case "${program} (notes ${selector}, rust fake)" rc 100 - -- "${runner}" rust ${@+"${@}"} notes "${selector}"
  done
}
# notes_past_count: selector 106 against the C++ fake exits 106 with <refusal>, the program's
# refusal of seen's record past its count, on stderr; against the Rust fake, 100.
function notes_past_count() { # <program> <refusal> <runner> [arg...]
  local program="${1}" refusal="${2}" runner="${3}"
  shift 3
  needles=("${refusal}")
  run_case "${program} (notes 106, cpp fake)" rc 106 - -- "${runner}" cpp ${@+"${@}"} notes 106
  run_case "${program} (notes 106, rust fake)" rc 100 - -- "${runner}" rust ${@+"${@}"} notes 106
}
function notes_cases() { notes_golden "${@}"; notes_refused "${@}"; }
function bin_runner() { # <fake> <binary> [arg...]
  local fake_dir
  fake_dir="$(fake_of "${1}")"
  shift
  env "$(searched "${fake_dir}")" "${@}"
}
function lua_runner() { # <fake> [arg...]
  local fake_dir
  fake_dir="$(fake_of "${1}")"
  shift
  env "$(searched "${fake_dir}")" luajit "${fixtures}/check_xy.lua" "${bindings}/xy_api.lua" "${@}"
}
function py_runner() { # <fake> [arg...]
  local fake_dir
  fake_dir="$(fake_of "${1}")"
  shift
  env -u "${loader}" "${libvar}=${fake_dir}/${so}" "${XY_PYTHON}" "${fixtures}/check_xy.py" "${python_mod}" "${@}"
}

# pair_in <first> <second>: the two consecutive lines of captured stderr.
function pair_in() {
  grep -F -A1 -- "${1}" "${capture}/err" | tail -n +2 | grep -qxF -- "${2}"
}

# py <expr> <out> [path...]: write the Python expression's value to <out>; eval sees support,
# support_xy32, argv (this command's own argv, 1-based strings) and read() — the shell quotes paths, so
# python literals never carry them. Fails, <out> removed, when the interpreter fails or writes
# nothing, so a case never reads input py did not produce.
function py() {
  local expr="${1}" out="${2}"
  shift 2
  "${XY_PYTHON:?}" -c 'import sys
from langxyne.tests import support, support_xy32
argv = lambda i: sys.argv[i]
read = lambda p: open(p, encoding="utf-8").read()
sys.stdout.write(eval(sys.argv[1]))' "${expr}" ${@+"${@}"} >"${out}" && [[ -s "${out}" ]] && return
  command rm -f "${out}"
  return 1
}

# write_definition <attribute> <out>: the definition generate reads next, support's attribute or,
# qualified, support_xy32's; without it the loop cannot run, exit 2, as for generate's own failure.
function write_definition() {
  local attribute="${1}"
  [[ "${attribute}" == *.* ]] || attribute="support.${attribute}"
  py "${attribute}" "${2}" && return
  fail "generation (${2##*/})" "input not produced"
  printf 'run-bindings: %s was not written; the loop cannot run\n' "${attribute}" >&2
  exit 2
}

function want_constants() { # every constant's `NAME=value`, sorted, into the run's constants file
  py "chr(10).join('%s=%s' % kv for kv in sorted(support.expected_constants(support.load(support.KITCHEN_SINK)).items())) + chr(10)" "${work}/constants"
}

# py_definition_plan <definition> <header>: the definition's API name to ${work}/api_name, the
# outputs its round trip generates to ${work}/outputs, and, only
# where the definition names a wrapped API, the one header bindgen renders — every one
# `_headers` names, as a build's wrapper would — to <header>; fails where any is not produced.
function py_definition_plan() {
  local definition="${1}" header="${2}"
  py "'%s' % support.load(read(argv(2))).name" "${work}/api_name" "${definition}" || return 1
  py "support_xy32.round_trip_outputs(read(argv(2)))" "${work}/outputs" "${definition}" || return 1
  py "'%d' % (support.load(read(argv(2))).wrapped_api is not None)" "${work}/wrapped" "${definition}" || return 1
  [[ "$(cat "${work}/wrapped")" == 1 ]] || return 0
  py "chr(10).join('#include \"%s\"' % h for h in support.load(read(argv(2))).wrapped_api.headers) + chr(10)" \
    "${header}" "${definition}"
}

function go_env() { env CGO_ENABLED=1 CC=clang GOTOOLCHAIN=local GOPROXY=off GOWORK=off GOFLAGS=-buildvcs=false GOENV=off "${@}"; }
# go_stage <dir> <binding> [main]: <dir> as module ${gomod} at the binding's floor, the
# package its `xy_api`, and main, where given, its main package.
function go_stage() {
  mkdir -p "${1}/xy_api"
  printf 'module %s\n\ngo 1.21\n' "${gomod}" >"${1}/go.mod"
  command cp "${2}" "${1}/xy_api/xy_api.go"
  [[ -z "${3:-}" ]] || command cp "${3}" "${1}/main.go"
}
function go_build() { # <module> <program> <library> [experiment]
  local experiment=""
  [[ -z "${4:-}" ]] || experiment="GOEXPERIMENT=${4}"
  ( cd "${1}" && attempt_in . go_env CGO_LDFLAGS="-L${3}" ${experiment:+"${experiment}"} env go build -o "${2}" "." )
}

function generate() { # <def file> <out dir> [extra flags...]: the generator, the loop's one
  # door to its trees; a failure here is exit 2, no tree means no loop.
  local label="generation (${1##*/})"
  if run_case "${label}" none - -- "${XY_PYTHON}" -m langxyne "${1}" --generated "${2}" "${@:3}"; then :; else
    printf 'run-bindings: %s failed; the loop cannot run\n' "${label}" >&2
    exit 2
  fi
}

root="${work}/tree"
rsfake="${root}/rsfake"
inc="${root}/generated/include/xy"
rust_dir="${root}/generated/rust"
stub_rs="${root}/generated/stub/xy_api.rs"
bindings="${root}/generated/lua"
python_mod="${root}/generated/python/xy_api.py"
bindgen_out="${root}/.bindgen"
bad_bindgen_out="${root}/.bindgen-bad"
libvar="$("${XY_PYTHON}" -c 'from langxyne import naming; print(naming.library_variable("xy"))' </dev/null)"
export LUA_PATH="${bindings}/?.lua${LUA_PATH:+;${LUA_PATH}};;"

mkdir -p "${root}" "${bindgen_out}" "${bad_bindgen_out}"
write_definition KITCHEN_SINK "${root}/xy_api.adef.toml"
generate "${root}/xy_api.adef.toml" "${root}/generated" --project xy --outputs="${NATIVE_OUTPUTS}"

# shellcheck source=run-bindings-c.sh
source "${here}/run-bindings-c.sh"
# shellcheck source=run-bindings-lua.sh
source "${here}/run-bindings-lua.sh"
# shellcheck source=run-bindings-rust.sh
source "${here}/run-bindings-rust.sh"
# shellcheck source=run-bindings-go.sh
source "${here}/run-bindings-go.sh"
# shellcheck source=run-bindings-python.sh
source "${here}/run-bindings-python.sh"
# shellcheck source=run-bindings-static.sh
source "${here}/run-bindings-static.sh"
# shellcheck source=run-bindings-node.sh
source "${here}/run-bindings-node.sh"
# shellcheck source=run-bindings-definitions.sh
source "${here}/run-bindings-definitions.sh"

printf 'run-bindings: %d checks, %d FAIL\n' "${checks}" "${failures}"
exit "$((failures > 0))"
