# shellcheck shell=bash
# run-bindings.sh's part for the Go output, sourced by it in order: its helpers, counters and
# tree paths are run-bindings.sh's.

# go: the module at the binding's floor, vetted, built bare and under cgocheck2, run
go_stage "${root}/gomod" "${root}/generated/go/xy_api/xy_api.go" "${fixtures}/consumer_xy.go"
run_case 'consumer_xy.go' none - -- go_build "${root}/gomod" "${root}/consumer_go" "${root}"
run_case 'consumer_xy.go (cgocheck2)' none - -- go_build "${root}/gomod" "${root}/consumer_go_cgocheck2" "${root}" cgocheck2
for fake in cpp rust; do
  fake_dir="$(fake_of "${fake}")"
  run_case "consumer_xy.go (bare, ${fake} fake)" none - -- env "$(searched "${fake_dir}")" "${root}/consumer_go"
  run_case "consumer_xy.go (cgocheck2, ${fake} fake)" none - -- env "$(searched "${fake_dir}")" "${root}/consumer_go_cgocheck2"
done
notes_cases 'consumer_xy.go' bin_runner "${root}/consumer_go"
notes_past_count 'consumer_xy.go' 'xy_on_notes: seen: record 1 at offset 16: count not met' bin_runner "${root}/consumer_go"
notes_golden 'consumer_xy.go cgocheck2' bin_runner "${root}/consumer_go_cgocheck2"
run_case 'consumer_xy.go (nested, cpp fake)' none - -- env "$(searched "${root}")" "${root}/consumer_go" nested
run_case 'consumer_xy.go (nested95, cpp fake)' none - -- env "$(searched "${root}")" "${root}/consumer_go" nested95
needles=('xy_seek returned a value xy_status does not name')
run_case 'consumer_xy.go (select, cpp fake)' rc nz - -- env "$(searched "${root}")" "${root}/consumer_go" select
run_case 'consumer_xy.go (select, rust fake)' none - -- env "$(searched "${rsfake}")" "${root}/consumer_go" select
needles=('xy_on_batch received a user_data no driving call of it made')
run_case 'consumer_xy.go (foreign, exit 2, cpp fake)' rc 2 - -- env "$(searched "${root}")" "${root}/consumer_go" foreign
needles=('unsafe.Slice: ptr is nil and len is not zero')
run_case 'consumer_xy.go (outside, exit 2, cpp fake)' rc 2 - -- env "$(searched "${root}")" "${root}/consumer_go" outside
# every definition's package vetted clean at the module's floor
for vet_def in KITCHEN_SINK REFS MINIMAL; do
  vet_dir="${work}/vet/${vet_def}"
  mkdir -p "${vet_dir}"
  write_definition "${vet_def}" "${vet_dir}/xy_api.adef.toml"
  generate "${vet_dir}/xy_api.adef.toml" "${vet_dir}/generated" --project xy --outputs=go --library xy
  go_stage "${vet_dir}/mod" "${vet_dir}/generated/go/xy_api/xy_api.go"
  run_case "go vet (${vet_def})" none - -- attempt_in "${vet_dir}/mod" go_env go vet "./..."
done
go_stage "${root}/vetmod" "${root}/generated/go/xy_api/xy_api.go" "${fixtures}/copy_xy.go"
refuse_case 'copy_xy.go (vet)' 'copies lock value' -- attempt_in "${root}/vetmod" go_env go vet "./..."
# constants, each name naming's own rule, the values the model's
if py "support.go_constants_main(support.KITCHEN_SINK, argv(2))" "${root}/constants.go" "${gomod}"; then
  go_stage "${root}/constmod" "${root}/generated/go/xy_api/xy_api.go" "${root}/constants.go"
  run_case 'constants.go (build)' none - -- go_build "${root}/constmod" "${root}/constants" "${root}"
  run_case 'constants (go)' constants - -- env "$(searched "${root}")" "${root}/constants"
else
  fail 'constants.go (build)' 'input not produced'
fi
# a struct whose layout is not the header's does not build
swapped="${work}/swapped"
mkdir -p "${swapped}"
if py "support.mutate(read(argv(2)), '\t// items seen\n\tCount uint32\n\tBytes uint64\n', '\tBytes uint64\n\tCount uint32\n')" "${swapped}/xy_api.go" "${root}/generated/go/xy_api/xy_api.go"; then
  go_stage "${swapped}/mod" "${swapped}/xy_api.go"
  refuse_case 'the layout pin (swapped Stats)' 'unsafe.Offsetof(Stats{}.Count)' -- attempt_in "${swapped}/mod" go_env go build "./..."
else
  fail 'the layout pin (swapped Stats)' 'input not produced'
fi
# ctor_refs: a constructor whose check after the call panics releases its handle
go_stage "${work}/ctor/mod" "${refs}/generated/go/xy_api/xy_api.go" "${fixtures}/ctor_refs.go"
run_case 'ctor_refs.go (build)' none - -- go_build "${work}/ctor/mod" "${work}/ctor/ctor" "${notes}"
rc=0
attempt_in "${work}/ctor/mod" env "$(searched "${notes}")" "${work}/ctor/ctor" || rc="${?}"
if [[ "${rc:-1}" -eq 0 ]] && pair_in 'destroy_port released a port' 'recovered: xy_open_port wrote a generation value xy_mode does not name'; then
  ok 'ctor_refs.go (handle released, notes fake)'
else
  fail_cmd 'ctor_refs.go (handle released, notes fake)' "exit or stderr order"
fi
