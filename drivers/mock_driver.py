#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Mock Driver for testing
"""

import os
import logging
from typing import Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockDriver:
    """Mock 驱动用于测试
    
    模拟所有硬件操作，返回假数据
    """
    
    def __init__(self):
        """初始化 Mock 驱动"""
        self.actions_log = []
        logger.info("[MockDriver] 初始化完成")
    
    def screenshot(self) -> bytes:
        """获取截图 (返回假数据)"""
        # 返回一个 1x1 像素的 PNG
        # PNG 签名 + IHDR + IDAT + IEND
        logger.info("[MockDriver] screenshot()")
        
        # 简单的测试图像数据
        fake_image = (
            b'\x89PNG\r\n\x1a\n'  # PNG signature
            b'\x00\x00\x00\rIHDR'
            b'\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
            b'\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return fake_image
    
    def tap(self, x: float, y: float):
        """点击
        
        Args:
            x: 归一化 x 坐标 (0-1)
            y: 归一化 y 坐标 (0-1)
        """
        logger.info(f"[MockDriver] tap({x:.3f}, {y:.3f})")
        self.actions_log.append(('tap', x, y))
    
    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration: float = 0.3):
        """滑动
        
        Args:
            x1, y1: 起点坐标
            x2, y2: 终点坐标
            duration: 持续时间
        """
        logger.info(f"[MockDriver] swipe({x1:.3f}, {y1:.3f} -> {x2:.3f}, {y2:.3f})")
        self.actions_log.append(('swipe', x1, y1, x2, y2))
    
    def long_press(self, x: float, y: float, duration: float = 1.0):
        """长按
        
        Args:
            x, y: 坐标
            duration: 持续时间
        """
        logger.info(f"[MockDriver] long_press({x:.3f}, {y:.3f}, {duration}s)")
        self.actions_log.append(('long_press', x, y, duration))
    
    def double_tap(self, x: float, y: float):
        """双击
        
        Args:
            x, y: 坐标
        """
        logger.info(f"[MockDriver] double_tap({x:.3f}, {y:.3f})")
        self.actions_log.append(('double_tap', x, y))
    
    def type_text(self, text: str):
        """输入文本
        
        Args:
            text: 要输入的文本
        """
        logger.info(f"[MockDriver] type_text('{text}')")
        self.actions_log.append(('type_text', text))
    
    def back(self):
        """返回键"""
        logger.info("[MockDriver] back()")
        self.actions_log.append(('back',))
    
    def home(self):
        """主页键"""
        logger.info("[MockDriver] home()")
        self.actions_log.append(('home',))
    
    def get_actions_log(self):
        """获取操作日志"""
        return self.actions_log
    
    def clear_log(self):
        """清除日志"""
        self.actions_log = []


if __name__ == '__main__':
    # 测试
    driver = MockDriver()
    
    print("测试 MockDriver...")
    driver.tap(0.5, 0.3)
    driver.swipe(0.5, 0.7, 0.5, 0.3)
    driver.type_text("测试文本")
    driver.back()
    
    print(f"\n操作日志: {driver.get_actions_log()}")
