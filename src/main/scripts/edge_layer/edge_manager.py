#! /usr/bin/env python3

import rospy
import sys
from typing import Dict, List, Tuple, Optional
import json

from sensor_msgs.msg._Image import Image
from std_msgs.msg import String
from main.srv import StringSrv, StringSrvRequest, StringSrvResponse
from main.srv import StrListSrv, StrListSrvRequest, StrListSrvResponse
from main.srv import ImageSrv, ImageSrvRequest, ImageSrvResponse

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
from subtask_alloc_server import SubtaskAllocServer
from global_info_server import GlobalInfoServer
from task_gen_server import TaskGenServer
from subtask_gen_server import SubtaskGenServer


class EdgeManager:
    def __init__(self):
        self.data: EdgeData = EdgeData(
            name=rospy.get_name().lstrip("/"),
            related_end_names=(
                str(rospy.get_param("~my_ends", "")).split(",")
                if rospy.get_param("~my_ends", "")
                else []
            ),
            related_cloud_name=None,
            end_time=0,
        )
        self.end_datas: Dict[str, EndData] = {}

        # Recorder
        self.record_csv_pub = rospy.Publisher("/record_csv", String, queue_size=10)
        self.record_jsonl_pub = rospy.Publisher("/record_jsonl", String, queue_size=10)

        # Config
        config_path = str(rospy.get_param("/config_path", ""))
        with open(config_path, "r") as f:
            self.config = json.load(f)

        # Init GUI

        # GUI: Edge Interface
        self.gui_global_info_pub = rospy.Publisher(
            f"/{self.data.name}/gui/global_info", String, queue_size=2
        )
        self.gui_global_info_image_pub = rospy.Publisher(
            f"/{self.data.name}/gui/global_info_image", Image, queue_size=2
        )
        self.gui_task_gen_pub = rospy.Publisher(
            f"/{self.data.name}/gui/task_generation", String, queue_size=10
        )
        self.gui_subtask_gen_pub = rospy.Publisher(
            f"/{self.data.name}/gui/subtask_generation", String, queue_size=2
        )
        self.gui_data_server_pub = rospy.Publisher(
            f"/{self.data.name}/gui/data_server", String, queue_size=2
        )
        self.gui_img_pub = rospy.Publisher(
            f"/{self.data.name}/gui/overlay_image", Image, queue_size=2
        )
        self.gui_timer = rospy.Timer(rospy.Duration(1), self._gui_timer_cb)
        self.gui_verification_client = rospy.ServiceProxy(
            f"{self.data.name}/gui/verification", StringSrv
        )
        self.gui_image_verification_client = rospy.ServiceProxy(
            f"{self.data.name}/gui/image_verification", ImageSrv
        )
        self.gui_llm_client = rospy.ServiceProxy(
            f"{self.data.name}/gui/llm_chat", StringSrv
        )
        self.gui_multi_select_client = rospy.ServiceProxy(
            f"{self.data.name}/gui/multi_select", StrListSrv
        )
        self.gui_single_select_client = rospy.ServiceProxy(
            f"{self.data.name}/gui/single_select", StringSrv
        )
        self.gui_assignment_verification_client = rospy.ServiceProxy(
            f"/{self.data.name}/gui/assignment_verification", StringSrv
        )
        self.gui_property_verification_client = rospy.ServiceProxy(
            f"/{self.data.name}/gui/property_verification", StringSrv
        )

        # GUI: Data Flow
        self.module_state_pub = rospy.Publisher(
            f"/gui/module_state", String, queue_size=10
        )
        self.gui_comm_pub = rospy.Publisher(
            f"/gui/layer_comm_vis", String, queue_size=10
        )

        # Init Modules
        self.detection_enabled = rospy.get_param("~detection_enabled", True)
        self.context_analysis_enabled = rospy.get_param("~context_analysis_enabled", True)
        self.subtask_alloc_enabled = rospy.get_param("~subtask_alloc_enabled", True)

        # Servers
        self.data_server = DataServer(self.data.name)
        self.global_info_server = GlobalInfoServer(self.data.name)
        self.task_gen_server = TaskGenServer(self.config)
        self.subtask_gen_server = SubtaskGenServer(
            self.config, self.gui_llm_client, self.data_server
        )
        self.subtask_alloc_server = SubtaskAllocServer(
            self.data, self.end_datas, self.data_server, self.config
        )

        self.global_info_buffer: List[Dict] = []
        self.task_gen_buffer: List[Tuple[str,Tuple]] = []

        # Timers
        rospy.Timer(rospy.Duration(1), self._global_info_cb)
        rospy.Timer(rospy.Duration(1), self._task_gen_cb)
        rospy.Timer(rospy.Duration(1), self._subtask_gen_cb)
        rospy.Timer(rospy.Duration(1), self._subtask_alloc_cb)

        # Init Comm

        # Cloud-Edge Communication
        self.set_my_cloud_server = rospy.Service(
            f"/{self.data.name}/set_my_cloud", StringSrv, self._set_my_cloud_cb
        )
        self.get_data_server = rospy.Service(
            f"/{self.data.name}/get_edge_data",
            StringSrv,
            lambda _: StringSrvResponse(True, self.data.to_json()),
        )
        self.alloc_task_server = rospy.Service(
            f"/{self.data.name}/alloc_task", StrListSrv, self._cloud_alloc_task_cb
        )

        # Edge-End Communication
        if not self.data.related_end_names:
            self._group_info_sub = rospy.Subscriber(
                f"/group_info", String, self._group_info_cb
            )
        else:
            self._init_my_ends(self.data.related_end_names)

    # region Grouping

    def _group_info_cb(self, msg: String):
        """format:
        "cloud": {
            "edge_name": ["end_name1", "end_name2", ...],
        }
        """
        group_info = json.loads(msg.data)
        if self.data.name not in group_info["cloud"]:
            return
        else:
            self.data.related_end_names = group_info["cloud"][self.data.name]
            if not self.data.related_end_names:
                rospy.logerr(f"{self.data.name} has no related ends.")
                return
            self.data.related_cloud_name = msg.data.split(",")[0]
            self._init_my_ends(self.data.related_end_names)

    def _init_my_ends(self, end_names: List[str]):
        self.set_my_edge_client: Dict[str, rospy.ServiceProxy] = {}
        for end in end_names:
            self.set_my_edge_client[end] = rospy.ServiceProxy(
                f"/{end}/set_my_edge", StringSrv
            )
            self.set_my_edge_client[end].wait_for_service(timeout=1)
            self.gui_comm_pub.publish(f"{self.data.name},{end}")
            rospy.sleep(0.1)
            self.set_my_edge_client[end].call(StringSrvRequest(self.data.name))
            self.set_my_edge_client[end].close()

        self.alloc_subtask_client: Dict[str, rospy.ServiceProxy] = {}
        for end in end_names:
            self.alloc_subtask_client[end] = rospy.ServiceProxy(
                f"/{end}/alloc_subtask", StrListSrv
            )
        self.upload_photo_server = rospy.Service(
            f"/{self.data.name}/upload_photo", ImageSrv, self._upload_photo_cb
        )
        self.subtask_exec_state_sub = rospy.Subscriber(
            f"/{self.data.name}/subtask_exec_state", String, self._subtask_exec_state_cb
        )

        # Get End Data
        self.get_end_data_client: Dict[str, rospy.ServiceProxy] = {}
        for end in end_names:
            self.get_end_data_client[end] = rospy.ServiceProxy(
                f"/{end}/get_end_data", StringSrv
            )
        rospy.Timer(rospy.Duration(1), self._update_ends_data_cb)

    # endregion

    # region Comm Cbs

    def _update_ends_data_cb(self, event):
        for end in self.data.related_end_names:
            self.get_end_data_client[end].wait_for_service(timeout=1)
            resp: StringSrvResponse = self.get_end_data_client[end].call(
                StringSrvRequest(self.data.name)
            )
            self.end_datas[end] = EndData.from_json(resp.data)
            self.data_server.set_data(
                self.end_datas[end].name, self.end_datas[end], False, True
            )
        self.data.skills = []
        for end in self.end_datas.values():
            end_skills = self.config["agent_types"][end.agent_type]["skills"]
            self.data.skills.extend(end_skills)
        self.data.skills = list(set(self.data.skills))

        # Update task states: if any scheme's all subtasks are done, mark task as done
        for task in self.data_server.filter_data_by_type(TaskInstance):
            if not task or not task.scheme_instances:
                continue
            for scheme in task.scheme_instances:
                if all(
                    self.data_server.get_data(sub_name, SubtaskInstance).state == "done"
                    for sub_name in scheme
                ):
                    task.state = "done"
                    break

    def _set_my_cloud_cb(self, msg: StringSrvRequest) -> StringSrvResponse:
        rospy.loginfo(f"{self.data.name} set my cloud: {msg.data}")
        self.data.related_cloud_name = msg.data
        self.data_server.set_search_client(self.data.related_cloud_name)
        self.upload_task_type_client = rospy.ServiceProxy(
            f"/{self.data.related_cloud_name}/upload_task_type", StrListSrv
        )
        self.upload_task_instance_client = rospy.ServiceProxy(
            f"/{self.data.related_cloud_name}/upload_task_instance", StrListSrv
        )
        self.upload_resource_type_client = rospy.ServiceProxy(
            f"/{self.data.related_cloud_name}/upload_resource_type", StrListSrv
        )
        self.upload_resource_instance_client = rospy.ServiceProxy(
            f"/{self.data.related_cloud_name}/upload_resource_instance", StrListSrv
        )
        return StringSrvResponse(True, self.data.name)

    def _cloud_alloc_task_cb(self, msg: StrListSrvRequest) -> StrListSrvResponse:
        rospy.loginfo(f"{self.data.name} is allocatted task: {msg.data}")
        tasks = msg.data
        for task_str in tasks:
            task: TaskInstance = TaskInstance.from_json(task_str)
            self.data.subtask_gen_buffer.append(task.name)
            self.data_server.set_data(task.name, task, True, False)
        return StrListSrvResponse(True, [])

    def _upload_photo_cb(self, msg: ImageSrvRequest) -> ImageSrvResponse:
        image: Image = msg.image
        img_x, img_y, img_z, image_name = msg.message.split(",")
        img_x = float(img_x)
        img_y = float(img_y)
        img_z = float(img_z)
        pos = (img_x, img_y, img_z)
        self.global_info_buffer.append(
            {
                "image": image,
                "name": image_name,
                "pos": pos,
            }
        )
        image.header.frame_id = f"{img_x},{img_y}"
        return ImageSrvResponse(True, Image(), "")

    def _subtask_exec_state_cb(self, msg: String):
        """format: subtask_name,state"""
        subtask_name, state = msg.data.split(",")
        if state in ["todo", "doing", "done"]:
            subtask_instance = self.data_server.get_data(subtask_name, SubtaskInstance)
            if subtask_instance is None:
                raise ValueError(f"Subtask {subtask_name} not found in data server.")
            subtask_instance.state = state
        else:
            raise ValueError(f"Invalid state: {state}")

    # endregion

    # region Module Timers

    def _global_info_cb(self, event):
        if not self.global_info_buffer:
            return

        # Update GUI
        self.module_state_pub.publish(f"{self.data.name},Global Info,active")
        start_time = rospy.Time.now()

        # Generate context info
        image_info = self.global_info_buffer.pop(0)
        image = image_info["image"]
        image_name = image_info["name"]
        pos = image_info["pos"]

        if self.detection_enabled:
            detected_image, context_info = self.global_info_server.get_context(
                image, image_name
            )  # actually return feature name
        else:
            detected_image = image
            context_info = ""

        try:
            img_request = ImageSrvRequest()
            img_request.image = detected_image
            img_request.message = json.dumps(
                {
                    "module_name": "Global Info",
                    "result": context_info,
                }
            )
            self.gui_image_verification_client.wait_for_service(timeout=1)
            resp: ImageSrvResponse = self.gui_image_verification_client.call(img_request)
            interaction_count = 0 if context_info == resp.message else 1
            context_info = resp.message
        except rospy.ROSException as e:
            rospy.logwarn(f"Service call failed: {e}")

        self.task_gen_buffer.append((context_info, pos))

        # Update GUI
        self.module_state_pub.publish(f"{self.data.name},Global Info,inactive")
        self.gui_global_info_pub.publish(context_info)
        self.gui_global_info_image_pub.publish(detected_image)
        duration = rospy.Time.now() - start_time
        
        self.record_csv_pub.publish(
            f"{self.data.name}_detection,{image_name},{context_info},{duration.to_sec()},{interaction_count}"
        )

    def _task_gen_cb(self, event):
        if not self.task_gen_buffer:
            return
        # Update GUI
        self.module_state_pub.publish(f"{self.data.name},Task Generation,active")

        # Get task generation result
        context_info = self.task_gen_buffer[0]
        pos = context_info[1]
        feature_label = context_info[0]
        resource_types = self.data_server.filter_data_by_type(ResourceType)
        task_types = self.data_server.filter_data_by_type(TaskType)
        if feature_label in [
            resource_types[i].name for i in range(len(resource_types))
        ]:
            type = "resource"
            context_analysis = ""
        elif feature_label in [task_types[i].name for i in range(len(task_types))]:
            type = "task"
            context_analysis = ""
        else:
            # New Feature Type
            if self.context_analysis_enabled:
                try:
                    start_time = rospy.Time.now()
                    self.gui_llm_client.wait_for_service(timeout=1)
                    llm_resp: StringSrvResponse = self.gui_llm_client.call(
                        StringSrvRequest(
                            json.dumps(
                                {
                                    "prompt": {
                                        "instruction": {
                                            "description": "Please classify the input noun according to the definitions provided",
                                            "task_definition": "A hazardous scenario requiring handling or an emergency response objective, including phenomena such as combustion, leakage risks, threatened personnel, or preventive maintenance measures implemented on critical equipment; emphasizes specific actions that need to be carried out",
                                            "resource_definition": "Disposal tools, protective materials, and supporting facilities that can be directly utilized, including physical devices, chemical substances, static protective installations, and medical aid locations; refers to specific objects, materials, or sites that are immediately available for use",
                                        },
                                        "input_noun": feature_label,
                                        "Please output in the following JSON format": {
                                            "analysis": "Brief analysis of the reasoning",
                                            "classification": "task/resource",
                                        },
                                    },
                                }
                            )
                        )
                    )
                    resp_dict = json.loads(llm_resp.data)
                    type: str = resp_dict["classification"]
                    context_analysis: str = resp_dict["analysis"]
                    duration = rospy.Time.now() - start_time
                    self.record_csv_pub.publish(
                        f"{self.data.name}_context_analysis,{feature_label},{type},{duration.to_sec()}"
                    )
                except Exception as e:
                    rospy.logwarn(f"Service call failed: {e}")
                    type = ""
                    context_analysis = ""
            else:
                try:
                    start_time = rospy.Time.now()
                    self.gui_single_select_client.wait_for_service(timeout=1)
                    resp: StringSrvResponse = self.gui_single_select_client.call(
                        StringSrvRequest(
                            json.dumps(
                                {
                                    "question": f"What is the type of '{feature_label}'?",
                                    "options": ["task", "resource"],
                                }
                            )
                        )
                    )
                    if resp.success:
                        type = resp.data
                    else:
                        type = "task" # Default to task if user cancels
                    context_analysis = ""
                    duration = rospy.Time.now() - start_time
                    self.record_csv_pub.publish(
                        f"{self.data.name}_context_analysis,{feature_label},{type},{duration.to_sec()}"
                    )
                except rospy.ROSException as e:
                    rospy.logwarn(f"Service call failed: {e}")
                    type = ""
                    context_analysis = ""

        task_gen_result = self.task_gen_server.gen_task(
            feature_label,
            pos,
            type,
            context_analysis,
            self.data_server.get_task_type_DAG(),
            self.data_server.filter_data_by_type(ResourceType),
        )

        # Update GUI
        task_gen_result_dicts = []
        for item in task_gen_result:
            if isinstance(
                item, (TaskType, TaskInstance, ResourceType, ResourceInstance)
            ):
                task_gen_result_dicts.append(json.loads(item.to_json()))
            else:
                raise ValueError(f"Unknown feature type: {item}")

        self.module_state_pub.publish(f"{self.data.name},Task Generation,inactive")
        for item in task_gen_result:
            self.gui_task_gen_pub.publish(item.to_json())
        self.gui_comm_pub.publish(f"{self.data.related_cloud_name},{self.data.name}")
        rospy.sleep(0.1)

        for item in task_gen_result:
            self.data_server.set_data(item.name, item, True, False)
            if isinstance(item, TaskType):
                self.upload_task_type_client.wait_for_service(timeout=1)
                self.upload_task_type_client.call(StrListSrvRequest([item.to_json()]))
            elif isinstance(item, TaskInstance):
                self.upload_task_instance_client.wait_for_service(timeout=1)
                self.upload_task_instance_client.call(
                    StrListSrvRequest([item.to_json()])
                )
            elif isinstance(item, ResourceType):
                # task_type_to_regen_schemes = []
                # try:
                #     self.gui_multi_select_client.wait_for_service(timeout=1)
                #     task_types = self.data_server.filter_data_by_type(TaskType)
                #     task_types = [t for t in task_types if "global_exp" not in t.name]
                #     if task_types:
                #         multi_select_resp: StrListSrvResponse = self.gui_multi_select_client.call(
                #             StrListSrvRequest([task_type.name for task_type in task_types])
                #         )
                #         task_type_to_regen_schemes = multi_select_resp.data
                # except rospy.ROSException as e:
                #     rospy.logwarn(f"Service call failed: {e}")
                #     task_type_to_regen_schemes = []
                # for task_type_name in task_type_to_regen_schemes:
                #     task_type = self.data_server.get_data(task_type_name, TaskType)
                #     task_type.scheme_types.clear()
                #     self.subtask_gen_server.gen_scheme(task_type)
                
                self.upload_resource_type_client.wait_for_service(timeout=1)
                self.upload_resource_type_client.call(
                    StrListSrvRequest([item.to_json()])
                )
            elif isinstance(item, ResourceInstance):
                self.upload_resource_instance_client.wait_for_service(timeout=1)
                self.upload_resource_instance_client.call(
                    StrListSrvRequest([item.to_json()])
                )
            else:
                raise ValueError(f"Unknown feature type: {item}")
        self.task_gen_buffer.pop(0)

    def _subtask_gen_cb(self, event):
        if any(end not in self.end_datas for end in self.data.related_end_names):
            return
        if any(end_data.cur_pos is None for end_data in self.end_datas.values()):
            return
        if not self.data.subtask_gen_buffer:
            return
        task_name = self.data.subtask_gen_buffer[0]
        task = self.data_server.get_data(task_name, TaskInstance)
        task_type = self.data_server.get_data(task.task_type, TaskType)

        if task_type.scheme_types:
            # 已有任务类型不进行子任务生成
            self.data.subtask_alloc_buffer.append(task.name)
            self.data.subtask_gen_buffer.pop(0)
            return

        # 新任务类型，生成子任务

        # Update GUI
        self.module_state_pub.publish(f"{self.data.name},Subtask Generation,active")
        rospy.sleep(0.1)

        # Generate subtasks
        start_time = rospy.Time.now()
        self.subtask_gen_server.gen_scheme(task_type)
        duration = rospy.Time.now() - start_time
        if "global_exp" not in task_type.name:
            scheme_dict = {}
            for i, scheme_type in enumerate(task_type.scheme_types):
                scheme_dict[f"Scheme_{i+1}"] = {}
                for j, subtask_type_name in enumerate(scheme_type):
                    subtask_type = self.data_server.get_data(
                        subtask_type_name, SubtaskType
                    )
                    scheme_dict[f"Scheme_{i+1}"][f"Step_{j}"] = json.loads(subtask_type.to_json())
            self.record_jsonl_pub.publish(
                json.dumps(
                    {
                        "filename": f"{self.data.name}_subtask_gen",
                        "task_type_name": task_type.name,
                        "schemes": scheme_dict,
                        "duration": duration.to_sec(),
                    }
                )
            )
        self.upload_task_type_client.call(StrListSrvRequest([task_type.to_json()]))

        # Update GUI
        self.module_state_pub.publish(f"{self.data.name},Subtask Generation,inactive")
        self.gui_subtask_gen_pub.publish(task_type.to_json())
        self.data.subtask_alloc_buffer.append(task.name)
        self.data.subtask_gen_buffer.pop(0)

    def _subtask_alloc_cb(self, event):
        if self.global_info_buffer or self.task_gen_buffer or self.data.subtask_gen_buffer:
            # 确保新发现的资源等已经考虑
            return
        if any(end not in self.end_datas for end in self.data.related_end_names):
            return
        if any(end_data.cur_pos is None for end_data in self.end_datas.values()):
            return
        if not self.data.subtask_alloc_buffer:
            return
        if all(
            end.todo_subtask_buffer or end.doing_subtask
            for end in self.end_datas.values()
        ):
            return

        # Update GUI
        self.module_state_pub.publish(f"{self.data.name},Subtask Ins. & Alloc.,active")

        # 探索任务生成
        self.subtask_alloc_server.gen_explore_task(self.data.subtask_alloc_buffer)

        # 分配前置任务已完成且优先级最高的任务
        candidate_tasks = []
        for task_name in self.data.subtask_alloc_buffer:
            task = self.data_server.get_data(task_name, TaskInstance)
            # 检查前置任务是否全部完成
            pre_done = True
            for pre_task_name in task.dep_task_instances:
                pre_task = self.data_server.get_data(pre_task_name, TaskInstance)
                if not pre_task or pre_task.state != "done":
                    pre_done = False
                    break
            if pre_done:
                task_type_obj = self.data_server.get_data(task.task_type, TaskType)
                priority = task_type_obj.priority
                candidate_tasks.append((priority, task_name))
        if not candidate_tasks:
            # 没有可分配的任务
            return
        # 选择优先级最高的任务（数值越大优先级越高）
        selected_task_name = max(candidate_tasks, key=lambda x: x[0])[1]
        task_name = selected_task_name

        task = self.data_server.get_data(task_name, TaskInstance)
        task_type = self.data_server.get_data(task.task_type, TaskType)
        if task_type.scheme_types is None:
            rospy.logerr(f"Task {task_name} has no scheme types.")
            self.data.subtask_alloc_buffer.remove(task_name)

        # 实例化方案
        self.subtask_alloc_server.instanciate_schemes(task)
        if not task.scheme_instances:
            rospy.logerr(f"Task {task_name} has no valid scheme instances.")
            self.data.subtask_alloc_buffer.remove(task_name)

        # 子任务分配

        # # 调用 property_verification 服务，编辑所有子任务属性
        # try:
        #     all_subtasks = {}
        #     for scheme in task.scheme_instances:
        #         for subtask_name in scheme:
        #             subtask = self.data_server.get_data(subtask_name, SubtaskInstance)
        #             attr_dict = {
        #                 "required_skill": subtask.required_skill,
        #                 "required_resource": subtask.required_resource,
        #                 "target": subtask.target,
        #                 "res_pos": subtask.res_pos,
        #                 "target_pos": subtask.target_pos,
        #                 "dep_subtask_types": subtask.dep_subtask_types,
        #                 "duration": subtask.duration,
        #             }
        #             all_subtasks[subtask_name] = attr_dict
        #     self.gui_property_verification_client.wait_for_service(timeout=1)
        #     resp: StringSrvResponse = self.gui_property_verification_client.call(
        #         StringSrvRequest(json.dumps(all_subtasks))
        #     )
        #     edited_subtasks = json.loads(resp.data)
        #     for subtask_name, edited_subtask in edited_subtasks.items():
        #         subtask_instance = self.data_server.get_data(subtask_name, SubtaskInstance)
        #         if subtask_instance:
        #             for key, value in edited_subtask.items():
        #                 setattr(subtask_instance, key, value)
        # except Exception as e:
        #     rospy.logwarn(f"Property verification service call failed: {e}")

        # 如果有强制预定方案，则直接选择预定方案
        choose_scheme = self.config["feature_instances"].get(task.name, "")
        if choose_scheme:
            choose_scheme = choose_scheme.get("choose_scheme", "")
            if choose_scheme:
                task.scheme_instances = [task.scheme_instances[int(choose_scheme)-1]]
        
        candidate_alloc_map = []
        for subtask_names in task.scheme_instances:
            subtask_instances = []
            for subtask_name in subtask_names:
                subtask_instance = self.data_server.get_data(
                    subtask_name, SubtaskInstance
                )
                subtask_instances.append(subtask_instance)

            alloc_map, end_time = self.subtask_alloc_server.allocate_subtasks(
                subtask_instances
            )
            if end_time < 0:
                # end time 小于 0 代表任务分配失败
                rospy.logerr(
                    f"Task {task_name} allocation failed. Alloc map: {alloc_map}"
                )
            candidate_alloc_map.append((alloc_map, end_time))
        if not candidate_alloc_map:
            rospy.logerr(f"Task {task_name} has no valid allocation.")
            return
            # self.data.subtask_alloc_buffer.remove(task_name)
        alloc_map, end_time = min(candidate_alloc_map, key=lambda x: x[1])

        task.state = "doing"

        # Update GUI

        if self.data.name != "edge_exp":
            alloc_map_dict = {}
            for end, subtasks in alloc_map.items():
                alloc_map_dict[end] = [
                    json.loads(SubtaskInstance.to_json(subtask)) for subtask in subtasks
                ]

            try:
                start_time = rospy.Time.now()
                vis_dict = {}
                if self.subtask_alloc_enabled:
                    for end, subtasks in alloc_map_dict.items():
                        vis_dict[end] = [f"{subtask['required_skill']} {subtask['required_resource']}#{subtask['name']}" for subtask in subtasks]
                else:
                    all_subtasks = []
                    for end, subtasks_list in alloc_map_dict.items():
                        all_subtasks.extend(subtasks_list)
                    subtasks = all_subtasks
                    first_end = True
                    for end in self.end_datas.keys():
                        if first_end:
                            vis_dict[end] = [f"{subtask['required_skill']} {subtask['required_resource']}#{subtask['name']}" for subtask in subtasks]
                            first_end = False
                        else:
                            vis_dict[end] = []
                self.gui_assignment_verification_client.wait_for_service(timeout=1)
                resp: StringSrvResponse = self.gui_assignment_verification_client.call(
                    StringSrvRequest(
                        json.dumps(
                            {
                                "module_name": "Subtask Ins. & Alloc.",
                                "result": vis_dict,
                            }
                        )
                    )
                )
                new_alloc_map_dict = json.loads(resp.data)
                new_alloc_map = {}
                for end, subtasks in new_alloc_map_dict.items():
                    new_alloc_map[end] = [
                        self.data_server.get_data(subtask.split("#")[1], SubtaskInstance) for subtask in subtasks
                    ]
                duration = rospy.Time.now() - start_time
                original_score = self._alloc_map_duration_predict(alloc_map, self.end_datas)
                alloc_map = new_alloc_map
                new_score = self._alloc_map_duration_predict(alloc_map, self.end_datas)

                LARGE_NUMBER = 999999999.0
                original_score_json = LARGE_NUMBER if original_score == float('inf') else original_score
                new_score_json = LARGE_NUMBER if new_score == float('inf') else new_score

                score_fraction = 0
                if new_score > 0:
                    score_fraction = original_score / new_score
                
                score_fraction_json = LARGE_NUMBER if score_fraction == float('inf') else score_fraction

                self.record_jsonl_pub.publish(
                    json.dumps(
                        {
                            "filename": f"{self.data.name}_subtask_alloc",
                            "task_name": task.name,
                            "alloc_map_solver": alloc_map_dict,
                            "alloc_map_human": new_alloc_map_dict,
                            "duration": duration.to_sec(),
                            "original_score": original_score_json,
                            "new_score": new_score_json,
                            "score_fraction": score_fraction_json,
                        }
                    )
                )

            except rospy.ROSException as e:
                rospy.logwarn(f"Service call failed: {e}")

        self.module_state_pub.publish(
            f"{self.data.name},Subtask Ins. & Alloc.,inactive"
        )
        self.data.subtask_alloc_buffer.remove(task_name)
        self.data.allocated_task_buffer.append(task_name)

        # Publish alloc map to Ends
        for end, subtasks in alloc_map.items():
            if subtasks:
                self.alloc_subtask_client[end].wait_for_service(timeout=1)
                self.gui_comm_pub.publish(f"{self.data.name},{end}")
                rospy.sleep(0.1)
                self.alloc_subtask_client[end].call(
                    StrListSrvRequest(
                        [SubtaskInstance.to_json(subtask) for subtask in subtasks]
                    )
                )

    # endregion

    # region GUI Timer

    def _gui_timer_cb(self, event):
        msg = String(data=self.data_server.to_json())
        self.gui_data_server_pub.publish(msg)

    # endregion

    def _alloc_map_duration_predict(
                self,
                alloc_map: Dict[str, List[SubtaskInstance]],
                end_datas: Dict[str, EndData],
            ) -> float:
        from collections import deque
        import math

        AGENT_TYPE_SKILLS = {
            "uheli": [
                "global_explore"
            ],
            "uav": [
                "local_explore",
                "inspect",
                "liquid_spray",
                "gas_spray",
                "monitor",
                "ignite",
                "detect",
                "throw"
            ],
            "ugv": [
                "local_explore",
                "inspect",
                "monitor",
                "solid_spray",
                "liquid_spray",
                "ignite",
                "gas_spray",
                "transport"
            ],
            "tugv": [
                "local_explore",
                "inspect",
                "monitor",
                "solid_spray",
                "liquid_spray",
                "gas_spray",
                "transport",
                "build",
                "lay",
                "clean_up"
            ],
            "dog": [
                "local_explore",
                "inspect",
                "monitor",
                "operate",
                "build",
                "rescue",
                "ignite",
                "fix",
                "clean_up"
            ]
        }

        # --- 0. 技能匹配检查 ---
        for end_name, subtasks in alloc_map.items():
            end_data = end_datas.get(end_name)
            if not end_data or not end_data.agent_type:
                # 数据不一致或机器人类型未知，视为非法
                return math.inf
            
            agent_type = end_data.agent_type
            available_skills = AGENT_TYPE_SKILLS.get(agent_type, [])
            
            for subtask in subtasks:
                if subtask.required_skill and subtask.required_skill not in available_skills:
                    # 技能不匹配，非法分配
                    return math.inf

        all_tasks = {subtask.name: subtask for subtasks in alloc_map.values() for subtask in subtasks}
        if not all_tasks:
            return 0.0

        # --- 1. 依赖关系检查 (拓扑排序检测循环依赖) ---
        adj = {name: [] for name in all_tasks}
        in_degree = {name: 0 for name in all_tasks}

        for name, subtask in all_tasks.items():
            for dep_name in subtask.dep_subtask_instances:
                if dep_name in all_tasks:
                    adj[dep_name].append(name)
                    in_degree[name] += 1
        
        queue = deque([name for name in all_tasks if in_degree[name] == 0])
        sorted_tasks = []
        while queue:
            u = queue.popleft()
            sorted_tasks.append(u)
            for v in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)
        
        if len(sorted_tasks) != len(all_tasks):
            # 检测到循环依赖
            return math.inf

        # --- 2. 严格按序模拟 ---
        subtask_completion_times: Dict[str, float] = {}
        end_finish_times: Dict[str, float] = {end_name: 0.0 for end_name in end_datas}
        end_cur_poses: Dict[str, Optional[Tuple[float, float, float]]] = {end_name: data.cur_pos for end_name, data in end_datas.items()}
        
        # 每个机器人下一个要执行的任务的索引
        next_task_indices = {end_name: 0 for end_name in end_datas}
        
        processed_task_count = 0
        # 循环直到所有任务都处理完毕
        while processed_task_count < len(all_tasks):
            progress_made_in_this_iteration = False
            
            for end_name, subtasks in alloc_map.items():
                task_idx = next_task_indices[end_name]
                
                # 如果这个机器人还有任务要做
                if task_idx < len(subtasks):
                    subtask = subtasks[task_idx]
                    
                    # 检查依赖是否满足
                    deps = subtask.dep_subtask_instances
                    if all(dep in subtask_completion_times for dep in deps):
                        # 依赖满足，可以执行
                        
                        # 1. 计算依赖任务完成时间
                        dep_finish_time = 0.0
                        if deps:
                            dep_finish_time = max(subtask_completion_times[dep_name] for dep_name in deps)
                        
                        # 2. 机器人准备好的时间
                        robot_ready_time = end_finish_times[end_name]

                        # 任务可以开始的最早时间
                        start_time = max(robot_ready_time, dep_finish_time)

                        # 3. 计算移动时间
                        travel_time = 0.0
                        cur_pos = end_cur_poses[end_name]
                        pos_seq = []
                        if subtask.res_pos is not None:
                            pos_seq.append(subtask.res_pos)
                        if subtask.target_pos is not None:
                            pos_seq.append(subtask.target_pos)

                        temp_pos = cur_pos
                        for pos in pos_seq:
                            if temp_pos is not None and pos is not None:
                                dist = ((temp_pos[0] - pos[0]) ** 2 + (temp_pos[1] - pos[1]) ** 2 + (temp_pos[2] - pos[2]) ** 2) ** 0.5
                                travel_time += dist / 1  # 假设速度为1
                                temp_pos = pos
                        
                        # 4. 计算任务完成时间
                        execution_duration = subtask.duration if hasattr(subtask, "duration") and subtask.duration else 0
                        completion_time = start_time + travel_time + execution_duration
                        
                        subtask_completion_times[subtask.name] = completion_time
                        end_finish_times[end_name] = completion_time
                        end_cur_poses[end_name] = temp_pos
                        
                        next_task_indices[end_name] += 1
                        processed_task_count += 1
                        progress_made_in_this_iteration = True

            # 如果一整轮下来没有任何机器人能执行任务，说明存在死锁
            if not progress_made_in_this_iteration:
                return math.inf

        if not subtask_completion_times:
            return 0.0
            
        return max(subtask_completion_times.values())

if __name__ == "__main__":
    rospy.init_node("edge_manager", anonymous=True)
    EdgeManager()
    rospy.spin()
