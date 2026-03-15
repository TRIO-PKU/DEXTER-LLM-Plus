from typing import List, Dict, Tuple, Union, cast, Optional
import rospy
import task_alloc_milp
from task_alloc_milp.srv import (
    TaskAllocSrv,
    TaskAllocSrvRequest,
    TaskAllocSrvResponse,
)
from task_alloc_dataclasses import (
    TA_Problem,
    TA_Solution,
    AtomicTask,
    Robot,
)
from task_alloc_solver import TaskAllocSolver
from classes import (
    EndData,
    EdgeData,
    SubtaskInstance,
    TaskInstance,
    SubtaskType,
    TaskType,
)


class MILPAdapter:
    def __init__(self, config: Dict):
        self.solver = TaskAllocSolver()
        self.client = rospy.ServiceProxy("/task_alloc_service", TaskAllocSrv)
        self.config = config

    def alloc_tasks(
        self,
        tasks: List[TaskInstance],
        edge_datas: Dict[str, EdgeData],
    ) -> List[TaskInstance]:
        return []

    def alloc_subtasks(
        self,
        subtasks: List[SubtaskInstance],
        end_datas: Dict[str, EndData],
    ) -> Tuple[Dict[str, List[SubtaskInstance]], float]:
        atomic_tasks = []
        robots = []
        task_dependencies = []
        task_simultaneity = []
        for subtask in subtasks:  
            at = AtomicTask(
                id=subtask.name,
                location=subtask.target_pos,
                required_skill=subtask.required_skill,
                duration=subtask.duration,
            )
            atomic_tasks.append(at)
            if subtask.dep_subtask_instances is not None:
                for dep in subtask.dep_subtask_instances:
                    task_dependencies.append((dep, subtask.name))
            if subtask.conjugate_subtask is not None:
                task_simultaneity.append((subtask.name, subtask.conjugate_subtask))

        for end_data in end_datas.values():
            skills = list(self.config['agent_types'][end_data.agent_type]['skills'])
            robot = Robot(
                id=end_data.name,
                skills=skills,
                free_pos=end_data.end_pos,
                free_time=0,
                speed=end_data.max_vel,
            )
            robots.append(robot)

        problem = TA_Problem(
            robots=robots,
            atomic_tasks=atomic_tasks,
            task_dependencies=task_dependencies,
            task_simultaneity=task_simultaneity,
            task_consistency=[],
            task_exclusivity=[],
        )

        print(f"Problem: {problem}")    
        self.client.wait_for_service(timeout=3)
        resp: TaskAllocSrvResponse = self.client.call(problem.to_json())
        solution = TA_Solution.from_json(resp.ta_solution_json)
        print(f"Solution: {solution}")

        if solution is None:
            raise ValueError("No solution found.")

        # 解析解
        allocated_subtasks: Dict[str, List[SubtaskInstance]] = {}
        for robot_name, meta_tasks in solution.robot_schedule.items():
            if robot_name not in allocated_subtasks:
                allocated_subtasks[str(robot_name)] = []
            last_mt: Optional[AtomicTask] = None
            for meta_task in meta_tasks:
                subtask = cast(
                    SubtaskInstance,
                    next((st for st in subtasks if st.name == meta_task.id), None),
                )
                subtask.allocated_end = str(robot_name)
                if last_mt is not None:
                    subtask.recommended_dep = str(last_mt.id)
                allocated_subtasks[str(robot_name)].append(subtask)
                last_mt = meta_task

        return allocated_subtasks, solution.T_max
