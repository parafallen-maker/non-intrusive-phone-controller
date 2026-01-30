#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AutoGLM Driver - The Hand-Eye Coordinator

持有 Camera 和 RoboticArm 的实例，实现微观闭环：
截图 → AutoGLM 规划 → 机械臂执行 → 验证 → 重试

核心方法: execute_step(goal: str, expect: str = None) -> StepResult

增强接口（支持 Long-horizon Planning）:
- ask(question: str) -> str: 询问当前界面状态
- checkpoint(description: str) -> bool: 验证检查点
"""

import os
import sys
import time
import base64
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from drivers.base_driver import BaseDriver

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== StepResult 数据类 ====================

@dataclass
class StepResult:
    """单步执行结果
    
    用于向策略层反馈执行状态，支持 Long-horizon Planning
    
    Attributes:
        success: 是否成功完成目标
        state: 当前界面状态描述（用于 LLM 判断下一步）
        has_more: 是否还有更多项目需要处理（用于循环控制）
        error: 错误信息（如果失败）
        retries: 重试次数
    """
    success: bool
    state: str = ""
    has_more: bool = False
    error: Optional[str] = None
    retries: int = 0
    
    def __bool__(self) -> bool:
        """允许直接用 if step_result: 判断成功"""
        return self.success
    
    def __str__(self) -> str:
        status = "✅" if self.success else "❌"
        state_preview = self.state[:50] + "..." if len(self.state) > 50 else self.state
        return f"StepResult({status} state='{state_preview}' has_more={self.has_more})"


class ActionType(Enum):
    """AutoGLM 支持的操作类型"""
    TAP = "Tap"
    SWIPE = "Swipe"
    LONG_PRESS = "Long_Press"
    DOUBLE_TAP = "Double_Tap"
    TYPE = "Type"
    BACK = "Back"
    HOME = "Home"
    WAIT = "Wait"
    SCROLL = "Scroll"
    TASK_FINISHED = "Task_finished"


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


class SafetyError(Exception):
    """安全检查失败"""
    pass


class MaxRetryError(Exception):
    """达到最大重试次数"""
    pass


class AutoGLMDriver:
    """AutoGLM 驱动 - 微观闭环控制器
    
    职责:
    1. 持有 Camera 和 RoboticArm 实例
    2. 实现 execute_step(goal) 微观闭环
    3. 内部自动重试和验证
    4. 输出结构化日志
    
    闭环流程:
    a. Capture: 截图
    b. Plan: 调用 AutoGLM API (输入截图+goal)，获取动作
    c. Act: 将动作转换为机械臂指令并执行
    d. Verify: 执行后 sleep(2.0)，再次截图，调用 AutoGLM 确认
    e. Retry: 如果失败，自动重试 1 次
    """
    
    def __init__(
        self,
        api_key: str,
        driver: BaseDriver,
        model: str = "autoglm-phone",
        max_retries: int = 2,
        verify_delay: float = 2.0
    ):
        """初始化
        
        Args:
            api_key: 智谱 API Key
            driver: 硬件驱动（Camera + RoboticArm）
            model: 模型名称
            max_retries: 最大重试次数
            verify_delay: 验证前等待时间（等待界面稳定）
        """
        self.api_key = api_key
        self.driver = driver
        self.model = model
        self.max_retries = max_retries
        self.verify_delay = verify_delay
        
        # 初始化 AutoGLM 客户端
        self.client = None
        self._init_client()
        
        # 统计
        self.total_steps = 0
        self.total_retries = 0
        
        logger.info(f"[AutoGLMDriver] 初始化完成，模型: {model}")
    
    def _init_client(self):
        """初始化 AutoGLM 客户端"""
        try:
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.api_key)
            logger.info("[AutoGLMDriver] ✅ AutoGLM 客户端初始化成功")
        except ImportError:
            logger.error("[AutoGLMDriver] ❌ zhipuai 未安装，请运行: pip install zhipuai")
        except Exception as e:
            logger.error(f"[AutoGLMDriver] ❌ 客户端初始化失败: {e}")
    
    def execute_step(self, goal: str, expect: str = None) -> StepResult:
        """执行单步操作 - 微观闭环
        
        Args:
            goal: 语义目标描述（如"点击搜索框"）
            expect: 期望的结果状态描述（可选，用于验证）
            
        Returns:
            StepResult: 包含执行状态和界面描述的结果对象
            
        Raises:
            SafetyError: 安全检查失败
            MaxRetryError: 达到最大重试次数
        """
        self.total_steps += 1
        step_id = self.total_steps
        
        logger.info("=" * 60)
        logger.info(f"[AutoGLMDriver] 步骤 #{step_id}: {goal}")
        if expect:
            logger.info(f"[AutoGLMDriver] 期望: {expect}")
        logger.info("=" * 60)
        
        retries_used = 0
        last_state = ""
        
        for attempt in range(self.max_retries):
            if attempt > 0:
                self.total_retries += 1
                retries_used = attempt
                logger.warning(f"[AutoGLMDriver] 🔄 重试 {attempt}/{self.max_retries-1}")
            
            try:
                # a. Capture: 截图
                logger.info(f"[AutoGLMDriver] 📸 a. Capture - 获取截图")
                screenshot = self.driver.screenshot()
                if screenshot is None:
                    logger.error("[AutoGLMDriver] ❌ 截图失败")
                    continue
                
                # b. Plan: 调用 AutoGLM
                logger.info(f"[AutoGLMDriver] 🧠 b. Plan - 调用 AutoGLM 分析")
                action = self._call_autoglm_plan(screenshot, goal)
                
                if action is None:
                    logger.error("[AutoGLMDriver] ❌ AutoGLM 规划失败")
                    continue
                
                logger.info(
                    f"[AutoGLMDriver]    → 动作: {action.action_type.value} | "
                    f"{action.reasoning}"
                )
                
                # c. Act: 执行动作
                logger.info(f"[AutoGLMDriver] 🤖 c. Act - 执行动作")
                self._execute_action(action)
                
                # d. Verify: 验证
                logger.info(
                    f"[AutoGLMDriver] ⏱️  d. Verify - 等待 {self.verify_delay}s 后验证"
                )
                time.sleep(self.verify_delay)
                
                new_screenshot = self.driver.screenshot()
                if new_screenshot is None:
                    logger.error("[AutoGLMDriver] ❌ 验证截图失败")
                    continue
                
                # 使用 expect 或 goal 进行验证
                verify_target = expect if expect else goal
                verified, state_desc = self._call_autoglm_verify_with_state(
                    new_screenshot, verify_target
                )
                last_state = state_desc
                
                if verified:
                    logger.info(f"[AutoGLMDriver] ✅ 步骤 #{step_id} 完成!")
                    # 检查是否还有更多项目
                    has_more = self._check_has_more(new_screenshot, goal)
                    return StepResult(
                        success=True,
                        state=state_desc,
                        has_more=has_more,
                        retries=retries_used
                    )
                else:
                    logger.warning(f"[AutoGLMDriver] ⚠️ 验证失败，准备重试")
                    continue
                    
            except SafetyError as e:
                logger.error(f"[AutoGLMDriver] 🚨 安全检查失败: {e}")
                raise
            except Exception as e:
                logger.error(f"[AutoGLMDriver] ❌ 执行异常: {e}")
                if attempt == self.max_retries - 1:
                    return StepResult(
                        success=False,
                        state=last_state,
                        error=str(e),
                        retries=retries_used
                    )
                continue
        
        # 所有重试都失败
        logger.error(f"[AutoGLMDriver] ❌ 步骤 #{step_id} 失败，已重试 {self.max_retries} 次")
        return StepResult(
            success=False,
            state=last_state,
            error=f"步骤 '{goal}' 达到最大重试次数",
            retries=retries_used
        )
    
    def _call_autoglm_plan(self, screenshot: bytes, goal: str) -> Optional[AutoGLMAction]:
        """调用 AutoGLM API 进行规划
        
        Args:
            screenshot: 截图 bytes
            goal: 目标描述
            
        Returns:
            AutoGLMAction 或 None
        """
        if not self.client:
            # Mock 模式
            logger.warning("[AutoGLMDriver] Mock 模式，返回假动作")
            return AutoGLMAction(
                action_type=ActionType.TAP,
                x=0.5,
                y=0.5,
                reasoning="Mock action"
            )
        
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        system_prompt = (
            "你是一个专业的手机操作助手。"
            "分析当前屏幕截图，根据用户目标，输出下一步操作。"
            "可用操作: Tap(x,y), Swipe(x1,y1,x2,y2), Type('文本'), Back, Home, Wait(秒)。"
            "坐标使用归一化值 (0.0-1.0)。"
            "只输出一个操作，不要输出多个步骤。"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": f"目标: {goal}\n请输出下一步操作。"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            logger.debug(f"[AutoGLMDriver] AutoGLM 响应: {content}")
            
            # 解析响应
            action = self._parse_action(content)
            return action
            
        except Exception as e:
            logger.error(f"[AutoGLMDriver] AutoGLM API 错误: {e}")
            return None
    
    def _call_autoglm_verify(self, screenshot: bytes, goal: str) -> bool:
        """调用 AutoGLM 验证操作是否成功
        
        Args:
            screenshot: 新截图 bytes
            goal: 原目标描述
            
        Returns:
            bool: 是否成功
        """
        if not self.client:
            # Mock 模式
            logger.warning("[AutoGLMDriver] Mock 模式，验证通过")
            return True
        
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        system_prompt = (
            "你是一个验证助手。"
            "上一步的操作目标是: '{goal}'。"
            "请分析当前截图，判断该操作是否已成功完成。"
            "只回答 'YES' 或 'NO'，并简要说明原因。"
        )
        
        messages = [
            {"role": "system", "content": system_prompt.format(goal=goal)},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": f"操作目标是: '{goal}'。当前界面是否符合预期？"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=200
            )
            
            content = response.choices[0].message.content.strip().upper()
            logger.debug(f"[AutoGLMDriver] 验证响应: {content}")
            
            # 判断是否成功
            if 'YES' in content or '成功' in content or '完成' in content:
                logger.info(f"[AutoGLMDriver] ✅ 验证通过: {content}")
                return True
            else:
                logger.warning(f"[AutoGLMDriver] ❌ 验证失败: {content}")
                return False
                
        except Exception as e:
            logger.error(f"[AutoGLMDriver] 验证 API 错误: {e}")
            # 验证失败时保守处理，返回 False
            return False
    
    def _call_autoglm_verify_with_state(
        self, screenshot: bytes, goal: str
    ) -> Tuple[bool, str]:
        """验证操作结果并返回状态描述
        
        Args:
            screenshot: 当前截图
            goal: 验证目标
            
        Returns:
            (是否成功, 状态描述)
        """
        if not self.client:
            # Mock 模式
            logger.warning("[AutoGLMDriver] Mock 模式，验证通过")
            return True, "Mock: 操作成功完成，界面显示正常"
        
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        system_prompt = (
            "你是一个验证助手。\n"
            "1. 判断操作目标 '{goal}' 是否已完成\n"
            "2. 用一句话描述当前界面状态\n\n"
            "输出格式:\n"
            "结果: YES/NO\n"
            "状态: <当前界面的简短描述>"
        )
        
        messages = [
            {"role": "system", "content": system_prompt.format(goal=goal)},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": f"请验证: '{goal}'"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=300
            )
            
            content = response.choices[0].message.content.strip()
            logger.debug(f"[AutoGLMDriver] 验证响应: {content}")
            
            # 解析结果
            success = 'YES' in content.upper() or '成功' in content or '完成' in content
            
            # 提取状态描述
            state_desc = "界面状态未知"
            if '状态:' in content:
                state_desc = content.split('状态:')[-1].strip()
            elif '\n' in content:
                state_desc = content.split('\n')[-1].strip()
            else:
                state_desc = content
            
            logger.info(f"[AutoGLMDriver] 验证: {'✅' if success else '❌'} | 状态: {state_desc}")
            return success, state_desc
            
        except Exception as e:
            logger.error(f"[AutoGLMDriver] 验证 API 错误: {e}")
            return False, f"验证失败: {e}"
    
    def _check_has_more(self, screenshot: bytes, context: str) -> bool:
        """检查是否还有更多项目需要处理
        
        用于支持循环操作的终止判断
        
        Args:
            screenshot: 当前截图
            context: 上下文描述
            
        Returns:
            bool: 是否还有更多项目
        """
        if not self.client:
            # Mock 模式，假设没有更多
            return False
        
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        system_prompt = (
            "分析当前界面，判断是否还有更多项目需要处理。\n"
            f"操作上下文: {context}\n\n"
            "只回答: YES (还有更多) 或 NO (没有更多)"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": "是否还有更多项目需要处理？"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=50
            )
            
            content = response.choices[0].message.content.strip().upper()
            has_more = 'YES' in content or '有' in content
            logger.debug(f"[AutoGLMDriver] has_more: {has_more}")
            return has_more
            
        except Exception as e:
            logger.error(f"[AutoGLMDriver] has_more 检查失败: {e}")
            return False
    
    def ask(self, question: str) -> str:
        """询问当前界面状态（支持 Long-horizon Planning）
        
        让策略层能够动态查询界面，做出判断
        
        Args:
            question: 问题（如"当前显示的是什么页面？"）
            
        Returns:
            str: 答案描述
            
        Example:
            >>> answer = driver.ask("屏幕上显示多少张照片？")
            >>> if "0" in answer:
            ...     print("没有照片了")
        """
        logger.info(f"[AutoGLMDriver] 📝 Ask: {question}")
        
        screenshot = self.driver.screenshot()
        if screenshot is None:
            return "错误：无法获取截图"
        
        if not self.client:
            # Mock 模式
            return f"Mock 回答: 关于 '{question}' 的答案"
        
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        messages = [
            {
                "role": "system",
                "content": "你是一个界面分析助手。根据截图回答用户问题，简洁准确。"
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": question
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=200
            )
            
            answer = response.choices[0].message.content.strip()
            logger.info(f"[AutoGLMDriver] 📝 Answer: {answer}")
            return answer
            
        except Exception as e:
            logger.error(f"[AutoGLMDriver] ask API 错误: {e}")
            return f"查询失败: {e}"
    
    def checkpoint(self, description: str) -> bool:
        """验证当前界面是否符合检查点描述（支持 Long-horizon Planning）
        
        用于在循环中验证状态，决定是否继续
        
        Args:
            description: 期望的状态描述（如"还有照片需要删除"）
            
        Returns:
            bool: 当前界面是否符合描述
            
        Example:
            >>> while driver.checkpoint("还有照片需要删除"):
            ...     driver.execute_step("删除第一张照片")
        """
        logger.info(f"[AutoGLMDriver] 🔍 Checkpoint: {description}")
        
        screenshot = self.driver.screenshot()
        if screenshot is None:
            logger.error("[AutoGLMDriver] 检查点：截图失败")
            return False
        
        if not self.client:
            # Mock 模式，默认返回 False（安全的选择）
            logger.warning("[AutoGLMDriver] Mock 模式，checkpoint 返回 False")
            return False
        
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个界面验证助手。\n"
                    "判断当前界面是否符合用户的描述。\n"
                    "只回答 YES 或 NO。"
                )
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                    },
                    {
                        "type": "text",
                        "text": f"当前界面是否符合: '{description}'？"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,
                max_tokens=50
            )
            
            content = response.choices[0].message.content.strip().upper()
            result = 'YES' in content or '是' in content or '符合' in content
            logger.info(f"[AutoGLMDriver] 🔍 Checkpoint 结果: {'✅' if result else '❌'}")
            return result
            
        except Exception as e:
            logger.error(f"[AutoGLMDriver] checkpoint API 错误: {e}")
            return False

    def _parse_action(self, content: str) -> Optional[AutoGLMAction]:
        """解析 AutoGLM 响应中的操作
        
        Args:
            content: 响应内容
            
        Returns:
            AutoGLMAction 或 None
        """
        import re
        
        content_lower = content.lower()
        
        # 解析 Tap(x, y)
        tap_match = re.search(r'tap\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', content_lower)
        if tap_match:
            return AutoGLMAction(
                action_type=ActionType.TAP,
                x=float(tap_match.group(1)),
                y=float(tap_match.group(2)),
                reasoning=content
            )
        
        # 解析 Swipe(x1, y1, x2, y2)
        swipe_match = re.search(
            r'swipe\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)',
            content_lower
        )
        if swipe_match:
            return AutoGLMAction(
                action_type=ActionType.SWIPE,
                x=float(swipe_match.group(1)),
                y=float(swipe_match.group(2)),
                end_x=float(swipe_match.group(3)),
                end_y=float(swipe_match.group(4)),
                reasoning=content
            )
        
        # 解析 Type('text')
        type_match = re.search(r"type\s*\(\s*['\"](.+?)['\"]\s*\)", content_lower)
        if type_match:
            return AutoGLMAction(
                action_type=ActionType.TYPE,
                text=type_match.group(1),
                reasoning=content
            )
        
        # 解析 Wait(seconds)
        wait_match = re.search(r'wait\s*\(\s*([\d.]+)\s*\)', content_lower)
        if wait_match:
            return AutoGLMAction(
                action_type=ActionType.WAIT,
                duration=float(wait_match.group(1)),
                reasoning=content
            )
        
        # 解析 Back
        if re.search(r'\bback\b', content_lower):
            return AutoGLMAction(
                action_type=ActionType.BACK,
                reasoning=content
            )
        
        # 解析 Home
        if re.search(r'\bhome\b', content_lower):
            return AutoGLMAction(
                action_type=ActionType.HOME,
                reasoning=content
            )
        
        logger.warning(f"[AutoGLMDriver] 无法解析操作: {content[:100]}")
        return None
    
    def _execute_action(self, action: AutoGLMAction):
        """执行单个操作
        
        Args:
            action: 操作对象
            
        Raises:
            SafetyError: 安全检查失败
        """
        action_type = action.action_type
        
        # 这里可以添加安全检查逻辑
        # 例如：检查坐标是否在安全范围内
        
        if action_type == ActionType.TAP:
            self.driver.tap(action.x, action.y)
        
        elif action_type == ActionType.SWIPE:
            self.driver.swipe(action.x, action.y, action.end_x, action.end_y)
        
        elif action_type == ActionType.LONG_PRESS:
            duration = action.duration or 1.0
            self.driver.long_press(action.x, action.y, duration)
        
        elif action_type == ActionType.DOUBLE_TAP:
            self.driver.double_tap(action.x, action.y)
        
        elif action_type == ActionType.TYPE:
            self.driver.type_text(action.text)
        
        elif action_type == ActionType.BACK:
            self.driver.back()
        
        elif action_type == ActionType.HOME:
            self.driver.home()
        
        elif action_type == ActionType.WAIT:
            time.sleep(action.duration or 1.0)
        
        elif action_type == ActionType.SCROLL:
            # 默认向下滚动
            self.driver.swipe(0.5, 0.7, 0.5, 0.3)
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            'total_steps': self.total_steps,
            'total_retries': self.total_retries
        }


# ==================== 便捷函数 ====================

def create_autoglm_driver(
    api_key: Optional[str] = None,
    driver: Optional[BaseDriver] = None
) -> AutoGLMDriver:
    """创建 AutoGLMDriver 的便捷函数
    
    Args:
        api_key: API Key (默认从环境变量读取)
        driver: 驱动 (默认使用 Mock)
        
    Returns:
        AutoGLMDriver
    """
    if api_key is None:
        api_key = os.getenv('ZHIPUAI_API_KEY', 'mock')
    
    if driver is None:
        from drivers.mock_driver import MockDriver
        driver = MockDriver()
    
    return AutoGLMDriver(api_key=api_key, driver=driver)


# ==================== 测试 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("AutoGLMDriver 测试")
    print("=" * 60)
    
    from drivers.mock_driver import MockDriver
    
    driver = MockDriver()
    autoglm_driver = create_autoglm_driver(driver=driver)
    
    # 测试单步
    print("\n测试 execute_step()...")
    try:
        result = autoglm_driver.execute_step("点击搜索框")
        print(f"✅ 结果: {result}")
    except MaxRetryError as e:
        print(f"❌ 失败: {e}")
    
    # 显示统计
    stats = autoglm_driver.get_stats()
    print(f"\n统计: {stats}")
