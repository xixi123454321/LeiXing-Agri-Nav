#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import numpy as np
import rospy
from geometry_msgs.msg import Twist, PoseStamped, PoseWithCovarianceStamped
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QFrame, QGridLayout)
from PyQt5.QtCore import QTimer, Qt, QRectF
from PyQt5.QtGui import QFont, QImage, QPixmap, QPainter, QColor, QPen

from ros_controller import RobotController

# 将一个可点击的 QLabel 封装出来
class ClickableMapCanvas(QLabel):
    def __init__(self, parent_gui):
        super().__init__()
        self.parent_gui = parent_gui
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #2e2e2e;")
        self.setMinimumSize(450, 450)

    # 捕获鼠标双击事件
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parent_gui.handle_map_click(event.pos().x(), event.pos().y())


class BunkerNav_GCS_V5(QWidget):
    def __init__(self):
        super().__init__()
        self.robot = RobotController()
        
        # 目标点发布器 (直接给 move_base 下达坐标)
        self.goal_pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=1)
        
        # 初始位置发布器 (用于一键精准定位)
        self.init_pose_pub = rospy.Publisher('/initialpose', PoseWithCovarianceStamped, queue_size=1)
        
        self.manual_override = False
        self.target_linear = 0.0
        self.target_angular = 0.0
        
        # 用于保存地图的尺寸数据，方便反算坐标
        self.map_info_cache = None
        self.scaled_pixmap_rect = None

        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.main_loop)
        self.timer.start(50)

    def init_ui(self):
        self.setWindowTitle('Bunker Pro V5.0 (UI 直接导航版)')
        self.resize(950, 650)
        main_layout = QHBoxLayout()

        # ==================== 左侧控制台 ====================
        left_panel = QVBoxLayout()
        title = QLabel("🤖 全息控制中心")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        left_panel.addWidget(title)

        self.lbl_real_speed = QLabel("当前速度: 0.00 m/s | 0.00 rad/s")
        self.lbl_real_speed.setStyleSheet("color: blue; font-weight: bold;")
        self.lbl_real_speed.setFont(QFont("Arial", 12))
        left_panel.addWidget(self.lbl_real_speed)

        self.lbl_nav_status = QLabel("⚠️ 地图尚未就绪 (请点击下方按钮初始化)")
        self.lbl_nav_status.setFont(QFont("Arial", 11))
        self.lbl_nav_status.setStyleSheet("color: orange; margin-top: 10px; margin-bottom: 5px;")
        left_panel.addWidget(self.lbl_nav_status)
        
        # 一键定位按钮
        self.btn_init_map = QPushButton("📍 一键系统初始化 (原点定位)")
        self.btn_init_map.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; font-size: 14px; padding: 10px;")
        self.btn_init_map.clicked.connect(self.reset_to_origin)
        left_panel.addWidget(self.btn_init_map)
        
        left_panel.addWidget(QFrame(frameShape=QFrame.HLine))

        lbl_joy = QLabel("🎮 强制人工接管 (按住操作)")
        lbl_joy.setFont(QFont("Arial", 12, QFont.Bold))
        left_panel.addWidget(lbl_joy)

        joy_layout = QGridLayout()
        btn_w = QPushButton("W 前进")
        btn_s = QPushButton("S 后退")
        btn_a = QPushButton("A 左转")
        btn_d = QPushButton("D 右转")
        self.btn_stop = QPushButton("🛑 紧急制动")
        self.btn_stop.setStyleSheet("background-color: #ff4d4d; color: white; font-weight: bold; font-size: 14px;")
        
        for btn in [btn_w, btn_s, btn_a, btn_d]:
            btn.setMinimumHeight(55)

        # 按压控制，松开刹车
        btn_w.pressed.connect(lambda: self.trigger_manual(0.2, 0.0))
        btn_s.pressed.connect(lambda: self.trigger_manual(-0.2, 0.0))
        btn_a.pressed.connect(lambda: self.trigger_manual(0.0, 0.3))
        btn_d.pressed.connect(lambda: self.trigger_manual(0.0, -0.3))
        for btn in [btn_w, btn_s, btn_a, btn_d]:
            btn.released.connect(self.release_manual)
            
        self.btn_stop.clicked.connect(self.emergency_stop)

        joy_layout.addWidget(btn_w, 0, 1)
        joy_layout.addWidget(btn_a, 1, 0)
        joy_layout.addWidget(self.btn_stop, 1, 1)
        joy_layout.addWidget(btn_d, 1, 2)
        joy_layout.addWidget(btn_s, 2, 1)
        left_panel.addLayout(joy_layout)
        main_layout.addLayout(left_panel, stretch=1)

        # ==================== 右侧地图区 ====================
        right_panel = QVBoxLayout()
        self.lbl_map_state = QLabel("🗺️ 实时导航监控")
        self.lbl_map_state.setFont(QFont("Arial", 11, QFont.Bold))
        right_panel.addWidget(self.lbl_map_state)

        # 使用我们自定义的带点击功能的画布
        self.map_canvas = ClickableMapCanvas(self)
        right_panel.addWidget(self.map_canvas, stretch=1)

        main_layout.addLayout(right_panel, stretch=2)
        self.setLayout(main_layout)

    # --- 核心：一键发送完美的零点坐标给 AMCL ---
    def reset_to_origin(self):
        print("[System] 正在发送绝对精准初始定位...")
        msg = PoseWithCovarianceStamped()
        
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = "map"
        
        # 填入你查到的真实精准位置
        msg.pose.pose.position.x = -0.20311299703461597
        msg.pose.pose.position.y = 0.2648602751027685
        msg.pose.pose.position.z = 0.0
        
        # 填入你查到的真实朝向 (四元数)
        msg.pose.pose.orientation.x = 0.0
        msg.pose.pose.orientation.y = 0.0
        msg.pose.pose.orientation.z = -0.0322609712252609
        msg.pose.pose.orientation.w = 0.9994794793969524 
        
        # 极高置信度的协方差矩阵
        msg.pose.covariance = [
            0.0938610085092724, 0.006484012855851394, 0.0, 0.0, 0.0, 0.0, 
            0.006484012855851394, 0.030758659982949077, 0.0, 0.0, 0.0, 0.0, 
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 
            0.0, 0.0, 0.0, 0.0, 0.0, 0.022157677127401115
        ]

        self.init_pose_pub.publish(msg)
        
        # 更新 UI 状态
        self.lbl_nav_status.setText("✅ 自动导航模式就绪 (已初始化)")
        self.lbl_nav_status.setStyleSheet("color: green; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")
        print("[System] 地图初始化指令已发送，AMCL 已对齐！")

    # --- 修复后的：点击地图触发导航算法 ---
    def handle_map_click(self, click_x, click_y):
        if not self.map_info_cache or not self.scaled_pixmap_rect:
            self.lbl_nav_status.setText("⚠️ 地图数据加载中，请稍后...")
            self.lbl_nav_status.setStyleSheet("color: orange; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")
            return

        w, h = self.map_info_cache.width, self.map_info_cache.height
        res = self.map_info_cache.resolution
        ox, oy = self.map_info_cache.origin.position.x, self.map_info_cache.origin.position.y

        # 从列表中解包数据 (已修复报错问题)
        offset_x = self.scaled_pixmap_rect[0]
        offset_y = self.scaled_pixmap_rect[1]
        scale_w = self.scaled_pixmap_rect[2]
        scale_h = self.scaled_pixmap_rect[3]

        # 检查点击是否在有效地图区域内
        if not (offset_x <= click_x <= offset_x + scale_w and offset_y <= click_y <= offset_y + scale_h):
            return

        # 1. 将 UI 点击坐标转为原始像素矩阵坐标
        pixel_x = (click_x - offset_x) * (w / scale_w)
        pixel_y = (click_y - offset_y) * (h / scale_h)

        # 2. 将像素矩阵坐标转为 ROS 物理世界的米 (记得 Y 轴是翻转的)
        real_x = pixel_x * res + ox
        real_y = (h - pixel_y) * res + oy

        # 3. 组装并发送 2D 导航目标点
        goal_msg = PoseStamped()
        goal_msg.header.frame_id = "map"
        goal_msg.header.stamp = rospy.Time.now()
        goal_msg.pose.position.x = real_x
        goal_msg.pose.position.y = real_y
        goal_msg.pose.position.z = 0.0
        # 给定一个默认朝向
        goal_msg.pose.orientation.w = 1.0 

        self.goal_pub.publish(goal_msg)
        self.lbl_nav_status.setText(f"🚀 正在前往目标: (X: {real_x:.2f}, Y: {real_y:.2f})")
        self.lbl_nav_status.setStyleSheet("color: #ff00ff; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")

    # --- 界面控制逻辑 ---
    def trigger_manual(self, linear, angular):
        self.manual_override = True
        self.target_linear = linear
        self.target_angular = angular
        self.lbl_nav_status.setText("⚠️ 人工强制接管中...")
        self.lbl_nav_status.setStyleSheet("color: orange; margin-top: 10px; margin-bottom: 5px;")

    def release_manual(self):
        self.manual_override = False
        self.target_linear = 0.0
        self.target_angular = 0.0
        self.lbl_nav_status.setText("✅ 手动解除，等待新导航指令")
        self.lbl_nav_status.setStyleSheet("color: green; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")

    def emergency_stop(self):
        self.trigger_manual(0.0, 0.0)
        
        # 同时取消现有的导航目标
        cancel_msg = PoseStamped()
        cancel_msg.header.frame_id = "map"
        self.goal_pub.publish(cancel_msg)
        
        self.lbl_nav_status.setText("🛑 已急停并取消导航任务！")
        self.lbl_nav_status.setStyleSheet("color: red; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")

    def render_map(self):
        grid_msg, info = self.robot.get_map_data()
        if not grid_msg or not info:
            return

        self.map_info_cache = info
        w, h = info.width, info.height
        res = info.resolution
        ox, oy = info.origin.position.x, info.origin.position.y

        grid_data = np.array(grid_msg.data, dtype=np.int8).reshape((h, w))
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[grid_data == -1] = [80, 80, 80]
        img[grid_data == 0] = [245, 245, 245]
        img[grid_data > 50] = [30, 30, 30]
        img = np.flipud(img)

        self._img_array_ref = np.ascontiguousarray(img)
        qimg = QImage(self._img_array_ref.data, w, h, 3*w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        status = self.robot.get_status_data()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(220, 20, 60))
        
        px = int((status['x'] - ox) / res)
        py = h - int((status['y'] - oy) / res)
        if (0 <= px < w and 0 <= py < h):
            painter.drawEllipse(px - 5, py - 5, 10, 10)
        painter.end()

        # 等比例缩放并获取真实的渲染矩形
        scaled_pixmap = pixmap.scaled(self.map_canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.map_canvas.setPixmap(scaled_pixmap)
        
        # 记录图像在 Canvas 中的位置 (已修复报错：改用普通列表存储)
        canvas_w, canvas_h = self.map_canvas.width(), self.map_canvas.height()
        img_w, img_h = scaled_pixmap.width(), scaled_pixmap.height()
        self.scaled_pixmap_rect = [
            (canvas_w - img_w) / 2, 
            (canvas_h - img_h) / 2, 
            img_w, 
            img_h
        ]

    def main_loop(self):
        if rospy.is_shutdown():
            self.close()

        status = self.robot.get_status_data()
        self.lbl_real_speed.setText(f"当前速度: {status['linear']:.2f} m/s | {status['angular']:.2f} rad/s")
        self.render_map()

        if self.manual_override:
            self.robot.send_speed(self.target_linear, self.target_angular)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = BunkerNav_GCS_V5()
    gui.show()
    sys.exit(app.exec_())