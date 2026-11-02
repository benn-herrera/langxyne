    // destroy_port's body in support.REFS's stub, for refs_notes_library(): each port it is
    // handed reported on stderr, so a caller sees a binding release one
    if !hport.is_null() {
        eprintln!("destroy_port released a port");
    }
