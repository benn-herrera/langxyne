-- Runs support.KITCHEN_SINK's Lua module (arg[1]) against the C++ fake's shared library `xy`, for
-- what only that fake does: stream(96)'s function calls seek(96) on another port, during which the
-- library calls the sink again; that invocation reaches no Lua code and is the call's failure, so
-- the function runs once and stream raises naming it. Every check is an assert, so a failure exits
-- nonzero naming its line.
local M = dofile(arg[1])

local function checks()
    local p = assert(M.Port.new(1))
    local q = assert(M.Port.new(2))
    local runs = 0
    local ok, message = pcall(p.stream, p, 96, {}, function()
        runs = runs + 1
        assert(q:seek(96) == true)
    end)
    assert(not ok and runs == 1)
    assert(message:find("xy_on_batch called again while a call of it was running in xy_stream", 1, true))
end

-- As check_xy.lua: a failure leaves Ports with GC finalizers behind, which luajit's error exit
-- runs after unloading the library, so report it here and exit without closing the state.
local ok, message = xpcall(checks, debug.traceback)
if not ok then
    io.stderr:write(message, "\n")
    os.exit(1)
end
