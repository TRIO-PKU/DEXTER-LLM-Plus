#!/usr/bin/env python3
import sys
import os
import json
import uuid
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel, QWidget, QScrollArea, QFrame, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
import rospy
from threading import Event
from main.srv import StringSrv, StringSrvRequest, StringSrvResponse
from std_msgs.msg import String
from openai import OpenAI
from typing import Optional, List, Tuple, Generator, Any
from PyQt5.QtGui import QPixmap
from rag import RAGKnowledgeBase

class LLMChatSignal(QObject):
    show_chat: pyqtSignal = pyqtSignal(str, str)  # prompt, request_id
    chat_result: pyqtSignal = pyqtSignal(str, str)  # request_id, llm_output

    def __init__(self) -> None:
        super().__init__()
        self._show_chat = self.show_chat
        self._chat_result = self.chat_result

class ChatBubble(QLabel):
    def __init__(self, text: str, is_user: bool) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setStyleSheet(
            "background-color: %s; border-radius: 10px; padding: 8px; margin: 4px;" %
            ("#d1eaff" if is_user else "#e6e6e6")
        )
        self.setAlignment(Qt.AlignLeft if is_user else Qt.AlignRight)

class LLMChatBubble(QWidget):
    def __init__(self, text: str, avatar_path: Optional[str] = None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if avatar_path:
            avatar_label = QLabel()
            pixmap = QPixmap(avatar_path)
            avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            avatar_label.setFixedSize(36, 36)
            layout.addWidget(avatar_label, alignment=Qt.AlignTop)
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_label.setStyleSheet(
            "background-color: #e6e6e6; border-radius: 10px; padding: 8px; margin: 4px; font-size: 16px;"
        )
        text_label.setAlignment(Qt.AlignLeft)
        self.text_label = text_label
        layout.addWidget(text_label)
        layout.addStretch(1)
    def setText(self, text: str):
        self.text_label.setText(text)

class UserChatBubble(QWidget):
    def __init__(self, text: str, avatar_path: Optional[str] = None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_label.setStyleSheet(
            "background-color: #d1eaff; border-radius: 10px; padding: 8px; margin: 4px; font-size: 16px;"
        )
        text_label.setAlignment(Qt.AlignLeft)
        self.text_label = text_label
        layout.addStretch(1)
        layout.addWidget(text_label)
        if avatar_path:
            avatar_label = QLabel()
            pixmap = QPixmap(avatar_path)
            avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            avatar_label.setFixedSize(36, 36)
            layout.addWidget(avatar_label, alignment=Qt.AlignTop)
    def setText(self, text: str):
        self.text_label.setText(text)

class RAGReferencesBubble(QWidget):
    def __init__(self, search_results: List[str], avatar_path: Optional[str] = None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if avatar_path and os.path.exists(avatar_path):
            avatar_label = QLabel()
            pixmap = QPixmap(avatar_path)
            avatar_label.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            avatar_label.setFixedSize(36, 36)
            layout.addWidget(avatar_label, alignment=Qt.AlignTop)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        title_label = QLabel("Search Result")
        title_label.setStyleSheet("color: #7a8a00; font-size: 13px; font-style: italic; margin-bottom: 2px;")
        content_layout.addWidget(title_label)

        for i, result in enumerate(search_results):
            result_label = QLabel(f"{i+1}. {result}")
            result_label.setWordWrap(True)
            result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            result_label.setStyleSheet("font-size: 16px; color: #222; margin-bottom: 2px;")
            result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content_layout.addWidget(result_label)
        content_widget.setStyleSheet(
            "background-color: #e7f7d6; border-radius: 10px; padding: 8px; margin: 4px; "
            "border: 1px solid #bfe2a7;"
        )
        content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(content_widget)

class OpenAILLMClient:
    def __init__(self, api_key: str, api_base: str, model: str) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=api_base)

    def stream_chat(self, history: List[Tuple[str, str]]) -> Generator[str, None, None]:
        messages = []
        for role, text in history:
            messages.append({"role": "user" if role == "user" else "assistant", "content": text})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            response_format={
                'type': 'json_object'
            }
        )
        # 返回生成器，yield每一段内容
        for chunk in response:
            delta = getattr(chunk.choices[0].delta, 'content', None)
            if delta:
                yield delta

class LLMStreamWorker(QThread):
    update = pyqtSignal(str)
    finished = pyqtSignal(str) # type: ignore
    error = pyqtSignal(str)
    def __init__(self, llm_client: Optional[OpenAILLMClient], history: List[Tuple[str, str]]):
        QThread.__init__(self)
        self.llm_client = llm_client
        self.history = history
        self._output = ""
    def run(self):
        if self.llm_client is None:
            self.error.emit("[未配置大模型client]") # type: ignore
            return
        try:
            for delta in self.llm_client.stream_chat(self.history):
                self._output += delta
                self.update.emit(self._output) # type: ignore
            self.finished.emit(self._output) # type: ignore
        except Exception as e:
            self.error.emit(f"[大模型流式调用失败]: {e}") # type: ignore

class LLMChatDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, llm_client: Any = None, log_dir: Optional[str] = None, rag_kb: Optional[RAGKnowledgeBase] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LLM Chat")
        self.resize(600, 700)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        # 聊天展示区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.addStretch(1)
        self._scroll.setWidget(self.chat_widget)
        layout.addWidget(self._scroll)
        # 输入区
        self.input_edit = QTextEdit()
        self.input_edit.setFixedHeight(80)
        layout.addWidget(self.input_edit)
        btn_layout = QHBoxLayout()
        self.send_btn = QPushButton("Send")
        self.confirm_btn = QPushButton("Confirm")
        btn_layout.addWidget(self.send_btn)
        btn_layout.addWidget(self.confirm_btn)
        layout.addLayout(btn_layout)
        # 状态
        self.history = []  # [(role, text)]
        self.llm_output = ""
        self.send_btn.clicked.connect(self.on_send) # type: ignore
        self.confirm_btn.clicked.connect(self.on_confirm) # type: ignore
        self._event = None
        self._request_id = None
        self._signal_obj = None
        self.llm_client: Any = llm_client
        self.log_dir: Optional[str] = log_dir
        self.rag_kb = rag_kb
        self.record_jsonl_pub = rospy.Publisher(
            "/record_jsonl", String, queue_size=10, latch=True
        )
        self.llm_start_time = rospy.Time.now()

    def set_signal(self, signal_obj: LLMChatSignal) -> None:
        self._signal_obj = signal_obj

    def set_event(self, event: Optional[Event]) -> None:
        self._event = event

    def set_request_id(self, request_id: Optional[str]) -> None:
        self._request_id = request_id

    def set_prompt(self, prompt: str) -> None:
        self.input_edit.setText(prompt)

    def on_send(self) -> None:
        user_text = self.input_edit.toPlainText().strip()
        if not user_text:
            return

        avatar_path = os.path.join(os.path.dirname(__file__), "a_user_avatar.png")
        bubble = UserChatBubble(user_text, avatar_path=avatar_path)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, bubble)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())
        self.history.append(("user", user_text))
        self.input_edit.clear()

        history_for_llm = list(self.history)
        rag_enabled = False
        rag_content = None
        # 自动判断是否启用RAG
        try:
            user_json = json.loads(user_text)
            if isinstance(user_json, dict) and "rag" in user_json:
                rag_enabled = True
                rag_content = user_json["rag"]
        except Exception:
            pass

        if rag_enabled and self.rag_kb and self.rag_kb.retriever and self.rag_kb.retriever.is_ready():
            # 使用rag_content作为检索内容，否则回退到原始输入
            search_query = rag_content if rag_content else user_text
            search_results = self.rag_kb.search(search_query, top_k=1)
            if search_results:
                rag_avatar_path = os.path.join(os.path.dirname(__file__), "a_rag_avatar.png")
                rag_bubble = RAGReferencesBubble(search_results, avatar_path=rag_avatar_path)
                self.chat_layout.insertWidget(self.chat_layout.count()-1, rag_bubble)
                self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

                context = "\n\n---\n\n".join([item for item in search_results])
                prompt_for_llm = f"Please answer the user's question based on the following context. If the context is not relevant, please answer based on your own knowledge.\n\nContext:\n{context}\n\nQuestion:\n{user_text}"
                history_for_llm[-1] = ("user", prompt_for_llm)
                print(f"[LLMChat] RAG context added to prompt.")

        avatar_path = os.path.join(os.path.dirname(__file__), "a_qwen_avatar.png")
        self.llm_bubble = LLMChatBubble("", avatar_path=avatar_path)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, self.llm_bubble)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())

        self.worker = LLMStreamWorker(self.llm_client, history_for_llm)
        self.worker.update.connect(self._on_llm_update) # type: ignore
        self.worker.finished.connect(self._on_llm_finish) # type: ignore
        self.worker.error.connect(self._on_llm_error) # type: ignore
        self.worker.start()

    def _on_llm_update(self, text: str) -> None:
        if hasattr(self, 'llm_bubble'):
            self.llm_bubble.setText(text)
        self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum())
        QApplication.processEvents()

    def _on_llm_finish(self, text: str) -> None:
        self.history.append(("llm", text))
        self.llm_output = text


    def _on_llm_error(self, msg: str) -> None:
        if hasattr(self, 'llm_bubble'):
            self.llm_bubble.setText(msg)
        self.llm_output = msg

    def on_confirm(self) -> None:
        user_override_text = self.input_edit.toPlainText().strip()
        if user_override_text:
            self.llm_output = user_override_text
            if self.history and self.history[-1][0] == "llm":
                self.history[-1] = ("llm", self.llm_output)
            else:
                # This case handles when the user provides input to be the final
                # result without a preceding response from the LLM. This could be
                # because the LLM call failed, or the user is directly
                # providing the response. We append it to the history as the
                # LLM's turn.
                self.history.append(("llm", self.llm_output))

        duration = rospy.Duration(0)
        if hasattr(self, 'llm_start_time'):
            duration = rospy.Time.now() - self.llm_start_time
        self.save_log(self.history, duration.to_sec())
        if self._signal_obj and self._request_id:
            getattr(self._signal_obj.chat_result, 'emit')(self._request_id, self.llm_output)  # type: ignore
        if self._event:
            self._event.set()
        self.accept()

    def save_log(self, history: List[Tuple[str, str]], duration: float = None) -> None:    
        if "rag" in history[0][1]:
            filename = "llm_subtask_generation"
        else:
            filename = "llm_context_analysis"
        log = {
            "filename": filename,
            "history": history,
            "duration": duration,
            "interaction_count": len(history)/2,
        }
        self.record_jsonl_pub.publish(json.dumps(log, ensure_ascii=False))

class LLMChatApp(QApplication):
    def __init__(self, sys_argv: List[str], signal_obj: LLMChatSignal, llm_client: Any = None, log_dir: Optional[str] = None, rag_kb: Optional[RAGKnowledgeBase] = None) -> None:
        super().__init__(sys_argv)
        self.setQuitOnLastWindowClosed(False)
        self.signal_obj = signal_obj
        self._events = {}  # request_id: Event
        self._results = {}  # request_id: llm_output
        self.llm_client = llm_client
        self.log_dir = log_dir
        self.rag_kb = rag_kb
        self.signal_obj.show_chat.connect(self.show_chat_dialog) # type: ignore
        self.signal_obj.chat_result.connect(self.on_chat_result) # type: ignore

    def show_chat_dialog(self, prompt: str, request_id: str) -> None:
        dialog = LLMChatDialog(llm_client=self.llm_client, log_dir=self.log_dir, rag_kb=self.rag_kb)
        dialog.set_signal(self.signal_obj)
        event = self._events[request_id]
        dialog.set_event(event)
        dialog.set_request_id(request_id)
        dialog.set_prompt(prompt)
        dialog.exec_()

    def on_chat_result(self, request_id: str, llm_output: str) -> None:
        self._results[request_id] = llm_output
        if request_id in self._events:
            self._events[request_id].set()

class LLMChatServer:
    def __init__(self, qt_app: 'LLMChatApp', signal_obj: LLMChatSignal) -> None:
        self.qt_app = qt_app
        self.signal_obj = signal_obj
        self.name = str(rospy.get_param("~name", ""))
        self.service = rospy.Service(f"{self.name}/gui/llm_chat", StringSrv, self.handle_request)

    def handle_request(self, req: StringSrvRequest) -> StringSrvResponse:
        req_data = json.loads(req.data)
        prompt = req_data.get("prompt", "")
        prompt = json.dumps(prompt, ensure_ascii=False)
        request_id = str(uuid.uuid4())
        event = Event()
        self.qt_app._events[request_id] = event
        self.signal_obj.show_chat.emit(prompt, request_id) # type: ignore
        event.wait()
        llm_output = self.qt_app._results.get(request_id, "")
        del self.qt_app._events[request_id]
        del self.qt_app._results[request_id]
        return StringSrvResponse(True, llm_output)

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    rospy.init_node("gui_llm_server", anonymous=True)
    signal_obj = LLMChatSignal()
    api_key = str(rospy.get_param("~api_key", "ollama"))
    model = str(rospy.get_param("~model", "qwen3:30b-a3b"))
    api_base = str(rospy.get_param("~api_base", "http://localhost:11434/v1"))
    config_path = str(rospy.get_param("~config", ""))
    log_dir = rospy.get_param("~log_dir", None) # Deprecated
    if log_dir is not None:
        log_dir = str(log_dir)

    rag_kb = None
    knowledge_base_path = rospy.get_param("~knowledge_base_path", None)
    if knowledge_base_path and os.path.exists(str(knowledge_base_path)):
        print(f"[LLMChat] Loading knowledge base from: {knowledge_base_path}")
        rag_kb = RAGKnowledgeBase(knowledge_file_path=str(knowledge_base_path))
    else:
        print(f"[LLMChat] No knowledge base path provided or file not found.")

    llm_client = None
    if config_path:
        from config_llm_server import ConfigLLMClient
        if not config_path or not os.path.exists(config_path):
            raise RuntimeError("Runtime Error: Invalid LLM config file!")
        llm_client = ConfigLLMClient(config_path)
    else:
        llm_client = OpenAILLMClient(api_key, api_base, model)

        try:
            print(f"[LLMChat] Testing LLM connection with model: {model} at {api_base}...")
            test_history = [("user", "Hi")]
            response_generator = llm_client.stream_chat(test_history)
            test_response = ""
            for chunk in response_generator:
                test_response += chunk
            if test_response:
                print(f"[LLMChat] LLM test successful.")
            else:
                print(f"[LLMChat] LLM test failed: empty response.")
        except Exception as e:
            print(f"[LLMChat] LLM test failed: {e}")

    qt_app = LLMChatApp(sys.argv, signal_obj, llm_client=llm_client, log_dir=log_dir, rag_kb=rag_kb)
    server = LLMChatServer(qt_app, signal_obj)
    from PyQt5.QtCore import QTimer
    def check_ros_shutdown():
        if rospy.is_shutdown():
            qt_app.quit()
    timer = QTimer()
    timer.timeout.connect(check_ros_shutdown) # type: ignore
    timer.start(200)
    sys.exit(qt_app.exec_())
