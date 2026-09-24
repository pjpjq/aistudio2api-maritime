//go:build darwin

package chromeauth

import "testing"

func TestPlatformImportableDarwin(t *testing.T) {
	for _, test := range []struct {
		name       string
		encrypted  []byte
		bindingKey []byte
		want       bool
	}{
		{name: "unbound_v10", encrypted: []byte("v10encrypted"), want: true},
		{name: "bound_v10", encrypted: []byte("v10encrypted"), bindingKey: []byte("bound"), want: false},
		{name: "v20", encrypted: []byte("v20encrypted"), want: false},
		{name: "empty", want: false},
	} {
		t.Run(test.name, func(t *testing.T) {
			if got := platformImportable(test.encrypted, test.bindingKey); got != test.want {
				t.Fatalf("platformImportable() = %v, want %v", got, test.want)
			}
		})
	}
}
