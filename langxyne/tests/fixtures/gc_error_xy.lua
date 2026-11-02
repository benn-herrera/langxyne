-- Over support.KITCHEN_SINK's Lua module (arg[1]): an error with a Port unreleased exits 1, its
-- finalizer running at the state's close without crashing it.
local M = dofile(arg[1])
local p = M.Port.new(1)
error("x")
