#!/usr/bin/env python3

from typing import Dict, List, cast, Tuple, Optional
import rospy
import sys
import os
import json
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QLabel,
    QScrollArea,
    QGraphicsView,
    QGraphicsScene,
    QPushButton,
    QFrame,
)
from PyQt5.QtCore import Qt, QTimer, QPointF, QObject, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPolygonF, QPainter, QPixmap, QFontMetrics
from std_msgs.msg import String

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from classes import (
    DataServer,
    EdgeData,
    SubtaskType,
    TaskInstance,
    ResourceInstance,
    TaskType,
    EndData,
)
from base_map_widget import BaseMapWidget


class ToggleBlock(QWidget):
    def __init__(self, title: str, scheme_text: str):
        super().__init__()
        self.title = title
        self.scheme_text = scheme_text
        self.init_ui()

    def init_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.toggle_button = QPushButton(self.title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        self.toggle_button.clicked.connect(self.on_toggle)  # type: ignore
        self._layout.addWidget(self.toggle_button)

        # 取消QScrollArea，直接用QWidget+QLabel
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 0, 0, 0)
        self.content_label = QLabel(self.scheme_text)
        self.content_label.setWordWrap(True)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.content_layout.addWidget(self.content_label)
        self.content.setVisible(False)
        self._layout.addWidget(self.content)

    def on_toggle(self):
        visible = self.toggle_button.isChecked()
        self.content.setVisible(visible)


class SchemeWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._outer_layout = QVBoxLayout(self)
        self.setLayout(self._outer_layout)
        self.schemes = {}
        self._toggle_states = {}
        self._blocks = {}
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self._outer_layout.addWidget(self.scroll_area)
        self.content_widget = QWidget()
        self._layout = QVBoxLayout(self.content_widget)
        self.scroll_area.setWidget(self.content_widget)
        self.init_ui()

    def init_ui(self):
        # 记录当前展开状态
        for task, block in self._blocks.items():
            if block is not None:
                self._toggle_states[task] = block.toggle_button.isChecked()
        # 清空旧内容
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._blocks = {}
        # 添加新内容
        for task, scheme in self.schemes.items():
            block = ToggleBlock(task, scheme)
            # 恢复展开状态
            if task in self._toggle_states:
                block.toggle_button.setChecked(self._toggle_states[task])
                block.content.setVisible(self._toggle_states[task])
            self._layout.addWidget(block)
            self._blocks[task] = block
        self._layout.addStretch()

    def set_schemes(self, schemes: Dict[str, str]):
        self.schemes = schemes
        self.init_ui()


class TaskDAGWidget(QGraphicsView):
    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.dependencies: Dict[str, List[str]] = {}

    def set_dependencies(self, dependencies: Dict[str, List[str]]):
        """Set the dependency graph where key -> list of dependent task types."""
        self.dependencies = dependencies
        self._scene.clear()
        # Gather all nodes
        nodes = set(dependencies.keys())
        for children in dependencies.values():
            nodes.update(children)
        nodes = list(nodes)

        # Compute in-degrees for a simple layer assignment
        indegree = {node: 0 for node in nodes}
        for parent, children in dependencies.items():
            for child in children:
                indegree[child] += 1

        # Assign layers using a simple approach: nodes with zero indegree in layer 0
        layers = {}
        current_layer = 0
        layer_nodes = [node for node in nodes if indegree[node] == 0]
        while layer_nodes:
            layers[current_layer] = layer_nodes
            next_layer = []
            for node in layer_nodes:
                for child in dependencies.get(node, []):
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        next_layer.append(child)
            current_layer += 1
            layer_nodes = next_layer

        # Layout parameters
        layer_spacing = 150
        node_spacing = 100
        node_radius = 20
        positions = {}
        # Center nodes in each layer vertically
        for layer, nodes_in_layer in layers.items():
            for i, node in enumerate(nodes_in_layer):
                x = layer * layer_spacing + node_radius + 10
                y = i * node_spacing + node_radius + 10
                positions[node] = (x, y)

        # Draw nodes (circles with labels)
        for node, (x, y) in positions.items():
            self._scene.addEllipse(
                x - node_radius, y - node_radius, node_radius * 2, node_radius * 2
            )
            text = self._scene.addText(node)
            text.setPos(x - node_radius, y - 2 * node_radius)

        # Draw edges with simple arrowheads
        for parent, children in dependencies.items():
            start_x, start_y = positions.get(parent, (0, 0))
            for child in children:
                end_x, end_y = positions.get(child, (0, 0))
                self._scene.addLine(start_x, start_y, end_x, end_y)
                # Draw an arrowhead at the end point
                dx = end_x - start_x
                dy = end_y - start_y
                length = (dx**2 + dy**2) ** 0.5
                if length == 0:
                    continue
                arrow_size = 10
                ux = dx / length
                uy = dy / length
                # Perpendicular vector
                perp_x = -uy
                perp_y = ux
                arrow_p1 = (
                    end_x - arrow_size * ux + (arrow_size / 2) * perp_x,
                    end_y - arrow_size * uy + (arrow_size / 2) * perp_y,
                )
                arrow_p2 = (
                    end_x - arrow_size * ux - (arrow_size / 2) * perp_x,
                    end_y - arrow_size * uy - (arrow_size / 2) * perp_y,
                )
                arrow_polygon = QPolygonF(
                    [
                        QPointF(end_x, end_y),
                        QPointF(arrow_p1[0], arrow_p1[1]),
                        QPointF(arrow_p2[0], arrow_p2[1]),
                    ]
                )
                self._scene.addPolygon(arrow_polygon)


# 自定义地图绘图组件
class MapWidget(BaseMapWidget):
    def __init__(self):
        super().__init__()
        self.tasks = []
        self.resources = []
        self.ends = []
        self.edge_colors = {}
        self.set_axes('right')

    def set_data(
        self,
        tasks: List[TaskInstance],
        resources: List[ResourceInstance],
        ends: Optional[List[EndData]] = None,
        edge_colors: Optional[dict] = None,
    ):
        self.tasks = tasks
        self.resources = resources
        self.ends = ends if ends is not None else []
        self.edge_colors = edge_colors or {}
        shapes = []
        # draw tasks
        for task in self.tasks:
            if hasattr(task, 'name') and 'global_exp' in task.name:
                continue
            x, y, _ = task.pos
            shapes.append({'x': x, 'y': y, 'color': 'blue', 'shape': 'circle', 'label': getattr(task, 'task_type', getattr(task, 'type', None))})
        # draw resources
        for res in self.resources:
            x, y, _ = res.pos
            shapes.append({'x': x, 'y': y, 'color': 'green', 'shape': 'rect', 'label': getattr(res, 'resource_type', getattr(res, 'type', None))})
        # draw ends
        for e in self.ends:
            if hasattr(e, 'cur_pos') and e.cur_pos:
                x, y, _ = e.cur_pos
                color = self.edge_colors.get(e.name, getattr(e, 'edge_color', '#494949'))
                shapes.append({'x': x, 'y': y, 'color': color, 'shape': 'circle', 'label': e.name})
        self.set_shapes(shapes)


# 底部图形展示区
class GraphWidget(QGraphicsView):
    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setSceneRect(0, 0, 400, 100)
        self.tasks = []  # current tasks sequence

    def set_tasks(self, tasks):
        """Update the task sequence in the graph view. 支持 (name, state) 元组输入，并根据状态着色。"""
        from PyQt5.QtGui import QFontMetrics

        self.tasks = tasks
        self._scene.clear()
        if not tasks:
            return
        font = self.font()
        metrics = QFontMetrics(font)
        rect_h = 50
        spacing = 20  # 间隔
        padding = 20  # 块内左右 padding
        x = 0
        rects = []
        # 颜色映射
        color_map = {
            "subtask_gen": QColor("#C8F7C5"),
            "subtask_alloc": QColor("#FFFACD"),
            "allocated": QColor("#C0C0C0"),
        }
        # 先计算每个块的宽度
        widths = [metrics.width(name) + padding for name, _ in tasks]
        for i, ((task_name, state), rect_w) in enumerate(zip(tasks, widths)):
            color = color_map.get(state, Qt.lightGray)
            self._scene.addRect(x, 25, rect_w, rect_h, brush=QBrush(color))
            text_item = self._scene.addText(task_name)
            text_item.setPos(x + padding // 2, 25 + rect_h / 2 - metrics.height() // 2)
            if i < len(tasks) - 1:
                next_x = x + rect_w + spacing
                self._scene.addLine(
                    x + rect_w, 25 + rect_h / 2, next_x, 25 + rect_h / 2
                )
            rects.append((x, rect_w))
            x += rect_w + spacing
        self.setSceneRect(0, 0, x, rect_h + 50)


# 主窗口类
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cloud Interface")
        self.resize(1920, 1080)
        main_layout = QVBoxLayout(self)
        # 主垂直分割器: 上部(top_splitter)和下部(scroll_area)可拖动调整
        main_splitter = QSplitter(Qt.Vertical)
        # 顶部水平分割器
        top_splitter = QSplitter(Qt.Horizontal)

        # 左侧：task DAG 依赖关系图，包装成带精致标题栏的容器
        self.task_dag_widget = TaskDAGWidget()
        # 示例依赖数据，可以后续根据 task type 实际数据更新
        sample_dependencies = {
            "TaskA": ["TaskB", "TaskC"],
            "TaskB": ["TaskD"],
            "TaskC": ["TaskD"],
            "TaskD": [],
        }
        sample_dependencies = {}
        self.task_dag_widget.set_dependencies(sample_dependencies)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        # 新增：精致的标题标签
        dag_title = QLabel("Mission Comprehension")
        dag_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #333; padding: 8px; background-color: #f7f7f7; border-bottom: 1px solid #ccc;"
        )
        left_layout.addWidget(dag_title)
        left_layout.addWidget(self.task_dag_widget)
        top_splitter.addWidget(left_container)

        # 中间：2D 地图（保持不变）
        self.map_widget = MapWidget()
        top_splitter.addWidget(self.map_widget)

        # 右侧：任务类型与方案，包装成带精致标题栏的容器
        self.scheme_widget = SchemeWidget()
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        scheme_title = QLabel("Data Management")
        scheme_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #333; padding: 8px; background-color: #f7f7f7; border-bottom: 1px solid #ccc;"
        )
        right_layout.addWidget(scheme_title)
        right_layout.addWidget(self.scheme_widget)
        top_splitter.addWidget(right_container)

        # Set initial widths for task DAG, map, and text panels
        top_splitter.setSizes([200, 400, 200])
        main_splitter.addWidget(top_splitter)

        # 底部滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        bottom_content = QWidget()
        self.bottom_layout = QVBoxLayout(bottom_content)
        self.bottom_layout.setSpacing(8)
        self.bottom_layout.setContentsMargins(6, 6, 6, 6)
        scroll_area.setWidget(bottom_content)
        scroll_area.setWidget(bottom_content)
        main_splitter.addWidget(scroll_area)
        main_splitter.setSizes([300, 400])
        main_layout.addWidget(main_splitter)

    def update_edges(self, edges_dict: Dict[str, EdgeData]):
        """Dynamically build and update edge panels based on edges_dict, edge风格与edge端一致."""
        if not hasattr(self, "edge_widgets"):
            self.edge_widgets: Dict[
                str, Tuple[GraphWidget, QLabel, QWidget, QLabel]
            ] = {}
        while self.bottom_layout.count():
            item = self.bottom_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
        color_map = {}
        for idx, edge_name in enumerate(edges_dict.keys()):
            edge_data = edges_dict[edge_name]
            color = getattr(edge_data, "color", None)
            if not color:
                color = QColor.fromHsv((idx * 40) % 360, 120, 220).name()
            color_map[edge_name] = color
        for idx, (edge_name, edge_data) in enumerate(edges_dict.items()):
            color = color_map[edge_name]
            # 直接用EdgeData的buffer
            subtask_gen = getattr(edge_data, "subtask_gen_buffer", [])
            subtask_alloc = getattr(edge_data, "subtask_alloc_buffer", [])
            allocated = getattr(edge_data, "allocated_task_buffer", [])
            n_gen = len(subtask_gen)
            n_alloc = len(subtask_alloc)
            n_allocated = len(allocated)
            # 顺序拼接
            task_names = []
            for t in allocated:
                task_names.append((t, "allocated"))
            for t in subtask_alloc:
                task_names.append((t, "subtask_alloc"))
            for t in subtask_gen:
                task_names.append((t, "subtask_gen"))

            if edge_name not in self.edge_widgets:
                row = QHBoxLayout()
                color_frame = QFrame()
                color_frame.setFixedWidth(16)
                color_frame.setFixedHeight(60)
                color_frame.setStyleSheet(
                    f"background-color: {color}; border-radius: 4px;"
                )
                row.addWidget(color_frame)
                name_lbl = QLabel(edge_name)
                name_lbl.setFixedWidth(80)
                name_lbl.setFixedHeight(60)
                name_lbl.setAlignment(Qt.AlignVCenter)
                row.addWidget(name_lbl)
                stat_lbl = QLabel()
                stat_lbl.setFixedWidth(120)
                row.addWidget(stat_lbl)
                gw = GraphWidget()
                gw.setFixedHeight(100)
                gw.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                gw.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                row.addWidget(gw, 1)
                row_widget = QWidget()
                row_widget.setLayout(row)
                self.bottom_layout.addWidget(row_widget)
                self.edge_widgets[edge_name] = (gw, stat_lbl, row_widget, name_lbl)
            else:
                gw, stat_lbl, row_widget, name_lbl = self.edge_widgets[edge_name]
                row_widget.show()
                self.bottom_layout.addWidget(row_widget)
            stat_lbl.setText(
                f"ST Gen: {n_gen}\nST Alloc: {n_alloc}\nAllocated: {n_allocated}"
            )
            name_lbl.setText(edge_name)
            gw.set_tasks(task_names)
        for edge_name in list(self.edge_widgets.keys()):
            if edge_name not in edges_dict:
                _, _, row_widget, _ = self.edge_widgets.pop(edge_name)
                row_widget.hide()


# 信号类
class GuiSignal(QObject):
    update_map = pyqtSignal()
    update_edges = pyqtSignal()
    update_task_types = pyqtSignal()

    def __init__(self):
        super().__init__()


# ROS 节点类
class GuiNode:
    def __init__(self):
        rospy.init_node("qt_cloud_interface", anonymous=True)
        self.name = rospy.get_name().lstrip("/")
        self.data_server = DataServer(self.name, False, False)
        self.cloud_node = str(rospy.get_param("~cloud_node", "cloud"))
        self.data_server = None
        self.window = None
        self.signals = GuiSignal()

        app = QApplication(sys.argv)
        import signal

        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self.window = MainWindow()
        map_path = str(rospy.get_param("~map_image", ""))
        map_scale = cast(float, rospy.get_param("~map_scale", 1.0))
        if map_path:
            self.window.map_widget.load_map(map_path, map_scale)
        self.window.show()

        self.signals.update_map.connect(self.update_map)  # type: ignore
        self.signals.update_edges.connect(self.update_edges)  # type: ignore
        self.signals.update_task_types.connect(self.update_task_types)  # type: ignore

        self.data_server_sub = rospy.Subscriber(
            f"/{self.cloud_node}/gui/data_server", String, self._data_server_cb
        )
        sys.exit(app.exec_())

    def _data_server_cb(self, msg: String):
        try:
            self.data_server = DataServer.from_json(msg.data)
            self.signals.update_map.emit()  # type: ignore
            self.signals.update_edges.emit()  # type: ignore
            self.signals.update_task_types.emit()  # type: ignore
        except Exception as e:
            rospy.logwarn(f"Failed to parse Data Server: {e}")

    def update_map(self):
        if not (self.window and isinstance(self.data_server, DataServer)):
            return
        # Get edge color for each end
        edge_colors = {}
        ends_raw = list(self.data_server.data_store.get("EndData", {}).values())
        ends = [e for e in ends_raw if isinstance(e, EndData)]
        edges = self.data_server.data_store.get("EdgeData", {})
        for end in ends:
            color = None
            if (
                getattr(end, "related_edge_name", None)
                and end.related_edge_name in edges
            ):
                edge = edges[end.related_edge_name]
                color = getattr(edge, "color", None)
            if not color:
                color = getattr(end, "edge_color", "#494949")
            edge_colors[end.name] = color
        self.window.map_widget.set_data(
            cast(
                List[TaskInstance],
                self.data_server.data_store[TaskInstance.__name__].values(),
            ),
            cast(
                List[ResourceInstance],
                self.data_server.data_store[ResourceInstance.__name__].values(),
            ),
            ends,
            edge_colors,
        )

    def update_edges(self):
        if not (self.window and isinstance(self.data_server, DataServer)):
            return
        self.window.update_edges(
            cast(Dict[str, EdgeData], self.data_server.data_store[EdgeData.__name__])
        )

    def update_task_types(self):
        if not (self.window and isinstance(self.data_server, DataServer)):
            return
        task_types = cast(
            List[TaskType], self.data_server.data_store[TaskType.__name__].values()
        )
        # 构建优先级DAG：高优先级指向低优先级
        name_priority = {}
        for tt in task_types:
            name_priority[tt.name] = getattr(tt, 'priority', 0)
        # 按优先级分组
        priority_groups = {}
        for name, prio in name_priority.items():
            priority_groups.setdefault(prio, []).append(name)
        priorities = sorted(priority_groups.keys(), reverse=True)  # 高到低
        dag = {name: [] for name in name_priority}
        for i in range(len(priorities) - 1):
            high = priorities[i]
            low = priorities[i + 1]
            for src in priority_groups[high]:
                dag[src].extend(priority_groups[low])
        # schemes逻辑保持不变
        schemes = {}
        for tt in task_types:
            name = tt.name
            if "global_exp" in name:
                continue
            if hasattr(tt, "scheme_types") and tt.scheme_types:
                scheme_lines = []
                for i, s in enumerate(tt.scheme_types):
                    scheme_lines.append(f"Scheme{i+1}:")
                    for sub in s:
                        subtask_obj = self.data_server.get_data(sub, SubtaskType)
                        display_name = subtask_obj.required_skill
                        if subtask_obj.required_resource != "":
                            display_name = f"{display_name} ({subtask_obj.required_resource})"
                        if subtask_obj.target != "this":
                            display_name = f"{display_name} to ({subtask_obj.target})"
                        scheme_lines.append(f"  - {display_name}")
                scheme_str = "\n".join(scheme_lines)
            else:
                scheme_str = "No Scheme"
            schemes[name] = scheme_str
        self.window.task_dag_widget.set_dependencies(dag)
        self.window.scheme_widget.set_schemes(schemes)


if __name__ == "__main__":
    try:
        node = GuiNode()
    except rospy.ROSInterruptException:
        pass
