// A fake implementation of support.KITCHEN_SINK's API behind the generated relay, built as
// the shared library `xy`: fake_xy.cpp's behaviour for every consumer, with named entries only. Where the relay
// hands over `None` for what a consumer never sends, the fake answers with an entry of its own,
// for edge_xy.c:
//   ErrFloor        a null non-optional pointer, a report or stream's sink or either of notify's
//                   callbacks included (probe's pmode excepted: probe writes it where given)
//   ErrUnsupported  a non-optional buffer the relay refused: null with a nonzero count,
//                   misaligned, or a count whose bytes exceed isize::MAX; also seek(12345),
//                   fake_xy.cpp's unnamed result, stream's batch 99, since the relay's callback
//                   cannot leave the call's thread, and stream's batches 95 and 97, lies of
//                   fake_xy.cpp's the relay gives the implementation no way to tell;
//                   stream_notes' batch above 6
//   ErrAgain        configure's mode naming no Mode entry
//   ErrOther        a null port for destroy_port and a null link or port for attach, as
//                   fake_xy.cpp; recv's or list's buffers not arriving zeroed
// mint writes the one token this library issues, and configure answers ok only for it, as
// fake_xy.cpp's. seek(u64::MAX) panics, so a caller can see the relay abort the process.
// stream's batch 96 delivers as batch 1 does, and while it runs seek(96) on any port calls its
// sink again with empty views and answers ok, as fake_xy.cpp's. Built for wasm, stream's batch 94
// calls the shim's callback, the Node binding's, with a user_data no frame of the binding names,
// and answers err_again where that call answered halt, else err_other.
//
// stream_notes pushes the six notes below through the relay's NoteBuf, which sets each head's
// kind (line 1, mark 2) and size (16) itself, so note i lies at byte 16 i. The selector `batch`
// is the notes a call (0: all six in one call), the last call the remainder; each call passes
// seen, every note so far, and fresh, those pushed since the previous call, seen's tail:
//   n0  line  at 0  label { offset 0, length 2 }
//   n1  mark  at 1  value -1           flag 1
//   n2  line  at 2  label { offset 2, length 3 }
//   n3  mark  at 3  value 2147483647   flag 0
//   n4  mark  at 4  value -2147483648  flag 4294967295
//   n5  line  at 5  label { offset 5, length 0 }

pub mod abi {
    include!(concat!(env!("LANGXYNE_RUST_DIR"), "/xy_api_abi.rs"));
}

use abi::{
    Entry, Mode, NoteBuf, NoteHead, NoteLine, NoteMark, NoteRef, Offset, OnBatch, OnMode, OnNotes,
    Stats, Status, Text, Wrap, ffi,
};
use core::cell::Cell;
use core::sync::atomic::{AtomicBool, AtomicU32, Ordering};

// A port handle is the address of its slot; a slot is open while it holds true.
static SLOTS: [AtomicBool; 4] = [const { AtomicBool::new(false) }; 4];
static LINK: u8 = 0;
// What mint's token points at.
static TOKEN: u8 = 0;
// The answers other than go the last batch-98 stream received.
static STREAM_STOPS: AtomicU32 = AtomicU32::new(0);

thread_local! {
    // The sink of the batch-96 stream running on this thread, which seek(96) calls again.
    static ACTIVE: Cell<*mut OnBatch<'static>> = const { Cell::new(core::ptr::null_mut()) };
}

// Clears ACTIVE when the batch-96 stream that set it returns.
struct Active;

impl Drop for Active {
    fn drop(&mut self) {
        ACTIVE.set(core::ptr::null_mut());
    }
}

fn link() -> ffi::xy_link {
    core::ptr::from_ref(&LINK).cast_mut().cast()
}

fn token() -> ffi::xy_token {
    core::ptr::from_ref(&TOKEN).cast_mut().cast()
}

pub fn open_port(
    unit: u32,
    pport: Option<&mut ffi::xy_port>,
    pstats: Option<&mut Stats>,
    generation: Option<&mut u32>,
    pwrap: Option<&mut Wrap>,
) -> Result<(), Status> {
    let (Some(pport), Some(generation), Some(pwrap)) = (pport, generation, pwrap) else {
        return Err(Status::ErrFloor);
    };
    if unit == 99 {
        return Err(Status::ErrBusy);
    }
    let Some(slot) = SLOTS
        .iter()
        .find(|slot| !slot.swap(true, Ordering::Relaxed))
    else {
        return Err(Status::ErrBusy);
    };
    *pport = core::ptr::from_ref(slot).cast_mut().cast();
    let stats = Stats {
        count: unit,
        bytes: 1 << 40,
    };
    if let Some(pstats) = pstats {
        *pstats = stats;
    }
    *generation = 7;
    *pwrap = Wrap {
        inner: stats,
        n: 11,
    };
    Ok(())
}

/// release the port
pub fn destroy_port(hport: ffi::xy_port) -> Result<(), Status> {
    let Some(slot) = SLOTS.iter().find(|slot| core::ptr::eq(*slot, hport.cast())) else {
        return Err(Status::ErrOther);
    };
    if !slot.swap(false, Ordering::Relaxed) {
        std::process::abort(); // released twice: a finalizer firing after an explicit release
    }
    Ok(())
}

/// buf: bytes to send
pub fn send(hport: ffi::xy_port, buf: Option<&[u8]>) -> Result<(), Status> {
    let _ = hport;
    match buf {
        None => Err(Status::ErrUnsupported),
        Some(buf) if buf.len() == 4 => Ok(()),
        Some(_) => Err(Status::ErrBusy),
    }
}

pub fn spend(htoken: ffi::xy_token) -> Result<(), Status> {
    let _ = htoken;
    Ok(())
}

pub fn recv(hport: ffi::xy_port, pdst: Option<&mut [u8]>) -> Result<(), Status> {
    let _ = hport;
    let Some(pdst) = pdst else {
        return Err(Status::ErrUnsupported);
    };
    if pdst.iter().any(|&b| b != 0) {
        return Err(Status::ErrOther);
    }
    pdst.fill(b'r');
    if let Some(third) = pdst.get_mut(2) {
        *third = 0;
    }
    Ok(())
}

pub fn configure(
    hport: ffi::xy_port,
    cfg: Option<&Stats>,
    limit: Option<&u32>,
    mode: ffi::xy_mode,
    who: ffi::xy_token,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(cfg), Some(limit)) = (cfg, limit) else {
        return Err(Status::ErrFloor);
    };
    let Ok(mode) = Mode::try_from(mode) else {
        return Err(Status::ErrAgain);
    };
    if cfg.count == 5 && *limit == 6 && mode == Mode::Slow && who == token() {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

pub fn stats_of(
    hport: ffi::xy_port,
    out: Option<&mut Stats>,
    pcount: Option<&mut u32>,
    plink: Option<&mut ffi::xy_link>,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(out), Some(pcount), Some(plink)) = (out, pcount, plink) else {
        return Err(Status::ErrFloor);
    };
    out.count = 42;
    *pcount = 43;
    *plink = link();
    Ok(())
}

/// level + 1, tally.count * 2, each byte of data + 1
pub fn bump(
    hport: ffi::xy_port,
    level: Option<&mut u32>,
    tally: Option<&mut Stats>,
    data: Option<&mut [u8]>,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(level), Some(tally)) = (level, tally) else {
        return Err(Status::ErrFloor);
    };
    let Some(data) = data else {
        return Err(Status::ErrUnsupported);
    };
    *level = level.wrapping_add(1);
    tally.count = tally.count.wrapping_mul(2);
    for b in data {
        *b = b.wrapping_add(1);
    }
    Ok(())
}

pub fn open_link(plink: Option<&mut ffi::xy_link>) -> Result<(), Status> {
    let Some(plink) = plink else {
        return Err(Status::ErrFloor);
    };
    *plink = link();
    Ok(())
}

/// ok for a non-null link and port, else err_other
pub fn attach(hlink: ffi::xy_link, hport: ffi::xy_port) -> Result<(), Status> {
    if hlink.is_null() || hport.is_null() {
        Err(Status::ErrOther)
    } else {
        Ok(())
    }
}

/// ptoken = a token the library holds
pub fn mint(ptoken: Option<&mut ffi::xy_token>) -> Result<(), Status> {
    let Some(ptoken) = ptoken else {
        return Err(Status::ErrFloor);
    };
    *ptoken = token();
    Ok(())
}

/// ok iff note is absent or note.count == 7
pub fn annotate(hport: ffi::xy_port, note: Option<&Stats>) -> Result<(), Status> {
    let _ = hport;
    if note.is_none_or(|note| note.count == 7) {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

pub fn reset() -> Result<(), Status> {
    Ok(())
}

/// ok for 1 << 40; ok for 98 where the last batch-98 stream received an answer other than go, else err_again; for 96 during a batch-95 or batch-96 stream, calls that stream's sink once with empty views and answers ok; for 95, ok where the last batch-95 stream's first call was answered other than go, else err_again (the C++ fake only)
pub fn seek(hport: ffi::xy_port, offset: u64) -> Result<(), Status> {
    let _ = hport;
    match offset {
        u64::MAX => panic!("fake seek: offset u64::MAX"),
        12345 => Err(Status::ErrUnsupported),
        98 if STREAM_STOPS.load(Ordering::Relaxed) != 0 => Ok(()),
        98 => Err(Status::ErrAgain),
        96 if !ACTIVE.get().is_null() => {
            // SAFETY: ACTIVE holds the sink of the batch-96 stream running on this thread, alive
            // until that stream returns; a call reads only its callback and user_data.
            let _answer = unsafe { (*ACTIVE.get()).call(&[], &[], &[], 0) };
            Ok(())
        }
        0x100_0000_0000 => Ok(()),
        _ => Err(Status::ErrBusy),
    }
}

/// pnext = big - 1, pdelta = delta - 1; ok iff delta == -3, big == -(1 << 40), small == 200, scale == 0.5
pub fn tune(
    hport: ffi::xy_port,
    delta: i32,
    big: i64,
    small: u8,
    scale: f64,
    pnext: Option<&mut i64>,
    pdelta: Option<&mut i32>,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(pnext), Some(pdelta)) = (pnext, pdelta) else {
        return Err(Status::ErrFloor);
    };
    *pnext = big.wrapping_sub(1);
    *pdelta = delta.wrapping_sub(1);
    if delta == -3 && big == -(1 << 40) && small == 200 && scale == 0.5 {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

/// pmode = slow, level + 1 and ppeek = 9 where given; ok iff payload is absent or 2 bytes and limit is absent or 3
pub fn probe(
    hport: ffi::xy_port,
    pmode: Option<&mut ffi::xy_mode>,
    payload: Option<&[u8]>,
    limit: Option<&u32>,
    level: Option<&mut u32>,
    ppeek: Option<&mut u32>,
) -> Result<(), Status> {
    let _ = hport;
    if let Some(pmode) = pmode {
        *pmode = ffi::XY_SLOW;
    }
    if let Some(level) = level {
        *level = level.wrapping_add(1);
    }
    if let Some(ppeek) = ppeek {
        *ppeek = 9;
    }
    if payload.is_none_or(|payload| payload.len() == 2) && limit.is_none_or(|&limit| limit == 3) {
        Ok(())
    } else {
        Err(Status::ErrBusy)
    }
}

/// ppos = pos
pub fn echo_offset(
    hport: ffi::xy_port,
    pos: Offset,
    ppos: Option<&mut Offset>,
) -> Result<(), Status> {
    let _ = hport;
    let Some(ppos) = ppos else {
        return Err(Status::ErrFloor);
    };
    *ppos = pos;
    Ok(())
}

/// entries e0..e2 (id 10 + i, label 'e<i>' at 2i) and their labels' arena 'e0e1e2', each as much as its buffer holds; lies at items capacity 4 (wrote 5, needed 9) and 6 (wrote 4), and at labels capacity 5 (wrote 7)
pub fn list(
    hport: ffi::xy_port,
    items: Option<&mut [Entry]>,
    items_wrote: Option<&mut u64>,
    items_needed: Option<&mut u64>,
    labels: Option<&mut [u8]>,
    labels_wrote: Option<&mut u32>,
    labels_needed: Option<&mut u32>,
) -> Result<(), Status> {
    const ARENA: &[u8] = b"e0e1e2";
    const ENTRIES: u32 = 3;
    let _ = hport;
    let (Some(items), Some(labels)) = (items, labels) else {
        return Err(Status::ErrUnsupported);
    };
    let (Some(items_wrote), Some(items_needed), Some(labels_wrote), Some(labels_needed)) =
        (items_wrote, items_needed, labels_wrote, labels_needed)
    else {
        return Err(Status::ErrFloor);
    };
    if items.iter().any(|e| *e != Entry::default()) || labels.iter().any(|&b| b != 0) {
        return Err(Status::ErrOther);
    }
    let capacity = items.len();
    for (item, i) in items.iter_mut().zip(0..ENTRIES) {
        *item = Entry {
            id: 10 + i,
            label: Text {
                offset: 2 * i,
                length: 2,
            },
        };
    }
    *items_wrote = match capacity {
        4 => 5,
        6 => 4,
        _ => capacity.min(ENTRIES as usize) as u64,
    };
    *items_needed = if capacity == 4 { 9 } else { u64::from(ENTRIES) };
    let bytes = labels.len().min(ARENA.len());
    labels[..bytes].copy_from_slice(&ARENA[..bytes]);
    *labels_wrote = if labels.len() == 5 {
        7
    } else {
        u32::try_from(bytes).map_err(|_| Status::ErrOther)?
    };
    *labels_needed = u32::try_from(ARENA.len()).map_err(|_| Status::ErrOther)?;
    Ok(())
}

/// entries e0..e6 (id 10 + i, label 'e<i>' at 2i) to sink: a batch when it holds batch entries (0: never) or a cut ends it, then a final call with the remainder, possibly empty; a sink answer other than go stops it with err_again; batch 99 calls sink from another thread (the C++ fake only); batch 98 delivers batches of 1 whatever the sink answers, err_again where any answer was not go; batch 97 (the C++ fake only) passes a null fresh with a count of 1 on its first call; batch 96 lets seek(96) on any port call the sink again while it runs; batch 94 (built for wasm) calls the Node binding's callback with a user_data no frame names, err_again where it answered halt; batch 95 (the C++ fake only) lets seek(96) call the sink again as batch 96 does and delivers batches of 1 whatever the sink answers, err_again where any answer was not go
pub fn stream(
    hport: ffi::xy_port,
    batch: u32,
    cuts: Option<&[ffi::xy_cut]>,
    sink: Option<OnBatch<'_>>,
) -> Result<(), Status> {
    const ARENA: &[u8] = b"e0e1e2e3e4e5e6";
    let _ = hport;
    let Some(mut sink) = sink else {
        return Err(Status::ErrFloor);
    };
    let Some(cuts) = cuts else {
        return Err(Status::ErrUnsupported);
    };
    if matches!(batch, 95 | 97 | 99) {
        return Err(Status::ErrUnsupported);
    }
    #[cfg(target_family = "wasm")]
    if batch == 94 {
        return foreign_user_data();
    }
    let ignore_answers = batch == 98;
    let _active = (batch == 96).then(|| {
        ACTIVE.set(core::ptr::from_mut(&mut sink).cast());
        Active
    });
    let batch = if ignore_answers || batch == 96 { 1 } else { batch };
    if ignore_answers {
        STREAM_STOPS.store(0, Ordering::Relaxed);
    }
    // whether the stream goes on after the sink answered `answer`
    let goes_on = |answer: ffi::xy_flow| {
        if ignore_answers {
            STREAM_STOPS.fetch_add(u32::from(answer != ffi::XY_GO), Ordering::Relaxed);
            return true;
        }
        answer == ffi::XY_GO
    };
    let entries: [Entry; 7] = core::array::from_fn(|i| {
        let i = u32::try_from(i).unwrap_or_default();
        Entry {
            id: 10 + i,
            label: Text {
                offset: 2 * i,
                length: 2,
            },
        }
    });
    let mut start = 0;
    for end in 1..=entries.len() {
        let full = batch != 0 && u32::try_from(end - start) == Ok(batch);
        let cut = cuts.iter().any(|&c| usize::try_from(c) == Ok(end - 1));
        if full || cut {
            if !goes_on(sink.call(&entries[..end], &entries[start..end], &ARENA[..2 * end], 0)) {
                return Err(Status::ErrAgain);
            }
            start = end;
        }
    }
    let go = goes_on(sink.call(&entries, &entries[start..], ARENA, 1));
    if go && !(ignore_answers && STREAM_STOPS.load(Ordering::Relaxed) != 0) {
        Ok(())
    } else {
        Err(Status::ErrAgain)
    }
}

// stream's batch 94 built for wasm: the shim's callback, which the Node binding passes as the
// sink, called with a user_data no frame of the binding names; err_again where it answered halt.
#[cfg(target_family = "wasm")]
fn foreign_user_data() -> Result<(), Status> {
    let Some(callback) = abi::xy__address_on_batch() else {
        return Err(Status::ErrFloor);
    };
    // SAFETY: the binding's callback reads no view where its user_data names no frame.
    let answer = unsafe {
        callback(
            core::ptr::null(),
            0,
            core::ptr::null(),
            0,
            core::ptr::null(),
            0,
            1,
            core::ptr::null_mut(),
        )
    };
    if answer == ffi::XY_HALT {
        Err(Status::ErrAgain)
    } else {
        Err(Status::ErrOther)
    }
}

/// notes n0..n5 to sink, batch of them a call (0: all six in one), the last call holding the remainder; a sink answer other than go stops it with err_again; a batch above 6 is err_unsupported
pub fn stream_notes(
    hport: ffi::xy_port,
    batch: u32,
    sink: Option<OnNotes<'_>>,
) -> Result<(), Status> {
    // kind and size 0: push sets them
    const fn head(at: u32) -> NoteHead {
        NoteHead {
            kind: 0,
            size: 0,
            at,
        }
    }
    const fn line(at: u32, offset: u32, length: u32) -> NoteLine {
        NoteLine {
            head: head(at),
            label: Text { offset, length },
        }
    }
    const fn mark(at: u32, value: i32, flag: u32) -> NoteMark {
        NoteMark {
            head: head(at),
            value,
            flag,
        }
    }
    const NOTES: [NoteRef<'static>; 6] = [
        NoteRef::Line(&line(0, 0, 2)),
        NoteRef::Mark(&mark(1, -1, 1)),
        NoteRef::Line(&line(2, 2, 3)),
        NoteRef::Mark(&mark(3, i32::MAX, 0)),
        NoteRef::Mark(&mark(4, i32::MIN, u32::MAX)),
        NoteRef::Line(&line(5, 5, 0)),
    ];
    let _ = hport;
    let mut sink = sink.ok_or(Status::ErrFloor)?;
    let batch = match usize::try_from(batch) {
        Ok(0) => NOTES.len(),
        Ok(batch) if batch <= NOTES.len() => batch,
        _ => return Err(Status::ErrUnsupported),
    };
    let mut buf = NoteBuf::new();
    for notes in NOTES.chunks(batch) {
        let mark = buf.mark();
        for note in notes {
            match note {
                NoteRef::Line(note) => buf.push_line(note),
                NoteRef::Mark(note) => buf.push_mark(note),
            }
        }
        if sink.call(buf.view(), buf.tail(mark)) != ffi::XY_GO {
            return Err(Status::ErrAgain);
        }
    }
    Ok(())
}

/// calls first with sent as the mode, then second, whatever either answers; err_again where either answered other than go
pub fn notify(
    hport: ffi::xy_port,
    sent: u32,
    first: Option<OnMode<'_>>,
    second: Option<OnMode<'_>>,
) -> Result<(), Status> {
    let _ = hport;
    let (Some(mut first), Some(mut second)) = (first, second) else {
        return Err(Status::ErrFloor);
    };
    let (a, b) = (first.call(sent), second.call(sent));
    if a == ffi::XY_GO && b == ffi::XY_GO {
        Ok(())
    } else {
        Err(Status::ErrAgain)
    }
}
