from openai import OpenAI
from typing import List, Tuple, Generator


class OpenAILLMClient:
    def __init__(self, api_key: str, api_base: str, model: str) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=api_base)

    def stream_chat(self, history: List[Tuple[str, str]]) -> Generator[str, None, None]:
        messages = []
        for role, text in history:
            messages.append({"role": "user" if role == "user" else "assistant", "content": text})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        # 返回生成器，yield每一段内容
        for chunk in response:
            delta = getattr(chunk.choices[0].delta, 'content', None)
            if delta:
                yield delta

def main():
    # Please fill in your own api_key and api_base
    client = OpenAILLMClient(api_key="ollama", api_base="http://192.168.3.8:11434/v1", model="qwen3:30b-a3b")
    history = [
        ("user", "hello /no_think")
    ]
    for delta in client.stream_chat(history):
        print(delta, end="")
    print()

if __name__ == "__main__":
    main()
