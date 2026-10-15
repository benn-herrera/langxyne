    // observe's body in support.REFS's stub, for refs_notes_library(): sink called once with the
    // spots 1, 2, an empty blob and Mode::Fine, through the relay's wrapper
    let Some(mut sink) = sink else {
        return Err(Status::ErrBusy);
    };
    let _ = sink.call(&[Offset(1), Offset(2)], &[], ffi::XY_FINE);
    Ok(())
