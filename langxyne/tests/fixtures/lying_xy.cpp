// A consumer of support.KITCHEN_SINK's C++ wrapper for what only the C++ fake does, run against it.
// With `nested`: stream(96)'s callable calls seek(96) on another port, during which the library calls
// the sink again; that invocation is answered stop without reaching the callable, so the callable runs
// once and stream answers ERR_AGAIN; then the same over stream(95), whose library goes on calling the
// sink after that failure was recorded, every later call answered stop without reaching the callable:
// exit 0, else 1. With `off_thread`: stream(99), whose sink the
// library calls from a thread of its own, which aborts the process; returning at all exits 4.
// Exit 2 is a usage error, 3 a port the fake did not open.
#include "xy_api.hpp"

#include <cstdint>
#include <cstring>
#include <initializer_list>

int main(int argc, char** argv) {
  if (argc != 2) {
    return 2;
  }
  xy::Port p = xy::Port::create(1);
  xy::Port q = xy::Port::create(2);
  if (!p || !q) {
    return 3;
  }
  if (std::strcmp(argv[1], "nested") == 0) {
    for (const uint32_t batch : {96u, 95u}) {
      int runs = 0;
      const xy::Status result = p.stream(batch, nullptr, 0, [&](auto...) {
        ++runs;
        (void)q.seek(96);
        return xy::Flow::Go;
      });
      if (result != xy::Status::ErrAgain || runs != 1) {
        return 1;
      }
    }
    return 0;
  }
  if (std::strcmp(argv[1], "off_thread") == 0) {
    (void)p.stream(99, nullptr, 0, [](auto...) { return xy::Flow::Go; });
    return 4;
  }
  return 2;
}
