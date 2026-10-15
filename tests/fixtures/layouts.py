"""Prints the layout of each `Structure` of the Python module argv[1] that argv[2:] names, as
support.layout_program() prints the header's: `<Name> <size>`, then `<Name>.<field>
<offset>` per field."""

import ctypes
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("xy_api", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for name in sys.argv[2:]:
    structure = getattr(module, name)
    print(name, ctypes.sizeof(structure))
    for field, _ in structure._fields_:
        print(f"{name}.{field}", getattr(structure, field).offset)
