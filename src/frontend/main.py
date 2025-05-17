import os
import time

import gradio as gr

import pandasai as pai
from pandasai.core.response import BaseResponse
from src.backend.local_llm import LocalLLM
from src.config.llm_config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODELS

absolute_script_path = os.path.abspath(__file__)
script_directory = os.path.dirname(absolute_script_path)


ROLE_SYSTEM = """You are an expert data scientist proficient in SQL and Pandas."""
llm = LocalLLM(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, model=DEEPSEEK_MODELS[0])
pai.config.set({
    'llm': llm,
    'verbose': True,
    'save_logs': False,
})

class SidebarChatInterface(gr.ChatInterface):
    def _render_history_area(self):
        with gr.Sidebar():
            gr.Markdown('# FluentDB')
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


with gr.Blocks(title='FluentDB', fill_height=True) as main_block:
    SidebarChatInterface(
        fn=Chatbot().chat_stream,
        type='messages',
        examples=["What is the average age?"],
        save_history=True,
        fill_height=True,
        fill_width=False,
    )


if __name__ == '__main__':
    main_block.queue()
    main_block.launch()
