#!/usr/bin/env python3

import sys
import os
from typing import Dict
import uuid
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QTextEdit,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
import rospy
import json
from threading import Event
from PyQt5.QtGui import QPixmap, QImage

from main.srv import StringSrv, StringSrvRequest, StringSrvResponse, StrListSrv, StrListSrvRequest, StrListSrvResponse
from sensor_msgs.msg import Image as RosImage
from main.srv import ImageSrv, ImageSrvRequest, ImageSrvResponse
import cv_bridge
from assignment_widget import AssignmentWidget
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QPushButton
from attribute_widget import AttributeWidget


class VerificationSignal(QObject):
    show_dialog = pyqtSignal(str, str, str)  # 增加 request_id
    dialog_result = pyqtSignal(str, bool, str)   # request_id, confirmed, edited_text
    show_image_dialog = pyqtSignal(object, str, str)  # image(QImage), message, request_id
    image_dialog_result = pyqtSignal(str, bool, str)  # request_id, confirmed, edited_text
    show_multi_select_dialog = pyqtSignal(list, str)  # options_list, request_id
    multi_select_dialog_result = pyqtSignal(str, bool, list)  # request_id, confirmed, selected_list
    show_single_select_dialog = pyqtSignal(str, list, str)  # question, options_list, request_id
    single_select_dialog_result = pyqtSignal(str, bool, str)  # request_id, confirmed, selected_option
    assignment_edit_request = pyqtSignal(str, str)  # assignment_json, request_id
    assignment_edit_result = pyqtSignal(str, bool, str)  # request_id, confirmed, assignment_json
    property_verification_request = pyqtSignal(str, str)  # property_json, request_id
    property_verification_result = pyqtSignal(str, bool, str)  # request_id, confirmed, property_json

    def __init__(self):
        super().__init__()


class VerificationDialog(QDialog):
    def __init__(self, module_name, result_text, parent=None):
        super().__init__(parent)
        self.resize(600, 700)
        self.setWindowTitle(f"{module_name} Result")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # 始终置顶
        layout = QVBoxLayout(self)
        # 可编辑文本框
        self.text_edit = QTextEdit()
        self.text_edit.setText(result_text)
        layout.addWidget(self.text_edit)
        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm")
        self.cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        self._result = None
        self.confirm_btn.clicked.connect(self.on_confirm)  # type: ignore
        self.cancel_btn.clicked.connect(self.on_cancel)  # type: ignore

    def on_confirm(self):
        self._result = True
        self.accept()

    def on_cancel(self):
        self._result = False
        self.reject()

    def get_text(self):
        return self.text_edit.toPlainText()


class ImageVerificationDialog(QDialog):
    def __init__(self, image: QImage, message: str, parent=None):
        super().__init__(parent)
        self.resize(600, 700)
        config = json.loads(message)
        if "module_name" in config:
            self.setWindowTitle(f"{config['module_name']} Result")
        else:
            self.setWindowTitle("Image Verification")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)  # 始终置顶
        layout = QVBoxLayout(self)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)  # 不自动拉伸，手动缩放
        self._pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(self._scaled_pixmap())
        layout.addWidget(self.image_label, 3)
        self.text_edit = QTextEdit()
        # 尝试格式化为 JSON
        if "result" in config:
            try:
                parsed = json.loads(config["result"])
                formatted = json.dumps(parsed, indent=4, ensure_ascii=False)
                self.text_edit.setText(formatted)
            except Exception:
                self.text_edit.setText(config["result"])
        else:
            self.text_edit.setText(message)
        layout.addWidget(self.text_edit, 1)
        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm")
        self.cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        self._result = None
        self.confirm_btn.clicked.connect(self.on_confirm) #type: ignore
        self.cancel_btn.clicked.connect(self.on_cancel) #type: ignore

    def _scaled_pixmap(self):
        # 根据label大小缩放pixmap，保持比例且不超出label
        if self.image_label.width() > 0 and self.image_label.height() > 0:
            return self._pixmap.scaled(
                self.image_label.width(),
                self.image_label.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        return self._pixmap

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self.image_label.setPixmap(self._scaled_pixmap())

    def on_confirm(self):
        self._result = True
        self.accept()

    def on_cancel(self):
        self._result = False
        self.reject()

    def get_text(self):
        return self.text_edit.toPlainText()


class MultiSelectDialog(QDialog):
    def __init__(self, options_list, parent=None):
        super().__init__(parent)
        self.resize(400, 500)
        self.setWindowTitle("Task Types to Regenerate Subtasks")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        self.checkboxes = []
        for opt in options_list:
            cb = QCheckBox(opt)
            layout.addWidget(cb)
            self.checkboxes.append(cb)
        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm")
        self.cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        self._result = None
        self.confirm_btn.clicked.connect(self.on_confirm) # type: ignore
        self.cancel_btn.clicked.connect(self.on_cancel) # type: ignore

    def on_confirm(self):
        self._result = True
        self.accept()

    def on_cancel(self):
        self._result = False
        self.reject()

    def get_selected(self):
        selected = [cb.text() for cb in self.checkboxes if cb.isChecked()]
        return selected


class SingleSelectDialog(QDialog):
    def __init__(self, question, options_list, parent=None):
        super().__init__(parent)
        self.resize(400, 500)
        self.setWindowTitle("Single Select")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        
        question_label = QLabel(question)
        layout.addWidget(question_label)

        self.radio_buttons = []
        self.button_group = QButtonGroup(self)
        for opt in options_list:
            rb = QRadioButton(opt)
            layout.addWidget(rb)
            self.radio_buttons.append(rb)
            self.button_group.addButton(rb)

        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm")
        self.cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        self._result = None
        self.confirm_btn.clicked.connect(self.on_confirm) # type: ignore
        self.cancel_btn.clicked.connect(self.on_cancel) # type: ignore

    def on_confirm(self):
        self._result = True
        self.accept()

    def on_cancel(self):
        self._result = False
        self.reject()

    def get_selected(self):
        for rb in self.radio_buttons:
            if rb.isChecked():
                return rb.text()
        return ""


class AssignmentEditDialog(QDialog):
    def __init__(self, assignment_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Assignment")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        self.widget = AssignmentWidget(assignment_dict)
        layout.addWidget(self.widget)
        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.clicked.connect(self.accept) # type: ignore
        layout.addWidget(self.confirm_btn)

    def get_assignment(self):
        return self.widget.get_assignment()


class PropertyEditDialog(QDialog):
    def __init__(self, data_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Properties")
        self.resize(600, 600)
        layout = QVBoxLayout(self)
        self.widget = AttributeWidget(data_dict)
        layout.addWidget(self.widget)
        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.clicked.connect(self.accept) # type: ignore
        layout.addWidget(self.confirm_btn)

    def get_data(self):
        return self.widget.get_data()


class MainApp(QApplication):
    def __init__(self, sys_argv, signal_obj: VerificationSignal):
        super().__init__(sys_argv)
        self.setQuitOnLastWindowClosed(False)  # 防止弹窗关闭后主循环退出
        self.signal_obj = signal_obj
        self._events: Dict[str, Event] = {}  # request_id: Event
        self._results = {} # request_id: (result, edited_text)
        self.signal_obj.show_dialog.connect(self.show_verification_dialog)  # type: ignore
        self.signal_obj.dialog_result.connect(self.on_dialog_result)        # type: ignore
        self.signal_obj.show_image_dialog.connect(self.show_image_verification_dialog) #type: ignore
        self.signal_obj.image_dialog_result.connect(self.on_image_dialog_result) #type: ignore
        self.signal_obj.show_multi_select_dialog.connect(self.show_multi_select_dialog_slot)  # type: ignore
        self.signal_obj.multi_select_dialog_result.connect(self.on_multi_select_dialog_result)  # type: ignore
        self.signal_obj.show_single_select_dialog.connect(self.show_single_select_dialog_slot)  # type: ignore
        self.signal_obj.single_select_dialog_result.connect(self.on_single_select_dialog_result)  # type: ignore
        self.signal_obj.assignment_edit_request.connect(self.show_assignment_edit_dialog)  # type: ignore
        self.signal_obj.assignment_edit_result.connect(self.on_assignment_edit_result)  # type: ignore
        self.signal_obj.property_verification_request.connect(self.show_property_verification_dialog)  # type: ignore
        self.signal_obj.property_verification_result.connect(self.on_property_verification_result)  # type: ignore
        self._image_results = {}  # request_id: (confirmed, text)
        self._multi_select_results = {}  # request_id: (confirmed, selected_list)
        self._single_select_results = {}  # request_id: (confirmed, selected_option)
        self._assignment_edit_results = {}  # request_id: (confirmed, assignment_json)
        self._property_verification_results = {}  # request_id: (confirmed, property_json)

    def show_verification_dialog(self, module_name, result_text, request_id):
        dialog = VerificationDialog(module_name, result_text)
        res = dialog.exec_()
        edited_text = dialog.get_text()
        self.signal_obj.dialog_result.emit(request_id, dialog._result, edited_text) # type: ignore

    def on_dialog_result(self, request_id, result, edited_text):
        self._results[request_id] = (result, edited_text)
        if request_id in self._events:
            self._events[request_id].set()

    def show_image_verification_dialog(self, qimage, message, request_id):
        dialog = ImageVerificationDialog(qimage, message)
        res = dialog.exec_()
        edited_text = dialog.get_text()
        self.signal_obj.image_dialog_result.emit(request_id, dialog._result, edited_text) #type: ignore

    def on_image_dialog_result(self, request_id, confirmed, text):
        self._image_results[request_id] = (confirmed, text)
        if request_id in self._events:
            self._events[request_id].set()

    def show_multi_select_dialog_slot(self, options_list, request_id):
        dialog = MultiSelectDialog(options_list)
        res = dialog.exec_()
        selected_list = dialog.get_selected()
        self.signal_obj.multi_select_dialog_result.emit(request_id, dialog._result, selected_list) # type: ignore

    def on_multi_select_dialog_result(self, request_id, confirmed, selected_list):
        self._multi_select_results[request_id] = (confirmed, selected_list)
        if request_id in self._events:
            self._events[request_id].set()

    def show_single_select_dialog_slot(self, question, options_list, request_id):
        dialog = SingleSelectDialog(question, options_list)
        res = dialog.exec_()
        selected_option = dialog.get_selected()
        self.signal_obj.single_select_dialog_result.emit(request_id, dialog._result, selected_option) # type: ignore

    def on_single_select_dialog_result(self, request_id, confirmed, selected_option):
        self._single_select_results[request_id] = (confirmed, selected_option)
        if request_id in self._events:
            self._events[request_id].set()

    def show_assignment_edit_dialog(self, assignment_json, request_id):
        import json
        assignment_dict = json.loads(assignment_json)
        dialog = AssignmentEditDialog(assignment_dict["result"])
        res = dialog.exec_()
        new_assignment = dialog.get_assignment()
        new_json = json.dumps(new_assignment, ensure_ascii=False)
        self.signal_obj.assignment_edit_result.emit(request_id, res == QDialog.Accepted, new_json) # type: ignore

    def on_assignment_edit_result(self, request_id, confirmed, assignment_json):
        self._assignment_edit_results[request_id] = (confirmed, assignment_json)
        if request_id in self._events:
            self._events[request_id].set()

    def show_property_verification_dialog(self, property_json, request_id):
        import json
        data_dict = json.loads(property_json)
        dialog = PropertyEditDialog(data_dict)
        res = dialog.exec_()
        new_data = dialog.get_data()
        new_json = json.dumps(new_data, ensure_ascii=False)
        self.signal_obj.property_verification_result.emit(request_id, res == QDialog.Accepted, new_json)  # type: ignore

    def on_property_verification_result(self, request_id, confirmed, property_json):
        self._property_verification_results[request_id] = (confirmed, property_json)
        if request_id in self._events:
            self._events[request_id].set()


class VerificationServer:
    def __init__(self, qt_app: MainApp, signal_obj: VerificationSignal):
        self.qt_app = qt_app
        self.signal_obj = signal_obj
        self.name = str(rospy.get_param("~name", ""))
        self.service = rospy.Service(f"{self.name}/gui/verification", StringSrv, self.handle_request)
        self.image_service = rospy.Service(f"{self.name}/gui/image_verification", ImageSrv, self.handle_image_request)
        self.multi_select_service = rospy.Service(f"{self.name}/gui/multi_select", StrListSrv, self.handle_multi_select_request)
        self.single_select_service = rospy.Service(f"{self.name}/gui/single_select", StringSrv, self.handle_single_select_request)
        self.assignment_edit_service = rospy.Service(f"{self.name}/gui/assignment_verification", StringSrv, self.handle_assignment_edit_request)
        self.property_verification_service = rospy.Service(
            f"{self.name}/gui/property_verification", StringSrv, self.handle_property_verification_request)
        self.bridge = cv_bridge.CvBridge()

    def handle_request(self, req: StringSrvRequest) -> StringSrvResponse:
        req_data = json.loads(req.data)
        module_name: str = req_data["module_name"]
        result = req_data["result"]
        request_id = str(uuid.uuid4())
        event = Event()
        self.qt_app._events[request_id] = event

        formatted = json.dumps(result, indent=4, ensure_ascii=False)
        result = formatted

        self.signal_obj.show_dialog.emit(module_name, result, request_id)  # type: ignore
        self.qt_app._events[request_id].wait()
        confirmed, edited_text = self.qt_app._results.get(request_id, (False, str(result)))
        del self.qt_app._events[request_id]
        del self.qt_app._results[request_id]
        return StringSrvResponse(confirmed, edited_text)

    def handle_image_request(self, req: ImageSrvRequest) -> ImageSrvResponse:
        # req.image: sensor_msgs/Image, req.message: str
        qimage = self.rosimg_to_qimage(req.image)
        request_id = str(uuid.uuid4())
        event = Event()
        self.qt_app._events[request_id] = event
        self.signal_obj.show_image_dialog.emit(qimage, req.message, request_id) #type: ignore
        self.qt_app._events[request_id].wait()
        confirmed, edited_text = self.qt_app._image_results.get(request_id, (False, req.message))
        del self.qt_app._events[request_id]
        del self.qt_app._image_results[request_id]
        # 返回原图和编辑后的文字
        return ImageSrvResponse(confirmed, req.image, edited_text)

    def handle_multi_select_request(self, req: StrListSrvRequest) -> StrListSrvResponse:
        options_list = req.data
        request_id = str(uuid.uuid4())
        event = Event()
        self.qt_app._events[request_id] = event
        self.signal_obj.show_multi_select_dialog.emit(options_list, request_id) # type: ignore
        self.qt_app._events[request_id].wait()
        confirmed, selected_list = self.qt_app._multi_select_results.get(request_id, (False, []))
        del self.qt_app._events[request_id]
        del self.qt_app._multi_select_results[request_id]
        return StrListSrvResponse(confirmed, selected_list)

    def handle_single_select_request(self, req: StringSrvRequest) -> StringSrvResponse:
        req_data = json.loads(req.data)
        question = req_data["question"]
        options = req_data["options"]
        request_id = str(uuid.uuid4())
        event = Event()
        self.qt_app._events[request_id] = event
        self.signal_obj.show_single_select_dialog.emit(question, options, request_id) # type: ignore
        self.qt_app._events[request_id].wait()
        confirmed, selected_option = self.qt_app._single_select_results.get(request_id, (False, ""))
        del self.qt_app._events[request_id]
        del self.qt_app._single_select_results[request_id]
        return StringSrvResponse(confirmed, selected_option)

    def handle_assignment_edit_request(self, req: StringSrvRequest) -> StringSrvResponse:
        import json
        assignment_json = req.data
        request_id = str(uuid.uuid4())
        event = Event()
        self.qt_app._events[request_id] = event
        self.signal_obj.assignment_edit_request.emit(assignment_json, request_id) # type: ignore
        self.qt_app._events[request_id].wait()
        confirmed, new_json = self.qt_app._assignment_edit_results.get(request_id, (False, assignment_json))
        del self.qt_app._events[request_id]
        del self.qt_app._assignment_edit_results[request_id]
        return StringSrvResponse(confirmed, new_json)

    def handle_property_verification_request(self, req: StringSrvRequest) -> StringSrvResponse:
        property_json = req.data
        request_id = str(uuid.uuid4())
        event = Event()
        self.qt_app._events[request_id] = event
        self.signal_obj.property_verification_request.emit(property_json, request_id)  # type: ignore
        self.qt_app._events[request_id].wait()
        confirmed, new_json = self.qt_app._property_verification_results.get(request_id, (False, property_json))
        del self.qt_app._events[request_id]
        del self.qt_app._property_verification_results[request_id]
        return StringSrvResponse(confirmed, new_json)

    def rosimg_to_qimage(self, ros_img):
        try:
            cv_img = self.bridge.imgmsg_to_cv2(ros_img, desired_encoding="bgr8")
            h, w, ch = cv_img.shape
            bytes_per_line = ch * w
            # QImage.Format_BGR888 is not always available, use Format_RGB888 after conversion
            import cv2
            cv_img_rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            qimg = QImage(cv_img_rgb.data, w, h, 3 * w, QImage.Format_RGB888)
            return qimg.copy()
        except Exception:
            return QImage()


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    rospy.init_node("verification_server", anonymous=True)
    signal_obj = VerificationSignal()
    qt_app = MainApp(sys.argv, signal_obj)
    server = VerificationServer(qt_app, signal_obj)

    # 定时检查 ROS 是否 shutdown，若是则退出 Qt 应用
    from PyQt5.QtCore import QTimer
    def check_ros_shutdown():
        if rospy.is_shutdown():
            qt_app.quit()
    timer = QTimer()
    timer.timeout.connect(check_ros_shutdown)  # type: ignore
    timer.start(200)

    sys.exit(qt_app.exec_())
