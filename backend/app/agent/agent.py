import json

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.providers.inception import InceptionProvider
from app.agent.tools import TOOLS, execute_tool

HOTEL_ID = 2
MAX_TOOL_ROUNDS = 5


class StayFlowAgent:
    def __init__(self):
        self.llm = InceptionProvider()

    def run(
        self,
        user_message: str,
        guest_id: int | None = None,
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    SYSTEM_PROMPT + f"\n\nYou are currently assisting hotel ID {HOTEL_ID}."
                ),
            },
            {
                "role": "user",
                "content": user_message,
            },
        ]

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.llm.client.chat.completions.create(
                model=self.llm.model,
                messages=messages,
                tools=TOOLS,
            )

            message = response.choices[0].message

            if not message.tool_calls:
                return message.content or ("I'm sorry, I couldn't generate a response.")

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in message.tool_calls
                    ],
                }
            )

            for tool_call in message.tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    result = json.dumps(
                        {
                            "success": False,
                            "error": "Invalid tool arguments.",
                        }
                    )
                else:
                    arguments["hotel_id"] = HOTEL_ID

                    if guest_id is not None:
                        arguments["guest_id"] = guest_id

                    result = execute_tool(
                        tool_call.function.name,
                        arguments,
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        return "I'm sorry, I couldn't complete the request right now. Please try again."
