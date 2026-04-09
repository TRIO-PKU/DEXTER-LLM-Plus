# Melding LLM and temporal logic for reliable human-swarm collaboration in complex environments 🚀🤖

![Cover](docs/static/images/video_cover.jpg)
<p align="center">
    <img width="110px" height="21px" src="https://img.shields.io/badge/Ubuntu-20.04-orange?logo=Ubuntu&Ubuntu-20.04" alt="ubuntu" />
    <img width="110px" height="21px" src="https://img.shields.io/badge/ROS-noetic-green?logo=ROS&ROS=noetic" alt="ROS" />
    <img width="110px" height="21px" src="https://img.shields.io/badge/Python-3.8-blue?logo=Python&Python=3.8" alt="Python" />
    <img width="110px" height="21px" src="https://img.shields.io/badge/Gurobi-11.0.3-red?logo=Gurobi&Gurobi=11.0.3" alt="Gurobi" />
    <img width="110px" height="21px" src="https://img.shields.io/badge/License-GPLv3-yellow?logo=Open%20Source%20Initiative" alt="License" />
</p>

## Abstract

Robot swarms promise scalable assistance in complex and hazardous environments.
Task planning lies at the core of human–swarm collaboration, translating the operator’s intent into
coordinated swarm actions and helping determine when validation or intervention is required
during execution. In long-horizon missions under dynamic scenarios, however, reliable task
planning becomes difficult to maintain: emerging events and changing conditions demand
continual adaptation, and sustained operator oversight imposes substantial cognitive burden.
Existing LLM-based planning tools can support plan generation, yet they remain susceptible to
invalid task orderings and infeasible robot actions, resulting in frequent manual adjustment. Here
we introduce a neuro-symbolic framework for long-horizon human-swarm collaboration that
tightly couples verifiable task planning with context-grounded LLM reasoning. We formalize
mission goals and operational rules as temporal logic formulas and admissible task orderings as
task automata. Conditioned on these formal constraints and live perceptual context, LLMs
generate executable subtask sequences that satisfy mission rules and remain grounded in the
current scene. An uncertainty-aware scheduler then assigns subtasks across the heterogeneous
swarm to maximize parallelisms while remaining resilient to disruptions. An event-triggered
interaction protocol further limits operator involvement to sparse, high-level confirmation and
guidance. In large-scale simulations with more than 40 robots executing 41 tasks with 155
subtasks in 11-minute missions, our system improves task success rates by 26% and increases
completed tasks by 132% relative to state-of-the-art baselines. At the same time, it reduces
operator interventions by 77% and lowers physiological stress by 49%. Deployment on a
heterogeneous robotic fleet yields similar results while remaining robust to hardware-specific
actuation and communication uncertainties. Together, these results support a formal and scalable
paradigm for reliable and low-overhead human–swarm collaboration in dynamic environments.

## Installation

Pre-Requirements

- Ubuntu 20.04
- ROS Noetic Desktop
- Gurobi Optimizer (11.3) (Optional)

Clone this repo

```bash
git clone https://github.com/TCXM/DEXTER-LLM-Plus-dev.git --recursive
```

ROS Packages

```bash
sudo apt install ros-noetic-vision-msgs
```

Python packages

```bash
pip3 install -r requirements.txt
```

Online Resources:
1. Download yolov7 weights to ```src/main/yolo```
2. Download images to ```src/main/images```
3. Download robot models to ```src/main/models```
4. Download maps to ```src/main/maps/real_factory_with_warehouse``` 

```bash
pip install gdown
gdown --folder https://drive.google.com/drive/folders/1LWn4c0Rq8vLXU6id67dR_m4aibuWsa7n --output src/main/yolo
gdown --folder https://drive.google.com/drive/folders/1OBv168ciQgxPTAMIZAYhfNQRBkFl--dO --output src/main/images
gdown --folder https://drive.google.com/drive/folders/1Zt9-Sh8yw-wjQ1nHR6hvVyrjyVy-TdXw --output src/main/models
gdown --folder https://drive.google.com/drive/folders/1hfNx5MJ9JXYOrRsRYWC6_uERziUY6fAQ --output src/main/maps/real_factory_with_warehouse
```

Make this workspace:

```bash
catkin_make
```

## LLM Setup

A local instance of Ollama is used by default. To use a custom LLM, you must update the endpoint and credentials in the launch file of each edge node, such as [src/main/launch/gui_edge_1.launch](src/main/launch/gui_edge_1.launch) and [src/main/launch/gui_edge_exp.launch](src/main/launch/gui_edge_exp.launch).

Update the following LLM parameters accordingly:
```xml
<param name="api_key" value=""/>
<param name="model" value=""/>
<param name="api_base" value=""/>
```

## Run HCI Experiment

Terminal 1:
```bash
source devel/setup.bash && roslaunch main gui_edge_exp_and_1.launch
```

Terminal 2:
```bash
source devel/setup.bash && roslaunch main sim.launch
```

Terminal 3:
```bash
source devel/setup.bash && roslaunch main test.launch
```

Experimental data will be recorded at ```src/simple_recorder/record```

## Contact

- [Junfeng Chen](mailto:chenjunfeng@stu.pku.edu.cn)
- [Yuxiao Zhu](mailto:yuxiao.zhu@dukekunshan.edu.cn)
- [Meng Guo](mailto:meng.guo@pku.edu.cn)
