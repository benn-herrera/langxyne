// A fake implementation of support.KITCHEN_SINK's API, built as the shared library `xy` for every
// consumer and archived for the static check. C headers only, and no exceptions: archived, it must
// need no C++ runtime at the consumer's link. xy_notify is fake_xy_notify.c's, linked beside it.
// Beside what support.KITCHEN_SINK's docstrings state: xy_attach answers XY_ERR_OTHER for a null
// link or port; xy_mint writes the one token this library issues, XY_ERR_OTHER for a null pointer,
// and xy_configure answers ok only for that token; xy_seek(95) reads the answer to the first call
// of the last batch-95 stream; xy_stream's batch 94 passes the sink a null user_data.
//
// xy_stream_notes writes the six notes as raw bytes, each its member's struct, at a 16-byte
// stride: n0 line at 0 label {0, 2}; n1 mark at 1 value -1 flag 1; n2 line at 2 label {2, 3}; n3
// mark at 3 value 2147483647 flag 0; n4 mark at 4 value -2147483648 flag 4294967295; n5 line at 5
// label {5, 0}. Batches 101 to 105 select a stream of two calls, the first n0 and n1 well formed,
// the second malformed in one of a walk's first five refusals, every one at fresh's record 1, byte
// 16, which is seen's record 3, byte 48, after which the stream ends, OK where the sink answered go:
//   101  n2, then 4 of n3's bytes: a header past the extent    (fresh: count 2, 20 bytes)
//   102  n2, n3 with kind 3: an unknown tag                    (count 2, 32 bytes)
//   103  n2, n3 with size 12: a size that is not the member's  (count 2, 32 bytes)
//   104  n2, then n3's head alone: a record past the extent    (count 2, 24 bytes)
//   105  n2, n3 counted as one: a count the walk does not meet (count 1, 32 bytes)
// Batch 106 selects one call whose views, seen and fresh alike, count n0 alone over n0 and n1's 32
// bytes: n1, well formed, lies past the count at byte 16, after which the stream ends as above.
#define XY_IMPL
#include "xy_api.h"
#undef XY_IMPL

#include <pthread.h>

#include <cstdint>
#include <cstdlib>
#include <cstring>

struct xy_port_opaque {
  uint32_t unit;
  bool open;
};

struct xy_link_opaque {
  int unused;
};

namespace {
xy_port_opaque slots[4];
xy_link_opaque the_link;
// what xy_mint's token points at
int token_slot;

xy_token the_token() {
  return reinterpret_cast<xy_token>(&token_slot);
}
}  // namespace

XY_API xy_status xy_open_port(uint32_t unit, xy_port* pport, xy_stats* pstats, uint32_t* generation, xy_wrap* pwrap) {
  if (unit == 99) {
    return XY_ERR_BUSY;
  }
  for (xy_port_opaque& slot : slots) {
    if (slot.open) {
      continue;
    }
    slot = {unit, true};
    *pport = &slot;
    const xy_stats stats = {unit, 1ULL << 40};
    if (pstats) {
      *pstats = stats;
    }
    *generation = 7;
    pwrap->inner = stats;
    pwrap->n = 11;
    return XY_OK;
  }
  return XY_ERR_BUSY;
}

XY_API xy_status xy_destroy_port(xy_port hport) {
  if (!hport) {
    return XY_ERR_OTHER;
  }
  if (!hport->open) {
    abort();  // released twice: a finalizer firing after an explicit release
  }
  hport->open = false;
  return XY_OK;
}

XY_API xy_status xy_send(xy_port hport, const void* buf, uint64_t buf_count) {
  (void)hport;
  return buf != nullptr && buf_count == 4 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_spend(xy_token htoken) {
  (void)htoken;
  return XY_OK;
}

XY_API xy_status xy_recv(xy_port hport, void* pdst, uint32_t pdst_count) {
  (void)hport;
  memset(pdst, 'r', pdst_count);
  if (pdst_count > 2) {
    static_cast<char*>(pdst)[2] = '\0';
  }
  return XY_OK;
}

XY_API xy_status xy_configure(xy_port hport, const xy_stats* cfg, const uint32_t* limit, xy_mode mode, xy_token who) {
  (void)hport;
  return cfg->count == 5 && *limit == 6 && mode == XY_SLOW && who == the_token() ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_stats_of(xy_port hport, xy_stats* out, uint32_t* pcount, xy_link* plink) {
  (void)hport;
  out->count = 42;
  *pcount = 43;
  *plink = &the_link;
  return XY_OK;
}

XY_API xy_status xy_bump(xy_port hport, uint32_t* level, xy_stats* tally, void* data, uint32_t data_count) {
  (void)hport;
  *level += 1;
  tally->count *= 2;
  for (uint32_t i = 0; i < data_count; ++i) {
    static_cast<uint8_t*>(data)[i] += 1;
  }
  return XY_OK;
}

XY_API xy_status xy_open_link(xy_link* plink) {
  *plink = &the_link;
  return XY_OK;
}

XY_API xy_status xy_attach(xy_link hlink, xy_port hport) {
  return hlink && hport ? XY_OK : XY_ERR_OTHER;
}

XY_API xy_status xy_mint(xy_token* ptoken) {
  if (!ptoken) {
    return XY_ERR_OTHER;
  }
  *ptoken = the_token();
  return XY_OK;
}

XY_API xy_status xy_annotate(xy_port hport, const xy_stats* note) {
  (void)hport;
  return note == nullptr || note->count == 7 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_reset(void) {
  return XY_OK;
}

namespace {
// One xy_stream call, run on the caller's thread or, for batch 99, on a thread of its own.
struct Stream {
  uint32_t batch;
  const xy_cut* cuts;
  uint32_t cuts_count;
  xy_on_batch sink;
  void* user_data;
  xy_status result;
};

// the batch-95 or batch-96 stream running now, whose sink seek(96) calls again
Stream* active;
// the answers other than go the last batch-98 stream received
uint32_t stream_stops;
// the answer the last batch-95 stream's first sink call received
xy_flow first_95_answer = XY_GO;
}  // namespace

XY_API xy_status xy_seek(xy_port hport, uint64_t offset) {
  (void)hport;
  if (offset == 12345) {
    return static_cast<xy_status>(12345);  // a result xy_status does not name, for the Rust binding's panic
  }
  if (offset == 96 && active != nullptr) {
    (void)active->sink(nullptr, 0, nullptr, 0, nullptr, 0, 0, active->user_data);
    return XY_OK;
  }
  if (offset == 98) {
    return stream_stops != 0 ? XY_OK : XY_ERR_AGAIN;
  }
  if (offset == 95) {
    return first_95_answer != XY_GO ? XY_OK : XY_ERR_AGAIN;
  }
  return offset == 1ULL << 40 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_tune(xy_port hport, int32_t delta, int64_t big, uint8_t small, double scale, int64_t* pnext,
                         int32_t* pdelta) {
  (void)hport;
  *pnext = big - 1;
  *pdelta = delta - 1;
  return delta == -3 && big == -(1LL << 40) && small == 200 && scale == 0.5 ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_probe(xy_port hport, xy_mode* pmode, const void* payload, uint32_t payload_count,
                          const uint32_t* limit, uint32_t* level, uint32_t* ppeek) {
  (void)hport;
  *pmode = XY_SLOW;
  if (level) {
    *level += 1;
  }
  if (ppeek) {
    *ppeek = 9;
  }
  const bool payload_ok = payload == nullptr ? payload_count == 0 : payload_count == 2;
  return payload_ok && (limit == nullptr || *limit == 3) ? XY_OK : XY_ERR_BUSY;
}

XY_API xy_status xy_echo_offset(xy_port hport, xy_offset pos, xy_offset* ppos) {
  (void)hport;
  *ppos = pos;
  return XY_OK;
}

XY_API xy_status xy_list(xy_port hport, xy_entry* items, uint64_t items_count, uint64_t* items_wrote,
                         uint64_t* items_needed, void* labels, uint32_t labels_count, uint32_t* labels_wrote,
                         uint32_t* labels_needed) {
  (void)hport;
  static const char arena[] = "e0e1e2";
  const uint32_t entries = 3;
  const uint32_t arena_size = sizeof arena - 1;
  const uint64_t wrote = items_count < entries ? items_count : entries;
  for (uint32_t i = 0; i < wrote; ++i) {
    items[i].id = 10 + i;
    items[i].label = {2 * i, 2};
  }
  *items_wrote = items_count == 4 ? 5 : items_count == 6 ? 4 : wrote;
  *items_needed = items_count == 4 ? 9 : entries;
  const uint32_t bytes = labels_count < arena_size ? labels_count : arena_size;
  if (bytes > 0) {
    memcpy(labels, arena, bytes);
  }
  *labels_wrote = labels_count == 5 ? 7 : bytes;
  *labels_needed = arena_size;
  return XY_OK;
}

namespace {
// Batches 95 to 98 deliver as batch 1 does, each with its own lie.
bool batches_of_one(uint32_t batch) {
  return batch == 1 || (batch >= 95 && batch <= 98);
}

void run_stream(Stream* s) {
  static const char arena[] = "e0e1e2e3e4e5e6";
  const uint32_t entries = 7;
  xy_entry seen[entries];
  for (uint32_t i = 0; i < entries; ++i) {
    seen[i] = {10 + i, {2 * i, 2}};
  }
  // batches 95 and 98 deliver whatever the sink answers, counting the answers other than go
  const bool ignore_answers = s->batch == 95 || s->batch == 98;
  uint32_t stops = 0;
  // calls sink with every entry up to `end`, those new since the last call (NULL where none
  // are, and for batch 97's first call with a count of 1), the arena they cover and `last`;
  // whether the stream goes on
  uint32_t start = 0;
  const auto deliver = [&](uint32_t end, uint32_t last) {
    const xy_entry* fresh = end > start && !(s->batch == 97 && start == 0) ? seen + start : nullptr;
    const xy_flow answer = s->sink(seen, end, fresh, end - start, arena, 2 * end, last, s->user_data);
    if (s->batch == 95 && start == 0) {
      first_95_answer = answer;
    }
    start = end;
    if (ignore_answers) {
      stops += answer != XY_GO;
      return true;
    }
    return answer == XY_GO;
  };
  const uint32_t batch = batches_of_one(s->batch) ? 1 : s->batch;
  for (uint32_t end = 1; end <= entries; ++end) {
    bool cut = batch != 0 && end - start == batch;
    for (uint32_t c = 0; c < s->cuts_count; ++c) {
      cut = cut || s->cuts[c] == end - 1;
    }
    if (cut && !deliver(end, 0)) {
      s->result = XY_ERR_AGAIN;
      return;
    }
  }
  const bool go = deliver(entries, 1);
  if (s->batch == 98) {
    stream_stops = stops;
  }
  s->result = go && stops == 0 ? XY_OK : XY_ERR_AGAIN;
}

void* run_stream_thread(void* s) {
  run_stream(static_cast<Stream*>(s));
  return nullptr;
}
}  // namespace

XY_API xy_status xy_stream(xy_port hport, uint32_t batch, const xy_cut* cuts, uint32_t cuts_count, xy_on_batch sink,
                           void* sink_user_data) {
  (void)hport;
  // batch 94 hands the sink a null user_data, which no driving call made
  Stream s = {batch, cuts, cuts_count, sink, batch == 94 ? nullptr : sink_user_data, XY_OK};
  if (batch == 95 || batch == 96) {
    active = &s;
    run_stream(&s);
    active = nullptr;
    return s.result;
  }
  if (batch != 99) {
    run_stream(&s);
    return s.result;
  }
  pthread_t thread;
  if (pthread_create(&thread, nullptr, run_stream_thread, &s) != 0 || pthread_join(thread, nullptr) != 0) {
    return XY_ERR_OTHER;
  }
  return s.result;
}

namespace {
constexpr uint32_t note_stride = 16;
constexpr uint32_t note_count = 6;

// a head as the library writes it
xy_note_head note_head(uint32_t kind, uint32_t size, uint32_t at) {
  return {uint16_t(kind), uint16_t(size), at};
}

// writes `note`'s bytes as note `i` of `list`
template <class T>
void write_note(unsigned char* list, uint32_t i, const T& note) {
  static_assert(sizeof note == note_stride);
  memcpy(list + i * note_stride, &note, sizeof note);
}
}  // namespace

XY_API xy_status xy_stream_notes(xy_port hport, uint32_t batch, xy_on_notes sink, void* sink_user_data) {
  (void)hport;
  const bool malformed = batch >= 101 && batch <= 105;
  const bool past_count = batch == 106;
  if (batch > note_count && !malformed && !past_count) {
    return XY_ERR_UNSUPPORTED;
  }
  alignas(xy_note_head) unsigned char list[note_count * note_stride];
  const uint32_t line = XY_KIND_LINE;
  const uint32_t mark = XY_KIND_MARK;
  write_note(list, 0, xy_note_line{note_head(line, sizeof(xy_note_line), 0), {0, 2}});
  write_note(list, 1, xy_note_mark{note_head(mark, sizeof(xy_note_mark), 1), -1, 1});
  write_note(list, 2, xy_note_line{note_head(line, sizeof(xy_note_line), 2), {2, 3}});
  const uint32_t n3_kind = batch == 102 ? 3 : mark;
  const uint32_t n3_size = batch == 103 ? 12 : sizeof(xy_note_mark);
  write_note(list, 3, xy_note_mark{note_head(n3_kind, n3_size, 3), INT32_MAX, 0});
  write_note(list, 4, xy_note_mark{note_head(mark, sizeof(xy_note_mark), 4), INT32_MIN, UINT32_MAX});
  write_note(list, 5, xy_note_line{note_head(line, sizeof(xy_note_line), 5), {5, 0}});
  // calls sink with seen every record up to `to` and fresh those from `from`, each a (count, bytes);
  // whether it answered go
  const auto deliver = [&](uint32_t from_count, uint32_t from_bytes, uint32_t to_count, uint32_t to_bytes) {
    const auto* seen = reinterpret_cast<const xy_note_head*>(list);
    const auto* fresh = reinterpret_cast<const xy_note_head*>(list + from_bytes);
    return sink(seen, to_count, to_bytes, fresh, to_count - from_count, to_bytes - from_bytes, sink_user_data) == XY_GO;
  };
  if (malformed) {
    static const uint32_t fresh_counts[] = {2, 2, 2, 2, 1};
    static const uint32_t fresh_bytes[] = {20, 32, 32, 24, 32};
    const uint32_t n = batch - 101;
    if (!deliver(0, 0, 2, 2 * note_stride)) {
      return XY_ERR_AGAIN;
    }
    return deliver(2, 2 * note_stride, 2 + fresh_counts[n], 2 * note_stride + fresh_bytes[n]) ? XY_OK : XY_ERR_AGAIN;
  }
  if (past_count) {
    return deliver(0, 0, 1, 2 * note_stride) ? XY_OK : XY_ERR_AGAIN;
  }
  const uint32_t step = batch == 0 ? note_count : batch;
  for (uint32_t from = 0; from < note_count; from += step) {
    const uint32_t to = from + step < note_count ? from + step : note_count;
    if (!deliver(from, from * note_stride, to, to * note_stride)) {
      return XY_ERR_AGAIN;
    }
  }
  return XY_OK;
}
