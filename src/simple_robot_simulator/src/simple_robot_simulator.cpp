#include "simple_robot_simulator/simple_robot_simulator.h"
#include <tf/transform_datatypes.h>

SimpleRobotSimulator::SimpleRobotSimulator(ros::NodeHandle& nh) : nh_(nh) {
    goal_sub_ = nh_.subscribe("/move_base_simple/goal", 1, &SimpleRobotSimulator::goalCallback, this);
    odom_pub_ = nh_.advertise<nav_msgs::Odometry>("/odom", 1);

    nh_.param("speed", speed_, 0.5); // default speed 0.5 m/s

    double init_x, init_y, init_z;
    nh_.param("init_x", init_x, 0.0);
    nh_.param("init_y", init_y, 0.0);
    nh_.param("init_z", init_z, 0.0);

    current_odom_.header.frame_id = "world";
    current_odom_.pose.pose.position.x = init_x;
    current_odom_.pose.pose.position.y = init_y;
    current_odom_.pose.pose.position.z = init_z;
    current_odom_.pose.pose.orientation.w = 1.0;
}

void SimpleRobotSimulator::goalCallback(const geometry_msgs::PoseStamped::ConstPtr& msg) {
    current_goal_ = *msg;
    ROS_INFO("New goal received.");
}

void SimpleRobotSimulator::run() {
    ros::Rate rate(10);
    while (ros::ok()) {
        if (!current_goal_.header.frame_id.empty()) {
            double dx = current_goal_.pose.position.x - current_odom_.pose.pose.position.x;
            double dy = current_goal_.pose.position.y - current_odom_.pose.pose.position.y;
            double dz = current_goal_.pose.position.z - current_odom_.pose.pose.position.z;
            double distance = std::sqrt(dx*dx + dy*dy + dz*dz);

            if (distance > 0.1) {
                double move_step = speed_ / 10.0; // Move per cycle
                current_odom_.pose.pose.position.x += move_step * dx / distance;
                current_odom_.pose.pose.position.y += move_step * dy / distance;
                current_odom_.pose.pose.position.z += move_step * dz / distance;

                // Update orientation to look at the goal
                double yaw = atan2(dy, dx);
                current_odom_.pose.pose.orientation = tf::createQuaternionMsgFromYaw(yaw);
            }
        }

        current_odom_.header.stamp = ros::Time::now();
        odom_pub_.publish(current_odom_);

        ros::spinOnce();
        rate.sleep();
    }
}
