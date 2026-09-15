package aistudio

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestEncodeGenerateContentRequest_ToolConfig(t *testing.T) {
	defaults := GenerationDefaults{
		MaxOutputTokens: 8192,
	}
	baseContents := []Content{
		{
			Role: "user",
			Parts: []Part{
				{Text: "hello"},
			},
		},
	}
	sampleFunc := FunctionDeclaration{
		Name:        "get_weather",
		Description: "Get the current weather",
		Parameters:  json.RawMessage(`{"type":"object","properties":{"location":{"type":"string"}}}`),
	}

	tests := []struct {
		name       string
		model      string
		tools      Tools
		runtime    RequestContext
		wantLength int
		wantWire13 any
	}{
		{
			name:  "functions+Google",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
				Google:    []string{"google_search"},
			},
			wantLength: 14,
			wantWire13: []any{nil, nil, true},
		},
		{
			name:  "functions+GoogleSearch",
			model: "models/gemini-3.8-flash",
			tools: Tools{
				Functions:    []FunctionDeclaration{sampleFunc},
				GoogleSearch: &GoogleSearchOptions{WebSearch: true},
			},
			wantLength: 14,
			wantWire13: []any{nil, nil, true},
		},
		{
			name:  "only-functions",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
			},
			wantLength: 11,
		},
		{
			name:  "only-builtins",
			model: "gemini-3.8-flash",
			tools: Tools{
				Google: []string{"google_search"},
			},
			wantLength: 11,
		},
		{
			name:  "mixed gemini-2.5-flash",
			model: "gemini-2.5-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
				Google:    []string{"google_search"},
			},
			wantLength: 11,
		},
		{
			name:  "mixed tools disabled",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions:  []FunctionDeclaration{sampleFunc},
				Google:     []string{"google_search"},
				ToolConfig: ToolConfig{Mode: "none"},
			},
			wantLength: 11,
		},
		{
			name:  "mixed tools with timezone",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
				Google:    []string{"google_search"},
			},
			runtime:    RequestContext{Timezone: "Asia/Shanghai"},
			wantLength: 14,
			wantWire13: []any{[]any{nil, nil, "Asia/Shanghai"}, nil, true},
		},
		{
			name:  "timezone without mixed tools",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
			},
			runtime:    RequestContext{Timezone: "Asia/Shanghai"},
			wantLength: 14,
			wantWire13: []any{[]any{nil, nil, "Asia/Shanghai"}},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			req := GenerateRequest{
				Model:    tc.model,
				Contents: baseContents,
				Tools:    tc.tools,
			}
			encoded, err := EncodeGenerateContentRequest(req, defaults, tc.runtime)
			if err != nil {
				t.Fatalf("EncodeGenerateContentRequest failed: %v", err)
			}

			var wire []any
			if err := json.Unmarshal(encoded, &wire); err != nil {
				t.Fatalf("json.Unmarshal failed: %v", err)
			}

			if len(wire) != tc.wantLength {
				t.Fatalf("wire length = %d, want %d", len(wire), tc.wantLength)
			}

			if wire[7] != nil {
				t.Errorf("wire[7] = %#v, want nil", wire[7])
			}
			var gotWire13 any
			if len(wire) > 13 {
				gotWire13 = wire[13]
			}
			if !reflect.DeepEqual(gotWire13, tc.wantWire13) {
				t.Errorf("wire[13] mismatch: got %#v, want %#v", gotWire13, tc.wantWire13)
			}
		})
	}
}
