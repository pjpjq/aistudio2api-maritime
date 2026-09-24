package chromeauth

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/Mag1cFall/AIStudio2API/internal/aistudio"
)

const (
	maxCookieAge = 400 * 24 * time.Hour
	userAgent    = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

// Account 描述本机 Chrome 中可发现的 Google 账号
type Account struct {
	Profile     string `json:"profile"`
	DisplayName string `json:"display_name"`
	Email       string `json:"email"`
	Locale      string `json:"locale"`
	Importable  bool   `json:"importable"`
}

// ImportOptions 保存 Chrome 批量导入参数
type ImportOptions struct {
	ChromeRoot string
	Proxy      string
	Profiles   []string
	Emails     []string
}

// ImportResult 返回一个已验证前的账号状态
type ImportResult struct {
	Profile     string
	DisplayName string
	Email       string
	Locale      string
	CookieCount int
	State       aistudio.StorageState
}

// DefaultChromeRoot 返回稳定版 Chrome User Data 目录
func DefaultChromeRoot() (string, error) {
	return defaultChromeRoot()
}

// Discover 只读列出本机 Chrome Google 账号
func Discover(chromeRoot string) ([]Account, error) {
	return discoverPlatform(chromeRoot)
}

// Import 通过设备绑定 OAuth 材料生成 Playwright storage state
func Import(ctx context.Context, options ImportOptions) ([]ImportResult, error) {
	if err := ensurePlatformImport(); err != nil {
		return nil, err
	}
	proxyURL, err := validateProxy(options.Proxy)
	if err != nil {
		return nil, err
	}
	accounts, err := Discover(options.ChromeRoot)
	if err != nil {
		return nil, err
	}
	selected, err := selectAccounts(accounts, options.Profiles, options.Emails)
	if err != nil {
		return nil, err
	}
	keyCache := make(map[string][]byte)
	results := make([]ImportResult, 0, len(selected))
	for _, account := range selected {
		result, err := importAccount(ctx, options.ChromeRoot, proxyURL, account, keyCache)
		if err != nil {
			return nil, fmt.Errorf("导入 %s: %w", account.Profile, err)
		}
		results = append(results, result)
	}
	return results, nil
}

// Refresh 使用保存的设备绑定材料重新签发 Google Cookie
func Refresh(ctx context.Context, material aistudio.ChromeOAuthMaterial, proxy string) ([]aistudio.StateCookie, error) {
	proxyURL, err := validateProxy(proxy)
	if err != nil {
		return nil, err
	}
	cookies, err := fetchGoogleCookies(ctx, material.GaiaID, material.RefreshToken, material.WrappedBindingKey, proxyURL)
	if err != nil {
		return nil, err
	}
	return toStorageCookies(cookies), nil
}

func importAccount(ctx context.Context, chromeRoot string, proxy string, account Account, keyCache map[string][]byte) (ImportResult, error) {
	gaiaID, encryptedToken, wrappedKey, err := readTokenService(chromeRoot, account.Profile)
	if err != nil {
		return ImportResult{}, err
	}
	version := string(encryptedToken[:min(len(encryptedToken), 3)])
	if version != "v10" && version != "v20" {
		return ImportResult{}, fmt.Errorf("refresh token 密文版本不支持: %s", version)
	}
	masterKey, ok := keyCache[version]
	if !ok {
		masterKey, err = retrieveTokenKey(chromeRoot, version)
		if err != nil {
			return ImportResult{}, err
		}
		if (version == "v10" && len(masterKey) != 16) || (version == "v20" && len(masterKey) != 32) {
			return ImportResult{}, fmt.Errorf("Chrome %s 主密钥长度异常", version)
		}
		keyCache[version] = append([]byte(nil), masterKey...)
	}
	var token string
	switch version {
	case "v10":
		token, err = decryptV10Token(masterKey, encryptedToken)
	case "v20":
		token, err = decryptV20Token(masterKey, encryptedToken)
	}
	if err != nil {
		return ImportResult{}, err
	}
	cookies, err := fetchGoogleCookies(ctx, gaiaID, token, wrappedKey, proxy)
	if err != nil {
		return ImportResult{}, err
	}
	state := aistudio.StorageState{Cookies: toStorageCookies(cookies), Origins: []aistudio.StorageOrigin{}}
	err = state.SetAuthExtension(aistudio.AuthExtension{
		Source: aistudio.AuthSource{Browser: "chrome", Profile: account.Profile, Email: strings.ToLower(strings.TrimSpace(account.Email))},
		OAuth: &aistudio.ChromeOAuthMaterial{
			GaiaID: gaiaID, RefreshToken: token, WrappedBindingKey: append([]byte(nil), wrappedKey...),
		},
	})
	if err != nil {
		return ImportResult{}, err
	}
	return ImportResult{
		Profile: account.Profile, DisplayName: account.DisplayName,
		Email: strings.ToLower(strings.TrimSpace(account.Email)), Locale: account.Locale,
		CookieCount: len(cookies), State: state,
	}, nil
}

func selectAccounts(accounts []Account, profiles []string, emails []string) ([]Account, error) {
	requestedProfiles := normalizedSet(profiles)
	requestedEmails := normalizedSet(emails)
	if len(requestedProfiles) == 0 && len(requestedEmails) == 0 {
		return nil, fmt.Errorf("未选择 Chrome 账号")
	}
	selected := make([]Account, 0, len(accounts))
	foundProfiles := make(map[string]struct{})
	foundEmails := make(map[string]struct{})
	for _, account := range accounts {
		profile := strings.ToLower(strings.TrimSpace(account.Profile))
		email := strings.ToLower(strings.TrimSpace(account.Email))
		_, profileMatch := requestedProfiles[profile]
		_, emailMatch := requestedEmails[email]
		if !profileMatch && !emailMatch {
			continue
		}
		if !account.Importable {
			return nil, fmt.Errorf("%s 缺少可导入的 OAuth 认证材料", account.Profile)
		}
		if !strings.Contains(email, "@") {
			return nil, fmt.Errorf("%s 缺少账号邮箱", account.Profile)
		}
		selected = append(selected, account)
		foundProfiles[profile] = struct{}{}
		foundEmails[email] = struct{}{}
	}
	if missing := missingValues(requestedProfiles, foundProfiles); len(missing) != 0 {
		return nil, fmt.Errorf("找不到 Chrome Profile: %s", strings.Join(missing, ", "))
	}
	if missing := missingValues(requestedEmails, foundEmails); len(missing) != 0 {
		return nil, fmt.Errorf("找不到 Chrome 账号: %s", strings.Join(missing, ", "))
	}
	return selected, nil
}

func normalizedSet(values []string) map[string]struct{} {
	result := make(map[string]struct{}, len(values))
	for _, value := range values {
		value = strings.ToLower(strings.TrimSpace(value))
		if value != "" {
			result[value] = struct{}{}
		}
	}
	return result
}

func missingValues(requested map[string]struct{}, found map[string]struct{}) []string {
	missing := make([]string, 0)
	for value := range requested {
		if _, ok := found[value]; !ok {
			missing = append(missing, value)
		}
	}
	sort.Strings(missing)
	return missing
}

func validateProxy(value string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return "", nil
	}
	parsed, err := url.Parse(value)
	if err != nil || parsed.Hostname() == "" {
		return "", fmt.Errorf("proxy 必须是 http、https 或 socks5 URL")
	}
	switch strings.ToLower(parsed.Scheme) {
	case "http", "https", "socks5":
		return value, nil
	default:
		return "", fmt.Errorf("proxy 必须是 http、https 或 socks5 URL")
	}
}

func decryptV20Token(masterKey []byte, encrypted []byte) (string, error) {
	if len(encrypted) < 3+12+16 || string(encrypted[:3]) != "v20" {
		return "", fmt.Errorf("refresh token 密文版本不是 v20")
	}
	block, err := aes.NewCipher(masterKey)
	if err != nil {
		return "", fmt.Errorf("创建 AES 解密器: %w", err)
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("创建 GCM 解密器: %w", err)
	}
	plaintext, err := gcm.Open(nil, encrypted[3:15], encrypted[15:], nil)
	if err != nil {
		return "", fmt.Errorf("refresh token 解密失败")
	}
	token := string(plaintext)
	if len(token) != 103 || !strings.HasPrefix(token, "1//0") {
		return "", fmt.Errorf("refresh token 解密结果格式异常")
	}
	return token, nil
}

func decryptV10Token(masterKey []byte, encrypted []byte) (string, error) {
	if len(masterKey) != 16 || len(encrypted) < 3+aes.BlockSize || string(encrypted[:3]) != "v10" {
		return "", fmt.Errorf("refresh token v10 密文格式异常")
	}
	block, err := aes.NewCipher(masterKey)
	if err != nil {
		return "", fmt.Errorf("创建 AES 解密器: %w", err)
	}
	ciphertext := encrypted[3:]
	if len(ciphertext)%aes.BlockSize != 0 {
		return "", fmt.Errorf("refresh token v10 密文长度异常")
	}
	plaintext := make([]byte, len(ciphertext))
	iv := bytes.Repeat([]byte{' '}, aes.BlockSize)
	for offset := 0; offset < len(ciphertext); offset += aes.BlockSize {
		block.Decrypt(plaintext[offset:offset+aes.BlockSize], ciphertext[offset:offset+aes.BlockSize])
		for index := 0; index < aes.BlockSize; index++ {
			plaintext[offset+index] ^= iv[index]
		}
		iv = ciphertext[offset : offset+aes.BlockSize]
	}
	padding := int(plaintext[len(plaintext)-1])
	if padding < 1 || padding > aes.BlockSize || padding > len(plaintext) || !bytes.Equal(plaintext[len(plaintext)-padding:], bytes.Repeat([]byte{byte(padding)}, padding)) {
		return "", fmt.Errorf("refresh token v10 填充校验失败")
	}
	token := string(plaintext[:len(plaintext)-padding])
	if len(token) < 30 || !strings.HasPrefix(token, "1//") {
		return "", fmt.Errorf("refresh token 解密结果格式异常")
	}
	return token, nil
}

func toStorageCookies(cookies []multiloginCookie) []aistudio.StateCookie {
	now := time.Now()
	result := make([]aistudio.StateCookie, 0, len(cookies))
	for _, cookie := range cookies {
		domain := cookie.Domain
		if domain == "" && cookie.Host != "" && !strings.HasPrefix(cookie.Host, ".") {
			domain = cookie.Host
		}
		expires := float64(-1)
		if cookie.MaxAge != nil {
			lifetime := time.Duration(*cookie.MaxAge * float64(time.Second))
			if lifetime > maxCookieAge {
				lifetime = maxCookieAge
			}
			expires = float64(now.Add(lifetime).UnixNano()) / 1e9
		}
		path := cookie.Path
		if path == "" {
			path = "/"
		}
		sameSite := strings.ToLower(cookie.SameSite)
		if sameSite != "none" && sameSite != "lax" && sameSite != "strict" {
			sameSite = ""
		} else {
			sameSite = strings.ToUpper(sameSite[:1]) + sameSite[1:]
		}
		result = append(result, aistudio.StateCookie{
			Name: cookie.Name, Value: cookie.Value, Domain: domain, Path: path,
			Expires: expires, HTTPOnly: cookie.IsHTTPOnly, Secure: cookie.IsSecure, SameSite: sameSite,
		})
	}
	return result
}
