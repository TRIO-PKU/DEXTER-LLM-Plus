import rospy
from visualization_msgs.msg import Marker
from matplotlib.colors import to_rgb
import math
import random
import tf.transformations

class AnimationController:
    def __init__(
        self,
        manager,
        duration,
        start_pos,
        end_pos,
        marker_pub,
        shape="sphere",
        color=(1, 0, 0),
        particle_count=30,
    ):
        self.manager = manager
        self.duration = duration
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.marker_pub = marker_pub
        self.shape = shape
        self.color = color
        self.particle_count = particle_count
        self.start_time = rospy.Time.now()
        self.timer = rospy.Timer(rospy.Duration.from_sec(0.05), self._timer_cb)
        self.finished = False
        self.particles = self._init_particles()
        self.cb = None

    def _init_particles(self):
        particles = []
        # 获取机器人正前方方向
        if self.manager.cur_odom is not None:
            q = self.manager.cur_odom.pose.pose.orientation
            quaternion = [q.x, q.y, q.z, q.w]
            _, _, yaw = tf.transformations.euler_from_quaternion(quaternion)
            main_dir = [math.cos(yaw), math.sin(yaw), 0]
            base_pos = self.manager.cur_odom.pose.pose.position
            start_pos = [
                base_pos.x + 0.5 * main_dir[0],
                base_pos.y + 0.5 * main_dir[1],
                base_pos.z + 0.5,
            ]
            self.start_pos = start_pos
        else:
            main_dir = [1, 0, 0]
            self.start_pos = [
                self.start_pos[0],
                self.start_pos[1],
                self.start_pos[2] + 0.5,
            ]
        norm = (
            math.sqrt(
                (self.end_pos[0] - self.start_pos[0]) ** 2
                + (self.end_pos[1] - self.start_pos[1]) ** 2
                + (self.end_pos[2] - self.start_pos[2]) ** 2
            )
            + 1e-6
        )
        max_range = max(norm * 1.8, 3.0)
        cone_angle = math.radians(60)
        for i in range(self.particle_count):
            theta = random.uniform(-cone_angle / 2, cone_angle / 2)
            phi = random.uniform(-cone_angle / 3, cone_angle / 3)
            dir_x = math.cos(theta) * main_dir[0] - math.sin(theta) * main_dir[1]
            dir_y = math.sin(theta) * main_dir[0] + math.cos(theta) * main_dir[1]
            dir_z = main_dir[2] + math.tan(phi)
            dir_norm = math.sqrt(dir_x**2 + dir_y**2 + dir_z**2) + 1e-6
            dir_vec = [dir_x / dir_norm, dir_y / dir_norm, dir_z / dir_norm]
            max_dist = max_range + random.uniform(-0.3, 0.3)
            start_t = random.uniform(0, 0.2)
            life = random.uniform(0.35, 0.5)
            particles.append(
                {
                    "start_t": start_t,
                    "life": life,
                    "dir_vec": dir_vec,
                    "max_dist": max_dist,
                }
            )
        return particles

    def _timer_cb(self, event):
        elapsed = (rospy.Time.now() - self.start_time).to_sec()
        progress = min(elapsed / self.duration, 1.0)
        any_alive = False
        for i, p in enumerate(self.particles):
            t0 = p["start_t"]
            t1 = p["start_t"] + p["life"]
            if progress < t0 or progress > t1:
                continue
            local_p = (progress - t0) / max(p["life"], 1e-5)
            dist = p["max_dist"] * local_p
            x = self.start_pos[0] + p["dir_vec"][0] * dist
            y = self.start_pos[1] + p["dir_vec"][1] * dist
            z = self.start_pos[2] + p["dir_vec"][2] * dist
            alpha = 0.8 * (1 - local_p)
            marker = Marker()
            marker.header.frame_id = "world"
            marker.header.stamp = rospy.Time.now()
            marker.ns = "anim_particles"
            marker.id = i
            marker.type = Marker.SPHERE if self.shape == "sphere" else Marker.CUBE
            marker.action = Marker.ADD
            marker.pose.position.x = x
            marker.pose.position.y = y
            marker.pose.position.z = z
            marker.pose.orientation.w = 1
            marker.scale.x = 0.08
            marker.scale.y = 0.08
            marker.scale.z = 0.08
            marker.color.r = self.color[0]
            marker.color.g = self.color[1]
            marker.color.b = self.color[2]
            marker.color.a = alpha
            marker.lifetime = rospy.Duration.from_sec(0.2)
            self.marker_pub.publish(marker)
            any_alive = True
        if not any_alive or progress >= 1.0:
            self.timer.shutdown()
            self.finished = True
            if self.cb:
                self.cb()

    def set_done_callback(self, cb):
        self.cb = cb

class ProgressBarController:
    def __init__(self, manager, name, duration, marker_pub, bar_length=0.8, bar_height=0.7):
        self.manager = manager
        self.duration = duration
        self.marker_pub = marker_pub
        self.bar_length = bar_length
        self.bar_height = bar_height
        self.start_time = rospy.Time.now()
        self.timer = rospy.Timer(rospy.Duration.from_sec(0.05), self._timer_cb)
        self.finished = False
        self.ns = f"{name}_progress_bar"
        self.green = to_rgb("#00ff00")
        self.gray = to_rgb("#cccccc")

    def _timer_cb(self, event):
        elapsed = (rospy.Time.now() - self.start_time).to_sec()
        progress = min(elapsed / self.duration, 1.0)
        if self.manager.cur_odom is None:
            return
        pos = self.manager.cur_odom.pose.pose.position
        # 进度条中心在机器人头顶 bar_height 米
        center = [pos.x, pos.y, pos.z + self.bar_height]
        half = self.bar_length / 2
        # 绿色部分
        green_marker = Marker()
        green_marker.header.frame_id = "world"
        green_marker.header.stamp = rospy.Time.now()
        green_marker.ns = self.ns
        green_marker.id = 0
        green_marker.type = Marker.LINE_STRIP
        green_marker.action = Marker.ADD
        green_marker.scale.x = 0.06
        green_marker.color.r = self.green[0]
        green_marker.color.g = self.green[1]
        green_marker.color.b = self.green[2]
        green_marker.color.a = 1.0
        green_marker.lifetime = rospy.Duration.from_sec(0.1)
        # 绿色部分长度随进度变化
        green_marker.points = []
        green_marker.points.append(self._make_point(center, -half, 0))
        green_marker.points.append(self._make_point(center, -half + self.bar_length * progress, 0))
        # 灰色部分
        gray_marker = Marker()
        gray_marker.header.frame_id = "world"
        gray_marker.header.stamp = rospy.Time.now()
        gray_marker.ns = self.ns
        gray_marker.id = 1
        gray_marker.type = Marker.LINE_STRIP
        gray_marker.action = Marker.ADD
        gray_marker.scale.x = 0.06
        gray_marker.color.r = self.gray[0]
        gray_marker.color.g = self.gray[1]
        gray_marker.color.b = self.gray[2]
        gray_marker.color.a = 1.0
        gray_marker.lifetime = rospy.Duration.from_sec(0.1)
        gray_marker.points = []
        gray_marker.points.append(self._make_point(center, -half + self.bar_length * progress, 0))
        gray_marker.points.append(self._make_point(center, half, 0))
        self.marker_pub.publish(green_marker)
        self.marker_pub.publish(gray_marker)
        if progress >= 1.0:
            self.timer.shutdown()
            self.finished = True

    def _make_point(self, center, offset_x, offset_y):
        from geometry_msgs.msg import Point
        p = Point()
        p.x = center[0] + offset_x
        p.y = center[1] + offset_y
        p.z = center[2]
        return p
