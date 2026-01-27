#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
串口机械臂驱动 (Serial Driver)
基于 GRBL 协议的 USB 串口通信

移植自: VLM/grbl/driver_adapter.py
增强: 继承 BaseDriver，集成 @safe_guard 安全层
"""

import serial
import serial.tools.list_ports
import threading
import time
from enum import IntEnum
from typing import Optional, Callable, Tuple, Dict, List

from .base_driver import BaseDriver, SafetyError, safe_guard


class ActionType(IntEnum):
    """操作类型枚举 (GRBL 协议)"""
    MOVE = 0      # 基础移动（不点击）
    CLICK = 1     # 单击
    DOUBLE = 2    # 双击
    LONG = 3      # 长按
    DRAG = 4      # 拖动/滑动
    HOME = 5      # 归位/复位
    MOVE_AXIS = 6 # 单轴移动
    TYPE = 7      # 文本输入
    BACK = 8      # 返回上一页
    LAUNCH = 9    # 启动应用
    WAIT = 10     # 等待


class SerialDriver(BaseDriver):
    """串口机械臂驱动 - 基于 GRBL 协议
    
    特性:
    - USB 串口通信 (默认 115200 波特率)
    - 命令队列管理
    - 异步响应监听
    - 绝对坐标与归一化坐标自动转换
    - 完整的 @safe_guard 安全检查
    """
    
    def __init__(self, port: str = None, baudrate: int = 115200):
        """初始化串口驱动
        
        Args:
            port: 串口号（如 COM3 / /dev/ttyUSB0），None 则自动检测
            baudrate: 波特率，默认 115200
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial: Optional[serial.Serial] = None
        
        # 工作区坐标（绝对值，单位取决于硬件）
        self.work_x1 = 0
        self.work_y1 = 0
        self.work_x2 = 3900
        self.work_y2 = 6300
        
        # 命令队列
        self.command_queue: List[Dict] = []
        self.queue_seq = 1
        self.executing = False
        self.current_command = None
        
        # 响应监听线程
        self.response_thread: Optional[threading.Thread] = None
        self.running = False
        self.ready_event = threading.Event()
    
    # ========== 连接管理 ==========
    
    def list_ports(self) -> List[str]:
        """列出系统中所有可用串口"""
        ports = []
        for port_info in serial.tools.list_ports.comports():
            ports.append(port_info.device)
        return ports
    
    def connect(self, port: str = None, **kwargs) -> bool:
        """连接串口设备
        
        Args:
            port: 串口号，None 则使用初始化时的端口或自动检测
            
        Returns:
            连接是否成功
        """
        port = port or self.port
        if not port:
            ports = self.list_ports()
            if not ports:
                self.log("未找到可用串口", "ERROR")
                return False
            port = ports[0]
            self.log(f"自动选择串口: {port}")
        
        try:
            self.serial = serial.Serial(port, self.baudrate, timeout=1)
            self.connected = True
            self.running = True
            
            # 启动响应监听线程
            self.response_thread = threading.Thread(
                target=self._response_listener,
                daemon=True
            )
            self.response_thread.start()
            
            self.log(f"已连接到 {port} @ {self.baudrate} baud")
            return True
            
        except Exception as e:
            self.log(f"连接失败: {str(e)}", "ERROR")
            self.connected = False
            return False
    
    def disconnect(self):
        """断开串口连接"""
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()
        self.connected = False
        self.log("已断开连接")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.connected and self.serial and self.serial.is_open
    
    # ========== 坐标转换 ==========
    
    def set_work_area(self, x1: int, y1: int, x2: int, y2: int):
        """设置工作区范围（绝对坐标）
        
        Args:
            x1, y1: 左上角绝对坐标
            x2, y2: 右下角绝对坐标
        """
        self.work_x1 = int(x1)
        self.work_y1 = int(y1)
        self.work_x2 = int(x2)
        self.work_y2 = int(y2)
        self.log(f"工作区设置: ({x1},{y1}) -> ({x2},{y2})")
    
    def _norm_to_abs(self, norm_x: float, norm_y: float) -> Tuple[int, int]:
        """归一化坐标 -> 绝对坐标"""
        abs_x = int(self.work_x1 + norm_x * (self.work_x2 - self.work_x1))
        abs_y = int(self.work_y1 + norm_y * (self.work_y2 - self.work_y1))
        return abs_x, abs_y
    
    def _abs_to_norm(self, abs_x: int, abs_y: int) -> Tuple[float, float]:
        """绝对坐标 -> 归一化坐标"""
        work_w = self.work_x2 - self.work_x1
        work_h = self.work_y2 - self.work_y1
        norm_x = (abs_x - self.work_x1) / work_w if work_w > 0 else 0.0
        norm_y = (abs_y - self.work_y1) / work_h if work_h > 0 else 0.0
        return max(0.0, min(1.0, norm_x)), max(0.0, min(1.0, norm_y))
    
    # ========== 底层通信 ==========
    
    def _send_command(self, cmd: str) -> bool:
        """发送原始命令到设备
        
        Args:
            cmd: 命令字符串（自动添加 \\r\\n）
            
        Returns:
            发送是否成功
        """
        if not self.is_connected():
            self.log("未连接到设备", "ERROR")
            return False
        
        try:
            if not cmd.endswith('\r\n'):
                cmd = cmd + '\r\n'
            self.serial.write(cmd.encode('ascii'))
            self.log(f"TX: {cmd.strip()}")
            return True
        except Exception as e:
            self.log(f"发送失败: {str(e)}", "ERROR")
            return False
    
    def _response_listener(self):
        """响应监听线程（后台运行）"""
        while self.running:
            try:
                if self.serial and self.serial.in_waiting > 0:
                    response = self.serial.readline().decode('utf-8', errors='ignore').strip()
                    if response:
                        self.log(f"RX: {response}")
                        if 'READY' in response.upper():
                            self.ready_event.set()
                time.sleep(0.01)
            except Exception as e:
                if self.running:
                    self.log(f"监听错误: {str(e)}", "ERROR")
                break
    
    # ========== 基础动作 (带安全检查) ==========
    
    @safe_guard
    def tap(self, x: float, y: float, **kwargs) -> bool:
        """点击指定坐标 (归一化)
        
        Args:
            x, y: 归一化坐标 (0.0-1.0)
            **kwargs: speed (移动速度，默认 100)
        """
        speed = kwargs.get('speed', 100)
        abs_x, abs_y = self._norm_to_abs(x, y)
        return self._queue_action(
            action_type=ActionType.CLICK,
            x=abs_x, y=abs_y, speed=speed
        )
    
    @safe_guard
    def double_tap(self, x: float, y: float, **kwargs) -> bool:
        """双击"""
        speed = kwargs.get('speed', 100)
        abs_x, abs_y = self._norm_to_abs(x, y)
        return self._queue_action(
            action_type=ActionType.DOUBLE,
            x=abs_x, y=abs_y, speed=speed
        )
    
    @safe_guard
    def long_press(self, x: float, y: float, duration_ms: int = 2000, **kwargs) -> bool:
        """长按"""
        speed = kwargs.get('speed', 100)
        abs_x, abs_y = self._norm_to_abs(x, y)
        return self._queue_action(
            action_type=ActionType.LONG,
            x=abs_x, y=abs_y, duration_ms=duration_ms, speed=speed
        )
    
    @safe_guard
    def swipe(self, x1: float, y1: float, x2: float, y2: float, **kwargs) -> bool:
        """滑动/拖动"""
        speed = kwargs.get('speed', 100)
        abs_x1, abs_y1 = self._norm_to_abs(x1, y1)
        abs_x2, abs_y2 = self._norm_to_abs(x2, y2)
        return self._queue_action(
            action_type=ActionType.DRAG,
            x1=abs_x1, y1=abs_y1, x2=abs_x2, y2=abs_y2, speed=speed
        )
    
    def reset(self) -> bool:
        """复位到原点"""
        self.log("执行复位")
        return self._send_command("home")
    
    # ========== 命令队列管理 ==========
    
    def _queue_action(self, action_type: ActionType, **kwargs) -> bool:
        """将动作加入队列"""
        queue_id = self.queue_seq
        self.queue_seq += 1
        
        action = {
            'id': queue_id,
            'type': action_type,
            'timestamp': time.time(),
            **kwargs
        }
        
        self.command_queue.append(action)
        self.log(f"入队: {action_type.name} (#{queue_id}), 队长: {len(self.command_queue)}")
        
        # 如果没有正在执行的命令，启动执行
        if not self.executing:
            threading.Thread(target=self._execute_next, daemon=True).start()
        
        return True
    
    def _execute_next(self):
        """执行队列中的下一个命令"""
        if not self.command_queue or self.executing:
            return
        
        self.executing = True
        self.current_command = self.command_queue.pop(0)
        cmd = self.current_command
        
        self.log(f"执行: {cmd['type'].name} (#{cmd['id']}), 剩余: {len(self.command_queue)}")
        
        try:
            if cmd['type'] == ActionType.CLICK:
                self._execute_click(cmd)
            elif cmd['type'] == ActionType.DOUBLE:
                self._execute_double(cmd)
            elif cmd['type'] == ActionType.LONG:
                self._execute_long(cmd)
            elif cmd['type'] == ActionType.DRAG:
                self._execute_drag(cmd)
            elif cmd['type'] == ActionType.HOME:
                self._send_command("home")
        except Exception as e:
            self.log(f"执行失败: {str(e)}", "ERROR")
        
        # 等待设备反馈或超时
        self.ready_event.clear()
        if not self.ready_event.wait(timeout=10):
            self.log("命令超时，继续下一条", "WARNING")
        
        self.executing = False
        self._execute_next()
    
    def _execute_click(self, cmd: Dict):
        """执行单击命令"""
        x, y = cmd.get('x', 0), cmd.get('y', 0)
        speed = cmd.get('speed', 100)
        norm_x, norm_y = self._abs_to_norm(x, y)
        protocol = f"move_click, {self.work_x1}, {self.work_y1}, {self.work_x2}, {self.work_y2}, {norm_x:.5f}, {norm_y:.5f}, {ActionType.CLICK}, {speed}"
        self._send_command(protocol)
    
    def _execute_double(self, cmd: Dict):
        """执行双击命令"""
        x, y = cmd.get('x', 0), cmd.get('y', 0)
        speed = cmd.get('speed', 100)
        norm_x, norm_y = self._abs_to_norm(x, y)
        protocol = f"move_click, {self.work_x1}, {self.work_y1}, {self.work_x2}, {self.work_y2}, {norm_x:.5f}, {norm_y:.5f}, {ActionType.DOUBLE}, {speed}"
        self._send_command(protocol)
    
    def _execute_long(self, cmd: Dict):
        """执行长按命令"""
        x, y = cmd.get('x', 0), cmd.get('y', 0)
        speed = cmd.get('speed', 100)
        norm_x, norm_y = self._abs_to_norm(x, y)
        protocol = f"move_click, {self.work_x1}, {self.work_y1}, {self.work_x2}, {self.work_y2}, {norm_x:.5f}, {norm_y:.5f}, {ActionType.LONG}, {speed}"
        self._send_command(protocol)
    
    def _execute_drag(self, cmd: Dict):
        """执行拖动命令"""
        x1, y1 = cmd.get('x1', 0), cmd.get('y1', 0)
        x2, y2 = cmd.get('x2', 0), cmd.get('y2', 0)
        norm_x1, norm_y1 = self._abs_to_norm(x1, y1)
        norm_x2, norm_y2 = self._abs_to_norm(x2, y2)
        protocol = f"drag, {self.work_x1}, {self.work_y1}, {self.work_x2}, {self.work_y2}, {norm_x1:.4f}, {norm_y1:.4f}, {norm_x2:.4f}, {norm_y2:.4f}"
        self._send_command(protocol)
    
    # ========== 状态查询 ==========
    
    def get_status(self) -> dict:
        """获取驱动状态"""
        return {
            "connected": self.connected,
            "driver_type": "SerialDriver",
            "port": self.port,
            "baudrate": self.baudrate,
            "executing": self.executing,
            "queue_length": len(self.command_queue),
            "work_area": (self.work_x1, self.work_y1, self.work_x2, self.work_y2)
        }


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== SerialDriver 测试 ===\n")
    
    driver = SerialDriver()
    
    # 列出可用串口
    ports = driver.list_ports()
    print(f"可用串口: {ports}\n")
    
    if not ports:
        print("未找到串口设备，使用模拟模式测试安全层...\n")
        
        # 测试安全检查
        driver.connected = True  # 模拟已连接
        
        try:
            print("测试 1: 正常点击 (0.5, 0.5)")
            driver.tap(0.5, 0.5)
            print("✅ 通过\n")
        except SafetyError as e:
            print(f"❌ 失败: {e}\n")
        
        try:
            print("测试 2: 超出边界点击 (1.5, 0.5)")
            driver.tap(1.5, 0.5)
            print("❌ 未捕获异常\n")
        except SafetyError as e:
            print(f"✅ 正确捕获: {e}\n")
    
    else:
        print("⚠️ 发现真实串口设备，请手动测试连接")
        print(f"使用方法: driver.connect('{ports[0]}')")
    
    print("=== 测试完成 ===")
