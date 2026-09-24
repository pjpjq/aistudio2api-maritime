package chromeauth

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"strconv"
	"strings"
	"testing"
)

func TestDecryptV10Token(t *testing.T) {
	masterKey := []byte("0123456789abcdef")
	for _, length := range []int{100, 103} {
		t.Run("length_"+strconv.Itoa(length), func(t *testing.T) {
			token := "1//0" + strings.Repeat("x", length-4)
			encrypted := encryptV10TestToken(t, masterKey, token)

			got, err := decryptV10Token(masterKey, encrypted)
			if err != nil {
				t.Fatalf("decryptV10Token() error = %v", err)
			}
			if got != token {
				t.Fatalf("decryptV10Token() = %q, want %q", got, token)
			}
		})
	}
}

func TestDecryptV10TokenRejectsInvalidPadding(t *testing.T) {
	masterKey := []byte("0123456789abcdef")
	encrypted := encryptV10TestToken(t, masterKey, "1//0"+strings.Repeat("x", 99))
	encrypted[len(encrypted)-1] ^= 1

	if _, err := decryptV10Token(masterKey, encrypted); err == nil {
		t.Fatal("decryptV10Token() accepted invalid padding")
	}
}

func encryptV10TestToken(t *testing.T, masterKey []byte, token string) []byte {
	t.Helper()
	block, err := aes.NewCipher(masterKey)
	if err != nil {
		t.Fatalf("aes.NewCipher() error = %v", err)
	}
	padding := aes.BlockSize - len(token)%aes.BlockSize
	plaintext := append([]byte(token), bytes.Repeat([]byte{byte(padding)}, padding)...)
	ciphertext := make([]byte, len(plaintext))
	cipher.NewCBCEncrypter(block, bytes.Repeat([]byte{' '}, aes.BlockSize)).CryptBlocks(ciphertext, plaintext)
	return append([]byte("v10"), ciphertext...)
}
