-- Over support.REFS's Lua module (arg[1]) against refs_notes_library(): note's `in` array of a
-- struct, its elements tables, and of a boxed scalar, its elements the FFI structs a struct field
-- of the type takes, reach the library as given.
local M = dofile(arg[1])
local ffi = require("ffi")
local p = assert(M.Port.new(1))
local spots = {ffi.new("xy_offset", 1), ffi.new("xy_offset", 2)}
assert(p:note({{count = 1, bytes = 2}, {count = 3, bytes = 4}}, spots) == true)
assert(p:note(nil, {}) == true)
assert(select(2, p:note({{count = 1, bytes = 2}}, spots)) == M.ERR_BUSY)
