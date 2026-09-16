package api

import (
	"encoding/json"
	"testing"
)

func TestMapOpenAIToolsFlattensNamespaceFunctions(t *testing.T) {
	strict := true
	tools := []openAITool{
		{
			Type: "namespace",
			Name: "default_api",
			Tools: []openAITool{
				{
					Type: "function",
					Function: struct {
						Name        string          `json:"name"`
						Description string          `json:"description"`
						Parameters  json.RawMessage `json:"parameters"`
						Strict      *bool           `json:"strict"`
					}{
						Name:        "exec_command",
						Description: "Run shell command",
						Parameters:  json.RawMessage(`{"type":"object","properties":{"cmd":{"type":"string"}}}`),
						Strict:      &strict,
					},
				},
				{
					Type:        "function",
					Name:        "top_level_func",
					Description: "Top level function",
					Parameters:  json.RawMessage(`{"type":"object","properties":{}}`),
				},
			},
		},
	}

	mapped, err := mapOpenAITools(tools, nil)
	if err != nil {
		t.Fatalf("mapOpenAITools failed: %v", err)
	}
	if len(mapped.Functions) != 2 {
		t.Fatalf("expected 2 functions, got %d", len(mapped.Functions))
	}
	if mapped.Functions[0].Name != "default_api__exec_command" {
		t.Fatalf("expected default_api__exec_command, got %s", mapped.Functions[0].Name)
	}
	if mapped.Functions[1].Name != "default_api__top_level_func" {
		t.Fatalf("expected default_api__top_level_func, got %s", mapped.Functions[1].Name)
	}
}

func TestMapAnthropicToolsFlattensNamespaceFunctions(t *testing.T) {
	tools := []anthropicTool{
		{
			Type: "namespace",
			Name: "default_api",
			Tools: []anthropicTool{
				{
					Type:        "custom",
					Name:        "exec_command",
					Description: "Run shell command",
					InputSchema: json.RawMessage(`{"type":"object","properties":{"cmd":{"type":"string"}}}`),
				},
			},
		},
	}

	mapped, err := mapAnthropicTools(tools, nil)
	if err != nil {
		t.Fatalf("mapAnthropicTools failed: %v", err)
	}
	if len(mapped.Functions) != 1 {
		t.Fatalf("expected 1 function, got %d", len(mapped.Functions))
	}
	if mapped.Functions[0].Name != "default_api__exec_command" {
		t.Fatalf("expected default_api__exec_command, got %s", mapped.Functions[0].Name)
	}
}
