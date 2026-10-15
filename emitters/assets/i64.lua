-- langxyne's static support module, copied byte for byte beside a generated Lua binding; do not edit.
-- i64: exact 64-bit integers for consumers of the generated Lua bindings, which hand back
-- `i64` and `u64` values as cdata. This parses decimal strings into those cdata integers, compares
-- cdata and whole Lua numbers with one another without loss, and prints them exactly; strings are
-- parsed by callers via parse_uint64/parse_int64 first. `ffi` is named only here: no consumer names it.

local ffi = require("ffi")

local M = {}

local UINT64_MAX = ffi.cast("uint64_t", -1)

local function digits_parse(digits, limit)
    -- The grammar [0-9]+ accumulated in uint64_t cdata with the overflow check, `limit` the
    -- largest magnitude admitted, cdata of the same type: value or nil and the reason.
    if digits == "" or digits:find("[^0-9]") then
        return nil, "malformed"
    end
    local u = ffi.cast("uint64_t", 0)
    for i = 1, #digits do
        local d = ffi.cast("uint64_t", string.byte(digits, i) - 48)
        if u > (UINT64_MAX - d) / 10 then
            return nil, "overflow"
        end
        u = u * 10 + d
    end
    if u > limit then
        return nil, "overflow"
    end
    return u
end

-- cast of a string truncates its pointer, not its digits: every bound is its own digits
local INT64_MIN_MAGNITUDE = assert(digits_parse("9223372036854775808", UINT64_MAX))

M.UINT64_MAX = UINT64_MAX
M.INT64_MAX = ffi.cast("int64_t", digits_parse("9223372036854775807", UINT64_MAX))
M.INT64_MIN = ffi.cast("int64_t", INT64_MIN_MAGNITUDE)

function M.parse_uint64(s)
    return digits_parse(s, UINT64_MAX)
end

function M.parse_int64(s)
    -- [+-]?[0-9]+ the i64 holds, the negative magnitude one larger than the positive: the
    -- digits parse as unsigned and only the cast turns the minimum's into the i64's.
    local sign = s:sub(1, 1)
    local negative = sign == "-"
    if sign == "+" or sign == "-" then
        s = s:sub(2)
    end
    local u, reason = digits_parse(s, negative and INT64_MIN_MAGNITUDE or M.INT64_MAX)
    if u == nil then
        return nil, reason
    end
    return negative and (0 - ffi.cast("int64_t", u)) or ffi.cast("int64_t", u)
end

local function is_boxed64(v)
    local kind = type(v)
    kind = (kind == "cdata") and tostring(ffi.typeof(v)) or kind
    return not not (kind == "ctype<int64_t>" or kind == "ctype<uint64_t>")
end

local function compare(a, b)
    if (a < 0) ~= (b < 0) then
        return (a < 0) and -1 or 1
    end
    return (a > b) and 1 or ((a < b) and -1 or 0)
end

function M.lt(a, b)
    return compare(a, b) < 0
end

function M.le(a, b)
    return compare(a, b) <= 0
end

function M.gt(a, b)
    return compare(a, b) > 0
end

function M.ge(a, b)
    return compare(a, b) >= 0
end

function M.eq(a, b)
    return compare(a, b) == 0
end

function M.tostring(v)
    return is_boxed64(v) and tostring(v):gsub("LL$", ""):gsub("U$", "") or tostring(v)
end

return M
