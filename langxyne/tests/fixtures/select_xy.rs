// Built beside support.KITCHEN_SINK's Rust binding: seek(12345), which the C++ fake answers with
// a result the enum does not name, so the binding panics, and the Rust fake with ErrUnsupported.
#[allow(dead_code)]
mod xy_api;

fn main() {
    let port = xy_api::Port::create(3).expect("either fake opens unit 3");
    let _ = port.seek(12345);
}
