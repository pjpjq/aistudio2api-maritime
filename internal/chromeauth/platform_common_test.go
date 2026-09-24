package chromeauth

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"
)

func TestReadTokenServiceWithoutBindingKeyColumn(t *testing.T) {
	chromeRoot := t.TempDir()
	profile := "Profile 13"
	profileRoot := filepath.Join(chromeRoot, profile)
	if err := os.MkdirAll(profileRoot, 0o700); err != nil {
		t.Fatalf("os.MkdirAll() error = %v", err)
	}

	database, err := sql.Open("sqlite", filepath.Join(profileRoot, "Web Data"))
	if err != nil {
		t.Fatalf("sql.Open() error = %v", err)
	}
	_, err = database.Exec(`CREATE TABLE token_service (
		service TEXT NOT NULL,
		encrypted_token BLOB NOT NULL
	)`)
	if err != nil {
		database.Close()
		t.Fatalf("CREATE TABLE error = %v", err)
	}
	_, err = database.Exec(
		"INSERT INTO token_service(service, encrypted_token) VALUES (?, ?)",
		"AccountId-gaia-id", []byte("v10encrypted"),
	)
	if err != nil {
		database.Close()
		t.Fatalf("INSERT error = %v", err)
	}
	if err := database.Close(); err != nil {
		t.Fatalf("database.Close() error = %v", err)
	}

	gaiaID, encrypted, bindingKey, err := readTokenService(chromeRoot, profile)
	if err != nil {
		t.Fatalf("readTokenService() error = %v", err)
	}
	if gaiaID != "gaia-id" {
		t.Fatalf("gaiaID = %q, want %q", gaiaID, "gaia-id")
	}
	if string(encrypted) != "v10encrypted" {
		t.Fatalf("encrypted token = %q, want %q", encrypted, "v10encrypted")
	}
	if len(bindingKey) != 0 {
		t.Fatalf("binding key length = %d, want 0", len(bindingKey))
	}
}
