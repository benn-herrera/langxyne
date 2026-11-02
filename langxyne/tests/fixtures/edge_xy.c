// A bare C caller of support.KITCHEN_SINK's library, run against fake_xy.rs's shared library `xy`: what the
// Rust relay hands the implementation for what no binding sends. fake_xy.rs names the entry it
// answers each case with.
// Exit codes: 0 every case answered as expected; 1 null for a non-optional out answers ERR_FLOOR;
// 2 that call claimed no slot: four ports still open; 3 null for a non-optional in struct answers
// ERR_FLOOR; 4 a count above isize::MAX answers ERR_UNSUPPORTED; 5 an out buffer reaches the
// implementation zeroed, whatever the caller's memory held; 6 a non-null buffer with a count of 0
// arrives present and empty, so ERR_BUSY; 7 aliased pointers are copied in before the call and
// written back after it in parameter order; 8 an enum value no entry names answers ERR_AGAIN;
// 9 null for probe's pmode is still ok; 10 outs are written back after a failing call; 11 an out
// starts from its default, not the caller's value; 12 a null in buffer with a nonzero count
// answers ERR_UNSUPPORTED; 13 null for a non-optional inout answers ERR_FLOOR; 14 a null out
// buffer with a nonzero count answers ERR_UNSUPPORTED; 15 so does a null inout buffer; 16 so does a
// null out array with a nonzero count; 17 and a misaligned one; 18 and one whose count is below
// isize::MAX but whose bytes are above it; 19 an out array reaches the implementation zeroed, whatever
// the caller's memory held, and comes back written; 20 null for a report answers ERR_FLOOR; 21 a null
// out array with a count of 0 answers ERR_UNSUPPORTED; 22 so does one whose bytes overflow the
// element-size multiplication; 23 stream with a null sink answers ERR_FLOOR; 24 a null in array
// with a nonzero count answers ERR_UNSUPPORTED; 25 so does a misaligned one; 26 a C sink halting on
// its first call is called once, with the user_data passed beside it, and stream answers ERR_AGAIN;
// 27 a null in array with a count of 0 arrives present and empty, so that sink is called once more
// and stream answers ERR_AGAIN; 28 a null in buffer with a count of 0 arrives present and empty, so
// send answers ERR_BUSY, as case 6's empty non-null buffer does; 29 recv on a null port answers
// ERR_OTHER and leaves its buffer as the caller's memory held it, since the relay writes no out buffer
// before the implementation takes it; 30 the header's _to_string conversions answer as every
// binding's: an enum's and a plain group's names, and a bit group's text, cut to the caller's buffer
// with its whole length returned.
// send's count and list's items count are u64: recv's and bump's are u32, which cannot exceed
// isize::MAX on a 64-bit target, so cases 4, 18 and 22 are the only counts or sizes above it.
// With the argument `panic`, calls xy_seek(NULL, UINT64_MAX), whose implementation panics: the
// process aborts, so returning at all exits 99.
// With the argument `notes`, against either fake: xy_stream_notes for batch 2, 4 and 0, each view
// walked by xy_note_first and xy_note_next, each record printed after a switch on its kind and the
// cast to its member's struct. Exit codes: 50 a stream did not answer XY_OK after calls of 2, 2, 2
// notes (of 4, 2; of 6), or a view's walk did not reach its count at its extent, or
// xy_note_well_formed refused it (the refusal on stderr); 51 at each call fresh's records are seen's
// last by identity, and seen's records are every earlier call's fresh records then this call's;
// 52 every offset recorded so far resolves by a walk of seen to its record, and each of fresh's by a
// walk of fresh; 53 the walk of seen to offset 4, inside n0, and to its extent passes the offset
// without landing on it: record 1 at offset 4, and the record after the last at the extent, are
// the sixth clause by xy_union_clause_text. Its stdout is the batch-2 stream's records, one line
// each, as consumer_xy.cpp writes them.
// With `notes <selector>`, 101 to 105, against fake_xy.cpp alone: the stream's second call is
// refused in both views, each refusal on stderr as `xy_on_notes: <view>: record <i> at offset <o>:
// <clause>`, the sink answering XY_HALT, and the process exits with the selector; 100 where a
// selector is not a decimal number below 256, no view was refused, the stream did not answer
// XY_ERR_AGAIN, or seen's refusal is not fresh's past the earlier records.
#include "xy_api.h"

#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static int sentinel;
static int sentinel_calls;

// counts the calls that arrive with &sentinel as their user_data, and halts
static xy_flow halting_sink(const xy_entry* seen, uint64_t seen_count, const xy_entry* fresh, uint64_t fresh_count,
                            const void* arena, uint32_t arena_count, uint32_t last, void* user_data) {
  (void)seen;
  (void)seen_count;
  (void)fresh;
  (void)fresh_count;
  (void)arena;
  (void)arena_count;
  (void)last;
  sentinel_calls += user_data == &sentinel ? 1 : 100;
  return XY_HALT;
}

// xy_access_to_string's text of `value` is `want`, whole in a buffer of 32 and cut to its first 5
// bytes in one of 6, its whole length returned each time and with no buffer at all
static bool access_text_is(int32_t value, const char* want) {
  char whole[32];
  char cut[6];
  uint32_t length = (uint32_t)strlen(want);
  return xy_access_to_string(value, whole, sizeof whole) == length && strcmp(whole, want) == 0 &&
         xy_access_to_string(value, cut, sizeof cut) == length && strncmp(cut, want, 5) == 0 &&
         cut[length < 5 ? length : 5] == '\0' && xy_access_to_string(value, NULL, 0) == length;
}

// the answers every binding's checks pin for the same values (check_xy.py, consumer_xy.cpp)
static bool conversions_answer(void) {
  return strcmp(xy_status_to_string(XY_ERR_BUSY), "ERR_BUSY") == 0 &&
         strcmp(xy_status_to_string((xy_status)12345), "UNKNOWN_STATUS") == 0 &&
         strcmp(xy_mode_to_string(XY_SLOW), "SLOW") == 0 && strcmp(xy_limit_to_string(16), "MAX_UNITS") == 0 &&
         strcmp(xy_limit_to_string(XY_NEG), "NEG") == 0 && strcmp(xy_limit_to_string(XY_FLOOR), "FLOOR") == 0 &&
         strcmp(xy_limit_to_string(99), "UNKNOWN") == 0 && access_text_is(3, "ACC_A|ACC_B") &&
         access_text_is(1, "ACC_A") && access_text_is(0, "NONE") && access_text_is(9, "ACC_A|0x8") &&
         access_text_is(-1, "ACC_A|ACC_B|0xfffffffc");
}

static int cases(void) {
  xy_port ports[4];
  xy_stats stats;
  uint32_t generation;
  xy_wrap wrap;

  if (xy_open_port(3, NULL, NULL, NULL, NULL) != XY_ERR_FLOOR) {
    return 1;
  }
  for (int i = 0; i < 4; ++i) {
    if (xy_open_port(3, &ports[i], &stats, &generation, &wrap) != XY_OK || generation != 7 || wrap.n != 11) {
      return 2;
    }
  }
  for (int i = 1; i < 4; ++i) {
    if (xy_destroy_port(ports[i]) != XY_OK) {
      return 2;
    }
  }
  xy_port port = ports[0];

  const uint32_t limit = 6;
  if (xy_configure(port, NULL, &limit, XY_SLOW, NULL) != XY_ERR_FLOOR) {
    return 3;
  }

  const char four[4] = {'a', 'b', 'c', 'd'};
  if (xy_send(port, four, (uint64_t)1 << 63) != XY_ERR_UNSUPPORTED) {
    return 4;
  }

  // fake_xy.rs answers ERR_OTHER to a buffer that arrives holding anything but zeros
  char dirty[8];
  memset(dirty, 0xaa, sizeof dirty);
  if (xy_recv(port, dirty, sizeof dirty) != XY_OK) {
    return 5;
  }
  char buf[8];
  if (xy_recv(port, buf, sizeof buf) != XY_OK || memcmp(buf, "rr\0rrrrr", sizeof buf) != 0) {
    return 5;
  }

  if (xy_send(port, four, 0) != XY_ERR_BUSY) {
    return 6;
  }

  // level aliases tally.count: each copy is bumped on its own, then level (5 + 1) is written back
  // before tally (count 5 * 2), so the count ends 10. Under C++'s in-place writes it would be 12.
  xy_stats tally = {.count = 5, .bytes = 0};
  char data[3] = {'a', 'b', 'c'};
  if (xy_bump(port, &tally.count, &tally, data, sizeof data) != XY_OK || tally.count != 10 ||
      memcmp(data, "bcd", sizeof data) != 0) {
    return 7;
  }
  // limit aliases level: limit is read before the call, so it is still 3 when checked.
  uint32_t shared = 3;
  xy_mode mode = XY_FINE;
  if (xy_probe(port, &mode, NULL, 0, &shared, &shared, NULL) != XY_OK || shared != 4 || mode != XY_SLOW) {
    return 7;
  }

  const xy_stats cfg = {.count = 5, .bytes = 0};
  if (xy_configure(port, &cfg, &limit, 7, NULL) != XY_ERR_AGAIN) {
    return 8;
  }

  if (xy_probe(port, NULL, NULL, 0, NULL, NULL, NULL) != XY_OK) {
    return 9;
  }

  // the fake writes both outs, then answers ERR_BUSY for delta 0
  int64_t next = 0;
  int32_t delta = 0;
  if (xy_tune(port, 0, 5, 200, 0.5, &next, &delta) != XY_ERR_BUSY || next != 4 || delta != -1) {
    return 10;
  }

  // the fake writes only count
  xy_stats seen = {.count = 1, .bytes = 99};
  uint32_t count;
  xy_link link;
  if (xy_stats_of(port, &seen, &count, &link) != XY_OK || seen.count != 42 || seen.bytes != 0) {
    return 11;
  }

  if (xy_send(port, NULL, 4) != XY_ERR_UNSUPPORTED) {
    return 12;
  }

  if (xy_bump(port, NULL, &tally, data, sizeof data) != XY_ERR_FLOOR) {
    return 13;
  }

  if (xy_recv(port, NULL, 8) != XY_ERR_UNSUPPORTED) {
    return 14;
  }

  uint32_t level = 1;
  if (xy_bump(port, &level, &tally, NULL, 3) != XY_ERR_UNSUPPORTED) {
    return 15;
  }

  uint64_t items_wrote;
  uint64_t items_needed;
  char labels[6];
  uint32_t labels_wrote;
  uint32_t labels_needed;
  if (xy_list(port, NULL, 3, &items_wrote, &items_needed, labels, sizeof labels, &labels_wrote, &labels_needed) !=
      XY_ERR_UNSUPPORTED) {
    return 16;
  }
  _Alignas(xy_entry) unsigned char raw[4 * sizeof(xy_entry)];
  // an integer-to-pointer conversion, implementation-defined (C17 6.3.2.3p5); a pointer-to-pointer one to a
  // misaligned address is undefined (6.3.2.3p7)
  xy_entry* misaligned = (xy_entry*)(uintptr_t)(raw + 1);
  if (xy_list(port, misaligned, 3, &items_wrote, &items_needed, labels, sizeof labels, &labels_wrote,
              &labels_needed) != XY_ERR_UNSUPPORTED) {
    return 17;
  }
  xy_entry items[3];
  if (xy_list(port, items, (uint64_t)1 << 60, &items_wrote, &items_needed, labels, sizeof labels, &labels_wrote,
              &labels_needed) != XY_ERR_UNSUPPORTED) {
    return 18;
  }
  // fake_xy.rs answers ERR_OTHER to an array that arrives holding anything but zeros
  memset(items, 0xff, sizeof items);
  if (xy_list(port, items, 3, &items_wrote, &items_needed, labels, sizeof labels, &labels_wrote, &labels_needed) !=
          XY_OK ||
      items_wrote != 3 || items[2].id != 12 || items[2].label.offset != 4 || items[2].label.length != 2 ||
      memcmp(labels, "e0e1e2", sizeof labels) != 0) {
    return 19;
  }
  if (xy_list(port, items, 3, NULL, &items_needed, labels, sizeof labels, &labels_wrote, &labels_needed) !=
      XY_ERR_FLOOR) {
    return 20;
  }
  if (xy_list(port, NULL, 0, &items_wrote, &items_needed, labels, sizeof labels, &labels_wrote, &labels_needed) !=
      XY_ERR_UNSUPPORTED) {
    return 21;
  }
  if (xy_list(port, items, (uint64_t)1 << 62, &items_wrote, &items_needed, labels, sizeof labels, &labels_wrote,
              &labels_needed) != XY_ERR_UNSUPPORTED) {
    return 22;
  }

  const xy_cut cuts[2] = {XY_AFTER_ONE, XY_AFTER_FOUR};
  if (xy_stream(port, 1, cuts, 2, NULL, NULL) != XY_ERR_FLOOR) {
    return 23;
  }
  if (xy_stream(port, 1, NULL, 2, halting_sink, &sentinel) != XY_ERR_UNSUPPORTED || sentinel_calls != 0) {
    return 24;
  }
  _Alignas(xy_cut) unsigned char cut_raw[3 * sizeof(xy_cut)] = {0};
  const xy_cut* misaligned_cuts = (const xy_cut*)(uintptr_t)(cut_raw + 1);
  if (xy_stream(port, 1, misaligned_cuts, 2, halting_sink, &sentinel) != XY_ERR_UNSUPPORTED || sentinel_calls != 0) {
    return 25;
  }
  if (xy_stream(port, 1, cuts, 2, halting_sink, &sentinel) != XY_ERR_AGAIN || sentinel_calls != 1) {
    return 26;
  }
  if (xy_stream(port, 1, NULL, 0, halting_sink, &sentinel) != XY_ERR_AGAIN || sentinel_calls != 2) {
    return 27;
  }
  if (xy_send(port, NULL, 0) != XY_ERR_BUSY) {
    return 28;
  }

  memset(dirty, 0xaa, sizeof dirty);
  if (xy_recv(NULL, dirty, sizeof dirty) != XY_ERR_OTHER) {
    return 29;
  }
  for (size_t i = 0; i < sizeof dirty; ++i) {
    if ((unsigned char)dirty[i] != 0xaa) {
      return 29;
    }
  }

  if (!conversions_answer()) {
    return 30;
  }

  if (xy_destroy_port(port) != XY_OK) {
    return 2;
  }
  return 0;
}

// the most records a view of the fakes' notes holds, and the longest line of text written for one
enum { notes_max = 8, text_max = 96 };

// a record a walk reached: its byte offset from the view's start and its line of the text form
struct note {
  uint32_t offset;
  char text[text_max];
};

// a view as far as xy_note_first and xy_note_next reach: its records, their notes, their bytes
struct notes_walk {
  uint32_t count;
  uint32_t bytes;
  const xy_note_head* records[notes_max];
  struct note notes[notes_max];
};

// a view's refusal as xy_note_well_formed names it, clause XY_UNION_OK where there is none
struct refusal {
  xy_union_clause clause;
  uint32_t index;
  uint32_t offset;
};

// `record`'s line of the text form, after the switch on its kind and the cast to its member's
// struct; false for a kind no member has or a line longer than text_max
static bool note_text(const xy_note_head* record, char text[text_max]) {
  int n;
  switch (record->kind) {
    case XY_KIND_LINE: {
      const xy_note_line* line = (const xy_note_line*)record;
      n = snprintf(text, text_max, "line %" PRIu16 " %" PRIu16 " %" PRIu32 " %" PRIu32 " %" PRIu32, line->head.kind,
                   line->head.size, line->head.at, line->label.offset, line->label.length);
      break;
    }
    case XY_KIND_MARK: {
      const xy_note_mark* mark = (const xy_note_mark*)record;
      n = snprintf(text, text_max, "mark %" PRIu16 " %" PRIu16 " %" PRIu32 " %" PRId32 " %" PRIu32, mark->head.kind,
                   mark->head.size, mark->head.at, mark->value, mark->flag);
      break;
    }
    default:
      return false;
  }
  return n >= 0 && n < text_max;
}

// `record <i> at offset <o>: <clause>`; false where it is longer than text_max
static bool refusal_text(struct refusal refusal, char text[text_max]) {
  const int n = snprintf(text, text_max, "record %" PRIu32 " at offset %" PRIu32 ": %s", refusal.index, refusal.offset,
                         xy_union_clause_text(refusal.clause));
  return n >= 0 && n < text_max;
}

// walks `list` by xy_note_first and xy_note_next until either answers null; false where it
// reaches more than notes_max records or one whose text cannot be written
static bool walk_notes(const xy_note_head* list, uint32_t bytes, struct notes_walk* walk) {
  walk->count = 0;
  walk->bytes = 0;
  for (const xy_note_head* record = xy_note_first(list, bytes); record != NULL;
       record = xy_note_next(list, record, bytes)) {
    if (walk->count == notes_max) {
      return false;
    }
    struct note* note = &walk->notes[walk->count];
    note->offset = walk->bytes;
    if (!note_text(record, note->text)) {
      return false;
    }
    walk->records[walk->count++] = record;
    walk->bytes += record->size;
  }
  return true;
}

// whether a view holds `count` records over its `bytes` by both its walk and xy_note_well_formed;
// where not, the stderr line `xy_on_notes: <view>: <refusal>`, the refusal well_formed's
static bool notes_view_ok(const char* view, const xy_note_head* list, uint32_t count, uint32_t bytes,
                          struct notes_walk* walk, struct refusal* refusal) {
  const bool walked = walk_notes(list, bytes, walk) && walk->count == count && walk->bytes == bytes;
  refusal->clause = xy_note_well_formed(list, count, bytes, &refusal->index, &refusal->offset);
  if (walked && refusal->clause == XY_UNION_OK) {
    return true;
  }
  char text[text_max];
  if (refusal_text(*refusal, text)) {
    fprintf(stderr, "xy_on_notes: %s: %s\n", view, text);
  }
  return false;
}

// the record `offset` bytes from `list`'s start by a walk from it, C having no `at`; null where the
// walk passes the offset or ends before it, and *index the record after it
static const xy_note_head* note_at(const xy_note_head* list, uint32_t bytes, uint32_t offset, uint32_t* index) {
  uint32_t at = 0;
  *index = 0;
  for (const xy_note_head* record = xy_note_first(list, bytes); record != NULL && at <= offset;
       record = xy_note_next(list, record, bytes)) {
    if (at == offset) {
      return record;
    }
    at += record->size;
    ++*index;
  }
  return NULL;
}

// whether the walk of `list` to `note`'s offset lands on a record whose text is `note`'s
static bool resolves(const xy_note_head* list, uint32_t bytes, const struct note* note) {
  uint32_t index;
  const xy_note_head* record = note_at(list, bytes, note->offset, &index);
  char text[text_max];
  return record != NULL && note_text(record, text) && strcmp(text, note->text) == 0;
}

// whether the walk of `list` to `offset` passes it as the sixth clause at `index`, in its text
static bool not_a_start(const xy_note_head* list, uint32_t bytes, uint32_t offset, uint32_t index, const char* want) {
  struct refusal refusal = {XY_UNION_NOT_A_RECORD_START, 0, offset};
  char text[text_max];
  return note_at(list, bytes, offset, &refusal.index) == NULL && refusal.index == index &&
         refusal_text(refusal, text) && strcmp(text, want) == 0;
}

// what the notes mode's sink saw over one stream
struct notes_run {
  uint32_t calls;
  uint32_t fresh_counts[notes_max];
  uint32_t kept_count;
  struct note kept[notes_max];
  int failed;
};

// one call of the notes mode's sink, checks 50 to 53: 0 or the failing check
static int check_notes(const xy_note_head* seen, uint32_t seen_count, uint32_t seen_bytes, const xy_note_head* fresh,
                       uint32_t fresh_count, uint32_t fresh_bytes, struct notes_run* run) {
  struct notes_walk seen_walk;
  struct notes_walk fresh_walk;
  struct refusal refusal;
  if (!notes_view_ok("seen", seen, seen_count, seen_bytes, &seen_walk, &refusal) ||
      !notes_view_ok("fresh", fresh, fresh_count, fresh_bytes, &fresh_walk, &refusal)) {
    return 50;
  }
  if (fresh_bytes > seen_bytes || seen_count != run->kept_count + fresh_count || seen_count > notes_max) {
    return 51;
  }
  const uint32_t earlier = run->kept_count;
  for (uint32_t i = 0; i < fresh_count; ++i) {
    if (seen_walk.records[earlier + i] != fresh_walk.records[i]) {
      return 51;
    }
    run->kept[run->kept_count] = fresh_walk.notes[i];
    run->kept[run->kept_count++].offset += seen_bytes - fresh_bytes;
  }
  for (uint32_t i = 0; i < seen_count; ++i) {
    if (seen_walk.notes[i].offset != run->kept[i].offset || strcmp(seen_walk.notes[i].text, run->kept[i].text) != 0) {
      return 51;
    }
  }
  for (uint32_t i = 0; i < seen_count; ++i) {
    if (!resolves(seen, seen_bytes, &run->kept[i])) {
      return 52;
    }
  }
  for (uint32_t i = 0; i < fresh_count; ++i) {
    if (!resolves(fresh, fresh_bytes, &fresh_walk.notes[i])) {
      return 52;
    }
  }
  char at_extent[text_max];
  const struct refusal past = {XY_UNION_NOT_A_RECORD_START, seen_count, seen_bytes};
  if (!not_a_start(seen, seen_bytes, 4, 1, "record 1 at offset 4: offset is not a record's start") ||
      !refusal_text(past, at_extent) || !not_a_start(seen, seen_bytes, seen_bytes, seen_count, at_extent)) {
    return 53;
  }
  return 0;
}

static xy_flow notes_sink(const xy_note_head* seen, uint32_t seen_count, uint32_t seen_bytes, const xy_note_head* fresh,
                          uint32_t fresh_count, uint32_t fresh_bytes, void* user_data) {
  struct notes_run* run = user_data;
  if (run->calls < notes_max) {
    run->fresh_counts[run->calls] = fresh_count;
  }
  ++run->calls;
  if (run->failed == 0) {
    run->failed = check_notes(seen, seen_count, seen_bytes, fresh, fresh_count, fresh_bytes, run);
  }
  return XY_GO;
}

static bool open_notes_port(xy_port* port) {
  xy_stats stats;
  uint32_t generation;
  xy_wrap wrap;
  return xy_open_port(3, port, &stats, &generation, &wrap) == XY_OK;
}

// the `notes` mode
static int notes(void) {
  static const struct {
    uint32_t batch;
    uint32_t calls;
    uint32_t fresh_counts[3];
  } streams[] = {{2, 3, {2, 2, 2}}, {4, 2, {4, 2}}, {0, 1, {6}}};
  xy_port port;
  if (!open_notes_port(&port)) {
    return 50;
  }
  for (size_t s = 0; s < sizeof streams / sizeof streams[0]; ++s) {
    struct notes_run run = {0};
    const xy_status result = xy_stream_notes(port, streams[s].batch, notes_sink, &run);
    if (run.failed != 0) {
      return run.failed;
    }
    if (result != XY_OK || run.calls != streams[s].calls ||
        memcmp(run.fresh_counts, streams[s].fresh_counts, run.calls * sizeof run.fresh_counts[0]) != 0) {
      return 50;
    }
    for (uint32_t i = 0; streams[s].batch == 2 && i < run.kept_count; ++i) {
      if (printf("%s\n", run.kept[i].text) < 0) {
        return 50;
      }
    }
  }
  if (fflush(stdout) != 0 || xy_destroy_port(port) != XY_OK) {
    return 50;
  }
  return 0;
}

// what the `notes <selector>` mode's sink saw at the call it halted
struct refused_run {
  struct refusal seen;
  struct refusal fresh;
  uint32_t earlier_count;
  uint32_t earlier_bytes;
};

static xy_flow refusing_sink(const xy_note_head* seen, uint32_t seen_count, uint32_t seen_bytes,
                             const xy_note_head* fresh, uint32_t fresh_count, uint32_t fresh_bytes, void* user_data) {
  struct refused_run* run = user_data;
  struct notes_walk walk;
  const bool seen_ok = notes_view_ok("seen", seen, seen_count, seen_bytes, &walk, &run->seen);
  const bool fresh_ok = notes_view_ok("fresh", fresh, fresh_count, fresh_bytes, &walk, &run->fresh);
  if (seen_ok && fresh_ok) {
    return XY_GO;
  }
  run->earlier_count = seen_count - fresh_count;
  run->earlier_bytes = seen_bytes - fresh_bytes;
  return XY_HALT;
}

// the `notes <selector>` mode
static int refused_notes(const char* arg) {
  int selector = 0;
  for (const char* digit = arg; *digit != '\0'; ++digit) {
    if (*digit < '0' || *digit > '9' || selector > 25) {
      return 100;
    }
    selector = selector * 10 + (*digit - '0');
  }
  xy_port port;
  if (*arg == '\0' || selector > 255 || !open_notes_port(&port)) {
    return 100;
  }
  struct refused_run run = {{XY_UNION_OK, 0, 0}, {XY_UNION_OK, 0, 0}, 0, 0};
  const xy_status result = xy_stream_notes(port, selector, refusing_sink, &run);
  if (xy_destroy_port(port) != XY_OK || result != XY_ERR_AGAIN || run.seen.clause == XY_UNION_OK ||
      run.fresh.clause == XY_UNION_OK || run.seen.clause != run.fresh.clause ||
      run.seen.index != run.earlier_count + run.fresh.index ||
      run.seen.offset != run.earlier_bytes + run.fresh.offset) {
    return 100;
  }
  return selector;
}

int main(int argc, char** argv) {
  if (argc > 1 && strcmp(argv[1], "panic") == 0) {
    (void)xy_seek(NULL, UINT64_MAX);
    return 99;
  }
  if (argc > 1 && strcmp(argv[1], "notes") == 0) {
    return argc == 2 ? notes() : refused_notes(argv[2]);
  }
  return cases();
}
