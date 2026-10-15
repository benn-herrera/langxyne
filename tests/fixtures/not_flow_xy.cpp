// Over support.KITCHEN_SINK's C++ wrapper, which must refuse it: stream's callable answers a bool,
// not xy::Flow.
#include "xy_api.hpp"

int main() {
  xy::Port port = xy::Port::create(3);
  return int(port.stream(0, nullptr, 0, [](auto...) { return true; }));
}
