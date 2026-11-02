// Built beside support.KITCHEN_SINK's Rust binding, which must refuse it: the port released inside
// the closure its own stream borrows.
#[allow(dead_code)]
mod xy_api;

fn main() {
    let port = xy_api::Port::create(3).expect("either fake opens unit 3");
    let _ = port.stream(1, &[], |_, _, _, _| {
        let _ = port.release();
        xy_api::Flow::Go
    });
}
