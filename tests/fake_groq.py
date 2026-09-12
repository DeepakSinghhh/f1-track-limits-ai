"""A minimal fake matching the slice of the Groq SDK's response shape
this project actually uses (chat.completions.create -> choices[0] with
.finish_reason and .message.{content,tool_calls}), shared between
tests/test_agent_reason.py and tests/test_api.py so both exercise the
same fake rather than two drifting copies.
"""
import json


class FakeFunctionCall:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments  # a JSON string, matching the real API


class FakeToolCall:
    def __init__(self, id, name, arguments_dict):
        self.id = id
        self.function = FakeFunctionCall(name, json.dumps(arguments_dict))


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, finish_reason, message):
        self.finish_reason = finish_reason
        self.message = message


class FakeResponse:
    def __init__(self, finish_reason, message):
        self.choices = [FakeChoice(finish_reason, message)]


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        return self._responses.pop(0)


class FakeChat:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)


class FakeClient:
    def __init__(self, responses):
        self.chat = FakeChat(responses)


def text_response(text, finish_reason="stop"):
    return FakeResponse(finish_reason=finish_reason, message=FakeMessage(content=text))


def tool_call_response(name, arguments_dict, tool_call_id="tool-1"):
    return FakeResponse(
        finish_reason="tool_calls",
        message=FakeMessage(content=None, tool_calls=[FakeToolCall(tool_call_id, name, arguments_dict)]),
    )
