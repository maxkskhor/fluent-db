from openai import OpenAI

from pandasai.agent.state import AgentState
from pandasai.core.prompts import BasePrompt
from pandasai.llm import LLM
from src.utils.tools import log_time


class CustomLLM(LLM):
    def __init__(self, api_key: str | None, base_url: str, **kwargs):
        super().__init__()
        self.client = OpenAI(api_key=api_key, base_url=base_url).chat.completions
        self._invocation_params = kwargs

    @log_time
    def call(self, instruction: BasePrompt, context: AgentState = None) -> str:
        last_prompt = instruction.to_string()

        memory = context.memory if context else None

        messages = memory.to_openai_messages() if memory else []

        # adding current prompt as latest query message
        messages.append({"role": "user", "content": last_prompt})

        params = {
            **self._invocation_params,
            "messages": messages,
        }

        response = self.client.create(**params)

        # noinspection PyTypeChecker
        return response.choices[0].message.content

    @property
    def type(self) -> str:
        return "Custom"
