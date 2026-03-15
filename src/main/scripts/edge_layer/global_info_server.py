from sensor_msgs.msg._Image import Image
from typing import Tuple, cast
import rospy
from vision_msgs.msg import Detection2DArray, Detection2D, BoundingBox2D


class GlobalInfoServer:
    def __init__(self, name):
        self.labels = []
        self.load_labels()

        self.yolo_detect_pub = rospy.Publisher(
            f"/{name}/original_image", Image, queue_size=10
        )
        self.yolo_detect_sub = rospy.Subscriber(
            f"/{name}/detect_result", Detection2DArray, self._yolo_detect_callback
        )
        self.yolo_detect_vis_sub = rospy.Subscriber(
            f"/{name}/detect_result/visualization",
            Image,
            self._yolo_detect_vis_callback,
        )
        self.detection_result = None
        self.detection_result_vis = None

    def load_labels(self):
        labels_file_path = str(rospy.get_param("/labels_file_path"))
        try:
            with open(labels_file_path, "r") as file:
                self.labels = [line.strip() for line in file if line.strip()]
            rospy.loginfo(f"Loaded {len(self.labels)} labels from {labels_file_path}")
        except Exception as e:
            rospy.logerr(f"Failed to load labels from {labels_file_path}: {e}")

    def get_context(self, image: Image, name: str) -> Tuple[Image, str]:
        if image.data is None or len(image.data) == 0:
            rospy.logwarn("Received an empty image.")
            return image, name.split(".")[0]
        self.yolo_detect_pub.publish(image)
        timeout = rospy.Time.now() + rospy.Duration(1)
        while (
            self.detection_result_vis is None or self.detection_result is None
        ) and rospy.Time.now() < timeout:
            rospy.logwarn("Waiting for detection results...")
            rospy.sleep(0.2)
        if self.detection_result_vis is None or self.detection_result is None:
            rospy.logwarn("Detection results not received within timeout.")
            return image, name.split(".")[0]
        detection_result = self.detection_result
        detection_result_vis = self.detection_result_vis
        self.detection_result = None
        self.detection_result_vis = None

        return detection_result_vis, detection_result

    def _yolo_detect_callback(self, msg: Detection2DArray):
        if not msg.detections:
            rospy.logwarn("No detections found.")
            self.detection_result = "Unknown"
            return

        # Process the first detection for simplicity
        detection: Detection2D = msg.detections[0]
        if detection.results:
            detection.results.sort(key=lambda r: r.score, reverse=True)
            highest_score_result = detection.results[0]
            rospy.loginfo(f"Highest score result: {highest_score_result}")
            self.detection_result = str(self.labels[highest_score_result.id])

    def _yolo_detect_vis_callback(self, msg: Image):
        self.detection_result_vis = msg
