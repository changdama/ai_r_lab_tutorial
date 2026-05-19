#!/usr/bin/env python3
import rclpy
from rclpy.node import Node

from moveit_msgs.msg import DisplayTrajectory
from sensor_msgs.msg import JointState

class Relay(Node):
    def __init__(self):
        super().__init__('relay_display_traj_to_jointstate')

        self.sub = self.create_subscription(
            DisplayTrajectory,
            '/display_planned_path',
            self.cb,
            10
        )
        self.pub = self.create_publisher(JointState, '/isaac_joint_targets', 10)

        self.get_logger().info('Relaying /display_planned_path -> /isaac_joint_targets (JointState)')

    def cb(self, msg: DisplayTrajectory):
        if not msg.trajectory:
            return

        jt = msg.trajectory[-1].joint_trajectory
        if not jt.joint_names or not jt.points:
            return

        pt = jt.points[-1]  
        if not pt.positions:
            return

        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = list(jt.joint_names)
        js.position = list(pt.positions)

        self.pub.publish(js)

def main():
    rclpy.init()
    node = Relay()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()

