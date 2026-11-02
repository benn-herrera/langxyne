// xy_notify of fake_xy.cpp's library, in C: it passes a mode no xy_mode entry names, which a C enum
// holds as the integer type it is compatible with does, where converting it to that unscoped enum in
// C++ would be undefined. Built and linked beside fake_xy.cpp.
#define XY_IMPL
#include "xy_api.h"
#undef XY_IMPL

#include <stddef.h>

XY_API xy_status xy_notify(xy_port hport, uint32_t sent, xy_on_mode first, void* first_user_data, xy_on_mode second,
                           void* second_user_data) {
  (void)hport;
  if (first == NULL || second == NULL) {
    return XY_ERR_FLOOR;
  }
  const xy_mode mode = sent;
  const xy_flow a = first(mode, first_user_data);
  const xy_flow b = second(mode, second_user_data);
  return a == XY_GO && b == XY_GO ? XY_OK : XY_ERR_AGAIN;
}
