// Built beside support.KITCHEN_SINK's Rust binding: stream(99, ...), whose sink the C++ fake calls
// from a thread of its own, so the binding aborts.
#[allow(dead_code)]
mod xy_api;

fn main() {
    let port = xy_api::Port::create(3).expect("the C++ fake opens unit 3");
    let _ = port.stream(99, &[], |_, _, _, _| xy_api::Flow::Go);
}
