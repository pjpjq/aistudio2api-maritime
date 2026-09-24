//go:build !windows && !darwin

package chromeauth

import "fmt"

func defaultChromeRoot() (string, error) {
	return "", fmt.Errorf("Chrome OAuth 导入仅支持 Windows 或 macOS")
}

func ensurePlatformImport() error {
	return fmt.Errorf("Chrome OAuth 导入仅支持 Windows 或 macOS")
}

func platformImportable([]byte, []byte) bool {
	return false
}

func retrieveTokenKey(string, string) ([]byte, error) {
	return nil, fmt.Errorf("Chrome OAuth 导入仅支持 Windows 或 macOS")
}
