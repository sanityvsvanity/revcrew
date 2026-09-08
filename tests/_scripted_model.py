"""A Model that plays a script — the only way to test an agent path offline.

agno's own approach: subclass ``Model``, return ``ModelResponse`` objects, and
let the real machinery (tool dispatch, output-schema parsing, workflow steps)
do the rest. The tests then exercise the actual path rather than a mock of it.

Landmine (inherited from the predecessor's fixture): do not name an attribute
``_tool_name`` — ``Model._tool_name`` is a staticmethod agno uses to sort tool
schemas, and shadowing it turns every run into a swallowed TypeError.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator

from agno.models.base import Model
from agno.models.response import ModelResponse


class ScriptedModel(Model):
    """Plays ``script`` in order: each item is a tool call ``("call", name, args)``
    or a final answer ``("say", text)``. Repeats the last answer if asked again."""

    def __init__(self, script: list[tuple], **kw: Any):
        super().__init__(id=kw.pop("id", "scripted"), provider="scripted", **kw)
        self._script = list(script)
        self.calls = 0
        self.prompts: list[str] = []

    def _record(self, *a: Any, **k: Any) -> None:
        for msg in k.get("messages") or (a[0] if a else None) or []:
            if getattr(msg, "role", "") == "user":
                self.prompts.append(str(getattr(msg, "content", "") or ""))

    def _next(self) -> ModelResponse:
        idx = min(self.calls, len(self._script) - 1)
        self.calls += 1
        item = self._script[idx]
        if item[0] == "call":
            _, name, args = item
            return ModelResponse(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": f"call_{self.calls}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            )
        return ModelResponse(role="assistant", content=item[1])

    def invoke(self, *a: Any, **k: Any) -> ModelResponse:
        self._record(*a, **k)
        return self._next()

    async def ainvoke(self, *a: Any, **k: Any) -> ModelResponse:
        self._record(*a, **k)
        return self._next()

    def invoke_stream(self, *a: Any, **k: Any) -> Iterator[ModelResponse]:
        self._record(*a, **k)
        yield self._next()

    async def ainvoke_stream(self, *a: Any, **k: Any) -> AsyncIterator[ModelResponse]:
        self._record(*a, **k)
        yield self._next()

    def _parse_provider_response(self, response: Any, **kw: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response
