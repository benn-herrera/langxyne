// Built beside support.KITCHEN_SINK's Rust binding, which must refuse it: a record of the view
// stream_notes lends its closure kept past the call.
#[allow(dead_code)]
mod xy_api;

fn main() {
    let port = xy_api::Port::create(3).expect("either fake opens unit 3");
    let mut kept = Vec::new();
    let _ = port.stream_notes(1, |seen, _| {
        kept.extend(seen.records().flatten());
        xy_api::Flow::Go
    });
    drop(kept);
}
