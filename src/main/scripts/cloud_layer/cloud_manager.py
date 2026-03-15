#! /usr/bin/env python3

import rospy
from typing import Dict, cast, List, Optional
import sys
from enum import Enum, auto
import json

from std_msgs.msg import String
from main.srv import StringSrv, StringSrvRequest, StringSrvResponse
from main.srv import StrListSrv, StrListSrvRequest, StrListSrvResponse

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
    ResourceType,
)
from task_coord_server import TaskCoordServer
from task_comp_server import TaskCompServer


class CloudManager:
    def __init__(self):
        self.name: str = rospy.get_name().lstrip("/")
        self.my_edge_names: list[str] = str(rospy.get_param("~my_edges", "")).split(",")
        self.edge_datas: Dict[str, EdgeData] = {}
        self.world_start_time: float = rospy.get_time()

        # Recorder
        self.recorder_pub = rospy.Publisher("/record_csv", String, queue_size=10)

        # Config
        self.config_path = str(rospy.get_param("/config_path", ""))
        with open(self.config_path, "r") as f:
            self.config = json.load(f)

        # Init GUI
        self.gui_data_server_pub = rospy.Publisher(
            f"/{self.name}/gui/data_server", String, queue_size=1
        )
        self.gui_timer = rospy.Timer(rospy.Duration(1), self._gui_timer_cb)
        self.gui_module_state_pub = rospy.Publisher(
            f"/gui/module_state", String, queue_size=10
        )
        self.gui_comm_pub = rospy.Publisher(
            f"/gui/layer_comm_vis", String, queue_size=10
        )
        self.gui_task_comp_pub = rospy.Publisher(
            f"/{self.name}/gui/task_comp", String, queue_size=10
        )
        self.gui_task_coord_pub = rospy.Publisher(
            f"/{self.name}/gui/task_coord", String, queue_size=10
        )
        self.gui_verification_client = rospy.ServiceProxy(
            f"/{self.name}/gui/verification", StringSrv
        )
        self.gui_assignment_verification_client = rospy.ServiceProxy(
            f"/{self.name}/gui/assignment_verification", StringSrv
        )

        # Init Modules
        self.data_server: DataServer = DataServer(self.name)
        self.task_comp_server: TaskCompServer = TaskCompServer(self.config)
        self.task_coord_server: TaskCoordServer = TaskCoordServer(
            self.config, self.data_server, self.edge_datas
        )
        self.task_comp_buffer: List[str] = []
        self.task_coord_buffer: List[str] = []
        rospy.Timer(rospy.Duration(1), self._task_comp_cb)
        rospy.Timer(rospy.Duration(1), self._task_coord_cb)

        # Cloud-Edge Communication
        self.set_my_cloud_client: Dict[str, rospy.ServiceProxy] = {}
        for edge in self.my_edge_names:
            self.set_my_cloud_client[edge] = rospy.ServiceProxy(
                f"/{edge}/set_my_cloud", StringSrv
            )
            self.set_my_cloud_client[edge].wait_for_service(timeout=20)
            self.gui_comm_pub.publish(f"{self.name},{edge}")
            rospy.sleep(0.1)
            self.set_my_cloud_client[edge].call(StringSrvRequest(self.name))
            self.set_my_cloud_client[edge].close()

        self.alloc_task_client: Dict[str, rospy.ServiceProxy] = {}
        for edge in self.my_edge_names:
            self.alloc_task_client[edge] = rospy.ServiceProxy(
                f"/{edge}/alloc_task", StrListSrv
            )

        # Upload Data
        self.upload_task_type_server = rospy.Service(
            f"/{self.name}/upload_task_type", StrListSrv, self._upload_task_type_cb
        )
        self.upload_task_instance_server = rospy.Service(
            f"/{self.name}/upload_task_instance",
            StrListSrv,
            self._upload_task_instance_cb,
        )
        self.upload_subtask_type_server = rospy.Service(
            f"/{self.name}/upload_subtask_type",
            StrListSrv,
            self._upload_subtask_type_cb,
        )
        self.upload_subtask_instance_server = rospy.Service(
            f"/{self.name}/upload_subtask_instance",
            StrListSrv,
            self._upload_subtask_instance_cb,
        )
        self.upload_resource_instance_server = rospy.Service(
            f"/{self.name}/upload_resource_type",
            StrListSrv,
            self._upload_resource_type_cb,
        )
        self.upload_resource_instance_server = rospy.Service(
            f"/{self.name}/upload_resource_instance",
            StrListSrv,
            self._upload_resource_instance_cb,
        )

        # Get Edge Data
        self.get_edge_data_client: Dict[str, rospy.ServiceProxy] = {}
        for edge in self.my_edge_names:
            self.get_edge_data_client[edge] = rospy.ServiceProxy(
                f"/{edge}/get_edge_data", StringSrv
            )
        rospy.Timer(rospy.Duration(1), self._update_edges_data_cb)

        # Grouping
        self.has_grouped = False
        self.gui_group_info_pub = rospy.Publisher(f"/group_info", String, queue_size=10)
        self.grouping_trigger = rospy.Timer(rospy.Duration(1), self._grouping_cb)

        # Initial Exploration
        self._gen_exp_task()
        # rospy.Timer(rospy.Duration(80), lambda event: self._gen_exp_task(), oneshot=True)
        # rospy.Timer(rospy.Duration(160), lambda event: self._gen_exp_task(), oneshot=True)

    # region Module Timers

    def _task_comp_cb(self, event):
        if any(edge not in self.edge_datas for edge in self.my_edge_names):
            return
        if any(edge.skills == [] for edge in self.edge_datas.values()):
            return
        if not self.task_comp_buffer:
            return
        if not self.has_grouped:
            return
        # 如果 buffer 不为空，则说明有新的 task type 被上传，重新进行 task comprehension

        # Update GUI
        self.gui_module_state_pub.publish(f"{self.name},Task Comprehension,active")
        rospy.sleep(1)

        task_types = self.data_server.filter_data_by_type(TaskType)
        self.task_comp_server.comp_task_types(
            task_types, self.data_server.get_task_type_DAG()
        )
        for task_type in task_types:
            self.data_server.set_data(task_type.name, task_type, False, True)
        self.task_comp_buffer = []

        # Update GUI
        dag = self.data_server.get_task_type_DAG()
        self.gui_task_comp_pub.publish(json.dumps(dag))
        self.gui_module_state_pub.publish(f"{self.name},Task Comprehension,inactive")

    def _task_coord_cb(self, event):
        if any(edge not in self.edge_datas for edge in self.my_edge_names):
            return
        if not self.task_coord_buffer:
            return
        tasks: List[TaskInstance] = []
        # 用 set 去重，避免同名任务多次处理
        buffer_copy = list(set(self.task_coord_buffer))
        to_remove = []
        for task_name in buffer_copy:
            task = self.data_server.get_data(task_name, TaskInstance)
            if task is None:
                raise ValueError(
                    f"Task {task_name} not found in data server."
                )
            # 跳过已分配的任务，避免重复分配
            if getattr(task, 'allocated_edge', None) is not None:
                continue
            task_type = self.data_server.get_data(task.task_type, TaskType)
            if task_type is None:
                raise ValueError(
                    f"Task type {task.task_type} not found in data server."
                )
            if task_type.to_be_comp:
                # 任务必须经过 task comprehension 才能进行 task coordination
                return
            tasks.append(task)

        if not tasks:
            return  # 没有需要分配的任务，直接返回

        # Update GUI
        self.gui_module_state_pub.publish(f"{self.name},Task Coordination,active")
        rospy.sleep(1)

        self.task_coord_server.coord_tasks(tasks)
        for task in tasks:
            if not hasattr(task, "allocated_edge") or not task.allocated_edge:
                raise ValueError(f"Task {task.name} was not allocated to any edge 2222")

        try:
            self.gui_assignment_verification_client.wait_for_service(timeout=1)
            allocation_result = {edge: [] for edge in self.my_edge_names}
            for task in tasks:
                edge = task.allocated_edge
                if edge:
                    allocation_result[edge].append(task.name)
                    to_remove.append(task.name)  # 只记录已分配的任务
            resp = self.gui_assignment_verification_client.call(
                StringSrvRequest(
                    json.dumps(
                        {
                            "module_name": "Task Coordination",
                            "result": allocation_result,
                        }
                    )
                )
            )
            if resp and hasattr(resp, 'data') and resp.data:
                try:
                    new_result = json.loads(resp.data)
                    # new_result: {edge: [task_name, ...], ...}
                    # 先构建 task_name -> edge 的映射
                    task2edge = {}
                    for edge, task_list in new_result.items():
                        for tname in task_list:
                            task2edge[tname] = edge
                    for task in tasks:
                        if task.name in task2edge:
                            task.allocated_edge = task2edge[task.name]
                except Exception as e:
                    rospy.logwarn(f"Failed to apply GUI allocation result: {e}")
        except rospy.ROSException as e:
            rospy.logwarn(f"GUI verification service not available: {e}")

        # Update GUI
        self.gui_task_coord_pub.publish(str([task.to_json() for task in tasks]))
        self.gui_module_state_pub.publish(f"{self.name},Task Coordination,inactive")

        for edge in self.my_edge_names:
            allocated_tasks: List[str] = [
                TaskInstance.to_json(task)
                for task in tasks
                if task.allocated_edge == edge
            ]
            if not allocated_tasks:
                continue
            self.alloc_task_client[edge].wait_for_service(timeout=20)

            self.gui_comm_pub.publish(f"{self.name},{edge}")

            self.alloc_task_client[edge].call(StrListSrvRequest(allocated_tasks))

        # 统一移除已分配的任务，避免重复分配
        for task_name in to_remove:
            if task_name in self.task_coord_buffer:
                self.task_coord_buffer.remove(task_name)

    # endregion

    def _gen_exp_task(self) -> None:
        exp_task_type: TaskType = TaskType(
            name="global_exp",
            basic_required_skills=["global_explore"],
            scheme_types=[],
            to_be_comp=False,
        )
        self.data_server.set_data(exp_task_type.name, exp_task_type, False, True)
        exp_task: TaskInstance = TaskInstance(
            name=f"global_exp_{rospy.get_time()}",
            task_type=exp_task_type.name,
            scheme_instances=[],
            dep_task_instances=[],
            allocated_edge=None,
        )
        self.data_server.set_data(exp_task.name, exp_task, False, True)
        self.task_comp_buffer.append(exp_task_type.name)  # * append to buffer here
        self.task_coord_buffer.append(exp_task.name)  # * append to buffer here

    # region Callbacks

    def _update_edges_data_cb(self, event):
        for edge in self.my_edge_names:
            self.get_edge_data_client[edge].wait_for_service(timeout=20)
            resp: StringSrvResponse = self.get_edge_data_client[edge].call(
                StringSrvRequest(self.name)
            )
            self.edge_datas[edge] = EdgeData.from_json(resp.data)
            self.data_server.set_data(
                self.edge_datas[edge].name, self.edge_datas[edge], False, True
            )

    # region Upload Cbs

    def _upload_task_type_cb(self, req: StrListSrvRequest) -> StrListSrvResponse:
        task_types = [TaskType.from_json(task_type) for task_type in req.data]
        for task_type in task_types:
            self.data_server.set_data(task_type.name, task_type, False, True)
            self.task_comp_buffer.append(task_type.name)  # * append to buffer here
        return StrListSrvResponse(True, [])

    def _upload_task_instance_cb(self, req: StrListSrvRequest) -> StrListSrvResponse:
        task_instances = [
            TaskInstance.from_json(task_instance) for task_instance in req.data
        ]
        for task_instance in task_instances:
            self.data_server.set_data(task_instance.name, task_instance, False, True)
            # 只在 buffer 中不存在时才添加，避免重复
            if task_instance.name not in self.task_coord_buffer:
                self.task_coord_buffer.append(task_instance.name)
            else:
                rospy.logerr(
                    f"Task instance {task_instance.name} already exists in the buffer."
                )
        return StrListSrvResponse(True, [])

    def _upload_subtask_type_cb(self, req: StrListSrvRequest) -> StrListSrvResponse:
        subtask_types = [
            SubtaskType.from_json(subtask_type) for subtask_type in req.data
        ]
        for subtask_type in subtask_types:
            self.data_server.set_data(subtask_type.name, subtask_type, False, True)
        return StrListSrvResponse(True, [])

    def _upload_subtask_instance_cb(self, req: StrListSrvRequest) -> StrListSrvResponse:
        subtask_instances = [
            SubtaskInstance.from_json(subtask_instance) for subtask_instance in req.data
        ]
        for subtask_instance in subtask_instances:
            self.data_server.set_data(subtask_instance.name, subtask_instance, False, True)
        return StrListSrvResponse(True, [])

    def _upload_resource_type_cb(self, req: StrListSrvRequest) -> StrListSrvResponse:
        resource_types = [
            ResourceType.from_json(resource_type) for resource_type in req.data
        ]
        for resource_type in resource_types:
            self.data_server.set_data(resource_type.name, resource_type, False, True)
        return StrListSrvResponse(True, [])

    def _upload_resource_instance_cb(
        self, req: StrListSrvRequest
    ) -> StrListSrvResponse:
        resource_instances = [
            ResourceInstance.from_json(resource_instance)
            for resource_instance in req.data
        ]
        for resource_instance in resource_instances:
            self.data_server.set_data(resource_instance.name, resource_instance, False, True)
        return StrListSrvResponse(True, [])

    # endregion

    # region Visualization publishing

    def _gui_timer_cb(self, event):
        msg = String(data=self.data_server.to_json())
        self.gui_data_server_pub.publish(msg)

    # endregion

    # region Grouping

    def _grouping_cb(self, event):
        tasks = self.data_server.filter_data_by_type(TaskInstance)
        resources = self.data_server.filter_data_by_type(ResourceInstance)
        if len(tasks) + len(resources) < 0:
            return
        group_info = self._grouping_algorithm(tasks)
        self.gui_group_info_pub.publish(json.dumps(group_info))
        self.has_grouped = True
        self.grouping_trigger.shutdown()

    def _grouping_algorithm(
        self, tasks: List[TaskInstance]
    ) -> Dict[str, Dict[str, List[str]]]:
        if not "hard" in self.config_path:
            group_info = {
                "cloud": {
                "edge_exp": ["end_101"],
                "edge_1": ["end_1", "end_2", "end_3", "end_4"],
                }
            }
        else:
            group_info = {
                "cloud": {
                "edge_exp": ["end_101"],
                "edge_1": ["end_1", "end_2", "end_3", "end_4", "end_5", "end_6", "end_7", "end_8", "end_9", "end_10"],
                }
            }
        try:
            self.gui_assignment_verification_client.wait_for_service(timeout=1)
            resp: StringSrvResponse = self.gui_assignment_verification_client.call(
                StringSrvRequest(
                    json.dumps(
                        {
                            "module_name": "Grouping",
                            "result": group_info["cloud"],
                        }
                    )
                )
            )
            # edited_group_info = json.loads(resp.data) # TODO 返回的字符串格式无法解析
            return group_info
        except rospy.ROSException as e:
            rospy.logwarn(f"GUI verification service not available: {e}")
        return group_info


if __name__ == "__main__":
    rospy.init_node("cloud_manager", anonymous=True)
    CloudManager()
    rospy.spin()
