from typing import List, Dict, Optional, cast, Tuple
import sys
import rospy

sys.path.insert(0, sys.path[0] + "/../")
from classes import (
    EndData,
    EdgeData,
    SubtaskInstance,
    TaskInstance,
    SubtaskType,
    TaskType,
    DataServer,
    ResourceInstance,
)

from milp_adapter import MILPAdapter
import math
import uuid


class SubtaskAllocServer:
    def __init__(
        self,
        edge_data: EdgeData,
        end_datas: Dict[str, EndData],
        data_server: DataServer,
        config: Dict,
    ):
        self.edge_data: EdgeData = edge_data
        self.end_datas: Dict[str, EndData] = end_datas
        self.data_server: DataServer = data_server
        self.config = config
        self.milp_adapter: MILPAdapter = MILPAdapter(self.config)
        self.exp_task_config: str = str(
            rospy.get_param("~exp_task_config", "-20,-20,20,20,10,2")
        )  # x_min,y_min,x_max,y_max,z,block_size

    def _search_resource(
        self,
        type_name: str,
        this_pos: Tuple[float, float, float],
        range: Optional[float] = None,
    ) -> Optional[Tuple[float, float, float]]:
        """找到与当前task距离最近且类型匹配的资源实例。如果range为None，则不限制半径。"""
        resource_instances = self.data_server.filter_data_by_type(ResourceInstance)
        min_dist = float("inf")
        closest_pos = None
        for res_inst in resource_instances:
            if res_inst.type == type_name:
                dist = math.sqrt(
                    (this_pos[0] - res_inst.pos[0]) ** 2
                    + (this_pos[1] - res_inst.pos[1]) ** 2
                    + (this_pos[2] - res_inst.pos[2]) ** 2
                )
                if (range is None or dist < range) and dist < min_dist:
                    min_dist = dist
                    closest_pos = res_inst.pos
        return closest_pos

    def gen_explore_task(self, task_instance_names: List[str]) -> None:
        """查看是否有需要生成的探索任务"""

        def gen_exp_task_at(pos: Tuple[float, float, float]) -> TaskInstance:
            l = self.data_server.filter_data(
                lambda x: x.name == "explore_res_task_type", TaskType
            )
            if len(l) == 0:
                # 探索任务类型不存在，创建一个新的
                subtask_type = SubtaskType(
                    name="explore_res",
                    required_skill="local_explore",
                    dep_subtask_types=[],
                    target="this",
                    required_resource="",
                )
                task_type = TaskType(
                    name="explore_res",
                    basic_required_skills=["local_explore"],
                    scheme_types=[[subtask_type.name]],
                    dep_task_types=None,
                    to_be_comp=False,
                )
                self.data_server.set_data(subtask_type.name, subtask_type, False, False)
                self.data_server.set_data(task_type.name, task_type, False, False)

            task = TaskInstance(
                name=f"exp_res_{uuid.uuid4().hex[:6]}",
                task_type="explore_res",
                scheme_instances=[],
                dep_task_instances=[],
                pos=pos,
                allocated_edge=None,
                exp_generated=True,
            )
            return task

        new_buffer: List[str] = []
        # 1. 获取当前buffer中的任务
        for task_instance_name in task_instance_names:
            if "global_exp" in task_instance_name:
                new_buffer.append(task_instance_name)
                continue
            task_instance: TaskInstance = self.data_server.get_data(
                task_instance_name, TaskInstance
            )
            if task_instance.exp_generated:
                new_buffer.append(task_instance_name)
                continue
            exp_required = False

            # 2. 检查资源与目标满足情况
            task_type: TaskType = self.data_server.get_data(
                task_instance.task_type, TaskType
            )
            for scheme_type in task_type.scheme_types:
                for subtask_type_name in scheme_type:
                    subtask_type: SubtaskType = self.data_server.get_data(
                        subtask_type_name, SubtaskType
                    )

                    if subtask_type.target != "this":
                        target_pos = self._search_resource(
                            subtask_type.target, task_instance.pos, 3
                        )
                        if target_pos is None:
                            exp_required = True
                            break

                    if subtask_type.required_resource != "":
                        res_pos = self._search_resource(
                            subtask_type.required_resource, task_instance.pos
                        )
                        if res_pos is None:
                            exp_required = True
                            break
                if exp_required:
                    break

            # 3. 生成探索子任务，其他子任务依赖这个子任务
            if exp_required:
                # 3.1 生成探索任务
                exp_task = gen_exp_task_at(task_instance.pos)
                self.data_server.set_data(exp_task.name, exp_task, False, False)

                # 3.2 将探索任务添加到当前任务的依赖列表中
                task_instance.dep_task_instances.append(exp_task.name)
                self.data_server.set_data(
                    task_instance.name, task_instance, False, False
                )

                # 3.3 将探索任务添加到buffer中
                new_buffer.append(exp_task.name)
            task_instance.exp_generated = True
            new_buffer.append(task_instance_name)

        task_instance_names.clear()
        task_instance_names.extend(new_buffer)

    def instanciate_schemes(self, task_instance: TaskInstance) -> None:
        """实例化方案，不能直接实例化的方案将被忽略。若所有方案都因资源缺失被忽略，则自动去除缺失资源的步骤，选择删减最少的方案。"""
        scheme_types = self.data_server.get_data(
            task_instance.task_type, TaskType
        ).scheme_types
        this_pos = task_instance.pos

        scheme_instances: List[List[SubtaskInstance]] = []
        invalid_steps_per_scheme: List[Tuple[int, List[SubtaskInstance], List[str]]] = []  # (去掉的步骤数, 剩余步骤, 被去掉的subtask_type_name)
        for scheme_type in scheme_types:
            is_valid_scheme = True
            scheme_instance: List[SubtaskInstance] = []
            local_id_2_global_id: Dict[str, str] = {}
            removed_steps: List[str] = []
            for subtask_type_name in scheme_type:
                if "global_exp" in subtask_type_name:
                    subtask_names: List[str] = []
                    x_min, y_min, x_max, y_max, z, block_size = map(
                        float, self.exp_task_config.split(",")
                    )
                    x_range = int((x_max - x_min) / block_size)
                    y_range = int((y_max - y_min) / block_size)
                    for i in range(x_range):
                        for j in range(y_range):
                            x = x_min + i * block_size
                            y = y_min + j * block_size
                            subtask: SubtaskInstance = SubtaskInstance(
                                name=f"global_exp_{i}_{j}",
                                required_skill="global_explore",
                                dep_subtask_types=[],
                                target_pos=(x, y, z),
                                duration=0,
                                allocated_end="",
                                recommended_dep=None,
                            )
                            subtask_names.append(subtask.name)
                            self.data_server.set_data(
                                subtask.name, subtask, False, False
                            )
                    task_instance.scheme_instances = [subtask_names]
                    return

                subtask_type = self.data_server.get_data(subtask_type_name, SubtaskType)

                if subtask_type.target == "this":
                    target_pos = this_pos
                else:
                    target_pos = self._search_resource(subtask_type.target, this_pos, 3)
                    if target_pos is None:
                        is_valid_scheme = False
                        removed_steps.append(subtask_type_name)
                        continue  # 不 break，继续尝试后续步骤

                if subtask_type.required_resource == "this":
                    res_pos = this_pos
                elif subtask_type.required_resource == "":
                    res_pos = None
                else:
                    res_pos = self._search_resource(
                        subtask_type.required_resource, this_pos
                    )
                    if res_pos is None:
                        is_valid_scheme = False
                        removed_steps.append(subtask_type_name)
                        continue

                # 通过共轭任务来实现 MR
                conjugate_subtask_name = None
                for i in range(subtask_type.required_robot_num):
                    subtask_instance: SubtaskInstance = SubtaskInstance(
                        name=f"{subtask_type.name}_{uuid.uuid4().hex[:6]}",
                        required_skill=subtask_type.required_skill,
                        required_resource=subtask_type.required_resource,
                        target=subtask_type.target,
                        dep_subtask_types=subtask_type.dep_subtask_types,
                        res_pos=res_pos,
                        target_pos=target_pos,
                        allocated_end="",
                        recommended_dep=None,
                        dep_subtask_instances=[],
                        conjugate_subtask=(
                            conjugate_subtask_name if conjugate_subtask_name else None
                        ),
                    )
                    conjugate_subtask_name = subtask_instance.name
                    local_id_2_global_id[subtask_type.name] = subtask_instance.name
                    scheme_instance.append(subtask_instance)

            if not is_valid_scheme:
                # 记录被去掉的步骤和剩余步骤
                valid_subtasks = [s for s in scheme_instance if s.name.split('_')[0] not in removed_steps]
                invalid_steps_per_scheme.append((len(removed_steps), valid_subtasks, removed_steps))
                continue
            else:
                scheme_instances.append(scheme_instance)

            # Handle dependency between subtasks
            for subtask_instance in scheme_instance:
                for dep_subtask_type in subtask_instance.dep_subtask_types:
                    if dep_subtask_type not in local_id_2_global_id:
                        raise ValueError(
                            f"SubtaskAllocServer: {subtask_instance.name} has a dependency on {dep_subtask_type}, but it is not in the local ID to global ID mapping. \n Local ID to Global ID: {local_id_2_global_id}"
                        )
                    subtask_instance.dep_subtask_instances.append(
                        local_id_2_global_id[str(dep_subtask_type)]
                    )

        # 如果所有方案都被忽略，则选择删减最少的方案
        if not scheme_instances and invalid_steps_per_scheme:
            min_removed = min(x[0] for x in invalid_steps_per_scheme)
            best_schemes = [x[1] for x in invalid_steps_per_scheme if x[0] == min_removed]
            scheme_instances = best_schemes

        for scheme_instance in scheme_instances:
            for subtask_instance in scheme_instance:
                self.data_server.set_data(
                    subtask_instance.name, subtask_instance, False, False
                )

        task_instance.scheme_instances = [
            [subtask.name for subtask in scheme_instance]
            for scheme_instance in scheme_instances
        ]

    def allocate_subtasks(
        self, subtasks: List[SubtaskInstance]
    ) -> Tuple[Dict[str, List[SubtaskInstance]], float]:
        if "global_exp" in subtasks[0].name:
            # 为每个机器人初始化一个分配结果列表
            remaining = subtasks.copy()
            drone_positions = {
                end_id: end_data.cur_pos for end_id, end_data in self.end_datas.items()
            }
            alloc_map: Dict[str, List[SubtaskInstance]] = {
                end_id: [] for end_id in drone_positions
            }

            # 逐步给最近的子任务分配给各个机器人
            while remaining:
                for end_id, pos in drone_positions.items():
                    if not remaining:
                        break
                    curr_pos = cast(Tuple[float, float, float], pos)
                    closest = min(
                        remaining,
                        key=lambda s: math.sqrt(
                            (curr_pos[0] - s.target_pos[0]) ** 2
                            + (curr_pos[1] - s.target_pos[1]) ** 2
                            + (curr_pos[2] - s.target_pos[2]) ** 2
                        ),
                    )
                    # 记录分配结果
                    closest.allocated_end = end_id
                    alloc_map[end_id].append(closest)
                    # 更新当前位置并移除已分配任务
                    drone_positions[end_id] = closest.target_pos
                    remaining.remove(closest)
            # 返回“机器人ID -> 分配子任务列表”字典
            return alloc_map, 1.0
        else:
            return self.milp_adapter.alloc_subtasks(subtasks, self.end_datas)