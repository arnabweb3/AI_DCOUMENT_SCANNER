# llm.py
# Code for talking to the LLM (Gemini or OpenAI).
# Both classes have an ask() function that also handles tool calling:
#   1. send the question + tools to the LLM
#   2. if the LLM wants to call a tool, run it (through MCP) and send the result back
#   3. repeat until the LLM gives the final answer

import json
import time

from config import MAX_TOOL_ROUNDS, MAX_TOOL_RESULT_LENGTH


def run_tool_safely(run_tool, name, args, tools_used):
    try:
        result = run_tool(name, args)
    except Exception as e:
        # send the error to the LLM, it can try again
        result = json.dumps({"error": str(e)})

    tools_used.append({"tool": name, "arguments": args, "result": result[:2000]})

    if len(result) > MAX_TOOL_RESULT_LENGTH:
        result = result[:MAX_TOOL_RESULT_LENGTH] + "\n...(cut)"
    return result


# ---------------- OpenAI ----------------

class OpenAIChat:
    def __init__(self, api_key, model, temperature=0.2):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def send(self, messages, tools=None):
        settings = {"model": self.model, "messages": messages}
        if tools:
            settings["tools"] = tools
        # some new models (o1, o3, gpt-5...) don't allow changing temperature
        if not self.model.startswith(("o1", "o3", "o4", "gpt-5")):
            settings["temperature"] = self.temperature
        return self.client.chat.completions.create(**settings)

    def ask(self, system_prompt, messages, tools, run_tool):
        all_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            all_messages.append({"role": m["role"], "content": m["content"]})

        # change MCP tools into OpenAI format
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            })

        tools_used = []
        for i in range(MAX_TOOL_ROUNDS):
            response = self.send(all_messages, openai_tools)
            message = response.choices[0].message

            # no tool call means this is the final answer
            if not message.tool_calls:
                return message.content or "", tools_used

            tool_calls = []
            for call in message.tool_calls:
                tool_calls.append({
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                })
            all_messages.append({"role": "assistant", "content": message.content or "", "tool_calls": tool_calls})

            for call in message.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except Exception:
                    args = {}
                result = run_tool_safely(run_tool, call.function.name, args, tools_used)
                all_messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        # too many tool calls, ask for an answer without tools
        response = self.send(all_messages)
        return response.choices[0].message.content or "", tools_used


# ---------------- Gemini ----------------

def convert_schema_for_gemini(schema):
    # Gemini needs its own Schema object, so I convert the MCP json schema
    from google.genai import types

    # Optional values come as anyOf [type, null], so take the non-null one
    if "anyOf" in schema:
        description = schema.get("description")
        options = []
        for option in schema["anyOf"]:
            if option.get("type") != "null":
                options.append(option)
        if len(options) > 0:
            schema = dict(options[0])
        else:
            schema = {"type": "string"}
        if description:
            schema["description"] = description

    schema_type = schema.get("type", "string")
    settings = {"type": schema_type.upper()}
    if schema.get("description"):
        settings["description"] = schema["description"]
    if schema.get("enum"):
        settings["enum"] = [str(e) for e in schema["enum"]]

    if schema_type == "object" and schema.get("properties"):
        properties = {}
        for name in schema["properties"]:
            properties[name] = convert_schema_for_gemini(schema["properties"][name])
        settings["properties"] = properties
        if schema.get("required"):
            settings["required"] = schema["required"]

    if schema_type == "array":
        settings["items"] = convert_schema_for_gemini(schema.get("items", {"type": "string"}))

    return types.Schema(**settings)


class GeminiChat:
    def __init__(self, api_key, model, temperature=0.2):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def send(self, contents, config):
        from google.genai import errors

        # sometimes gemini says "high demand" (503) or "too many requests" (429), so try again
        for attempt in range(4):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.APIError as e:
                if e.code not in [429, 500, 503] or attempt == 3:
                    raise
                time.sleep(2 * (2 ** attempt))  # wait 2, 4, 8 seconds

    def ask(self, system_prompt, messages, tools, run_tool):
        from google.genai import types

        contents = []
        for m in messages:
            role = "user"
            if m["role"] == "assistant":
                role = "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))

        # change MCP tools into Gemini format
        functions = []
        for tool in tools:
            if tool["input_schema"] and tool["input_schema"].get("properties"):
                functions.append(types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=convert_schema_for_gemini(tool["input_schema"]),
                ))
            else:
                functions.append(types.FunctionDeclaration(name=tool["name"], description=tool["description"]))

        config_with_tools = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self.temperature,
            tools=[types.Tool(function_declarations=functions)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        config_without_tools = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self.temperature,
        )

        tools_used = []
        for i in range(MAX_TOOL_ROUNDS):
            response = self.send(contents, config_with_tools)

            # no function call means this is the final answer
            if not response.function_calls:
                return response.text or "", tools_used

            contents.append(response.candidates[0].content)
            parts = []
            for call in response.function_calls:
                args = dict(call.args or {})
                result = run_tool_safely(run_tool, call.name, args, tools_used)
                parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))

        # too many tool calls, ask for an answer without tools
        response = self.send(contents, config_without_tools)
        return response.text or "", tools_used


def make_llm(provider, api_key, model, temperature=0.2):
    if provider == "OpenAI":
        return OpenAIChat(api_key, model, temperature)
    else:
        return GeminiChat(api_key, model, temperature)
