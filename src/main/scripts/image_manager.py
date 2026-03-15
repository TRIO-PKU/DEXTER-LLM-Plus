#! /usr/bin/env python3
import rospy
from dataclasses import dataclass
from typing import Dict, Tuple, List, Literal, Optional, cast

from main.srv import ImageSrv, ImageSrvRequest, ImageSrvResponse
from visualization_msgs.msg import Marker
from sensor_msgs.msg import Image
import os
import cv2
from cv_bridge import CvBridge
from threading import Lock
import json
from std_msgs.msg import String


@dataclass
class EnvImage:
    name: str
    pos: Tuple[float, float, float]
    visibility: Literal["coarse", "fine", "manual"]
    data: Image
    state: Literal["init", "detected"]

    def __repr__(self) -> str:
        return f"EnvImage(name='{self.name}', pos='{self.pos}', visibility='{self.visibility}', state='{self.state}')"


class ImageManager:
    def __init__(self):
        self.take_photo_server = rospy.Service(
            "/take_photo", ImageSrv, self._take_photo_cb
        )
        self.photo_vis = rospy.Publisher("/photo_vis", Image, queue_size=10)
        self.photo_location_vis = rospy.Publisher(
            "/extended_vis", Marker, queue_size=10
        )
        self.start_time = rospy.get_time()

        # Config
        config_path = str(rospy.get_param("/config_path", "src/main/launch/config.json"))
        with open(config_path, "r") as f:
            self.config: Dict = json.load(f)

        self.images: List[EnvImage] = []
        self._load_images(str(rospy.get_param("~image_dir", "src/main/images/")))
        self.lock = Lock()
        self.manual_discover_sub = rospy.Subscriber(
            "/md", String, self._manual_discover_cb
        )

    def _load_images(self, image_dir: str) -> None:
        bridge = CvBridge()
        feature_instances: Dict[str, Dict] = self.config.get("feature_instances", {})
        for name, info in feature_instances.items():
            pos = cast(Tuple, info.get("position"))
            vis = cast(Literal["coarse", "fine", "manual"], info.get("visibility"))
            img_fname = f"{name}.jpg"
            img_path = os.path.join(image_dir, img_fname)
            if os.path.exists(img_path):
                cv_img = cv2.imread(img_path)
                if cv_img is not None:
                    ros_img = bridge.cv2_to_imgmsg(cv_img, encoding="bgr8")
                else:
                    rospy.logwarn(f"Failed to load image '{img_path}'")
                    ros_img = Image()
            else:
                rospy.logwarn(f"Image file '{img_path}' not found for feature '{name}'")
                ros_img = Image()

            env_image = EnvImage(
                name=name, pos=pos, visibility=vis, data=ros_img, state="init"
            )
            self.images.append(env_image)
            print(env_image)

    def _take_photo_cb(self, req: ImageSrvRequest) -> ImageSrvResponse:
        """
        format: x_min,y_min,z_min,x_max,y_max,z_max,coarse/fine
        """
        x_min, y_min, z_min, x_max, y_max, z_max, visibility = req.message.split(",")
        if visibility not in ("coarse", "fine", "manual"):
            raise ValueError(f"Invalid visibility: {visibility}")

        env_image = self._get_photo(
            float(x_min),
            float(y_min),
            float(z_min),
            float(x_max),
            float(y_max),
            float(z_max),
            visibility,
        )
        if env_image is None:
            return ImageSrvResponse(False, Image(), "")
        else:
            self.photo_vis.publish(env_image.data)
            marker = self._gen_photo_location_marker(env_image)
            self.photo_location_vis.publish(marker)
            message = f"{env_image.pos[0]},{env_image.pos[1]},{env_image.pos[2]},{env_image.name}"
            return ImageSrvResponse(True, env_image.data, message)

    def _get_photo(
        self,
        x_min: float,
        y_min: float,
        z_min: float,
        x_max: float,
        y_max: float,
        z_max: float,
        visibility: Literal["coarse", "fine", "manual"],
    ) -> Optional[EnvImage]:
        """find the first undetected image within the requested box and visibility
        if visibility==manual, return the first manual feature instance with discovered_time < now
        """
        if visibility == "manual":
            now = rospy.get_time() - self.start_time
            feature_instances = self.config.get("feature_instances", {})
            for name, info in feature_instances.items():
                if info.get("visibility") == "manual":
                    discovered_time = info.get("discovered_time", float("inf"))
                    if discovered_time < now:
                        for img in self.images:
                            if img.name == name and img.state == "init" and img.visibility == "manual":
                                img.state = "detected"
                                return img
            return None

        with self.lock:
            candidates = [
                img
                for img in self.images
                if img.visibility == visibility
                and img.state == "init"
                and x_min <= img.pos[0] <= x_max
                and y_min <= img.pos[1] <= y_max
                and z_min <= img.pos[2] <= z_max
            ]
        if not candidates:
            return None
        else:
            return_img = candidates[0]
            return_img.state = "detected"
            return return_img

    def _gen_photo_location_marker(self, env_image: EnvImage) -> Marker:
        marker = Marker()
        marker.header.frame_id = "world"
        marker.header.stamp = rospy.Time.now()
        marker.ns = "photo_location"
        marker.id = 0
        marker.type = Marker.SPHERE
        marker.action = Marker.ADD
        marker.pose.position.x = env_image.pos[0]
        marker.pose.position.y = env_image.pos[1]
        marker.pose.position.z = env_image.pos[2]
        marker.scale.x = 0.5
        marker.scale.y = 0.5
        marker.scale.z = 0.5
        marker.color.r = 1.0
        marker.color.g = 0.0
        marker.color.b = 0.0
        marker.color.a = 1.0
        return marker

    def _manual_discover_cb(self, msg: String):
        feature_name = msg.data.strip()
        feature_instances = self.config.get("feature_instances", {})
        if feature_name in feature_instances:
            feature_instances[feature_name]["discovered_time"] = 0.0
            rospy.loginfo(f"Feature '{feature_name}' discovered_time set to 0.")
        else:
            rospy.logwarn(f"Feature '{feature_name}' not found in config.")


if __name__ == "__main__":
    rospy.init_node("image_manager", anonymous=True)
    ImageManager()
    rospy.spin()
