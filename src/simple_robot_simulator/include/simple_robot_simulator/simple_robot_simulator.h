#ifndef SIMPLE_ROBOT_SIMULATOR_H
#define SIMPLE_ROBOT_SIMULATOR_H

#include <ros/ros.h>
#include <geometry_msgs/PoseStamped.h>
#include <nav_msgs/Odometry.h>

class SimpleRobotSimulator {
public:
    SimpleRobotSimulator(ros::NodeHandle& nh);
    void goalCallback(const geometry_msgs::PoseStamped::ConstPtr& msg);
    void run();

private:
    ros::NodeHandle nh_;
    ros::Subscriber goal_sub_;
    ros::Publisher odom_pub_;

    geometry_msgs::PoseStamped current_goal_;
    nav_msgs::Odometry current_odom_;
    double speed_;
};

#endif // SIMPLE_ROBOT_SIMULATOR_H
