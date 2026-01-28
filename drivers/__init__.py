"""
驱动模块 - 统一的硬件抽象层

支持的驱动:
- SerialDriver: 串口机械臂控制 (基于 GRBL)
- WiFiDriver: WiFi/ESP32-S3 网络控制
- MockDriver: 模拟驱动 (测试用)
"""

from .base_driver import BaseDriver, SafetyError, safe_guard, MockDriver

# 延迟导入 SerialDriver 和 WiFiDriver，避免依赖问题
def __getattr__(name):
    if name == 'SerialDriver':
        from .serial_driver import SerialDriver
        return SerialDriver
    elif name == 'WiFiDriver':
        from .wifi_driver import WiFiDriver
        return WiFiDriver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'BaseDriver',
    'SafetyError',
    'safe_guard',
    'MockDriver',
    'SerialDriver',
    'WiFiDriver',
]
