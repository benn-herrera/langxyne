// Over support.KITCHEN_SINK's C++ wrapper, which must refuse it: as<T> of a note record with a T,
// the note's own prefix, that is not a member of union note.
#include "xy_api.hpp"

int main() {
  const xy::NoteHead head{};
  return xy::as<xy::NoteHead>(head) != nullptr;
}
