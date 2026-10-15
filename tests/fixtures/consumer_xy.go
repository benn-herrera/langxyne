// A consumer of support.KITCHEN_SINK's Go binding, the package xy_api of its module, run against
// either fake and over the static archive. consumer_xy.rs's steps, in its order and with its codes.
// Exit codes: 0 all steps passed; 1 NewPort(99) failure result; 2 NewPort(3) and its cached out
// parameters; 3 Send; 4 Recv; 5 Configure with Mint's token, which Spend takes, and with the null
// TokenHandle, a panic naming who; 6 StatsOf; 9 Release, after which a method panics naming
// destroy_port and a second Release reaches the library as the null handle; 10 every released
// object freed its slot; 11 Product; 12 NewDataLink; 13 Bump; 14 Seek and Tune; 15 Annotate (an
// _optional struct in parameter); 16 the _to_string conversions; 17 Probe (an enum out parameter as
// the enum, _optional memory in, scalar in, inout and out parameters); 18 EchoOffset (a boxed scalar
// by value and out); 20 an empty non-nil optional slice reaches the library as a present, zero-length
// payload; List, by capacity (items, labels), as consumer_xy.rs: 21 (0, 0) succeeds reporting
// nothing written and what is needed; 22 (1, 2) entry 0 and its label; 23 (2, 3) entry 1's label
// leaves the arena written, so Resolve is false; 24 (3, 6) every label resolves; 25 (5, 8) the prefix
// written and what is needed; 26 (4, 6) a wrote above the capacity alone, 27 (6, 6) a wrote above the
// need alone, 28 (3, 5) a wrote above a byte buffer's capacity: each panics naming xy_list and the
// buffer. Stream, as consumer_xy.rs: 30 to 37; 38 a func panicking on its second call: Stream panics
// with the func's own value, the func having run exactly twice; 39 Stream with a nil func panics
// naming sink before any C call. 40 inside Stream(1)'s func, Seek(1 << 40) on the same port answers
// StatusErrBusy without reaching the library, and the stream answers nil; 41 inside it, Release
// answers StatusErrBusy, and Send succeeds after the stream; 42 Notify(1) calls each func once with
// ModeSlow and answers nil; 43 Notify(1) whose first func panics: second never runs, and the panic
// resumes with first's value, first having run once; 44 Notify(7): a panic naming xy_on_mode and mode
// resumes, and neither func ran; 45 Stream(98), whose library calls the sink eight times whatever it
// answers, with a func panicking on its second call and then on its eighth: each runs up to that
// call only, its panic resumes, and Seek(98) then answers nil, the library having seen a stop; 48
// inside Stream(1)'s func, Attach(port) on a DataLink answers StatusErrBusy without reaching the
// library, and answers nil after the stream; 49 after the port's Release, Attach(port) panics naming
// hport is a Port used after destroy_port, and Attach(nil) naming hport is nil; 50 the state a
// Stream(0) func captured is finalized once the call returns, its cgo.Handle deleted.
// With an argument, one step for run-bindings.sh alone: "select", Seek(12345); "nested", under the
// C++ fake, Stream(96)'s func calling Seek(96) on a second port, during which the library calls the
// sink again: answered stop without reaching the func, the stream panics naming the nested call;
// "nested95", under the C++ fake, the same through Stream(95), whose library goes on calling the
// sink: the func ran once, and Seek(95) answers nil, the library having seen its first call answered
// stop; "foreign", under the C++ fake, Stream(94), whose library passes the sink a null user_data;
// "outside", under the C++ fake, Stream(97), whose library passes a null view with a count of 1.
// "notes", against either fake: StreamNotes for batch 2, 4 and 0, each view walked by Walk and Next
// and each record printed after a type switch over NoteRecord; nothing of a view is kept past its
// func but offsets and text. Exit codes: 50 a stream did not answer nil after calls of 2, 2, 2 notes
// (of 4, 2; of 6), or a view's walk did not meet its count (the refusal on stderr); 51 at each call
// fresh's bytes are seen's last by identity, seen counts the earlier calls' records and fresh's, and
// seen's records are every earlier call's fresh records then this call's; 52 every offset recorded
// so far resolves through seen's At to its record, and each of fresh's through fresh's At, each
// offset in units of the list's alignment; 53 seen's At of byte 4, inside n0, is the *UnionError "record 1 at offset 4: offset is not a record's start",
// and seen.At of its extent the same clause at the record after the last. Its stdout is the batch-2
// stream's records, one line each, as consumer_xy.cpp writes them.
// "notes <selector>", 101 to 105, against the C++ fake alone: the stream's second call is refused
// in both views, each refusal on stderr as `xy_on_notes: <view>: record <i> at offset <o>:
// <clause>`, the func answering FlowHalt, and the process exits with the selector; 100 where the
// selector is not a decimal number below 256, no view was refused, the stream did not answer
// StatusErrAgain, or seen's refusal is not fresh's past the earlier records.
// "notes 106", against the C++ fake alone: seen's At of byte 16, the record past seen's count, is
// refused, on stderr as `xy_on_notes: seen: <refusal>`, the func answering FlowHalt, and the
// process exits 106; 100 where At did not refuse or the stream did not answer StatusErrAgain.
package main

import (
	"errors"
	"fmt"
	"os"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"time"

	"xy_consumer/xy_api"
)

// What Stream's sink saw: each call's (seen, fresh, last) counts, and whether every view held what
// the fakes promise.
type streamed struct {
	err   error
	calls [][3]int
	views bool
}

// Whether the calls' fresh counts are `fresh`, seen counting them up, the last one alone final where
// `last`.
func (s streamed) is(fresh []int, last bool) bool {
	if len(s.calls) != len(fresh) {
		return false
	}
	seen := 0
	for i, count := range fresh {
		seen += count
		final := 0
		if last && i == len(fresh)-1 {
			final = 1
		}
		if s.calls[i] != [3]int{seen, count, final} {
			return false
		}
	}
	return true
}

// stream(batch, cuts), its sink answering halt on call `haltOn` (0: never).
func stream(port *xy_api.Port, batch uint32, cuts []xy_api.Cut, haltOn int) streamed {
	s := streamed{views: true}
	s.err = port.Stream(batch, cuts, func(seen, fresh []xy_api.Entry, arena []byte, last uint32) xy_api.Flow {
		s.calls = append(s.calls, [3]int{len(seen), len(fresh), int(last)})
		for i, e := range fresh {
			s.views = s.views && e.Id == seen[len(seen)-len(fresh)+i].Id
		}
		for i, e := range seen {
			// a resolved label ends at its own length, so no append writes into the arena
			label, ok := e.Label.Resolve(arena)
			s.views = s.views && ok && string(label) == fmt.Sprintf("e%d", i) && cap(label) == len(label)
		}
		_, ok := xy_api.Text{Offset: uint32(len(arena)), Length: 2}.Resolve(arena)
		s.views = s.views && !ok
		if len(s.calls) == haltOn {
			return xy_api.FlowHalt
		}
		return xy_api.FlowGo
	})
	return s
}

// The text of what `f` panicked with, "" where it returned.
func panicked(f func()) (message string) {
	defer func() {
		if v := recover(); v != nil {
			message = fmt.Sprint(v)
		}
	}()
	f()
	return ""
}

func run() int {
	if _, err := xy_api.NewPort(99); err != xy_api.StatusErrBusy || err.Error() != "ERR_BUSY" {
		return 1
	}

	port, err := xy_api.NewPort(3)
	if err != nil || port.Pstats().Count != 3 || port.Generation() != 7 || port.Pwrap().N != 11 {
		return 2
	}

	buf := []byte("abcd")
	if port.Send(buf) != nil || port.Send(buf[:3]) != xy_api.StatusErrBusy {
		return 3
	}

	out := make([]byte, 5)
	if port.Recv(out) != nil || out[2] != 0 {
		return 4
	}

	tok, err := xy_api.Mint()
	if err != nil || port.Configure(xy_api.Stats{Count: 5}, 6, xy_api.ModeSlow, tok) != nil || xy_api.Spend(tok) != nil ||
		!strings.Contains(panicked(func() { _ = port.Configure(xy_api.Stats{Count: 5}, 6, xy_api.ModeSlow, xy_api.TokenHandle{}) }),
			"who is a null TokenHandle") {
		return 5
	}

	if st, c, l, err := port.StatsOf(); err != nil || st.Count != 42 || c != 43 || l == (xy_api.LinkHandle{}) {
		return 6
	}

	level, tally, data := uint32(4), xy_api.Stats{Count: 5}, []byte("abc")
	if port.Bump(&level, &tally, data) != nil || level != 5 || tally.Count != 10 || string(data) != "bcd" {
		return 13
	}

	if port.Seek(1<<40) != nil {
		return 14
	}
	if next, delta, err := port.Tune(-3, -(1 << 40), 200, 0.5); err != nil || next != -(1<<40)-1 || delta != -4 {
		return 14
	}

	if port.Annotate(&xy_api.Stats{Count: 7}) != nil || port.Annotate(nil) != nil {
		return 15
	}

	probeLimit, probeLevel, peek := uint32(3), uint32(4), uint32(0)
	if mode, err := port.Probe(nil, nil, nil, nil); err != nil || mode != xy_api.ModeSlow {
		return 17
	}
	if mode, err := port.Probe([]byte("ab"), &probeLimit, &probeLevel, &peek); err != nil || mode != xy_api.ModeSlow ||
		probeLevel != 5 || peek != 9 {
		return 17
	}
	if _, err := port.Probe([]byte("abc"), nil, nil, nil); err != xy_api.StatusErrBusy {
		return 17
	}

	if pos, err := port.EchoOffset(xy_api.Offset(1 << 40)); err != nil || pos != xy_api.Offset(1<<40) {
		return 18
	}

	// []byte{} is a non-null pointer with a count of 0, which the fake refuses as a payload that is
	// present but not 2 bytes; nil, a null pointer, it accepts.
	if _, err := port.Probe([]byte{}, nil, nil, nil); err != xy_api.StatusErrBusy {
		return 20
	}

	items, labels := make([]xy_api.Entry, 8), make([]byte, 8)
	filled := func(wrote, needed int) xy_api.Filled { return xy_api.Filled{Wrote: wrote, Needed: needed} }
	if written, arena, err := port.List(items[:0], labels[:0]); err != nil || written != filled(0, 3) ||
		arena != filled(0, 6) {
		return 21
	}
	written, arena, err := port.List(items[:1], labels[:2])
	if label, ok := items[0].Label.Resolve(labels[:arena.Wrote]); err != nil || written.Wrote != 1 ||
		items[0].Id != 10 || !ok || string(label) != "e0" {
		return 22
	}
	written, arena, err = port.List(items[:2], labels[:3])
	if _, ok := items[1].Label.Resolve(labels[:arena.Wrote]); err != nil || written.Wrote != 2 || items[1].Id != 11 || ok {
		return 23
	}
	_, arena, err = port.List(items[:3], labels[:6])
	for i := 0; i < 3; i++ {
		if label, ok := items[i].Label.Resolve(labels[:arena.Wrote]); err != nil || !ok || string(label) != fmt.Sprintf("e%d", i) {
			return 24
		}
	}
	if written, arena, err := port.List(items[:5], labels); err != nil || written != filled(3, 3) || arena != filled(6, 6) {
		return 25
	}
	for code, lie := range map[int]struct {
		items, labels int
		buffer        string
	}{26: {4, 6, "items"}, 27: {6, 6, "items"}, 28: {3, 5, "labels"}} {
		message := panicked(func() { _, _, _ = port.List(make([]xy_api.Entry, lie.items), make([]byte, lie.labels)) })
		if !strings.Contains(message, "xy_list over-reported "+lie.buffer) {
			return code
		}
	}

	if s := stream(port, 1, nil, 0); !s.is([]int{1, 1, 1, 1, 1, 1, 1, 0}, true) || s.err != nil || !s.views {
		return 30
	}
	if s := stream(port, 3, nil, 0); !s.is([]int{3, 3, 1}, true) || s.err != nil {
		return 31
	}
	if s := stream(port, 0, nil, 0); !s.is([]int{7}, true) || s.err != nil {
		return 32
	}
	if s := stream(port, 3, []xy_api.Cut{xy_api.CutAfterOne, xy_api.CutAfterFour}, 0); !s.is([]int{2, 3, 2}, true) || s.err != nil {
		return 33
	}
	if s := stream(port, 0, []xy_api.Cut{xy_api.CutAfterFour}, 0); !s.is([]int{5, 2}, true) || s.err != nil {
		return 34
	}
	if s := stream(port, 1, nil, 3); !s.is([]int{1, 1, 1}, false) || s.err != xy_api.StatusErrAgain {
		return 35
	}
	if s := stream(port, 3, nil, 1); !s.is([]int{3}, false) || s.err != xy_api.StatusErrAgain {
		return 36
	}
	if s := stream(port, 3, []xy_api.Cut{}, 0); !s.views || len(s.calls) != 3 {
		return 37
	}
	runs := 0
	message := panicked(func() {
		_ = port.Stream(1, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
			runs++
			if runs == 2 {
				panic("the consumer's sink panics on its second call")
			}
			return xy_api.FlowGo
		})
	})
	if runs != 2 || message != "the consumer's sink panics on its second call" {
		return 38
	}
	if message := panicked(func() { _ = port.Stream(1, nil, nil) }); !strings.Contains(message, "sink") {
		return 39
	}

	var refused error = xy_api.StatusOk
	if err := port.Stream(1, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
		if refused == xy_api.StatusOk {
			refused = port.Seek(1 << 40)
		}
		return xy_api.FlowGo
	}); err != nil || refused != xy_api.StatusErrBusy {
		return 40
	}
	refused = xy_api.StatusOk
	if err := port.Stream(1, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
		if refused == xy_api.StatusOk {
			refused = port.Release()
		}
		return xy_api.FlowGo
	}); err != nil || refused != xy_api.StatusErrBusy || port.Send(buf) != nil {
		return 41
	}
	link, err := xy_api.NewDataLink()
	if err != nil {
		return 48
	}
	refused = xy_api.StatusOk
	if err := port.Stream(1, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
		if refused == xy_api.StatusOk {
			refused = link.Attach(port)
		}
		return xy_api.FlowGo
	}); err != nil || refused != xy_api.StatusErrBusy || link.Attach(port) != nil {
		return 48
	}

	// a func whose captured state is collected once Stream returns: its cgo.Handle was deleted
	collected := make(chan struct{}, 1)
	func() {
		state := &struct{ calls int }{}
		runtime.SetFinalizer(state, func(*struct{ calls int }) { collected <- struct{}{} })
		_ = port.Stream(0, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
			state.calls++
			return xy_api.FlowGo
		})
	}()
	finalized := false
	for round := 0; round < 100 && !finalized; round++ {
		runtime.GC()
		select {
		case <-collected:
			finalized = true
		case <-time.After(10 * time.Millisecond):
		}
	}
	if !finalized {
		return 50
	}

	var firsts, seconds []xy_api.Mode
	if err := port.Notify(1, func(mode xy_api.Mode) xy_api.Flow {
		firsts = append(firsts, mode)
		return xy_api.FlowGo
	}, func(mode xy_api.Mode) xy_api.Flow {
		seconds = append(seconds, mode)
		return xy_api.FlowGo
	}); err != nil || len(firsts) != 1 || firsts[0] != xy_api.ModeSlow || len(seconds) != 1 || seconds[0] != xy_api.ModeSlow {
		return 42
	}

	firstRuns, secondRuns := 0, 0
	notify := func(sent uint32, failing bool) string {
		firstRuns, secondRuns = 0, 0
		return panicked(func() {
			_ = port.Notify(sent, func(xy_api.Mode) xy_api.Flow {
				firstRuns++
				if failing {
					panic("the consumer's first callback panics")
				}
				return xy_api.FlowGo
			}, func(xy_api.Mode) xy_api.Flow {
				secondRuns++
				return xy_api.FlowGo
			})
		})
	}
	if message := notify(1, true); firstRuns != 1 || secondRuns != 0 || message != "the consumer's first callback panics" {
		return 43
	}
	if message := notify(7, false); firstRuns != 0 || secondRuns != 0 || !strings.Contains(message, "xy_on_mode") ||
		!strings.Contains(message, "mode") {
		return 44
	}

	// batch 98 calls the sink eight times whatever it answers: a panic on the second call stops the
	// func being called again, and one on the eighth, the last, is still answered stop
	for _, panicking := range []int{2, 8} {
		runs := 0
		message := panicked(func() {
			_ = port.Stream(98, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
				runs++
				if runs == panicking {
					panic("the consumer's sink panics on a call")
				}
				return xy_api.FlowGo
			})
		})
		if runs != panicking || message != "the consumer's sink panics on a call" || port.Seek(98) != nil {
			return 45
		}
	}

	if port.Release() != nil || !strings.Contains(panicked(func() { _ = port.Send(buf) }), "destroy_port") ||
		port.Release() != xy_api.StatusErrOther {
		return 9
	}
	if !strings.Contains(panicked(func() { _ = link.Attach(port) }), "hport is a Port used after destroy_port") ||
		!strings.Contains(panicked(func() { _ = link.Attach(nil) }), "hport is nil") {
		return 49
	}

	var ports []*xy_api.Port
	for unit := uint32(1); unit <= 4; unit++ {
		p, err := xy_api.NewPort(unit)
		if err != nil {
			return 10
		}
		ports = append(ports, p)
	}
	for _, p := range ports {
		if p.Release() != nil {
			return 10
		}
	}
	for unit := uint32(1); unit <= 4; unit++ {
		p, err := xy_api.NewPort(unit)
		if err != nil || p.Release() != nil {
			return 10
		}
	}

	if xy_api.Product != "xy widget" {
		return 11
	}

	if link, err := xy_api.NewDataLink(); err != nil || link.Handle() == (xy_api.LinkHandle{}) {
		return 12
	}

	if xy_api.ModeSlow.String() != "SLOW" || fmt.Sprint(xy_api.StatusErrBusy) != "ERR_BUSY" ||
		xy_api.Status(12345).ToString() != "UNKNOWN_STATUS" || xy_api.AccessToString(3) != "ACC_A|ACC_B" ||
		xy_api.AccessToString(1) != "ACC_A" || xy_api.AccessToString(0) != "NONE" ||
		xy_api.AccessToString(9) != "ACC_A|0x8" || xy_api.AccessToString(-1) != "ACC_A|ACC_B|0xfffffffc" ||
		xy_api.LimitToString(16) != "MAX_UNITS" || xy_api.LimitToString(xy_api.Neg) != "NEG" ||
		xy_api.LimitToString(xy_api.Floor) != "FLOOR" || xy_api.LimitToString(99) != "UNKNOWN" {
		return 16
	}
	return 0
}

// The steps only one fake answers, or whose failure is the process's.
func step(name string) int {
	switch name {
	case "select":
		port, err := xy_api.NewPort(3)
		if err != nil {
			return 1
		}
		_ = port.Seek(12345)
		return 0
	case "nested":
		p, perr := xy_api.NewPort(1)
		q, qerr := xy_api.NewPort(2)
		if perr != nil || qerr != nil {
			return 1
		}
		runs := 0
		message := panicked(func() {
			_ = p.Stream(96, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
				runs++
				_ = q.Seek(96)
				return xy_api.FlowGo
			})
		})
		if runs != 1 || message != "xy_on_batch called again while a call of it was running in xy_stream" {
			return 2
		}
		return 0
	case "nested95":
		p, perr := xy_api.NewPort(1)
		q, qerr := xy_api.NewPort(2)
		if perr != nil || qerr != nil {
			return 1
		}
		runs := 0
		message := panicked(func() {
			_ = p.Stream(95, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow {
				runs++
				if runs == 1 {
					_ = q.Seek(96)
				}
				return xy_api.FlowGo
			})
		})
		if runs != 1 || message != "xy_on_batch called again while a call of it was running in xy_stream" {
			return 2
		}
		// the library saw its first call answered stop, though the func answered go
		if p.Seek(95) != nil {
			return 3
		}
		return 0
	case "foreign":
		port, err := xy_api.NewPort(3)
		if err != nil {
			return 1
		}
		_ = port.Stream(94, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow { return xy_api.FlowGo })
		return 0
	case "outside":
		port, err := xy_api.NewPort(3)
		if err != nil {
			return 1
		}
		_ = port.Stream(97, nil, func([]xy_api.Entry, []xy_api.Entry, []byte, uint32) xy_api.Flow { return xy_api.FlowGo })
		return 0
	case "notes":
		return notes()
	}
	return 1
}

// A record a walk reached: its byte offset from the view's start and its line of the text form.
type note struct {
	offset uint32
	text   string
}

// noteOf is a record's line of the text form and its head; the walker refuses a tag no member has,
// so the switch has no default.
func noteOf(record xy_api.NoteRecord) (string, xy_api.NoteHead) {
	switch r := record.(type) {
	case *xy_api.NoteLine:
		return fmt.Sprintf("line %d %d %d %d %d", r.Head.Kind, r.Head.Size, r.Head.At, r.Label.Offset, r.Label.Length), r.Head
	case *xy_api.NoteMark:
		return fmt.Sprintf("mark %d %d %d %d %d", r.Head.Kind, r.Head.Size, r.Head.At, r.Value, r.Flag), r.Head
	}
	return "", xy_api.NoteHead{}
}

// walkNotes is each record's offset and line, as far as the walk went, and the walker's Err.
func walkNotes(sequence xy_api.NoteSequence) ([]note, error) {
	var notes []note
	offset := uint32(0)
	w := sequence.Walk()
	for r, ok := w.Next(); ok; r, ok = w.Next() {
		text, head := noteOf(r)
		notes = append(notes, note{offset, text})
		offset += uint32(head.Size)
	}
	return notes, w.Err()
}

// refused writes `xy_on_notes: <view>: <refusal>` to stderr where err is a refusal, and says so.
func refused(view string, err error) bool {
	if err != nil {
		fmt.Fprintf(os.Stderr, "xy_on_notes: %s: %v\n", view, err)
	}
	return err != nil
}

// resolves is whether At lands on a record whose line is the note's.
func resolves(sequence xy_api.NoteSequence, n note) bool {
	r, err := sequence.At(n.offset / xy_api.NoteAlign)
	text, _ := noteOf(r)
	return err == nil && text == n.text
}

// notARecordStart is At's refusal of offset as clause 6, "" where At answers otherwise.
func notARecordStart(sequence xy_api.NoteSequence, offset uint32) string {
	var refusal *xy_api.UnionError
	if r, err := sequence.At(offset / xy_api.NoteAlign); r == nil && errors.As(err, &refusal) && refusal.Clause == xy_api.UnionClauseNotARecordStart {
		return refusal.Error()
	}
	return ""
}

// One call of StreamNotes' func, checks 50 to 53: kept holds every record earlier calls delivered,
// at its offset in seen, and gains fresh's; 0 or the failing check.
func checkNotes(seen, fresh xy_api.NoteSequence, kept *[]note) int {
	seenNotes, seenErr := walkNotes(seen)
	freshNotes, freshErr := walkNotes(fresh)
	if refused("seen", seenErr) || refused("fresh", freshErr) {
		return 50
	}
	all, tail := seen.Bytes(), fresh.Bytes()
	if len(tail) > len(all) || (len(tail) > 0 && &tail[0] != &all[len(all)-len(tail)]) ||
		int(seen.Count()) != len(*kept)+int(fresh.Count()) {
		return 51
	}
	before := uint32(len(all) - len(tail))
	for _, n := range freshNotes {
		*kept = append(*kept, note{before + n.offset, n.text})
	}
	if !slices.Equal(seenNotes, *kept) {
		return 51
	}
	for _, n := range *kept {
		if !resolves(seen, n) {
			return 52
		}
	}
	for _, n := range freshNotes {
		if !resolves(fresh, n) {
			return 52
		}
	}
	if notARecordStart(seen, 4) != "record 1 at offset 4: offset is not a record's start" ||
		notARecordStart(seen, uint32(len(all))) !=
			fmt.Sprintf("record %d at offset %d: offset is not a record's start", seen.Count(), len(all)) {
		return 53
	}
	return 0
}

// The "notes" step.
func notes() int {
	port, err := xy_api.NewPort(3)
	if err != nil {
		return 50
	}
	for _, stream := range []struct {
		batch uint32
		calls []uint32
	}{{2, []uint32{2, 2, 2}}, {4, []uint32{4, 2}}, {0, []uint32{6}}} {
		var kept []note
		var freshCounts []uint32
		failed := 0
		err := port.StreamNotes(stream.batch, func(seen, fresh xy_api.NoteSequence) xy_api.Flow {
			freshCounts = append(freshCounts, fresh.Count())
			if failed == 0 {
				failed = checkNotes(seen, fresh, &kept)
			}
			return xy_api.FlowGo
		})
		if failed != 0 {
			return failed
		}
		if err != nil || !slices.Equal(freshCounts, stream.calls) {
			return 50
		}
		if stream.batch == 2 {
			for _, n := range kept {
				fmt.Println(n.text)
			}
		}
	}
	if port.Release() != nil {
		return 50
	}
	return 0
}

// The "notes <selector>" step.
func refusedNotes(arg string) int {
	selector, err := strconv.ParseUint(arg, 10, 8)
	if err != nil {
		return 100
	}
	port, err := xy_api.NewPort(3)
	if err != nil {
		return 100
	}
	var seenErr, freshErr *xy_api.UnionError
	var earlierCount, earlierBytes uint32
	result := port.StreamNotes(uint32(selector), func(seen, fresh xy_api.NoteSequence) xy_api.Flow {
		_, seenWalk := walkNotes(seen)
		_, freshWalk := walkNotes(fresh)
		seenRefused, freshRefused := refused("seen", seenWalk), refused("fresh", freshWalk)
		if !seenRefused && !freshRefused {
			return xy_api.FlowGo
		}
		errors.As(seenWalk, &seenErr)
		errors.As(freshWalk, &freshErr)
		earlierCount = seen.Count() - fresh.Count()
		earlierBytes = uint32(len(seen.Bytes()) - len(fresh.Bytes()))
		return xy_api.FlowHalt
	})
	if port.Release() != nil || result != xy_api.StatusErrAgain || seenErr == nil || freshErr == nil ||
		seenErr.Index != earlierCount+freshErr.Index || seenErr.Offset != earlierBytes+freshErr.Offset ||
		seenErr.Clause != freshErr.Clause {
		return 100
	}
	return int(selector)
}

// The "notes 106" step.
func atPastCount() int {
	port, err := xy_api.NewPort(3)
	if err != nil {
		return 100
	}
	var atErr error
	result := port.StreamNotes(106, func(seen, _ xy_api.NoteSequence) xy_api.Flow {
		_, atErr = seen.At(16 / xy_api.NoteAlign)
		refused("seen", atErr)
		return xy_api.FlowHalt
	})
	if port.Release() != nil || result != xy_api.StatusErrAgain || atErr == nil {
		return 100
	}
	return 106
}

func main() {
	if len(os.Args) == 3 && os.Args[1] == "notes" && os.Args[2] == "106" {
		os.Exit(atPastCount())
	}
	if len(os.Args) == 3 && os.Args[1] == "notes" {
		os.Exit(refusedNotes(os.Args[2]))
	}
	if len(os.Args) > 1 {
		os.Exit(step(os.Args[1]))
	}
	os.Exit(run())
}
