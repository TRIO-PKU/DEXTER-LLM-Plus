from typing import List, Dict, Union
import sys, rospy

sys.path.insert(0, sys.path[0] + "/../")
from classes import (
    EndData,
    EdgeData,
    SubtaskInstance,
    TaskInstance,
    SubtaskType,
    TaskType,
    DataServer,
    ResourceType,
    ResourceInstance,
)


class TaskGenServer:
    def __init__(self, config):
        self.config = config

    def gen_task(
        self,
        f_label: str,
        f_pos: tuple,
        type: str,
        context_analysis: str,
        task_type_DAG: Dict[str, List[str]],
        resource_types: List[ResourceType],
    ) -> List[Union[TaskType, TaskInstance, ResourceType, ResourceInstance]]:
        instance_name = f_label
        type_name = f_label

        type_config: Dict = self.config["feature_types"].get(type_name, "")
        if type_config == "":
            rospy.logerr(f"Feature type '{type_name}' not found in config.")
            return []
        type_priority = type_config.get("priority", 0)

        if type == "":
            type = type_config["type"]

        if type == "task" and type_name not in task_type_DAG.keys():
            # 新任务类型
            task_type = TaskType(
                name=type_name,
                basic_required_skills=type_config.get("basic_required_skills", ["inspect"]),
                priority=type_priority,
                context_analysis=context_analysis,
            )
            task_instance = TaskInstance(
                task_type=type_name,
                name=instance_name,
                pos=tuple(f_pos),
            )
            return [task_type, task_instance]
        elif type == "task" and type_name in task_type_DAG.keys():
            # 任务类型已存在
            task_instance = TaskInstance(
                task_type=type_name,
                name=instance_name,
                pos=tuple(f_pos),
            )
            return [task_instance]
        elif type == "resource" and type_name not in resource_types:
            # 新资源类型
            resource_type = ResourceType(name=type_name)
            resource_instance = ResourceInstance(
                name=instance_name,
                type=type_name,
                pos=tuple(f_pos),
            )
            return [resource_type, resource_instance]
        elif type == "resource" and type_name in resource_types:
            # 资源类型已存在
            resource_instance = ResourceInstance(
                name=instance_name,
                type=type_name,
                pos=tuple(f_pos),
            )
            return [resource_instance]
        else:
            return []
