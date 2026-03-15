#!/usr/bin/env python3

import json
import rospy
import sys
import os
from typing import Dict, List, Tuple, cast, Optional
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QScrollArea,
    QTextEdit,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QBrush, QColor, QPixmap, QImage, QFontMetrics
import cv2
import numpy as np
from sensor_msgs.msg import Image
import cv_bridge

# ensure classes import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from classes import SubtaskInstance, TaskInstance, ResourceInstance, EndData, DataServer
from std_msgs.msg import String
from base_map_widget import BaseMapWidget


# Map widget including tasks, resources, ends
class MapWidget(BaseMapWidget):
    def __init__(self):
        super().__init__()
        self.tasks = []
        self.resources = []
        self.ends = []
        self.end_colors = {}
        self.overlay_images = []

    def set_tasks(self, tasks):
        self.tasks = tasks
        self._update_shapes()

    def set_resources(self, resources):
        self.resources = resources
        self._update_shapes()

    def set_ends(self, ends):
        self.ends = ends
        self._update_shapes()

    def set_end_colors(self, end_colors):
        if end_colors:
            self.end_colors = end_colors
            self._update_shapes()

    def set_overlay_images(self, images):
        self.overlay_images = images
        self.update()

    def update_view(self):
        self.update()

    def _update_shapes(self):
        shapes = []
        for task in self.tasks:
            x, y, _ = task.pos
            shapes.append(
                {
                    "x": x,
                    "y": y,
                    "color": "blue",
                    "shape": "circle",
                    "label": getattr(task, "task_type", getattr(task, "type", None)),
                }
            )
        for res in self.resources:
            x, y, _ = res.pos
            shapes.append(
                {
                    "x": x,
                    "y": y,
                    "color": "green",
                    "shape": "rect",
                    "label": getattr(res, "resource_type", getattr(res, "type", None)),
                }
            )
        for e in self.ends:
            if hasattr(e, "cur_pos") and e.cur_pos:
                x, y, _ = e.cur_pos
                color = getattr(
                    e, "color", self.end_colors.get(getattr(e, "name", ""), "#494949")
                )
                shapes.append(
                    {
                        "x": x,
                        "y": y,
                        "color": color,
                        "shape": "circle",
                        "label": getattr(e, "name", None),
                    }
                )
        self.set_shapes(shapes)


# graph widget same as cloud
from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtGui import QPolygonF
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QGraphicsScene


class GraphWidget(QGraphicsView):
    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setSceneRect(0, 0, 400, 100)
        self.tasks = []  # List[Tuple[str, str]]
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def set_tasks(self, tasks: List[Tuple[str, str]]):
        """
        tasks: List of (name, state), state in ['todo', 'doing', 'done']
        """
        self.tasks = tasks
        self._scene.clear()
        rect_h, spacing = 50, 20
        font = self.font()
        fm = QFontMetrics(font)
        color_map = {
            "todo": QColor("#C8F7C5"),
            "doing": QColor("#FFFACD"),
            "done": QColor("#C0C0C0"),
        }
        x = 0
        block_centers = []
        doing_center = None
        for i, (name, state) in enumerate(tasks):
            rect_w = fm.width(name) + 20  # padding
            color = color_map.get(state, Qt.lightGray)
            self._scene.addRect(x, 25, rect_w, rect_h, brush=QBrush(color))
            txt = self._scene.addText(name)
            txt.setPos(x + 10, 25 + rect_h / 2 - fm.height() / 2)
            center_x = x + rect_w / 2
            block_centers.append(center_x)
            if state == "doing":
                doing_center = center_x
            if i < len(tasks) - 1:
                self._scene.addLine(
                    x + rect_w, 25 + rect_h / 2, x + rect_w + spacing, 25 + rect_h / 2
                )
            x += rect_w + spacing
        self.setSceneRect(0, 0, max(x, 400), rect_h + 50)
        # 自动滚动到doing任务居中
        if doing_center is not None:
            view_w = self.viewport().width()
            scroll_to = max(0, int(doing_center - view_w / 2))
            self.horizontalScrollBar().setValue(scroll_to)
        # 自动调整 sceneRect 以支持滚动
        self.setSceneRect(0, 0, max(x, 400), rect_h + 50)


# main window for edge interface
class MainWindow(QWidget):
    def __init__(self, title: str = "Edge Interface"):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(1920, 750)
        main_layout = QVBoxLayout(self)
        main_splitter = QSplitter(Qt.Vertical)
        top_splitter = QSplitter(Qt.Horizontal)
        self.map_widget = MapWidget()
        top_splitter.addWidget(self.map_widget)

        # Global Info 区域，带标题栏
        global_info_container = QWidget()
        global_info_layout = QVBoxLayout(global_info_container)
        global_info_title = QLabel("Global Info")
        global_info_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #333; padding: 8px; background-color: #f7f7f7; border-bottom: 1px solid #ccc;"
        )
        global_info_layout.addWidget(global_info_title)
        # 新增：图片显示控件
        self.global_info_image = QLabel()
        self.global_info_image.setAlignment(Qt.AlignCenter)
        self.global_info_image.setFixedHeight(120)
        self.global_info_image.setStyleSheet(
            "background: #fafafa; border: 1px solid #eee;"
        )
        global_info_layout.addWidget(self.global_info_image)
        # 原有文本控件
        self.global_info = QTextEdit()
        self.global_info.setReadOnly(True)
        self.global_info.setMinimumWidth(220)
        self.global_info.setMaximumWidth(350)
        self.global_info.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.global_info.setPlaceholderText("Global Info")
        global_info_layout.addWidget(self.global_info)
        top_splitter.addWidget(global_info_container)

        # Task Generation 区域，带标题栏
        task_gen_container = QWidget()
        task_gen_layout = QVBoxLayout(task_gen_container)
        task_gen_title = QLabel("Task Generation")
        task_gen_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #333; padding: 8px; background-color: #f7f7f7; border-bottom: 1px solid #ccc;"
        )
        task_gen_layout.addWidget(task_gen_title)
        self.task_gen = QTextEdit()
        self.task_gen.setReadOnly(True)
        self.task_gen.setMinimumWidth(220)
        self.task_gen.setMaximumWidth(350)
        self.task_gen.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.task_gen.setPlaceholderText("Task Generation")
        task_gen_layout.addWidget(self.task_gen)
        top_splitter.addWidget(task_gen_container)

        # Subtask Generation 区域，带标题栏
        subtask_gen_container = QWidget()
        subtask_gen_layout = QVBoxLayout(subtask_gen_container)
        subtask_gen_title = QLabel("Subtask Generation")
        subtask_gen_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #333; padding: 8px; background-color: #f7f7f7; border-bottom: 1px solid #ccc;"
        )
        subtask_gen_layout.addWidget(subtask_gen_title)
        self.subtask_gen = QTextEdit()
        self.subtask_gen.setReadOnly(True)
        self.subtask_gen.setMinimumWidth(220)
        self.subtask_gen.setMaximumWidth(350)
        self.subtask_gen.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.subtask_gen.setPlaceholderText("Subtask Generation")
        subtask_gen_layout.addWidget(self.subtask_gen)
        top_splitter.addWidget(subtask_gen_container)

        top_splitter.setSizes([500, 250, 250, 250])
        main_splitter.addWidget(top_splitter)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        bottom_content = QWidget()
        self.bottom_layout = QVBoxLayout(bottom_content)
        self.bottom_layout.setSpacing(8)
        self.bottom_layout.setContentsMargins(6, 6, 6, 6)
        scroll_area.setWidget(bottom_content)
        main_splitter.addWidget(scroll_area)
        main_splitter.setSizes([300, 400])
        main_layout.addWidget(main_splitter)
        self.setLayout(main_layout)
        self.edge_widgets: Dict[str, Tuple[GraphWidget, QLabel, QWidget, QLabel]] = {}
        self.data_server = None

    def on_update_data_server(self, data_server: DataServer):
        self.data_server = data_server

    def set_global_info(self, text: str):
        self.global_info.setPlainText(text)

    def set_global_info_image(self, pixmap: QPixmap):
        self.global_info_image.setPixmap(
            pixmap.scaled(
                self.global_info_image.width(),
                self.global_info_image.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def set_task_generation(self, text: str):
        self.task_gen.setPlainText(text)

    def set_subtask_generation(self, text: str):
        self.subtask_gen.setPlainText(text)

    def set_overlay_images(self, images):
        self.map_widget.set_overlay_images(images)

    def set_tasks(self, tasks):
        self.map_widget.set_tasks(tasks)

    def set_resources(self, resources):
        self.map_widget.set_resources(resources)

    def set_ends(self, ends, end_colors=None):
        self.map_widget.set_ends(ends)
        if end_colors:
            self.map_widget.set_end_colors(end_colors)
        self.update_ends(ends)

    def update_map_view(self):
        self.map_widget.update_view()

    def update_ends(self, ends: List[EndData]):
        end_colors = {}
        # 1. 创建或更新每个end的UI
        for idx, e in enumerate(ends):
            name = e.name
            color = QColor(e.color)
            end_colors[name] = color
            if name not in self.edge_widgets:
                # 首次创建UI
                row = QHBoxLayout()
                color_frame = QFrame()
                color_frame.setFixedWidth(16)
                color_frame.setFixedHeight(60)
                color_frame.setStyleSheet(
                    f"background-color: {color.name()}; border-radius: 4px;"
                )
                row.addWidget(color_frame)
                # end名字标签，垂直居中对齐，和color_frame同高
                name_lbl = QLabel(name)
                name_lbl.setFixedWidth(80)
                name_lbl.setFixedHeight(60)
                name_lbl.setAlignment(Qt.AlignVCenter)
                row.addWidget(name_lbl)
                stat_lbl = QLabel()
                stat_lbl.setFixedWidth(90)
                row.addWidget(stat_lbl)
                gw = GraphWidget()
                gw.setFixedHeight(100)
                gw.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                gw.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                row.addWidget(gw, 1)
                row_widget = QWidget()
                row_widget.setLayout(row)
                self.bottom_layout.addWidget(row_widget)
                self.edge_widgets[name] = (gw, stat_lbl, row_widget, name_lbl)
            else:
                gw, stat_lbl, row_widget, name_lbl = self.edge_widgets[name]
            # 2. 刷新UI内容
            todo = len(e.todo_subtask_buffer)
            doing = 1 if e.doing_subtask else 0
            done = len(e.done_subtask_buffer)
            stat_lbl.setText(f"Todo: {todo}\nDoing: {doing}\nDone: {done}")
            name_lbl.setText(name)
            # 刷新GraphWidget
            subtask_states = []
            # 获取所有SubtaskInstance对象（通过data_server）
            for subtask_name in e.my_subtasks:
                if self.data_server is None:
                    subtask_states.append((subtask_name, "todo"))
                    continue
                subtask_obj = cast(
                    SubtaskInstance,
                    self.data_server.data_store[SubtaskInstance.__name__].get(
                        subtask_name, None
                    ),
                )
                if subtask_obj is None:
                    subtask_states.append((subtask_name, "todo"))
                    continue
                display_name = subtask_obj.required_skill
                if subtask_obj.required_resource != "":
                    display_name = f"{display_name} ({subtask_obj.required_resource})"
                if subtask_obj.target != "this":
                    display_name = f"{display_name} to ({subtask_obj.target})"
                if subtask_name in e.todo_subtask_buffer:
                    state = "todo"
                elif subtask_name == e.doing_subtask:
                    state = "doing"
                else:
                    state = "done"
                subtask_states.append((display_name, state))
            gw.set_tasks(subtask_states)
        # 3. 更新map_widget
        self.map_widget.set_ends(ends)
        self.map_widget.set_end_colors(end_colors)
        self.map_widget.update_view()


# 信号类
class GuiSignal(QObject):
    update_data = pyqtSignal(object, object, object)  # tasks, resources, ends
    update_overlay = pyqtSignal(object)
    update_global_info = pyqtSignal(str)
    update_global_info_image = pyqtSignal(object)  # 新增，object为QPixmap
    update_task_gen = pyqtSignal(str)
    update_subtask_gen = pyqtSignal(str)
    update_subtask_alloc = pyqtSignal(str)  # subtask name
    update_data_server = pyqtSignal(object)  # 新增，object为DataServer

    def __init__(self):
        super().__init__()


class GuiNode:
    def __init__(self):
        rospy.init_node("qt_edge_interface", anonymous=True)
        self.edge_name = str(rospy.get_param("~edge_name", "edge_1"))
        app = QApplication(sys.argv)
        import signal

        signal.signal(signal.SIGINT, signal.SIG_DFL)
        self.window = MainWindow(title=self.edge_name)

        # 信号实例
        self.signals = GuiSignal()
        self.signals.update_data.connect(  # type: ignore
            lambda tasks, resources, ends: (
                self.window.set_tasks(tasks),
                self.window.set_resources(resources),
                self.window.set_ends(ends),
                self.window.update_map_view(),
            )
        )
        self.signals.update_overlay.connect(self.window.set_overlay_images)  # type: ignore
        self.signals.update_global_info.connect(self.window.set_global_info)  # type: ignore
        self.signals.update_global_info_image.connect(self.window.set_global_info_image)  # type: ignore
        self.signals.update_task_gen.connect(self.window.set_task_generation)  # type: ignore
        self.signals.update_subtask_gen.connect(self.window.set_subtask_generation)  # type: ignore
        self.signals.update_data_server.connect(self.window.on_update_data_server)  # type: ignore

        # Data Server
        self.data_server_sub = rospy.Subscriber(
            f"/{self.edge_name}/gui/data_server", String, self._data_server_cb
        )

        # Overlay Image
        self.bridge = cv_bridge.CvBridge()
        self.overlay_images = []  # [{pixmap, x, y, w, h}]
        self.image_sub = rospy.Subscriber(
            f"/{self.edge_name}/gui/overlay_image",
            Image,
            self._image_cb,
        )

        # 2d Map
        map_img = str(rospy.get_param("~map_image", ""))
        map_scale = cast(float, rospy.get_param("~map_scale", 1.0))
        if map_img:
            self.window.map_widget.load_map(map_img, map_scale)

        # Global Info
        rospy.Subscriber(
            f"/{self.edge_name}/gui/global_info", String, self._global_info_cb
        )

        # Global Info Image
        self.global_info_image_sub = rospy.Subscriber(
            f"/{self.edge_name}/gui/global_info_image",
            Image,
            self._global_info_image_cb,
        )

        # Task Generation
        rospy.Subscriber(
            f"/{self.edge_name}/gui/task_generation", String, self._task_gen_cb
        )

        # Subtask Generation
        rospy.Subscriber(
            f"/{self.edge_name}/gui/subtask_generation", String, self._subtask_gen_cb
        )

        self.window.show()
        sys.exit(app.exec_())

    def _data_server_cb(self, msg: String):
        self.data_server = DataServer.from_json(msg.data)
        if hasattr(self, "window") and isinstance(self.data_server, DataServer):
            self.signals.update_data_server.emit(self.data_server)  # type: ignore
            tasks = list(self.data_server.data_store[TaskInstance.__name__].values())
            resources = list(
                self.data_server.data_store[ResourceInstance.__name__].values()
            )
            ends = [
                end
                for end in self.data_server.data_store[EndData.__name__].values()
                if getattr(end, "related_edge_name", None) == self.edge_name
            ]
            self.signals.update_data.emit(tasks, resources, ends)  # type: ignore

    def _image_cb(self, msg: Image):
        try:
            pos_str = msg.header.frame_id
            x, y = [float(v) for v in pos_str.split(",")]
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            h, w, _ = cv_img.shape
            cv_img_rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            qimg = QImage(cv_img_rgb.data, w, h, 3 * w, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            show_w, show_h = 6, 6
            overlay_images = [
                {"pixmap": pixmap, "x": x, "y": y, "w": show_w, "h": show_h}
            ]
            self.signals.update_overlay.emit(overlay_images)  # type: ignore
        except Exception as e:
            rospy.logwarn(f"Failed to process overlay image: {e}")

    def _global_info_cb(self, msg: String):
        self.signals.update_global_info.emit(msg.data)  # type: ignore

    def _task_gen_cb(self, msg: String):
        formatted = json.dumps(json.loads(msg.data), indent=4, ensure_ascii=False)
        self.signals.update_task_gen.emit(formatted)  # type: ignore

    def _subtask_gen_cb(self, msg: String):
        formatted = json.dumps(json.loads(msg.data), indent=4, ensure_ascii=False)
        self.signals.update_subtask_gen.emit(formatted)  # type: ignore

    def _global_info_image_cb(self, msg: Image):
        try:
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            h, w, _ = cv_img.shape
            cv_img_rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            qimg = QImage(cv_img_rgb.data, w, h, 3 * w, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            self.signals.update_global_info_image.emit(pixmap)  # type: ignore
        except Exception as e:
            rospy.logwarn(f"Failed to process global info image: {e}")


if __name__ == "__main__":
    try:
        GuiNode()
    except rospy.ROSInterruptException:
        pass
