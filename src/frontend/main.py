import os
import random
import time

import gradio as gr

import pandasai as pai
from pandasai.agent.base import Stage
from pandasai.core.response import BaseResponse
from src.backend.local_llm import CustomLLM
from src.config.llm_config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODELS

absolute_script_path = os.path.abspath(__file__)
script_directory = os.path.dirname(absolute_script_path)


ROLE_SYSTEM = """You are an expert data scientist proficient in SQL and Pandas."""
llm = CustomLLM(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, model=DEEPSEEK_MODELS[0])
pai.config.set({
    'llm': llm,
    'verbose': True,
    'save_logs': False,
})

class SidebarChatInterface(gr.ChatInterface):
    def _render_history_area(self):
        with gr.Sidebar():
            gr.Markdown('# FluentDB')
            gr.Markdown('Powered by PandasAI')
            self.new_chat_button = gr.Button(
                "New chat",
                variant="primary",
                size="md",
                icon=gr.utils.get_icon_path("plus.svg"),
                # scale=0,
            )
            self.chat_history_dataset = gr.Dataset(
                components=[gr.Textbox(visible=False)],
                show_label=False,
                layout="table",
                type="index",
            )


def setup_agent() -> pai.Agent:
    df = pai.read_csv(f"{script_directory }/heart.csv")
    return pai.Agent(
        dfs=[df],
        config=None,
        memory_size=10,
        vectorstore=None,
        description=ROLE_SYSTEM,
        sandbox=None,
    )


agent = setup_agent()


def format_base_response_to_gradio(response: BaseResponse):
    if response.type == 'error':
        return f"{response.value}```\npython{response.last_code_executed}\n```"
    elif response.type == 'dataframe':
        return gr.HTML(response.value.to_html())
    elif response.type == 'chart':
        return gr.Image(response.value)
    else:
        return str(response.value)


class Chatbot:
    @staticmethod
    def chat_stream(message: str, history: list[dict], request: gr.Request):
        final_result = []
        start_time = time.time()
        if not history:
            response = agent.chat(message)
        else:
            response = agent.follow_up(message)

        content = format_base_response_to_gradio(response)
        final_result.append({"role": "assistant", "content": f"```python\n{response.last_code_executed}\n```",
                             "metadata": {"title": "Code Executed", "status": "done", "duration": time.time() - start_time}})
        final_result.append({"role": "assistant", "content": content})
        return final_result

    @staticmethod
    def chat_stream_proper(message: str, history: list[dict], request: gr.Request):
        final_result = []
        start_time = time.time()
        yield [{"role": "assistant", "content": "...", "metadata": {"title": "🤖🛠️⚙️ Setting up agent ...", "status": "pending"}}]
        random_sleep_duration = random.uniform(1.0, 3.0)
        time.sleep(random_sleep_duration)  # simulated
        final_result.append({"role": "assistant", "content": "Setup agent",
                     "metadata": {"title": "🤖 Setup Agent", "status": "done", "duration": time.time() - start_time}})
        yield final_result + [{"role": "assistant", "content": "...",
                               "metadata": {"title": "Generating Code ...", "status": "pending"}}]

        if not history:
            result_generator = agent.chat_with_stream(message)
        else:
            result_generator = agent.follow_up_with_stream(message)

        for stream_response in result_generator:
            if stream_response.stage is Stage.CODE_GENERATION:
                final_result.append(
                    {"role": "assistant", "content": f"```python\n{stream_response.content}\n```",
                     "metadata": {"title": "🤖➡️📄 Code Generated", "status": "done", "duration": time.time() - start_time}}
                )
                yield final_result + [{"role": "assistant", "content": "...",
                                       "metadata": {"title": "▶️ Executing Code ...", "status": "pending"}}]
            elif stream_response.stage is Stage.CODE_EXECUTION_FAILURE:
                final_result.append(
                    {"role": "assistant", "content": f"```python\n{stream_response.content}\n```",
                     "metadata": {"title": "▶️❌ Code Execution Error", "status": "done", "duration": time.time() - start_time}}
                )
                yield final_result + [{"role": "assistant", "content": "...",
                                       "metadata": {"title": "🛠️🧠➡️📄 Re-generating Code ...", "status": "pending"}}]
            elif stream_response.stage is Stage.CODE_REGENERATION:
                final_result.append(
                    {"role": "assistant", "content": f"```python\n{stream_response.content}\n```",
                     "metadata": {"title": "🔄📄 Code Regenerated", "status": "done", "duration": time.time() - start_time}}
                )
                yield final_result + [{"role": "assistant", "content": "...",
                                       "metadata": {"title": "▶️ Executing Code ...", "status": "pending"}}]
            elif stream_response.stage is Stage.FINAL_ERROR:
                final_result.append(
                    {"role": "assistant", "content": "❌ **Error**:\n",}
                )
                final_result.append(
                    {"role": "assistant", "content": format_base_response_to_gradio(stream_response.content),}
                )
                yield final_result
            elif stream_response.stage is Stage.FINAL_RESULT:
                final_result.append(
                    {"role": "assistant", "content": "✅ **Result**:\n",}
                )
                final_result.append(
                    {"role": "assistant", "content": format_base_response_to_gradio(stream_response.content),}
                )
                yield final_result
            else:
                raise gr.Error(f'Wrong StreamResponse Stage: {stream_response.stage}')
            start_time = time.time()

with gr.Blocks(title='FluentDB', fill_height=True) as main_block:
    SidebarChatInterface(
        fn=Chatbot().chat_stream_proper,
        type='messages',
        examples=["What is the average age?", "Plot the distribution of Max Heart Rate.", "Plot the distribution of the Age, grouped by Sex."],
        save_history=True,
        fill_height=True,
        fill_width=False,
    )


if __name__ == '__main__':
    main_block.queue()
    main_block.launch()
