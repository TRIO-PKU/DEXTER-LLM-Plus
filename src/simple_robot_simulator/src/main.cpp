#include "simple_robot_simulator/simple_robot_simulator.h"

int main(int argc, char** argv) {
    ros::init(argc, argv, "simple_robot_simulator");
    ros::NodeHandle nh("~");
    SimpleRobotSimulator simulator(nh);
    simulator.run();
    return 0;
}
