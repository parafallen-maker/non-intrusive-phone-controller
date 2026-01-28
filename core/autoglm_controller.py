#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AutoGLM 核心控制器

重构后的核心模块 - 直接使用 AutoGLM 的闭环控制

核心流程:
1. 截图
2. 发送截图+指令给 AutoGLM
3. AutoGLM 返回操作列表
4. 执行操作
5. 回到步骤1，直到任务完成
"""

import os
import sys
import time
import logging
import base64
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from drivers.base_driver import BaseDriver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    SCROLL = "Scroll"
    TAKE_OVER = "Take_over"
    TASK_FINISHED = "Task_finished"


@dataclass
class AutoGLMAction:
    """AutoGLM 返回的操作"""
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    reasoning: Optional[str] = None
    
    @property
    def action_type(self) -> ActionType:
        """获取操作类型枚举"""
        action_map = {
            'tap': ActionType.TAP,
            'swipe': ActionType.SWIPE,
            'long press': ActionType.LONG_PRESS,
            'longpress': ActionType.LONG_PRESS,
            'double tap': ActionType.DOUBLE_TAP,
            'doubletap': ActionType.DOUBLE_TAP,
            'type': ActionType.TYPE,
            'back': ActionType.BACK,
            'home': ActionType.HOME,
            'wait': ActionType.WAIT,
            'scroll': ActionType.SCROLL,
            'take_over': ActionType.TAKE_OVER,
            'task_finished': ActionType.TASK_FINISHED,
        }
        return action_map.get(self.action.lower(), ActionType.TAP)
    
    @property
    def x(self) -> Optional[float]:
        return self.params.get('x')
    
    @property
    def y(self) -> Optional[float]:
        return self.params.get('y')
    
    @property
    def end_x(self) -> Optional[float]:
        return self.params.get('end_x')
    
    @property
    def end_y(self) -> Optional[float]:
        return self.params.get('end_y')
    
    @property
    def text(self) -> Optional[str]:
        return self.params.get('text')
    
    @property
    def duration(self) -> Optional[float]:
        return self.params.get('duration')


@dataclass
class AutoGLMResponse:
    """AutoGLM 响应"""
    success: bool
    actions: List[AutoGLMAction]
    raw_response: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    session_id: Optional[str] = None


class AutoGLMController:
    """AutoGLM 核心控制器
    
    重构后的核心模块，直接使用 AutoGLM 进行闭环控制
    
    Usage:
        controller = AutoGLMController(api_key, driver)
        result = controller.execute_task("打开微信")
    """
    
    def __init__(
        self,
        api_key: str,
        driver: BaseDriver,
        model: str = "autoglm-phone",
        max_loops: int = 20,
        action_delay: float = 0.5
    ):
        """初始化
        
        Args:
            api_key: 智谱 API Key
            driver: 硬件驱动（用于截图和执行操作）
            model: 模型名称
            max_loops: 最大循环次数（每次循环可能执行多个动作）
            action_delay: 每个动作后的等待时间
        """
        self.api_key = api_key
        self.driver = driver
        self.model = model
        self.max_loops = max_loops
        self.action_delay = action_delay
        
        # 初始化客户端
        self.client = None
        self._init_client()
        
        # 执行历史
        self.history: List[Dict[str, Any]] = []
        
        # 统计
        self.total_actions = 0
        self.total_loops = 0
    
    def _init_client(self):
        """初始化 AutoGLM 客户端"""
        try:
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.api_key)
            logger.info(f"AutoGLM 客户端初始化成功，模型: {self.model}")
        except ImportError:
            logger.error("zhipuai 未安装，请运行: pip install zhipuai")
        except Exception as e:
            logger.error(f"AutoGLM 客户端初始化失败: {e}")
    
    def execute_task(self, instruction: str) -> Dict[str, Any]:
        """执行任务 - 核心闭环
        
        Args:
            instruction: 用户自然语言指令
            
        Returns:
            执行结果
        """
        self.history = []
        self.total_actions = 0
        loop_count = 0
        
        logger.info("=" * 60)
        logger.info(f"[AutoGLM] 开始执行任务: {instruction}")
        logger.info("=" * 60)
        
        while loop_count < self.max_loops:
            loop_count += 1
            logger.info(f"\n[AutoGLM] === 循环 {loop_count}/{self.max_loops} ===")
            
            # 1. 截图
            logger.info("[AutoGLM] 1. 获取截图...")
            screenshot = self.driver.screenshot()
            if screenshot is None:
                logger.error("[AutoGLM] 截图失败!")
                return {
                    'success': False,
                    'error': '截图失败',
                    'loops': loop_count,
                    'actions': self.total_actions
                }
            
            # 2. 调用 AutoGLM
            logger.info("[AutoGLM] 2. 调用 AutoGLM 分析...")
            response = self._call_autoglm(screenshot, instruction)
            
            if not response.success:
                logger.error(f"[AutoGLM] API 调用失败: {response.error}")
                return {
                    'success': False,
                    'error': response.error,
                    'loops': loop_count,
                    'actions': self.total_actions
                }
            
            # 3. 处理响应
            if not response.actions:
                logger.warning("[AutoGLM] 没有返回操作，继续循环...")
                continue
            
            # 4. 执行动作
            for i, action in enumerate(response.actions):
                action_type = action.action_type
                
                logger.info(
                    f"[AutoGLM] 3. 执行操作 [{i+1}/{len(response.actions)}]: "
                    f"{action.action} | {action.reasoning or ''}"
                )
                
                # 检查是否需要人工接管
                if action_type == ActionType.TAKE_OVER:
                    logger.warning(f"[AutoGLM] ⚠️ 请求人工接管: {action.reasoning}")
                    return {
                        'success': False,
                        'error': f'需要人工接管: {action.reasoning}',
                        'loops': loop_count,
                        'actions': self.total_actions
                    }
                
                # 检查是否任务完成
                if action_type == ActionType.TASK_FINISHED:
                    logger.info(f"[AutoGLM] ✅ 任务完成! 共 {loop_count} 次循环, {self.total_actions} 个操作")
                    return {
                        'success': True,
                        'loops': loop_count,
                        'actions': self.total_actions,
                        'history': self.history
                    }
                
                # 执行操作
                self._execute_action(action)
                self.total_actions += 1
                
                # 记录历史
                self.history.append({
                    'loop': loop_count,
                    'action': action.action,
                    'params': action.params,
                    'reasoning': action.reasoning
                })
                
                # 等待界面响应
                time.sleep(self.action_delay)
        
        # 达到最大循环次数
        logger.warning(f"[AutoGLM] ⚠️ 达到最大循环次数 {self.max_loops}")
        return {
            'success': False,
            'error': f'达到最大循环次数 {self.max_loops}',
            'loops': loop_count,
            'actions': self.total_actions,
            'history': self.history
        }
    
    def _call_autoglm(self, screenshot: bytes, instruction: str) -> AutoGLMResponse:
        """调用 AutoGLM API
        
        Args:
            screenshot: 截图 bytes
            instruction: 指令
            
        Returns:
            AutoGLMResponse
        """
        if not self.client:
            return AutoGLMResponse(
                success=False,
                actions=[],
                error="AutoGLM 客户端未初始化"
            )
        
        # 编码截图
        image_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        # 构建消息
        system_prompt = (
            "你是一个 AI 助手，通过机械臂控制 Android 手机。"
            "分析当前屏幕截图，提供下一步操作来完成用户任务。"
            "可用操作: Tap(x,y), Swipe(x1,y1,x2,y2), Type('文本'), Back, Home, Wait(秒), Take_over, Task_finished。"
            "坐标使用归一化值 (0.0-1.0)。"
            "如果任务完成，返回 Task_finished。"
            "如果无法继续，返回 Take_over 并说明原因。"
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
                        "text": f"当前屏幕如图所示。任务: {instruction}"
                    }
                ]
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=1000
            )
            
            raw_response = response.model_dump()
            content = response.choices[0].message.content
            
            logger.debug(f"AutoGLM 原始响应: {content}")
            
            # 解析操作
            actions = self._parse_actions(content)
            
            return AutoGLMResponse(
                success=True,
                actions=actions,
                raw_response=raw_response
            )
            
        except Exception as e:
            logger.error(f"AutoGLM API 错误: {e}")
            return AutoGLMResponse(
                success=False,
                actions=[],
                error=str(e)
            )
    
    def _parse_actions(self, content: str) -> List[AutoGLMAction]:
        """解析 AutoGLM 响应中的操作
        
        Args:
            content: 响应内容
            
        Returns:
            操作列表
        """
        import re
        actions = []
        
        content_lower = content.lower()
        
        # 检查任务完成
        if 'task_finished' in content_lower or '任务完成' in content:
            return [AutoGLMAction(action='Task_finished', reasoning=content)]
        
        # 检查人工接管
        if 'take_over' in content_lower or '人工接管' in content or '无法继续' in content:
            return [AutoGLMAction(action='Take_over', reasoning=content)]
        
        # 解析 Tap(x, y)
        tap_pattern = r'tap\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)'
        for match in re.finditer(tap_pattern, content_lower):
            actions.append(AutoGLMAction(
                action='Tap',
                params={'x': float(match.group(1)), 'y': float(match.group(2))},
                reasoning=self._extract_reasoning(content, match.group(0))
            ))
        
        # 解析 Swipe(x1, y1, x2, y2)
        swipe_pattern = r'swipe\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)'
        for match in re.finditer(swipe_pattern, content_lower):
            actions.append(AutoGLMAction(
                action='Swipe',
                params={
                    'x': float(match.group(1)),
                    'y': float(match.group(2)),
                    'end_x': float(match.group(3)),
                    'end_y': float(match.group(4))
                },
                reasoning=self._extract_reasoning(content, match.group(0))
            ))
        
        # 解析 Type('text')
        type_pattern = r"type\s*\(\s*['\"](.+?)['\"]\s*\)"
        for match in re.finditer(type_pattern, content_lower):
            actions.append(AutoGLMAction(
                action='Type',
                params={'text': match.group(1)},
                reasoning=self._extract_reasoning(content, match.group(0))
            ))
        
        # 解析 Wait(seconds)
        wait_pattern = r'wait\s*\(\s*([\d.]+)\s*\)'
        for match in re.finditer(wait_pattern, content_lower):
            actions.append(AutoGLMAction(
                action='Wait',
                params={'duration': float(match.group(1))},
                reasoning=self._extract_reasoning(content, match.group(0))
            ))
        
        # 解析 Back
        if re.search(r'\bback\b', content_lower):
            actions.append(AutoGLMAction(action='Back', reasoning='返回上一页'))
        
        # 解析 Home
        if re.search(r'\bhome\b', content_lower):
            actions.append(AutoGLMAction(action='Home', reasoning='返回主屏幕'))
        
        # 如果没有解析到任何操作，可能是自由格式
        if not actions:
            logger.warning(f"无法从响应中解析操作，尝试自由格式解析: {content[:200]}")
            # 可以添加更灵活的解析逻辑
        
        return actions
    
    def _extract_reasoning(self, content: str, action_str: str) -> Optional[str]:
        """从响应中提取操作的原因
        
        Args:
            content: 完整响应
            action_str: 操作字符串
            
        Returns:
            原因说明
        """
        # 简单实现：提取操作后的说明
        idx = content.lower().find(action_str)
        if idx >= 0:
            rest = content[idx + len(action_str):].strip()
            # 取第一句话
            for end_char in ['\n', '。', '.', '，', ',']:
                end_idx = rest.find(end_char)
                if end_idx > 0:
                    return rest[:end_idx].strip(' -')
            return rest[:100] if rest else None
        return None
    
    def _execute_action(self, action: AutoGLMAction):
        """执行单个操作
        
        Args:
            action: 操作对象
        """
        action_type = action.action_type
        
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
    
    def is_available(self) -> bool:
        """检查 AutoGLM 是否可用"""
        return self.client is not None


# ==================== 便捷函数 ====================

def create_controller(
    api_key: Optional[str] = None,
    driver: Optional[BaseDriver] = None
) -> AutoGLMController:
    """创建控制器的便捷函数
    
    Args:
        api_key: API Key (默认从环境变量读取)
        driver: 驱动 (默认使用 Mock)
        
    Returns:
        AutoGLMController
    """
    if api_key is None:
        api_key = os.getenv('ZHIPUAI_API_KEY')
    
    if driver is None:
        from drivers.mock_driver import MockDriver
        driver = MockDriver()
    
    return AutoGLMController(api_key=api_key, driver=driver)


# ==================== 测试 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("AutoGLM 核心控制器测试")
    print("=" * 60)
    
    # 检查 API Key
    api_key = os.getenv('ZHIPUAI_API_KEY')
    if not api_key or api_key == 'your_api_key_here':
        print("\n⚠️ 请配置 ZHIPUAI_API_KEY 环境变量")
        print("   export ZHIPUAI_API_KEY='your_actual_key'")
        print("\n使用 Mock 模式测试...")
        
        # Mock 测试
        from drivers.mock_driver import MockDriver
        driver = MockDriver()
        controller = AutoGLMController(api_key="mock", driver=driver)
        
        # 测试解析
        test_content = "Tap(0.5, 0.3) - 点击搜索框"
        actions = controller._parse_actions(test_content)
        print(f"\n解析测试: '{test_content}'")
        print(f"结果: {[a.action for a in actions]}")
        
    else:
        print(f"\n✅ 找到 API Key: {api_key[:10]}...")
        
        # 真实测试
        from drivers.mock_driver import MockDriver
        driver = MockDriver()
        controller = AutoGLMController(api_key=api_key, driver=driver)
        
        if controller.is_available():
            print("✅ AutoGLM 客户端初始化成功")
        else:
            print("❌ AutoGLM 客户端初始化失败")
