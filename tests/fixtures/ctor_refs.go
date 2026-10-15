// A consumer of support.REFS's Go binding against run-bindings.sh's refs notes fake: NewPort(7),
// whose library writes a generation no Mode entry names, panics, releasing the handle it made before
// the panic leaves it; the recovered panic is reported on stderr after the library's report.
package main

import (
	"fmt"
	"os"

	"xy_consumer/xy_api"
)

func main() {
	defer func() {
		fmt.Fprintln(os.Stderr, "recovered:", recover())
	}()
	_, _ = xy_api.NewPort(7)
}
