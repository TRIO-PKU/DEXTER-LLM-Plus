#!/usr/bin/env python

import rospy
from visualization_msgs.msg import Marker
import sys

def show_map(publisher, map_path):
    marker = Marker()
    marker.id = 0
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
    marker.mesh_use_embedded_materials = True
    marker.mesh_resource = map_path
    for i in range(3):
        publisher.publish(marker)
        rospy.sleep(5)

if __name__=="__main__":
    rospy.init_node("map_vis")
    pub = rospy.Publisher("/map_vis", Marker, queue_size=10)
    show_map(pub, sys.argv[1])
    rospy.spin()