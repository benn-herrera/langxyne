    // note's body in support.REFS's stub, for refs_notes_library(): ok only for the notes
    // (count, bytes) (1, 2), (3, 4) with the spots 1, 2, or for no notes with no spots
    let notes: Option<Vec<(u32, u64)>> = notes.map(|n| n.iter().map(|s| (s.count, s.bytes)).collect());
    let spots: Option<Vec<u64>> = spots.map(|s| s.iter().map(|o| o.0).collect());
    match (notes, spots) {
        (None, Some(s)) if s.is_empty() => Ok(()),
        (Some(n), Some(s)) if n == [(1, 2), (3, 4)] && s == [1, 2] => Ok(()),
        _ => Err(Status::ErrBusy),
    }
