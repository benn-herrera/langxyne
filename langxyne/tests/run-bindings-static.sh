# shellcheck shell=bash
# run-bindings.sh's part for the statically linked Rust and Go bindings, sourced by it in order:
# its helpers, counters and tree paths are run-bindings.sh's.

# static: libxy.a alone, the bindings' static hints linked against it, no loader variable
static="${work}/static"
archive="${static}/archive"
mkdir -p "${archive}"
run_case 'fake_xy.o (static)' none - -- \
  clang++ -std=c++20 -c -fPIC -fno-exceptions -Wall -Wextra -Werror -I"${inc}" -I"${wrapped}" -o "${static}/fake_xy.o" "${fixtures}/fake_xy.cpp"
run_case 'libxy.a (archive)' none - -- ar rcs "${archive}/libxy.a" "${static}/fake_xy.o" "${root}/fake_xy_notify.o"
entries="$(cd "${archive}" && command ls -A)"
if [[ "${entries}" == "libxy.a" ]]; then ok 'archive holds libxy.a alone'; else fail 'archive holds libxy.a alone' "holds: ${entries}"; fi
write_definition KITCHEN_SINK "${static}/xy_api.adef.toml"
generate "${static}/xy_api.adef.toml" "${static}/generated" --project xy --outputs=rs --link=static
run_case 'static/rust/xy_api.rs (rustfmt)' none - -- rustfmt --check --edition 2024 --config-path /dev/null "${static}/generated/rust/xy_api.rs"
for edition in "${EDITIONS[@]}"; do
  run_case "static/rust/xy_api.rs (clippy lib ${edition})" none - -- \
    clippy-driver --edition "${edition}" --crate-type lib -D warnings \
      -o "${static}/libxy_api_${edition}.rlib" "${static}/generated/rust/xy_api.rs"
done
command cp "${fixtures}/consumer_xy.rs" "${static}/generated/rust/consumer_xy.rs"
run_case 'consumer_static (build)' none - -- \
  rustc --edition "${EDITION}" "-L${archive}" -o "${static}/consumer_static" "${static}/generated/rust/consumer_xy.rs"
run_case 'consumer_static (runs, no loader variable)' none - -- env -u "${loader}" "${static}/consumer_static"
generate "${static}/xy_api.adef.toml" "${static}/generated" --project xy --outputs=go --link=static
go_stage "${static}/gomod" "${static}/generated/go/xy_api/xy_api.go" "${fixtures}/consumer_xy.go"
run_case 'consumer_xy.go (static vet)' none - -- \
  attempt_in "${static}/gomod" go_env CGO_LDFLAGS="-L${archive}" go vet "./..."
run_case 'consumer_xy.go (static build)' none - -- go_build "${static}/gomod" "${static}/consumer" "${archive}"
run_case 'consumer_xy.go (static runs, no loader variable)' none - -- env -u "${loader}" "${static}/consumer"
