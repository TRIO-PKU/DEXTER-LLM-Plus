import json
import time
import re
import random
from typing import Dict, List, Tuple, Generator


class ConfigLLMClient:
    """
    伪大模型服务，接口与OpenAILLMClient一致。
    config_path: 配置文件路径，需包含{"llm_answers": {"输入": "标准答案"}}
    match_func: 可选，自定义输入与标准答案匹配逻辑
    token_delay: token间延迟，模拟大模型流式输出
    """

    def __init__(self, config_path: str, token_delay: float = 0.06) -> None:
        self.config_path = config_path
        self.config = self._load_config(config_path)
        self.token_delay = token_delay

    def _load_config(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def match_func(self, history: List[Tuple[str, str]], config: dict) -> str:
        user_text = next((msg for role, msg in history if role == "user"), "")
        user_text_dict: Dict = json.loads(user_text)
        if "input_noun" in user_text_dict.keys():
            # Context Analysis
            input_noun: str = user_text_dict["input_noun"]
            if "." in input_noun:
                input_noun = input_noun.split(".")[0]
            feature_type = config["feature_types"][input_noun]
            # 判断是否有 fake_type 和 fake_context_analysis
            fake_type = feature_type.get("fake_type", None)
            fake_context_analysis = feature_type.get("fake_context_analysis", None)
            user_rounds = sum(1 for role, _ in history if role == "user")
            if fake_type and fake_context_analysis and user_rounds == 1:
                type_value = fake_type
                analysis_value = fake_context_analysis
            else:
                type_value = feature_type["type"]
                analysis_value = feature_type["context_analysis"]
            answer = json.dumps(
                {
                    "analysis": analysis_value,
                    "classification": type_value,
                }
            )
        elif "task" in user_text_dict.keys():
            # Subtask Generation
            task_type = config["feature_types"][user_text_dict["task"]["name"]]
            # 判断是否有 fake_schemes 和 fake_subtask_gen_analysis
            fake_schemes = task_type.get("fake_schemes", None)
            fake_subtask_gen_analysis = task_type.get("fake_subtask_gen_analysis", None)
            # 统计当前对话轮次（只统计 user 说话的次数）
            user_rounds = sum(1 for role, _ in history if role == "user")
            answer = {
                "analysis": None,
                "schemes": None,
            }
            if fake_schemes and user_rounds <= len(fake_schemes):
                # 返回 fake_schemes 中对应轮次的方案和 fake_subtask_gen_analysis
                answer["schemes"] = fake_schemes[user_rounds - 1]
                answer["analysis"] = fake_subtask_gen_analysis[user_rounds - 1]
            else:
                # 返回真实 schemes 和 analysis
                answer["schemes"] = task_type["schemes"]
                answer["analysis"] = task_type["subtask_gen_analysis"]
                # 兼容 hidden_schemes 逻辑
                if "resources" in user_text_dict["task"].keys() and "hidden_schemes" in task_type.keys():
                    resources = user_text_dict["task"]["resources"]
                    hidden_schemes = task_type["hidden_schemes"]
                    for res in resources:
                        if res in hidden_schemes.keys():
                            answer["schemes"][res] = hidden_schemes[res]
            answer = json.dumps(answer, ensure_ascii=False)
        else:
            answer = "服务器繁忙，请稍后再试。"
        return answer

    def _tokenize(self, text: str):
        # 先用正则分出所有token
        pattern = r"[\u4e00-\u9fff]|\w+|[ \t\r\n]+|[^\w\s]"
        raw_tokens = re.findall(pattern, text)
        tokens = []
        buf = ""
        for t in raw_tokens:
            # 如果是长度大于1的英文单词/数字/下划线，直接作为token输出
            if re.fullmatch(r"\w+", t) and len(t) > 2:
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(t)
            else:
                buf += t
                # 如果buf长度大于等于2，且下一个token是长词，则提前输出buf
        if buf:
            tokens.append(buf)
        return tokens

    def stream_chat(self, history: List[Tuple[str, str]]) -> Generator[str, None, None]:
        answer = self.match_func(history, self.config)
        time.sleep(3)
        tokens = self._tokenize(answer)
        output = ""
        for token in tokens:
            yield token
            time.sleep(self.token_delay + random.uniform(-0.05, 0.05))


if __name__ == "__main__":

    user_input = {
        "task": {
            "name": "alkane_gas_flame",
            "description": "A fire caused by the combustion of alkane gas, which is a flammable gas. The fire is characterized by a blue flame and can be extinguished using water or foam.",
        },
        "skills": {
            "inspect": {
                "description": "dispatch personnel to conduct an on-site investigation and gather detailed information, establishing a foundation for subsequent planning."
            },
            "operate": {
                "description": "Perform precise manipulation of valve, switch, and other control devices to regulate system parameters and maintain operational safety."
            },
            "liquid_spray": {
                "description": "Sprays pressurized liquid (water/foam) to cool flames and block oxygen."
            },
            "solid_spray": {
                "description": "Releases dry powder to disrupt chemical reactions in fires."
            },
            "gas_spray": {
                "description": "Uses gases (e.g., dry_ice, inert_gas) to reduce oxygen and extinguish flames."
            },
            "monitor": {
                "description": "Post-task observation by personnel to verify completion and ensure safety."
            },
            "clean_up": {
                "description": "Hazard cleanup using activated_carbon, calcium_hydroxide, or other absorbents."
            },
            "throw": {
                "description": "Long-range deployment of fire_extinguishing_bomb to suppress fires or complete tasks."
            },
            "lay": {
                "description": "Construct defenses such as fire_dike or metal_net to contain risks."
            },
            "build": {
                "description": "Construct defenses such as fire_dike or metal_net to contain risks."
            },
            "rescue": {
                "description": "Rescue people using rescue_station facilities or administer antidote for treatment."
            },
            "ignite": {
                "description": "Safely ignite explosives or combustibles in controlled scenarios."
            },
            "fix": {"description": "Repair broken objects"},
        },
        "instruction": "Using a combination of the above skills to accomplish the task, requiring the number of skill combinations to be between 3-7. You need to generate 1 - 3 schemes. The output format should follow:Special reminder: In the 'analysis' section, always enclose specific resources or targets in angle brackets (e.g., <water>, <valve>). However, in the 'step_1' to 'step_n' sections, never use angle brackets - write resource and target names directly (e.g., water, valve). Maintain this formatting distinction throughout the response.",
        "output format": {
            "analysis": "Briefly analyze the reasoning behind the skill combination sequence.",
            "schemes": {
                "scheme_1": {
                    "step_k": {
                        "required_skill": "skill name",
                        "resource": '0-1 immediately available objects nearby that can be directly used locally (return "" if none),',
                        "target": '0-1 distant objects requiring remote operation (return "this" if none or is just current task object),',
                        "dependency": [
                            "prerequisite steps that must be completed first(e.g. step_1)"
                        ],
                    }
                }
            },
        }
    }
    user_input = json.dumps(user_input, ensure_ascii=False)
    history = [("user", user_input)]

    config_path = "src/main/launch/config.json"

    # 实例化并测试
    client = ConfigLLMClient(config_path)
    print("Streaming output:")
    for out in client.stream_chat(history):
        print(out, end="", flush=True)