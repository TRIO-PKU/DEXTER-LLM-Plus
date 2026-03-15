#!/usr/bin/env python3

from typing import Dict
from PyQt5.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QApplication,
    QWidget,
    QVBoxLayout,
    QGraphicsPathItem,
)
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QPen, QColor, QPainter, QPainterPath

import rospy
from std_msgs.msg import String

# --- 配置 ---
CLOUD_MODULES = ["Task Comprehension", "Task Coordination"]
EDGE_MODULES = [
    "Global Info",
    "Task Generation",
    "Subtask Generation",
    "Subtask Ins. & Alloc.",
]
END_MODULES = ["Moving", "Executing"]
MODULE_COLORS = {
    "inactive": QColor("#C8C8C8"),
    "active": QColor("#64C864"),
    "border": QColor("#505050"),
}


class ModuleBlockItem(QGraphicsRectItem):
    def __init__(self, name, rect, parent=None):
        # 动态调整块大小以适应文字
        x, y, w, h = rect
        # 先用默认宽高
        super().__init__(x, y, w, h)
        if parent is not None:
            self.setParentItem(parent)
        self.name = name
        # 创建文字项，测量其实际宽高
        self.text = QGraphicsTextItem(name)
        font = self.text.font()
        font.setPointSize(10)
        self.text.setFont(font)
        # 计算文本实际宽高
        text_rect = self.text.boundingRect()
        pad_x, pad_y = 10, 6
        min_w, min_h = 60, 20
        new_w = max(w, text_rect.width() + pad_x * 2, min_w)
        new_h = max(h, text_rect.height() + pad_y * 2, min_h)
        # 重新设置块大小
        self.setRect(x, y, new_w, new_h)
        # 设置背景和边框
        self.setBrush(MODULE_COLORS["inactive"])
        self.setPen(QPen(MODULE_COLORS["border"], 2))
        # 设置文字位置居中
        self.text.setParentItem(self)
        self.text.setPos(
            x + (new_w - text_rect.width()) / 2, y + (new_h - text_rect.height()) / 2
        )
        self.setZValue(1)
        self.active = False

    def set_active(self, active: bool):
        self.active = active
        self.setBrush(MODULE_COLORS["active"] if active else MODULE_COLORS["inactive"])


class NodeGroupItem(QGraphicsRectItem):
    def __init__(self, name, rect, modules, module_layout, parent=None):
        # rect: (x, y, w, h) 其中x, y仅用于整体放置，内部布局全部用(0, 0)
        x, y, w, h = rect
        module_blocks = []
        max_mod_w, total_mod_h = 0, 0
        pad_x, pad_y = 10, 8
        spacing_y = 8
        spacing_x = 12  # 横向间距
        for i, m in enumerate(modules):
            temp_block = ModuleBlockItem(m, (0, 0, 0, 0))
            mod_rect = temp_block.rect()
            mod_w, mod_h = mod_rect.width(), mod_rect.height()
            max_mod_w = max(max_mod_w, mod_w)
            total_mod_h += mod_h
            module_blocks.append((mod_w, mod_h))
        total_mod_h += (len(modules) - 1) * spacing_y
        # Data模块尺寸
        data_block = ModuleBlockItem("Data", (0, 0, 0, 0))
        data_rect = data_block.rect()
        data_w, data_h = data_rect.width(), data_rect.height()
        is_cloud = name.lower() == "cloud"
        if is_cloud:
            # 统一cloud子模块宽度
            uniform_mod_w = max(max_mod_w, 120)
            n_blocks = len(modules) + 1  # 包含Data块
            total_mod_w = uniform_mod_w * n_blocks + spacing_x * (n_blocks - 1)
            new_w = max(w, total_mod_w + pad_x * 2, 100)
            new_h = max(h, max([h for _, h in module_blocks] + [data_h]) + pad_y * 2 + 24, 60)
            super().__init__(0, 0, new_w, new_h)
            if parent is not None:
                self.setParentItem(parent)
            self.name = name
            self.modules: Dict[str, ModuleBlockItem] = {}
            self.setPen(QPen(Qt.black, 2))
            self.setBrush(QColor(240, 240, 255))
            self.text = QGraphicsTextItem(name, self)
            font = self.text.font()
            font.setBold(True)
            font.setPointSize(11)
            self.text.setFont(font)
            text_rect = self.text.boundingRect()
            self.text.setPos((new_w - text_rect.width()) / 2, 6)
            cur_x = pad_x
            cur_y = 24 + pad_y
            for i, m in enumerate(modules):
                mod_w, mod_h = module_blocks[i]
                mod_item = ModuleBlockItem(m, (cur_x, cur_y, uniform_mod_w, mod_h), self)
                self.modules[m] = mod_item
                cur_x += uniform_mod_w + spacing_x
            data_x = cur_x
            data_y = cur_y
            data_item = ModuleBlockItem("Data", (data_x, data_y, uniform_mod_w, new_h - 24 - pad_y * 2), self)
            self.modules["Data"] = data_item
        else:
            # Data块高度与左侧所有模块总高度一致，宽度与左侧模块最大宽度一致
            new_w = max(w, max_mod_w + data_w + spacing_x + pad_x * 2, 100)
            new_h = max(h, max(total_mod_h, data_h) + pad_y * 2 + 24, 60)
            super().__init__(0, 0, new_w, new_h)
            if parent is not None:
                self.setParentItem(parent)
            self.name = name
            self.modules: Dict[str, ModuleBlockItem] = {}
            self.setPen(QPen(Qt.black, 2))
            self.setBrush(QColor(240, 240, 255))
            self.text = QGraphicsTextItem(name, self)
            font = self.text.font()
            font.setBold(True)
            font.setPointSize(11)
            self.text.setFont(font)
            text_rect = self.text.boundingRect()
            self.text.setPos((new_w - text_rect.width()) / 2, 6)
            cur_y = 30
            for i, m in enumerate(modules):
                mod_w, mod_h = module_blocks[i]
                mod_x = pad_x
                mod_item = ModuleBlockItem(m, (mod_x, cur_y, max_mod_w, mod_h), self)
                self.modules[m] = mod_item
                cur_y += mod_h + spacing_y
            # Data块竖着放在右侧，高度与左侧所有模块一致
            data_x = pad_x + max_mod_w + spacing_x
            data_y = 30
            data_item = ModuleBlockItem("Data", (data_x, data_y, data_w, total_mod_h), self)
            self.modules["Data"] = data_item
        # 最后整体放置
        self.setPos(x, y)

    def set_module_state(self, module, active):
        if module in self.modules:
            self.modules[module].set_active(active)


class DataFlowGraphWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.node_items: dict[str, NodeGroupItem] = {}
        self.line_items: dict[tuple[str, str], QGraphicsPathItem] = {}
        self.module_state: dict[str, dict[str, bool]] = {}
        self._ros_msg_buffer: list[tuple[str, str, bool]] = []
        self._comm_vis_buffer: list[tuple[str, str]] = []
        self.line_highlight_timers: dict[tuple[str, str], QTimer] = {}
        self._group_info_buffer: list[dict] = []

        self._ros_sub = rospy.Subscriber("/gui/module_state", String, self._ros_cb)
        self._ros_comm_vis_sub = rospy.Subscriber("/gui/layer_comm_vis", String, self._ros_comm_vis_cb)
        self._ros_group_info_sub = rospy.Subscriber("/group_info", String, self._ros_group_info_cb)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._process_ros_msgs)  # type: ignore
        self._timer.start(100)

    def _ros_cb(self, msg: String):
        try:
            node, module, state = msg.data.split(",")
            active = state.strip().lower() == "active"
            self._ros_msg_buffer.append((node, module, active))
        except Exception as e:
            print(f"[WARN] Bad module state msg: {msg.data}")

    def _ros_comm_vis_cb(self, msg: String):
        try:
            src, dst = msg.data.split(",")
            src, dst = src.strip(), dst.strip()
            self._comm_vis_buffer.append((src, dst))
        except Exception as e:
            print(f"[WARN] Bad comm vis msg: {msg.data}")

    def _ros_group_info_cb(self, msg: String):
        import json
        try:
            group_info = json.loads(msg.data)
            self._group_info_buffer.append(group_info)
        except Exception as e:
            print(f"[WARN] Bad group info msg: {msg.data}, error: {e}")

    def _highlight_line(self, key):
        # 保证在主线程执行
        QTimer.singleShot(0, lambda: self.highlight_line_slot(key))

    def highlight_line_slot(self, key):
        if key in self.line_items:
            line_key = key
        elif (key[1], key[0]) in self.line_items:
            line_key = (key[1], key[0])
        else:
            return
        line = self.line_items[line_key]
        # 变为红色
        line.setPen(QPen(QColor("#ff0000"), 2))
        # 如果已有定时器，先停止
        if line_key in self.line_highlight_timers:
            self.line_highlight_timers[line_key].stop()
            self.line_highlight_timers.pop(line_key, None)
        def reset_color():
            if line_key in self.line_items:
                self.line_items[line_key].setPen(QPen(Qt.gray, 2))
        QTimer.singleShot(1000, reset_color)

    def _process_ros_msgs(self):
        # 定时处理缓存的ROS消息
        while self._ros_msg_buffer:
            node, module, active = self._ros_msg_buffer.pop(0)
            self.set_module_state(node, module, active)
        while self._comm_vis_buffer:
            src, dst = self._comm_vis_buffer.pop(0)
            self._highlight_line((src, dst))
        while self._group_info_buffer:
            group_info = self._group_info_buffer.pop(0)
            self.set_group_info(group_info)

    def set_group_info(self, group_info):
        self._scene.clear()
        self.node_items.clear()
        self.line_items.clear()
        self.module_state.clear()
        # 停止所有高亮 QTimer，防止悬挂回调访问已清空的 line_items
        for timer in self.line_highlight_timers.values():
            timer.stop()
        self.line_highlight_timers.clear()
        # Layout参数
        x0, y0 = 300, 50
        cloud_w, cloud_h = 180, 80
        edge_w, edge_h = 160, 80
        end_w, end_h = 100, 50
        h_gap = 100 
        # 统计
        cloud_name = list(group_info.keys())[0]
        edges = list(group_info[cloud_name].keys())
        all_ends = []
        for edge in edges:
            all_ends.extend(group_info[cloud_name][edge])
        n_end = len(all_ends)
        # 先生成所有End节点，获取实际高度
        # 竖直排列end节点，每个edge下的end竖直排列，edge之间横向排列
        end_items = []
        end_pos_dict = {}
        edge_end_map = {}  # edge: [(end_name, end_item)]
        end_w, end_h = 100, 50
        v_gap_end = 90  # 再次增大end之间的竖直间距
        for edge in edges:
            ends = group_info[cloud_name][edge]
            edge_end_map[edge] = []
            for idx, end in enumerate(ends):
                # x 先不定，y 竖直排列
                end_item = NodeGroupItem(
                    end, (0, 0, end_w, end_h), END_MODULES, lambda i: (10, 10 + i * 22, 80, 20)
                )
                end_items.append((end, end_item))
                edge_end_map[edge].append((end, end_item))
        # 计算Edge层最大高度
        edge_items = []
        edge_pos_dict = {}
        max_edge_h = 0
        edge_w, edge_h = 160, 80
        spacing_x = 180
        pad_x = 40
        # 横向排列edge
        for i, edge in enumerate(edges):
            edge_item = NodeGroupItem(
                edge, (0, 0, edge_w, edge_h), EDGE_MODULES, lambda idx: (10, 10 + idx * 30, 80, 24)
            )
            edge_items.append((edge, edge_item, i))
            max_edge_h = max(max_edge_h, edge_item.rect().height())
        # 计算edge横向分布
        total_edge_w = len(edges) * edge_w + (len(edges) - 1) * spacing_x
        start_edge_x = x0 + cloud_w / 2 - total_edge_w / 2
        edge_y = y0 + cloud_h + 40
        for i, (edge, edge_item, idx) in enumerate(edge_items):
            ex = start_edge_x + idx * (edge_w + spacing_x)
            edge_item.setPos(ex, edge_y)
            self._scene.addItem(edge_item)
            self.node_items[edge] = edge_item
            edge_pos_dict[edge] = (ex + edge_item.rect().width() / 2, edge_y + edge_item.rect().height())
            self.module_state[edge] = {m: False for m in EDGE_MODULES}
        # cloud节点
        def cloud_layout(idx):
            return (20 + idx * 100, 40, 90, 28)
        cloud_item = NodeGroupItem(
            cloud_name,
            (0, 0, cloud_w, cloud_h),
            CLOUD_MODULES,
            cloud_layout,
        )
        # cloud 居中于所有edge
        actual_cloud_w = cloud_item.rect().width()
        cloud_x = start_edge_x + total_edge_w / 2 - actual_cloud_w / 2
        cloud_item.setPos(cloud_x, y0)
        self._scene.addItem(cloud_item)
        self.node_items[cloud_name] = cloud_item
        self.module_state[cloud_name] = {m: False for m in CLOUD_MODULES}
        # End层，竖直排列，每个edge下的end竖直排列
        end_y_start = edge_y + max_edge_h + 40
        for i, (edge, edge_item, idx) in enumerate(edge_items):
            ends = edge_end_map[edge]
            ex = edge_item.scenePos().x() + edge_item.rect().width() / 2 - end_w / 2
            for j, (end, end_item) in enumerate(ends):
                ey = end_y_start + j * (end_h + v_gap_end)
                end_item.setPos(ex, ey)
                self._scene.addItem(end_item)
                self.node_items[end] = end_item
                end_pos_dict[end] = (ex + end_item.rect().width() / 2, ey)
                self.module_state[end] = {m: False for m in END_MODULES}
        # 连线
        self.line_items.clear()
        # cloud → edge（平滑曲线）
        for edge, edge_item, idx in edge_items:
            cloud_center_x = cloud_item.scenePos().x() + cloud_item.rect().width() / 2
            cloud_bottom_y = cloud_item.scenePos().y() + cloud_item.rect().height()
            edge_center_x = edge_item.scenePos().x() + edge_item.rect().width() / 2
            edge_top_y = edge_item.scenePos().y()
            path = QPainterPath()
            path.moveTo(cloud_center_x, cloud_bottom_y)
            cp1 = QPointF(cloud_center_x, (cloud_bottom_y + edge_top_y) / 2)
            cp2 = QPointF(edge_center_x, (cloud_bottom_y + edge_top_y) / 2)
            edge_center = QPointF(edge_center_x, edge_top_y)
            path.cubicTo(cp1, cp2, edge_center)
            line = self._scene.addPath(path, QPen(Qt.gray, 2))
            self.line_items[(cloud_name, edge)] = line
        # edge → end
        for edge, edge_item, idx in edge_items:
            ends = edge_end_map[edge]
            edge_center_x = edge_item.scenePos().x() + edge_item.rect().width() / 2
            edge_bottom_y = edge_item.scenePos().y() + edge_item.rect().height()
            edge_left_x = edge_item.scenePos().x()
            for j, (end, end_item) in enumerate(ends):
                # 目标点：end左侧中点
                enx = end_item.scenePos().x()
                eny = end_item.scenePos().y() + end_item.rect().height() / 2
                path = QPainterPath()
                # 1. 从edge左侧竖直向下（与end左侧对齐）
                bullet_x = edge_left_x + 40 - j*8 # 与end左侧对齐
                bullet_start_y = edge_bottom_y
                bullet_end_y = eny
                # 竖直下到与end中点齐平
                path.moveTo(bullet_x, bullet_start_y)
                path.lineTo(bullet_x, bullet_end_y)
                # 水平连到end左侧
                path.lineTo(enx, bullet_end_y)
                line = self._scene.addPath(path, QPen(Qt.gray, 2))
                self.line_items[(edge, end)] = line

    def set_module_state(self, node, module, active):
        if node in self.node_items:
            self.node_items[node].set_module_state(module, active)
            self.module_state[node][module] = active


if __name__ == "__main__":
    import sys
    import signal
    import threading
    
    rospy.init_node("dataflow_graph_gui", anonymous=True)

    app = QApplication(sys.argv)
    win = QWidget()
    layout = QVBoxLayout(win)
    graph = DataFlowGraphWidget()
    layout.addWidget(graph)
    win.resize(1700, 1100)
    win.setWindowTitle("Module Dashboard")
    win.show()
    group_info = {
        "cloud": {
            "edge_exp": ["end_101"],
            "edge_1": [],
        }
    }
    graph.set_group_info(group_info)

    # 处理 Ctrl+C 退出
    def handle_sigint(*args):
        app.quit()
    signal.signal(signal.SIGINT, handle_sigint)

    # 让 ROS 和 Qt 共存
    qt_ros_timer = QTimer()
    qt_ros_timer.timeout.connect(lambda: None)  # type: ignore
    qt_ros_timer.start(100)

    sys.exit(app.exec_())
