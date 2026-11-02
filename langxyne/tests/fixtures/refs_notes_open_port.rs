    // open_port's body in support.REFS's stub, for refs_notes_library(): a non-null handle, and
    // for unit 7 a generation no Mode entry names, which a binding's constructor refuses
    static PORT: u8 = 0;
    if let Some(p) = pport {
        *p = core::ptr::from_ref(&PORT).cast_mut().cast();
    }
    let _ = pstats;
    if let (7, Some(g)) = (unit, generation) {
        *g = 7;
    }
