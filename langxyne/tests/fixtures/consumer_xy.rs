// A consumer of support.KITCHEN_SINK's Rust binding, run against either fake and over the static archive; the
// binding is xy_api.rs beside this file. consumer_xy.cpp's steps, in its order and with its codes.
// Exit codes: 0 all steps passed; 1 create(99) failure result; 2 create(3) and its cached
// out parameters; 3 send; 4 recv; 5 configure with the token xy_mint issues; 6 stats_of; 7 move; 8 move assignment;
// 9 release; 10 drops freed the slots; 11 PRODUCT; 12 DataLink::create; 13 bump; 14 seek and tune;
// 15 annotate (an _optional struct in parameter); 16 the _to_string conversions; 17 probe (an enum out
// parameter as the enum, _optional memory in, scalar in, inout and out parameters); 18 echo_offset (a
// boxed scalar by value and out); 20 an empty optional slice reaches the library as a present,
// zero-length payload; list, by capacity (items, labels), as consumer_xy.cpp: 21 (0, 0) succeeds
// reporting nothing written and what is needed; 22 (1, 2) entry 0 and its label; 23 (2, 3) entry
// 1's label leaves the arena written, so resolve is None; 24 (3, 6) every label resolves; 25 (5, 8)
// the prefix written and what is needed; 26 (4, 6) a `wrote` above the capacity alone, 27 (6, 6) a
// `wrote` above the need alone, 28 (3, 5) a `wrote` above a byte buffer's capacity: each panics
// naming xy_list and the buffer, caught by a catch_unwind over the method that needs no
// AssertUnwindSafe, which only compiles where Port is RefUnwindSafe. Code 19 is unused.
// stream, as consumer_xy.cpp: 30 to 37; 38 a closure panicking on its second call: stream panics
// with the closure's own message, the closure having run exactly twice. 40 inside stream(1)'s
// closure, seek(1 << 40) on the same port answers Err(ErrBusy) without reaching the library, and
// the stream answers Ok; 48 inside it, attach(&port) on a DataLink answers Err(ErrBusy) without
// reaching the library, and Ok after the stream; 42 notify(1) calls each closure once with Mode::Slow and answers Ok; 43
// notify(1) whose first closure panics: second never runs, and the panic resumes with first's
// message, first having run once; 44 notify(7): a panic naming xy_on_mode and mode resumes, and
// neither closure ran; 45 stream(98), whose library calls the sink eight times whatever it
// answers, with a closure panicking on its second call and then on its eighth: each runs up to
// that call only, its panic resumes, and seek(98) then answers Ok, the library having seen a stop.
// stream_notes, the notes fake_xy.rs's header lists, for batch 2 and batch 4, each view walked
// through records() and its records matched on NoteRef with no wildcard: 50 the stream answers
// Ok after calls of 2, 2, 2 notes (of 4, 2), every view walked to its count with no refusal (the
// refusal's text on stderr); 51 at each call fresh ends where seen ends, and seen's records are
// every earlier call's fresh records then this call's; 52 at each call every offset recorded so
// far resolves through seen.at to its record, and each of fresh's through fresh.at, each offset in
// units of the list's alignment; 53 seen.at of byte 4,
// inside n0, is the error "record 1 at offset 4: offset is not a record's start", and seen.at of
// its extent the error naming the record after the last.
// Its stdout is the batch-2 stream's records, one line each, in order, fields in definition order
// and integers in decimal: `line <head.kind> <head.size> <head.at> <label.offset> <label.length>`
// or `mark <head.kind> <head.size> <head.at> <value> <flag>`, as `mark 2 16 1 -1 1`.
// `consumer notes <selector>`, checks 101 to 105, against fake_xy.cpp alone: the stream whose
// second call fake_xy.cpp's header describes for that selector is refused by the walk of both its
// views, each refusal on stderr as `xy_on_notes: <view>: record <i> at offset <o>: <clause>`, the
// closure answering Halt, and the process exits with the selector; 100 where no view was refused,
// the stream did not answer ErrAgain, or seen's refusal is not fresh's past the earlier records.
// `consumer notes 106`, against fake_xy.cpp alone: seen.at of byte 16, the record past seen's
// count, is refused, on stderr as `xy_on_notes: seen: <refusal>`, the closure answering Halt, and
// the process exits 106; 100 where at did not refuse or the stream did not answer ErrAgain.
#[allow(dead_code)]
mod xy_api;

use std::any::Any;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::process::ExitCode;
use xy_api::{
    Cut, DataLink, Entry, Filled, Flow, Mode, NoteRef, NoteSequence, Offset, Port, Stats, Status, Text,
    UnionError,
};

// NoteSequence::at takes an offset in units of the list's alignment, as its index's type.
const NOTE_ALIGN: u32 = xy_api::NOTE_ALIGN as u32;

// What stream's sink saw: each call's (seen, fresh, last) counts, and whether every view held
// what the fakes promise.
struct Streamed {
    result: Result<(), Status>,
    calls: Vec<(usize, usize, u32)>,
    views: bool,
}

impl Streamed {
    // Whether the calls' fresh counts are `fresh`, seen counting them up, the last one alone
    // final where `last`.
    fn is(&self, fresh: &[usize], last: bool) -> bool {
        let mut seen = 0;
        let expected = fresh.iter().enumerate().map(|(i, &count)| {
            seen += count;
            (seen, count, u32::from(last && i == fresh.len() - 1))
        });
        self.calls.iter().copied().eq(expected)
    }
}

// stream(batch, cuts), its sink answering halt on call `halt_on` (0: never).
fn stream(port: &Port, batch: u32, cuts: &[Cut], halt_on: usize) -> Streamed {
    let mut calls = Vec::new();
    let mut views = true;
    let result = port.stream(batch, cuts, |seen, fresh, arena, last| {
        calls.push((seen.len(), fresh.len(), last));
        views &= fresh
            .iter()
            .map(|e| e.id)
            .eq(seen[seen.len() - fresh.len()..].iter().map(|e| e.id));
        views &= seen
            .iter()
            .enumerate()
            .all(|(i, e)| e.label.resolve(arena) == Some(format!("e{i}").as_bytes()));
        let end = Text {
            offset: u32::try_from(arena.len()).unwrap_or(u32::MAX),
            length: 2,
        };
        views &= end.resolve(arena).is_none();
        if calls.len() == halt_on {
            Flow::Halt
        } else {
            Flow::Go
        }
    });
    Streamed {
        result,
        calls,
        views,
    }
}

// A note's size and its line of stdout's text form.
fn note_text(record: NoteRef<'_>) -> (u32, String) {
    let (member, head, first, second) = match record {
        NoteRef::Line(r) => ("line", r.head, i64::from(r.label.offset), i64::from(r.label.length)),
        NoteRef::Mark(r) => ("mark", r.head, i64::from(r.value), i64::from(r.flag)),
    };
    let text = format!("{member} {} {} {} {first} {second}", head.kind, head.size, head.at);
    (u32::from(head.size), text)
}

// Each record's byte offset and line, in order, or the walk's refusal.
fn walk(notes: NoteSequence<'_>) -> Result<Vec<(u32, String)>, UnionError> {
    let mut offset = 0;
    notes
        .records()
        .map(|record| {
            let (size, text) = note_text(record?);
            offset += size;
            Ok((offset - size, text))
        })
        .collect()
}

// One call of stream_notes' sink, checks 50 to 53: `kept` holds every record earlier calls
// delivered, at its offset in seen, and gains fresh's.
fn check_notes(seen: NoteSequence<'_>, fresh: NoteSequence<'_>, kept: &mut Vec<(u32, String)>) -> Result<(), u8> {
    let walked = walk(seen).and_then(|s| Ok((s, walk(fresh)?)));
    let (seen_notes, fresh_notes) = walked.map_err(|error| {
        eprintln!("xy_on_notes: {error}");
        50
    })?;
    let before = seen.bytes().len().checked_sub(fresh.bytes().len()).ok_or(51)?;
    let before = u32::try_from(before).map_err(|_| 51)?;
    if seen.bytes().as_ptr_range().end != fresh.bytes().as_ptr_range().end {
        return Err(51);
    }
    kept.extend(fresh_notes.iter().map(|(offset, text)| (before + offset, text.clone())));
    if seen_notes != *kept {
        return Err(51);
    }
    let resolves = |notes: NoteSequence<'_>, (offset, text): &(u32, String)| {
        notes.at(*offset / NOTE_ALIGN).is_ok_and(|record| note_text(record).1 == *text)
    };
    if !kept.iter().all(|note| resolves(seen, note)) || !fresh_notes.iter().all(|note| resolves(fresh, note)) {
        return Err(52);
    }
    let extent = u32::try_from(seen.bytes().len()).map_err(|_| 53)?;
    let refused = |offset: u32| seen.at(offset / NOTE_ALIGN).err().map(|error| error.to_string());
    if refused(4).as_deref() != Some("record 1 at offset 4: offset is not a record's start")
        || refused(extent)
            != Some(format!("record {} at offset {extent}: offset is not a record's start", seen.count()))
    {
        return Err(53);
    }
    Ok(())
}

// Checks 101 to 105: `consumer notes <selector>`.
fn refused_notes(selector: u32) -> u8 {
    let Ok(port) = Port::create(3) else {
        return 100;
    };
    let mut shifted = false;
    let streamed = port.stream_notes(selector, |seen, fresh| {
        let (seen_error, fresh_error) = (walk(seen).err(), walk(fresh).err());
        if seen_error.is_none() && fresh_error.is_none() {
            return Flow::Go;
        }
        for (view, error) in [("seen", seen_error), ("fresh", fresh_error)] {
            if let Some(error) = error {
                eprintln!("xy_on_notes: {view}: {error}");
            }
        }
        let earlier_count = seen.count().checked_sub(fresh.count());
        let earlier_bytes = seen.bytes().len().checked_sub(fresh.bytes().len());
        let earlier_bytes = earlier_bytes.and_then(|bytes| u32::try_from(bytes).ok());
        shifted = match (seen_error, fresh_error, earlier_count, earlier_bytes) {
            (Some(s), Some(f), Some(count), Some(bytes)) => {
                Some(s.index) == count.checked_add(f.index)
                    && Some(s.offset) == bytes.checked_add(f.offset)
                    && s.clause == f.clause
            }
            _ => false,
        };
        Flow::Halt
    });
    if streamed != Err(Status::ErrAgain) || !shifted {
        return 100;
    }
    u8::try_from(selector).unwrap_or(100)
}

// Check 106: `consumer notes 106`.
fn at_past_count() -> u8 {
    let Ok(port) = Port::create(3) else {
        return 100;
    };
    let mut refused = false;
    let streamed = port.stream_notes(106, |seen, _| {
        if let Err(error) = seen.at(16 / NOTE_ALIGN) {
            eprintln!("xy_on_notes: seen: {error}");
            refused = true;
        }
        Flow::Halt
    });
    if streamed != Err(Status::ErrAgain) || !refused {
        return 100;
    }
    106
}

// Whether a caught panic's message holds every one of `words`.
fn panicked_naming(payload: &(dyn Any + Send), words: &[&str]) -> bool {
    let message = payload
        .downcast_ref::<String>()
        .map(String::as_str)
        .or_else(|| payload.downcast_ref::<&str>().copied())
        .unwrap_or_default();
    words.iter().all(|word| message.contains(word))
}

// `<T as NotClone<_>>::check` names one function only when T is not Clone; for a Clone T the
// two impls make it ambiguous and the build fails. NotFromU64 is the same test for From<u64>.
// run() names both, so the checks are compile-time steps.
trait NotClone<A> {
    fn check() {}
}
impl<T> NotClone<()> for T {}
impl<T: Clone> NotClone<u8> for T {}

trait NotFromU64<A> {
    fn check() {}
}
impl<T> NotFromU64<()> for T {}
impl<T: From<u64>> NotFromU64<u8> for T {}

const _: fn(Stats) -> xy_api::ffi::xy_stats = |value| value;
const _: fn(xy_api::Wrap) -> xy_api::ffi::xy_wrap = |value| value;
const _: fn(Offset) -> xy_api::ffi::xy_offset = |value| value;
const _: fn(i32) -> Result<Status, i32> = Status::try_from;
const _: fn(u32) -> Result<Mode, u32> = Mode::try_from;
const _: () = assert!(size_of::<Status>() == size_of::<i32>());
const _: () = assert!(size_of::<Mode>() == size_of::<u32>());
const _: u32 = xy_api::API_VERSION;
const _: i32 = xy_api::FEAT_A;
const _: u32 = xy_api::FEAT_ALL;
const _: i32 = xy_api::NEG;
const _: u32 = xy_api::MAGIC;
const _: () = assert!(Status::ErrBusy as i32 == 9);
const _: () = assert!(Mode::Slow as u32 == 1);
const _: () = assert!(xy_api::FEAT_ALL == 9);
const _: () = assert!(xy_api::API_VERSION == 0x01020304);
const _: () = assert!(xy_api::NEG == -5);
const _: i32 = xy_api::FLOOR;
const _: () = assert!(xy_api::FLOOR == i32::MIN);
const _: () = assert!(Status::ErrFloor as i32 == i32::MIN);

fn run() -> u8 {
    let _: fn() = <Port as NotClone<_>>::check;
    let _: fn() = <Offset as NotFromU64<_>>::check;

    let Err(r) = Port::create(99) else {
        return 1;
    };
    if r != Status::ErrBusy || r.to_string() != "ERR_BUSY" {
        return 1;
    }

    let Ok(port) = Port::create(3) else {
        return 2;
    };
    if port.pstats().count != 3 || port.generation() != 7 || port.pwrap().n != 11 {
        return 2;
    }

    let buf = *b"abcd";
    if port.send(&buf) != Ok(()) || port.send(&buf[..3]) != Err(Status::ErrBusy) {
        return 3;
    }

    let mut out = [0u8; 5];
    if port.recv(&mut out) != Ok(()) || out[2] != 0 {
        return 4;
    }

    let cfg = Stats {
        count: 5,
        ..Stats::default()
    };
    let limit = 6;
    let mut token = std::ptr::null_mut();
    // SAFETY: token is a local the call writes.
    if Status::try_from(unsafe { xy_api::ffi::xy_mint(&mut token) }) != Ok(Status::Ok) {
        return 5;
    }
    // SAFETY: the library issued token and destroys none.
    if unsafe { port.configure(&cfg, &limit, Mode::Slow, token) } != Ok(()) {
        return 5;
    }

    let Ok((st, c, l)) = port.stats_of() else {
        return 6;
    };
    if st.count != 42 || c != 43 || l.is_null() {
        return 6;
    }

    let mut level = 4;
    let mut tally = Stats {
        count: 5,
        ..Stats::default()
    };
    let mut data = *b"abc";
    if port.bump(&mut level, &mut tally, &mut data) != Ok(())
        || level != 5
        || tally.count != 10
        || &data != b"bcd"
    {
        return 13;
    }

    if port.seek(1 << 40) != Ok(())
        || port.tune(-3, -(1 << 40), 200, 0.5) != Ok((-(1 << 40) - 1, -4))
    {
        return 14;
    }

    let note = Stats {
        count: 7,
        ..Stats::default()
    };
    if port.annotate(Some(&note)) != Ok(()) || port.annotate(None) != Ok(()) {
        return 15;
    }

    let probe_limit = 3;
    let mut probe_level = 4;
    let mut peek = 0;
    if port.probe(None, None, None, None) != Ok(Mode::Slow)
        || port.probe(
            Some(b"ab".as_slice()),
            Some(&probe_limit),
            Some(&mut probe_level),
            Some(&mut peek),
        ) != Ok(Mode::Slow)
        || probe_level != 5
        || peek != 9
        || port.probe(Some(b"abc".as_slice()), None, None, None) != Err(Status::ErrBusy)
    {
        return 17;
    }

    if port.echo_offset(Offset(1 << 40)) != Ok(Offset(1 << 40)) {
        return 18;
    }

    // Some(&[]) is a non-null pointer with a count of 0, which the fake refuses as a payload
    // that is present but not 2 bytes; None, a null pointer, it accepts.
    if port.probe(Some(&[]), None, None, None) != Err(Status::ErrBusy) {
        return 20;
    }

    let filled = |wrote, needed| Filled { wrote, needed };
    let mut items = [Entry::default(); 8];
    let mut labels = [0u8; 8];
    if port.list(&mut items[..0], &mut labels[..0]) != Ok((filled(0, 3), filled(0, 6))) {
        return 21;
    }
    let Ok((written, arena)) = port.list(&mut items[..1], &mut labels[..2]) else {
        return 22;
    };
    if written.wrote != 1 || items[0].id != 10 || items[0].label.resolve(&labels[..arena.wrote]) != Some(b"e0".as_slice()) {
        return 22;
    }
    let Ok((written, arena)) = port.list(&mut items[..2], &mut labels[..3]) else {
        return 23;
    };
    let bytes = &labels[..arena.wrote];
    if written.wrote != 2 || items[1].id != 11 || items[1].label.resolve(bytes).is_some() {
        return 23;
    }
    let Ok((_, arena)) = port.list(&mut items[..3], &mut labels[..6]) else {
        return 24;
    };
    let bytes = &labels[..arena.wrote];
    if items[..3].iter().map(|e| e.label.resolve(bytes)).ne([b"e0", b"e1", b"e2"].map(|s| Some(s.as_slice()))) {
        return 24;
    }
    if port.list(&mut items[..5], &mut labels) != Ok((filled(3, 3), filled(6, 6))) {
        return 25;
    }
    match catch_unwind(|| port.list(&mut [Entry::default(); 4], &mut [0; 6])) {
        Err(payload) if panicked_naming(&*payload, &["xy_list over-reported items"]) => {}
        _ => return 26,
    }
    match catch_unwind(|| port.list(&mut [Entry::default(); 6], &mut [0; 6])) {
        Err(payload) if panicked_naming(&*payload, &["xy_list over-reported items"]) => {}
        _ => return 27,
    }
    match catch_unwind(|| port.list(&mut [Entry::default(); 3], &mut [0; 5])) {
        Err(payload) if panicked_naming(&*payload, &["xy_list over-reported labels"]) => {}
        _ => return 28,
    }

    let s = stream(&port, 1, &[], 0);
    if !s.is(&[1, 1, 1, 1, 1, 1, 1, 0], true) || s.result != Ok(()) || !s.views {
        return 30;
    }
    let s = stream(&port, 3, &[], 0);
    if !s.is(&[3, 3, 1], true) || s.result != Ok(()) {
        return 31;
    }
    let s = stream(&port, 0, &[], 0);
    if !s.is(&[7], true) || s.result != Ok(()) {
        return 32;
    }
    let s = stream(&port, 3, &[Cut::AfterOne, Cut::AfterFour], 0);
    if !s.is(&[2, 3, 2], true) || s.result != Ok(()) {
        return 33;
    }
    let s = stream(&port, 0, &[Cut::AfterFour], 0);
    if !s.is(&[5, 2], true) || s.result != Ok(()) {
        return 34;
    }
    let s = stream(&port, 1, &[], 3);
    if !s.is(&[1, 1, 1], false) || s.result != Err(Status::ErrAgain) {
        return 35;
    }
    let s = stream(&port, 3, &[], 1);
    if !s.is(&[3], false) || s.result != Err(Status::ErrAgain) {
        return 36;
    }
    let s = stream(&port, 3, &[], 0);
    if !s.views || s.calls.len() != 3 {
        return 37;
    }
    let mut runs = 0;
    let streamed = catch_unwind(AssertUnwindSafe(|| {
        port.stream(1, &[], |_, _, _, _| {
            runs += 1;
            if runs == 2 {
                panic!("the consumer's sink panics on its second call");
            }
            Flow::Go
        })
    }));
    match streamed {
        Err(payload)
            if runs == 2 && panicked_naming(&*payload, &["the consumer's sink panics on its second call"]) => {}
        _ => return 38,
    }

    let mut refused = None;
    let streamed = port.stream(1, &[], |_, _, _, _| {
        if refused.is_none() {
            refused = Some(port.seek(1 << 40));
        }
        Flow::Go
    });
    if streamed != Ok(()) || refused != Some(Err(Status::ErrBusy)) {
        return 40;
    }

    let Ok(link) = DataLink::create() else {
        return 48;
    };
    let mut refused = None;
    let streamed = port.stream(1, &[], |_, _, _, _| {
        if refused.is_none() {
            refused = Some(link.attach(&port));
        }
        Flow::Go
    });
    if streamed != Ok(()) || refused != Some(Err(Status::ErrBusy)) || link.attach(&port) != Ok(()) {
        return 48;
    }

    let (mut firsts, mut seconds) = (Vec::new(), Vec::new());
    let notified = port.notify(
        1,
        |mode| {
            firsts.push(mode);
            Flow::Go
        },
        |mode| {
            seconds.push(mode);
            Flow::Go
        },
    );
    if notified != Ok(()) || firsts != [Mode::Slow] || seconds != [Mode::Slow] {
        return 42;
    }

    let (mut first_runs, mut second_runs) = (0, 0);
    let notified = catch_unwind(AssertUnwindSafe(|| {
        port.notify(
            1,
            |_| {
                first_runs += 1;
                panic!("the consumer's first callback panics");
            },
            |_| {
                second_runs += 1;
                Flow::Go
            },
        )
    }));
    match notified {
        Err(payload)
            if (first_runs, second_runs) == (1, 0)
                && panicked_naming(&*payload, &["the consumer's first callback panics"]) => {}
        _ => return 43,
    }

    let (mut first_runs, mut second_runs) = (0, 0);
    let notified = catch_unwind(AssertUnwindSafe(|| {
        port.notify(
            7,
            |_| {
                first_runs += 1;
                Flow::Go
            },
            |_| {
                second_runs += 1;
                Flow::Go
            },
        )
    }));
    match notified {
        Err(payload) if (first_runs, second_runs) == (0, 0) && panicked_naming(&*payload, &["xy_on_mode", "mode"]) => {}
        _ => return 44,
    }

    // batch 98 calls the sink eight times whatever it answers: a panic on the second call stops
    // the closure being called again, and one on the eighth, the last, is still answered stop
    for panicking_call in [2, 8] {
        let mut runs = 0;
        let streamed = catch_unwind(AssertUnwindSafe(|| {
            port.stream(98, &[], |_, _, _, _| {
                runs += 1;
                if runs == panicking_call {
                    panic!("the consumer's sink panics on a call");
                }
                Flow::Go
            })
        }));
        match streamed {
            Err(payload)
                if runs == panicking_call
                    && panicked_naming(&*payload, &["the consumer's sink panics on a call"]) => {}
            _ => return 45,
        }
        if port.seek(98) != Ok(()) {
            return 45;
        }
    }

    for (batch, calls) in [(2, [2, 2, 2].as_slice()), (4, &[4, 2])] {
        let (mut kept, mut fresh_counts, mut failed) = (Vec::new(), Vec::new(), None);
        let streamed = port.stream_notes(batch, |seen, fresh| {
            fresh_counts.push(fresh.count());
            if let Err(code) = check_notes(seen, fresh, &mut kept) {
                failed = failed.or(Some(code));
            }
            Flow::Go
        });
        if let Some(code) = failed {
            return code;
        }
        if streamed != Ok(()) || fresh_counts != calls {
            return 50;
        }
        if batch == 2 {
            for (_, text) in &kept {
                println!("{text}");
            }
        }
    }

    // Reading `port` after the move does not compile, so only the destination is checked.
    let moved = port;
    if moved.handle().is_null() {
        return 7;
    }

    let Ok(mut other) = Port::create(4) else {
        return 8;
    };
    if other.handle() == moved.handle() {
        return 8;
    }
    other = moved;
    if other.handle().is_null() || other.generation() != 7 {
        return 8;
    }

    // release consumes the port, so a second release does not compile; the fake aborts if the
    // drop that follows a release destroys the port again.
    if other.release() != Ok(()) {
        return 9;
    }

    {
        let ports = [1, 2, 3, 4].map(Port::create);
        if ports.iter().any(Result::is_err) {
            return 10;
        }
    }
    if Port::create(1).is_err() {
        return 10;
    }

    if xy_api::PRODUCT != "xy widget" {
        return 11;
    }

    if DataLink::create().is_err() {
        return 12;
    }

    if Mode::Slow.to_string() != "SLOW"
        || format!("{}", Status::ErrBusy) != "ERR_BUSY"
        || Status::try_from(12345) != Err(12345)
        || xy_api::access_to_string(3) != "ACC_A|ACC_B"
        || xy_api::access_to_string(1) != "ACC_A"
        || xy_api::access_to_string(0) != "NONE"
        || xy_api::access_to_string(9) != "ACC_A|0x8"
        || xy_api::access_to_string(-1) != "ACC_A|ACC_B|0xfffffffc"
        || xy_api::limit_to_string(16) != "MAX_UNITS"
        || xy_api::limit_to_string(xy_api::NEG) != "NEG"
        || xy_api::limit_to_string(xy_api::FLOOR) != "FLOOR"
        || xy_api::limit_to_string(99) != "UNKNOWN"
    {
        return 16;
    }
    0
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    ExitCode::from(match args.as_slice() {
        [notes, selector] if notes == "notes" && selector == "106" => at_past_count(),
        [notes, selector] if notes == "notes" => selector.parse().map_or(100, refused_notes),
        _ => run(),
    })
}
