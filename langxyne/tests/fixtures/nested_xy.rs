// Built beside support.KITCHEN_SINK's Rust binding, run under the C++ fake, whose seek(96) calls
// the running batch-96 stream's sink again, on any port: the nested invocation is answered stop
// and resurfaces as the stream's panic, the closure having run once. Exit 0 where it does.
#[allow(dead_code)]
mod xy_api;

fn main() -> std::process::ExitCode {
    let p = xy_api::Port::create(1).expect("the C++ fake opens unit 1");
    let q = xy_api::Port::create(2).expect("the C++ fake opens unit 2");
    let mut runs = 0;
    let streamed = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        p.stream(96, &[], |_, _, _, _| {
            runs += 1;
            let _ = q.seek(96);
            xy_api::Flow::Go
        })
    }));
    let Err(payload) = streamed else {
        return 1.into();
    };
    let message = payload.downcast_ref::<String>().map_or("", String::as_str);
    if runs != 1 || !message.contains("xy_on_batch called again while a call of it was running in xy_stream") {
        return 2.into();
    }
    0.into()
}
