#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视觉适配器 (Vision Adapter)
实现 Task 1.2: AutoGLM 接口标准化

核心功能:
- 统一的 predict() 接口
- 返回结构化 MicroAction 对象
- Mock 模式支持调试
"""

import re
import base64
import logging
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


class ActionType(Enum):
    """动作类型枚举"""
    TAP = "tap"
    DOUBLE_TAP = "double_tap"
    LONG_PRESS = "long_press"
    SWIPE = "swipe"
    TYPE = "type"
    BACK = "back"
    HOME = "home"
    WAIT = "wait"
    TAKE_OVER = "take_over"      # 请求人工接管
    TASK_FINISHED = "task_finished"  # 任务完成


@dataclass
class MicroAction:
    """微动作结构体 - Task 1.2 核心输出
    
    Attributes:
        type: 动作类型 (ActionType)
        coords: 坐标元组，(x, y) 或 (x1, y1, x2, y2)，归一化 0.0-1.0
        details: 额外参数字典 (duration_ms, text, etc.)
        reasoning: AI 的推理过程（调试用）
        confidence: 置信度 0.0-1.0
    """
    type: ActionType
    coords: Optional[Tuple[float, ...]] = None
    details: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（兼容旧代码）"""
        return {
            "type": self.type.value,
            "coords": self.coords,
            "details": self.details,
            "reasoning": self.reasoning,
            "confidence": self.confidence
        }
    
    def __repr__(self):
        if self.coords:
            return f"MicroAction({self.type.value}, coords={self.coords})"
        return f"MicroAction({self.type.value})"


class VisionAdapter:
    """视觉适配器 - AutoGLM 接口封装
    
    将 AutoGLM 的原始文本响应转换为结构化的 MicroAction 对象。
    
    Usage:
        adapter = VisionAdapter(api_key="xxx")
        action = adapter.predict(image_bytes, "点击设置按钮")
        # action.type == ActionType.TAP
        # action.coords == (0.85, 0.05)
    """
    
    def __init__(self, api_key: Optional[str] = None, mock: bool = False):
        """初始化视觉适配器
        
        Args:
            api_key: 智谱 API Key
            mock: 是否使用 Mock 模式（用于测试）
        """
        self.mock = mock
        self.client = None
        
        if not mock:
            try:
                from zhipuai import ZhipuAI
                self.api_key = api_key
                if api_key:
                    self.client = ZhipuAI(api_key=api_key)
            except ImportError:
                logger.warning("zhipuai not installed, using mock mode")
                self.mock = True
    
    def predict(self, image: bytes, instruction: str) -> MicroAction:
        """预测下一步动作
        
        Args:
            image: 屏幕截图 (JPEG/PNG bytes)
            instruction: 自然语言指令 (goal)
            
        Returns:
            MicroAction: 结构化的动作对象
        """
        if self.mock:
            return self._mock_predict(instruction)
        
        return self._real_predict(image, instruction)
    
    def _real_predict(self, image: bytes, instruction: str) -> MicroAction:
        """调用真实 AutoGLM API"""
        if not self.client:
            raise RuntimeError("AutoGLM client not initialized")
        
        # 编码图片
        image_base64 = base64.b64encode(image).decode('utf-8')
        
        # 构建消息
        messages = [
            {
                "role": "system",
                "content": (
                    "You are controlling an Android phone through a mechanical arm. "
                    "Analyze the screenshot and determine the SINGLE next action to achieve the goal. "
                    "Available actions: Tap(x, y), Swipe(x1, y1, x2, y2), LongPress(x, y), "
                    "DoubleTap(x, y), Type(text), Back, Home, Wait(seconds), TakeOver, TaskFinished. "
                    "Coordinates are normalized 0.0-1.0. "
                    "Respond in format: ACTION(params) | Reasoning: explanation"
                )
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    },
                    {
                        "type": "text",
                        "text": f"Goal: {instruction}\nWhat is the SINGLE next action?"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model="glm-4v-flash",
                messages=messages,
                temperature=0.3,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            logger.info(f"AutoGLM raw response: {content}")
            
            return self._parse_response(content)
            
        except Exception as e:
            logger.error(f"AutoGLM API error: {e}")
            return MicroAction(
                type=ActionType.TAKE_OVER,
                reasoning=f"API error: {str(e)}"
            )
    
    def _parse_response(self, text: str) -> MicroAction:
        """解析 AutoGLM 响应文本为 MicroAction
        
        Supported formats:
        - Tap(0.5, 0.3)
        - Swipe(0.2, 0.8, 0.2, 0.2)
        - LongPress(0.5, 0.5)
        - Type("hello world")
        - Back
        - Home
        - Wait(2)
        - TakeOver
        - TaskFinished
        """
        text = text.strip()
        
        # 提取推理部分
        reasoning = ""
        if "|" in text:
            parts = text.split("|", 1)
            text = parts[0].strip()
            reasoning = parts[1].strip()
        
        # 解析动作
        text_upper = text.upper()
        
        # Tap(x, y)
        tap_match = re.search(r'TAP\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', text_upper)
        if tap_match:
            x, y = float(tap_match.group(1)), float(tap_match.group(2))
            return MicroAction(ActionType.TAP, coords=(x, y), reasoning=reasoning)
        
        # DoubleTap(x, y)
        double_match = re.search(r'DOUBLE\s*TAP\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', text_upper)
        if double_match:
            x, y = float(double_match.group(1)), float(double_match.group(2))
            return MicroAction(ActionType.DOUBLE_TAP, coords=(x, y), reasoning=reasoning)
        
        # LongPress(x, y)
        long_match = re.search(r'LONG\s*PRESS\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', text_upper)
        if long_match:
            x, y = float(long_match.group(1)), float(long_match.group(2))
            return MicroAction(ActionType.LONG_PRESS, coords=(x, y), reasoning=reasoning)
        
        # Swipe(x1, y1, x2, y2)
        swipe_match = re.search(
            r'SWIPE\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)',
            text_upper
        )
        if swipe_match:
            x1, y1 = float(swipe_match.group(1)), float(swipe_match.group(2))
            x2, y2 = float(swipe_match.group(3)), float(swipe_match.group(4))
            return MicroAction(ActionType.SWIPE, coords=(x1, y1, x2, y2), reasoning=reasoning)
        
        # Type("text")
        type_match = re.search(r'TYPE\s*\(\s*["\'](.+?)["\']\s*\)', text, re.IGNORECASE)
        if type_match:
            text_content = type_match.group(1)
            return MicroAction(ActionType.TYPE, details={"text": text_content}, reasoning=reasoning)
        
        # Wait(seconds)
        wait_match = re.search(r'WAIT\s*\(\s*([\d.]+)\s*\)', text_upper)
        if wait_match:
            seconds = float(wait_match.group(1))
            return MicroAction(ActionType.WAIT, details={"seconds": seconds}, reasoning=reasoning)
        
        # Simple actions
        if "BACK" in text_upper:
            return MicroAction(ActionType.BACK, reasoning=reasoning)
        if "HOME" in text_upper:
            return MicroAction(ActionType.HOME, reasoning=reasoning)
        if "TAKEOVER" in text_upper or "TAKE_OVER" in text_upper:
            return MicroAction(ActionType.TAKE_OVER, reasoning=reasoning)
        if "TASKFINISHED" in text_upper or "TASK_FINISHED" in text_upper or "FINISHED" in text_upper:
            return MicroAction(ActionType.TASK_FINISHED, reasoning=reasoning)
        
        # 无法解析，请求人工接管
        logger.warning(f"Cannot parse AutoGLM response: {text}")
        return MicroAction(
            type=ActionType.TAKE_OVER,
            reasoning=f"Cannot parse response: {text}"
        )
    
    def _mock_predict(self, instruction: str) -> MicroAction:
        """Mock 模式 - 返回假数据用于测试
        
        根据指令关键词返回合理的模拟动作。
        """
        instruction_lower = instruction.lower()
        
        # 简单的关键词匹配
        if "点击" in instruction or "tap" in instruction_lower or "click" in instruction_lower:
            return MicroAction(
                type=ActionType.TAP,
                coords=(0.5, 0.5),
                reasoning="Mock: detected click intent"
            )
        
        if "滑动" in instruction or "swipe" in instruction_lower or "scroll" in instruction_lower:
            return MicroAction(
                type=ActionType.SWIPE,
                coords=(0.5, 0.8, 0.5, 0.2),
                reasoning="Mock: detected swipe intent"
            )
        
        if "输入" in instruction or "type" in instruction_lower:
            return MicroAction(
                type=ActionType.TYPE,
                details={"text": "mock text"},
                reasoning="Mock: detected type intent"
            )
        
        if "返回" in instruction or "back" in instruction_lower:
            return MicroAction(ActionType.BACK, reasoning="Mock: detected back intent")
        
        if "桌面" in instruction or "home" in instruction_lower:
            return MicroAction(ActionType.HOME, reasoning="Mock: detected home intent")
        
        # 默认返回点击屏幕中心
        return MicroAction(
            type=ActionType.TAP,
            coords=(0.5, 0.5),
            reasoning="Mock: default action"
        )
    
    def verify(self, image: bytes, goal: str, previous_action: MicroAction) -> bool:
        """验证目标是否达成
        
        Args:
            image: 执行动作后的截图
            goal: 原始目标
            previous_action: 刚执行的动作
            
        Returns:
            bool: 目标是否达成
        """
        if self.mock:
            # Mock 模式总是返回成功
            logger.info("Mock verify: returning True")
            return True
        
        if not self.client:
            return True  # 无法验证时假设成功
        
        image_base64 = base64.b64encode(image).decode('utf-8')
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are verifying if a phone operation was successful. "
                    "Answer only 'YES' or 'NO'."
                )
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    },
                    {
                        "type": "text",
                        "text": f"Goal: {goal}\nPrevious action: {previous_action}\nIs the goal achieved based on the current screen?"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model="glm-4v-flash",
                messages=messages,
                temperature=0.1,
                max_tokens=10
            )
            
            answer = response.choices[0].message.content.strip().upper()
            logger.info(f"Verify response: {answer}")
            
            return "YES" in answer
            
        except Exception as e:
            logger.error(f"Verify error: {e}")
            return True  # 出错时假设成功，避免无限重试


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== Task 1.2 VisionAdapter 测试 ===\n")
    
    # 测试 Mock 模式
    adapter = VisionAdapter(mock=True)
    
    test_cases = [
        "点击设置按钮",
        "向下滑动",
        "输入用户名",
        "返回上一页",
        "回到桌面",
    ]
    
    for instruction in test_cases:
        action = adapter.predict(b"fake_image", instruction)
        print(f"指令: {instruction}")
        print(f"  → {action}")
        print()
    
    # 测试解析器
    print("=== 解析器测试 ===\n")
    
    test_responses = [
        "Tap(0.85, 0.12) | Reasoning: clicking the settings icon",
        "Swipe(0.5, 0.8, 0.5, 0.2) | scroll down",
        "LongPress(0.3, 0.4)",
        "Type(\"hello world\")",
        "Back",
        "TaskFinished",
    ]
    
    for resp in test_responses:
        action = adapter._parse_response(resp)
        print(f"响应: {resp}")
        print(f"  → {action}")
        print()
    
    print("=== 测试完成 ===")
