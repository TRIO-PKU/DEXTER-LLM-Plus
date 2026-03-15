# assignment_widget.py
# Qt widget for visualizing and editing assignment results (robot-task allocation)

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PyQt5.QtCore import Qt, QMimeData
from PyQt5.QtGui import QDrag

class TaskBlock(QLabel):
    def __init__(self, task_name: str, parent=None):
        super().__init__(task_name.split("#")[0], parent)
        self.setFrameShape(QFrame.Box)
        self.setMargin(5)
        self.setStyleSheet('background-color: #e0f7fa; border: 1px solid #00838f; border-radius: 4px;')
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(60)
        self.setMaximumHeight(32)
        self.task_name: str = task_name
        self.setAcceptDrops(False)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setText(self.task_name)
            drag.setMimeData(mime_data)
            drag.exec_(Qt.MoveAction)

class AssignmentRow(QWidget):
    def __init__(self, robot_name, tasks, parent=None):
        super().__init__(parent)
        self.robot_name = robot_name
        self.tasks = tasks
        self.hbox = QHBoxLayout()
        self.hbox.setContentsMargins(5, 5, 5, 5)
        self.hbox.setSpacing(10)
        self.label = QLabel(f"{robot_name}")
        self.label.setMinimumWidth(100)
        self.hbox.addWidget(self.label)
        for task in tasks:
            block = TaskBlock(task)
            self.hbox.addWidget(block)
        self.hbox.addStretch()
        self.setLayout(self.hbox)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, a0):
        if a0.mimeData().hasText():
            a0.acceptProposedAction()

    def dropEvent(self, a0):
        task_name = a0.mimeData().text()
        source = a0.source()
        if isinstance(source, TaskBlock):
            source.deleteLater()
        new_block = TaskBlock(task_name)
        self.hbox.insertWidget(self.hbox.count() - 1, new_block)
        a0.acceptProposedAction()
        # Optionally: emit a signal to notify parent widget of the change

class AssignmentWidget(QWidget):
    """
    Widget to visualize and edit assignment results.
    assignment_dict: {robot_name: [task1, task2, ...], ...}
    """
    def __init__(self, assignment_dict, parent=None):
        super().__init__(parent)
        self.assignment_dict = assignment_dict
        self.vbox = QVBoxLayout()
        self.vbox.setContentsMargins(10, 10, 10, 10)
        self.vbox.setSpacing(10)
        self.rows = {}
        for robot, tasks in assignment_dict.items():
            row = AssignmentRow(robot, tasks)
            self.vbox.addWidget(row)
            self.rows[robot] = row
        self.vbox.addStretch()
        self.setLayout(self.vbox)

    def get_assignment(self):
        # Return the current assignment as a dict
        result = {}
        for robot, row in self.rows.items():
            tasks = []
            for i in range(1, row.hbox.count() - 1):
                widget = row.hbox.itemAt(i).widget()
                if isinstance(widget, TaskBlock):
                    tasks.append(widget.task_name)
            result[robot] = tasks
        return result
