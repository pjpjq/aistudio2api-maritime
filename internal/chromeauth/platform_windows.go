//go:build windows

package chromeauth

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func defaultChromeRoot() (string, error) {
	localAppData := strings.TrimSpace(os.Getenv("LOCALAPPDATA"))
	if localAppData == "" {
		return "", fmt.Errorf("环境变量 LOCALAPPDATA 为空")
	}
	return filepath.Join(localAppData, "Google", "Chrome", "User Data"), nil
}

func ensurePlatformImport() error {
	return nil
}

func platformImportable(encrypted []byte, bindingKey []byte) bool {
	return strings.HasPrefix(string(encrypted), "v20") && len(bindingKey) != 0
}

func retrieveTokenKey(chromeRoot string, version string) ([]byte, error) {
	if version != "v20" {
		return nil, fmt.Errorf("Windows Chrome 仅支持 v20 refresh token")
	}
	return retrieveV20Key(chromeRoot)
}
