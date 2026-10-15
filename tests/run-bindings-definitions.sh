# shellcheck shell=bash
# run-bindings.sh's part for the consuming definitions' round trip, sourced by it in order: its
# helpers, counters and paths are run-bindings.sh's.

# the definitions: every consuming definition (any *.adef.toml under the tree) round-trips, the
# consuming repository's tree LANGXYNE_DEFINITIONS names or else the fixture tree; a
# definition's own directory is its project directory
definitions="${LANGXYNE_DEFINITIONS:-${fixtures}/definitions}"
while IFS= read -r definition; do
  project_dir="$(dirname "${definition}")"
  project="$(basename "${project_dir}")"
  gen="${work}/definition/${project}/generated"
  mkdir -p "${gen}"
  definition_include="${gen}/include/${project}"
  py_definition_plan "${definition}" "${work}/definition/${project}/wrapped_api.h" || {
    fail "definition ${project} (plan)" 'input not produced'; continue; }
  api_name="$(cat "${work}/api_name")"
  outputs="$(cat "${work}/outputs")"
  run_case "definition ${project} (generation)" none - -- \
    "${XY_PYTHON}" -m langxyne "${definition}" --generated "${gen}" --project "${project}" --outputs="${outputs}"
  # the stub includes a wrapped header as <project>/<header>, so its root is the project directory's parent
  run_case "definition ${project} (stub syntax)" none - -- \
    clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Werror "-I${definition_include}" "-I${project_dir%/*}" "${gen}/stub/"*.cpp
  printf '#include "%s.hpp"\n' "$(basename "${definition}" .adef.toml)" >"${work}/tu.cpp"
  run_case "definition ${project} (wrapper syntax)" none - -- \
    clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Werror "-I${definition_include}" "${work}/tu.cpp"
  # one file per luajit -bl: given two, it writes the first one's listing over the second
  for lua in "${gen}/lua/"*.lua; do
    run_case "definition ${project} (luajit -bl ${lua##*/})" none - -- luajit -bl "${lua}"
  done
  run_case "definition ${project} (rustfmt)" none - -- \
    rustfmt --check --edition 2024 --config-path /dev/null "${gen}/rust/"*_abi.rs "${gen}/stub/"*.rs "${gen}/rust/"*.rs
  if [[ -f "${work}/definition/${project}/wrapped_api.h" ]]; then
    run_case "definition ${project} (bindgen)" none - -- \
      bindgen "${work}/definition/${project}/wrapped_api.h" -o "${gen}/wrapped_api.rs" -- "-I${project_dir}"
    OUT_DIR="${gen}"
  else
    OUT_DIR=""
  fi
  for edition in "${EDITIONS[@]}"; do
    run_case "definition ${project} (clippy cdylib ${edition})" none - -- \
      env LANGXYNE_RUST_DIR="${gen}/rust" ${OUT_DIR:+OUT_DIR="${OUT_DIR}"} \
        clippy-driver --edition "${edition}" --crate-type cdylib -D warnings \
          -o "${gen}/lib${api_name}_stub.${dylib_suffix}" "${gen}/stub/"*.rs
    run_case "definition ${project} (clippy lib ${edition})" none - -- \
      clippy-driver --edition "${edition}" --crate-type lib -D warnings \
        -o "${gen}/lib${api_name}.rlib" "${gen}/rust/${api_name}.rs"
  done
  # the stub with the shim beside its relay, as the library's wasm build includes it
  stub_rs_file=("${gen}/stub/"*.rs)
  if py "support_xy32.with_shim(read(argv(2)), argv(3))" "${gen}/stub_wasm.rs" "${stub_rs_file[0]}" "${api_name}"; then
    for edition in "${EDITIONS[@]}"; do
      run_case "definition ${project} (shim, clippy ${WASM_TARGET} ${edition})" none - -- \
        env LANGXYNE_RUST_DIR="${gen}/rust" ${OUT_DIR:+OUT_DIR="${OUT_DIR}"} \
          clippy-driver --edition "${edition}" --target "${WASM_TARGET}" --crate-type cdylib -D warnings \
            -o "${gen}/${api_name}_${edition}.wasm" "${gen}/stub_wasm.rs"
    done
  else
    fail "definition ${project} (shim)" 'input not produced'
  fi
  if [[ ",${outputs}," == *,node,* ]]; then
    run_case "definition ${project} (node --check)" none - -- node --check "${gen}/node/${api_name}.mjs"
    run_case "definition ${project} (tsc)" none - -- \
      tsc --strict --noEmit --module nodenext "${gen}/node/${api_name}.d.mts"
  fi
done < <(find "${definitions}" -name '*.adef.toml' | sort)
# a tree naming nothing is a setup error, not an empty round-trip
if [[ ! -d "${work}/definition" ]]; then fail "definitions" "${definitions} holds no *.adef.toml"; fi
