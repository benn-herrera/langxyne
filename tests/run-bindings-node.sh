# shellcheck shell=bash
# run-bindings.sh's part for the wasm shim and the Node binding, sourced by it in order: its
# helpers, counters and tree paths are run-bindings.sh's.

# node: XY32's Node binding over its fake, built with the relay and the shim for wasm32-wasip1 as
# the module file beside the emitted module; the fixture programs beside both, so they import
# ./xy_api.mjs
xy32="${work}/xy32"
node_dir="${xy32}/generated/node"
mkdir -p "${xy32}"
write_definition support_xy32.XY32 "${xy32}/xy_api.adef.toml"
generate "${xy32}/xy_api.adef.toml" "${xy32}/generated" --project xy --outputs="${ALL_OUTPUTS}"
if py "support_xy32.fake_xy32()" "${xy32}/fake_xy32.rs"; then
  run_case "fake_xy32.rs (${WASM_TARGET})" none - -- \
    env LANGXYNE_RUST_DIR="${xy32}/generated/rust" OUT_DIR="${bindgen_out}" \
      rustc --edition "${EDITION}" --target "${WASM_TARGET}" --crate-type cdylib -D warnings \
        -C link-arg=-l:crt1-reactor.o -o "${node_dir}/xy.wasm" "${xy32}/fake_xy32.rs"
  for edition in "${EDITIONS[@]}"; do
    run_case "fake_xy32.rs (shim, clippy ${edition})" none - -- \
      env LANGXYNE_RUST_DIR="${xy32}/generated/rust" OUT_DIR="${bindgen_out}" \
        clippy-driver --edition "${edition}" --target "${WASM_TARGET}" --crate-type cdylib -D warnings \
          -C link-arg=-l:crt1-reactor.o -o "${xy32}/xy_clippy_${edition}.wasm" "${xy32}/fake_xy32.rs"
  done
else
  fail "fake_xy32.rs (${WASM_TARGET})" 'input not produced'
fi
# XY32_UNHIDDEN's Node binding beside XY32's as xy_api_unhidden.mjs, loading the same xy.wasm
unhidden32="${xy32}/unhidden"
mkdir -p "${unhidden32}"
write_definition support_xy32.XY32_UNHIDDEN "${unhidden32}/xy_api.adef.toml"
generate "${unhidden32}/xy_api.adef.toml" "${unhidden32}" --project xy --outputs=node
command cp "${unhidden32}/node/xy_api.mjs" "${node_dir}/xy_api_unhidden.mjs"
command cp "${unhidden32}/node/xy_api.d.mts" "${node_dir}/xy_api_unhidden.d.mts"
marshalling=check_xy32_marshalling.mjs
lifetime=check_xy32_lifetime.mjs
command cp "${fixtures}/${marshalling}" "${fixtures}/${lifetime}" "${fixtures}/check_xy32_shared.mjs" \
  "${fixtures}/node_xy32.d.ts" "${node_dir}/"
run_case 'check_xy32 programs (tsc)' none - -- \
  tsc --strict --noEmit --allowJs --checkJs --module nodenext \
    "${node_dir}/${marshalling}" "${node_dir}/${lifetime}" "${node_dir}/node_xy32.d.ts"
# the golden pin sorts stdout, so the want is sorted the same way
if py "chr(10).join('%s=%s' % kv for kv in support.expected_constants(support.load(support_xy32.XY32)).items()) + chr(10)" "${work}/constants_xy32"; then
  command sort -o "${work}/constants_xy32" "${work}/constants_xy32"
  run_case "${marshalling} (constants)" golden "${work}/constants_xy32" -- node "${node_dir}/${marshalling}" constants
else
  fail "${marshalling} (constants)" 'input not produced'
fi
for step in calls load stack; do
  run_case "${marshalling} (${step})" none - -- node "${node_dir}/${marshalling}" "${step}"
done
run_case "${marshalling} (notes)" stdout "${fixtures}/notes_xy.txt" -- node "${node_dir}/${marshalling}" notes
# the Rust fake refuses no record
for selector in 101 102 103 104 105 106; do
  run_case "${marshalling} (notes ${selector})" rc 100 - -- node "${node_dir}/${marshalling}" notes "${selector}"
done
for step in reentry after failure growth unlocked nested foreign; do
  run_case "${lifetime} (${step})" none - -- node "${node_dir}/${lifetime}" "${step}"
done
needles=('fake seek: offset u32::MAX')
run_case "${lifetime} (dead)" none - -- node "${node_dir}/${lifetime}" dead
