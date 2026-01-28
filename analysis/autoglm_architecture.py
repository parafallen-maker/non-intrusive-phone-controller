#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AutoGLM 架构分析与重构方案

核心发现:
===========

AutoGLM (autoglm-phone) 的实际能力:
- 输入: 截图 + 用户指令
- 输出: 单步操作指令 (Tap/Swipe/Type/Back/Home 等)
- 特点: 每次只输出一个操作，需要循环调用

当前架构问题:
============

1. 模型重复/混淆:
   - 策略层 Planner 使用 glm-4-flash 生成 Python 代码
   - 战术层 VisionAdapter 使用 glm-4v-flash 分析截图
   - 但实际的 autoglm-phone 才是专门的手机控制模型！

2. 流程断层:
   - 当前: 用户指令 → Planner(生成完整代码) → Runtime(执行) → step() → VisionAdapter
   - 实际应该: 用户指令 → AutoGLM(截图+指令) → 单步操作 → 执行 → 截图 → AutoGLM → ...

3. 正确的 AutoGLM 闭环:
   while not task_finished:
       screenshot = capture()
       action = autoglm(screenshot, instruction)
       execute(action)
       if action == "TaskFinished":
           break
"""

import os
import sys
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==================== AutoGLM 核心架构 ====================

class ActionType(Enum):
    """AutoGLM 支持的操作类型"""
    TAP = "Tap"
    SWIPE = "Swipe"
    LONG_PRESS = "Long Press"
    DOUBLE_TAP = "Double Tap"
    TYPE = "Type"
    BACK = "Back"
    HOME = "Home"
    WAIT = "Wait"
    TAKE_OVER = "Take_over"        # 请求人工接管
    TASK_FINISHED = "Task_finished"  # 任务完成


@dataclass
class AutoGLMAction:
    """AutoGLM 返回的操作"""
    action_type: ActionType
    x: Optional[float] = None      # 归一化坐标 0-1
    y: Optional[float] = None
    end_x: Optional[float] = None  # Swipe 终点
    end_y: Optional[float] = None
    text: Optional[str] = None     # Type 文本
    duration: Optional[float] = None
    reasoning: str = ""


class AutoGLMController:
    """AutoGLM 控制器 - 正确的闭环架构
    
    核心流程:
    1. 截图
    2. 发送截图+指令给 AutoGLM
    3. AutoGLM 返回单步操作
    4. 执行操作
    5. 回到步骤1，直到任务完成
    
    这才是 AutoGLM 的正确使用方式！
    """
    
    def __init__(
        self,
        api_key: str,
        driver: 'BaseDriver',
        max_steps: int = 50
    ):
        """初始化
        
        Args:
            api_key: 智谱 API Key
            driver: 硬件驱动（用于截图和执行操作）
            max_steps: 最大步骤数（防止无限循环）
        """
        self.api_key = api_key
        self.driver = driver
        self.max_steps = max_steps
        
        # 初始化 AutoGLM 客户端
        self.client = None
        self._init_client()
        
        # 执行历史
        self.history: List[AutoGLMAction] = []
    
    def _init_client(self):
        """初始化 AutoGLM 客户端"""
        try:
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.api_key)
        except ImportError:
            logger.warning("zhipuai not installed")
    
    def execute_task(self, instruction: str) -> Dict[str, Any]:
        """执行任务 - 核心闭环
        
        Args:
            instruction: 用户自然语言指令
            
        Returns:
            执行结果
        """
        self.history = []
        step_count = 0
        
        logger.info(f"[AutoGLM] 开始执行任务: {instruction}")
        
        while step_count < self.max_steps:
            step_count += 1
            logger.info(f"[AutoGLM] === 步骤 {step_count} ===")
            
            # 1. 截图
            screenshot = self.driver.screenshot()
            if screenshot is None:
                return {
                    'success': False,
                    'error': '截图失败',
                    'steps': step_count
                }
            
            # 2. 调用 AutoGLM
            action = self._call_autoglm(screenshot, instruction)
            self.history.append(action)
            
            logger.info(f"[AutoGLM] 操作: {action.action_type.value} | {action.reasoning}")
            
            # 3. 检查是否完成
            if action.action_type == ActionType.TASK_FINISHED:
                logger.info(f"[AutoGLM] ✅ 任务完成! 共 {step_count} 步")
                return {
                    'success': True,
                    'steps': step_count,
                    'history': self.history
                }
            
            if action.action_type == ActionType.TAKE_OVER:
                logger.warning(f"[AutoGLM] ⚠️ 请求人工接管: {action.reasoning}")
                return {
                    'success': False,
                    'error': f'需要人工接管: {action.reasoning}',
                    'steps': step_count
                }
            
            # 4. 执行操作
            self._execute_action(action)
            
            # 5. 等待界面稳定
            import time
            time.sleep(0.5)
        
        logger.warning(f"[AutoGLM] ⚠️ 达到最大步骤数 {self.max_steps}")
        return {
            'success': False,
            'error': f'达到最大步骤数 {self.max_steps}',
            'steps': step_count
        }
    
    def _call_autoglm(self, screenshot: bytes, instruction: str) -> AutoGLMAction:
        """调用 AutoGLM API
        
        Args:
            screenshot: 截图 bytes
            instruction: 指令
            
        Returns:
            AutoGLMAction
        """
        import base64
        
        if not self.client:
            # Mock 模式
            return AutoGLMAction(
                action_type=ActionType.TASK_FINISHED,
                reasoning="Mock mode"
            )
        
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": f"任务: {instruction}\n请分析当前屏幕，输出下一步操作。"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model="autoglm-phone",  # 关键: 使用专用模型
                messages=messages,
                temperature=0.1,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            return self._parse_response(content)
            
        except Exception as e:
            logger.error(f"AutoGLM API 错误: {e}")
            return AutoGLMAction(
                action_type=ActionType.TAKE_OVER,
                reasoning=f"API 错误: {str(e)}"
            )
    
    def _parse_response(self, text: str) -> AutoGLMAction:
        """解析 AutoGLM 响应"""
        # TODO: 根据实际 autoglm-phone 的输出格式解析
        # 这里是简化版
        
        text_lower = text.lower()
        
        if 'task_finished' in text_lower or '任务完成' in text_lower:
            return AutoGLMAction(
                action_type=ActionType.TASK_FINISHED,
                reasoning=text
            )
        
        if 'take_over' in text_lower or '人工' in text_lower:
            return AutoGLMAction(
                action_type=ActionType.TAKE_OVER,
                reasoning=text
            )
        
        # 解析 Tap(x, y)
        import re
        tap_match = re.search(r'tap\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', text_lower)
        if tap_match:
            return AutoGLMAction(
                action_type=ActionType.TAP,
                x=float(tap_match.group(1)),
                y=float(tap_match.group(2)),
                reasoning=text
            )
        
        # 解析 Swipe
        swipe_match = re.search(
            r'swipe\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)',
            text_lower
        )
        if swipe_match:
            return AutoGLMAction(
                action_type=ActionType.SWIPE,
                x=float(swipe_match.group(1)),
                y=float(swipe_match.group(2)),
                end_x=float(swipe_match.group(3)),
                end_y=float(swipe_match.group(4)),
                reasoning=text
            )
        
        # 默认返回需要人工接管
        return AutoGLMAction(
            action_type=ActionType.TAKE_OVER,
            reasoning=f"无法解析响应: {text}"
        )
    
    def _execute_action(self, action: AutoGLMAction):
        """执行操作"""
        if action.action_type == ActionType.TAP:
            self.driver.tap(action.x, action.y)
        elif action.action_type == ActionType.SWIPE:
            self.driver.swipe(action.x, action.y, action.end_x, action.end_y)
        elif action.action_type == ActionType.BACK:
            self.driver.back()
        elif action.action_type == ActionType.HOME:
            self.driver.home()
        elif action.action_type == ActionType.WAIT:
            import time
            time.sleep(action.duration or 1.0)


# ==================== 重构方案 ====================

"""
重构建议:
=========

1. 删除/简化策略层:
   - 不需要 Planner 生成 Python 代码
   - 不需要 TaskRuntime 沙盒执行
   - AutoGLM 本身就是"端到端"的

2. 核心改为 AutoGLM 闭环:
   ```
   AutoGLMController.execute_task(instruction)
       ↓
   while not finished:
       screenshot = driver.screenshot()
       action = autoglm(screenshot, instruction)
       driver.execute(action)
   ```

3. 保留的模块:
   - drivers/: 硬件驱动层（SerialDriver, WiFiDriver）
   - @safe_guard: 安全检查装饰器
   - 技能系统: 用于记录成功的执行轨迹

4. 简化的架构:
   ```
   用户指令
       ↓
   AutoGLMController (核心)
       ├── capture() → 截图
       ├── autoglm() → 获取操作
       └── execute() → 执行
       ↓
   BaseDriver (@safe_guard)
       ├── SerialDriver (机械臂)
       └── WiFiDriver (ESP32)
   ```

5. 技能系统的新角色:
   - 记录成功的执行轨迹
   - 提供给 AutoGLM 作为上下文参考
   - 不再是"生成代码"的来源
"""


# ==================== 测试 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("AutoGLM 架构分析")
    print("=" * 60)
    
    print("""
核心发现:
---------
AutoGLM (autoglm-phone) 是专门的手机控制模型:
  - 输入: 截图 + 指令
  - 输出: 单步操作 (Tap/Swipe/Type 等)
  - 需要循环调用，每次返回一个操作

当前问题:
---------
1. 使用了错误的模型:
   - Planner 用 glm-4-flash (文本模型)
   - VisionAdapter 用 glm-4v-flash (通用视觉)
   - 应该用 autoglm-phone (专用手机控制)

2. 架构过于复杂:
   - 不需要 "生成 Python 代码 → 执行" 
   - AutoGLM 本身就是端到端的

重构方向:
---------
1. 核心改为 AutoGLM 闭环:
   while not finished:
       screenshot = capture()
       action = autoglm(screenshot, instruction)
       execute(action)

2. 保留:
   - 硬件驱动层 (drivers/)
   - 安全检查 (@safe_guard)
   - 技能记录 (用于参考)

3. 删除:
   - Planner (代码生成)
   - TaskRuntime (沙盒执行)
   - step() 函数
""")
