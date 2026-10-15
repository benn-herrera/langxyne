// A consumer of support.KITCHEN_SINK's Go binding copying a Port, which go vet must report: two
// values owning one handle would each release it.
package main

import "xy_consumer/xy_api"

func main() {
	p, err := xy_api.NewPort(3)
	if err != nil {
		return
	}
	q := *p
	_ = q.Release()
}
