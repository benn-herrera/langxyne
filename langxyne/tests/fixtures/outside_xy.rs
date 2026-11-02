// Built beside support.KITCHEN_SINK's Rust binding, run under the C++ fake, which passes
// stream(97, ...)'s first call a null fresh with a count of 1: the binding panics naming it.
#[allow(dead_code)]
mod xy_api;

fn main() {
    let port = xy_api::Port::create(3).expect("the C++ fake opens unit 3");
    let _ = port.stream(97, &[], |_, _, _, _| xy_api::Flow::Go);
}
