from typing import Protocol


class LLMProvider(Protocol):
    def chat(self, messages: list[dict]) -> object: ...
