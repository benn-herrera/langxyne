-- Exactness checks of the generated integer support module, reached through the generated
-- binding: a parse, a print and a compare that cross the 2^53 line exactly, both directions,
-- and the refusals that name why. The support module has a fixed name, the same for every
-- binding; only the binding's directory has to be on LUA_PATH for it, and this fixture never
-- names ffi, as no consumer of the binding may.
local xy = dofile(arg[1])
local i64 = require("i64")

local function digits(text, parsed)
    -- one decimal text's exact round trip through parse and print, the number handed on
    assert(i64.tostring(parsed) == text, "round trip of " .. text .. " printed " .. i64.tostring(parsed))
    return parsed
end

local max = digits("9223372036854775807", i64.parse_int64("9223372036854775807"))
local min = digits("-9223372036854775808", i64.parse_int64("-9223372036854775808"))
assert(i64.tostring(i64.UINT64_MAX) == "18446744073709551615", "MAX_U32 absent, UINT64_MAX prints folded")
assert(i64.lt(min, max) and not i64.eq(min, max), "the extremes do not order")
assert(not i64.ge(max, i64.UINT64_MAX) and i64.lt(max, i64.UINT64_MAX), "the i64 maximum is below the u64 one")

-- the straddle of 2^53, the line a Lua double would fold: both sides distinguished exactly
local below = digits("9007199254740992", i64.parse_int64("9007199254740992"))
local above = digits("9007199254740993", i64.parse_int64("9007199254740993"))
assert(i64.lt(below, above) and not i64.eq(below, above), "the straddle folded")
assert(i64.eq(below, 9007199254740992), "the exact straddle number reads equal")
assert(i64.gt(above, 9007199254740992), "the straddle's other side is above its number")
assert(i64.lt(9007199254740992, above), "a plain number below compares below")
assert(i64.ge(i64.INT64_MAX, max) and i64.le(i64.INT64_MIN, min), "the constants are those values")

assert(i64.lt(-1, below), "protection against coercion of negative to u64 failed")
assert(i64.lt(-2, -1), "protection against coercion of negative to u64 failed")
assert(i64.gt(below, -1), "protection against coercion of negative to u64 failed")
assert(i64.gt(-1, -2), "protection against coercion of negative to u64 failed")

-- refusals name why
for _, case in ipairs({
    { "9223372036854775808", "overflow", i64.parse_int64 },
    { "18446744073709551616", "overflow", i64.parse_uint64 },
    { "-1", "malformed", i64.parse_uint64 },
    { "", "malformed", i64.parse_int64 },
    { "1e3", "malformed", i64.parse_int64 },
}) do
    local value, reason = case[3](case[1])
    assert(value == nil and reason == case[2], case[1] .. " answered " .. tostring(value) .. "," .. tostring(reason))
end

-- compare refuses its string operands: callers parse them first, and the refusal is the raise
assert(not pcall(i64.lt, max, "9223372036854775807"), "a string operand of lt did not raise")
assert(not pcall(i64.eq, "9223372036854775807", max), "a string operand of eq did not raise")

print("i64 ok")
