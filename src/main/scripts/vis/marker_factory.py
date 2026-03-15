from visualization_msgs.msg import Marker, MarkerArray
import rospy
from typing import Dict, List, Tuple
from matplotlib.colors import to_rgb
from geometry_msgs.msg import Pose, Point


class MarkerFactory:
    @staticmethod
    def get_model_marker(name, model_path, color: str) -> Marker:
        marker = Marker()
        marker.id = 0
        marker.ns = name
        marker.header.stamp = rospy.Time.now()
        marker.header.frame_id = "world"
        marker.type = Marker.MESH_RESOURCE
        marker.action = Marker.ADD
        marker.scale.x = 1 
        marker.scale.y = 1
        marker.scale.z = 1
        marker.pose.orientation.w = 1.0
        marker.pose.position.x = 0
        marker.pose.position.y = 0
        marker.pose.position.z = 0
        marker.color.a = 1.0
        r, g, b = to_rgb(color)
        marker.color.r = r
        marker.color.g = g
        marker.color.b = b
        marker.mesh_use_embedded_materials = True
        marker.mesh_resource = model_path
        return marker

    @staticmethod
    def gen_fov(name, dist, width, hight, pose: Pose) -> Marker:
        marker = Marker()
        marker.id = 0
        marker.ns = f"{name}_fov"
        marker.header.stamp = rospy.Time.now()
        marker.header.frame_id = "world"
        marker.type = Marker.LINE_LIST
        marker.action = Marker.ADD
        marker.scale.x = 0.05
        marker.pose = pose
        marker.color.a = 1.0
        marker.color.r = 1
        marker.color.g = 0
        marker.color.b = 0

        half_width = width / 2
        half_height = hight / 2
        points = [
            (0, 0, 0),
            (dist, -half_width, -half_height),
            (0, 0, 0),
            (dist, half_width, -half_height),
            (0, 0, 0),
            (dist, half_width, half_height),
            (0, 0, 0),
            (dist, -half_width, half_height),
            (dist, -half_width, -half_height),
            (dist, half_width, -half_height),
            (dist, half_width, -half_height),
            (dist, half_width, half_height),
            (dist, half_width, half_height),
            (dist, -half_width, half_height),
            (dist, -half_width, half_height),
            (dist, -half_width, -half_height)
        ]
        marker.points = []
        for point in points:
            p = Point()
            p.x, p.y, p.z = point
            marker.points.append(p)
        return marker