from typing import List, Dict
import sys

sys.path.insert(0, sys.path[0] + "/../")
from classes import (
    EndData,
    EdgeData,
    SubtaskInstance,
    TaskInstance,
    SubtaskType,
    TaskType,
    DataServer,
)


class TaskCompServer:
    def __init__(self, config):
        self.config = config

    def comp_task_types(
        self, task_types: List[TaskType], task_type_DAG: Dict[str, List[str]]
    ) -> None:
        for task_type in task_types:
            if "global_exp" in task_type.name:
                task_type.to_be_comp = False
                continue
            task_type.dep_task_types = self.config["feature_types"][task_type.name].get(
                "dep_task_types", []
            )
            task_type.to_be_comp = False
