#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
基础驱动抽象层 (Base Driver)
实现 Task 1.1: 安全层 - 物理边界检查与防火墙

核心功能:
- SafetyError 异常类
- @safe_guard 装饰器 (物理边界检查)
- BaseDriver 抽象基类
"""

import abc
from typing import Tuple, Callable, Optional
from functools import wraps


class SafetyError(Exception):
    """物理安全异常
    
    当机械臂动作超出物理边界或违反安全限制时抛出。
    这是系统的最后一道防线，绝对不能让危险指令执行。
    """
    pass


def safe_guard(func: Callable) -> Callable:
    """安全守卫装饰器 - Task 1.1 核心实现
    
    在每个物理动作执行前进行边界检查:
    1. 坐标是否在工作区范围内 (0.0-1.0 归一化坐标)
    2. Z 轴是否过低 (如果适用)
    3. 参数是否合法
    
    如果检查失败，抛出 SafetyError 并阻止执行。
    
    Usage:
        @safe_guard
        def tap(self, x: float, y: float):
            ...
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # 提取坐标参数 (支持多种调用方式)
        x, y = None, None
        x1, y1, x2, y2 = None, None, None, None
        
        # 从位置参数提取
        if len(args) >= 2:
            if func.__name__ in ['tap', 'move', 'double_tap', 'long_press']:
                x, y = args[0], args[1]
            elif func.__name__ in ['swipe', 'drag']:
                if len(args) >= 4:
                    x1, y1, x2, y2 = args[0], args[1], args[2], args[3]
        
        # 从关键字参数提取
        x = x or kwargs.get('x') or kwargs.get('x_ratio')
        y = y or kwargs.get('y') or kwargs.get('y_ratio')
        x1 = x1 or kwargs.get('x1') or kwargs.get('start_x')
        y1 = y1 or kwargs.get('y1') or kwargs.get('start_y')
        x2 = x2 or kwargs.get('x2') or kwargs.get('end_x')
        y2 = y2 or kwargs.get('y2') or kwargs.get('end_y')
        
        # 边界检查 - 单点坐标
        if x is not None and y is not None:
            if not (0.0 <= x <= 1.0):
                raise SafetyError(
                    f"X 坐标超出边界: {x} (允许范围 0.0-1.0)\n"
                    f"函数: {func.__name__}\n"
                    f"❌ 安全检查失败，已阻止执行"
                )
            if not (0.0 <= y <= 1.0):
                raise SafetyError(
                    f"Y 坐标超出边界: {y} (允许范围 0.0-1.0)\n"
                    f"函数: {func.__name__}\n"
                    f"❌ 安全检查失败，已阻止执行"
                )
        
        # 边界检查 - 两点坐标 (拖动/滑动)
        if x1 is not None and y1 is not None:
            if not (0.0 <= x1 <= 1.0):
                raise SafetyError(f"起点 X 坐标超出边界: {x1} (允许范围 0.0-1.0)")
            if not (0.0 <= y1 <= 1.0):
                raise SafetyError(f"起点 Y 坐标超出边界: {y1} (允许范围 0.0-1.0)")
        
        if x2 is not None and y2 is not None:
            if not (0.0 <= x2 <= 1.0):
                raise SafetyError(f"终点 X 坐标超出边界: {x2} (允许范围 0.0-1.0)")
            if not (0.0 <= y2 <= 1.0):
                raise SafetyError(f"终点 Y 坐标超出边界: {y2} (允许范围 0.0-1.0)")
        
        # Z 轴检查 (如果参数中包含 z 坐标)
        z = kwargs.get('z')
        if z is not None:
            # 假设 Z 轴安全范围是 0-100 (具体值需根据实际硬件调整)
            if z < 0 or z > 100:
                raise SafetyError(
                    f"Z 轴坐标超出安全范围: {z} (允许范围 0-100)\n"
                    f"⚠️ 可能导致机械臂与屏幕碰撞"
                )
        
        # 通过安全检查，执行原函数
        return func(self, *args, **kwargs)
    
    return wrapper


class BaseDriver(abc.ABC):
    """机械臂驱动抽象基类
    
    定义统一的接口规范，所有具体驱动 (Serial/WiFi/Mock) 必须继承此类。
    
    核心原则:
    1. 所有坐标使用归一化值 (0.0-1.0)
    2. 所有物理动作方法必须应用 @safe_guard 装饰器
    3. 驱动只负责"怎么做"，不关心"做什么"
    """
    
    def __init__(self):
        """初始化驱动"""
        self.connected = False
        self.logger: Optional[Callable] = None
    
    def set_logger(self, logger: Callable[[str], None]):
        """设置日志回调函数"""
        self.logger = logger
    
    def log(self, msg: str, level: str = "INFO"):
        """记录日志"""
        if self.logger:
            self.logger(f"[{level}] {msg}")
        else:
            print(f"[{level}] {msg}")
    
    # ========== 连接管理 (抽象方法) ==========
    
    @abc.abstractmethod
    def connect(self, **kwargs) -> bool:
        """连接到设备
        
        Returns:
            连接是否成功
        """
        pass
    
    @abc.abstractmethod
    def disconnect(self):
        """断开连接"""
        pass
    
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass
    
    # ========== 基础动作 (必须实现，必须应用 @safe_guard) ==========
    
    @abc.abstractmethod
    @safe_guard
    def tap(self, x: float, y: float, **kwargs) -> bool:
        """点击指定坐标
        
        Args:
            x: X 坐标 (归一化 0.0-1.0)
            y: Y 坐标 (归一化 0.0-1.0)
            **kwargs: 驱动特定参数 (如 speed, delay 等)
        
        Returns:
            执行是否成功
        """
        pass
    
    @abc.abstractmethod
    @safe_guard
    def swipe(self, x1: float, y1: float, x2: float, y2: float, **kwargs) -> bool:
        """滑动/拖动
        
        Args:
            x1, y1: 起点坐标 (归一化)
            x2, y2: 终点坐标 (归一化)
            **kwargs: 驱动特定参数
        
        Returns:
            执行是否成功
        """
        pass
    
    @abc.abstractmethod
    def reset(self) -> bool:
        """复位/归位到安全位置
        
        Returns:
            执行是否成功
        """
        pass
    
    # ========== 扩展动作 (可选实现) ==========
    
    @safe_guard
    def double_tap(self, x: float, y: float, **kwargs) -> bool:
        """双击 (默认实现: 两次快速点击)"""
        self.tap(x, y, **kwargs)
        self.tap(x, y, **kwargs)
        return True
    
    @safe_guard
    def long_press(self, x: float, y: float, duration_ms: int = 2000, **kwargs) -> bool:
        """长按 (默认实现: 点击 + 延迟)
        
        子类可以覆盖此方法提供更精确的实现。
        """
        return self.tap(x, y, delay=duration_ms, **kwargs)
    
    # ========== 系统手势 ==========
    
    def home(self) -> bool:
        """返回桌面手势 (底部中心上滑)"""
        return self.swipe(0.5, 0.95, 0.5, 0.2)
    
    def back(self) -> bool:
        """返回上一页手势 (左侧内滑)"""
        return self.swipe(0.02, 0.5, 0.35, 0.5)
    
    # ========== 高级功能 ==========
    
    def screenshot(self) -> Optional[bytes]:
        """获取屏幕截图
        
        Returns:
            截图数据 (PNG/JPEG 格式)，或 None 如果不支持
        """
        self.log("此驱动不支持截图功能", "WARNING")
        return None
    
    def get_status(self) -> dict:
        """获取设备状态"""
        return {
            "connected": self.connected,
            "driver_type": self.__class__.__name__
        }


class MockDriver(BaseDriver):
    """模拟驱动 (用于测试)
    
    不连接真实硬件，所有操作只记录日志。
    用于开发和测试阶段。
    """
    
    def connect(self, **kwargs) -> bool:
        """模拟连接"""
        self.log("MockDriver 已连接 (模拟)")
        self.connected = True
        return True
    
    def disconnect(self):
        """模拟断开"""
        self.log("MockDriver 已断开")
        self.connected = False
    
    def is_connected(self) -> bool:
        return self.connected
    
    @safe_guard
    def tap(self, x: float, y: float, **kwargs) -> bool:
        """模拟点击"""
        self.log(f"MockDriver.tap({x:.3f}, {y:.3f})")
        return True
    
    @safe_guard
    def swipe(self, x1: float, y1: float, x2: float, y2: float, **kwargs) -> bool:
        """模拟滑动"""
        self.log(f"MockDriver.swipe(({x1:.3f}, {y1:.3f}) -> ({x2:.3f}, {y2:.3f}))")
        return True
    
    def reset(self) -> bool:
        """模拟复位"""
        self.log("MockDriver.reset()")
        return True


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== Task 1.1 安全层测试 ===\n")
    
    # 测试 1: 正常操作
    print("测试 1: 正常操作 (应该成功)")
    driver = MockDriver()
    driver.connect()
    driver.tap(0.5, 0.5)
    print("✅ 通过\n")
    
    # 测试 2: X 坐标超出边界
    print("测试 2: X 坐标超出边界 (应该抛出 SafetyError)")
    try:
        driver.tap(1.5, 0.5)
        print("❌ 失败: 未捕获异常\n")
    except SafetyError as e:
        print(f"✅ 正确捕获: {e}\n")
    
    # 测试 3: Y 坐标为负数
    print("测试 3: Y 坐标为负数 (应该抛出 SafetyError)")
    try:
        driver.tap(0.5, -0.1)
        print("❌ 失败: 未捕获异常\n")
    except SafetyError as e:
        print(f"✅ 正确捕获: {e}\n")
    
    # 测试 4: 滑动边界检查
    print("测试 4: 滑动终点超出边界 (应该抛出 SafetyError)")
    try:
        driver.swipe(0.2, 0.2, 1.2, 0.5)
        print("❌ 失败: 未捕获异常\n")
    except SafetyError as e:
        print(f"✅ 正确捕获: {e}\n")
    
    # 测试 5: 系统手势
    print("测试 5: 系统手势 (应该成功)")
    driver.home()
    driver.back()
    print("✅ 通过\n")
    
    driver.disconnect()
    print("=== 所有测试完成 ===")
