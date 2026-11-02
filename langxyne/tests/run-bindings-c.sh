# shellcheck shell=bash
# run-bindings.sh's part for the fakes and the C and C++ outputs, sourced by it in order: its
# helpers, counters and tree paths are run-bindings.sh's.

# the fakes, cpp into the tree itself, rust into rsfake, then the consumers against each
run_case 'fake_xy_notify.c' none - -- \
  clang -std=c17 -c -fPIC -Wall -Wextra -Werror -I"${inc}" -I"${wrapped}" \
    -o "${root}/fake_xy_notify.o" "${fixtures}/fake_xy_notify.c"
run_case 'fake_xy.cpp (libxy)' none - -- \
  clang++ -std=c++20 -shared -fPIC -Wall -Wextra -Werror -I"${inc}" -I"${wrapped}" \
    -o "${root}/${so}" "${fixtures}/fake_xy.cpp" "${root}/fake_xy_notify.o"
run_case 'wrapped/xy/driver/xy_ioctl.h (bindgen)' none - -- \
  bindgen "${header}" -o "${bindgen_out}/wrapped_api.rs" -- "-I${wrapped}"
run_case 'wrapped_bad/xy/driver/xy_ioctl.h (bindgen)' none - -- \
  bindgen "${bad_header}" -o "${bad_bindgen_out}/wrapped_api.rs" -- "-I${fixtures}/wrapped_bad"
mkdir -p "${rsfake}"
run_case 'fake_xy.rs' none - -- \
  env LANGXYNE_RUST_DIR="${rust_dir}" OUT_DIR="${bindgen_out}" \
    rustc --edition "${EDITION}" --crate-type cdylib -D warnings \
      -o "${rsfake}/${so}" "${fixtures}/fake_xy.rs"
run_case 'fake_xy.rs (clippy 2021)' none - -- \
  env LANGXYNE_RUST_DIR="${rust_dir}" OUT_DIR="${bindgen_out}" \
    clippy-driver --edition 2021 --crate-type cdylib -D warnings \
      -o "${rsfake}/libxy_gate_2021.${dylib_suffix}" "${fixtures}/fake_xy.rs"
run_case 'fake_xy.rs (clippy 2024)' none - -- \
  env LANGXYNE_RUST_DIR="${rust_dir}" OUT_DIR="${bindgen_out}" \
    clippy-driver --edition 2024 --crate-type cdylib -D warnings \
      -o "${rsfake}/libxy_gate_2024.${dylib_suffix}" "${fixtures}/fake_xy.rs"

# edge_xy.c, the bare C caller of the Rust fake: its relay answers what no binding sends, and
# its panic is the extern "C" boundary's, not an unwind that failed to start
run_case 'edge_xy.c' none - -- \
  clang -std=c17 -Wall -Wextra -Werror -I"${inc}" -o "${rsfake}/edge" "${fixtures}/edge_xy.c" "-L${rsfake}" -lxy
run_case 'edge (rust fake)' none - -- env "$(searched "${rsfake}")" "${rsfake}/edge"
notes_cases edge bin_runner "${rsfake}/edge"
notes_past_count edge 'xy_on_notes: seen: record 1 at offset 16: count not met' bin_runner "${rsfake}/edge"
needles=('fake seek: offset u64::MAX' 'panic in a function that cannot unwind')
run_case 'edge (panic, rust fake)' rc 134 - -- env "$(searched "${rsfake}")" "${rsfake}/edge" panic

# the constants and types of the generated header, as _Static_asserts over the model
function values_cases() { # <expr>: values.c from the expression, then its consumer and implementation TUs
  py "${1}" "${root}/values.c" || { fail 'values.c (consumer TU)' 'input not produced'; return; }
  run_case 'values.c (consumer TU)' none - -- \
    clang -x c -std=c17 -fsyntax-only -Wall -Wextra -Werror -I"${inc}" "${root}/values.c"
  run_case 'values.c (implementation TU, pins)' none - -- \
    clang -x c -std=c17 -fsyntax-only -Wall -Wextra -Werror -I"${inc}" -DXY_IMPL -I"${wrapped}" "${root}/values.c"
}
values_cases "support.values_tu()"
# py's guard pinned: an expression that raises fails the case reading its output. The subshell
# keeps that run's counts apart, so its expected FAIL is this case's ok.
guard='values.c (an expression that raises fails the case)'
if ( values_cases "1 // 0" ) >"${work}/raises" 2>&1; then
  fail "${guard}" 'passed, must not'
elif grep -qxF 'values.c (consumer TU): FAIL input not produced' "${work}/raises"; then
  ok "${guard}"
else
  fail "${guard}" "$(head -n 1 "${work}/raises")"
fi

# the implementation stub over its header: built with the wrapped header's pins active, refused
# where a pin differs
run_case 'generated/stub/xy_api.cpp (pins)' none - -- \
  clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Werror -I"${inc}" -I"${wrapped}" "${root}/generated/stub/xy_api.cpp"
refuse_case 'generated/stub/xy_api.cpp (bad pins)' 'XY_FEAT_A must match XYD_FEAT_A' -- \
  clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Werror -I"${inc}" -I"${fixtures}/wrapped_bad" \
    "${root}/generated/stub/xy_api.cpp"

run_case 'consumer_xy.cpp' none - -- \
  clang++ -std=c++20 -fno-exceptions -Wall -Wextra -Wshadow -Werror -I"${inc}" \
    -o "${root}/consumer" "${fixtures}/consumer_xy.cpp" "-L${root}" -lxy
run_case 'lying_xy.cpp' none - -- \
  clang++ -std=c++20 -fno-exceptions -Wall -Wextra -Wshadow -Werror -I"${inc}" \
    -o "${root}/lying" "${fixtures}/lying_xy.cpp" "-L${root}" -lxy
run_case 'consumer_xy.cpp (cpp fake)' stdout "${fixtures}/notes_xy.txt" -- env "$(searched "${root}")" "${root}/consumer"
run_case 'consumer_xy.cpp (rust fake)' stdout "${fixtures}/notes_xy.txt" -- env "$(searched "${rsfake}")" "${root}/consumer"
notes_refused consumer_xy.cpp bin_runner "${root}/consumer"
notes_past_count consumer_xy.cpp 'xy_on_notes: seen: record 1 at offset 16: count not met' bin_runner "${root}/consumer"
run_case 'lying_xy.cpp (nested, cpp fake)' none - -- env "$(searched "${root}")" "${root}/lying" nested
needles=('xy_on_batch called on another thread than the one calling xy_stream')
run_case 'lying_xy.cpp (off_thread, cpp fake)' rc 134 - -- env "$(searched "${root}")" "${root}/lying" off_thread
refuse_case 'not_flow_xy.cpp' 'sink must return xy::Flow' -- \
  clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Werror -I"${inc}" "${fixtures}/not_flow_xy.cpp"
refuse_case 'not_member_xy.cpp' 'T must be a member of union note' -- \
  clang++ --std=c++20 -fsyntax-only -Wall -Wextra -Werror -I"${inc}" "${fixtures}/not_member_xy.cpp"
refuse_case 'nodiscard_xy.cpp' 'unused-result' -- \
  clang++ --std=c++20 -fsyntax-only -Werror=unused-result -I"${inc}" "${fixtures}/nodiscard_xy.cpp"

# bit 31 of a u32 group: the header and the wrapper carry it, wide_xy.cpp proves it
bit31="${work}/bit31"
mkdir -p "${bit31}"
write_definition BIT_THIRTY_ONE "${bit31}/xy_api.adef.toml"
generate "${bit31}/xy_api.adef.toml" "${bit31}/generated" --project xy --outputs=h,hpp
run_case 'wide_xy.cpp' none - -- \
  clang++ -std=c++20 -Wall -Wextra -Werror "-I${bit31}/generated/include/xy" -o "${bit31}/wide" "${fixtures}/wide_xy.cpp"
run_case 'wide (bit 31)' none - -- "${bit31}/wide"
