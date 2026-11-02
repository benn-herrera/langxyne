-- Runs support.KITCHEN_SINK's Lua module (arg[1]) against either fake's shared library `xy`.
-- Prints NAME=value for every constant; every check is an assert, so a failure exits
-- nonzero naming its line. The list steps run the capacities (items, labels) of
-- consumer_xy.rs's codes 21 to 28: (0, 0), (1, 2), (2, 3), (3, 6), (5, 8), (4, 6), (6, 6) and (3, 5).
-- The stream steps run consumer_xy.rs's codes 30 to 37, then 38: a function erroring on its second
-- call raises the function's error after exactly two calls, 2100 times, so every cast is freed, and a
-- following stream still succeeds; 39: 300 calls complete; it cannot show `jit.off`, since the
-- per-call closure already keeps the method from compiling; 40 inside stream(1)'s function,
-- seek(2 ^ 40) on the same port raises naming Port.seek and xy_stream, and the stream succeeds;
-- 41 inside it, destroy_port raises the same way, and send succeeds after the stream; 48 inside it,
-- attach(p) on a DataLink raises naming DataLink.attach, hport and xy_stream, and succeeds after the
-- stream, a raw handle in p's place failing its assert; 49 after destroy_port, attach(p) fails an
-- assert naming hport is a Port used after destroy_port; configure takes the token M.raw.mint
-- writes; 42 notify(1)
-- calls each function once with 1 and succeeds; 43 notify(1) whose first function errors: second
-- never runs, and the error is raised, first having run once; 44 notify(7): first receives 7;
-- 45 stream(98), whose library calls the sink eight times whatever it answers, with a function
-- erroring on its second call: it runs twice, its error is raised, and seek(98) then succeeds, the
-- library having seen a stop; 46 a function answering 0.5 raises naming xy_on_batch, having run
-- once; 47 M.resolve reads a string arena whatever the length says, other cdata within its length,
-- and a byte view while its callback runs within the library's count or a smaller length; the view
-- kept past its stream, resolved without a length, raises naming M.resolve.
-- `notes` runs consumer_xy.cpp's 50 to 53 against either fake: stream_notes for batch 2, 4 and 0,
-- each view walked through M.note_records and each record printed after a test of its head.kind;
-- nothing of a view is kept past its function but offsets and text. 50 the stream answers true
-- after calls of 2, 2, 2 notes (of 4, 2; of 6), every view walked to its count with no refusal (the
-- refusal is the assert's message); 51 at each call fresh's first record is seen's record at seen's
-- bytes less fresh's, seen counts the earlier calls' records and fresh's, and seen's records are
-- every earlier call's fresh records then this call's; 52 every offset recorded so far resolves
-- through M.note_at over seen to its record, and each of fresh's over fresh; 53 M.note_at at seen's offset 4,
-- inside n0, raises "xy_note_at: record 1 at offset 4: offset is not a record's start", and at
-- seen's extent the same clause at the record after the last. Its stdout is the batch-2 stream's
-- records, one line each, as consumer_xy.cpp writes them.
-- `notes <selector>`, 101 to 105, against the C++ fake alone: the stream's second call is refused
-- in both views, each refusal on stderr as `xy_on_notes: <view>: record <i> at offset <o>:
-- <clause>`, the function answering M.HALT, and the process exits with the selector; 100 where the
-- selector is not a decimal number below 256, no view was refused, the stream did not answer
-- M.ERR_AGAIN, or seen's refusal is not fresh's past the earlier records.
-- `notes 106`, against the C++ fake alone: M.note_at over seen at byte 16, the record past seen's
-- count, raises, its message on stderr, the function answering M.HALT, and the process exits 106;
-- 100 where M.note_at did not raise or the stream did not answer M.ERR_AGAIN.
local M = dofile(arg[1])
local ffi = require("ffi")

-- stream(batch, cuts), its sink answering halt on call `halt_on` (nil: never): the method's
-- results, each call's {seen, fresh, last} counts, and whether every view held what the fakes promise.
local function stream(p, batch, cuts, halt_on)
    local calls, views = {}, true
    local ok, err = p:stream(batch, cuts, function(seen, seen_count, fresh, fresh_count, arena, arena_count, last)
        seen_count, fresh_count = tonumber(seen_count), tonumber(fresh_count)
        calls[#calls + 1] = {seen_count, fresh_count, last}
        for i = 0, fresh_count - 1 do
            views = views and fresh[i].id == seen[seen_count - fresh_count + i].id
        end
        for i = 0, seen_count - 1 do
            views = views and M.resolve(seen[i].label, arena, arena_count) == "e" .. i
        end
        views = views and M.resolve({offset = arena_count, length = 2}, arena, arena_count) == nil
        if #calls == halt_on then
            return M.HALT
        end
    end)
    return ok, err, calls, views
end

-- Whether `calls` hold the fresh counts `fresh`, seen counting them up, the last one alone final
-- where `final`.
local function streamed(calls, fresh, final)
    if #calls ~= #fresh then
        return false
    end
    local seen = 0
    for i, count in ipairs(fresh) do
        seen = seen + count
        local last = (final and i == #fresh) and 1 or 0
        if calls[i][1] ~= seen or calls[i][2] ~= count or calls[i][3] ~= last then
            return false
        end
    end
    return true
end

-- Calls `fn(...)`, expecting it to fail as an assertion naming `needle`.
local function type_error(needle, fn, ...)
    local ok, err = pcall(fn, ...)
    return ok == false and err ~= nil and err:find(needle, 1, true) ~= nil
end

local function checks()
    for k, v in pairs(M) do
        if type(v) == "number" then
            print(k .. "=" .. string.format("%d", v))
        elseif type(v) == "string" then
            print(k .. "=" .. v)
        end
    end

    assert(M.status_to_string(9) == "ERR_BUSY")
    assert(M.status_to_string(12345) == "UNKNOWN_STATUS")
    assert(M.mode_to_string(1) == "SLOW")
    assert(M.access_to_string(3) == "ACC_A|ACC_B")
    assert(M.access_to_string(1) == "ACC_A")
    assert(M.access_to_string(0) == "NONE")
    assert(M.access_to_string(9) == "ACC_A|0x8")
    assert(M.access_to_string(-1) == "ACC_A|ACC_B|0xfffffffc")
    assert(M.limit_to_string(16) == "MAX_UNITS")
    assert(M.limit_to_string(M.NEG) == "NEG")
    assert(M.limit_to_string(M.FLOOR) == "FLOOR")
    assert(M.limit_to_string(99) == "UNKNOWN")
    for _, convert in ipairs({M.status_to_string, M.mode_to_string, M.access_to_string, M.limit_to_string}) do
        assert(convert(nil) == "nil")
    end
    assert(M.Token == nil)
    -- FFI functions are cdata, not Lua functions: call them
    assert(M.raw.spend(nil) == M.OK)
    assert(M.raw.reset() == M.OK)

    local none, err = M.Port.new(99)
    assert(none == nil and err == M.ERR_BUSY)

    local p = assert(M.Port.new(3))
    assert(p.pstats.count == 3)
    assert(type(p.pstats.count) == "number")
    assert(p.pstats.bytes == 1099511627776ULL)
    assert(type(p.pstats.bytes) == "cdata")
    assert(p.generation == 7)
    assert(p.pwrap.inner.count == 3)
    assert(p.pwrap.n == 11)

    assert(p:send("abcd") == true)
    assert(M.status_to_string(select(2, p:send("abcd"))) == "nil")
    assert(select(2, p:send("abc")) == M.ERR_BUSY)
    assert(p:recv(5) == "rr\0rr")
    local minted = ffi.new("xy_token[1]")
    assert(M.raw.mint(minted) == M.OK)
    local token = minted[0]
    assert(p:configure({count = 5, bytes = 0}, 6, M.SLOW, token) == true)
    assert(p:configure(ffi.new("xy_stats", {count = 5}), 6, M.SLOW, token) == true)
    -- A bare struct cdata (fields unset) passes the type check; only its count matters to the library.
    assert(pcall(p.configure, p, ffi.new("xy_stats"), 6, M.SLOW, token))
    local no_token = ffi.new("xy_token")

    assert(type_error("must be a string", p.send, p, 42))
    assert(type_error("pdst_count must be a whole number uint32_t holds", p.recv, p, "5"))
    assert(type_error("pdst_count must be a whole number uint32_t holds", p.recv, p, 2 ^ 32))
    assert(type_error("pdst_count must be a whole number uint32_t holds", p.recv, p, -1))
    assert(type_error("pdst_count must be a whole number uint32_t holds", p.recv, p, 1.5))
    assert(type_error("must be a number", M.Port.new, "1"))
    assert(type_error("must be a table or xy_stats", p.configure, p, "x", 6, M.SLOW, no_token))
    assert(type_error("must be a table or xy_stats", p.configure, p, ffi.new("uint32_t[1]"), 6, M.SLOW, no_token))
    assert(type_error("must be a xy_token", p.configure, p, {count = 5, bytes = 0}, 6, M.SLOW, 42))
    assert(type_error("must be a string", p.send, p, nil))

    assert(select("#", p:stats_of()) == 4)
    local out, count, link, rest = p:stats_of()
    assert(out.count == 42)
    assert(count == 43)
    assert(link ~= nil)
    assert(rest == nil)

    assert(select("#", p:bump(4, {count = 5, bytes = 0}, "abc")) == 4)
    local level, tally, data, bump_rest = p:bump(4, {count = 5, bytes = 0}, "abc")
    assert(level == 5)
    assert(tally.count == 10)
    assert(type(tally.bytes) == "cdata")
    assert(data == "bcd")
    assert(bump_rest == nil)

    assert(p:seek(1099511627776ULL) == true)
    assert(p:seek(ffi.new("int64_t", 1099511627776)) == true)
    assert(p:seek(2 ^ 40) == true)
    assert(select(2, p:seek(48ULL)) == M.ERR_BUSY)
    assert(type_error("must be a number or 64-bit cdata", p.seek, p, ffi.new("xy_stats")))

    local next_big, next_delta, tune_rest = p:tune(-3, -1099511627776LL, 200, 0.5)
    assert(next_big == -1099511627777LL)
    assert(type(next_big) == "cdata")
    assert(next_delta == -4)
    assert(type(next_delta) == "number")
    assert(tune_rest == nil)
    assert(p:tune(-3, -2 ^ 40, 200, 0.5))
    assert(select(2, p:tune(-3, -2 ^ 40, 199, 0.5)) == M.ERR_BUSY)
    assert(select(2, p:tune(-3, -2 ^ 40, 200, 0.25)) == M.ERR_BUSY)
    assert(type_error("must be a number", p.tune, p, -3, -2 ^ 40, "200", 0.5))
    assert(type_error("scale must be a number", p.tune, p, -3, -2 ^ 40, 200, "0.5"))
    assert(type_error("must be a number or 64-bit cdata", p.tune, p, -3, "big", 200, 0.5))

    assert(p:annotate(nil) == true)
    assert(p:annotate({count = 7, bytes = 0}) == true)
    assert(select(2, p:annotate({count = 1, bytes = 0})) == M.ERR_BUSY)
    assert(type_error("must be a table or xy_stats or nil", p.annotate, p, 42))

    -- _optional memory in, scalar in and scalar inout: nil passes through as a null pointer
    assert(select("#", p:probe(nil, nil, nil)) == 4)
    local mode, no_level, peek, probe_rest = p:probe(nil, nil, nil)
    assert(mode == M.SLOW and no_level == nil and peek == 9 and probe_rest == nil)
    assert(select(2, p:probe("ab", 3, 4)) == 5)
    assert(select(2, p:probe("abc")) == M.ERR_BUSY)
    assert(select(2, p:probe(nil, 4)) == M.ERR_BUSY)
    assert(type_error("payload must be a string uint32_t can count or nil", p.probe, p, 42))
    assert(type_error("limit must be a number or nil", p.probe, p, nil, "3"))

    -- a boxed scalar: the caller passes and receives its base type's value, never the box
    assert(select("#", p:echo_offset(2 ^ 40)) == 2)
    local moved_to = p:echo_offset(2 ^ 40)
    assert(moved_to == 1099511627776ULL)
    assert(type(moved_to) == "cdata")
    assert(p:echo_offset(48ULL) == 48ULL)
    assert(type_error("pos must be a number or 64-bit cdata", p.echo_offset, p, "48"))

    -- list, by capacity (items, labels): an out array is a 0-based cdata array; a reported
    -- buffer returns its data, what it wrote and what it needs, the bytes written as a string
    assert(select("#", p:list(0, 0)) == 7)
    local items, items_wrote, items_needed, labels, labels_wrote, labels_needed = p:list(0, 0)
    assert(type(items) == "cdata")
    assert(items_wrote == 0 and type(items_wrote) == "cdata" and items_needed == 3)
    assert(labels == "" and labels_wrote == 0 and labels_needed == 6)
    items, items_wrote, items_needed, labels = p:list(1, 2)
    assert(items_wrote == 1 and items[0].id == 10 and labels == "e0" and M.resolve(items[0].label, labels) == "e0")
    items, items_wrote, items_needed, labels = p:list(2, 3)
    assert(items_wrote == 2 and items[1].id == 11 and labels == "e0e")
    assert(M.resolve(items[1].label, labels) == nil)
    items, items_wrote, items_needed, labels = p:list(3, 6)
    for i = 0, 2 do
        assert(M.resolve(items[i].label, labels) == "e" .. i)
    end
    items, items_wrote, items_needed, labels, labels_wrote, labels_needed = p:list(5, 8)
    assert(items_wrote == 3 and items_needed == 3 and labels == "e0e1e2" and labels_wrote == 6 and labels_needed == 6)
    for _, lie in ipairs({{4, 6, "items"}, {6, 6, "items"}, {3, 5, "labels"}}) do
        local ok, err = pcall(p.list, p, lie[1], lie[2])
        assert(not ok and err:find("xy_list over-reported " .. lie[3], 1, true))
    end

    local ok, err, calls, views = stream(p, 1, {})
    assert(ok == true and err == nil and views and streamed(calls, {1, 1, 1, 1, 1, 1, 1, 0}, true))
    ok, err, calls = stream(p, 3, {})
    assert(ok == true and streamed(calls, {3, 3, 1}, true))
    ok, err, calls = stream(p, 0, {})
    assert(ok == true and streamed(calls, {7}, true))
    ok, err, calls = stream(p, 3, {M.AFTER_ONE, M.AFTER_FOUR})
    assert(ok == true and streamed(calls, {2, 3, 2}, true))
    ok, err, calls = stream(p, 0, {M.AFTER_FOUR})
    assert(ok == true and streamed(calls, {5, 2}, true))
    ok, err, calls = stream(p, 1, {}, 3)
    assert(ok == nil and err == M.ERR_AGAIN and streamed(calls, {1, 1, 1}, false))
    ok, err, calls = stream(p, 3, {}, 1)
    assert(ok == nil and err == M.ERR_AGAIN and streamed(calls, {3}, false))
    ok, err, calls, views = stream(p, 3, {})
    assert(views and #calls == 3)
    assert(type_error("cuts must be a table uint32_t can count", p.stream, p, 1, "x", function() end))
    assert(type_error("sink must be a function", p.stream, p, 1, {}, 42))
    -- more than the callbacks LuaJIT holds at once, so a cast not freed would exhaust them
    for _ = 1, 2100 do
        local runs = 0
        local raised, message = pcall(p.stream, p, 1, {}, function()
            runs = runs + 1
            if runs == 2 then
                error("the consumer's sink errors on its second call")
            end
        end)
        assert(not raised and message:find("the consumer's sink errors on its second call", 1, true) and runs == 2)
    end
    ok, err, calls = stream(p, 0, {})
    assert(ok == true and streamed(calls, {7}, true))
    for _ = 1, 300 do
        ok, err, calls = stream(p, 1, {})
        assert(ok == true and #calls == 8)
    end

    local refused, refusal
    ok = p:stream(1, {}, function()
        if refused == nil then
            refused, refusal = pcall(p.seek, p, 2 ^ 40)
        end
    end)
    assert(ok == true and refused == false)
    assert(refusal:find("Port.seek: called while xy_stream is in progress on this Port", 1, true))
    refused = nil
    ok = p:stream(1, {}, function()
        if refused == nil then
            refused, refusal = pcall(p.destroy_port, p)
        end
    end)
    assert(ok == true and refused == false)
    assert(refusal:find("Port.destroy_port: called while xy_stream is in progress on this Port", 1, true))
    assert(p:send("abcd") == true)
    local link = assert(M.DataLink.new())
    refused = nil
    ok = p:stream(1, {}, function()
        if refused == nil then
            refused, refusal = pcall(link.attach, link, p)
        end
    end)
    assert(ok == true and refused == false)
    assert(refusal:find("DataLink.attach: hport is a Port while xy_stream is in progress on it", 1, true))
    assert(link:attach(p) == true)
    assert(type_error("hport must be a M.Port", link.attach, link, p._handle))

    local firsts, seconds = {}, {}
    ok = p:notify(1, function(mode)
        firsts[#firsts + 1] = mode
    end, function(mode)
        seconds[#seconds + 1] = mode
    end)
    assert(ok == true and #firsts == 1 and firsts[1] == M.SLOW and #seconds == 1 and seconds[1] == M.SLOW)
    local first_runs, second_runs = 0, 0
    local raised, message = pcall(p.notify, p, 1, function()
        first_runs = first_runs + 1
        error("the consumer's first callback errors")
    end, function()
        second_runs = second_runs + 1
    end)
    assert(not raised and message:find("the consumer's first callback errors", 1, true))
    assert(first_runs == 1 and second_runs == 0)
    firsts = {}
    assert(p:notify(7, function(mode)
        firsts[#firsts + 1] = mode
    end, function() end) == true)
    assert(#firsts == 1 and firsts[1] == 7)

    -- batch 98 calls the sink eight times whatever it answers
    local runs = 0
    raised, message = pcall(p.stream, p, 98, {}, function()
        runs = runs + 1
        if runs == 2 then
            error("the consumer's sink errors on its second call")
        end
    end)
    assert(not raised and message:find("the consumer's sink errors on its second call", 1, true) and runs == 2)
    assert(p:seek(98) == true)

    runs = 0
    raised, message = pcall(p.stream, p, 0, {}, function()
        runs = runs + 1
        return 0.5
    end)
    assert(not raised and message:find("xy_on_batch", 1, true) and runs == 1)

    local text = {offset = 2, length = 2}
    assert(M.resolve(text, "e0e1", 1) == "e1")
    local bytes = ffi.new("uint8_t[4]", {101, 48, 101, 49})
    assert(M.resolve(text, bytes, 4) == "e1" and M.resolve(text, bytes, 3) == nil)
    local kept
    assert(p:stream(0, {}, function(seen, seen_count, fresh, fresh_count, arena)
        assert(M.resolve(seen[1].label, arena) == "e1" and M.resolve(seen[1].label, arena, 3) == nil)
        kept = arena
    end) == true)
    raised, message = pcall(M.resolve, {offset = 0, length = 2}, kept)
    assert(not raised and message:find("M.resolve: a cdata arena needs its length; a callback's byte view is "
        .. "bounded only while its callback runs", 1, true))

    assert(p:destroy_port() == true)
    local again, again_err = p:destroy_port()
    assert(again == nil and again_err == M.ERR_OTHER)
    assert(pcall(p.send, p, "abcd") == false)
    assert(type_error("DataLink.attach: hport is a Port used after destroy_port", link.attach, link, p))

    local data_link = assert(M.DataLink.new())
    assert(data_link._handle ~= nil)

    for i = 1, 4 do
        assert(M.Port.new(i))
    end
    collectgarbage("collect")
    collectgarbage("collect")
    assert(M.Port.new(1))
end

-- A record's line of stdout's text form, after a test of its kind; the walk refuses any other tag.
local function note_text(record)
    local head = record.head
    if head.kind == M.KIND_LINE then
        return string.format("line %d %d %d %d %d", head.kind, head.size, head.at,
            record.label.offset, record.label.length)
    end
    return string.format("mark %d %d %d %d %d", head.kind, head.size, head.at, record.value, record.flag)
end

-- Each record's {offset, line}, in order, as far as the walk went, and its refusal, nil where none.
local function walk(seq, count, bytes)
    local notes, offset = {}, 0
    local ok, err = pcall(function()
        for record in M.note_records(seq, count, bytes) do
            notes[#notes + 1] = {offset, note_text(record)}
            offset = offset + record.head.size
        end
    end)
    return notes, not ok and err or nil
end

-- The record M.note_at finds at byte `offset`.
local function note_at(seq, count, bytes, offset)
    return M.note_at(seq, count, bytes, offset / M.NOTE_ALIGN)
end

-- The message M.note_at raises at byte `offset`, nil where it does not raise.
local function note_at_refusal(seq, count, bytes, offset)
    local ok, err = pcall(note_at, seq, count, bytes, offset)
    return not ok and err or nil
end

-- One call of stream_notes' function, checks 50 to 53: `kept` holds every record earlier calls
-- delivered, at its offset in seen, and gains fresh's.
local function check_notes(seen, seen_count, seen_bytes, fresh, fresh_count, fresh_bytes, kept)
    local seen_notes, seen_err = walk(seen, seen_count, seen_bytes)
    local fresh_notes, fresh_err = walk(fresh, fresh_count, fresh_bytes)
    assert(seen_err == nil, seen_err)
    assert(fresh_err == nil, fresh_err)
    local before = seen_bytes - fresh_bytes
    assert(before >= 0 and seen_count == #kept + fresh_count)
    assert(fresh_count == 0
        or note_at(fresh, fresh_count, fresh_bytes, 0) == note_at(seen, seen_count, seen_bytes, before))
    for _, note in ipairs(fresh_notes) do
        kept[#kept + 1] = {before + note[1], note[2]}
    end
    assert(#seen_notes == #kept)
    for i, note in ipairs(kept) do
        assert(seen_notes[i][1] == note[1] and seen_notes[i][2] == note[2])
    end
    for _, note in ipairs(kept) do
        assert(note_text(note_at(seen, seen_count, seen_bytes, note[1])) == note[2])
    end
    for _, note in ipairs(fresh_notes) do
        assert(note_text(note_at(fresh, fresh_count, fresh_bytes, note[1])) == note[2])
    end
    assert(note_at_refusal(seen, seen_count, seen_bytes, 4)
        == "xy_note_at: record 1 at offset 4: offset is not a record's start")
    assert(note_at_refusal(seen, seen_count, seen_bytes, seen_bytes) == string.format(
        "xy_note_at: record %d at offset %d: offset is not a record's start", seen_count, seen_bytes))
end

-- The `notes` mode.
local function notes()
    local p = assert(M.Port.new(3))
    for _, run in ipairs({{2, {2, 2, 2}}, {4, {4, 2}}, {0, {6}}}) do
        local batch, calls = run[1], run[2]
        local kept, fresh_counts = {}, {}
        local ok = p:stream_notes(batch, function(seen, seen_count, seen_bytes, fresh, fresh_count, fresh_bytes)
            fresh_counts[#fresh_counts + 1] = fresh_count
            check_notes(seen, seen_count, seen_bytes, fresh, fresh_count, fresh_bytes, kept)
        end)
        assert(ok == true and #fresh_counts == #calls)
        for i, count in ipairs(calls) do
            assert(fresh_counts[i] == count)
        end
        if batch == 2 then
            for _, note in ipairs(kept) do
                print(note[2])
            end
        end
    end
    assert(p:destroy_port() == true)
end

-- The `notes <selector>` mode's exit code.
local function refused_notes(selector)
    selector = selector:match("^%d+$") and tonumber(selector)
    if not selector or selector > 255 then
        return 100
    end
    local p = M.Port.new(3)
    if not p then
        return 100
    end
    local refusals, earlier_count, earlier_bytes = {}, 0, 0
    local ok, result = p:stream_notes(selector, function(seen, seen_count, seen_bytes, fresh, fresh_count, fresh_bytes)
        local _, seen_err = walk(seen, seen_count, seen_bytes)
        local _, fresh_err = walk(fresh, fresh_count, fresh_bytes)
        if seen_err == nil and fresh_err == nil then
            return nil
        end
        for _, view in ipairs({{"seen", seen_err}, {"fresh", fresh_err}}) do
            local index, offset, clause = (view[2] or ""):match("^xy_note_records: record (%d+) at offset (%d+): (.+)$")
            if index then
                io.stderr:write(string.format("xy_on_notes: %s: record %s at offset %s: %s\n",
                    view[1], index, offset, clause))
                refusals[view[1]] = {tonumber(index), tonumber(offset), clause}
            end
        end
        earlier_count, earlier_bytes = seen_count - fresh_count, seen_bytes - fresh_bytes
        return M.HALT
    end)
    local seen, fresh = refusals.seen, refusals.fresh
    if p:destroy_port() ~= true or ok ~= nil or result ~= M.ERR_AGAIN or not seen or not fresh
        or seen[1] ~= earlier_count + fresh[1] or seen[2] ~= earlier_bytes + fresh[2] or seen[3] ~= fresh[3] then
        return 100
    end
    return selector
end

-- The `notes 106` mode's exit code.
local function at_past_count()
    local p = M.Port.new(3)
    if not p then
        return 100
    end
    local refusal
    local ok, result = p:stream_notes(106, function(seen, seen_count, seen_bytes)
        refusal = note_at_refusal(seen, seen_count, seen_bytes, 16)
        if refusal then
            io.stderr:write(refusal, "\n")
        end
        return M.HALT
    end)
    if p:destroy_port() ~= true or ok ~= nil or result ~= M.ERR_AGAIN or not refusal then
        return 100
    end
    return 106
end

if arg[2] == "notes" and arg[3] ~= nil then
    local ran, code = pcall(arg[3] == "106" and at_past_count or refused_notes, arg[3])
    if not ran then
        io.stderr:write(code, "\n")
    end
    os.exit(ran and code or 100)
end

-- A failure leaves Ports with GC finalizers behind; luajit's error exit collects them
-- after unloading the library and crashes before printing the error, so report it here
-- and exit without closing the state.
local ok, message = xpcall(arg[2] == "notes" and notes or checks, debug.traceback)
if not ok then
    io.stderr:write(message, "\n")
    os.exit(1)
end
