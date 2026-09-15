package api

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Mag1cFall/AIStudio2API/internal/aistudio"
)

func TestMapResponsesToolsFlattensNamespaceFunctionsAndCustomTools(t *testing.T) {
	strict := false
	tools := []responsesTool{{
		Type: "namespace", Name: "functions", Tools: []responsesTool{
			{Type: "function", Name: "wait", Parameters: json.RawMessage(`{"type":"object","properties":{}}`), Strict: &strict},
			{Type: "custom", Name: "exec", Format: json.RawMessage(`{"type":"grammar","syntax":"lark"}`)},
		},
	}}

	mapped, err := mapResponsesTools(tools, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(mapped.Functions) != 2 {
		t.Fatalf("functions = %d, want 2", len(mapped.Functions))
	}
	if got := mapped.Functions[0].Name; got != "functions__wait" {
		t.Fatalf("function name = %q, want functions__wait", got)
	}
	if got := mapped.Functions[1].Name; got != "functions__exec" {
		t.Fatalf("custom name = %q, want functions__exec", got)
	}
	if !strings.Contains(mapped.Functions[1].Description, `"syntax":"lark"`) {
		t.Fatalf("custom format missing from description: %q", mapped.Functions[1].Description)
	}
}

func TestResponseToolCallRestoresNamespaceIdentity(t *testing.T) {
	request := responsesRequest{Tools: []responsesTool{{
		Type: "namespace", Name: "functions", Tools: []responsesTool{
			{Type: "function", Name: "wait"},
			{Type: "custom", Name: "exec"},
		},
	}}}

	functionItem := responseToolCall(aistudio.FunctionCall{
		ID: "wait-1", Name: "functions__wait", Arguments: json.RawMessage(`{"seconds":1}`),
	}, request)
	if functionItem["type"] != "function_call" || functionItem["name"] != "wait" || functionItem["namespace"] != "functions" {
		t.Fatalf("unexpected function item: %#v", functionItem)
	}

	customItem := responseToolCall(aistudio.FunctionCall{
		ID: "exec-1", Name: "functions__exec", Arguments: json.RawMessage(`{"input":"text(1);"}`),
	}, request)
	if customItem["type"] != "custom_tool_call" || customItem["name"] != "exec" || customItem["namespace"] != "functions" {
		t.Fatalf("unexpected custom item: %#v", customItem)
	}
	if customItem["input"] != "text(1);" {
		t.Fatalf("custom input = %#v, want text(1);", customItem["input"])
	}
}

func TestResponsesStreamRestoresCustomNamespaceIdentity(t *testing.T) {
	request := responsesRequest{Tools: []responsesTool{{
		Type: "namespace", Name: "functions", Tools: []responsesTool{{Type: "custom", Name: "exec"}},
	}}}
	recorder := httptest.NewRecorder()
	writer := responsesStreamWriter{
		w: recorder, request: request, indexes: make(map[string]int),
	}
	if err := writer.emitToolCall(aistudio.FunctionCall{
		ID: "exec-1", Name: "functions__exec", Arguments: json.RawMessage(`{"input":"text(1);"}`),
	}); err != nil {
		t.Fatal(err)
	}
	body := recorder.Body.String()
	for _, expected := range []string{
		`response.custom_tool_call_input.done`,
		`"type":"custom_tool_call"`,
		`"namespace":"functions"`,
		`"name":"exec"`,
		`"input":"text(1);"`,
	} {
		if !strings.Contains(body, expected) {
			t.Fatalf("stream missing %q: %s", expected, body)
		}
	}
}

func TestResponsesAdditionalToolsJoinRequestWithoutContentError(t *testing.T) {
	request := responsesRequest{
		Input: json.RawMessage(`[{"type":"additional_tools","tools":[{"type":"namespace","name":"mcp","tools":[{"type":"function","name":"lookup"}]}]}]`),
	}
	tools := request.allTools()
	if len(tools) != 1 || tools[0].Type != "namespace" {
		t.Fatalf("additional tools not collected: %#v", tools)
	}
	contents, _, err := responsesContents(request.Input)
	if err != nil {
		t.Fatal(err)
	}
	if len(contents) != 0 {
		t.Fatalf("additional_tools produced conversation content: %#v", contents)
	}
}
