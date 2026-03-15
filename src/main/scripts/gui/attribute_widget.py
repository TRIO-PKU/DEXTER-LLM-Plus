from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLabel, QLineEdit, QScrollArea, QApplication, QDialog, QPushButton
import json

class AttributeWidget(QWidget):
    def __init__(self, data_dict, parent=None):
        super().__init__(parent)
        self._editors = {}  # {object_name: {attr: QLineEdit}}
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        for obj_name, attr_dict in data_dict.items():
            group = QGroupBox(str(obj_name))
            form = QFormLayout()
            self._editors[obj_name] = {}
            for attr, value in attr_dict.items():
                # 显示为 JSON 字符串
                edit = QLineEdit(json.dumps(value, ensure_ascii=False))
                self._editors[obj_name][attr] = edit
                form.addRow(QLabel(str(attr)), edit)
            group.setLayout(form)
            content_layout.addWidget(group)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def get_data(self):
        result = {}
        for obj_name, attr_editors in self._editors.items():
            result[obj_name] = {}
            for attr, edit in attr_editors.items():
                text = edit.text()
                try:
                    # 尝试解析为 JSON
                    value = json.loads(text)
                except Exception:
                    value = text
                result[obj_name][attr] = value
        return result

if __name__ == "__main__":
    import sys

    test_data = {
        "object1": {
            "str": "hello",
            "int": 123,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"a": 1, "b": 2}
        },
        "object2": {
            "none": None,
            "nested": {"x": [1, {"y": False}]},
            "chinese": "测试",
            "json_str": '{"foo": "bar"}'
        }
    }

    class TestDialog(QDialog):
        def __init__(self, data):
            super().__init__()
            self.setWindowTitle("AttributeWidget 测试")
            layout = QVBoxLayout(self)
            self.widget = AttributeWidget(data)
            layout.addWidget(self.widget)
            self.btn = QPushButton("打印当前数据并关闭")
            self.btn.clicked.connect(self.on_print_and_close) # type: ignore
            layout.addWidget(self.btn)
        def on_print_and_close(self):
            print(self.widget.get_data())
            self.accept()

    app = QApplication(sys.argv)
    dlg = TestDialog(test_data)
    dlg.exec_()
