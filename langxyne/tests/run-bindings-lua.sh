# shellcheck shell=bash
# run-bindings.sh's part for the Lua output, sourced by it in order: its helpers, counters and
# tree paths are run-bindings.sh's.

# without the model's constants every `constants` case below fails its compare
want_constants || fail 'constants (model)' 'input not produced'
run_case 'generated/lua/xy_api.lua (byte-compile)' none - -- luajit -bl "${bindings}/xy_api.lua"
for fake in cpp rust; do
  fake_dir="$(fake_of "${fake}")"
  run_case "check_xy.lua (constants, ${fake} fake)" constants - -- \
    env "$(searched "${fake_dir}")" luajit "${fixtures}/check_xy.lua" "${bindings}/xy_api.lua"
  run_case "check_i64_xy.lua (${fake} fake)" i64 - -- \
    env "$(searched "${fake_dir}")" luajit "${fixtures}/check_i64_xy.lua" "${bindings}/xy_api.lua"
done
notes_cases check_xy.lua lua_runner
notes_past_count check_xy.lua 'xy_note_at: record 1 at offset 16: count not met' lua_runner
run_case 'lying_xy.lua (cpp fake)' none - -- \
  env "$(searched "${root}")" luajit "${fixtures}/lying_xy.lua" "${bindings}/xy_api.lua"
run_case 'gc_xy.lua (cpp fake)' none - -- \
  env "$(searched "${root}")" luajit "${fixtures}/gc_xy.lua" "${bindings}/xy_api.lua"
run_case 'gc_error_xy.lua (exit 1, cpp fake)' rc 1 - -- \
  env "$(searched "${root}")" luajit "${fixtures}/gc_error_xy.lua" "${bindings}/xy_api.lua"
# a failed argument after a callback frees its cast: the module whose cuts follow the sink,
# the library never reached, so its own order of the two does not matter
cuts="${work}/cuts"
mkdir -p "${cuts}"
write_definition CUTS_AFTER_SINK "${cuts}/xy_api.adef.toml"
generate "${cuts}/xy_api.adef.toml" "${cuts}/generated" --project xy --outputs=h,lua
for fake in cpp rust; do
  fake_dir="$(fake_of "${fake}")"
  run_case "failed_argument_xy.lua (${fake} fake)" none - -- \
    env "$(searched "${fake_dir}")" "$(lua_search "${cuts}/generated/lua")" \
      luajit "${fixtures}/failed_argument_xy.lua" "${cuts}/generated/lua/xy_api.lua"
done
