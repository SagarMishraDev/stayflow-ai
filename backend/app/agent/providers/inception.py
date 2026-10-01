import os

from openai import OpenAI


class InceptionProvider:
    def __init__(self):
        api_key = os.getenv("INCEPTION_API_KEY")
        base_url = os.getenv(
            "INCEPTION_BASE_URL",
            "https://api.inceptionlabs.ai/v1",
        )
        model = os.getenv("INCEPTION_MODEL", "mercury-2.5")

        if not api_key:
            raise ValueError("INCEPTION_API_KEY is not set")

        self.model = model

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    def chat(self, messages: list[dict]) -> object:
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
