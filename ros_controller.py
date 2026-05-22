#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry, OccupancyGrid
import threading

class RobotController:
    """Bunker Pro 自动导航通讯控制器 V4.0"""
    def __init__(self):
        rospy.init_node('bunker_nav_controller', anonymous=True, disable_signals=True)
        
        self.cmd_pub = rospy.Publisher('/smoother_cmd_vel', Twist, queue_size=10)
        rospy.Subscriber('/odom', Odometry, self.odom_callback)
        rospy.Subscriber('/map', OccupancyGrid, self.map_callback)

        self._lock = threading.Lock()
        self.current_linear = 0.0
        self.current_angular = 0.0
        self.map_grid = None
        self.map_info = None
        self.robot_x = 0.0
        self.robot_y = 0.0

    def odom_callback(self, msg):
        with self._lock:
            self.current_linear = msg.twist.twist.linear.x
            self.current_angular = msg.twist.twist.angular.z
            self.robot_x = msg.pose.pose.position.x
            self.robot_y = msg.pose.pose.position.y

    def map_callback(self, msg):
        with self._lock:
            self.map_grid = msg
            self.map_info = msg.info

    def send_speed(self, linear_x, angular_z=0.0):
        twist_msg = Twist()
        twist_msg.linear.x = linear_x
        twist_msg.angular.z = angular_z
        self.cmd_pub.publish(twist_msg)

    def get_status_data(self):
        with self._lock:
            return {
                'linear': self.current_linear,
                'angular': self.current_angular,
                'x': self.robot_x,
                'y': self.robot_y
            }

    def get_map_data(self):
        with self._lock:
            if self.map_grid is not None:
                return self.map_grid, self.map_info
            return None, None