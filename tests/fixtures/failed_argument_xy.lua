-- Over the Lua module (arg[1]) of support.KITCHEN_SINK with stream's sink before its cuts: a cuts
-- table that fails to convert after the callback is cast, 2100 times, above the callbacks LuaJIT
-- holds at once, each raising the conversion error, so every cast is freed; then a cast still works.
local M = dofile(arg[1])
local ffi = require("ffi")
local p = assert(M.Port.new(1))
for _ = 1, 2100 do
    local ok, err = pcall(p.stream, p, 1, function() end, {"x"})
    assert(not ok and err:find("cannot convert", 1, true), err)
end
ffi.cast("xy_on_batch", function() end):free()
assert(p:destroy_port())
