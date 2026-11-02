// A consumer of support.KITCHEN_SINK's C++ wrapper, run against either fake's shared library `xy`.
// Exit codes: 0 all steps passed; 1 create(99) failure result; 2 create(3) and its cached
// out parameters; 3 send; 4 recv; 5 configure with the token xy_mint issues; 6 stats_of; 7 move
// construction; 8 move assignment; 9 release; 49 after it, attach of the released port on a DataLink
// answers ERR_BUSY without reaching the library; 10 destructors freed the slots; 11 PRODUCT; 12 DataLink::create; 13 bump; 14 seek and tune;
// 15 annotate (an _optional struct in parameter); 16 the _to_string conversions; 17 probe (an enum out
// parameter as the C typedef, _optional memory in, scalar in, inout and out parameters); 18 echo_offset (a
// boxed scalar by value and out); list, by capacity (items, labels): 21 (0, 0) succeeds reporting nothing
// written and what is needed; 22 (1, 2) entry 0 and its label; 23 (2, 3) entry 1's label leaves the arena
// written, so resolve is nullopt; 24 (3, 6) every label resolves; 25 (5, 8) the prefix written and what is
// needed; 26 (4, 6), where the fake reports 5 written to a 4-element buffer, is forwarded as reported: the
// wrapper checks no report. stream, by (batch, cuts), each call's fresh count in order, the final one last:
// 30 (1, none) 1 seven times then an empty final call, each fresh view seen's tail; 31 (3, none) 3, 3, 1;
// 32 (0, none), a const callable, 7; 33 (3, after_one and after_four from a const array) 2, 3, 2; 34 (0,
// after_four) 5, 2; 35 (1, none) halting on call 3: three calls, none final, ERR_AGAIN; 36 (3, none)
// halting on call 1: one call, none final, ERR_AGAIN; 37 (3, none) every seen label resolves to e<i>
// against the arena view, and a text at the arena's end is nullopt; 38 the raw xy_stream with a C function
// sees its user_data on every call; 40 inside stream(1)'s callable, seek(1 << 40) on the same port answers
// ERR_BUSY without reaching the library, and the stream answers OK; 41 inside it, release() answers ERR_BUSY,
// and send on the port succeeds after the stream; 48 inside it, attach(port) on a DataLink answers ERR_BUSY
// without reaching the library, and OK after the stream; 42 notify(1) calls each callable once with Mode::Slow and
// answers OK; 43 notify(1) whose first callable answers Halt: second still runs once, ERR_AGAIN; 44
// notify(7): first receives a Mode whose value is 7; 45 stream(98), whose library calls the sink eight times
// whatever it answers, halting on call 2: eight calls, ERR_AGAIN, and seek(98) then answers OK, the library
// having seen a stop; 46 (0, none) a plain function by name, then by address: OK with one call each; 47 (0,
// an empty std::vector's data() and size(), null with a count of 0 under libc++) 7, OK.
// stream_notes, the notes the fakes' headers list, for batch 2, 4 and 0, each view walked through
// NoteSequence and each record printed through as<T>: 50 the stream answers Ok after calls of 2, 2, 2
// notes (of 4, 2; of 6), every view walked to its count with no refusal (the refusal on stderr); 51
// at each call fresh ends where seen ends, seen counts the earlier calls' records and fresh's, and
// seen's records are every earlier call's fresh records then this call's; 52 at each call every
// offset recorded so far resolves through seen.at to its record, and each of fresh's through
// fresh.at, each offset in units of the list's alignment; 53 seen.at of byte 4, inside n0, is refused as "record 1 at offset 4: offset is not a record's
// start", and seen.at of its extent as the record after the last; 54 each record is exactly one
// member through as<T>, at the record's own address, as<NoteLine> of a mark null.
// Its stdout is the batch-2 stream's records, one line each, in order, fields in definition order
// and integers in decimal: `line <head.kind> <head.size> <head.at> <label.offset> <label.length>`
// or `mark <head.kind> <head.size> <head.at> <value> <flag>`, as `mark 2 16 1 -1 1`.
// `consumer notes <selector>`, checks 101 to 105, against fake_xy.cpp alone: the stream whose
// second call fake_xy.cpp's header describes for that selector is refused by the walk of both its
// views, each refusal on stderr as `xy_on_notes: <view>: record <i> at offset <o>: <clause>`, the
// callable answering Halt, and the process exits with the selector; 100 where no view was refused,
// the stream did not answer ErrAgain, or seen's refusal is not fresh's past the earlier records.
// `consumer notes 106`, against fake_xy.cpp alone: seen.at of byte 16, the record past seen's
// count, is refused, on stderr as `xy_on_notes: seen: <refusal>`, the callable answering Halt, and
// the process exits 106; 100 where at did not refuse or the stream did not answer ErrAgain.
#include "xy_api.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <optional>
#include <initializer_list>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

static_assert(!std::is_copy_constructible_v<xy::Port>);
static_assert(!std::is_copy_assignable_v<xy::Port>);
static_assert(std::is_nothrow_move_constructible_v<xy::Port>);
static_assert(std::is_nothrow_move_assignable_v<xy::Port>);
static_assert(std::is_same_v<xy::Stats, xy_stats>);
static_assert(std::is_same_v<xy::Wrap, xy_wrap>);
static_assert(std::is_same_v<xy::Offset, xy_offset>);
static_assert(!std::is_convertible_v<uint64_t, xy::Offset>);
static_assert(std::is_same_v<std::underlying_type_t<xy::Status>, int32_t>);
static_assert(std::is_same_v<std::underlying_type_t<xy::Mode>, uint32_t>);
static_assert(std::is_same_v<decltype(xy::API_VERSION), const uint32_t>);
static_assert(std::is_same_v<decltype(xy::FEAT_A), const int32_t>);
static_assert(std::is_same_v<decltype(xy::FEAT_ALL), const uint32_t>);
static_assert(std::is_same_v<decltype(xy::NEG), const int32_t>);
static_assert(std::is_same_v<decltype(xy::MAGIC), const uint32_t>);
static_assert(int32_t(xy::Status::ErrBusy) == XY_ERR_BUSY);
static_assert(int32_t(xy::Mode::Slow) == XY_SLOW);
static_assert(xy::FEAT_ALL == XY_FEAT_ALL);
static_assert(xy::API_VERSION == XY_API_VERSION);
static_assert(int32_t(xy::NEG) == XY_NEG);
static_assert(std::is_same_v<decltype(xy::FLOOR), const int32_t>);
static_assert(xy::FLOOR == INT32_MIN);
static_assert(int32_t(xy::Status::ErrFloor) == INT32_MIN);

static int sentinel;
static int sentinel_calls;

// a plain C function as xy_on_batch: counts the calls that arrive with &sentinel as their user_data
extern "C" xy_flow sentinel_sink(const xy_entry*, uint64_t, const xy_entry*, uint64_t, const void*, uint32_t, uint32_t,
                                 void* user_data) {
  sentinel_calls += user_data == &sentinel ? 1 : 100;
  return XY_GO;
}

static int counted_calls;

// a plain function as stream's sink, counting its calls
static xy::Flow counting_sink(const xy::Entry*, uint64_t, const xy::Entry*, uint64_t, const void*, uint32_t, uint32_t) {
  ++counted_calls;
  return xy::Flow::Go;
}

// What stream's sink saw: each call's seen and fresh counts and final flag, and whether every
// view held what the fakes promise.
struct Streamed {
  xy::Status result;
  int calls;
  uint64_t seen[16];
  uint64_t fresh[16];
  uint32_t last[16];
  bool views;

  // whether the calls' fresh counts are `fresh`, seen counting them up, the last one alone final
  // where `final`
  bool is(std::initializer_list<uint64_t> fresh_counts, bool final) const {
    if (calls != int(fresh_counts.size())) {
      return false;
    }
    uint64_t total = 0;
    int i = 0;
    for (const uint64_t count : fresh_counts) {
      total += count;
      if (fresh[i] != count || seen[i] != total || last[i] != uint32_t(final && i == calls - 1)) {
        return false;
      }
      ++i;
    }
    return true;
  }
};

// A record's line of stdout's text form, through as<T>; empty for a record neither member is.
static std::string note_text(const xy::NoteHead& record) {
  const auto fields = [](const char* member, const xy::NoteHead& head, int64_t first, int64_t second) {
    return std::string(member) + ' ' + std::to_string(head.kind) + ' ' + std::to_string(head.size) + ' ' +
           std::to_string(head.at) + ' ' + std::to_string(first) + ' ' + std::to_string(second);
  };
  if (const xy::NoteLine* line = xy::as<xy::NoteLine>(record)) {
    return fields("line", line->head, line->label.offset, line->label.length);
  }
  if (const xy::NoteMark* mark = xy::as<xy::NoteMark>(record)) {
    return fields("mark", mark->head, mark->value, mark->flag);
  }
  return {};
}

// A refusal in the binding's words: `record <i> at offset <o>: <clause>`.
static std::string refusal(const xy::UnionError& error) {
  return "record " + std::to_string(error.index) + " at offset " + std::to_string(error.offset) + ": " +
         xy::union_clause_text(error.clause);
}

// Each record's byte offset and line, in order, as far as the walk went, and its refusal if any.
struct Walked {
  std::vector<std::pair<uint32_t, std::string>> notes;
  std::optional<xy::UnionError> error;
};

static Walked walk(const xy::NoteSequence& sequence) {
  Walked walked;
  uint32_t offset = 0;
  for (const xy::NoteHead& record : sequence) {
    walked.notes.emplace_back(offset, note_text(record));
    offset += record.size;
  }
  walked.error = sequence.error();
  return walked;
}

// One call of stream_notes' callable, checks 50 to 54: `kept` holds every record earlier calls
// delivered, at its offset in seen, and gains fresh's; 0 or the failing check.
static int check_notes(const xy::NoteSequence& seen, const xy::NoteSequence& fresh,
                       std::vector<std::pair<uint32_t, std::string>>& kept) {
  const Walked seen_walk = walk(seen);
  const Walked fresh_walk = walk(fresh);
  for (const auto& [view, walked] : {std::pair{"seen", &seen_walk}, std::pair{"fresh", &fresh_walk}}) {
    if (walked->error) {
      std::fprintf(stderr, "xy_on_notes: %s: %s\n", view, refusal(*walked->error).c_str());
      return 50;
    }
  }
  const char* seen_end = reinterpret_cast<const char*>(seen.data()) + seen.bytes();
  if (fresh.bytes() > seen.bytes() || reinterpret_cast<const char*>(fresh.data()) + fresh.bytes() != seen_end ||
      seen.count() != kept.size() + fresh.count()) {
    return 51;
  }
  const uint32_t before = seen.bytes() - fresh.bytes();
  for (const auto& [offset, text] : fresh_walk.notes) {
    kept.emplace_back(before + offset, text);
  }
  if (seen_walk.notes != kept) {
    return 51;
  }
  const auto resolves = [](const xy::NoteSequence& sequence, const std::pair<uint32_t, std::string>& note) {
    const xy::NoteHead* record = sequence.at(uint32_t(note.first / xy::NoteSequence::align));
    return record != nullptr && note_text(*record) == note.second;
  };
  for (const auto& note : kept) {
    if (!resolves(seen, note)) {
      return 52;
    }
  }
  for (const auto& note : fresh_walk.notes) {
    if (!resolves(fresh, note)) {
      return 52;
    }
  }
  const auto refused = [&seen](uint32_t offset) {
    return seen.at(uint32_t(offset / xy::NoteSequence::align)) == nullptr && seen.error() ? refusal(*seen.error()) : std::string();
  };
  if (refused(4) != "record 1 at offset 4: offset is not a record's start" ||
      refused(seen.bytes()) != "record " + std::to_string(seen.count()) + " at offset " +
                                   std::to_string(seen.bytes()) + ": offset is not a record's start") {
    return 53;
  }
  for (const xy::NoteHead& record : seen) {
    const xy::NoteLine* line = xy::as<xy::NoteLine>(record);
    const xy::NoteMark* mark = xy::as<xy::NoteMark>(record);
    const void* as_member = line != nullptr ? static_cast<const void*>(line) : mark;
    if ((line == nullptr) == (mark == nullptr) || as_member != &record ||
        (record.kind == xy::KIND_MARK && line != nullptr)) {
      return 54;
    }
  }
  return 0;
}

// Checks 101 to 105: `consumer notes <selector>`.
static int refused_notes(uint32_t selector) {
  xy::Port port = xy::Port::create(3);
  if (!port) {
    return 100;
  }
  std::optional<xy::UnionError> seen_error;
  std::optional<xy::UnionError> fresh_error;
  uint32_t earlier_count = 0;
  uint32_t earlier_bytes = 0;
  const xy::Status status = port.stream_notes(selector, [&](xy::NoteSequence seen, xy::NoteSequence fresh) {
    seen_error = walk(seen).error;
    fresh_error = walk(fresh).error;
    if (!seen_error && !fresh_error) {
      return xy::Flow::Go;
    }
    for (const auto& [view, error] : {std::pair{"seen", &seen_error}, std::pair{"fresh", &fresh_error}}) {
      if (*error) {
        std::fprintf(stderr, "xy_on_notes: %s: %s\n", view, refusal(**error).c_str());
      }
    }
    earlier_count = seen.count() - fresh.count();
    earlier_bytes = seen.bytes() - fresh.bytes();
    return xy::Flow::Halt;
  });
  if (status != xy::Status::ErrAgain || !seen_error || !fresh_error ||
      seen_error->index != earlier_count + fresh_error->index ||
      seen_error->offset != earlier_bytes + fresh_error->offset || seen_error->clause != fresh_error->clause) {
    return 100;
  }
  return int(selector);
}

// Check 106: `consumer notes 106`.
static int at_past_count() {
  xy::Port port = xy::Port::create(3);
  if (!port) {
    return 100;
  }
  bool refused = false;
  const xy::Status status = port.stream_notes(106, [&](xy::NoteSequence seen, xy::NoteSequence) {
    if (seen.at(uint32_t(16 / xy::NoteSequence::align)) == nullptr && seen.error()) {
      std::fprintf(stderr, "xy_on_notes: seen: %s\n", refusal(*seen.error()).c_str());
      refused = true;
    }
    return xy::Flow::Halt;
  });
  return status == xy::Status::ErrAgain && refused ? 106 : 100;
}

int main(int argc, char** argv) {
  if (argc == 3 && std::strcmp(argv[1], "notes") == 0 && std::strcmp(argv[2], "106") == 0) {
    return at_past_count();
  }
  if (argc == 3 && std::strcmp(argv[1], "notes") == 0) {
    return refused_notes(uint32_t(std::strtoul(argv[2], nullptr, 10)));
  }
  xy::Status r = xy::Status::Ok;
  if (xy::Port::create(99, &r) || r != xy::Status::ErrBusy || std::strcmp(xy::to_string(r), "ERR_BUSY") != 0) {
    return 1;
  }

  xy::Port port = xy::Port::create(3);
  if (!port || port.pstats().count != 3 || port.generation() != 7 || port.pwrap().n != 11) {
    return 2;
  }

  const char buf[4] = {'a', 'b', 'c', 'd'};
  if (port.send(buf, 4) != xy::Status::Ok || port.send(buf, 3) != xy::Status::ErrBusy) {
    return 3;
  }

  char out[5] = {};
  if (port.recv(out, 5) != xy::Status::Ok || out[2] != 0) {
    return 4;
  }

  xy::Stats cfg{};
  cfg.count = 5;
  const uint32_t limit = 6;
  xy_token token = nullptr;
  if (xy_mint(&token) != XY_OK || port.configure(cfg, limit, xy::Mode::Slow, token) != xy::Status::Ok) {
    return 5;
  }

  xy::Stats st{};
  uint32_t c = 0;
  xy_link l = nullptr;
  if (port.stats_of(st, c, l) != xy::Status::Ok || st.count != 42 || c != 43 || l == nullptr) {
    return 6;
  }

  uint32_t level = 4;
  xy::Stats tally{};
  tally.count = 5;
  char data[3] = {'a', 'b', 'c'};
  if (port.bump(level, tally, data, 3) != xy::Status::Ok || level != 5 || tally.count != 10 ||
      std::memcmp(data, "bcd", 3) != 0) {
    return 13;
  }

  int64_t next = 0;
  int32_t delta = 0;
  if (port.seek(1ULL << 40) != xy::Status::Ok || port.tune(-3, -(1LL << 40), 200, 0.5, next, delta) != xy::Status::Ok ||
      next != -(1LL << 40) - 1 || delta != -4) {
    return 14;
  }

  xy::Stats note{};
  note.count = 7;
  if (port.annotate(&note) != xy::Status::Ok || port.annotate() != xy::Status::Ok) {
    return 15;
  }

  xy_mode mode = XY_FINE;
  uint32_t probe_limit = 3;
  uint32_t probe_level = 4;
  uint32_t peek = 0;
  if (port.probe(mode, nullptr, 0) != xy::Status::Ok || mode != XY_SLOW ||
      port.probe(mode, "ab", 2, &probe_limit, &probe_level, &peek) != xy::Status::Ok || probe_level != 5 ||
      peek != 9 || port.probe(mode, "abc", 3) != xy::Status::ErrBusy) {
    return 17;
  }

  xy::Offset moved_to{};
  if (port.echo_offset(xy::Offset{1ULL << 40}, moved_to) != xy::Status::Ok || moved_to.value != 1ULL << 40) {
    return 18;
  }

  xy::Entry items[8] = {};
  char labels[8] = {};
  uint64_t items_wrote = 99;
  uint64_t items_needed = 0;
  uint32_t labels_wrote = 99;
  uint32_t labels_needed = 0;
  const auto list = [&](uint64_t item_capacity, uint32_t label_capacity) {
    return port.list(items, item_capacity, items_wrote, items_needed, labels, label_capacity, labels_wrote,
                     labels_needed);
  };
  const auto label = [&](int i) { return xy::resolve(items[i].label, std::string_view(labels, labels_wrote)); };
  if (list(0, 0) != xy::Status::Ok || items_wrote != 0 || labels_wrote != 0 || items_needed != 3 ||
      labels_needed != 6) {
    return 21;
  }
  if (list(1, 2) != xy::Status::Ok || items_wrote != 1 || items[0].id != 10 || label(0) != "e0") {
    return 22;
  }
  if (list(2, 3) != xy::Status::Ok || items_wrote != 2 || items[1].id != 11 || label(1).has_value()) {
    return 23;
  }
  if (list(3, 6) != xy::Status::Ok || label(0) != "e0" || label(1) != "e1" || label(2) != "e2") {
    return 24;
  }
  if (list(5, 8) != xy::Status::Ok || items_wrote != 3 || labels_wrote != 6 || items_needed != 3 ||
      labels_needed != 6) {
    return 25;
  }
  if (list(4, 6) != xy::Status::Ok || items_wrote != 5 || items_needed != 9) {
    return 26;
  }

  const xy_cut both_cuts[2] = {XY_AFTER_ONE, XY_AFTER_FOUR};
  const xy_cut fourth_cut[1] = {XY_AFTER_FOUR};
  Streamed streamed{};
  const auto sink = [&streamed](int halt_on) {
    return [&streamed, halt_on](const xy::Entry* all, uint64_t all_count, const xy::Entry* added, uint64_t added_count,
                                const void* bytes, uint32_t bytes_count, uint32_t final_call) {
      const int call = streamed.calls++;
      if (call < 16) {
        streamed.seen[call] = all_count;
        streamed.fresh[call] = added_count;
        streamed.last[call] = final_call;
      }
      const std::string_view text(static_cast<const char*>(bytes), bytes_count);
      for (uint64_t i = 0; i < added_count; ++i) {
        streamed.views = streamed.views && added[i].id == all[all_count - added_count + i].id;
      }
      for (uint64_t i = 0; i < all_count; ++i) {
        const char want[2] = {'e', char('0' + i)};
        streamed.views = streamed.views && xy::resolve(all[i].label, text) == std::string_view(want, 2);
      }
      streamed.views = streamed.views && !xy::resolve(xy::Text{bytes_count, 2}, text).has_value();
      return streamed.calls == halt_on ? xy::Flow::Halt : xy::Flow::Go;
    };
  };
  const auto stream = [&](uint32_t batch, const xy_cut* cuts, uint32_t cuts_count, int halt_on) {
    streamed = Streamed{};
    streamed.views = true;
    streamed.result = port.stream(batch, cuts, cuts_count, sink(halt_on));
    return streamed;
  };
  if (!stream(1, nullptr, 0, 0).is({1, 1, 1, 1, 1, 1, 1, 0}, true) || streamed.result != xy::Status::Ok ||
      !streamed.views) {
    return 30;
  }
  if (!stream(3, nullptr, 0, 0).is({3, 3, 1}, true) || streamed.result != xy::Status::Ok) {
    return 31;
  }
  const auto const_sink = sink(0);
  streamed = Streamed{};
  if (port.stream(0, nullptr, 0, const_sink) != xy::Status::Ok || !streamed.is({7}, true)) {
    return 32;
  }
  if (!stream(3, both_cuts, 2, 0).is({2, 3, 2}, true) || streamed.result != xy::Status::Ok) {
    return 33;
  }
  if (!stream(0, fourth_cut, 1, 0).is({5, 2}, true) || streamed.result != xy::Status::Ok) {
    return 34;
  }
  if (!stream(1, nullptr, 0, 3).is({1, 1, 1}, false) || streamed.result != xy::Status::ErrAgain) {
    return 35;
  }
  if (!stream(3, nullptr, 0, 1).is({3}, false) || streamed.result != xy::Status::ErrAgain) {
    return 36;
  }
  if (!stream(3, nullptr, 0, 0).views || streamed.calls != 3) {
    return 37;
  }
  if (xy_stream(port.handle(), 1, nullptr, 0, sentinel_sink, &sentinel) != XY_OK || sentinel_calls != 8) {
    return 38;
  }
  xy::Status refused = xy::Status::Ok;
  if (port.stream(1, nullptr, 0,
                  [&](auto...) {
                    refused = port.seek(1ULL << 40);
                    return xy::Flow::Go;
                  }) != xy::Status::Ok ||
      refused != xy::Status::ErrBusy) {
    return 40;
  }
  if (port.stream(1, nullptr, 0,
                  [&](auto...) {
                    refused = port.release();
                    return xy::Flow::Go;
                  }) != xy::Status::Ok ||
      refused != xy::Status::ErrBusy || port.send(buf, 4) != xy::Status::Ok) {
    return 41;
  }
  xy::DataLink link = xy::DataLink::create();
  refused = xy::Status::Ok;
  if (!link ||
      port.stream(1, nullptr, 0,
                  [&](auto...) {
                    if (refused == xy::Status::Ok) {
                      refused = link.attach(port);
                    }
                    return xy::Flow::Go;
                  }) != xy::Status::Ok ||
      refused != xy::Status::ErrBusy || link.attach(port) != xy::Status::Ok) {
    return 48;
  }
  std::vector<xy::Mode> firsts;
  std::vector<xy::Mode> seconds;
  const auto notify = [&](uint32_t sent) {
    firsts.clear();
    seconds.clear();
    return port.notify(
        sent,
        [&](xy::Mode m) {
          firsts.push_back(m);
          return xy::Flow::Go;
        },
        [&](xy::Mode m) {
          seconds.push_back(m);
          return xy::Flow::Go;
        });
  };
  if (notify(1) != xy::Status::Ok || firsts != std::vector{xy::Mode::Slow} || seconds != std::vector{xy::Mode::Slow}) {
    return 42;
  }
  int first_runs = 0;
  int second_runs = 0;
  if (port.notify(
          1,
          [&](xy::Mode) {
            ++first_runs;
            return xy::Flow::Halt;
          },
          [&](xy::Mode) {
            ++second_runs;
            return xy::Flow::Go;
          }) != xy::Status::ErrAgain ||
      first_runs != 1 || second_runs != 1) {
    return 43;
  }
  if (notify(7) != xy::Status::Ok || firsts.size() != 1 || uint32_t(firsts[0]) != 7) {
    return 44;
  }
  if (stream(98, nullptr, 0, 2).calls != 8 || streamed.result != xy::Status::ErrAgain ||
      port.seek(98) != xy::Status::Ok) {
    return 45;
  }
  if (port.stream(0, nullptr, 0, counting_sink) != xy::Status::Ok || counted_calls != 1 ||
      port.stream(0, nullptr, 0, &counting_sink) != xy::Status::Ok || counted_calls != 2) {
    return 46;
  }
  const std::vector<xy_cut> no_cuts;
  if (!stream(0, no_cuts.data(), uint32_t(no_cuts.size()), 0).is({7}, true) || streamed.result != xy::Status::Ok) {
    return 47;
  }
  struct NoteStream {
    uint32_t batch;
    std::vector<uint32_t> calls;
  };
  for (const NoteStream& note_stream : {NoteStream{2, {2, 2, 2}}, NoteStream{4, {4, 2}}, NoteStream{0, {6}}}) {
    std::vector<std::pair<uint32_t, std::string>> kept;
    std::vector<uint32_t> fresh_counts;
    int failed = 0;
    const xy::Status result = port.stream_notes(note_stream.batch, [&](xy::NoteSequence seen, xy::NoteSequence fresh) {
      fresh_counts.push_back(fresh.count());
      if (failed == 0) {
        failed = check_notes(seen, fresh, kept);
      }
      return xy::Flow::Go;
    });
    if (failed != 0) {
      return failed;
    }
    if (result != xy::Status::Ok || fresh_counts != note_stream.calls) {
      return 50;
    }
    if (note_stream.batch == 2) {
      for (const auto& [offset, text] : kept) {
        std::printf("%s\n", text.c_str());
      }
    }
  }

  xy::Port moved = std::move(port);
  if (port || !moved) {
    return 7;
  }

  xy::Port other = xy::Port::create(4);
  other = std::move(moved);
  if (moved || !other || other.generation() != 7) {
    return 8;
  }

  if (other.release() != xy::Status::Ok || other || other.release() != xy::Status::ErrOther) {
    return 9;
  }
  if (link.attach(other) != xy::Status::ErrBusy) {
    return 49;
  }

  {
    xy::Port a = xy::Port::create(1);
    xy::Port b = xy::Port::create(2);
    xy::Port d = xy::Port::create(3);
    xy::Port e = xy::Port::create(4);
    if (!a || !b || !d || !e) {
      return 10;
    }
  }
  if (!xy::Port::create(1)) {
    return 10;
  }

  if (std::strcmp(xy::PRODUCT, "xy widget") != 0) {
    return 11;
  }

  if (!xy::DataLink::create()) {
    return 12;
  }

  if (std::strcmp(xy::to_string(xy::Mode::Slow), "SLOW") != 0 ||
      std::strcmp(xy::to_string(xy::Status(12345)), "UNKNOWN_STATUS") != 0 || xy::access_to_string(3) != "ACC_A|ACC_B" ||
      xy::access_to_string(1) != "ACC_A" || xy::access_to_string(0) != "NONE" || xy::access_to_string(9) != "ACC_A|0x8" ||
      xy::access_to_string(-1) != "ACC_A|ACC_B|0xfffffffc" || xy::limit_to_string(16) != "MAX_UNITS" ||
      xy::limit_to_string(xy::NEG) != "NEG" || xy::limit_to_string(xy::FLOOR) != "FLOOR" ||
      xy::limit_to_string(99) != "UNKNOWN") {
    return 16;
  }
  return 0;
}
