#! /usr/bin/env python3

import rospy
from typing import Union, cast, Optional, Tuple, List
from enum import Enum, auto
import queue
import sys
import os
import json
import tf2_ros
from matplotlib.colors import to_rgb

from geometry_msgs.msg import TransformStamped
from geometry_msgs.msg import PoseStamped, Pose
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from sensor_msgs.msg import Image
from visualization_msgs.msg import Marker

from main.srv import StringSrv, StringSrvRequest, StringSrvResponse
from main.srv import StrListSrv, StrListSrvRequest, StrListSrvResponse
from main.srv import ImageSrv, ImageSrvRequest, ImageSrvResponse

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from animation_controller import AnimationController, ProgressBarController

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
from vis.marker_factory import MarkerFactory as MF


class EndState(Enum):
    INIT = auto()
    IDLE = auto()
    MOVE = auto()
    WAIT = auto()
    EXEC = auto()
    ANIM = auto()


REACH_HORIZON = 1  # 判定到达目标点的距离阈值


class EndManager:
    def __init__(self):
        self.data: EndData = EndData(
            name=rospy.get_name().lstrip("/"),
            robot_id=int(cast(int, rospy.get_param("~robot_id", -1))),
            related_edge_name=None,
            agent_type=str(rospy.get_param("~agent_type")),
            cur_pos=None,
            todo_subtask_buffer=[],
            doing_subtask="",
            done_subtask_buffer=[],
            max_vel=float(cast(float, rospy.get_param("~max_vel", 1.0))),
            max_acc=float(cast(float, rospy.get_param("~max_acc", 1.0))),
            sensor_radius=float(cast(float, rospy.get_param("~sensor_radius", 4.0))),
        )

        # Recorder
        self.recorder_pub = rospy.Publisher("/record_csv", String, queue_size=10)

        # End Data Server
        self.data_server: DataServer = DataServer(self.data.name)

        # Config
        config_path = str(rospy.get_param("/config_path", ""))
        with open(config_path, "r") as f:
            self.config = json.load(f)

        # Waypoint and Odometry
        self.tf_broadcaster = tf2_ros.TransformBroadcaster()
        odom_topic: str = str(rospy.get_param("~odom_topic", "odom"))
        self.cur_odom: Optional[Odometry] = None
        self.waypoint_pub = rospy.Publisher(
            f"/drone_{self.data.robot_id}_planning/waypoint", PoseStamped, queue_size=10
        )
        self.odom_sub = rospy.Subscriber(
            f"/drone_{self.data.robot_id}_{odom_topic}", Odometry, self._odom_cb
        )

        # Edge-End Communication
        self.set_my_edge_server = rospy.Service(
            f"/{self.data.name}/set_my_edge", StringSrv, self._set_my_edge_cb
        )
        self.subtask_server = rospy.Service(
            f"/{self.data.name}/alloc_subtask", StrListSrv, self._alloc_subtask_cb
        )
        self.get_data_server = rospy.Service(
            f"/{self.data.name}/get_end_data",
            StringSrv,
            lambda _: StringSrvResponse(True, self.data.to_json()),
        )
        self.subtask_exec_state_pub = rospy.Publisher(
            f"/{self.data.related_edge_name}/subtask_exec_state", String, queue_size=3
        )

        # Camera
        self.take_photo_client = rospy.ServiceProxy(f"/take_photo", ImageSrv)
        self.upload_photo_client = rospy.ServiceProxy(
            f"/{self.data.related_edge_name}/upload_photo", ImageSrv
        )
        if self.data.agent_type == "uheli":
            self.maunal_script_timer = rospy.Timer(
                rospy.Duration(1),
                self.manual_script_timer_cb,
            )

        # Visualization
        self.marker: Optional[Union[Marker, List[Marker]]] = None
        self.cur_marker: Optional[Marker] = None
        self.marker_pub = rospy.Publisher(f"/extended_vis", Marker, queue_size=50)
        self.module_state_pub = rospy.Publisher(
            f"/gui/module_state", String, queue_size=10
        )
        self.layer_comm_vis_pub = rospy.Publisher(
            f"/layer_comm_vis", String, queue_size=10
        )

        if isinstance(
            self.config["agent_types"][self.data.agent_type]["model_path"], list
        ):
            self.model_path = [
                f"package://main/models/{path}"
                for path in self.config["agent_types"][self.data.agent_type][
                    "model_path"
                ]
            ]
            self.marker = [
                MF.get_model_marker(self.data.name, path, self.data.edge_color)
                for path in self.model_path
            ]
            freq = self.config["agent_types"][self.data.agent_type]["animation_freq"]
            self.animation_timer = rospy.Timer(
                rospy.Rate(freq).sleep_dur,
                self.animation_timer_cb,
            )
        else:
            self.model_path = f"package://main/models/{self.config['agent_types'][self.data.agent_type]['model_path']}"
            self.marker = MF.get_model_marker(
                self.data.name, self.model_path, self.data.edge_color
            )
            self.cur_marker = self.marker

        self.vis_timer = rospy.Timer(
            rospy.Duration().from_sec(0.1),
            self.vis_timer_cb,
        )

        # FSM
        self.state: EndState = EndState.INIT
        self.cur_subtask: Optional[SubtaskInstance] = None
        self.fsm_timer = rospy.Timer(rospy.Duration().from_sec(0.1), self._fsm_cb)

    # region FSM

    def _fsm_cb(self, event):
        if self.state == EndState.INIT:
            if (
                self.cur_odom is not None
                and self.data.related_edge_name is not None
                and self.data_server.search_client is not None
            ):
                self._set_state(EndState.IDLE)

        elif self.state == EndState.IDLE:
            if len(self.data.todo_subtask_buffer) > 0:

                # Get the first subtask from the buffer
                key = self.data.todo_subtask_buffer.pop(0)
                self.cur_subtask = self.data_server.get_data(key, SubtaskInstance)
                if self.cur_subtask.required_skill in ["operate", "fix", "rescure"]:
                    self.cur_subtask.duration = 20
                assert self.cur_subtask is not None
                self.data.doing_subtask = self.cur_subtask.name

                # 如果有资源位置，则先去资源位置，没有则直接去目标位置
                if self.cur_subtask.res_pos is None:
                    self.cur_subtask.state = "exec"
                    self._go_to(self.pos_remap(self.cur_subtask.target_pos))
                    self.module_state_pub.publish(f"{self.data.name},Moving,active")
                    self._set_state(EndState.MOVE)
                else:
                    self.cur_subtask.state = "res"
                    self._go_to(self.cur_subtask.res_pos)
                    self.module_state_pub.publish(f"{self.data.name},Moving,active")
                    self._set_state(EndState.MOVE)

        elif self.state == EndState.MOVE:
            assert self.cur_subtask is not None

            # --- 动态资源点切换逻辑 ---
            if self.cur_subtask.state == "res":
                # 只在去资源点的过程中动态切换
                resource_type = getattr(self.cur_subtask, "required_resource", None)
                if (
                    resource_type
                    and self.data.cur_pos is not None
                    and self.cur_subtask.res_pos is not None
                ):
                    # 获取所有同类型资源实例
                    all_resources = self.data_server.filter_data_by_type(
                        ResourceInstance
                    )
                    best_res = self.cur_subtask.res_pos
                    best_dist = self._distance(
                        self.data.cur_pos, self.cur_subtask.res_pos
                    ) + self._distance(
                        self.cur_subtask.res_pos, self.cur_subtask.target_pos
                    )
                    for res in all_resources:
                        if (
                            res.type == resource_type
                            and isinstance(res.pos, tuple)
                            and len(res.pos) == 3
                        ):
                            total_dist = self._distance(
                                self.data.cur_pos, res.pos
                            ) + self._distance(res.pos, self.cur_subtask.target_pos)
                            # 不能是当前目标点，且更优
                            if (
                                res.pos != self.cur_subtask.res_pos
                                and total_dist < best_dist
                            ):
                                best_res = res.pos
                                best_dist = total_dist
                    # 如果发现更优资源点，切换目标
                    if (
                        best_res != self.cur_subtask.res_pos
                        and best_res is not None
                        and len(best_res) == 3
                    ):
                        rospy.loginfo(
                            f"{self.data.name} 切换资源点: {self.cur_subtask.res_pos} -> {best_res}"
                        )
                        self.cur_subtask.res_pos = best_res
                        self._go_to(
                            (float(best_res[0]), float(best_res[1]), float(best_res[2]))
                        )

            if (
                self.cur_subtask.state == "res"
                and self._distance(self.data.cur_pos, self.cur_subtask.res_pos)
                < REACH_HORIZON
            ):
                self._go_to(self.pos_remap(self.cur_subtask.target_pos))
                self.cur_subtask.state = "exec"
            elif (
                self.cur_subtask.state == "exec"
                and self._distance(self.data.cur_pos, self.pos_remap(self.cur_subtask.target_pos))
                < REACH_HORIZON
            ):
                self.module_state_pub.publish(f"{self.data.name},Moving,inactive")
                self.cur_subtask.state = "wait"
                self._set_state(EndState.WAIT)

        elif self.state == EndState.WAIT:
            assert self.cur_subtask is not None

            if self.cur_subtask.conjugate_subtask is not None:
                conj_subtask = self.data_server.get_data(
                    self.cur_subtask.conjugate_subtask, SubtaskInstance
                )
                if conj_subtask.state not in ["wait", "doing", "done"]:
                    return

            self.module_state_pub.publish(f"{self.data.name},Executing,active")
            self.subtask_exec_state_pub.publish(f"{self.cur_subtask.name},doing")
            self.cur_subtask.state = "doing"
            self.data_server.set_data(
                self.cur_subtask.name, self.cur_subtask, True, True
            )
            self._set_state(EndState.EXEC)

        elif self.state == EndState.EXEC:
            assert self.cur_subtask is not None
            assert self.data.cur_pos is not None

            if self.cur_subtask.required_skill in ["global_explore", "local_explore"]:
                self.take_photo_client.wait_for_service(timeout=3)
                x_min = self.data.cur_pos[0] - self.data.sensor_radius
                y_min = self.data.cur_pos[1] - self.data.sensor_radius
                z_min = 0
                x_max = self.data.cur_pos[0] + self.data.sensor_radius
                y_max = self.data.cur_pos[1] + self.data.sensor_radius
                z_max = 20
                visibility = "coarse" if self.data.agent_type == "uheli" else "fine"
                resp: ImageSrvResponse = self.take_photo_client.call(
                    ImageSrvRequest(
                        Image(),
                        f"{x_min},{y_min},{z_min},{x_max},{y_max},{z_max},{visibility}",
                    )
                )
                if resp.success:
                    self.upload_photo_client.wait_for_service(timeout=3)
                    self.layer_comm_vis_pub.publish(
                        f"{self.data.name},{self.data.related_edge_name}"
                    )
                    resp: ImageSrvResponse = self.upload_photo_client.call(
                        ImageSrvRequest(resp.image, resp.message)
                    )

            # --- 动画替换sleep ---
            def on_anim_done():
                subtask = self.cur_subtask  # 先保存引用
                if subtask is not None:
                    self.subtask_exec_state_pub.publish(f"{subtask.name},done")
                    subtask.state = "done"
                    self.data_server.set_data(subtask.name, subtask, True, True)
                    self.module_state_pub.publish(
                        f"{self.data.name},Executing,inactive"
                    )
                    self.data.done_subtask_buffer.append(self.data.doing_subtask)
                    self.data.doing_subtask = ""
                self.cur_subtask = None
                # 结束时关闭进度条
                if hasattr(self, "progress_ctrl") and self.progress_ctrl:
                    self.progress_ctrl.timer.shutdown()
                    self.progress_ctrl = None
                self._set_state(EndState.IDLE)

            # --- 进度条动画 ---
            if self.cur_subtask.duration > 0:
                self.progress_ctrl = ProgressBarController(
                    manager=self,
                    name=self.data.name,
                    duration=self.cur_subtask.duration,
                    marker_pub=self.marker_pub,
                    bar_length=0.8,
                    bar_height=0.7,
                )

            if self.cur_subtask.required_skill in [
                "liquid_spray",
                "solid_spray",
                "gas_spray",
            ]:
                # 根据技能类型选择不同的形状和颜色
                if self.cur_subtask.required_skill == "solid_spray":
                    shape = "cube"
                    color = to_rgb("#fdea44")   # 黄色
                elif self.cur_subtask.required_skill == "liquid_spray":
                    shape = "sphere"
                    color = to_rgb("#4894ff")   # 蓝色
                elif self.cur_subtask.required_skill == "gas_spray":
                    shape = "sphere"
                    color = to_rgb("#cccccc")  # 浅灰色
                else:
                    shape = "sphere"
                    color = to_rgb("#ff0000")

                self.anim_ctrl = AnimationController(
                    manager=self,
                    duration=self.cur_subtask.duration,
                    start_pos=self.data.cur_pos,
                    end_pos=self.cur_subtask.target_pos,
                    marker_pub=self.marker_pub,
                    shape=shape,
                    color=color,
                    particle_count=40,
                )
                self.anim_ctrl.set_done_callback(on_anim_done)
                self._set_state(EndState.ANIM)
            else:
                # 不需要动画，直接sleep模拟
                rospy.sleep(self.cur_subtask.duration)
                on_anim_done()

        elif self.state == EndState.ANIM:
            # 动画控制器会在完成后自动回调on_anim_done
            pass

    def _set_state(self, state: EndState):
        self.state = state
        rospy.loginfo(f"{self.data.name} state: {self.state.name}")
        self.recorder_pub.publish(
            String(f"{self.data.name}_state,{self.state.name},{self.cur_subtask}")
        )

    def _distance(self, a, b) -> float:
        return sum((a[i] - b[i]) ** 2 for i in range(min(len(b), len(a)))) ** 0.5

    def _go_to(self, target_pos: Tuple[float, float, float]):
        pose = PoseStamped()
        pose.header.frame_id = "world"
        pose.header.stamp = rospy.Time.now()
        pose.pose.position.x = target_pos[0]
        pose.pose.position.y = target_pos[1]
        pose.pose.position.z = target_pos[2]
        pose.pose.orientation.w = 1
        self.waypoint_pub.publish(pose)

    # endregion

    # region Callbacks

    def manual_script_timer_cb(self, event):
        if self.data.related_edge_name is None:
            return
        if self.data.cur_pos is None:
            return
        self.take_photo_client.wait_for_service(timeout=3)
        resp: ImageSrvResponse = self.take_photo_client.call(
            ImageSrvRequest(
                Image(),
                f"0,0,0,0,0,0,manual",
            )
        )
        if resp.success:
            self.upload_photo_client.wait_for_service(timeout=3)
            self.layer_comm_vis_pub.publish(
                f"{self.data.name},{self.data.related_edge_name}"
            )
            resp: ImageSrvResponse = self.upload_photo_client.call(
                ImageSrvRequest(resp.image, resp.message)
            )

    def vis_timer_cb(self, event):
        if self.cur_odom is None:
            return
        if self.cur_marker is None:
            return
        if self.data.agent_type == "uheli":
            if not hasattr(self, "fov_marker"):
                self.fov_marker = MF.gen_fov(
                    self.data.name,
                    3,
                    self.data.sensor_radius * 2,
                    self.data.sensor_radius * 2,
                    self.cur_odom.pose.pose,
                )
            self.fov_marker.pose.position = self.cur_odom.pose.pose.position
            self.fov_marker.pose.orientation.x = 0
            self.fov_marker.pose.orientation.y = 0.707
            self.fov_marker.pose.orientation.z = 0
            self.fov_marker.pose.orientation.w = 0.707
            self.marker_pub.publish(self.fov_marker)
        self.cur_marker.pose = self.cur_odom.pose.pose
        r, g, b = to_rgb(self.data.edge_color)
        self.cur_marker.color.r = r
        self.cur_marker.color.g = g
        self.cur_marker.color.b = b
        self.marker_pub.publish(self.cur_marker)

    def animation_timer_cb(self, event):
        if self.cur_odom is None:
            return
        if not isinstance(self.marker, list):
            raise ValueError("Marker is not a list")
        self.cur_marker = self.marker.pop(0)
        self.marker.append(self.cur_marker)

    def _set_my_edge_cb(self, msg: StringSrvRequest) -> StringSrvResponse:
        rospy.loginfo(f"{self.data.name} set my edge: {msg.data}")
        self.data.related_edge_name = msg.data
        self.data_server.set_search_client(self.data.related_edge_name)
        self.upload_photo_client = rospy.ServiceProxy(
            f"/{self.data.related_edge_name}/upload_photo", ImageSrv
        )
        return StringSrvResponse(True, self.data.name)

    def _alloc_subtask_cb(self, msg: StrListSrvRequest) -> StrListSrvResponse:
        rospy.loginfo(f"{self.data.name} is allocatted subtask: {msg.data}")
        subtasks = msg.data
        now = rospy.get_time()  # 当前时间戳（秒）
        # 初始化 end_time 和 end_pos
        if not hasattr(self.data, "end_time") or self.data.end_time is None:
            self.data.end_time = now
        if not hasattr(self.data, "end_pos") or self.data.end_pos is None:
            self.data.end_pos = (
                self.data.cur_pos if self.data.cur_pos is not None else (0, 0, 0)
            )
        # 以 end_time 和 end_pos 作为起点
        cur_time = max(self.data.end_time, now)
        cur_pos = self.data.end_pos
        for subtask_str in subtasks:
            subtask: SubtaskInstance = SubtaskInstance.from_json(subtask_str)
            # 计算travel_time
            if subtask.res_pos is not None:
                dist1 = self._distance(cur_pos, subtask.res_pos)
                dist2 = self._distance(subtask.res_pos, subtask.target_pos)
                travel_time = (
                    dist1 / max(self.data.max_vel, 1e-3)
                    + dist2 / max(self.data.max_vel, 1e-3)
                    + subtask.duration
                )
                cur_pos = subtask.target_pos  # 串行执行，更新当前位置
            else:
                dist = self._distance(cur_pos, subtask.target_pos)
                travel_time = dist / max(self.data.max_vel, 1e-3) + subtask.duration
                cur_pos = subtask.target_pos
            cur_time += travel_time
            self.data.todo_subtask_buffer.append(subtask.name)
            self.data_server.set_data(subtask.name, subtask, True, False)
        # 更新end_time和end_pos
        self.data.end_time = cur_time
        self.data.end_pos = cur_pos
        return StrListSrvResponse(True, [])

    def _odom_cb(self, msg: Odometry):
        self.data.cur_pos = (
            msg.pose.pose.position.x,
            msg.pose.pose.position.y,
            msg.pose.pose.position.z,
        )
        self.cur_odom = msg
        # 广播tf
        t = TransformStamped()
        t.header.stamp = rospy.Time.now()
        t.header.frame_id = "world"
        t.child_frame_id = f"/{self.data.name}/base_link"
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self.tf_broadcaster.sendTransform(t)

    # endregion

    def pos_remap(self, pos: Tuple[float, float, float]) -> Tuple[float, float, float]:
        return pos


if __name__ == "__main__":
    rospy.init_node("end_manager", anonymous=True)
    EndManager()
    rospy.spin()
