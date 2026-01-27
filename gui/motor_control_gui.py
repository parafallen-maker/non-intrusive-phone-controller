#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
电机控制上位机 - GUI版本
支持所有控制类型：基础移动、点击、双击、长按、拖动、归位
支持USB摄像头实时视频显示和视频点击控制
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
import threading
import time
from datetime import datetime
from enum import IntEnum
import cv2
from PIL import Image, ImageTk
import numpy as np
import os
import sys
import json
import base64
import requests

# 单实例检查
LOCK_FILE = os.path.join(os.path.expanduser("~"), ".motor_control_gui.lock")
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".motor_control_gui_config.json")

def kill_existing_process():
    """关闭已有的进程"""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            # 先检查进程是否还在运行
            process_running = False
            if sys.platform == 'win32':
                import subprocess
                result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], 
                                      capture_output=True, text=True, timeout=2)
                process_running = str(pid) in result.stdout
            else:
                import signal
                try:
                    os.kill(pid, 0)  # 发送信号0只检查进程是否存在
                    process_running = True
                except OSError:
                    process_running = False
            
            # 只有进程还在运行时才关闭
            if process_running:
                if sys.platform == 'win32':
                    subprocess.run(['taskkill', '/PID', str(pid), '/F'], 
                                 capture_output=True, timeout=5)
                else:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except:
                        pass
                # 等待进程关闭
                time.sleep(0.5)
            
            # 删除旧的锁文件
            try:
                os.remove(LOCK_FILE)
            except:
                pass
        except:
            # 如果检查失败，尝试删除锁文件
            try:
                os.remove(LOCK_FILE)
            except:
                pass

def create_lock_file():
    """创建锁文件"""
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except:
        pass

def remove_lock_file():
    """删除锁文件"""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except:
        pass


class ClickType(IntEnum):
    """操作类型枚举"""
    MOVE = 0      # 基础移动
    CLICK = 1     # 单击
    DOUBLE = 2    # 双击
    LONG = 3      # 长按
    DRAG = 4      # 拖动/滑动
    HOME = 5      # 归位


class CameraCapture:
    """USB摄像头捕获类"""
    
    def __init__(self):
        self.cap = None
        self.running = False
        self.current_frame = None
        self.frame_count = 0
        self.fps = 0
        self.last_time = time.time()
        self.callback = None
        self.frame_skip = 0  # 跳帧计数
        self.skip_frames = 2  # 每3帧更新一次GUI
        self.update_flag = False  # 更新标志
        self.error_count = 0  # 连续错误计数
        self.max_errors = 10  # 最大允许错误次数
        self.width = 2560  # 实际分辨率宽度 (1440p)
        self.height = 1440  # 实际分辨率高度 (1440p)
        
    def list_cameras(self, max_test=5):
        """列出可用摄像头"""
        available = []
        # 只检测索引为1的摄像头，不进行实际读取测试（避免被占用）
        cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        if cap.isOpened():
            available.append({
                'index': 1,
                'name': 'Camera 1',
                'resolution': '2560x1440'
            })
            cap.release()
        return available
    
    def start(self, camera_index=0):
        """启动摄像头"""
        if self.running:
            return False
        
        # 尝试多个后端，避免MSMF错误
        backends = [
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_ANY, "Auto"),
        ]
        
        self.cap = None
        for backend, name in backends:
            print(f"[尝试] 使用{name}后端打开摄像头...")
            cap_test = cv2.VideoCapture(camera_index, backend)
            if cap_test.isOpened():
                self.cap = cap_test
                print(f"[成功] {name}后端打开成功")
                break
            else:
                cap_test.release()
                print(f"[失败] {name}后端打开失败")
        
        if not self.cap or not self.cap.isOpened():
            return False
        
        # 设置摄像头参数
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 设置小缓冲，减少延迟
        
        # 尝试多种分辨率，直到找到支持的分辨率
        resolutions = [
            (2560, 1440),  # 1440p - 优先使用1440p
            (1920, 1080),  # 1080p
            (1280, 720),   # 720p
            (640, 480),    # VGA
            (320, 240),    # QVGA
        ]
        
        success = False
        for width, height in resolutions:
            print(f"[尝试] 设置分辨率: {width}x{height}")
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            
            # 多次尝试读取帧
            for attempt in range(3):
                ret, test_frame = self.cap.read()
                if ret and test_frame is not None and test_frame.size > 0:
                    actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    # 保存实际分辨率
                    self.width = actual_width
                    self.height = actual_height
                    print(f"[成功] 摄像头分辨率设置为: {actual_width}x{actual_height}")
                    success = True
                    break
                else:
                    time.sleep(0.1)  # 等待摄像头稳定
            
            if success:
                break
        
        if not success:
            print("[错误] 所有分辨率尝试失败")
            self.cap.release()
            return False
        
        self.error_count = 0
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return True
    
    def stop(self):
        """停止摄像头"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        if self.cap:
            self.cap.release()
            self.cap = None
        self.current_frame = None
    
    def _capture_loop(self):
        """摄像头捕获循环"""
        consecutive_errors = 0
        while self.running:
            try:
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    self.error_count = 0  # 重置错误计数
                    consecutive_errors = 0
                    self.frame_count += 1
                    
                    # 计算FPS
                    current_time = time.time()
                    if current_time - self.last_time >= 1.0:
                        self.fps = self.frame_count
                        self.frame_count = 0
                        self.last_time = current_time
                    
                    # 跳帧处理，降低GUI更新频率
                    self.frame_skip += 1
                    if self.frame_skip >= self.skip_frames:
                        self.frame_skip = 0
                        self.current_frame = frame.copy()
                        self.update_flag = True
                    
                    time.sleep(0.033)  # 约30fps采集
                else:
                    # 读取失败，累计错误
                    consecutive_errors += 1
                    self.error_count += 1
                    
                    if consecutive_errors == 1:  # 只在第一次错误时打印
                        print(f"[警告] 摄像头读取失败")
                    
                    if self.error_count >= self.max_errors:
                        print(f"[错误] 摄像头连续{self.error_count}次读取失败，自动停止")
                        self.running = False
                        break
                    
                    time.sleep(0.1)  # 错误时等待更久
            except Exception as e:
                print(f"[异常] 摄像头采集异常: {str(e)}")
                time.sleep(0.1)
    
    def get_frame(self):
        """获取当前帧"""
        return self.current_frame


class SerialBridge:
    """串口桥接类 - 双向透明转发"""
    
    def __init__(self):
        self.port1 = None  # 上位机端
        self.port2 = None  # 电机端
        self.running = False
        self.thread = None
        self.callback = None
        self.bytes_1_to_2 = 0
        self.bytes_2_to_1 = 0
        self.buffer_1_to_2 = b""  # 缓冲区port1->port2的数据
        self.buffer_2_to_1 = b""  # 缓冲区port2->port1的数据
    
    def connect(self, port1_name, port2_name, baudrate=9600):
        """连接两个串口"""
        try:
            self.port1 = serial.Serial(
                port=port1_name,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.01
            )
            
            self.port2 = serial.Serial(
                port=port2_name,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.01
            )
            
            return True, f"桥接模式: {port1_name} <-> {port2_name}"
        except Exception as e:
            if self.port1:
                self.port1.close()
            if self.port2:
                self.port2.close()
            return False, f"桥接连接失败: {str(e)}"
    
    def disconnect(self):
        """断开串口"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        if self.port1 and self.port1.is_open:
            self.port1.close()
        if self.port2 and self.port2.is_open:
            self.port2.close()
    
    def start_forwarding(self):
        """启动转发线程"""
        self.running = True
        self.thread = threading.Thread(target=self._forward_loop, daemon=True)
        self.thread.start()
    
    def _forward_loop(self):
        """转发循环"""
        error_count = 0
        while self.running:
            try:
                # 方向1: port1 -> port2
                if self.port1 and self.port1.is_open:
                    try:
                        if self.port1.in_waiting > 0:
                            data = self.port1.read(min(self.port1.in_waiting, 256))  # 最败读256字节
                            if data:
                                self.port2.write(data)
                                self.bytes_1_to_2 += len(data)
                                self.buffer_1_to_2 += data
                                
                                # 按行分组显示
                                self._process_buffer(self.buffer_1_to_2, "[P1->P2]", lambda msg: self.buffer_1_to_2.split(b'\r\n')[0] if b'\r\n' in self.buffer_1_to_2 else b"")
                    except Exception as e:
                        pass
                
                # 方向2: port2 -> port1
                if self.port2 and self.port2.is_open:
                    try:
                        if self.port2.in_waiting > 0:
                            data = self.port2.read(min(self.port2.in_waiting, 256))  # 最败读256字节
                            if data:
                                self.port1.write(data)
                                self.bytes_2_to_1 += len(data)
                                self.buffer_2_to_1 += data
                                
                                # 按行分组显示
                                self._process_buffer(self.buffer_2_to_1, "[P2->P1]", lambda msg: self.buffer_2_to_1.split(b'\r\n')[0] if b'\r\n' in self.buffer_2_to_1 else b"")
                    except Exception as e:
                        pass
                
                error_count = 0
                time.sleep(0.005)  # 增加等待时间，让整线数据串行
            except Exception as e:
                error_count += 1
                if error_count == 1 and self.callback:
                    self.callback(f"桥接错误: {str(e)}")
                if error_count > 10:
                    break
    
    def _process_buffer(self, buffer, prefix, get_line_func):
        """处理缓冲区，按行显示"""
        try:
            while b'\r\n' in buffer or b'\n' in buffer:
                # 优先为\r\n，其次\n
                if b'\r\n' in buffer:
                    line, rest = buffer.split(b'\r\n', 1)
                else:
                    line, rest = buffer.split(b'\n', 1)
                
                line = line.strip()
                if line and self.callback:
                    try:
                        text = line.decode('utf-8', errors='ignore')
                        self.callback(f"{prefix} {text}")
                    except:
                        pass
                
                buffer = rest
            
            # 更新缓冲区（回写到类变量）
            if prefix == "[P1->P2]":
                self.buffer_1_to_2 = buffer
            elif prefix == "[P2->P1]":
                self.buffer_2_to_1 = buffer
        except:
            pass


class MotorController:
    """电机控制器通信类"""
    
    # 这些常量已废弃，不再使用
    # 系统现在使用绝对坐标 (X: 0-3900, Y: 0-6300)
    WORK_X1 = 1200  # 已废弃
    WORK_Y1 = 90    # 已废弃
    WORK_X2 = 3750  # 已废弃
    WORK_Y2 = 6300  # 已废弃
    
    def __init__(self):
        self.serial = None
        self.connected = False
        self.rx_buffer = ""
        self.callback = None
        self.bridge_mode = False
        self.bridge = None
        self.control_port = None  # 桥接模式下用于直接控制的端口
        # 注意：work_x1/y1/x2/y2 已废弃，不再使用
        # GUI层使用绝对坐标 (X: 0-3900, Y: 0-6300)
        # 命令层转换为归一化坐标 (0.0-1.0) 发送给机械臂
        
    def connect(self, port, baudrate=9600, bridge_mode=False, port2=None):
        """连接串口"""
        self.bridge_mode = bridge_mode
        
        if bridge_mode:
            # 桥接模式
            if not port2:
                return False, "桥接模式需要指定两个端口"
            
            self.bridge = SerialBridge()
            self.bridge.callback = self.callback
            success, msg = self.bridge.connect(port, port2, baudrate)
            if success:
                self.bridge.start_forwarding()
                # 保留port2的引用用于直接发送控制指令
                self.control_port = self.bridge.port2
                self.connected = True
            return success, msg
        else:
            # 直连模式
            try:
                self.serial = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.1
                )
                self.connected = True
                return True, f"成功连接到 {port}"
            except Exception as e:
                self.connected = False
                return False, f"连接失败: {str(e)}"
    
    def disconnect(self):
        """断开串口"""
        if self.bridge_mode and self.bridge:
            self.bridge.disconnect()
            self.bridge = None
            self.control_port = None
        elif self.serial and self.serial.is_open:
            self.serial.close()
        self.connected = False
        self.bridge_mode = False
    
    def send_move(self, axis, position):
        """发送单轴移动指令"""
        if not self.connected:
            return False, "未连接"
        
        try:
            cmd = f"move,{axis},{position}\r\n"
            
            # 桥接模式下使用control_port，直接发送到电机控制器
            if self.bridge_mode and self.control_port:
                self.control_port.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"[GUI->P2] {cmd.strip()}")
            else:
                self.serial.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"TX: {cmd.strip()}")
            
            return True, "指令已发送"
        except Exception as e:
            return False, f"发送失败: {str(e)}"
    
    def send_move_xy(self, x, y):
        """发送XY坐标移动指令（不点击）
        
        Args:
            x: X轴绝对坐标 (0-3900)
            y: Y轴绝对坐标 (0-6300)
        """
        if not self.connected:
            return False, "未连接"
        
        try:
            # 限制在有效范围内
            x = max(0, min(3900, int(x)))
            y = max(0, min(6300, int(y)))
            
            # 使用简单的move,x,y格式
            cmd = f"move,{x},{y}\r\n"
            
            # 桥接模式下使用control_port
            if self.bridge_mode and self.control_port:
                self.control_port.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"[GUI->P2] move({x},{y})")
            else:
                self.serial.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"TX: move({x},{y})")
            
            return True, f"移动到({x},{y})"
        except Exception as e:
            return False, f"发送失败: {str(e)}"

    def send_reset(self):
        """发送电机复位指令"""
        if not self.connected:
            return False, "未连接"

        try:
            cmd = "home\r\n"

            if self.bridge_mode and self.control_port:
                self.control_port.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"[GUI->P2] {cmd.strip()}")
            else:
                self.serial.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"TX: {cmd.strip()}")

            return True, "复位指令已发送"
        except Exception as e:
            return False, f"发送失败: {str(e)}"
    
    def send_move_click(self, x, y, work_x1, work_y1, work_x2, work_y2, click_type=ClickType.CLICK, speed=100, delay_ms=0):
        """发送坐标移动指令
        
        Args:
            x: X轴绝对坐标 (0-3900)
            y: Y轴绝对坐标 (0-6300)
            work_x1, work_y1: 工作区域左上角绝对坐标
            work_x2, work_y2: 工作区域右下角绝对坐标
            click_type: 操作类型 (CLICK/DOUBLE/LONG等)
            speed: 速度 (默认100)
            delay_ms: 按压延迟(毫秒)，用于长按操作
        """
        if not self.connected:
            return False, "未连接"
        
        try:
            # 限制所有坐标在有效范围内
            work_x1 = max(0, min(3900, int(work_x1)))
            work_y1 = max(0, min(6300, int(work_y1)))
            work_x2 = max(0, min(3900, int(work_x2)))
            work_y2 = max(0, min(6300, int(work_y2)))
            
            # 确保工作区域有效（x2>x1, y2>y1）
            if work_x2 <= work_x1:
                work_x2 = work_x1 + 100
            if work_y2 <= work_y1:
                work_y2 = work_y1 + 100
            
            # 计算在工作区域内的归一化位置
            norm_x = (x - work_x1) / (work_x2 - work_x1)
            norm_y = (y - work_y1) / (work_y2 - work_y1)
            norm_x = max(0.0, min(1.0, norm_x))
            norm_y = max(0.0, min(1.0, norm_y))
            
            # move_click, <x1>, <y1>, <x2>, <y2>, <norm_x>, <norm_y>, <click_type>, <speed>
            cmd = f"move_click, {work_x1}, {work_y1}, {work_x2}, {work_y2}, {norm_x:.5f}, {norm_y:.5f}, {click_type}, {speed}\r\n"
            
            # 桥接模式下使用control_port，直接发送到电机控制器
            if self.bridge_mode and self.control_port:
                self.control_port.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"[GUI->P2] move_click({work_x1}, {work_y1}, {work_x2}, {work_y2}, {norm_x:.5f}, {norm_y:.5f}, {click_type}, {speed})")
            else:
                self.serial.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"TX: move_click({work_x1}, {work_y1}, {work_x2}, {work_y2}, {norm_x:.5f}, {norm_y:.5f}, {click_type}, {speed})")
            
            return True, f"指令已发送: move_click"
        except Exception as e:
            return False, f"发送失败: {str(e)}"
    
    def send_drag(self, start_x, start_y, end_x, end_y, work_x1, work_y1, work_x2, work_y2):
        """发送拖动指令
        
        Args:
            start_x: 起点X绝对坐标 (0-3900)
            start_y: 起点Y绝对坐标 (0-6300)
            end_x: 终点X绝对坐标 (0-3900)
            end_y: 终点Y绝对坐标 (0-6300)
            work_x1, work_y1, work_x2, work_y2: 工作区范围
        
        格式: drag, work_x1, work_y1, work_x2, work_y2, start_norm_x, start_norm_y, end_norm_x, end_norm_y
        """
        if not self.connected:
            return False, "未连接"
        
        try:
            # 计算工作区尺寸
            work_width = work_x2 - work_x1
            work_height = work_y2 - work_y1
            
            # 归一化坐标：同向（0在工作区顶部，1在底部）
            norm_start_x = (start_x - work_x1) / work_width if work_width > 0 else 0.0
            norm_start_y = (start_y - work_y1) / work_height if work_height > 0 else 0.0
            norm_end_x = (end_x - work_x1) / work_width if work_width > 0 else 0.0
            norm_end_y = (end_y - work_y1) / work_height if work_height > 0 else 0.0
            
            # 限制在0.0-1.0范围内
            norm_start_x = max(0.0, min(1.0, norm_start_x))
            norm_start_y = max(0.0, min(1.0, norm_start_y))
            norm_end_x = max(0.0, min(1.0, norm_end_x))
            norm_end_y = max(0.0, min(1.0, norm_end_y))
            
            # 格式: drag, 工作区x1, 工作区y1, 工作区x2, 工作区y2, 归一化起点x, 归一化起点y, 归一化终点x, 归一化终点y
            cmd = f"drag, {work_x1}, {work_y1}, {work_x2}, {work_y2}, {norm_start_x:.4f}, {norm_start_y:.4f}, {norm_end_x:.4f}, {norm_end_y:.4f}\r\n"
            
            # 桥接模式下使用control_port
            if self.bridge_mode and self.control_port:
                self.control_port.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"[GUI->P2] {cmd.strip()}")
            else:
                self.serial.write(cmd.encode('ascii'))
                if self.callback:
                    self.callback(f"TX: {cmd.strip()}")
            
            return True, "拖动指令已发送"
        except Exception as e:
            return False, f"发送失败: {str(e)}"
    
    def read_response(self):
        """读取响应"""
        if not self.connected:
            return []
        
        responses = []
        
        # 桥接模式：仅让_forward_loop线程读取数据
        # read_response仅用于直连模式
        if self.bridge_mode and self.bridge:
            # 桥接模式下，数据不在这里读取（避免与_forward_loop竞争）
            # 数据输出是通过_forward_loop的回调实现的
            return responses
        
        # 直连模式：读取单个端口
        elif self.serial and self.serial.is_open and self.serial.in_waiting > 0:
            try:
                data = self.serial.read(self.serial.in_waiting)
                self.rx_buffer += data.decode('utf-8', errors='ignore')
                
                while '\n' in self.rx_buffer:
                    line, self.rx_buffer = self.rx_buffer.split('\n', 1)
                    line = line.strip()
                    if line:
                        responses.append(line)
                        if self.callback:
                            self.callback(f"RX: {line}")
            except Exception as e:
                if self.callback:
                    self.callback(f"读取错误: {str(e)}")
        
        return responses


class MotorControlGUI:
    """电机控制GUI界面"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("电机控制上位机 v1.0 - 带视频监控")
        self.root.geometry("1200x900")  # 调整为更适合竖屏视频的尺寸
        self.root.minsize(800, 600)  # 设置最小尺寸
        
        self.controller = MotorController()
        self.controller.callback = self.log_message
        self.reader_thread = None
        self.running = False
        
        # 摄像头相关
        self.camera = CameraCapture()
        self.video_label = None
        self.camera_running = False
        self.video_paused = False  # 视频暂停状态
        
        # 定位状态
        self.locating_mode = None  # None, 'top_left', 'bottom_right'
        self.locate_x = None
        self.locate_y = None
        
        # 屏幕检测相关
        self.screen_detection_mode = None  # None, 'manual', 'auto'
        self.screen_detection_active = False
        self.detect_start_x = None
        self.detect_start_y = None
        self.detect_end_x = None
        self.detect_end_y = None
        self.polygon_points = []  # 手动框选的多边形顶点列表
        self.screen_mask = None  # 屏幕区域蒙版(用于显示)
        self.crop_enabled = False  # 是否启用裁切
        self.crop_rect = None  # 裁切区域 (x1, y1, x2, y2) 原始帧坐标
        self.display_scale = 1.0  # 显示缩放比例
        self.display_offset_x = 0  # 显示偏移 X
        self.display_offset_y = 0  # 显示偏移 Y
        self.display_width = 0  # 实际显示宽度
        self.display_height = 0  # 实际显示高度
        self.rotated_width = 0  # 旋转后帧宽度
        self.rotated_height = 0  # 旋转后帧高度
        self.canvas_width = 0  # Canvas宽度
        self.canvas_height = 0  # Canvas高度
        self.paused_frame = None  # 暂停时保存的帧
        
        # 配置管理
        self.configs = {}  # 存储所有配置 {name: {work_area: {...}, crop_enabled: ..., ...}}
        self.current_config_name = "默认配置"
        
        # 鼠标交互增强
        self.mouse_click_count = 0  # 单次点击计数
        self.mouse_click_timer = None  # 点击计时器
        self.mouse_double_click_threshold = 0.3  # 双击时间阈值(秒)
        self.mouse_drag_active = False  # 是否正在拖动
        self.mouse_long_press_timer = None  # 长按计时器
        self.mouse_long_press_threshold = 0.5  # 长按时间阈值(秒)
        self.current_click_x = None  # 当前点击X坐标
        self.current_click_y = None  # 当前点击Y坐标
        self.mouse_down_pos = None  # 鼠标按下位置(Canvas)
        self.drag_start_pos = None  # 拖动起点 (x, y)
        self.drag_end_pos = None  # 拖动终点 (x, y)
        self.drag_queue_id = None  # 拖动标记的队列编号
        
        # 命令队列系统
        self.command_queue = []  # 命令队列 [{type, pos, data}, ...]
        self.current_command = None  # 当前执行的命令
        self.waiting_response = False  # 是否等待响应
        self.command_timeout = 10  # 命令超时时间（秒）
        self.command_timer = None  # 命令超时计时器
        self.queue_seq = 1  # 队列编号（队列清空后重置）
        
        # 操作标记显示
        self.operation_markers = []  # 操作标记列表 [{type, pos, timestamp}, ...]

        # 模型配置（旧版本兼容）
        self.model_api_key = ""
        self.model_base_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        self.model_name = "autoglm-phone"
        
        # AutoGLM API 配置
        self.autoglm_api_base = "http://114.132.181.107:7663"
        self.autoglm_screen_width = 1080  # 手机屏幕宽度
        self.autoglm_screen_height = 2340  # 手机屏幕高度
        
        # 自动任务状态
        self.auto_task_running = False
        self.auto_task_thread = None
        self.auto_task_stop_flag = False
        self.auto_task_current_step = 0
        self.auto_task_max_steps = 30
        self.auto_task_step_delay = 1.0  # 每步之间的延迟（秒）
        
        # 系统手势模板（归一化坐标，基于工作区）
        # 返回桌面：底部中心上滑（来源于一次成功拖动样本）
        self.home_swipe_template = {
            'start_norm_x': 0.4243,
            'start_norm_y': 0.9775,
            'end_norm_x': 0.4294,
            'end_norm_y': 0.1397
        }
        # 返回上一页：左侧边缘内滑
        self.back_swipe_template = {
            'start_norm_x': 0.02,
            'start_norm_y': 0.5,
            'end_norm_x': 0.35,
            'end_norm_y': 0.5
        }
        
        self.setup_ui()
        self.list_ports()
        self.list_cameras()
        self.load_config()  # 加载配置
        
    def setup_ui(self):
        """创建UI界面"""
        
        # 主容器：左右分割
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # ========== 左侧：视频预览区域（占据最大空间）==========
        left_container = ttk.Frame(main_paned)
        main_paned.add(left_container, weight=2)  # 调整权重比例
        
        # 顶部摄像头控制栏（紧凑布局）
        cam_control_frame = ttk.Frame(left_container)
        cam_control_frame.pack(fill=tk.X, padx=5, pady=(5, 2))
        
        # 摄像头选择和控制
        ttk.Label(cam_control_frame, text="摄像头:").pack(side=tk.LEFT, padx=(0, 5))
        self.camera_var = tk.StringVar()
        self.camera_combo = ttk.Combobox(cam_control_frame, textvariable=self.camera_var, width=15, state='readonly')
        self.camera_combo.pack(side=tk.LEFT, padx=2)
        
        self.cam_btn = ttk.Button(cam_control_frame, text="启动", command=self.toggle_camera, width=8)
        self.cam_btn.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(cam_control_frame, text="刷新", command=self.list_cameras, width=6).pack(side=tk.LEFT, padx=2)
        
        # 模型配置按钮（右上角）
        ttk.Button(cam_control_frame, text="模型配置", command=self.open_model_config_dialog, width=10).pack(side=tk.RIGHT, padx=5)
        self.fps_label = ttk.Label(cam_control_frame, text="FPS: 0", width=10)
        self.fps_label.pack(side=tk.RIGHT, padx=5)
        
        # 屏幕检测控制栏
        screen_control_frame = ttk.Frame(left_container)
        screen_control_frame.pack(fill=tk.X, padx=5, pady=2)
        
        ttk.Label(screen_control_frame, text="屏幕检测:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(screen_control_frame, text="自动识别", command=self.auto_detect_screen, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(screen_control_frame, text="手动框选", command=self.start_manual_screen_detection, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(screen_control_frame, text="确认", command=self.finish_manual_detection, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(screen_control_frame, text="清除", command=self.clear_screen_detection, width=8).pack(side=tk.LEFT, padx=2)
        
        self.crop_btn = ttk.Button(screen_control_frame, text="裁切画面", command=self.toggle_crop, width=10)
        self.crop_btn.pack(side=tk.RIGHT, padx=2)
        
        # 视频显示容器（直接使用Frame，保持16:9竖屏比例）
        # 创建外部包装容器，背景为黑色，与视频融为一体
        self.video_outer_wrapper = tk.Frame(left_container, bg='black')
        self.video_outer_wrapper.pack(fill=tk.BOTH, expand=True)
        
        # 创建16:9比例的视频容器（初始大小：高宽比16:9，竖屏）
        # 动态计算合适的初始尺寸
        self.video_container = tk.Frame(self.video_outer_wrapper, bg='black', width=450, height=800)
        self.video_container.place(relx=0.5, rely=0.5, anchor='center')
        
        # 防止容器自动收缩
        self.video_container.pack_propagate(False)
        
        # 视频显示区域（Canvas，完全填充，无边框，无内边距）
        self.video_canvas = tk.Canvas(self.video_container, bg='black', highlightthickness=0, bd=0)
        self.video_canvas.pack(fill=tk.BOTH, expand=True)
        
        # 绑定外部容器的Configure事件，用于动态调整16:9比例
        self.video_outer_wrapper.bind('<Configure>', self.on_outer_container_resize)
        
        # 绑定Canvas的Configure事件
        self.video_canvas.bind('<Configure>', self.on_canvas_resize)
        
        # 在Canvas上创建Label用于显示视频
        self.video_label = ttk.Label(self.video_canvas, text="摄像头未启动", 
                                     background='black', foreground='white',
                                     font=('Arial', 14), cursor='circle')
        self.video_label.place(relx=0.5, rely=0.5, anchor='center')
        
        # 绑定鼠标事件
        self.video_label.bind('<Button-1>', self.on_video_click)
        self.video_label.bind('<B1-Motion>', self.on_video_drag)
        self.video_label.bind('<ButtonRelease-1>', self.on_video_release)
        self.video_label.bind('<Motion>', self.on_video_motion)
        
        # 底部信息栏（紧凑）
        self.video_info_label = ttk.Label(left_container, text="等待启动摄像头...", 
                                          font=('Arial', 9), foreground='gray')
        self.video_info_label.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=(0, 5))
        
        # ========== 右侧：控制区域 ==========
        right_container = ttk.Frame(main_paned)
        main_paned.add(right_container, weight=1)
        
        # ========== 连接区域 ==========
        conn_frame = ttk.LabelFrame(right_container, text="串口连接", padding=10)
        conn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 第一行：模式选择
        ttk.Label(conn_frame, text="模式:").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.mode_var = tk.StringVar(value="direct")
        mode_frame = ttk.Frame(conn_frame)
        mode_frame.grid(row=0, column=1, columnspan=2, padx=5, sticky=tk.W)
        ttk.Radiobutton(mode_frame, text="直连", variable=self.mode_var, 
                       value="direct", command=self.on_mode_change).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="桥接", variable=self.mode_var, 
                       value="bridge", command=self.on_mode_change).pack(side=tk.LEFT, padx=5)
        
        # 第二行：端口1（根据模式动态标注）
        self.port1_label = ttk.Label(conn_frame, text="端口1(控制端):")
        self.port1_label.grid(row=1, column=0, padx=5, sticky=tk.W)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(conn_frame, textvariable=self.port_var, width=15)
        self.port_combo.grid(row=1, column=1, padx=5)
        
        # 第三行：端口2（桥接模式用）
        self.port2_label = ttk.Label(conn_frame, text="端口2(接收端):")
        self.port2_label.grid(row=2, column=0, padx=5, sticky=tk.W)
        self.port2_var = tk.StringVar()
        self.port2_combo = ttk.Combobox(conn_frame, textvariable=self.port2_var, width=15)
        self.port2_combo.grid(row=2, column=1, padx=5)
        
        # 第四行：波特率和按钮
        ttk.Label(conn_frame, text="波特率:").grid(row=1, column=2, padx=5)
        self.baud_var = tk.StringVar(value="9600")
        baud_combo = ttk.Combobox(conn_frame, textvariable=self.baud_var, 
                                   values=["9600", "19200", "38400", "115200"], width=10)
        baud_combo.grid(row=1, column=3, padx=5)
        
        self.conn_btn = ttk.Button(conn_frame, text="连接", command=self.toggle_connection)
        self.conn_btn.grid(row=1, column=4, padx=5)
        
        ttk.Button(conn_frame, text="刷新", command=self.list_ports).grid(row=1, column=5, padx=5)
        
        self.status_label = ttk.Label(conn_frame, text="未连接", foreground="red")
        self.status_label.grid(row=1, column=6, padx=20)
        
        # 初始隐藏端口2
        self.port2_label.grid_remove()
        self.port2_combo.grid_remove()

        # 初始化端口标签文本（保持与模式逻辑一致）
        self.update_port_labels()
        
        # ========== 控制区域 ==========
        control_frame = ttk.LabelFrame(right_container, text="控制面板", padding=10)
        control_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 左侧 - 坐标控制
        left_frame = ttk.Frame(control_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        # ========== 工作区域与坐标测试合并 ==========
        work_frame = ttk.LabelFrame(left_frame, text="工作区域校准 (绝对坐标 X:0-3900, Y:0-6300)", padding=10)
        work_frame.pack(fill=tk.X, pady=5)
        
        # 配置管理区域
        config_mgmt_frame = ttk.Frame(work_frame)
        config_mgmt_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(config_mgmt_frame, text="配置:").pack(side=tk.LEFT, padx=(0,5))
        self.config_name_var = tk.StringVar(value="默认配置")
        self.config_combo = ttk.Combobox(config_mgmt_frame, textvariable=self.config_name_var, 
                                          values=["默认配置"], state="readonly", width=15)
        self.config_combo.pack(side=tk.LEFT, padx=2)
        self.config_combo.bind('<<ComboboxSelected>>', self.load_selected_config)
        ttk.Button(config_mgmt_frame, text="保存配置", command=self.save_current_config).pack(side=tk.LEFT, padx=2)
        ttk.Button(config_mgmt_frame, text="新建配置", command=self.create_new_config).pack(side=tk.LEFT, padx=2)
        ttk.Button(config_mgmt_frame, text="删除配置", command=self.delete_current_config).pack(side=tk.LEFT, padx=2)
        
        # 说明文字
        ttk.Label(work_frame, text="调整滑块（绝对坐标 X:0-3900, Y:0-6300）移动到屏幕角落，测试移动后点击定位保存", 
                     wraplength=300, justify=tk.LEFT, foreground="blue").pack(fill=tk.X, padx=5, pady=(5,5))
        
        # X坐标输入 - 绝对坐标 0-3900
        x_frame = ttk.Frame(work_frame)
        x_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(x_frame, text="X:", width=3).pack(side=tk.LEFT, padx=(0,5))
        self.x_var = tk.IntVar(value=0)
        ttk.Scale(x_frame, from_=0, to=3900, variable=self.x_var, 
                 orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.x_label = ttk.Label(x_frame, text="0", width=8)
        self.x_label.pack(side=tk.LEFT, padx=5)
        
        # Y坐标输入 - 绝对坐标 0-6300
        y_frame = ttk.Frame(work_frame)
        y_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(y_frame, text="Y:", width=3).pack(side=tk.LEFT, padx=(0,5))
        self.y_var = tk.IntVar(value=0)
        ttk.Scale(y_frame, from_=0, to=6300, variable=self.y_var, 
                 orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.y_label = ttk.Label(y_frame, text="0", width=8)
        self.y_label.pack(side=tk.LEFT, padx=5)
        
        # 更新坐标显示
        self.x_var.trace_add('write', lambda *_: self.x_label.config(text=f"{self.x_var.get()}"))
        self.y_var.trace_add('write', lambda *_: self.y_label.config(text=f"{self.y_var.get()}"))
        
        # 定位按钮（简化，去掉输入框）
        locate_frame = ttk.Frame(work_frame)
        locate_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # 左上角定位
        tl_frame = ttk.Frame(locate_frame)
        tl_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(tl_frame, text="定位左上角", command=self.locate_top_left_from_slider).pack(fill=tk.X)
        
        # 测试按钮
        test_frame = ttk.Frame(locate_frame)
        test_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(test_frame, text="测试移动", command=self.test_slider_position).pack(fill=tk.X)
        
        # 右下角定位
        br_frame = ttk.Frame(locate_frame)
        br_frame.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(br_frame, text="定位右下角", command=self.locate_bottom_right_from_slider).pack(fill=tk.X)
        
        # 工作区域显示（绝对坐标）
        info_frame = ttk.Frame(work_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # 左上角
        ttk.Label(info_frame, text="左上:").grid(row=0, column=0, padx=2, sticky=tk.W)
        self.x1_var = tk.IntVar(value=0)
        ttk.Label(info_frame, textvariable=self.x1_var, width=7, relief=tk.SUNKEN).grid(row=0, column=1, padx=2)
        self.y1_var = tk.IntVar(value=0)
        ttk.Label(info_frame, textvariable=self.y1_var, width=7, relief=tk.SUNKEN).grid(row=0, column=2, padx=2)
        
        # 右下角
        ttk.Label(info_frame, text="右下:").grid(row=0, column=3, padx=(10,2), sticky=tk.W)
        self.x2_var = tk.IntVar(value=3900)
        ttk.Label(info_frame, textvariable=self.x2_var, width=7, relief=tk.SUNKEN).grid(row=0, column=4, padx=2)
        self.y2_var = tk.IntVar(value=6300)
        ttk.Label(info_frame, textvariable=self.y2_var, width=7, relief=tk.SUNKEN).grid(row=0, column=5, padx=2)
        
        # 坐标映射分析
        ratio_frame = ttk.LabelFrame(left_frame, text="坐标映射分析", padding=10)
        ratio_frame.pack(fill=tk.X, pady=5)
        
        self.ratio_info_label = ttk.Label(ratio_frame, text="请完成工作区域校准", 
                                          wraplength=300, justify=tk.LEFT)
        self.ratio_info_label.pack(fill=tk.X, padx=5, pady=5)
        
        # 绑定坐标变化事件
        self.x1_var.trace_add('write', lambda *_: self.update_ratio_info())
        self.y1_var.trace_add('write', lambda *_: self.update_ratio_info())
        self.x2_var.trace_add('write', lambda *_: self.update_ratio_info())
        self.y2_var.trace_add('write', lambda *_: self.update_ratio_info())
        
        # 右侧 - 操作类型整合区域
        right_frame = ttk.Frame(control_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        
        # 操作按钮
        btn_frame = ttk.LabelFrame(right_frame, text="操作类型", padding=10)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # 使用网格布局 - 基础操作（蓝色风格）
        basic_buttons = [
            ("基础移动", ClickType.MOVE, "移动到目标位置", "primary"),
            ("归位", ClickType.HOME, "回到原点", "primary")
        ]
        
        row_idx = 0
        for idx, (text, cmd_type, tooltip, style) in enumerate(basic_buttons):
            col = idx % 2
            btn = ttk.Button(btn_frame, text=text, width=15,
                           command=lambda t=cmd_type: self.execute_command(t))
            btn.grid(row=row_idx, column=col, padx=5, pady=3, sticky=tk.EW)
            self.create_tooltip(btn, tooltip)
        row_idx += 1
        
        # 点击操作（默认风格）
        click_buttons = [
            ("单击", ClickType.CLICK, "移动后单击"),
            ("双击", ClickType.DOUBLE, "移动后双击"),
            ("长按", ClickType.LONG, "移动后长按"),
            ("拖动", ClickType.DRAG, "从当前位置拖动")
        ]
        
        for idx, (text, cmd_type, tooltip) in enumerate(click_buttons):
            row = row_idx + idx // 2
            col = idx % 2
            btn = ttk.Button(btn_frame, text=text, width=15,
                           command=lambda t=cmd_type: self.execute_command(t))
            btn.grid(row=row, column=col, padx=5, pady=3, sticky=tk.EW)
            self.create_tooltip(btn, tooltip)
        row_idx += 2
        
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)

        # 系统操作（独占行）
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).grid(row=row_idx, column=0, columnspan=2, sticky=tk.EW, pady=5)
        row_idx += 1
        
        reset_btn = ttk.Button(btn_frame, text="复位", width=15, command=self.reset_motor)
        reset_btn.grid(row=row_idx, column=0, columnspan=2, padx=5, pady=3, sticky=tk.EW)
        self.create_tooltip(reset_btn, "发送电机复位指令")
        row_idx += 1
        
        photo_btn = ttk.Button(btn_frame, text="拍照移动", width=15, command=self.photo_mode_move)
        photo_btn.grid(row=row_idx, column=0, columnspan=2, padx=5, pady=3, sticky=tk.EW)
        self.create_tooltip(photo_btn, "固定移动到拍照位置 move,1,3300")
        row_idx += 1

        # 返回桌面（底部中心上滑）
        home_swipe_btn = ttk.Button(btn_frame, text="返回桌面(上滑)", width=15, command=self.perform_home_swipe_gesture)
        home_swipe_btn.grid(row=row_idx, column=0, columnspan=2, padx=5, pady=3, sticky=tk.EW)
        self.create_tooltip(home_swipe_btn, "执行系统手势：底部中心上滑（Home）")
        row_idx += 1
        
        # 返回上一页（侧边内滑）
        back_swipe_btn = ttk.Button(btn_frame, text="返回(侧滑)", width=15, command=self.perform_back_swipe_gesture)
        back_swipe_btn.grid(row=row_idx, column=0, columnspan=2, padx=5, pady=3, sticky=tk.EW)
        self.create_tooltip(back_swipe_btn, "执行系统手势：左侧边缘内滑（Back）")
        row_idx += 1
        
        # ========== 自动任务区域 ==========
        auto_task_frame = ttk.LabelFrame(right_frame, text="AutoGLM 自动任务", padding=10)
        auto_task_frame.pack(fill=tk.X, pady=5)
        
        # 任务描述输入
        ttk.Label(auto_task_frame, text="任务描述:").pack(anchor=tk.W)
        self.auto_task_entry = ttk.Entry(auto_task_frame, width=30)
        self.auto_task_entry.pack(fill=tk.X, pady=(2, 5))
        self.auto_task_entry.insert(0, "打开微信")
        
        # 参数设置行
        param_frame = ttk.Frame(auto_task_frame)
        param_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(param_frame, text="最大步数:").pack(side=tk.LEFT)
        self.auto_task_max_steps_var = tk.IntVar(value=30)
        ttk.Spinbox(param_frame, from_=1, to=100, width=5, 
                    textvariable=self.auto_task_max_steps_var).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(param_frame, text="步间延迟(秒):").pack(side=tk.LEFT, padx=(10, 0))
        self.auto_task_delay_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(param_frame, from_=0.1, to=5.0, increment=0.1, width=5,
                    textvariable=self.auto_task_delay_var).pack(side=tk.LEFT, padx=2)
        
        # 控制按钮
        btn_row = ttk.Frame(auto_task_frame)
        btn_row.pack(fill=tk.X, pady=5)
        
        self.auto_task_start_btn = ttk.Button(btn_row, text="▶ 开始任务", 
                                               command=self.start_auto_task, width=12)
        self.auto_task_start_btn.pack(side=tk.LEFT, padx=2)
        
        self.auto_task_stop_btn = ttk.Button(btn_row, text="■ 停止", 
                                              command=self.stop_auto_task, width=8, state=tk.DISABLED)
        self.auto_task_stop_btn.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(btn_row, text="API配置", command=self.open_autoglm_config_dialog, 
                   width=8).pack(side=tk.RIGHT, padx=2)
        
        # 状态显示
        self.auto_task_status_var = tk.StringVar(value="就绪")
        self.auto_task_status_label = ttk.Label(auto_task_frame, 
                                                 textvariable=self.auto_task_status_var,
                                                 foreground="gray")
        self.auto_task_status_label.pack(anchor=tk.W, pady=2)
        
        # 快捷位置（放在操作类型下方）
        preset_frame = ttk.LabelFrame(right_frame, text="快捷位置", padding=10)
        preset_frame.pack(fill=tk.X, pady=5)
        
        presets = [
            ("中心", 0.5, 0.5),
            ("左上", 0.0, 0.0),
            ("右上", 1.0, 0.0),
            ("左下", 0.0, 1.0),
            ("右下", 1.0, 1.0)
        ]
        
        for idx, (name, x, y) in enumerate(presets):
            row = idx // 3
            col = idx % 3
            ttk.Button(preset_frame, text=name, width=10,
                      command=lambda px=x, py=y: self.set_position(px, py)).grid(
                      row=row, column=col, padx=2, pady=2)
        
        preset_frame.columnconfigure(0, weight=1)
        preset_frame.columnconfigure(1, weight=1)
        preset_frame.columnconfigure(2, weight=1)
        
        # ========== 手动指令区域 ==========
        cmd_frame = ttk.LabelFrame(right_container, text="手动指令", padding=10)
        cmd_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 指令输入行
        cmd_input_frame = ttk.Frame(cmd_frame)
        cmd_input_frame.pack(fill=tk.X)
        
        self.manual_cmd_entry = ttk.Entry(cmd_input_frame, width=30)
        self.manual_cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.manual_cmd_entry.bind('<Return>', lambda e: self.send_manual_command())
        
        ttk.Button(cmd_input_frame, text="发送", command=self.send_manual_command, width=8).pack(side=tk.LEFT)
        
        # 快捷指令按钮
        quick_cmd_frame = ttk.Frame(cmd_frame)
        quick_cmd_frame.pack(fill=tk.X, pady=(5, 0))
        
        quick_commands = [
            ("复位", "reset"),
            ("归位", "home"),
            ("状态", "status"),
            ("停止", "stop"),
        ]
        
        for text, cmd in quick_commands:
            ttk.Button(quick_cmd_frame, text=text, width=6,
                      command=lambda c=cmd: self.send_quick_command(c)).pack(side=tk.LEFT, padx=2)
        
        # 指令历史下拉
        ttk.Label(cmd_frame, text="历史指令:").pack(anchor=tk.W, pady=(5, 0))
        self.cmd_history = []
        self.cmd_history_var = tk.StringVar()
        self.cmd_history_combo = ttk.Combobox(cmd_frame, textvariable=self.cmd_history_var, 
                                               state='readonly', width=35)
        self.cmd_history_combo.pack(fill=tk.X, pady=2)
        self.cmd_history_combo.bind('<<ComboboxSelected>>', self.on_history_select)
        
        # ========== 日志区域 ==========
        log_frame = ttk.LabelFrame(right_container, text="通信日志", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 按钮行
        btn_row = ttk.Frame(log_frame)
        btn_row.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Button(btn_row, text="清空日志", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="保存日志", command=self.save_log).pack(side=tk.LEFT, padx=5)
        
    def create_tooltip(self, widget, text):
        """创建简单的tooltip"""
        def on_enter(event):
            widget.config(cursor="hand2")
        def on_leave(event):
            widget.config(cursor="")
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
    
    def list_ports(self):
        """列出可用串口"""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo['values'] = ports
        self.port2_combo['values'] = ports
        
        # 设置默认端口
        # 直连模式：端口1默认COM13
        # 桥接模式：端口1默认COM7，端口2默认COM13
        if 'COM13' in ports:
            self.port_combo.set('COM13')
        elif ports:
            self.port_combo.current(0)
        
        if 'COM13' in ports:
            self.port2_combo.set('COM13')
        elif len(ports) > 1:
            self.port2_combo.current(1)
        elif ports:
            self.port2_combo.current(0)

    def update_port_labels(self):
        """根据模式更新端口标签，保持与控制逻辑一致"""
        if self.mode_var.get() == "bridge":
            self.port1_label.config(text="端口1(桥接上游):")
            self.port2_label.config(text="端口2(控制端/电机):")
        else:
            self.port1_label.config(text="端口1(控制端):")
            self.port2_label.config(text="端口2(备用):")
    
    def on_mode_change(self):
        """模式切换"""
        self.update_port_labels()
        if self.mode_var.get() == "bridge":
            # 显示端口2
            self.port2_label.grid()
            self.port2_combo.grid()
            # 桥接模式下，端口1默认为COM7（桥接上游）
            ports = [port.device for port in serial.tools.list_ports.comports()]
            if 'COM7' in ports:
                self.port_combo.set('COM7')
            elif ports:
                self.port_combo.current(0)
            self.log_message("切换到桥接模式：端口1为桥接上游，端口2为控制端/电机")
        else:
            # 隐藏端口2
            self.port2_label.grid_remove()
            self.port2_combo.grid_remove()
            # 直连模式下，端口1默认为COM7
            ports = [port.device for port in serial.tools.list_ports.comports()]
            if 'COM7' in ports:
                self.port_combo.set('COM7')
            elif ports:
                self.port_combo.current(0)
            self.log_message("切换到直连模式：只需要一个端口")
    
    def on_outer_container_resize(self, event):
        """外部容器尺寸改变时，调整内部容器的比例"""
        if not hasattr(self, 'video_container'):
            return
        
        # 获取外部容器尺寸
        container_width = event.width
        container_height = event.height
        
        if container_width < 10 or container_height < 10:
            return
        
        # 确定目标比例
        if self.crop_enabled and self.crop_rect:
            # 裁切模式：使用裁切区域的实际比例（旋转后）
            x1, y1, x2, y2 = self.crop_rect
            crop_width = x2 - x1
            crop_height = y2 - y1
            # 旋转90度后，宽高互换
            target_ratio = crop_height / crop_width  # 宽度/高度的比例（旋转后）
        else:
            # 未裁切模式：使用16:9的高宽比（高度:宽度 = 16:9），即高度较大的竖屏
            target_ratio = 9.0 / 16.0  # 宽度/高度的比例
        
        current_ratio = container_width / container_height
        
        if current_ratio > target_ratio:
            # 容器太宽，以高度为准，计算合适的宽度
            video_height = container_height
            video_width = int(video_height * target_ratio)
        else:
            # 容器太窄或刚好，以宽度为准，计算合适的高度
            video_width = container_width
            video_height = int(video_width / target_ratio)
        
        # 确保尺寸合理
        video_width = max(90, min(video_width, container_width))
        video_height = max(160, min(video_height, container_height))
        
        # 设置内部容器尺寸
        self.video_container.configure(width=video_width, height=video_height)
    
    def on_canvas_resize(self, event):
        """Canvas尺寸改变时的处理"""
        # 当Canvas尺寸改变时，如果有视频正在播放，重新调整显示
        if self.camera_running and hasattr(self, 'video_label') and self.video_label.imgtk:
            # 标记需要重新计算尺寸
            if hasattr(self, '_size_logged'):
                delattr(self, '_size_logged')
            if hasattr(self, '_scale_logged'):
                delattr(self, '_scale_logged')
    
    def list_cameras(self):
        """列出可用摄像头"""
        cameras = self.camera.list_cameras()
        if cameras:
            camera_names = [f"{cam['name']} - {cam['resolution']}" for cam in cameras]
            self.camera_combo['values'] = camera_names
            self.camera_combo.current(0)
            self.camera_indices = [cam['index'] for cam in cameras]
        else:
            self.camera_combo['values'] = ["未找到摄像头"]
            self.camera_indices = []
    
    def toggle_camera(self):
        """启动/停止摄像头"""
        if not self.camera_running:
            if not self.camera_indices:
                messagebox.showerror("错误", "未找到可用摄像头")
                return
            
            cam_idx = self.camera_combo.current()
            if cam_idx < 0 or cam_idx >= len(self.camera_indices):
                messagebox.showerror("错误", "请选择摄像头")
                return
            
            camera_index = self.camera_indices[cam_idx]
            if self.camera.start(camera_index):
                self.camera_running = True
                self.cam_btn.config(text="停止摄像头")
                self.log_message(f"摄像头已启动: {self.camera_var.get()}")
                # 启动GUI更新循环
                self.root.after(100, self.on_new_frame)
            else:
                messagebox.showerror("错误", "无法启动摄像头")
        else:
            self.camera.stop()
            self.camera_running = False
            self.cam_btn.config(text="启动摄像头")
            self.video_label.config(image='', text="摄像头未启动")
            self.video_info_label.config(text="摄像头已停止")
            self.fps_label.config(text="FPS: 0")
            self.log_message("摄像头已停止")
    
    def on_new_frame(self):
        """接收新帧并显示（定时调用）"""
        try:
            if not self.camera_running or self.camera.current_frame is None:
                return
            
            # 如果有暂停帧，使用暂停帧；否则使用实时帧
            if self.paused_frame is not None:
                frame = self.paused_frame.copy()
            else:
                # 只在有新帧时更新
                if not self.camera.update_flag:
                    return
                    
                self.camera.update_flag = False
                frame = self.camera.current_frame.copy()
            
            # 转换为RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 保存原始帧尺寸（用于坐标转换）
            h_original, w_original = frame_rgb.shape[:2]
            crop_offset_x = 0
            crop_offset_y = 0
            
            # 应用裁切（如果启用）
            if self.crop_enabled and self.crop_rect is not None:
                x1, y1, x2, y2 = self.crop_rect
                crop_offset_x = x1
                crop_offset_y = y1
                frame_rgb = frame_rgb[y1:y2, x1:x2]
            
            # 保存裁切偏移量供坐标转换使用
            self.current_crop_offset_x = crop_offset_x
            self.current_crop_offset_y = crop_offset_y
            self.current_original_width = w_original
            self.current_original_height = h_original
            
            # 绘制屏幕检测蒙版和多边形（仅在未裁切时显示）
            if not self.crop_enabled and (self.screen_mask is not None or (self.screen_detection_active and len(self.polygon_points) > 0)):
                # 创建叠加层
                overlay = frame_rgb.copy()
                
                # 如果有完整的蒙版，绘制半透明蒙版
                if self.screen_mask is not None:
                    mask_colored = cv2.cvtColor(self.screen_mask, cv2.COLOR_GRAY2RGB)
                    mask_colored[:, :, 0] = 0  # 移除红色通道
                    mask_colored[:, :, 2] = 0  # 移除蓝色通道
                    overlay = cv2.addWeighted(frame_rgb, 0.7, mask_colored, 0.3, 0)
                
                # 如果正在手动框选，绘制当前的多边形
                if self.screen_detection_active and len(self.polygon_points) > 0:
                    points = np.array(self.polygon_points, dtype=np.int32)
                    
                    # 绘制已连接的线段
                    for i in range(len(points) - 1):
                        cv2.line(overlay, tuple(points[i]), tuple(points[i + 1]), (0, 255, 0), 2)
                    
                    # 如果有3个以上的点，连接首尾形成闭合多边形
                    if len(points) >= 3:
                        cv2.line(overlay, tuple(points[-1]), tuple(points[0]), (0, 255, 0), 2)
                        # 填充半透明区域
                        mask_temp = np.zeros(frame_rgb.shape[:2], dtype=np.uint8)
                        cv2.fillPoly(mask_temp, [points], 255)
                        mask_colored_temp = cv2.cvtColor(mask_temp, cv2.COLOR_GRAY2RGB)
                        mask_colored_temp[:, :, 0] = 0
                        mask_colored_temp[:, :, 2] = 0
                        overlay = cv2.addWeighted(overlay, 0.8, mask_colored_temp, 0.2, 0)
                    
                    # 绘制顶点
                    for i, point in enumerate(points):
                        cv2.circle(overlay, tuple(point), 5, (255, 0, 0), -1)
                        cv2.putText(overlay, str(i + 1), (point[0] + 10, point[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                frame_rgb = overlay
            
            # 逆时针旋转90度
            frame_rotated = cv2.rotate(frame_rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
            
            # 获取旋转后的原始尺寸
            h_rotated, w_rotated = frame_rotated.shape[:2]
            
            # 获取Canvas的实际大小（视频显示区域）
            canvas_width = self.video_canvas.winfo_width()
            canvas_height = self.video_canvas.winfo_height()
            
            # 如果Canvas还未显示，强制更新一次并重新获取尺寸
            if canvas_width < 10 or canvas_height < 10:
                self.video_canvas.update_idletasks()
                canvas_width = self.video_canvas.winfo_width()
                canvas_height = self.video_canvas.winfo_height()
            
            # 如果Canvas尺寸仍然无效，使用合理的默认值（640x480）
            if canvas_width < 10 or canvas_height < 10:
                canvas_width = 640
                canvas_height = 480
            
            # 调试日志：输出尺寸信息（仅第一次）
            if not hasattr(self, '_size_logged'):
                self._size_logged = True
                self.log_message(f"[调试] Canvas尺寸: {canvas_width}x{canvas_height}")
                self.log_message(f"[调试] 旋转后帧尺寸: {w_rotated}x{h_rotated}")
            
            # 计算缩放比例
            scale_w = canvas_width / w_rotated
            scale_h = canvas_height / h_rotated
            
            # 使用max模式：充满Canvas（会裁切超出部分）
            # 增加一点点缩放以确保完全覆盖（消除舍入误差）
            scale = max(scale_w, scale_h) * 1.001
            
            display_width = int(w_rotated * scale + 0.5)  # 四舍五入
            display_height = int(h_rotated * scale + 0.5)
            
            # 确保显示尺寸至少等于Canvas尺寸
            if display_width < canvas_width:
                display_width = canvas_width
            if display_height < canvas_height:
                display_height = canvas_height
            
            # 调整大小到显示尺寸
            frame_resized = cv2.resize(frame_rotated, (display_width, display_height))
            
            # 裁切到精确的Canvas尺寸
            if display_width > canvas_width or display_height > canvas_height:
                start_x = (display_width - canvas_width) // 2
                start_y = (display_height - canvas_height) // 2
                end_x = start_x + canvas_width
                end_y = start_y + canvas_height
                
                frame_resized = frame_resized[start_y:end_y, start_x:end_x]

            # 调整显示尺寸为Canvas尺寸，确保点击映射一致
            display_width = canvas_width
            display_height = canvas_height
            
            # 最终尺寸必须精确匹配Canvas
            display_width = canvas_width
            display_height = canvas_height
            
            # 绘制拖动标记（在转换为PIL之前）
            if self.drag_start_pos is not None:
                cv2.circle(frame_resized, self.drag_start_pos, 8, (0, 255, 0), 2)
                cv2.circle(frame_resized, self.drag_start_pos, 3, (0, 255, 0), -1)
                start_label = "START"
                if getattr(self, 'drag_queue_id', None):
                    start_label += f" #{self.drag_queue_id}"
                cv2.putText(frame_resized, start_label, (self.drag_start_pos[0] + 12, self.drag_start_pos[1] - 8),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            if self.drag_end_pos is not None:
                cv2.circle(frame_resized, self.drag_end_pos, 8, (0, 0, 255), 2)
                cv2.circle(frame_resized, self.drag_end_pos, 3, (0, 0, 255), -1)
                end_label = "END"
                if getattr(self, 'drag_queue_id', None):
                    end_label += f" #{self.drag_queue_id}"
                cv2.putText(frame_resized, end_label, (self.drag_end_pos[0] + 12, self.drag_end_pos[1] - 8),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                
                if self.drag_start_pos is not None:
                    cv2.arrowedLine(frame_resized, self.drag_start_pos, self.drag_end_pos, 
                                   (255, 255, 0), 2, tipLength=0.3)
            
            # 绘制所有操作标记（点击类），带队列编号
            for marker in self.operation_markers:
                marker_type = marker['type']
                pos = marker['pos']
                qid = marker.get('queue_id')
                label_suffix = f" #{qid}" if qid else ""
                
                if marker_type == 'CLICK':
                    cv2.circle(frame_resized, pos, 10, (255, 0, 0), 2)
                    cv2.putText(frame_resized, f"CLICK{label_suffix}", (pos[0] + 12, pos[1] - 8),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                elif marker_type == 'DOUBLE':
                    cv2.circle(frame_resized, pos, 10, (255, 0, 255), 2)
                    cv2.circle(frame_resized, pos, 15, (255, 0, 255), 2)
                    cv2.putText(frame_resized, f"DOUBLE{label_suffix}", (pos[0] + 12, pos[1] - 8),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
                elif marker_type == 'LONG':
                    cv2.circle(frame_resized, pos, 12, (0, 165, 255), -1)
                    cv2.circle(frame_resized, pos, 12, (0, 100, 200), 2)
                    cv2.putText(frame_resized, f"LONG{label_suffix}", (pos[0] + 12, pos[1] - 8),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2)

            # 绘制队列和执行中的拖动任务（包含编号）
            pending_drags = []
            if self.current_command and self.current_command.get('type') == 'drag':
                pending_drags.append(self.current_command)
            pending_drags.extend([cmd for cmd in self.command_queue if cmd.get('type') == 'drag'])
            for cmd in pending_drags:
                start_pos = cmd.get('canvas_start')
                end_pos = cmd.get('canvas_end')
                qid = cmd.get('queue_id')
                if not start_pos or not end_pos:
                    continue
                cv2.circle(frame_resized, start_pos, 8, (0, 255, 0), 2)
                cv2.circle(frame_resized, start_pos, 3, (0, 255, 0), -1)
                cv2.putText(frame_resized, f"START #{qid}", (start_pos[0] + 12, start_pos[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                cv2.circle(frame_resized, end_pos, 8, (0, 0, 255), 2)
                cv2.circle(frame_resized, end_pos, 3, (0, 0, 255), -1)
                cv2.putText(frame_resized, f"END #{qid}", (end_pos[0] + 12, end_pos[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                cv2.arrowedLine(frame_resized, start_pos, end_pos, (255, 255, 0), 2, tipLength=0.3)
            
            # 转换为PIL Image
            img = Image.fromarray(frame_resized)
            imgtk = ImageTk.PhotoImage(image=img)
            
            # 更新Label的尺寸和位置
            self.video_label.config(image=imgtk, text='')
            self.video_label.imgtk = imgtk  # 保持引用
            
            # 更新Label的尺寸和位置，充满整个Canvas
            self.video_label.place(x=0, y=0, width=display_width, height=display_height)
            
            # 更新FPS
            self.fps_label.config(text=f"FPS: {self.camera.fps}")
            
            # 更新信息
            h_orig, w_orig = frame.shape[:2]
            crop_info = f" | 裁切" if self.crop_enabled and self.crop_rect else ""
            self.video_info_label.config(text=f"分辨率: {w_orig}x{h_orig}{crop_info} | 显示: {display_width}x{display_height}")
            
        except Exception as e:
            self.log_message(f"显示错误: {str(e)}")
        finally:
            # 继续定时更新
            if self.camera_running:
                self.root.after(50, self.on_new_frame)  # 每50ms检查一次
    
    def on_video_click(self, event):
        """视频画面点击事件 - 支持单击/双击/长按检测"""
        if not self.camera_running:
            return
        
        # 获取点击坐标（相对于Label，即显示图像）
        click_x = event.x
        click_y = event.y
        
        # 获取Label的实际尺寸
        label_width = self.video_label.winfo_width()
        label_height = self.video_label.winfo_height()
        
        if label_width <= 1 or label_height <= 1:
            return
        
        # 确保点击在有效范围内
        if click_x < 0 or click_y < 0 or click_x >= label_width or click_y >= label_height:
            return
        
        # 计算相对于原始帧的归一化坐标（考虑裁切、旋转、缩放）
        # 获取原始帧尺寸
        if self.paused_frame is not None:
            frame = self.paused_frame
        else:
            frame = self.camera.current_frame
        h_orig, w_orig = frame.shape[:2]
        
        # 获取Canvas尺寸
        canvas_width = self.video_canvas.winfo_width()
        canvas_height = self.video_canvas.winfo_height()
        
        # 获取裁切信息
        if self.crop_enabled and self.crop_rect:
            x1_c, y1_c, x2_c, y2_c = self.crop_rect
            crop_offset_x = x1_c
            crop_offset_y = y1_c
            w_cropped = x2_c - x1_c
            h_cropped = y2_c - y1_c
        else:
            crop_offset_x = 0
            crop_offset_y = 0
            w_cropped = w_orig
            h_cropped = h_orig
        
        # 旋转后的帧尺寸
        w_rotated = h_cropped
        h_rotated = w_cropped
        
        # 计算缩放比例（与on_new_frame中的逻辑一致）
        scale_w = canvas_width / w_rotated
        scale_h = canvas_height / h_rotated
        scale = max(scale_w, scale_h) * 1.001
        
        # 计算缩放后的尺寸
        display_width = int(w_rotated * scale + 0.5)
        display_height = int(h_rotated * scale + 0.5)
        
        if display_width < canvas_width:
            display_width = canvas_width
        if display_height < canvas_height:
            display_height = canvas_height
        
        # 计算居中裁切的偏移量
        center_crop_x = (display_width - canvas_width) // 2
        center_crop_y = (display_height - canvas_height) // 2
        
        # 反向转换：Label点击坐标 -> 旋转后缩放坐标系
        scaled_x = click_x + center_crop_x
        scaled_y = click_y + center_crop_y
        
        # 除以缩放比例，得到旋转后原始尺寸的坐标
        rotated_x = scaled_x / scale
        rotated_y = scaled_y / scale
        
        # 反向旋转得到裁切后坐标系
        cropped_x = w_cropped - 1 - rotated_y
        cropped_y = rotated_x
        
        # 映射回原始帧坐标
        orig_x = cropped_x + crop_offset_x
        orig_y = cropped_y + crop_offset_y
        
        # 计算归一化坐标（基于原始帧）
        norm_x = orig_x / w_orig
        norm_y = orig_y / h_orig
        
        # 限制范围
        norm_x = max(0.0, min(1.0, norm_x))
        norm_y = max(0.0, min(1.0, norm_y))
        
        # 获取工作区范围
        x1 = self.x1_var.get()
        y1 = self.y1_var.get()
        x2 = self.x2_var.get()
        y2 = self.y2_var.get()
        work_width = x2 - x1
        work_height = y2 - y1
        
        # Canvas位置直接映射到工作区（Canvas坐标系=工作区坐标系）
        # 获取Label尺寸
        label_width = self.video_label.winfo_width()
        label_height = self.video_label.winfo_height()
        
        # Canvas坐标映射到全局坐标（同向：Canvas向下=机械臂向下）
        abs_x = x1 + int((click_x / label_width) * work_width)
        abs_y = y1 + int((click_y / label_height) * work_height)
        
        # 限制在工作区范围内
        abs_x = max(x1, min(x2, abs_x))
        abs_y = max(y1, min(y2, abs_y))
        
        # 保存当前点击坐标（使用绝对坐标和Canvas坐标）
        self.current_click_x = abs_x
        self.current_click_y = abs_y
        self.current_click_canvas_x = click_x
        self.current_click_canvas_y = click_y
        self.mouse_down_pos = (click_x, click_y)
        
        # 手动框选模式：记录顶点
        if self.screen_detection_active and self.screen_detection_mode == 'manual':
            # 获取原始帧（未旋转、未缩放）
            if self.paused_frame is not None:
                frame = self.paused_frame
            else:
                frame = self.camera.current_frame
            h_orig, w_orig = frame.shape[:2]
            
            # 将Label上的像素坐标转换回原始帧的像素坐标
            # 1. 获取Canvas的实际尺寸（显示区域）
            canvas_width = self.video_canvas.winfo_width()
            canvas_height = self.video_canvas.winfo_height()
            
            # 2. 获取裁切偏移量（视频帧裁切，不是显示裁切）
            if hasattr(self, 'current_crop_offset_x'):
                crop_offset_x = self.current_crop_offset_x
                crop_offset_y = self.current_crop_offset_y
            else:
                crop_offset_x = 0
                crop_offset_y = 0
            
            # 3. 获取裁切后的帧尺寸（旋转前）
            if self.crop_enabled and self.crop_rect:
                x1_c, y1_c, x2_c, y2_c = self.crop_rect
                w_cropped = x2_c - x1_c
                h_cropped = y2_c - y1_c
            else:
                w_cropped = w_orig
                h_cropped = h_orig
            
            # 4. 旋转后的帧尺寸
            w_rotated = h_cropped
            h_rotated = w_cropped
            
            # 5. 计算缩放比例（与on_new_frame中的逻辑一致）
            scale_w = canvas_width / w_rotated
            scale_h = canvas_height / h_rotated
            scale = max(scale_w, scale_h) * 1.001
            
            # 6. 计算缩放后的尺寸
            display_width = int(w_rotated * scale + 0.5)
            display_height = int(h_rotated * scale + 0.5)
            
            # 确保显示尺寸至少等于Canvas尺寸
            if display_width < canvas_width:
                display_width = canvas_width
            if display_height < canvas_height:
                display_height = canvas_height
            
            # 7. 计算居中裁切的偏移量
            center_crop_x = (display_width - canvas_width) // 2
            center_crop_y = (display_height - canvas_height) // 2
            
            # 8. 反向转换：Label点击坐标 -> 旋转后缩放坐标系
            # 加上居中裁切偏移
            scaled_x = click_x + center_crop_x
            scaled_y = click_y + center_crop_y
            
            # 9. 除以缩放比例，得到旋转后原始尺寸的坐标
            rotated_x = scaled_x / scale
            rotated_y = scaled_y / scale
            
            # 10. 反向旋转（逆时针90度的反向 = 顺时针90度）
            # cv2.ROTATE_90_COUNTERCLOCKWISE: (x, y) -> (y, w-1-x)
            # 反向变换: (x', y') -> (w-1-y', x')
            # 原始尺寸: w_cropped x h_cropped
            # 旋转后尺寸: h_cropped x w_cropped
            cropped_x = w_cropped - 1 - rotated_y
            cropped_y = rotated_x
            
            # 11. 映射回原始帧坐标（加上裁切偏移）
            orig_x = int(cropped_x + crop_offset_x)
            orig_y = int(cropped_y + crop_offset_y)
            
            # 限制在有效范围内
            orig_x = max(0, min(w_orig - 1, orig_x))
            orig_y = max(0, min(h_orig - 1, orig_y))
            
            # 添加顶点
            self.polygon_points.append([orig_x, orig_y])
            self.log_message(f"[手动框选] 添加顶点 #{len(self.polygon_points)}: 原始({orig_x}, {orig_y}) <- 显示({click_x}, {click_y}) [缩放:{scale:.3f}, 居中偏移:({center_crop_x},{center_crop_y})]")
            return
        
        # 检查是否处于定位模式
        if self.locating_mode == 'top_left':
            # 直接使用绝对坐标
            self.x1_var.set(abs_x)
            self.y1_var.set(abs_y)
            self.log_message(f"[定位] 左上角坐标已设置: X={abs_x}, Y={abs_y}")
            self.locating_mode = None
            self.save_config()  # 自动保存配置
            return
        
        if self.locating_mode == 'bottom_right':
            # 直接使用绝对坐标
            self.x2_var.set(abs_x)
            self.y2_var.set(abs_y)
            self.log_message(f"[定位] 右下角坐标已设置: X={abs_x}, Y={abs_y}")
            self.locating_mode = None
            self.save_config()  # 自动保存配置
            return
        
        # 更新滑块
        self.x_var.set(abs_x)
        self.y_var.set(abs_y)
        
        self.log_message(f"[视频点击] 位置: ({click_x}, {click_y}) -> 绝对坐标: X={abs_x}, Y={abs_y}")
        
        # 多击检测逻辑
        self.mouse_click_count += 1
        
        if self.mouse_click_timer:
            self.root.after_cancel(self.mouse_click_timer)
        
        # 启动长按检测（鼠标按下时开始计时）
        self._start_long_press_detection(abs_x, abs_y)
        
        # 设置双击检测窗口(300ms内)
        # 注意：这里不执行点击操作，等待鼠标释放时再判断
        self.mouse_click_timer = self.root.after(
            int(self.mouse_double_click_threshold * 1000), 
            lambda: setattr(self, 'mouse_click_count', 0)
        )
    
    def _start_long_press_detection(self, abs_x, abs_y):
        """开始长按检测（需要鼠标按住不放）"""
        if self.mouse_long_press_timer:
            self.root.after_cancel(self.mouse_long_press_timer)
        
        def on_long_press_timeout():
            self.log_message(f"[长按] 长按 {self.mouse_long_press_threshold}s 以上，执行长按操作")
            if self.controller.connected:
                # 发送长按操作(延迟3000ms)
                canvas_pos = (self.current_click_canvas_x, self.current_click_canvas_y) if hasattr(self, 'current_click_canvas_x') else None
                self._send_mouse_event(abs_x, abs_y, ClickType.LONG, canvas_pos)
        
        self.mouse_long_press_timer = self.root.after(
            int(self.mouse_long_press_threshold * 1000), 
            on_long_press_timeout
        )
    
    def _send_mouse_event(self, abs_x, abs_y, click_type, canvas_pos=None):
        """发送鼠标事件（使用命令队列）
        
        Args:
            abs_x, abs_y: 绝对坐标
            click_type: 操作类型
            canvas_pos: Canvas位置用于显示标记
        """
        try:
            # 如果没有Canvas位置，尝试从当前点击坐标获取
            if canvas_pos is None:
                # 使用当前保存的点击位置
                canvas_pos = (100, 100)  # 默认位置
            
            # 添加到命令队列
            self.add_command_to_queue(
                command_type='click',
                click_type=click_type,
                abs_x=abs_x,
                abs_y=abs_y,
                canvas_pos=canvas_pos
            )
        except Exception as e:
            self.log_message(f"[错误] 鼠标事件发送失败: {str(e)}")
    
    def on_video_drag(self, event):
        """视频画面拖动事件 - 支持拖动检测"""
        if not self.camera_running:
            return
        
        # 手动框选模式下禁用拖动
        if self.screen_detection_active and self.screen_detection_mode == 'manual':
            return
        
        # 正常拖动操作：只在摄像头运行时处理
        # 取消长按计时器，因为开始拖动了
        if self.mouse_long_press_timer:
            self.root.after_cancel(self.mouse_long_press_timer)
            self.mouse_long_press_timer = None
        
        # 只有超过阈值才判定为拖动，避免误判点击
        drag_threshold = 5
        if self.mouse_down_pos:
            dx = abs(event.x - self.mouse_down_pos[0])
            dy = abs(event.y - self.mouse_down_pos[1])
            if dx < drag_threshold and dy < drag_threshold:
                return
        
        if not self.mouse_drag_active:
            self.mouse_drag_active = True
            # 记录拖动起点为按下时位置
            self.drag_start_pos = self.mouse_down_pos if self.mouse_down_pos else (event.x, event.y)
            self.drag_end_pos = None
        # 更新拖动终点
        self.drag_end_pos = (event.x, event.y)
    
    def on_video_release(self, event):
        """视频画面鼠标释放事件 - 支持拖动完成和长按取消"""
        if not self.camera_running:
            return
        
        # 取消长按计时器（如果有的话）- 因为鼠标已释放，不再是长按
        long_press_was_active = self.mouse_long_press_timer is not None
        if self.mouse_long_press_timer:
            self.root.after_cancel(self.mouse_long_press_timer)
            self.mouse_long_press_timer = None
        
        # 手动框选模式下不处理释放事件
        if self.screen_detection_active and self.screen_detection_mode == 'manual':
            return
        
        # 正常模式下的拖动完成处理
        if self.mouse_drag_active:
            self.mouse_drag_active = False
            
            # 获取拖动终点坐标
            label_width = self.video_label.winfo_width()
            label_height = self.video_label.winfo_height()
            
            if label_width <= 1 or label_height <= 1:
                return
            
            # 获取工作区范围
            x1 = self.x1_var.get()
            y1 = self.y1_var.get()
            x2 = self.x2_var.get()
            y2 = self.y2_var.get()
            work_width = x2 - x1
            work_height = y2 - y1
            
            # Canvas坐标映射到全局坐标（同向）
            end_abs_x = x1 + int((event.x / label_width) * work_width)
            end_abs_y = y1 + int((event.y / label_height) * work_height)
            
            # 限制在工作区范围内
            end_abs_x = max(x1, min(x2, end_abs_x))
            end_abs_y = max(y1, min(y2, end_abs_y))
            
            # 发送拖动指令
            if self.controller.connected and hasattr(self, 'current_click_x'):
                self.log_message(f"[拖动调试] Canvas起点: {self.drag_start_pos}, Canvas终点: ({event.x}, {event.y})")
                self.log_message(f"[拖动] 从 ({self.current_click_x}, {self.current_click_y}) 到 ({end_abs_x}, {end_abs_y})")
                
                # 添加拖动命令到队列，包含Canvas坐标和Label尺寸
                self.add_command_to_queue(
                    command_type='drag',
                    start_x=self.current_click_x,
                    start_y=self.current_click_y,
                    end_x=end_abs_x,
                    end_y=end_abs_y,
                    canvas_start=self.drag_start_pos,
                    canvas_end=self.drag_end_pos,
                    label_width=label_width,
                    label_height=label_height
                )
            return  # 拖动完成，不执行点击
        
        # 如果长按计时器被取消了，说明是快速点击/释放
        if long_press_was_active and hasattr(self, 'current_click_x'):
            # 判断点击类型
            if self.mouse_click_count == 1:
                # 等待双击检测窗口结束后执行单击
                def execute_single_click():
                    if self.mouse_click_count == 1:
                        self.log_message(f"[单击] 执行单击操作")
                        if self.controller.connected:
                            canvas_pos = (self.current_click_canvas_x, self.current_click_canvas_y) if hasattr(self, 'current_click_canvas_x') else None
                            self._send_mouse_event(self.current_click_x, self.current_click_y, ClickType.CLICK, canvas_pos)
                    self.mouse_click_count = 0
                
                if self.mouse_click_timer:
                    self.root.after_cancel(self.mouse_click_timer)
                self.mouse_click_timer = self.root.after(
                    int(self.mouse_double_click_threshold * 1000),
                    execute_single_click
                )
            elif self.mouse_click_count == 2:
                # 双击
                if self.mouse_click_timer:
                    self.root.after_cancel(self.mouse_click_timer)
                    self.mouse_click_timer = None
                self.log_message(f"[双击] 执行双击操作")
                if self.controller.connected:
                    canvas_pos = (self.current_click_canvas_x, self.current_click_canvas_y) if hasattr(self, 'current_click_canvas_x') else None
                    self._send_mouse_event(self.current_click_x, self.current_click_y, ClickType.DOUBLE, canvas_pos)
                self.mouse_click_count = 0
            elif self.mouse_click_count >= 3:
                # 多击
                if self.mouse_click_timer:
                    self.root.after_cancel(self.mouse_click_timer)
                    self.mouse_click_timer = None
                self.log_message(f"[多击] 检测到 {self.mouse_click_count} 次点击")
                self.mouse_click_count = 0
    
    def on_video_motion(self, event):
        """鼠标移动事件 - 实时计算并显示绝对坐标"""
        if not self.camera_running:
            return
        
        # 获取鼠标相对于Label的位置
        mouse_x = event.x
        mouse_y = event.y
        
        # 获取Label的实际尺寸
        label_width = self.video_label.winfo_width()
        label_height = self.video_label.winfo_height()
        
        if label_width <= 1 or label_height <= 1:
            return
        
        # 确保鼠标在有效范围内
        if mouse_x < 0 or mouse_y < 0 or mouse_x >= label_width or mouse_y >= label_height:
            return
        
        # Canvas坐标直接映射到工作区（忽略视频旋转，Canvas本身就是工作区视图）
        # Canvas左上角(0,0) = 工作区坐标(0,0)
        # Canvas右下角(width,height) = 工作区坐标(work_width, work_height)
        
        # 获取当前工作区域坐标
        try:
            x1 = self.x1_var.get()
            y1 = self.y1_var.get()
            x2 = self.x2_var.get()
            y2 = self.y2_var.get()
            
            # Canvas坐标映射到工作区域
            work_width = x2 - x1
            work_height = y2 - y1
            
            # 工作区内相对坐标（以左上角为原点）
            # Canvas位置直接对应工作区相对坐标
            work_relative_x = int((mouse_x / label_width) * work_width)
            work_relative_y = int((mouse_y / label_height) * work_height)
            
            # 全局坐标（机械臂坐标系，Y同向）
            global_x = x1 + work_relative_x
            global_y = y1 + work_relative_y
            
            # 获取摄像头实际分辨率
            camera_width = self.camera.width
            camera_height = self.camera.height
            
            # 计算归一化坐标用于显示摄像头像素位置（考虑90度旋转）
            norm_x = 1.0 - (mouse_y / label_height)
            norm_y = mouse_x / label_width
            camera_pixel_x = int(norm_y * camera_width)
            camera_pixel_y = int((1.0 - norm_x) * camera_height)
            
            # 裁切信息
            crop_info = ""
            if self.crop_enabled and self.crop_rect:
                x1_c, y1_c, x2_c, y2_c = self.crop_rect
                crop_info = f"\n裁切区域: ({x1_c}, {y1_c}) -> ({x2_c}, {y2_c})"
            
            # 更新坐标映射分析区域
            info_text = (
                f"🖱️ 视频坐标系:\n"
                f"显示位置: ({mouse_x}, {mouse_y}) / {label_width}x{label_height}\n"
                f"摄像头像素: ({camera_pixel_x}, {camera_pixel_y}) / {camera_width}x{camera_height}{crop_info}\n"
                f"\n🤖 机械臂坐标:\n"
                f"全局坐标: X={global_x}, Y={global_y}\n"
                f"工作区坐标: X={work_relative_x}, Y={work_relative_y} (区域大小: {work_width}×{work_height})\n"
                f"工作区原点: X={x1}, Y={y1}"
            )
            
            self.ratio_info_label.config(text=info_text)
        except Exception as e:
            # 若获取失败则不更新
            pass
    
    def add_operation_marker(self, marker_type, pos, queue_id=None):
        """添加操作标记"""
        # 避免重复添加相同队列的同类标记
        exists = any(m.get('queue_id') == queue_id and m.get('type') == marker_type for m in self.operation_markers)
        if exists:
            return
        self.operation_markers.append({
            'type': marker_type,
            'pos': pos,
            'queue_id': queue_id,
            'timestamp': time.time()
        })
    
    def clear_operation_markers(self, queue_id=None):
        """清除操作标记，支持按队列ID清除"""
        if queue_id is None:
            self.operation_markers.clear()
        else:
            self.operation_markers = [m for m in self.operation_markers if m.get('queue_id') != queue_id]
        # 仅在清除当前命令时才移除拖动标记
        if queue_id is None or (self.current_command and self.current_command.get('queue_id') == queue_id):
            self.drag_start_pos = None
            self.drag_end_pos = None
    
    def add_command_to_queue(self, command_type, **kwargs):
        """添加命令到队列
        
        Args:
            command_type: 'click' or 'drag'
            **kwargs: 命令参数
                对于click: click_type, abs_x, abs_y, canvas_pos
                对于drag: start_x, start_y, end_x, end_y, canvas_start, canvas_end
        """
        queue_id = self.queue_seq
        self.queue_seq += 1
        command = {
            'type': command_type,
            'queue_id': queue_id,
            'timestamp': time.time()
        }
        command.update(kwargs)
        
        self.command_queue.append(command)
        # 为点击类命令添加标记（排队即显示）
        if command_type == 'click' and 'canvas_pos' in command:
            self.add_operation_marker(command['click_type'].name if hasattr(command['click_type'], 'name') else 'CLICK', command['canvas_pos'], queue_id=queue_id)
        
        self.log_message(f"[队列] 添加命令: {command_type} (#{queue_id}), 队列长度: {len(self.command_queue)}")
        
        # 如果没有正在执行的命令，立即执行
        if not self.waiting_response:
            self.execute_next_command()
    
    def execute_next_command(self):
        """执行队列中的下一个命令"""
        if not self.command_queue or self.waiting_response:
            return
        
        self.current_command = self.command_queue.pop(0)
        self.waiting_response = True
        
        cmd = self.current_command
        command_type = cmd['type']
        queue_id = cmd.get('queue_id')
        
        self.log_message(f"[队列] 执行命令: {command_type} (#{queue_id}), 剩余: {len(self.command_queue)}")
        
        try:
            if command_type == 'click':
                click_type = cmd['click_type']
                abs_x = cmd['abs_x']
                abs_y = cmd['abs_y']
                canvas_pos = cmd['canvas_pos']
                
                # 确保标记存在（若未在入队时生成）
                if click_type == ClickType.CLICK:
                    self.add_operation_marker('CLICK', canvas_pos, queue_id=queue_id)
                elif click_type == ClickType.DOUBLE:
                    self.add_operation_marker('DOUBLE', canvas_pos, queue_id=queue_id)
                elif click_type == ClickType.LONG:
                    self.add_operation_marker('LONG', canvas_pos, queue_id=queue_id)
                
                # 发送命令
                work_x1 = self.x1_var.get()
                work_y1 = self.y1_var.get()
                work_x2 = self.x2_var.get()
                work_y2 = self.y2_var.get()
                
                if click_type == ClickType.CLICK:
                    success, msg = self.controller.send_move_click(abs_x, abs_y, work_x1, work_y1, work_x2, work_y2, click_type, speed=100)
                elif click_type == ClickType.DOUBLE:
                    success, msg = self.controller.send_move_click(abs_x, abs_y, work_x1, work_y1, work_x2, work_y2, click_type, speed=100)
                elif click_type == ClickType.LONG:
                    success, msg = self.controller.send_move_click(abs_x, abs_y, work_x1, work_y1, work_x2, work_y2, click_type, delay_ms=3000)
                
                self.log_message(f"[{click_type.name}] {msg}")
                
            elif command_type == 'drag':
                # 获取拖动参数
                start_x = cmd['start_x']
                start_y = cmd['start_y']
                end_x = cmd['end_x']
                end_y = cmd['end_y']
                canvas_start = cmd['canvas_start']
                canvas_end = cmd['canvas_end']
                label_width = cmd.get('label_width', 1)
                label_height = cmd.get('label_height', 1)
                
                # 设置拖动标记
                self.drag_start_pos = canvas_start
                self.drag_end_pos = canvas_end
                self.drag_queue_id = queue_id
                
                # 获取工作区范围
                work_x1 = self.x1_var.get()
                work_y1 = self.y1_var.get()
                work_x2 = self.x2_var.get()
                work_y2 = self.y2_var.get()
                
                # 发送拖动命令（传递工作区参数）
                success, msg = self.controller.send_drag(start_x, start_y, end_x, end_y, work_x1, work_y1, work_x2, work_y2)
                self.log_message(f"[拖动] {msg}")
            
            # 启动超时计时器
            if self.command_timer:
                self.root.after_cancel(self.command_timer)
            self.command_timer = self.root.after(
                int(self.command_timeout * 1000),
                self.on_command_timeout
            )
            
        except Exception as e:
            self.log_message(f"[错误] 命令执行失败: {str(e)}")
            self.on_command_complete()
    
    def on_command_complete(self):
        """命令执行完成"""
        self.waiting_response = False
        finished_cmd = self.current_command
        finished_queue_id = finished_cmd.get('queue_id') if finished_cmd else None
        self.current_command = None
        
        # 取消超时计时器
        if self.command_timer:
            self.root.after_cancel(self.command_timer)
            self.command_timer = None
        
        # 清除当前命令的标记
        self.clear_operation_markers(queue_id=finished_queue_id)
        if finished_cmd and finished_cmd.get('type') == 'drag':
            self.drag_queue_id = None
        
        # 执行下一个命令
        if self.command_queue:
            self.root.after(100, self.execute_next_command)
        else:
            # 队列空时重置编号
            self.queue_seq = 1
    
    def on_command_timeout(self):
        """命令超时处理"""
        self.log_message(f"[警告] 命令执行超时")
        self.on_command_complete()
    
    def clear_drag_markers(self):
        """清除拖动起点和终点标记"""
        self.drag_start_pos = None
        self.drag_end_pos = None
    
    def update_work_area(self):
        """保存工作区域坐标"""
        try:
            x1 = self.x1_var.get()
            y1 = self.y1_var.get()
            x2 = self.x2_var.get()
            y2 = self.y2_var.get()
            
            # 验证坐标有效性
            if x1 >= x2 or y1 >= y2:
                messagebox.showerror("错误", "坐标设置无效：左上角应小于右下角")
                return
            
            # 不再需要更新控制器中的绝对坐标
            
            # 保存配置
            self.save_config()
            
            self.log_message(f"[坐标保存] 绝对坐标 - 左上角: X={x1}, Y={y1}, 右下角: X={x2}, Y={y2}")
            messagebox.showinfo("成功", f"工作区域已保存并持久化\n左上角: X={x1}, Y={y1}\n右下角: X={x2}, Y={y2}")
        except Exception as e:
            messagebox.showerror("错误", f"坐标设置错误: {str(e)}")
    
    def test_slider_position(self):
        """测试移动到滑块位置"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return
        
        # 滑块直接使用绝对坐标，测试整个机械臂行程
        abs_x = self.x_var.get()
        abs_y = self.y_var.get()
        
        # 限制在有效范围内
        target_x = max(0, min(3900, abs_x))
        target_y = max(0, min(6300, abs_y))
        
        # 直接发送简单的move命令
        try:
            cmd = f"move,{target_x},{target_y}\r\n"
            if self.controller.bridge_mode and self.controller.control_port:
                self.controller.control_port.write(cmd.encode('ascii'))
                if self.controller.callback:
                    self.controller.callback(f"[GUI->P2] move({target_x},{target_y})")
            else:
                self.controller.serial.write(cmd.encode('ascii'))
                if self.controller.callback:
                    self.controller.callback(f"TX: move({target_x},{target_y})")
            
            self.log_message(f"[测试移动] 机械臂绝对坐标: X={target_x}, Y={target_y}")
        except Exception as e:
            messagebox.showerror("错误", f"发送失败: {str(e)}")
    
    def locate_top_left_from_slider(self):
        """从滑块定位左上角坐标"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return

        # 滑块直接使用绝对坐标
        abs_x = self.x_var.get()
        abs_y = self.y_var.get()
        
        # 保存绝对坐标
        self.x1_var.set(abs_x)
        self.y1_var.set(abs_y)
        
        self.save_config()
        self.log_message(f"[定位左上] 绝对坐标: X={abs_x}, Y={abs_y}")
        messagebox.showinfo("成功", f"左上角已保存\n绝对坐标: X={abs_x}, Y={abs_y}")
    
    def locate_bottom_right_from_slider(self):
        """从滑块定位右下角坐标"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return

        # 滑块直接使用绝对坐标
        abs_x = self.x_var.get()
        abs_y = self.y_var.get()
        
        # 保存绝对坐标
        self.x2_var.set(abs_x)
        self.y2_var.set(abs_y)
        
        self.save_config()
        self.log_message(f"[定位右下] 绝对坐标: X={abs_x}, Y={abs_y}")
        messagebox.showinfo("成功", f"右下角已保存\n绝对坐标: X={abs_x}, Y={abs_y}")
    
    def update_ratio_info(self):
        """更新坐标映射比例信息"""
        try:
            x1 = self.x1_var.get()
            y1 = self.y1_var.get()
            x2 = self.x2_var.get()
            y2 = self.y2_var.get()
            
            # 计算工作区域尺寸（绝对坐标）
            work_width = x2 - x1
            work_height = y2 - y1
            
            if work_width <= 0 or work_height <= 0:
                self.ratio_info_label.config(text="请设置有效的坐标范围")
                return
            
            # 使用摄像头实际分辨率
            camera_width = self.camera.width
            camera_height = self.camera.height
            
            # 计算映射比例（绝对坐标到像素）
            x_ratio = work_width / camera_width
            y_ratio = work_height / camera_height
            
            info_text = (
                f"📐 绝对坐标配置:\n"
                f"左上角: X={x1}, Y={y1}\n"
                f"右下角: X={x2}, Y={y2}\n"
                f"工作区域: {work_width} × {work_height}\n"
                f"(最大范围: X=3900, Y=6300)\n"
                f"\n📷 视频坐标映射:\n"
                f"摄像头分辨率: {camera_width} × {camera_height} 像素\n"
                f"映射比例: {x_ratio:.6f} × {y_ratio:.6f}"
            )
            
            self.ratio_info_label.config(text=info_text)
        except Exception as e:
            self.ratio_info_label.config(text=f"计算错误: {str(e)}")
    
    def start_screen_detection(self):
        """启动屏幕检测模式（已废弃，保留兼容性）"""
        self.start_manual_screen_detection()
    
    def auto_detect_screen(self):
        """自动识别屏幕区域"""
        if not self.camera_running:
            messagebox.showwarning("警告", "请先启动摄像头")
            return
        
        try:
            # 获取当前帧
            frame = self.camera.current_frame.copy()
            
            # 转换为灰度图
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 高斯模糊
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # Canny边缘检测
            edges = cv2.Canny(blurred, 50, 150)
            
            # 查找轮廓
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                messagebox.showwarning("检测失败", "未能检测到屏幕区域，请使用手动框选")
                return
            
            # 找到最大的矩形轮廓
            max_contour = max(contours, key=cv2.contourArea)
            
            # 计算最小外接矩形
            rect = cv2.minAreaRect(max_contour)
            box = cv2.boxPoints(rect)
            box = np.int0(box)
            
            # 保存检测到的屏幕区域多边形（4个顶点）
            self.polygon_points = box.tolist()
            self.screen_detection_mode = 'auto'
            
            # 创建蒙版用于显示
            h, w = frame.shape[:2]
            self.screen_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(self.screen_mask, [box], 255)
            
            # 计算归一化坐标（使用外接矩形的左上和右下角）
            x_coords = [p[0] for p in box]
            y_coords = [p[1] for p in box]
            
            # 旋转后的视频坐标需要转换
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
            
            # 转换为归一化坐标（考虑90度旋转）
            norm_left = min_y / w
            norm_right = max_y / w
            norm_top = min_x / h
            norm_bottom = max_x / h
            
            # 计算归一化坐标（考虑Y轴翻转）
            screen_x1 = 1.0 - norm_bottom
            screen_y1 = norm_left
            screen_x2 = 1.0 - norm_top
            screen_y2 = norm_right
            
            # 更新坐标
            self.x1_var.set(screen_x1)
            self.y1_var.set(screen_y1)
            self.x2_var.set(screen_x2)
            self.y2_var.set(screen_y2)
            
            self.log_message(f"[自动识别] 屏幕区域: 左上({screen_x1:.5f}, {screen_y1:.5f}), 右下({screen_x2:.5f}, {screen_y2:.5f})")
            messagebox.showinfo("识别成功", f"已自动识别屏幕区域\n左上角: ({screen_x1:.5f}, {screen_y1:.5f})\n右下角: ({screen_x2:.5f}, {screen_y2:.5f})")
            
        except Exception as e:
            self.log_message(f"[错误] 自动识别失败: {str(e)}")
            messagebox.showerror("识别失败", f"自动识别出错: {str(e)}\n请使用手动框选")
    
    def start_manual_screen_detection(self):
        """启动手动框选屏幕模式"""
        if not self.camera_running:
            messagebox.showwarning("警告", "请先启动摄像头")
            return
        
        # 保存当前帧作为暂停画面
        if self.camera.current_frame is not None:
            self.paused_frame = self.camera.current_frame.copy()
        
        # 重置状态
        self.screen_detection_mode = 'manual'
        self.screen_detection_active = True
        self.polygon_points = []
        self.screen_mask = None
        
        # 切换光标为十字
        self.video_label.config(cursor='crosshair')
        
        self.log_message("[手动框选] 已启动 - 请在视频中依次点击屏幕区域的各个顶点")
        messagebox.showinfo("手动框选", "请在视频画面中依次点击屏幕区域的各个顶点\n至少需要3个点\n完成后请点击\"确认框选\"按钮")
    
    def finish_manual_detection(self):
        """完成手动框选"""
        if len(self.polygon_points) < 3:
            messagebox.showwarning("警告", "至少需要3个顶点才能完成框选")
            return
        
        # 恢复视频流
        self.paused_frame = None
        
        try:
            # 获取当前帧尺寸
            frame = self.camera.current_frame
            h, w = frame.shape[:2]
            
            # 创建蒙版
            self.screen_mask = np.zeros((h, w), dtype=np.uint8)
            points_array = np.array(self.polygon_points, dtype=np.int32)
            cv2.fillPoly(self.screen_mask, [points_array], 255)
            
            # 计算边界框
            x_coords = [p[0] for p in self.polygon_points]
            y_coords = [p[1] for p in self.polygon_points]
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
            
            # 转换为归一化坐标（考虑90度旋转）
            norm_left = min_y / w
            norm_right = max_y / w
            norm_top = min_x / h
            norm_bottom = max_x / h
            
            # 计算归一化坐标（考虑Y轴翻转）
            screen_x1 = 1.0 - norm_bottom
            screen_y1 = norm_left
            screen_x2 = 1.0 - norm_top
            screen_y2 = norm_right
            
            # 更新坐标
            self.x1_var.set(screen_x1)
            self.y1_var.set(screen_y1)
            self.x2_var.set(screen_x2)
            self.y2_var.set(screen_y2)
            
            # 关闭框选模式
            self.screen_detection_active = False
            
            # 恢复光标
            self.video_label.config(cursor='circle')
            
            self.log_message(f"[手动框选完成] 屏幕区域({len(self.polygon_points)}个顶点): 左上({screen_x1:.5f}, {screen_y1:.5f}), 右下({screen_x2:.5f}, {screen_y2:.5f})")
            messagebox.showinfo("框选完成", f"已完成手动框选\n顶点数: {len(self.polygon_points)}\n左上角: ({screen_x1:.5f}, {screen_y1:.5f})\n右下角: ({screen_x2:.5f}, {screen_y2:.5f})")
            
        except Exception as e:
            self.log_message(f"[错误] 手动框选完成失败: {str(e)}")
            messagebox.showerror("错误", f"框选处理出错: {str(e)}")
    
    def clear_screen_detection(self):
        """清除屏幕检测"""
        self.screen_detection_mode = None
        self.screen_detection_active = False
        self.polygon_points = []
        self.screen_mask = None
        
        # 恢复视频流（清除暂停帧）
        self.paused_frame = None
        
        # 恢复光标
        self.video_label.config(cursor='circle')
        
        self.log_message("[清除] 已清除屏幕检测区域")
    
    def toggle_crop(self):
        """切换裁切模式"""
        if not self.camera_running:
            messagebox.showwarning("警告", "请先启动摄像头")
            return
        
        if not self.crop_enabled:
            # 启用裁切
            if len(self.polygon_points) < 3:
                messagebox.showwarning("警告", "请先完成屏幕区域框选")
                return
            
            # 计算多边形的边界框作为裁切区域
            x_coords = [p[0] for p in self.polygon_points]
            y_coords = [p[1] for p in self.polygon_points]
            x1, x2 = min(x_coords), max(x_coords)
            y1, y2 = min(y_coords), max(y_coords)
            
            # 确保坐标在有效范围内
            frame = self.camera.current_frame
            h, w = frame.shape[:2]
            x1 = max(0, min(x1, w - 1))
            x2 = max(0, min(x2, w))
            y1 = max(0, min(y1, h - 1))
            y2 = max(0, min(y2, h))
            
            self.crop_rect = (x1, y1, x2, y2)
            self.crop_enabled = True
            self.crop_btn.config(text="取消裁切")
            self.log_message(f"[裁切] 已启用裁切: ({x1}, {y1}) -> ({x2}, {y2})")
            
            # 触发容器重新调整大小以适应裁切后的比例
            if hasattr(self, 'video_outer_wrapper'):
                self.video_outer_wrapper.event_generate('<Configure>')
            
            self.save_config()  # 保存配置
        else:
            # 禁用裁切
            self.crop_enabled = False
            self.crop_rect = None
            self.crop_btn.config(text="裁切画面")
            self.log_message("[裁切] 已取消裁切")
            
            # 触发容器重新调整大小以恢复原始比例
            if hasattr(self, 'video_outer_wrapper'):
                self.video_outer_wrapper.event_generate('<Configure>')
            
            self.save_config()  # 保存配置
    
    def toggle_connection(self):
        """连接/断开串口"""
        if not self.controller.connected:
            port = self.port_var.get()
            baudrate = int(self.baud_var.get())
            mode = self.mode_var.get()
            
            if not port:
                messagebox.showerror("错误", "请选择端口1")
                return
            
            # 桥接模式需要两个端口
            if mode == "bridge":
                port2 = self.port2_var.get()
                if not port2:
                    messagebox.showerror("错误", "桥接模式需要选择端口2")
                    return
                if port == port2:
                    messagebox.showerror("错误", "两个端口不能相同")
                    return
                
                success, msg = self.controller.connect(port, baudrate, bridge_mode=True, port2=port2)
            else:
                # 直连模式
                success, msg = self.controller.connect(port, baudrate, bridge_mode=False)
            
            if success:
                self.status_label.config(text="已连接", foreground="green")
                self.conn_btn.config(text="断开")
                self.log_message(msg)
                self.log_message(f"[调试] 模式: {'桥接' if self.mode_var.get() == 'bridge' else '直连'}")
                self.log_message(f"[调试] 端口1: {port}, 波特率: {baudrate}")
                if self.mode_var.get() == 'bridge':
                    self.log_message(f"[调试] 端口2: {self.port2_var.get()}")
                self.start_reader()
            else:
                messagebox.showerror("连接失败", msg)
        else:
            self.stop_reader()
            self.controller.disconnect()
            self.status_label.config(text="未连接", foreground="red")
            self.conn_btn.config(text="连接")
            self.log_message("已断开连接")
    
    def start_reader(self):
        """启动读取线程"""
        self.running = True
        self.reader_thread = threading.Thread(target=self.reader_loop, daemon=True)
        self.reader_thread.start()
    
    def stop_reader(self):
        """停止读取线程"""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=1)
    
    def reader_loop(self):
        """读取循环"""
        while self.running:
            responses = self.controller.read_response()
            # 处理响应
            for response in responses:
                # 检查是否是命令完成响应: RX: READY
                if 'READY' in response:
                    # 在主线程中调用完成处理
                    self.root.after(0, self.on_command_complete)
                elif 'ERROR' in response.upper() or 'ERR' in response.upper():
                    # 错误响应
                    self.root.after(0, lambda r=response: self.log_message(f"[错误] 设备返回错误: {r}"))
                    self.root.after(0, self.on_command_complete)
            time.sleep(0.01)
    
    def execute_command(self, cmd_type):
        """执行命令"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return
        
        x = self.x_var.get()
        y = self.y_var.get()
        
        # 获取工作区域参数
        work_x1 = self.x1_var.get()
        work_y1 = self.y1_var.get()
        work_x2 = self.x2_var.get()
        work_y2 = self.y2_var.get()
        
        success, msg = self.controller.send_move_click(x, y, work_x1, work_y1, work_x2, work_y2, cmd_type)
        if not success:
            messagebox.showerror("错误", msg)

    def reset_motor(self):
        """发送复位指令"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return

        success, msg = self.controller.send_reset()
        if success:
            self.log_message(msg)
        else:
            messagebox.showerror("错误", msg)

    def photo_mode_move(self):
        """拍照模式：固定移动到1轴3300位置"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return

        success, msg = self.controller.send_move(1, 3300)
        if success:
            self.log_message("[拍照模式] 已发送 move,1,3300")
        else:
            messagebox.showerror("错误", msg)
    
    def move_axis(self, axis, position):
        """移动单个轴"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return
        
        success, msg = self.controller.send_move(axis, position)
        if not success:
            messagebox.showerror("错误", msg)
    
    def send_manual_command(self):
        """发送手动输入的指令"""
        cmd = self.manual_cmd_entry.get().strip()
        if not cmd:
            return
        
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return
        
        try:
            # 发送指令（自动添加换行符）
            if not cmd.endswith('\n'):
                cmd_to_send = cmd + '\r\n'
            else:
                cmd_to_send = cmd
            
            # 根据模式选择端口
            if self.controller.bridge_mode and self.controller.control_port:
                self.controller.control_port.write(cmd_to_send.encode('ascii'))
                self.log_message(f"[手动->P2] {cmd}")
            else:
                self.controller.serial.write(cmd_to_send.encode('ascii'))
                self.log_message(f"[手动TX] {cmd}")
            
            # 添加到历史记录
            if cmd not in self.cmd_history:
                self.cmd_history.insert(0, cmd)
                if len(self.cmd_history) > 20:  # 最多保留20条
                    self.cmd_history.pop()
                self.cmd_history_combo['values'] = self.cmd_history
            
            # 清空输入框
            self.manual_cmd_entry.delete(0, tk.END)
            
        except Exception as e:
            messagebox.showerror("错误", f"发送失败: {str(e)}")
    
    def send_quick_command(self, cmd):
        """发送快捷指令"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return
        
        try:
            cmd_to_send = cmd + '\r\n'
            
            if self.controller.bridge_mode and self.controller.control_port:
                self.controller.control_port.write(cmd_to_send.encode('ascii'))
                self.log_message(f"[快捷->P2] {cmd}")
            else:
                self.controller.serial.write(cmd_to_send.encode('ascii'))
                self.log_message(f"[快捷TX] {cmd}")
                
        except Exception as e:
            messagebox.showerror("错误", f"发送失败: {str(e)}")
    
    def on_history_select(self, event=None):
        """从历史记录中选择指令"""
        selected = self.cmd_history_var.get()
        if selected:
            self.manual_cmd_entry.delete(0, tk.END)
            self.manual_cmd_entry.insert(0, selected)
    
    def set_position(self, x, y):
        """设置位置"""
        self.x_var.set(x)
        self.y_var.set(y)
    
    def log_message(self, msg):
        """记录日志"""
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)
    
    def log_message_async(self, msg):
        """线程安全日志"""
        self.root.after(0, lambda: self.log_message(msg))
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)

    def format_model_response(self, resp_text):
        """格式化模型响应，优先展示内容，再附原始JSON"""
        try:
            data = json.loads(resp_text)
        except Exception:
            return resp_text.strip()

        content_segments = []
        try:
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content")
                if isinstance(content, str):
                    content_segments.append(content.strip())
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_val = item.get("text")
                            if text_val:
                                content_segments.append(str(text_val).strip())
        except Exception:
            pass

        pretty_json = json.dumps(data, ensure_ascii=False, indent=2)
        parts = []
        if content_segments:
            parts.append("模型内容:\n" + "\n\n".join(content_segments))
        parts.append("原始JSON:\n" + pretty_json)
        return "\n\n".join(parts)

    def run_model_inference(self, prompt_text, on_result=None, on_done=None):
        """将文本+当前画面发送到模型"""
        prompt = (prompt_text or "").strip()
        if not prompt:
            messagebox.showwarning("警告", "请输入发送内容")
            if on_done:
                on_done()
            return
        frame_source = None
        if self.paused_frame is not None:
            frame_source = self.paused_frame
        elif self.camera is not None and self.camera.current_frame is not None:
            frame_source = self.camera.current_frame
        if frame_source is None:
            messagebox.showwarning("警告", "当前没有可用的图像帧")
            if on_done:
                on_done()
            return
        try:
            frame = frame_source.copy()
        except Exception:
            frame = np.array(frame_source)
        if self.crop_enabled and self.crop_rect:
            x1_c, y1_c, x2_c, y2_c = self.crop_rect
            frame = frame[y1_c:y2_c, x1_c:x2_c]
        h_before, w_before = frame.shape[:2]
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        h_after, w_after = frame.shape[:2]
        success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not success:
            messagebox.showerror("错误", "图像编码失败，无法推理")
            if on_done:
                on_done()
            return
        img_bytes = buffer.tobytes()
        img_b64 = base64.b64encode(img_bytes).decode("ascii")
        url = self.model_base_url.strip()
        if not url:
            messagebox.showwarning("警告", "请先填写模型 Base URL")
            if on_done:
                on_done()
            return
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}",
                                "detail": "auto"
                            }
                        }
                    ]
                }
            ],
            "stream": False
        }
        payload_for_log = json.loads(json.dumps(payload))
        try:
            payload_for_log["messages"][0]["content"][1]["image_url"]["url"] = "[base64已省略]"
        except Exception:
            pass
        headers = {"Content-Type": "application/json"}
        if self.model_api_key:
            headers["Authorization"] = f"Bearer {self.model_api_key}"
        def log_ui(text):
            self.root.after(0, lambda: self.log_message(text))
        def worker():
            log_ui(f"[模型推理] 准备发送: url={url}, model={self.model_name}, prompt_len={len(prompt)}, 图像={w_after}x{h_after} (裁剪前 {w_before}x{h_before}), bytes={len(img_bytes)}")
            log_ui(f"[模型推理] payload={json.dumps(payload_for_log, ensure_ascii=False)}")
            resp_text = ""
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                resp_text = resp.text
                fmt = self.format_model_response(resp_text)
                log_ui(f"[模型推理] 响应 {resp.status_code}\n{fmt}")
            except Exception as e:
                resp_text = f"请求失败: {str(e)}"
                log_ui(f"[模型推理] 请求失败: {str(e)}")
            if on_result:
                self.root.after(0, lambda: on_result(self.format_model_response(resp_text)))
            if on_done:
                self.root.after(0, on_done)
        threading.Thread(target=worker, daemon=True).start()

    def open_model_config_dialog(self):
        """打开模型配置弹窗"""
        dialog = tk.Toplevel(self.root)
        dialog.title("模型配置")
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.geometry("520x520")
        ttk.Label(dialog, text="API Key:").grid(row=0, column=0, padx=8, pady=8, sticky=tk.W)
        api_var = tk.StringVar(value=self.model_api_key)
        api_entry = ttk.Entry(dialog, textvariable=api_var, width=40, show="*")
        api_entry.grid(row=0, column=1, padx=8, pady=8, sticky=tk.W)
        ttk.Label(dialog, text="Base URL:").grid(row=1, column=0, padx=8, pady=8, sticky=tk.W)
        url_var = tk.StringVar(value=self.model_base_url)
        ttk.Entry(dialog, textvariable=url_var, width=40).grid(row=1, column=1, padx=8, pady=8, sticky=tk.W)
        ttk.Label(dialog, text="模型名称:").grid(row=2, column=0, padx=8, pady=8, sticky=tk.W)
        model_var = tk.StringVar(value=self.model_name)
        ttk.Entry(dialog, textvariable=model_var, width=20).grid(row=2, column=1, padx=8, pady=8, sticky=tk.W)
        ttk.Label(dialog, text="发送内容:").grid(row=3, column=0, padx=8, pady=(12, 4), sticky=tk.NW)
        send_text = scrolledtext.ScrolledText(dialog, width=48, height=4)
        send_text.grid(row=4, column=0, columnspan=2, padx=8, pady=(0, 8), sticky=tk.EW)
        ttk.Label(dialog, text="接收内容:").grid(row=6, column=0, padx=8, pady=(12, 4), sticky=tk.NW)
        recv_text = scrolledtext.ScrolledText(dialog, width=48, height=8, state=tk.DISABLED)
        recv_text.grid(row=7, column=0, columnspan=2, padx=8, pady=(0, 8), sticky=tk.EW)
        dialog.columnconfigure(1, weight=1)
        def update_recv(content):
            recv_text.config(state=tk.NORMAL)
            recv_text.delete("1.0", tk.END)
            recv_text.insert(tk.END, content)
            recv_text.config(state=tk.DISABLED)
        def do_infer():
            send_content = send_text.get("1.0", tk.END)
            update_recv("推理中...")
            infer_btn.config(state=tk.DISABLED)
            self.run_model_inference(
                send_content,
                on_result=lambda text: update_recv(text),
                on_done=lambda: infer_btn.config(state=tk.NORMAL)
            )
        infer_btn = ttk.Button(dialog, text="推理", command=do_infer, width=10)
        infer_btn.grid(row=5, column=1, padx=8, pady=4, sticky=tk.E)
        def save_and_close():
            self.model_api_key = api_var.get().strip()
            self.model_base_url = url_var.get().strip()
            self.model_name = model_var.get().strip()
            dialog.destroy()
            self.log_message("[模型配置] 已保存")
        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=12)
        ttk.Button(btn_frame, text="保存", command=save_and_close, width=10).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=6)
    
    def save_log(self):
        """保存日志"""
        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.get(1.0, tk.END))
                messagebox.showinfo("成功", "日志已保存")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {str(e)}")

    def compute_work_abs_from_norm(self, norm_x, norm_y):
        """将归一化坐标映射为当前工作区内的绝对坐标"""
        x1 = self.x1_var.get()
        y1 = self.y1_var.get()
        x2 = self.x2_var.get()
        y2 = self.y2_var.get()
        abs_x = int(x1 + float(norm_x) * (x2 - x1))
        abs_y = int(y1 + float(norm_y) * (y2 - y1))
        return abs_x, abs_y

    def perform_home_swipe_gesture(self):
        """执行返回桌面系统手势：底部中心上滑
        基于样本 drag 指令：
        drag, work_x1, work_y1, work_x2, work_y2, 0.4243, 0.9775, 0.4294, 0.1397
        """
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return

        # 当前工作区
        work_x1 = self.x1_var.get()
        work_y1 = self.y1_var.get()
        work_x2 = self.x2_var.get()
        work_y2 = self.y2_var.get()

        tpl = self.home_swipe_template
        sx, sy = self.compute_work_abs_from_norm(tpl['start_norm_x'], tpl['start_norm_y'])
        ex, ey = self.compute_work_abs_from_norm(tpl['end_norm_x'], tpl['end_norm_y'])

        # 数据关系日志（便于复核和后续校准）
        self.log_message(
            f"[Home手势] 工作区: ({work_x1},{work_y1}) -> ({work_x2},{work_y2})"
        )
        self.log_message(
            f"[Home手势] 归一化→绝对: start=({tpl['start_norm_x']:.4f},{tpl['start_norm_y']:.4f}) → ({sx},{sy}), "
            f"end=({tpl['end_norm_x']:.4f},{tpl['end_norm_y']:.4f}) → ({ex},{ey})"
        )
        self.log_message(
            "[Home手势] 映射公式: abs_x = x1 + norm_x*(x2-x1); abs_y = y1 + norm_y*(y2-y1)"
        )

        # 发送拖动（控制端会按协议转换为归一化drag指令）
        ok, msg = self.controller.send_drag(sx, sy, ex, ey, work_x1, work_y1, work_x2, work_y2)
        if ok:
            self.log_message("[Home手势] 底部中心上滑 已发送")
        else:
            messagebox.showerror("错误", msg)
    
    def perform_back_swipe_gesture(self):
        """执行返回上一页手势：左侧边缘内滑"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return

        # 当前工作区
        work_x1 = self.x1_var.get()
        work_y1 = self.y1_var.get()
        work_x2 = self.x2_var.get()
        work_y2 = self.y2_var.get()

        tpl = self.back_swipe_template
        sx, sy = self.compute_work_abs_from_norm(tpl['start_norm_x'], tpl['start_norm_y'])
        ex, ey = self.compute_work_abs_from_norm(tpl['end_norm_x'], tpl['end_norm_y'])

        self.log_message(
            f"[Back手势] 归一化→绝对: start=({tpl['start_norm_x']:.2f},{tpl['start_norm_y']:.2f}) → ({sx},{sy}), "
            f"end=({tpl['end_norm_x']:.2f},{tpl['end_norm_y']:.2f}) → ({ex},{ey})"
        )

        ok, msg = self.controller.send_drag(sx, sy, ex, ey, work_x1, work_y1, work_x2, work_y2)
        if ok:
            self.log_message("[Back手势] 侧边内滑 已发送")
        else:
            messagebox.showerror("错误", msg)
    
    # ========== AutoGLM API 集成 ==========
    
    def open_autoglm_config_dialog(self):
        """打开 AutoGLM API 配置对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("AutoGLM API 配置")
        dialog.geometry("450x280")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # API 地址
        ttk.Label(dialog, text="API 地址:").grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        api_base_var = tk.StringVar(value=self.autoglm_api_base)
        ttk.Entry(dialog, textvariable=api_base_var, width=40).grid(row=0, column=1, padx=10, pady=5)
        
        # 屏幕宽度
        ttk.Label(dialog, text="手机屏幕宽度:").grid(row=1, column=0, padx=10, pady=5, sticky=tk.W)
        width_var = tk.IntVar(value=self.autoglm_screen_width)
        ttk.Entry(dialog, textvariable=width_var, width=15).grid(row=1, column=1, padx=10, pady=5, sticky=tk.W)
        
        # 屏幕高度
        ttk.Label(dialog, text="手机屏幕高度:").grid(row=2, column=0, padx=10, pady=5, sticky=tk.W)
        height_var = tk.IntVar(value=self.autoglm_screen_height)
        ttk.Entry(dialog, textvariable=height_var, width=15).grid(row=2, column=1, padx=10, pady=5, sticky=tk.W)
        
        # 测试连接按钮
        def test_connection():
            try:
                resp = requests.get(f"{api_base_var.get()}/api/health", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    messagebox.showinfo("成功", f"连接成功！\\n状态: {data.get('status', 'unknown')}")
                else:
                    messagebox.showerror("错误", f"服务器返回错误: {resp.status_code}")
            except Exception as e:
                messagebox.showerror("错误", f"连接失败: {str(e)}")
        
        ttk.Button(dialog, text="测试连接", command=test_connection).grid(row=3, column=1, padx=10, pady=10, sticky=tk.W)
        
        # 保存按钮
        def save_and_close():
            self.autoglm_api_base = api_base_var.get().strip().rstrip('/')
            self.autoglm_screen_width = width_var.get()
            self.autoglm_screen_height = height_var.get()
            dialog.destroy()
            self.log_message(f"[AutoGLM] API配置已保存: {self.autoglm_api_base}")
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="保存", command=save_and_close, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=10)
    
    def capture_current_frame_as_base64(self):
        """捕获当前摄像头画面并编码为 Base64"""
        if not self.camera_running or self.camera.current_frame is None:
            return None
        
        try:
            frame = self.camera.current_frame.copy()
            
            # 如果启用了裁切，应用裁切
            if self.crop_enabled and self.crop_rect:
                x1, y1, x2, y2 = self.crop_rect
                frame = frame[y1:y2, x1:x2]
            
            # 旋转90度（如果需要竖屏）
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            
            # 编码为 JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            img_b64 = base64.b64encode(buffer).decode('utf-8')
            return img_b64
        except Exception as e:
            self.log_message(f"[AutoGLM] 截图失败: {str(e)}")
            return None
    
    def call_autoglm_api(self, task, screenshot_b64):
        """调用 AutoGLM API 进行分析
        
        Args:
            task: 任务描述
            screenshot_b64: Base64 编码的截图
        
        Returns:
            dict: API 响应，包含 action 等
        """
        try:
            url = f"{self.autoglm_api_base}/api/analyze"
            payload = {
                'task': task,
                'screenshot': screenshot_b64,
                'screen_width': self.autoglm_screen_width,
                'screen_height': self.autoglm_screen_height,
                'lang': 'zh'
            }
            
            response = requests.post(url, json=payload, timeout=15)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f"API返回错误: {response.status_code}", 'detail': response.text}
        except requests.Timeout:
            return {'error': "API请求超时"}
        except Exception as e:
            return {'error': f"API调用失败: {str(e)}"}
    
    def convert_api_coords_to_work_area(self, element, element_abs=None):
        """将 API 返回的坐标转换为工作区绝对坐标
        
        API 返回的 element 是千分比坐标 [0-999, 0-999]
        element_abs 是基于屏幕分辨率的绝对像素坐标
        
        我们需要将其映射到机械臂的工作区坐标
        """
        work_x1 = self.x1_var.get()
        work_y1 = self.y1_var.get()
        work_x2 = self.x2_var.get()
        work_y2 = self.y2_var.get()
        
        work_width = work_x2 - work_x1
        work_height = work_y2 - work_y1
        
        # 使用千分比坐标转换
        if element:
            norm_x = element[0] / 1000.0
            norm_y = element[1] / 1000.0
        elif element_abs:
            # 从绝对坐标反推归一化坐标
            norm_x = element_abs[0] / self.autoglm_screen_width
            norm_y = element_abs[1] / self.autoglm_screen_height
        else:
            return None, None
        
        # 映射到工作区
        abs_x = int(work_x1 + norm_x * work_width)
        abs_y = int(work_y1 + norm_y * work_height)
        
        return abs_x, abs_y
    
    def execute_autoglm_action(self, action):
        """执行 AutoGLM 返回的操作指令
        
        Args:
            action: API 返回的 action 字典
        
        Returns:
            bool: True=继续执行, False=任务结束
            str: 执行结果描述
        """
        if action is None:
            return True, "action为空，跳过"
        
        action_type = action.get('action')
        work_x1 = self.x1_var.get()
        work_y1 = self.y1_var.get()
        work_x2 = self.x2_var.get()
        work_y2 = self.y2_var.get()
        
        if action_type == 'Tap':
            x, y = self.convert_api_coords_to_work_area(
                action.get('element'), 
                action.get('element_abs')
            )
            if x is not None:
                self.controller.send_move_click(x, y, work_x1, work_y1, work_x2, work_y2, ClickType.CLICK)
                return True, f"点击 ({x}, {y})"
            return True, "坐标无效"
        
        elif action_type == 'Double Tap':
            x, y = self.convert_api_coords_to_work_area(
                action.get('element'),
                action.get('element_abs')
            )
            if x is not None:
                self.controller.send_move_click(x, y, work_x1, work_y1, work_x2, work_y2, ClickType.DOUBLE)
                return True, f"双击 ({x}, {y})"
            return True, "坐标无效"
        
        elif action_type == 'Long Press':
            x, y = self.convert_api_coords_to_work_area(
                action.get('element'),
                action.get('element_abs')
            )
            if x is not None:
                self.controller.send_move_click(x, y, work_x1, work_y1, work_x2, work_y2, ClickType.LONG)
                return True, f"长按 ({x}, {y})"
            return True, "坐标无效"
        
        elif action_type == 'Swipe':
            start = action.get('start')
            end = action.get('end')
            if start and end:
                # 转换起止点坐标
                sx, sy = self.convert_api_coords_to_work_area(start)
                ex, ey = self.convert_api_coords_to_work_area(end)
                if sx is not None and ex is not None:
                    self.controller.send_drag(sx, sy, ex, ey, work_x1, work_y1, work_x2, work_y2)
                    return True, f"滑动 ({sx},{sy}) -> ({ex},{ey})"
            return True, "滑动坐标无效"
        
        elif action_type == 'Type':
            text = action.get('text', '')
            # 输入文本需要特殊处理，可能需要语音输入或其他方式
            self.log_message(f"[AutoGLM] 需要输入文本: {text}")
            return True, f"输入文本: {text} (需手动处理)"
        
        elif action_type == 'Back':
            self.perform_back_swipe_gesture()
            return True, "执行返回手势"
        
        elif action_type == 'Home':
            self.perform_home_swipe_gesture()
            return True, "执行Home手势"
        
        elif action_type == 'Launch':
            app = action.get('app', '')
            # 启动应用：先回桌面，然后需要找图标点击
            self.perform_home_swipe_gesture()
            return True, f"启动应用: {app} (已回桌面，需找图标)"
        
        elif action_type == 'Finish':
            message = action.get('message', '任务完成')
            return False, f"任务完成: {message}"
        
        else:
            return True, f"未知操作类型: {action_type}"
    
    def start_auto_task(self):
        """开始自动任务"""
        if not self.controller.connected:
            messagebox.showwarning("警告", "请先连接串口")
            return
        
        if not self.camera_running:
            messagebox.showwarning("警告", "请先启动摄像头")
            return
        
        task = self.auto_task_entry.get().strip()
        if not task:
            messagebox.showwarning("警告", "请输入任务描述")
            return
        
        self.auto_task_running = True
        self.auto_task_stop_flag = False
        self.auto_task_current_step = 0
        self.auto_task_max_steps = self.auto_task_max_steps_var.get()
        self.auto_task_step_delay = self.auto_task_delay_var.get()
        
        # 更新UI状态
        self.auto_task_start_btn.config(state=tk.DISABLED)
        self.auto_task_stop_btn.config(state=tk.NORMAL)
        self.auto_task_status_var.set("运行中...")
        self.auto_task_status_label.config(foreground="green")
        
        self.log_message(f"[AutoGLM] 开始任务: {task}")
        self.log_message(f"[AutoGLM] 最大步数: {self.auto_task_max_steps}, 步间延迟: {self.auto_task_step_delay}秒")
        
        # 启动任务线程
        self.auto_task_thread = threading.Thread(
            target=self._auto_task_loop,
            args=(task,),
            daemon=True
        )
        self.auto_task_thread.start()
    
    def stop_auto_task(self):
        """停止自动任务"""
        self.auto_task_stop_flag = True
        self.log_message("[AutoGLM] 正在停止任务...")
    
    def _auto_task_loop(self, task):
        """自动任务主循环（在后台线程运行）"""
        try:
            for step in range(self.auto_task_max_steps):
                if self.auto_task_stop_flag:
                    self.root.after(0, lambda: self.log_message("[AutoGLM] 任务已停止"))
                    break
                
                self.auto_task_current_step = step + 1
                self.root.after(0, lambda s=step+1: self.auto_task_status_var.set(f"步骤 {s}/{self.auto_task_max_steps}"))
                
                # 1. 截图
                screenshot_b64 = self.capture_current_frame_as_base64()
                if not screenshot_b64:
                    self.root.after(0, lambda: self.log_message("[AutoGLM] 截图失败，等待重试..."))
                    time.sleep(1)
                    continue
                
                # 2. 调用 API
                self.root.after(0, lambda s=step+1: self.log_message(f"[AutoGLM] 步骤 {s}: 正在分析..."))
                result = self.call_autoglm_api(task, screenshot_b64)
                
                if 'error' in result:
                    self.root.after(0, lambda e=result['error']: self.log_message(f"[AutoGLM] API错误: {e}"))
                    time.sleep(1)
                    continue
                
                action = result.get('action')
                raw_response = result.get('raw_response', '')
                
                self.root.after(0, lambda r=raw_response: self.log_message(f"[AutoGLM] 模型输出: {r}"))
                
                # 3. 执行操作
                should_continue, exec_msg = self.execute_autoglm_action(action)
                self.root.after(0, lambda m=exec_msg: self.log_message(f"[AutoGLM] 执行: {m}"))
                
                if not should_continue:
                    self.root.after(0, lambda: self.log_message("[AutoGLM] 任务完成"))
                    break
                
                # 4. 等待
                time.sleep(self.auto_task_step_delay)
            
            else:
                self.root.after(0, lambda: self.log_message("[AutoGLM] 已达到最大步数"))
        
        except Exception as e:
            self.root.after(0, lambda e=str(e): self.log_message(f"[AutoGLM] 任务异常: {e}"))
        
        finally:
            # 恢复UI状态
            self.auto_task_running = False
            self.root.after(0, self._reset_auto_task_ui)
    
    def _reset_auto_task_ui(self):
        """重置自动任务UI状态"""
        self.auto_task_start_btn.config(state=tk.NORMAL)
        self.auto_task_stop_btn.config(state=tk.DISABLED)
        self.auto_task_status_var.set("就绪")
        self.auto_task_status_label.config(foreground="gray")
    
    def save_config(self):
        """保存当前配置到文件（兼容旧版本）"""
        try:
            # 保存当前配置到configs字典
            self.configs[self.current_config_name] = {
                'crop_enabled': self.crop_enabled,
                'crop_rect': self.crop_rect,
                'polygon_points': self.polygon_points,
                'work_area': {
                    'x1': self.x1_var.get(),
                    'y1': self.y1_var.get(),
                    'x2': self.x2_var.get(),
                    'y2': self.y2_var.get()
                }
            }
            
            # 保存所有配置到文件
            all_config = {
                'current_config': self.current_config_name,
                'configs': self.configs
            }
            
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {str(e)}")
    
    def load_config(self):
        """从文件加载配置"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    all_config = json.load(f)
                
                # 新格式：包含多配置
                if 'configs' in all_config:
                    self.configs = all_config['configs']
                    self.current_config_name = all_config.get('current_config', '默认配置')
                    
                    # 更新配置选择器
                    if hasattr(self, 'config_combo'):
                        self.config_combo['values'] = list(self.configs.keys())
                        self.config_name_var.set(self.current_config_name)
                    
                    # 加载当前配置
                    if self.current_config_name in self.configs:
                        config = self.configs[self.current_config_name]
                        self._apply_config(config)
                else:
                    # 旧格式：单一配置，转换为新格式
                    self.configs = {'默认配置': all_config}
                    self.current_config_name = '默认配置'
                    if hasattr(self, 'config_combo'):
                        self.config_combo['values'] = ['默认配置']
                        self.config_name_var.set('默认配置')
                    self._apply_config(all_config)
                
                self.log_message(f"已加载配置: {self.current_config_name}")
        except Exception as e:
            print(f"加载配置失败: {str(e)}")
            # 初始化默认配置（使用绝对坐标）
            self.configs = {'默认配置': {
                'crop_enabled': False,
                'crop_rect': None,
                'polygon_points': [],
                'work_area': {'x1': 0, 'y1': 0, 'x2': 3900, 'y2': 6300}
            }}
            self.current_config_name = '默认配置'
            if hasattr(self, 'config_combo'):
                self.config_combo['values'] = ['默认配置']
    
    def _apply_config(self, config):
        """应用配置到界面"""
        # 恢复裁切设置
        if config.get('crop_enabled') and config.get('crop_rect'):
            self.crop_rect = tuple(config['crop_rect'])
            self.crop_enabled = config['crop_enabled']
            if self.crop_enabled and hasattr(self, 'crop_btn'):
                self.crop_btn.config(text="取消裁切")
        
        # 恢复多边形点
        if config.get('polygon_points'):
            self.polygon_points = config['polygon_points']
            # 重新生成蒙版
            if len(self.polygon_points) >= 3 and self.camera.current_frame is not None:
                frame = self.camera.current_frame
                h, w = frame.shape[:2]
                self.screen_mask = np.zeros((h, w), dtype=np.uint8)
                points_array = np.array(self.polygon_points, dtype=np.int32)
                cv2.fillPoly(self.screen_mask, [points_array], 255)
        
        # 恢复工作区域（绝对坐标）
        if 'work_area' in config:
            x1 = config['work_area']['x1']
            y1 = config['work_area']['y1']
            x2 = config['work_area']['x2']
            y2 = config['work_area']['y2']
            
            # 兼容旧版本：如果坐标值小于等于2，说明是旧的归一化坐标，需要转换为绝对坐标
            if x1 <= 2 and y1 <= 2 and x2 <= 2 and y2 <= 2:
                # 转换归一化坐标为绝对坐标
                x1 = int(x1 * 3900)
                y1 = int(y1 * 6300)
                x2 = int(x2 * 3900)
                y2 = int(y2 * 6300)
            
            self.x1_var.set(int(x1))
            self.y1_var.set(int(y1))
            self.x2_var.set(int(x2))
            self.y2_var.set(int(y2))
    
    def save_current_config(self):
        """保存当前配置按钮的回调"""
        self.save_config()
        messagebox.showinfo("成功", f"配置 '{self.current_config_name}' 已保存")
        self.log_message(f"[配置] 已保存配置: {self.current_config_name}")
    
    def create_new_config(self):
        """创建新配置"""
        from tkinter import simpledialog
        name = simpledialog.askstring("新建配置", "请输入新配置名称:")
        if name:
            if name in self.configs:
                messagebox.showwarning("警告", "配置名称已存在")
                return
            
            # 创建新配置（使用当前设置）
            self.configs[name] = {
                'crop_enabled': self.crop_enabled,
                'crop_rect': self.crop_rect,
                'polygon_points': self.polygon_points.copy(),
                'work_area': {
                    'x1': self.x1_var.get(),
                    'y1': self.y1_var.get(),
                    'x2': self.x2_var.get(),
                    'y2': self.y2_var.get()
                }
            }
            
            # 更新配置列表
            self.current_config_name = name
            self.config_combo['values'] = list(self.configs.keys())
            self.config_name_var.set(name)
            
            self.save_config()
            messagebox.showinfo("成功", f"已创建新配置: {name}")
            self.log_message(f"[配置] 已创建新配置: {name}")
    
    def delete_current_config(self):
        """删除当前配置"""
        if self.current_config_name == "默认配置":
            messagebox.showwarning("警告", "不能删除默认配置")
            return
        
        if len(self.configs) <= 1:
            messagebox.showwarning("警告", "至少需要保留一个配置")
            return
        
        if messagebox.askyesno("确认", f"确定要删除配置 '{self.current_config_name}' 吗？"):
            del self.configs[self.current_config_name]
            
            # 切换到默认配置
            self.current_config_name = "默认配置"
            self.config_combo['values'] = list(self.configs.keys())
            self.config_name_var.set(self.current_config_name)
            
            # 加载默认配置
            if self.current_config_name in self.configs:
                self._apply_config(self.configs[self.current_config_name])
            
            self.save_config()
            messagebox.showinfo("成功", "配置已删除")
            self.log_message(f"[配置] 已删除配置并切换到: {self.current_config_name}")
    
    def load_selected_config(self, event=None):
        """加载选中的配置"""
        config_name = self.config_name_var.get()
        if config_name in self.configs:
            self.current_config_name = config_name
            self._apply_config(self.configs[config_name])
            self.log_message(f"[配置] 已切换到配置: {config_name}")
            messagebox.showinfo("成功", f"已切换到配置: {config_name}")
    
    def on_closing(self):
        """关闭窗口"""
        self.save_config()  # 保存配置
        self.stop_reader()
        self.controller.disconnect()
        if self.camera_running:
            self.camera.stop()
        self.root.destroy()


def main():
    # 关闭已有的进程（如果存在）
    kill_existing_process()
    
    # 稍微等待一下，确保旧进程已完全关闭
    time.sleep(0.5)
    
    # 创建锁文件
    create_lock_file()
    
    try:
        root = tk.Tk()
        app = MotorControlGUI(root)
        root.protocol("WM_DELETE_WINDOW", app.on_closing)
        root.mainloop()
    finally:
        # 删除锁文件
        remove_lock_file()


if __name__ == '__main__':
    main()
