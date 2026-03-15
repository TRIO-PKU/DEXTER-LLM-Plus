# Simple Robot Simulator

A very simple robot simulator that takes `geometry_msgs/PoseStamped` waypoints and outputs `nav_msgs/Odometry` information.

## Overview

This package provides a lightweight simulator for testing and development purposes. It subscribes to a topic for waypoints and publishes the robot's position and orientation as odometry messages. This is useful for scenarios where you need a simple simulated robot to test algorithms like path planning or control without the overhead of a full-fledged simulator like Gazebo.