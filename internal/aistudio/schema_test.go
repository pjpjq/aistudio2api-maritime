package aistudio

import (
	"encoding/json"
	"os"
	"testing"
)

type CodexToolItem struct {
	Source string          `json:"source"`
	Name   string          `json:"name"`
	Schema json.RawMessage `json:"schema"`
}

func TestAllCodexToolsEncoding(t *testing.T) {
	data, err := os.ReadFile("/tmp/all_codex_tools.json")
	if err != nil {
		t.Skip("cache file not found, skipping bulk test")
		return
	}
	var tools []CodexToolItem
	if err := json.Unmarshal(data, &tools); err != nil {
		t.Fatal(err)
	}
	for i, tool := range tools {
		wire, err := encodeJSONSchema(tool.Schema)
		if err != nil {
			t.Fatalf("Tool %d (%s) failed: %v", i, tool.Name, err)
		}
		if len(wire) == 0 {
			t.Fatalf("Tool %d (%s) produced empty wire", i, tool.Name)
		}
	}
	t.Logf("Successfully validated all %d Codex tools!", len(tools))
}

func TestComplexNestedSchemaWithoutType(t *testing.T) {
	// Reproduce the exact undo_config -> anyOf[0] -> deployments error
	raw := json.RawMessage(`{
		"type": "object",
		"properties": {
			"undo_config": {
				"anyOf": [
					{
						"properties": {
							"deployments": {
								"anyOf": [
									{
										"properties": {
											"chatgpt": {
												"properties": {
													"schedule_triggers": {
														"items": {
															"properties": {
																"deployment_id": {
																	"title": "Deployment Id",
																	"type": "string"
																},
																"channel_binding": {
																	"anyOf": [
																		{
																			"oneOf": [
																				{
																					"type": "object",
																					"properties": {"type": {"const": "chatgpt"}}
																				}
																			]
																		},
																		{"type": "null"}
																	]
																}
															}
														}
													}
												}
											}
										}
									},
									{"type": "null"}
								]
							}
						}
					},
					{"type": "null"}
				]
			}
		}
	}`)
	wire, err := encodeJSONSchema(raw)
	if err != nil {
		t.Fatalf("Failed to encode complex nested schema: %v", err)
	}
	if len(wire) == 0 {
		t.Fatal("Expected non-empty wire")
	}
}

func TestSchemaConstAndNumericEnum(t *testing.T) {
	raw := json.RawMessage(`{
		"properties": {
			"status": {"const": "ACTIVE"},
			"priority": {"enum": [1, 2, 3]}
		}
	}`)
	wire, err := encodeJSONSchema(raw)
	if err != nil {
		t.Fatalf("Failed to encode const/numeric enum schema: %v", err)
	}
	if len(wire) == 0 {
		t.Fatal("Expected non-empty wire")
	}
}
