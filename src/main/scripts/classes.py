from typing import Optional, Tuple, Dict, List, Union, TypeVar, Type, Callable, cast
from dataclasses import dataclass, field
import json
import rospy

from main.srv import StringSrv, StringSrvRequest, StringSrvResponse
from std_msgs.msg import String


COLOR_MAP = {
    "edge_exp": "#CC00FF",
    "edge_1": "#FF1919",
    "edge_2": "#FFD600",
    "edge_3": "#1E90FF",
    "edge_4": "#00D26A",
    "end_101": "#FF7171",
    "end_102": "#F2FE51",
    "end_103": "#4EACFF",
    "end_104": "#5BFF5B",
    "end_1": "#FF6969",
    "end_2": "#FFFC66",
    "end_3": "#67ABFF",
    "end_4": "#8AFF66",
    "end_5": "#FC6363",
    "end_6": "#FFFC63",
    "end_7": "#57D5FF",
    "end_8": "#63FF5D",
    "end_9": "#FF67FA",
    "end_10": "#FF755D",
    "end_11": "#FDEE52",
    "end_12": "#69A0FF",
    "end_13": "#83FF64",
    "end_14": "#FF6565",
    "end_15": "#FFF869",
    "end_16": "#63BEFF",
    "end_17": "#70FF66",
    "end_18": "#FF64FF",
}


class JSONSerializable:
    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, json_data: Union[str, dict]):
        if isinstance(json_data, str):
            data = json.loads(json_data)
        elif isinstance(json_data, dict):
            data = json_data
        else:
            raise ValueError("Input must be a JSON string or a dictionary.")
        return cls(**data)


@dataclass
class SubtaskType(JSONSerializable):
    name: str
    required_skill: str = ""
    dep_subtask_types: List[str] = field(default_factory=list)
    required_resource: str = ""
    target: str = ""
    required_robot_num: int = 1


@dataclass
class SubtaskInstance(JSONSerializable):
    name: str
    # type
    required_skill: str = ""
    dep_subtask_types: List[str] = field(default_factory=list)
    required_resource: str = ""
    target: str = ""

    res_pos: Optional[Tuple[float, float, float]] = None
    target_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    duration: float = 10
    dep_subtask_instances: List[str] = field(default_factory=list)
    allocated_end: str = ""
    recommended_dep: Optional[str] = None
    conjugate_subtask: Optional[str] = None

    state: str = "todo"  # status: todo, res, exec, wait, doing, done


@dataclass
class TaskType(JSONSerializable):
    name: str
    basic_required_skills: List[str] = field(default_factory=list)
    scheme_types: List[List[str]] = field(default_factory=list)
    dep_task_types: Optional[List[str]] = field(default_factory=list)
    priority: int = 0
    to_be_comp: bool = True
    context_analysis: str = ""

@dataclass
class TaskInstance(JSONSerializable):
    name: str
    task_type: str

    scheme_instances: List[List[str]] = field(default_factory=list)
    dep_task_instances: List[str] = field(default_factory=list)
    pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    allocated_edge: Optional[str] = None

    exp_generated: bool = False
    state: str = "todo"  # status: todo, doing, done


@dataclass
class EndData(JSONSerializable):
    name: str
    robot_id: int
    agent_type: str = ""
    max_vel: float = 0.0
    max_acc: float = 0.0
    sensor_radius: float = 0.0
    related_edge_name: Optional[str] = None
    cur_pos: Optional[Tuple[float, float, float]] = None
    todo_subtask_buffer: List[str] = field(default_factory=list)
    doing_subtask: str = ""
    done_subtask_buffer: List[str] = field(default_factory=list)

    end_time: float = 0.0
    end_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def my_subtasks(self) -> List[str]:
        """Combine all subtask buffers into a single list: done + [doing] + todo"""
        return (
            self.done_subtask_buffer + [self.doing_subtask] + self.todo_subtask_buffer
        )

    @property
    def color(self) -> str:
        return COLOR_MAP.get(self.name, "#494949")

    @property
    def edge_color(self) -> str:
        return COLOR_MAP.get(str(self.related_edge_name), "#494949")


@dataclass
class EdgeData(JSONSerializable):
    name: str
    related_end_names: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    related_cloud_name: Optional[str] = None
    end_time: float = 0.0
    subtask_gen_buffer: List[str] = field(default_factory=list)
    subtask_alloc_buffer: List[str] = field(default_factory=list)
    allocated_task_buffer: List[str] = field(default_factory=list)

    @property
    def my_tasks(self) -> List[str]:
        """Combine all task buffers into a single list: ST Gen + ST Alloc + Allocated"""
        return (
            self.subtask_gen_buffer
            + self.subtask_alloc_buffer
            + self.allocated_task_buffer
        )

    @property
    def color(self) -> str:
        return COLOR_MAP.get(self.name, "#494949")


@dataclass
class ResourceType(JSONSerializable):
    name: str


@dataclass
class ResourceInstance(JSONSerializable):
    name: str
    type: str
    pos: Tuple[float, float, float]


DataType = Union[
    SubtaskInstance,
    TaskInstance,
    SubtaskType,
    TaskType,
    EndData,
    EdgeData,
    ResourceType,
    ResourceInstance,
]

DT = TypeVar("DT", bound=DataType)


class DataServer(JSONSerializable):
    TYPE_MAP: Dict[str, Type[DataType]] = {
        "TaskInstance": TaskInstance,
        "SubtaskInstance": SubtaskInstance,
        "EndData": EndData,
        "EdgeData": EdgeData,
        "SubtaskType": SubtaskType,
        "TaskType": TaskType,
        "ResourceType": ResourceType,
        "ResourceInstance": ResourceInstance,
    }

    def __init__(
        self, name: str, init_search_server: bool = True, write_log: bool = True
    ):
        self.name = name
        # 为每个类型单独维护一个字典
        self.data_store: Dict[str, Dict[str, DataType]] = {
            type_name: {} for type_name in self.TYPE_MAP
        }
        self.search_client = None
        self.gui_module_state_pub = None

        if init_search_server:
            self.search_server = rospy.Service(
                f"/{name}/search_data", StringSrv, self._get_data_cb
            )

        log_dir = str(rospy.get_param("/log_dir", ""))
        if write_log and log_dir:
            self.log_timer = rospy.Timer(
                rospy.Duration(2),
                lambda _: self.write_log(f"{log_dir}/{self.name}_data_server_log.txt"),
            )

        self.gui_module_state_pub = rospy.Publisher(
            f"/module_state", String, queue_size=10
        )

        self.broadcast_sub = rospy.Subscriber(
            "/data_server_broadcast", String, self._broadcast_cb
        )

        # 新增：订阅添加资源实例的话题
        self.add_resource_instance_sub = rospy.Subscriber(
            f"/add_resource_instance", String, self._add_resource_instance_cb
        )

    def set_search_client(self, search_target_name: str):
        self.search_client = rospy.ServiceProxy(
            f"/{search_target_name}/search_data", StringSrv
        )
        self.search_client.wait_for_service(timeout=10)
        rospy.loginfo(f"Search client set with target {search_target_name}")

    def get_data(self, key: str, data_type: Type[DT]) -> DT:
        if self.search_client is None and self.name != "cloud":
            rospy.logwarn(f"No search client available, name:{self.name} key:{key}")
        type_name = data_type.__name__

        # 优先从本地对应类型的字典中获取
        if key in self.data_store[type_name]:
            return cast(DT, self.data_store[type_name][key])

        if not self.search_client:
            raise ValueError(
                f"Search client not set. Cannot search for key: {key} of type: {type_name}"
            )

        self.search_client.wait_for_service(timeout=3)
        resp: StringSrvResponse = self.search_client.call(
            StringSrvRequest(f"{key},{type_name}")
        )
        if resp.success:
            obj = data_type.from_json(resp.data)
            self.set_data(key, obj, False, False)
            return obj

        raise ValueError(
            f"Data not found for key: {key} of type: {type_name}. Response: {resp.data}"
        )

    def _broadcast_data(self, key: str, data: DataType):
        """Broadcast data to other DataServers via ROS topic."""
        if not hasattr(self, "broadcast_pub"):
            self.broadcast_pub = rospy.Publisher(
                "/data_server_broadcast", String, queue_size=50
            )
        msg = json.dumps(
            {
                "server": self.name,
                "type": data.__class__.__name__,
                "key": key,
                "data": data.to_json(),
            }
        )
        self.broadcast_pub.publish(msg)

    def _broadcast_cb(self, msg):
        try:
            info = json.loads(msg.data)
            if info["server"] == self.name:
                return  # Ignore own broadcast
            type_name = info["type"]
            key = info["key"]
            data_json = info["data"]
            obj = self.TYPE_MAP[type_name].from_json(data_json)
            self.set_data(key, obj, vis=False, broadcast=False)
        except Exception as e:
            rospy.logwarn(f"Broadcast callback error: {e}")

    def set_data(self, key: str, data: DataType, vis=True, broadcast=False):
        type_name = data.__class__.__name__
        self.data_store[type_name][key] = data
        if self.gui_module_state_pub and vis:
            self.gui_module_state_pub.publish(f"{self.name},Data,active")
            rospy.sleep(0.1)
            self.gui_module_state_pub.publish(f"{self.name},Data,inactive")
            rospy.sleep(0.1)
        if broadcast:
            self._broadcast_data(key, data)

    def _get_data_cb(self, req: StringSrvRequest) -> StringSrvResponse:
        try:
            key, type_name = req.data.split(",")  # 客户端传 key,type
        except:
            raise ValueError(
                f"Invalid request format. Expected 'key,type', got '{req.data}'"
            )
        data = self.get_data(key, self.TYPE_MAP[type_name])
        if data is None:
            return StringSrvResponse(False, f"Data not found for key: {key}")
        return StringSrvResponse(True, data.to_json())

    def filter_data(
        self, filter_func: Callable, target_type: Optional[Type[DataType]] = None
    ) -> List[DataType]:
        if target_type:
            type_name = target_type.__name__
            items = list(self.data_store.get(type_name, {}).values())
        else:
            items = []
            for d in self.data_store.values():
                items.extend(d.values())
        return [d for d in items if filter_func(d)]

    def filter_data_by_type(self, target_type: Type[DT]) -> List[DT]:
        return cast(
            List[DT], list(self.data_store.get(target_type.__name__, {}).values())
        )

    def get_task_type_DAG(self) -> Dict[str, List[str]]:
        task_type_DAG = {}
        for task_type in self.filter_data_by_type(TaskType):
            if isinstance(task_type, TaskType):
                task_type_DAG[task_type.name] = task_type.dep_task_types
            else:
                raise TypeError(f"Expected TaskType, got {type(task_type).__name__}")
        return task_type_DAG

    def write_log(self, log_file: str):
        with open(log_file, "w") as f:
            for type_name, items in self.data_store.items():
                f.write(f"{type_name}:\n")
                for key, item in list(
                    items.items()
                ):  # Use a static list to avoid RuntimeError
                    f.write(f"  {key}: {item.to_json()}\n")

    def to_json(self) -> str:
        serialized_data = {
            "name": self.name,
            "data_store": {
                type_name: {
                    key: json.loads(item.to_json()) for key, item in list(items.items())
                }
                for type_name, items in list(self.data_store.items())
            },
        }
        return json.dumps(serialized_data)

    @classmethod
    def from_json(cls, json_data: Union[str, dict]):
        if isinstance(json_data, str):
            data = json.loads(json_data)
        elif isinstance(json_data, dict):
            data = json_data
        else:
            raise ValueError("Input must be a JSON string or a dictionary.")
        name = data["name"]

        server = cls(name, init_search_server=False, write_log=False)
        if hasattr(server, "log_timer"):
            server.log_timer.shutdown()
            del server.log_timer
        for type_name, items in data["data_store"].items():
            for key, item in items.items():
                obj = server.TYPE_MAP[type_name].from_json(item)
                server.set_data(key, obj, False, False)
        return server

    def _add_resource_instance_cb(self, msg: String):
        """
        通过订阅话题动态添加ResourceInstance。
        消息格式为字符串: type,x,y
        """
        try:
            info = msg.data.split(",")
            type_ = info[0]
            pos = [0.0,0.0,0.0]
            pos[0] = float(info[1])
            pos[1] = float(info[2])
            if len(info) > 3:
                pos[2] = float(info[3])
            else:
                pos[2] = 0.5  # 默认高度为 0.5
            name = f"{type_}_{pos[0]}_{pos[1]}_{pos[2]}"
            resource = ResourceInstance(name=name, type=type_, pos=(pos[0], pos[1], pos[2]))
            self.set_data(name, resource, vis=False, broadcast=False)
            rospy.loginfo(f"ResourceInstance added: {name}, type: {type_}, pos: {pos}")
        except Exception as e:
            rospy.logwarn(f"Failed to add ResourceInstance from topic: {e}")


if __name__ == "__main__":
    pass
