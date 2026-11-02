// Over the header and wrapper of support.KITCHEN_SINK with its u32 bit group's flag at bit 31 and a
// conversion: both carry the flag, and the conversion names it. Exit 0 where it does.
#include "xy_api.hpp"

static_assert(XY_FEAT_ONE == 0x80000000u);
static_assert(xy::FEAT_ALL == 0x80000008u);

int main() {
  return xy::wide_to_string(xy::FEAT_ALL) == "FEAT_ONE|0x8" ? 0 : 1;
}
