//go:build darwin

package chromeauth

import (
	"bytes"
	"crypto/sha1"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"golang.org/x/crypto/pbkdf2"
)

func defaultChromeRoot() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("获取用户 Home 目录: %w", err)
	}
	return filepath.Join(home, "Library", "Application Support", "Google", "Chrome"), nil
}

func ensurePlatformImport() error {
	if strings.TrimSpace(os.Getenv("CHROME_SAFE_STORAGE_PASSWORD")) != "" {
		return nil
	}
	if _, err := exec.LookPath("security"); err != nil {
		return fmt.Errorf("找不到 macOS security 命令: %w", err)
	}
	return nil
}

func platformImportable(encrypted []byte, bindingKey []byte) bool {
	return strings.HasPrefix(string(encrypted), "v10") && len(bindingKey) == 0
}

func retrieveTokenKey(_ string, version string) ([]byte, error) {
	if version != "v10" {
		return nil, fmt.Errorf("macOS Chrome 仅支持 v10 refresh token: %s", version)
	}
	password := strings.TrimSpace(os.Getenv("CHROME_SAFE_STORAGE_PASSWORD"))
	if password == "" {
		command := exec.Command("security", "find-generic-password", "-a", "Chrome", "-s", "Chrome Safe Storage", "-w")
		var stderr bytes.Buffer
		command.Stderr = &stderr
		output, err := command.Output()
		if err != nil {
			detail := strings.TrimSpace(stderr.String())
			if detail != "" {
				return nil, fmt.Errorf("读取 Chrome Safe Storage 失败: %s: %w", detail, err)
			}
			return nil, fmt.Errorf("读取 Chrome Safe Storage 失败；请在 MBP 图形终端执行，或设置 CHROME_SAFE_STORAGE_PASSWORD: %w", err)
		}
		password = strings.TrimSpace(string(output))
	}
	if password == "" {
		return nil, fmt.Errorf("Chrome Safe Storage 密码为空")
	}
	return pbkdf2.Key([]byte(password), []byte("saltysalt"), 1003, 16, sha1.New), nil
}
