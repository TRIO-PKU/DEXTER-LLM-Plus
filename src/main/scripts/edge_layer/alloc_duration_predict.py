#! /usr/bin/env python3

from typing import Dict, List
import sys
sys.path.insert(0, sys.path[0] + "/../")
from classes import SubtaskInstance, EndData


def alloc_map_duration_predict(
        alloc_map: Dict[str, List[SubtaskInstance]],
        end_datas: Dict[str, EndData],
    ) -> float:
    total_time = 0.0
    for end_name, subtasks in alloc_map.items():
        end_data = end_datas[end_name]
        cur_pos = end_data.cur_pos
        time = 0.0
        for subtask in subtasks:
            # 先去resource点（如果有），再去target点
            pos_seq = []
            if subtask.res_pos is not None:
                pos_seq.append(subtask.res_pos)
            if subtask.target_pos is not None:
                pos_seq.append(subtask.target_pos)
            for pos in pos_seq:
                if cur_pos is not None and pos is not None:
                    dist = ((cur_pos[0] - pos[0]) ** 2 + (cur_pos[1] - pos[1]) ** 2 + (cur_pos[2] - pos[2]) ** 2) ** 0.5
                    # 假设机器人速度为1单位/秒
                    time += dist / 1
                    cur_pos = pos
            # 加上子任务自身的duration
            if hasattr(subtask, "duration") and subtask.duration:
                time += float(subtask.duration)
        if time > total_time:
            total_time = time
    return total_time


if __name__ == "__main__":

    import rospy
    rospy.init_node("alloc_duration_predict")
    # Example usage
    alloc_map = {
        "end1": [SubtaskInstance("subtask1", res_pos=(1, 0, 0), target_pos=(1, 1, 0), duration=2),
                 SubtaskInstance("subtask1", res_pos=(0, 1, 0), target_pos=(0, 0, 0), duration=2)],
        "end2": [SubtaskInstance("subtask2", res_pos=(2, 2, 2), target_pos=(3, 3, 3), duration=3)]
    }
    end_datas = {
        "end1": EndData("end_1", 1, cur_pos=(0, 0, 0)),
        "end2": EndData("end_2", 2, cur_pos=(1, 1, 1))
    }
    print(alloc_map_duration_predict(alloc_map, end_datas))  # Output: total time