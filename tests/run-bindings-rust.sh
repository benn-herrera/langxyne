# shellcheck shell=bash
# run-bindings.sh's part for the Rust outputs, the refs definition's among them, sourced by it in
# order: its helpers, counters and tree paths are run-bindings.sh's.

# rust: the binding's shape (rustfmt, clippy lib), the stub over the relay (clippy cdylib),
# the consumer at each edition, then the three refusals the pins owe
run_case 'generated/rust/xy_api_abi.rs (rustfmt)' none - -- rustfmt --check --edition 2024 --config-path /dev/null "${rust_dir}/xy_api_abi.rs"
run_case 'generated/rust/xy_api.rs (rustfmt)' none - -- rustfmt --check --edition 2024 --config-path /dev/null "${rust_dir}/xy_api.rs"
run_case 'generated/stub/xy_api.rs (rustfmt)' none - -- rustfmt --check --edition 2024 --config-path /dev/null "${stub_rs}"
for edition in "${EDITIONS[@]}"; do
  run_case "generated/rust/xy_api.rs (clippy lib ${edition})" none - -- \
    clippy-driver --edition "${edition}" --crate-type lib -D warnings \
      -o "${root}/libxy_api_clippy_${edition}.rlib" "${rust_dir}/xy_api.rs"
  run_case "generated/stub/xy_api.rs (clippy cdylib ${edition})" none - -- \
    env LANGXYNE_RUST_DIR="${rust_dir}" OUT_DIR="${bindgen_out}" \
      clippy-driver --edition "${edition}" --crate-type cdylib -D warnings \
        -o "${root}/libxy_stub_${edition}.${dylib_suffix}" "${stub_rs}"
  command cp "${fixtures}/consumer_xy.rs" "${rust_dir}/consumer_xy.rs"
  run_case "consumer_xy.rs (${edition})" none - -- \
    clippy-driver --edition "${edition}" -D warnings "-L${root}" \
      -o "${root}/consumer_rs_${edition}" "${rust_dir}/consumer_xy.rs"
done
for edition in "${EDITIONS[@]}"; do
  for fake in cpp rust; do
    fake_dir="$(fake_of "${fake}")"
    run_case "consumer_rs_${edition} (${fake} fake)" none - -- env "$(searched "${fake_dir}")" "${root}/consumer_rs_${edition}"
  done
  notes_cases "consumer_rs_${edition}" bin_runner "${root}/consumer_rs_${edition}"
  notes_past_count "consumer_rs_${edition}" 'xy_on_notes: seen: record 1 at offset 16: count not met' \
    bin_runner "${root}/consumer_rs_${edition}"
done
refuse_case 'generated/stub/xy_api.rs (bad pins)' 'XY_FEAT_A must match XYD_FEAT_A' -- \
  env LANGXYNE_RUST_DIR="${rust_dir}" OUT_DIR="${bad_bindgen_out}" \
    rustc --edition "${EDITION}" --crate-type cdylib -D warnings \
      -o "${root}/libxy_stub_bad.${dylib_suffix}" "${stub_rs}"
refuse_dir="${root}/.in-callback"
mkdir -p "${refuse_dir}"
command cp "${rust_dir}/xy_api.rs" "${refuse_dir}/xy_api.rs"
for program in release_in_callback_xy.rs drop_in_callback_xy.rs; do
  command cp "${fixtures}/${program}" "${refuse_dir}/${program}"
  # the needle holds literal backticks, from rustc's own diagnostic
  # shellcheck disable=SC2016
  refuse_case "${program}" 'error[E0505]: cannot move out of `port` because it is borrowed' -- \
    rustc --edition "${EDITION}" -o "${refuse_dir}/${program%.rs}" "${refuse_dir}/${program}"
done
command cp "${fixtures}/keep_note_xy.rs" "${refuse_dir}/keep_note_xy.rs"
refuse_case 'keep_note_xy.rs' 'error[E0521]: borrowed data escapes outside of closure' -- \
  rustc --edition "${EDITION}" -o "${refuse_dir}/keep_note_xy" "${refuse_dir}/keep_note_xy.rs"
# the fake_xy.rs variants the relay's fn-pointer pin refuses, one line each
mkdir -p "${root}/.variants"
for variant in static unsafe extra spawn; do
  case "${variant}" in
    static) variant_needles=('error[E0308]' 'one type is more general than the other') ;;
    unsafe) variant_needles=('error[E0308]' 'expected safe fn, found unsafe fn') ;;
    extra) variant_needles=('error[E0308]' 'aborting due to 1 previous error') ;;
    spawn) variant_needles=('error[E0277]' 'cannot be sent between threads safely') ;;
  esac
  py "support.fake_variant('${variant}')" "${root}/.variants/${variant}.rs" || {
    fail "fake_xy.rs (${variant})" 'input not produced'; continue; }
  refuse_case "fake_xy.rs (${variant})" "${variant_needles[@]}" -- \
    env LANGXYNE_RUST_DIR="${rust_dir}" OUT_DIR="${bindgen_out}" \
      rustc --edition "${EDITION}" --crate-type cdylib -D warnings \
        -o "${root}/.variants/libxy_${variant}.${dylib_suffix}" "${root}/.variants/${variant}.rs"
done
# the relay regenerated with a moved-on whence: the stub built over it fails, naming it
relay="${work}/relay"
mkdir -p "${relay}"
write_definition RELAY_WITH_WHENCE "${relay}/xy_api.adef.toml"
generate "${relay}/xy_api.adef.toml" "${relay}/generated" --project xy --outputs=abi_rs
refuse_case 'generated/stub/xy_api.rs (relay changed)' 'error[E0308]' '{seek}' -- \
  env LANGXYNE_RUST_DIR="${relay}/generated/rust" OUT_DIR="${bindgen_out}" \
    rustc --edition "${EDITION}" --crate-type cdylib -D warnings \
      -o "${relay}/libxy_stub_changed.${dylib_suffix}" "${stub_rs}"
# structs named like prelude names the relay does not spell: the module-scope check lets them build
unspelled="${work}/unspelled"
mkdir -p "${unspelled}"
write_definition UNSPELLED_PRELUDE "${unspelled}/xy_api.adef.toml"
generate "${unspelled}/xy_api.adef.toml" "${unspelled}/generated" --project xy --outputs=abi_rs,stub_rs
run_case 'generated/stub/xy_api.rs (unspelled prelude)' none - -- \
  env LANGXYNE_RUST_DIR="${unspelled}/generated/rust" OUT_DIR="${bindgen_out}" \
    clippy-driver --edition "${EDITION}" --crate-type cdylib -D warnings \
      -o "${unspelled}/libxy_stub.${dylib_suffix}" "${unspelled}/generated/stub/xy_api.rs"
# a parameter named like a trampoline builds
tramp="${work}/tramp"
mkdir -p "${tramp}"
write_definition TRAMPOLINE_PARAM "${tramp}/xy_api.adef.toml"
generate "${tramp}/xy_api.adef.toml" "${tramp}/generated" --project xy --outputs=rs
for edition in "${EDITIONS[@]}"; do
  run_case "generated/rust/xy_api.rs (trampoline, clippy lib ${edition})" none - -- \
    clippy-driver --edition "${edition}" --crate-type lib -D warnings \
      -o "${tramp}/libxy_api_${edition}.rlib" "${tramp}/generated/rust/xy_api.rs"
done

# the binding's runs: one program linked once answers its safety contract against either fake
command cp "${fixtures}/select_xy.rs" "${rust_dir}/select_xy.rs"
run_case 'select_xy.rs (rust fake)' none - -- \
  env LANGXYNE_RUST_DIR="${rust_dir}" OUT_DIR="${bindgen_out}" \
    rustc --edition "${EDITION}" "-L${rsfake}" -o "${root}/select_rs" "${rust_dir}/select_xy.rs"
needles=('xy_seek returned a value xy_status does not name')
run_case 'select_xy.rs (cpp fake)' rc nz - -- env "$(searched "${root}")" "${root}/select_rs"
run_case 'select_rs (rust fake, the loader selects)' none - -- env "$(searched "${rsfake}")" "${root}/select_rs"
for program in off_thread_xy.rs nested_xy.rs outside_xy.rs; do
  command cp "${fixtures}/${program}" "${rust_dir}/${program}"
  case "${program}" in
    off_thread_xy.rs)
      run_case 'off_thread_xy.rs (build)' none - -- rustc --edition "${EDITION}" "-L${root}" -o "${root}/off_thread" "${rust_dir}/off_thread_xy.rs"
      needles=('xy_on_batch called on another thread than the one calling xy_stream')
      run_case 'off_thread_xy.rs (abort, cpp fake)' rc 134 - -- env "$(searched "${root}")" "${root}/off_thread" ;;
    nested_xy.rs)
      run_case 'nested_xy.rs (build)' none - -- rustc --edition "${EDITION}" "-L${root}" -o "${root}/nested" "${rust_dir}/nested_xy.rs"
      run_case 'nested_xy.rs (stop resurfaces, cpp fake)' none - -- env "$(searched "${root}")" "${root}/nested" ;;
    outside_xy.rs)
      run_case 'outside_xy.rs (build)' none - -- rustc --edition "${EDITION}" "-L${root}" -o "${root}/outside" "${rust_dir}/outside_xy.rs"
      needles=('xy_on_batch received view fresh outside the definition')
      run_case 'outside_xy.rs (exit 101, cpp fake)' rc 101 - -- env "$(searched "${root}")" "${root}/outside" ;;
  esac
done

# refs: the relay, stub, notes fake, and the programs that check what the library receives
refs="${work}/refs"
mkdir -p "${refs}"
write_definition REFS "${refs}/xy_api.adef.toml"
generate "${refs}/xy_api.adef.toml" "${refs}/generated" --project xy --outputs="${NATIVE_OUTPUTS}"
run_case 'refs/rust/xy_api_abi.rs (rustfmt)' none - -- rustfmt --check --edition 2024 --config-path /dev/null "${refs}/generated/rust/xy_api_abi.rs"
run_case 'refs/rust/xy_api.rs (rustfmt)' none - -- rustfmt --check --edition 2024 --config-path /dev/null "${refs}/generated/rust/xy_api.rs"
run_case 'refs/stub/xy_api.rs (rustfmt)' none - -- rustfmt --check --edition 2024 --config-path /dev/null "${refs}/generated/stub/xy_api.rs"
for edition in "${EDITIONS[@]}"; do
  run_case "refs/stub/xy_api.rs (clippy cdylib ${edition})" none - -- \
    env LANGXYNE_RUST_DIR="${refs}/generated/rust" OUT_DIR="${bindgen_out}" \
      clippy-driver --edition "${edition}" --crate-type cdylib -D warnings \
        -o "${refs}/libxy_stub_${edition}.${dylib_suffix}" "${refs}/generated/stub/xy_api.rs"
  run_case "refs/rust/xy_api.rs (clippy lib ${edition})" none - -- \
    clippy-driver --edition "${edition}" --crate-type lib -D warnings \
      -o "${refs}/libxy_api_${edition}.rlib" "${refs}/generated/rust/xy_api.rs"
done
notes="${work}/notes"
mkdir -p "${notes}"
if py "support.notes_stub(read(argv(2)))" "${notes}/notes.rs" "${refs}/generated/stub/xy_api.rs"; then
  run_case 'refs notes fake (libxy)' none - -- \
    env LANGXYNE_RUST_DIR="${refs}/generated/rust" OUT_DIR="${bindgen_out}" \
      rustc --edition "${EDITION}" --crate-type cdylib -D warnings \
        -o "${notes}/${so}" "${notes}/notes.rs"
else
  fail 'refs notes fake (libxy)' 'input not produced'
fi
command cp "${fixtures}/refs_enums_xy.rs" "${refs}/generated/rust/refs_enums_xy.rs"
command cp "${fixtures}/refs_slice_xy.rs" "${refs}/generated/rust/refs_slice_xy.rs"
run_case 'refs_enums_xy.rs (build)' none - -- \
  env LANGXYNE_RUST_DIR="${refs}/generated/rust" OUT_DIR="${bindgen_out}" \
    rustc --edition "${EDITION}" "-L${notes}" -o "${refs}/refs_enums" "${refs}/generated/rust/refs_enums_xy.rs"
run_case 'refs_enums_xy.rs (round-trips, notes fake)' none - -- env "$(searched "${notes}")" "${refs}/refs_enums"
run_case 'refs_slice_xy.rs (build)' none - -- \
  env LANGXYNE_RUST_DIR="${refs}/generated/rust" OUT_DIR="${bindgen_out}" \
    rustc --edition "${EDITION}" "-L${notes}" -o "${refs}/refs_slice" "${refs}/generated/rust/refs_slice_xy.rs"
needles=('buf is longer than u8 can count')
run_case 'refs_slice_xy.rs (panics its message, notes fake)' none - -- env "$(searched "${notes}")" "${refs}/refs_slice"
run_case 'in_arrays_refs.lua (notes fake)' none - -- \
  env "$(searched "${notes}")" "$(lua_search "${refs}/generated/lua")" \
    luajit "${fixtures}/in_arrays_refs.lua" "${refs}/generated/lua/xy_api.lua"
