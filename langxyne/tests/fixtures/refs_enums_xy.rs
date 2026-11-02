// Built beside support.REFS's Rust binding, run against REFS's Rust stub, which writes nothing:
// each enum reached through `in` or `inout` travels to C and back unchanged, and each `out`, the
// cached one included, comes back as the relay's default, the zero entry. Exit 0 where it does.
#[allow(dead_code)]
mod xy_api;
use xy_api::{Mode, Port};

fn main() -> std::process::ExitCode {
    let port = Port::create(1).expect("the stub returns the zero entry");
    if port.generation() != Mode::Fine {
        return 1.into();
    }
    let (mut cur, mut seen, mut last) = (Mode::Slow, Mode::Slow, Mode::Slow);
    let steered = port.steer(&Mode::Slow, &mut cur, Some(&Mode::Slow), Some(&mut seen), Some(&mut last));
    if steered != Ok(()) || [cur, seen, last] != [Mode::Slow, Mode::Slow, Mode::Fine] {
        return 2.into();
    }
    if port.steer(&Mode::Fine, &mut cur, None, None, None) != Ok(()) || cur != Mode::Slow {
        return 3.into();
    }
    0.into()
}
