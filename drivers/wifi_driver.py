#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WiFi 网络驱动 (WiFi Driver)
基于 ESP32-S3 的 HTTP API 网络控制

移植自: autoglm-s3-service/esp32_client.py
增强: 继承 BaseDriver，集成 @safe_guard 安全层
"""

import requests
import logging
import time
from typing import Dict, Any, Optional

try:
    from .base_driver import BaseDriver, SafetyError, safe_guard
except ImportError:
    from base_driver import BaseDriver, SafetyError, safe_guard


logger = logging.getLogger(__name__)


class WiFiDriver(BaseDriver):
    """WiFi 网络驱动 - 基于 ESP32-S3 HTTP API
    
    特性:
    - WiFi/HTTP 网络通信 (端口 8888)
    - 会话管理 (登录认证)
    - 归一化坐标 (0.0-1.0)
    - 完整的 @safe_guard 安全检查
    """
    
    DEFAULT_PORT = 8888
    TIMEOUT = 5
    
    def __init__(self, device_ip: str = None, username: str = "admin", password: str = "admin"):
        """初始化 WiFi 驱动
        
        Args:
            device_ip: 设备 IP 地址 (如 192.168.1.100)
            username: 登录用户名
            password: 登录密码
        """
        super().__init__()
        self.device_ip = device_ip
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.timeout = self.TIMEOUT
        self.logged_in = False
    
    # ========== 连接管理 ==========
    
    def connect(self, device_ip: str = None, **kwargs) -> bool:
        """连接到 WiFi 设备
        
        Args:
            device_ip: 设备 IP，None 则使用初始化时的 IP
            
        Returns:
            连接是否成功
        """
        device_ip = device_ip or self.device_ip
        if not device_ip:
            self.log("未指定设备 IP", "ERROR")
            return False
        
        self.device_ip = device_ip
        
        try:
            # 尝试登录
            url = self._build_url("/login")
            response = self.session.post(
                url,
                data={
                    "username": self.username,
                    "password": self.password
                },
                allow_redirects=False,
                timeout=self.TIMEOUT
            )
            
            # 检查登录是否成功（302重定向或200）
            if response.status_code in [200, 302]:
                if 'ESPSESSIONID' in self.session.cookies:
                    self.logged_in = True
                    self.connected = True
                    self.log(f"已连接到 {device_ip}:{self.DEFAULT_PORT}")
                    return True
            
            self.log(f"登录失败: HTTP {response.status_code}", "ERROR")
            return False
            
        except Exception as e:
            self.log(f"连接失败: {str(e)}", "ERROR")
            self.connected = False
            return False
    
    def disconnect(self):
        """断开连接"""
        self.session.close()
        self.connected = False
        self.logged_in = False
        self.log("已断开连接")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.connected and self.logged_in
    
    # ========== 底层通信 ==========
    
    def _build_url(self, endpoint: str = "/") -> str:
        """构建请求 URL"""
        if not self.device_ip:
            raise ValueError("Device IP is required")
        return f"http://{self.device_ip}:{self.DEFAULT_PORT}{endpoint}"
    
    def _send_http_get(self, endpoint: str, params: Dict = None) -> Dict[str, Any]:
        """发送 GET 请求
        
        Args:
            endpoint: API 端点
            params: 查询参数
            
        Returns:
            响应字典
        """
        if not self.is_connected():
            return {"success": False, "message": "Not connected"}
        
        try:
            url = self._build_url(endpoint)
            self.log(f"GET {url} params={params}")
            
            response = self.session.get(url, params=params, timeout=self.TIMEOUT)
            response.raise_for_status()
            
            return {
                "success": True,
                "data": response.text,
                "status_code": response.status_code
            }
            
        except Exception as e:
            self.log(f"HTTP GET 错误: {str(e)}", "ERROR")
            return {"success": False, "message": str(e)}
    
    # ========== 基础动作 (带安全检查) ==========
    
    @safe_guard
    def tap(self, x: float, y: float, **kwargs) -> bool:
        """点击指定坐标 (归一化)
        
        Args:
            x, y: 归一化坐标 (0.0-1.0)
            **kwargs: click_count (点击次数), delay_ms (延迟)
        """
        click_count = kwargs.get('click_count', 1)
        delay_ms = kwargs.get('delay_ms', 0)
        
        result = self._send_http_get(
            "/test_move",
            params={"x": round(x, 5), "y": round(y, 5)}
        )
        
        if result.get("success"):
            self.log(f"点击 ({x:.3f}, {y:.3f}) x{click_count}")
            return True
        else:
            self.log(f"点击失败: {result.get('message')}", "ERROR")
            return False
    
    @safe_guard
    def double_tap(self, x: float, y: float, **kwargs) -> bool:
        """双击"""
        self.tap(x, y, **kwargs)
        time.sleep(0.1)
        self.tap(x, y, **kwargs)
        return True
    
    @safe_guard
    def long_press(self, x: float, y: float, duration_ms: int = 2000, **kwargs) -> bool:
        """长按 (模拟: 移动到位置后保持)"""
        self.log(f"长按 ({x:.3f}, {y:.3f}) {duration_ms}ms")
        result = self.tap(x, y, delay_ms=duration_ms, **kwargs)
        time.sleep(duration_ms / 1000.0)
        return result
    
    @safe_guard
    def swipe(self, x1: float, y1: float, x2: float, y2: float, **kwargs) -> bool:
        """滑动/拖动
        
        Args:
            x1, y1: 起点 (归一化)
            x2, y2: 终点 (归一化)
            **kwargs: steps (分步数, 默认10), delay (每步延迟秒数)
        """
        steps = kwargs.get('steps', 10)
        delay = kwargs.get('delay', 0.05)
        
        self.log(f"滑动 ({x1:.3f},{y1:.3f}) -> ({x2:.3f},{y2:.3f}), {steps}步")
        
        for i in range(steps + 1):
            ratio = i / steps
            x = x1 + (x2 - x1) * ratio
            y = y1 + (y2 - y1) * ratio
            
            result = self._send_http_get(
                "/test_move",
                params={"x": round(x, 5), "y": round(y, 5)}
            )
            
            if not result.get("success"):
                self.log(f"滑动步骤 {i}/{steps} 失败", "ERROR")
                return False
            
            if i < steps:
                time.sleep(delay)
        
        return True
    
    def reset(self) -> bool:
        """复位到原点 (0, 0)"""
        self.log("执行复位")
        result = self._send_http_get("/test_move", params={"x": 0.0, "y": 0.0})
        return result.get("success", False)
    
    # ========== 高级功能 ==========
    
    def screenshot(self) -> Optional[bytes]:
        """获取屏幕截图
        
        Returns:
            截图数据 (JPEG 格式)，失败返回 None
        """
        if not self.is_connected():
            self.log("未连接到设备", "ERROR")
            return None
        
        try:
            url = self._build_url("/capture")
            self.log(f"获取截图: {url}")
            
            response = self.session.get(url, timeout=self.TIMEOUT * 3)
            response.raise_for_status()
            
            # 检查内容类型
            content_type = response.headers.get('Content-Type', '')
            if 'image' not in content_type.lower():
                self.log(f"无效的内容类型: {content_type}", "ERROR")
                return None
            
            self.log(f"截图成功: {len(response.content)} bytes")
            return response.content
            
        except Exception as e:
            self.log(f"截图失败: {str(e)}", "ERROR")
            return None
    
    def get_device_status(self) -> Dict[str, Any]:
        """获取设备状态"""
        try:
            url = self._build_url("/api/status")
            response = self.session.get(url, timeout=self.TIMEOUT)
            
            if response.status_code == 404:
                # 端点不存在，返回基本状态
                return {
                    "success": True,
                    "data": {
                        "online": True,
                        "connected": self.connected
                    }
                }
            
            response.raise_for_status()
            return {
                "success": True,
                "data": response.json()
            }
            
        except Exception as e:
            self.log(f"获取状态失败: {str(e)}", "ERROR")
            return {
                "success": False,
                "message": str(e)
            }
    
    # ========== 状态查询 ==========
    
    def get_status(self) -> dict:
        """获取驱动状态"""
        return {
            "connected": self.connected,
            "driver_type": "WiFiDriver",
            "device_ip": self.device_ip,
            "port": self.DEFAULT_PORT,
            "logged_in": self.logged_in
        }


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== WiFiDriver 测试 ===\n")
    
    # 测试安全检查（不连接真实设备）
    driver = WiFiDriver()
    driver.connected = True  # 模拟已连接
    
    try:
        print("测试 1: 正常点击 (0.5, 0.5)")
        # 注意：这会失败因为没有真实设备，但会通过安全检查
        driver.tap(0.5, 0.5)
        print("✅ 安全检查通过\n")
    except SafetyError as e:
        print(f"❌ 失败: {e}\n")
    
    try:
        print("测试 2: 超出边界点击 (1.5, 0.5)")
        driver.tap(1.5, 0.5)
        print("❌ 未捕获异常\n")
    except SafetyError as e:
        print(f"✅ 正确捕获: {e}\n")
    
    try:
        print("测试 3: 滑动边界检查 (0.2, 0.2) -> (1.2, 0.5)")
        driver.swipe(0.2, 0.2, 1.2, 0.5)
        print("❌ 未捕获异常\n")
    except SafetyError as e:
        print(f"✅ 正确捕获: {e}\n")
    
    print("\n⚠️ 要测试真实连接，请使用:")
    print("driver = WiFiDriver(device_ip='192.168.1.100')")
    print("driver.connect()")
    
    print("\n=== 测试完成 ===")
