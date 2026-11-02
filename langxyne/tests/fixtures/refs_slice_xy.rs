// Built beside support.REFS's Rust binding, run against REFS's Rust stub: a slice of 255 bytes is
// sent through a u8 count, and one of 256 panics. Exit 0 where both hold.
#[allow(dead_code)]
mod xy_api;

fn main() -> std::process::ExitCode {
    let port = xy_api::Port::create(1).expect("the stub returns the zero entry");
    if port.send_short(&[0; 255]) != Ok(()) {
        return 1.into();
    }
    if std::panic::catch_unwind(|| port.send_short(&[0; 256])).is_ok() {
        return 2.into();
    }
    0.into()
}
