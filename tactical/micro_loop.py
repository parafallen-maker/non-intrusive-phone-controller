#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微观闭环 (Micro Loop)
实现 Task 2.1: 战术闭环核心

流程: Capture → Predict → Act → Wait → Verify
这是系统的"心脏"，确保每一步都执行成功。
"""

import time
import logging
from typing import Optional, Callable
from dataclasses import dataclass
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入视觉适配器
try:
    from tactical.vision_adapter import VisionAdapter, MicroAction, ActionType
except ImportError:
    from vision_adapter import VisionAdapter, MicroAction, ActionType

# 导入驱动基类
try:
    from drivers.base_driver import BaseDriver, SafetyError, MockDriver
except ImportError:
    # 定义最小化的 Mock 类用于测试
    class SafetyError(Exception):
        pass
    
    class BaseDriver:
        def tap(self, x, y, **kwargs): pass
        def swipe(self, x1, y1, x2, y2, **kwargs): pass
        def double_tap(self, x, y, **kwargs): pass
        def long_press(self, x, y, **kwargs): pass
        def back(self): pass
        def home(self): pass
        def screenshot(self): return None
    
    class MockDriver(BaseDriver):
        def __init__(self):
            self.connected = False
        def connect(self, **kwargs):
            self.connected = True
            return True
        def disconnect(self):
            self.connected = False
        def tap(self, x, y, **kwargs):
            print(f"  [MockDriver] tap({x:.3f}, {y:.3f})")
        def swipe(self, x1, y1, x2, y2, **kwargs):
            print(f"  [MockDriver] swipe({x1:.3f}, {y1:.3f}) -> ({x2:.3f}, {y2:.3f})")
        def back(self):
            print("  [MockDriver] back()")
        def home(self):
            print("  [MockDriver] home()")


logger = logging.getLogger(__name__)


class StepFailedError(Exception):
    """单步执行失败异常"""
    def __init__(self, goal: str, reason: str, attempts: int):
        self.goal = goal
        self.reason = reason
        self.attempts = attempts
        super().__init__(f"Step failed after {attempts} attempts: {goal} - {reason}")


@dataclass
class StepResult:
    """单步执行结果"""
    success: bool
    action: Optional[MicroAction] = None
    error: Optional[str] = None
    attempts: int = 1
    execution_time: float = 0.0


def execute_step(
    goal: str,
    driver: BaseDriver,
    vision: VisionAdapter,
    capture_func: Optional[Callable[[], bytes]] = None,
    max_retries: int = 1,
    cooldown: float = 1.5,
    verify: bool = True
) -> StepResult:
    """执行单步目标 - Task 2.1 核心函数
    
    这是战术层的核心闭环，包含:
    1. Capture: 截图获取当前屏幕状态
    2. Predict: 调用 AutoGLM 预测动作
    3. Act: 驱动机械臂执行动作
    4. Wait: 物理冷却等待
    5. Verify: 再次截图确认目标达成
    
    Args:
        goal: 语义目标描述 (如 "点击设置按钮")
        driver: 机械臂驱动实例
        vision: 视觉适配器实例
        capture_func: 截图函数，返回 bytes。如果为 None 则尝试使用 driver.screenshot()
        max_retries: 最大重试次数
        cooldown: 动作后冷却时间（秒）
        verify: 是否执行验证步骤
        
    Returns:
        StepResult: 执行结果
        
    Raises:
        StepFailedError: 重试后仍失败
        SafetyError: 动作超出安全边界
    """
    start_time = time.time()
    attempts = 0
    last_error = None
    last_action = None
    
    # 确定截图函数
    if capture_func is None:
        capture_func = driver.screenshot
    
    while attempts <= max_retries:
        attempts += 1
        logger.info(f"[Step] Attempt {attempts}/{max_retries + 1}: {goal}")
        
        try:
            # ========== 1. CAPTURE ==========
            logger.info("[Step] Phase 1: Capture")
            screenshot = capture_func()
            if screenshot is None:
                logger.warning("Screenshot returned None, using empty bytes")
                screenshot = b""
            
            # ========== 2. PREDICT ==========
            logger.info("[Step] Phase 2: Predict")
            action = vision.predict(screenshot, goal)
            last_action = action
            logger.info(f"[Step] Predicted: {action}")
            
            # 检查是否需要人工接管
            if action.type == ActionType.TAKE_OVER:
                raise StepFailedError(goal, "AI requested human takeover", attempts)
            
            # 检查任务是否已完成
            if action.type == ActionType.TASK_FINISHED:
                logger.info("[Step] Task reported as finished")
                return StepResult(
                    success=True,
                    action=action,
                    attempts=attempts,
                    execution_time=time.time() - start_time
                )
            
            # ========== 3. ACT ==========
            logger.info("[Step] Phase 3: Act")
            _execute_action(driver, action)
            
            # ========== 4. WAIT ==========
            logger.info(f"[Step] Phase 4: Wait ({cooldown}s cooldown)")
            time.sleep(cooldown)
            
            # ========== 5. VERIFY ==========
            if verify:
                logger.info("[Step] Phase 5: Verify")
                verify_screenshot = capture_func()
                if verify_screenshot is None:
                    verify_screenshot = b""
                
                is_success = vision.verify(verify_screenshot, goal, action)
                
                if is_success:
                    logger.info("[Step] ✅ Verification passed")
                    return StepResult(
                        success=True,
                        action=action,
                        attempts=attempts,
                        execution_time=time.time() - start_time
                    )
                else:
                    logger.warning("[Step] ⚠️ Verification failed, will retry")
                    last_error = "Verification failed"
                    continue
            else:
                # 不验证，直接返回成功
                return StepResult(
                    success=True,
                    action=action,
                    attempts=attempts,
                    execution_time=time.time() - start_time
                )
                
        except SafetyError as e:
            # 安全错误不重试，直接抛出
            logger.error(f"[Step] 🛑 Safety error: {e}")
            raise
            
        except StepFailedError:
            raise
            
        except Exception as e:
            logger.error(f"[Step] Error: {e}")
            last_error = str(e)
            if attempts <= max_retries:
                logger.info(f"[Step] Retrying in {cooldown}s...")
                time.sleep(cooldown)
    
    # 所有重试都失败
    raise StepFailedError(goal, last_error or "Unknown error", attempts)


def _execute_action(driver: BaseDriver, action: MicroAction):
    """执行 MicroAction 到驱动
    
    Args:
        driver: 机械臂驱动
        action: 要执行的动作
    """
    if action.type == ActionType.TAP:
        x, y = action.coords
        driver.tap(x, y)
        
    elif action.type == ActionType.DOUBLE_TAP:
        x, y = action.coords
        driver.double_tap(x, y)
        
    elif action.type == ActionType.LONG_PRESS:
        x, y = action.coords
        duration = action.details.get("duration_ms", 2000)
        driver.long_press(x, y, duration_ms=duration)
        
    elif action.type == ActionType.SWIPE:
        x1, y1, x2, y2 = action.coords
        driver.swipe(x1, y1, x2, y2)
        
    elif action.type == ActionType.TYPE:
        text = action.details.get("text", "")
        logger.info(f"[Action] Type text: {text}")
        # TODO: 需要键盘输入支持
        
    elif action.type == ActionType.BACK:
        driver.back()
        
    elif action.type == ActionType.HOME:
        driver.home()
        
    elif action.type == ActionType.WAIT:
        seconds = action.details.get("seconds", 2.0)
        logger.info(f"[Action] Wait {seconds}s")
        time.sleep(seconds)
        
    elif action.type == ActionType.TAKE_OVER:
        logger.warning("[Action] Human takeover requested")
        
    elif action.type == ActionType.TASK_FINISHED:
        logger.info("[Action] Task finished")
        
    else:
        logger.warning(f"[Action] Unknown action type: {action.type}")


# ========== 便捷包装函数 ==========

def step(goal: str) -> bool:
    """简化的 step 函数（用于 Runtime 注入）
    
    这个函数会在 TaskRuntime 中被绑定到具体的 driver 和 vision。
    
    Args:
        goal: 语义目标
        
    Returns:
        bool: 是否成功
    """
    # 这个函数在实际使用时会被 TaskRuntime 替换
    raise NotImplementedError(
        "step() must be called within TaskRuntime context. "
        "Use execute_step() directly for standalone usage."
    )


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== Task 2.1 Micro Loop 测试 ===\n")
    
    # 使用内置 MockDriver
    driver = MockDriver()
    driver.connect()
    
    vision = VisionAdapter(mock=True)
    
    # 测试用例
    test_goals = [
        "点击设置按钮",
        "向下滑动查看更多",
        "返回上一页",
    ]
    
    for goal in test_goals:
        print(f"\n--- 执行: {goal} ---")
        try:
            result = execute_step(
                goal=goal,
                driver=driver,
                vision=vision,
                capture_func=lambda: b"mock_screenshot",
                max_retries=1,
                cooldown=0.5,  # 测试时缩短冷却时间
                verify=True
            )
            print(f"✅ 成功! 动作: {result.action}, 尝试次数: {result.attempts}")
        except StepFailedError as e:
            print(f"❌ 失败: {e}")
        except SafetyError as e:
            print(f"🛑 安全错误: {e}")
    
    driver.disconnect()
    print("\n=== 测试完成 ===")
