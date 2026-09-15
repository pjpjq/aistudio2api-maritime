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
		name      string
		model     string
		tools     Tools
		wantWire7 any
	}{
		{
			name:  "functions+Google",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
				Google:    []string{"google_search"},
			},
			wantWire7: []any{nil, nil, nil, true},
		},
		{
			name:  "functions+GoogleSearch",
			model: "models/gemini-3.8-flash",
			tools: Tools{
				Functions:    []FunctionDeclaration{sampleFunc},
				GoogleSearch: &GoogleSearchOptions{WebSearch: true},
			},
			wantWire7: []any{nil, nil, nil, true},
		},
		{
			name:  "only-functions",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
			},
			wantWire7: nil,
		},
		{
			name:  "only-builtins",
			model: "gemini-3.8-flash",
			tools: Tools{
				Google: []string{"google_search"},
			},
			wantWire7: nil,
		},
		{
			name:  "mixed gemini-2.5-flash",
			model: "gemini-2.5-flash",
			tools: Tools{
				Functions: []FunctionDeclaration{sampleFunc},
				Google:    []string{"google_search"},
			},
			wantWire7: nil,
		},
		{
			name:  "mixed tools disabled",
			model: "gemini-3.8-flash",
			tools: Tools{
				Functions:  []FunctionDeclaration{sampleFunc},
				Google:     []string{"google_search"},
				ToolConfig: ToolConfig{Mode: "none"},
			},
			wantWire7: nil,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			req := GenerateRequest{
				Model:    tc.model,
				Contents: baseContents,
				Tools:    tc.tools,
			}
			encoded, err := EncodeGenerateContentRequest(req, defaults, RequestContext{})
			if err != nil {
				t.Fatalf("EncodeGenerateContentRequest failed: %v", err)
			}

			var wire []any
			if err := json.Unmarshal(encoded, &wire); err != nil {
				t.Fatalf("json.Unmarshal failed: %v", err)
			}

			if len(wire) < 11 {
				t.Fatalf("wire length = %d, want at least 11", len(wire))
			}

			gotWire7 := wire[7]
			if !reflect.DeepEqual(gotWire7, tc.wantWire7) {
				t.Errorf("wire[7] mismatch: got %#v, want %#v", gotWire7, tc.wantWire7)
			}
		})
	}
}
