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


class TaskCoordServer:
    def __init__(
        self, config: Dict, data_server: DataServer, edge_datas: Dict[str, EdgeData]
    ):
        self.config = config
        self.data_server = data_server
        self.edge_datas = edge_datas

    def coord_tasks(self, tasks: List[TaskInstance]) -> None:
        for task in tasks:
            # 从 feature_instances 里找到对应的 feature，获取 alloc_to 属性
            feature_config = self.config['feature_instances'].get(task.name,"")
            if feature_config:
                if feature_config.get('alloc_to', ""):
                    task.allocated_edge = feature_config['alloc_to']
                    continue

            task_type = self.data_server.get_data(task.task_type, TaskType)
            if task_type is None:
                raise ValueError(f"Task type {task.task_type} not found in data server")
            if task_type.basic_required_skills == ["global_explore"]:
                task.allocated_edge = "edge_exp"
                continue

            # skill req vector
            skill_req = []
            if not task.scheme_instances:
                skill_req = task_type.basic_required_skills
            elif task_type.scheme_types:
                for subtask_type_name in task_type.scheme_types[0]:
                    subtask_type = self.data_server.get_data(
                        subtask_type_name, SubtaskType
                    )
                    if subtask_type is None:
                        raise ValueError(
                            f"Subtask type {subtask_type_name} not found in data server"
                        )
                    skill_req.append(subtask_type.required_skill)
                skill_req = list(set(skill_req))

            # find the edge with the available skills
            candidate_edges = []
            for edge_name, edge_data in self.edge_datas.items():
                if all(skill in edge_data.skills for skill in skill_req):
                    candidate_edges.append(edge_name)
            if not candidate_edges:
                raise ValueError(
                    f"No edge found with the required skills {skill_req} for task {task.name}\nedge_datas: {self.edge_datas}"
                )

            # find the edge with the earliest end time
            earliest_edge = min(
                candidate_edges,
                key=lambda edge_name: len(self.edge_datas[edge_name].my_tasks),
            )
            task.allocated_edge = earliest_edge
