# shellcheck shell=bash
# run-bindings.sh's part for the Python output, sourced by it in order: its helpers, counters and
# tree paths are run-bindings.sh's.

# python: the module under the venv's interpreter, the library variable naming its fake
run_case 'generated/python/xy_api.py (byte-compile)' none - -- "${XY_PYTHON}" -m py_compile "${python_mod}"
run_case 'check_xy.py (constants, cpp fake)' constants - -- \
  env -u "${loader}" "${libvar}=${root}/${so}" "${XY_PYTHON}" "${fixtures}/check_xy.py" "${python_mod}"
run_case 'check_xy.py (constants, rust fake)' constants - -- \
  env -u "${loader}" "${libvar}=${rsfake}/${so}" "${XY_PYTHON}" "${fixtures}/check_xy.py" "${python_mod}"
run_case 'check_xy.py (select, cpp fake)' rc nz - -- \
  env -u "${loader}" "${libvar}=${root}/${so}" "${XY_PYTHON}" "${fixtures}/check_xy.py" "${python_mod}" select
run_case 'check_xy.py (select, rust fake)' none - -- \
  env -u "${loader}" "${libvar}=${rsfake}/${so}" "${XY_PYTHON}" "${fixtures}/check_xy.py" "${python_mod}" select
notes_cases check_xy.py py_runner
notes_past_count check_xy.py 'xy_on_notes received view seen refused at record 1, offset 16: count not met' py_runner
for step in nested nested95 outside off_thread; do
  run_case "check_xy.py (${step}, cpp fake)" none - -- \
    env -u "${loader}" "${libvar}=${root}/${so}" "${XY_PYTHON}" "${fixtures}/check_xy.py" "${python_mod}" "${step}"
done
# load resolution: beside its library it opens a port; alone, run from a directory holding
# the library, it searches nothing; a relative library variable is refused
loadtmp="$(mktemp -d "${work}/load.XXXX")"
beside="${loadtmp}/beside"; alone="${loadtmp}/alone"; holding="${loadtmp}/holding"
mkdir -p "${beside}" "${alone}" "${holding}"
command cp "${python_mod}" "${beside}/xy_api.py"
command cp "${python_mod}" "${alone}/xy_api.py"
command cp "${root}/${so}" "${beside}/${so}"
run_case 'check_xy.py (open, beside its library)' none - -- \
  attempt_in "${loadtmp}" env -u "${loader}" -u "${libvar}" "${XY_PYTHON}" "${beside}/xy_api.py" open
# the message holds the path then the OSError's text, so the stem and the path are pinned apart
needles=('ImportError: cannot load the library xy from' "${alone}")
run_case 'check_xy.py (open, alone, cwd holds the library)' rc nz - -- \
  attempt_in "${holding}" env -u "${loader}" -u "${libvar}" "${XY_PYTHON}" "${alone}/xy_api.py" open
run_case 'check_xy.py (open, relative library variable refused)' rc nz - -- \
  attempt_in "${beside}" env -u "${loader}" -u "${libvar}" "${libvar}=${so}" "${XY_PYTHON}" "${beside}/xy_api.py" open
# a port without _hides_pointer keeps the unlocked class
unhidden="${work}/unhidden"
mkdir -p "${unhidden}"
write_definition UNHIDDEN_PORT "${unhidden}/xy_api.adef.toml"
generate "${unhidden}/xy_api.adef.toml" "${unhidden}" --project xy --outputs=py
for fake in cpp rust; do
  fake_dir="$(fake_of "${fake}")"
  run_case "check_xy.py (unhidden, ${fake} fake)" none - -- \
    env -u "${loader}" "${libvar}=${fake_dir}/${so}" "${XY_PYTHON}" "${fixtures}/check_xy.py" "${unhidden}/python/xy_api.py" unhidden
done
# the layouts of the structs: the header's own, both definitions
function layouts() { # <def attr> <generated dir> <fake dir>
  py "support.layout_program(support.${1})" "${work}/layout.c" || { fail "layouts (${1}, build)" 'input not produced'; return; }
  run_case "layouts (${1}, build)" none - -- clang -std=c17 "-I${2}/include/xy" -o "${work}/layout" "${work}/layout.c"
  run_case "layouts (${1}, header)" none - -- "${work}/layout"
  command cp "${capture}/out" "${work}/layout.header"
  # each row's first field, before its size; the field's Name.field split before its first dot
  names="$(awk '{ split($1, a, "."); print a[1] }' "${work}/layout.header" | sort -u)"
  command sort -o "${work}/layout.header" "${work}/layout.header"  # the golden pin sorts stdout, so the want is sorted too
  # names are UpperCamel identifiers, one per line; the word split is the interface
  # shellcheck disable=SC2086
  run_case "layouts (${1}, module vs header)" golden "${work}/layout.header" -- \
    env -u "${loader}" "${libvar}=${3}/${so}" "${XY_PYTHON}" "${fixtures}/layouts.py" "${2}/python/xy_api.py" ${names}
}
layouts KITCHEN_SINK "${root}/generated" "${root}"
layouts REFS "${refs}/generated" "${notes}"
rc=0
attempt env -u "${loader}" "${libvar}=${notes}/${so}" "${XY_PYTHON}" "${fixtures}/in_arrays_refs.py" "${refs}/generated/python/xy_api.py" </dev/null >"${capture}/out" 2>"${capture}/err" || rc="${?}"
if [[ "${rc:-1}" -eq 0 ]] && pair_in 'destroy_port released a port' 'collected'; then
  ok 'in_arrays_refs.py (notes fake)'
else
  fail_cmd 'in_arrays_refs.py (notes fake)' 'exit or stderr order'
fi
