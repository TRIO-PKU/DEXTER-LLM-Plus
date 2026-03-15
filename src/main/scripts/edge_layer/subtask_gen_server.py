from typing import List, Dict
import rospy
import json

from main.srv import StringSrvRequest, StringSrvResponse

from classes import (
    SubtaskInstance,
    TaskInstance,
    SubtaskType,
    TaskType,
    ResourceType,
    DataServer,
)


def gen_prompt(task_type_name: str, context_analysis: str, resources: List[str]) -> str:
    return json.dumps(
        {
            "prompt": {
                "rag": task_type_name,
                "task": {
                    "name": task_type_name,
                    "description": context_analysis,
                    "resources": list(set(["antidote", "oxygen", "valve", "foam", "water", "mental_net", "asbestos_felt", "activated_carbon"] + resources)),
                },
                "skills": {
                    "inspect": "dispatch personnel to conduct an on-site investigation and gather detailed information, establishing a foundation for subsequent planning.",
                    "operate": "Perform precise manipulation of valve, switch, and other control devices to regulate system parameters and maintain operational safety.",
                    "liquid_spray": "Sprays pressurized liquid (e.g. water, foam).",
                    "solid_spray": "Releases dry powder or other solid substances.",
                    "gas_spray": "Uses gases (e.g., oxygen).",
                    "monitor": "Post-task observation by personnel to verify completion and ensure safety.",
                    "clean_up": "Clean up a certain area.",
                    "lay": "Construct defenses such as asbestos_felt or metal_net to contain risks.",
                    "rescue": "Rescue people.",
                    "ignite": "Safely ignite in controlled scenarios.",
                    "fix": "Repair broken objects",
                },
                "instruction": "Using a combination of the above skills to accomplish the task, requiring the number of skill combinations to be between 3-5. You need to generate 1 - 3 schemes. Please follow JSON format",
                "output format": {
                    "analysis": "Briefly analyze the reasoning behind the skill combination sequence.",
                    "schemes": {
                        "scheme_1": {
                            "step_k": {
                                "required_skill": "skill name",
                                "resource": '0-1 immediately available objects nearby that can be directly used locally (return "" if none),',
                                "dependency": [
                                    "prerequisite steps that must be completed first(e.g. step_1)"
                                ],
                            }
                        }
                    },
                },
                "think_mode": "/no_think",
            }
        }
    )


class SubtaskGenServer:
    def __init__(
        self, config, gui_llm_client: rospy.ServiceProxy, data_server: DataServer
    ):
        self.config = config
        self.data_server = data_server
        self.gui_llm_client = gui_llm_client

    def gen_scheme(self, task_type: TaskType) -> None:
        if "global_exp" in task_type.name:
            subtask_type = SubtaskType(
                name=f"global_exp_subtask_type",
                required_skill="global_explore",
                dep_subtask_types=[],
            )
            task_type.scheme_types = [[subtask_type.name]]
            self.data_server.set_data(task_type.name, task_type, True, True)
        else:
            try:
                resources = [
                    res.name
                    for res in self.data_server.filter_data_by_type(ResourceType)
                ]
                self.gui_llm_client.wait_for_service(timeout=1)
                resp: StringSrvResponse = self.gui_llm_client.call(
                    StringSrvRequest(
                        gen_prompt(
                            task_type.name, task_type.context_analysis, resources
                        )
                    )
                )
                try:
                    scheme_types_dict: Dict = json.loads(resp.data).get("schemes", {})
                except json.JSONDecodeError as e:
                    rospy.logerr(f"Failed to decode JSON response: {e}")
                    scheme_types_dict = {}
            except rospy.ROSException as e:
                rospy.logerr(f"Service call failed: {e}")
                return

            for scheme_idx, scheme_dict in scheme_types_dict.items():
                scheme = []
                if not isinstance(scheme_dict, dict):
                    rospy.logerr(
                        f"Invalid scheme format for task {task_type.name}: {scheme_dict}"
                    )
                    continue
                for subtask_idx, subtask_type_dict in scheme_dict.items():
                    subtask_type = SubtaskType(
                        name=f"{task_type.name}-{scheme_idx}-{subtask_idx}",
                        required_skill=subtask_type_dict["required_skill"],
                        dep_subtask_types=[
                            f"{task_type.name}-{scheme_idx}-{d}"
                            for d in subtask_type_dict.get("dependency", [])
                        ],
                        required_resource=subtask_type_dict["resource"],
                        target=subtask_type_dict.get("target", "this"),
                        required_robot_num=(
                            2 if subtask_type_dict["required_skill"] == "inspect" else 1
                        ),
                    )
                    scheme.append(subtask_type.name)
                    self.data_server.set_data(
                        subtask_type.name, subtask_type, True, True
                    )
                task_type.scheme_types.append(scheme)
            self.data_server.set_data(task_type.name, task_type, True, True)
