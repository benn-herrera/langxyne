# ROADMAP – langxyne

Forthcoming developments

## Additional emitters
- Swift
- JVM languages via FFI (not JNI)

## Bindings
- The Node binding refuses 64-bit types, which cross wasm as `BigInt`, and a struct field of opaque type; a definition holding either is generated without `node`.
- The Lua module loads its library by name, through the platform's search; it should load from a fixed path as the Python module does.
- A Go object the consumer never releases leaks: a finalizer would run the dtor on the runtime's finalizer goroutine, on a thread the consumer never chose, and would need `runtime.KeepAlive` after every call. Go 1.24's `runtime.AddCleanup` is the candidate once the binding's floor allows it.

## Definition language
- Buffers beyond `in` and `out` arrays of builtins, boxed scalars and structs and a function's `in` arrays of enums: `inout` arrays, arrays of opaque elements, and enum arrays the library writes (an `out` array or a callback's view), each refused as not implemented today; and a text type wider than `u32` offsets and lengths, which bound one arena at 4 GiB.
- A callback a handle holds past the call that passes it, refused today: a class-lifetime design in every binding, and in Go cgo's rule that C keeps no Go pointer past the call unless it is pinned.

## Platforms
- Windows DLL export in the C header: `NS_API` under `NS_IMPL` marks visibility with `__attribute__((visibility("default")))`, which MSVC rejects; a C or C++ implementation built on Windows needs `__declspec(dllexport)` there.
