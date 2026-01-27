#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
集成测试 (Integration Test)
实现 Task 6.1: 端到端测试

测试完整流程:
用户指令 → Planner → TaskRuntime → MicroLoop → Driver
"""

import sys
import os
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ========== 配置日志 ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ========== Mock 组件 ==========

@dataclass
class MockScreenState:
    """模拟屏幕状态"""
    app: str = "launcher"
    screen: str = "home"
    items: List[str] = None
    
    def __post_init__(self):
        if self.items is None:
            self.items = []


class MockVisionAdapter:
    """模拟视觉适配器"""
    
    def __init__(self):
        self.state = MockScreenState()
        self.action_history = []
        
    def predict(self, screenshot: bytes, goal: str) -> Dict[str, Any]:
        """模拟预测动作"""
        logger.info(f"[MockVision] predict: {goal}")
        
        # 根据目标返回模拟动作
        if "打开" in goal:
            app_name = goal.replace("打开", "").strip()
            return {
                "action_type": "tap",
                "description": f"点击 {app_name} 图标",
                "target": app_name,
                "confidence": 0.95
            }
        
        if "点击" in goal:
            target = goal.replace("点击", "").strip()
            return {
                "action_type": "tap",
                "description": f"点击 {target}",
                "target": target,
                "confidence": 0.92
            }
        
        if "滑动" in goal or "向下" in goal or "向上" in goal:
            direction = "up" if "向上" in goal else "down"
            return {
                "action_type": "swipe",
                "description": f"向{'上' if direction == 'up' else '下'}滑动",
                "direction": direction,
                "confidence": 0.98
            }
        
        return {
            "action_type": "tap",
            "description": goal,
            "confidence": 0.8
        }
    
    def verify(self, screenshot: bytes, expected: str) -> Dict[str, Any]:
        """模拟验证结果"""
        logger.info(f"[MockVision] verify: {expected}")
        
        # 模拟 90% 成功率
        import random
        success = random.random() < 0.9
        
        return {
            "success": success,
            "actual": expected if success else "未知状态",
            "confidence": 0.88 if success else 0.4
        }


class MockDriver:
    """模拟驱动器"""
    
    def __init__(self):
        self.action_log = []
        
    def tap(self, x: int, y: int) -> bool:
        """模拟点击"""
        logger.info(f"[MockDriver] tap({x}, {y})")
        self.action_log.append(("tap", x, y))
        return True
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        """模拟滑动"""
        logger.info(f"[MockDriver] swipe({x1}, {y1}) -> ({x2}, {y2})")
        self.action_log.append(("swipe", x1, y1, x2, y2))
        return True
    
    def screenshot(self) -> bytes:
        """模拟截图"""
        logger.info("[MockDriver] screenshot()")
        return b"mock_screenshot_data"
    
    def home(self) -> bool:
        """返回桌面"""
        logger.info("[MockDriver] home()")
        self.action_log.append(("home",))
        return True


# ========== 简化版集成执行器 ==========

class IntegrationRunner:
    """集成测试运行器
    
    模拟完整流程:
    1. Planner 生成代码
    2. TaskRuntime 执行代码
    3. step() 调用 MicroLoop
    """
    
    def __init__(self):
        self.driver = MockDriver()
        self.vision = MockVisionAdapter()
        self.step_results = []
        
    def execute_instruction(self, instruction: str) -> Dict[str, Any]:
        """执行用户指令
        
        Args:
            instruction: 自然语言指令
            
        Returns:
            执行结果
        """
        logger.info(f"\n{'='*50}")
        logger.info(f"[Integration] 开始执行: {instruction}")
        logger.info(f"{'='*50}\n")
        
        result = {
            "instruction": instruction,
            "success": False,
            "steps_executed": 0,
            "steps_succeeded": 0,
            "code": None,
            "error": None
        }
        
        try:
            # Step 1: Planner 生成代码
            from runtime.planner import Planner
            planner = Planner(provider='mock')
            plan_result = planner.plan(instruction)
            
            if not plan_result.success:
                result["error"] = f"Plan failed: {plan_result.error}"
                return result
            
            result["code"] = plan_result.code
            logger.info(f"[Integration] 生成的代码:\n{plan_result.code}\n")
            
            # Step 2: TaskRuntime 执行代码
            from runtime.task_runtime import TaskRuntime
            
            # 定义 step 函数
            def step(goal: str) -> bool:
                """模拟步骤执行"""
                logger.info(f"[Step] 执行: {goal}")
                self.step_results.append({"goal": goal})
                result["steps_executed"] += 1
                
                # 模拟 MicroLoop
                screenshot = self.driver.screenshot()
                action = self.vision.predict(screenshot, goal)
                
                # 执行动作
                if action["action_type"] == "tap":
                    self.driver.tap(100, 200)  # 模拟坐标
                elif action["action_type"] == "swipe":
                    if action.get("direction") == "up":
                        self.driver.swipe(200, 400, 200, 100)
                    else:
                        self.driver.swipe(200, 100, 200, 400)
                
                # 验证
                verify_result = self.vision.verify(screenshot, goal)
                if verify_result["success"]:
                    result["steps_succeeded"] += 1
                    return True
                else:
                    logger.warning(f"[Step] 验证失败: {goal}")
                    return True  # 继续执行
            
            runtime = TaskRuntime(step_function=step)
            exec_result = runtime.execute(plan_result.code)
            
            if not exec_result.success:
                result["error"] = exec_result.error
                return result
            
            result["success"] = True
            logger.info(f"\n[Integration] ✅ 执行完成")
            logger.info(f"[Integration] 步骤: {result['steps_executed']} 执行, {result['steps_succeeded']} 成功")
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"[Integration] ❌ 执行失败: {e}")
            import traceback
            traceback.print_exc()
        
        return result


# ========== 测试用例 ==========

def test_wechat_moments_like():
    """测试: 给微信朋友圈前3条点赞"""
    print("\n" + "="*60)
    print("测试用例: 给微信朋友圈前3条点赞")
    print("="*60)
    
    runner = IntegrationRunner()
    result = runner.execute_instruction("给微信朋友圈前3条点赞")
    
    # 验证
    assert result["success"], f"执行失败: {result['error']}"
    assert result["steps_executed"] >= 3, f"步骤数不足: {result['steps_executed']}"
    
    print(f"\n✅ 测试通过!")
    print(f"   生成代码行数: {len(result['code'].split(chr(10)))}")
    print(f"   执行步骤数: {result['steps_executed']}")
    
    return True


def test_calculator():
    """测试: 打开计算器计算 1+1"""
    print("\n" + "="*60)
    print("测试用例: 打开计算器计算 1+1")
    print("="*60)
    
    runner = IntegrationRunner()
    result = runner.execute_instruction("打开计算器计算 1+1")
    
    # 验证
    assert result["success"], f"执行失败: {result['error']}"
    assert result["steps_executed"] >= 1, f"步骤数不足: {result['steps_executed']}"
    
    print(f"\n✅ 测试通过!")
    print(f"   执行步骤数: {result['steps_executed']}")
    
    return True


def test_simple_command():
    """测试: 简单命令"""
    print("\n" + "="*60)
    print("测试用例: 打开设置")
    print("="*60)
    
    runner = IntegrationRunner()
    result = runner.execute_instruction("打开设置")
    
    # 验证
    assert result["success"], f"执行失败: {result['error']}"
    
    print(f"\n✅ 测试通过!")
    
    return True


def test_skill_distillation():
    """测试: 技能蒸馏流程"""
    print("\n" + "="*60)
    print("测试用例: 技能蒸馏流程")
    print("="*60)
    
    from skills.skill_distiller import SkillDistiller, ExecutionTrace
    from skills.skill_registry import SkillRegistry
    import tempfile
    
    # 模拟执行轨迹
    trace = ExecutionTrace(
        instruction="给微信朋友圈前3条点赞",
        code='''
step("打开微信")
step("点击发现")
step("点击朋友圈")
step("点击第1条的点赞")
step("点击第2条的点赞")
step("点击第3条的点赞")
''',
        steps=["打开微信", "点击发现", "点击朋友圈", "点击第1条的点赞", "点击第2条的点赞", "点击第3条的点赞"],
        success=True
    )
    
    # 蒸馏
    distiller = SkillDistiller()
    skill = distiller.distill(trace)
    
    assert skill is not None, "蒸馏失败"
    assert "count" in skill.parameters, "应该有 count 参数"
    assert "for" in skill.code or "range" in skill.code, "应该转换为循环"
    
    # 注册
    temp_dir = tempfile.mkdtemp()
    registry = SkillRegistry(temp_dir)
    skill_id = registry.register(
        name=skill.name,
        description=skill.description,
        code=skill.code,
        tags=skill.tags,
        source='distilled'
    )
    
    assert skill_id is not None, "注册失败"
    
    # 搜索
    results = registry.search("点赞")
    assert len(results) > 0, "搜索失败"
    
    print(f"\n✅ 测试通过!")
    print(f"   蒸馏技能: {skill.name}")
    print(f"   参数: {skill.parameters}")
    print(f"   已注册: {skill_id}")
    
    # 清理
    import shutil
    shutil.rmtree(temp_dir)
    
    return True


def test_full_pipeline():
    """测试: 完整管道 (Planner → Runtime → Skill)"""
    print("\n" + "="*60)
    print("测试用例: 完整管道测试")
    print("="*60)
    
    from runtime.planner import Planner
    from runtime.task_runtime import TaskRuntime
    from skills.skill_distiller import SkillDistiller, ExecutionTrace
    
    instruction = "给微信朋友圈前5条点赞"
    
    # 1. Planner
    planner = Planner(provider='mock')
    plan_result = planner.plan(instruction)
    assert plan_result.success, f"Plan 失败: {plan_result.error}"
    print(f"[1/4] ✅ Planner 生成代码成功")
    
    # 2. TaskRuntime
    steps_executed = []
    def mock_step(goal: str) -> bool:
        steps_executed.append(goal)
        return True
    
    runtime = TaskRuntime(step_function=mock_step)
    exec_result = runtime.execute(plan_result.code)
    assert exec_result.success, f"Runtime 失败: {exec_result.error}"
    print(f"[2/4] ✅ TaskRuntime 执行成功, 步骤数: {len(steps_executed)}")
    
    # 3. 模拟执行轨迹
    trace = ExecutionTrace(
        instruction=instruction,
        code=plan_result.code,
        steps=steps_executed,
        success=True
    )
    
    # 4. 技能蒸馏
    distiller = SkillDistiller()
    skill = distiller.distill(trace)
    assert skill is not None, "蒸馏失败"
    print(f"[3/4] ✅ 技能蒸馏成功: {skill.name}")
    
    print(f"[4/4] ✅ 完整管道测试通过!")
    
    return True


# ========== 运行所有测试 ==========

def run_all_tests():
    """运行所有集成测试"""
    print("\n" + "="*60)
    print("      语义容器架构 - 集成测试 (Task 6.1)")
    print("="*60)
    
    tests = [
        ("微信朋友圈点赞", test_wechat_moments_like),
        ("计算器", test_calculator),
        ("简单命令", test_simple_command),
        ("技能蒸馏", test_skill_distillation),
        ("完整管道", test_full_pipeline),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            success = test_fn()
            results.append((name, success, None))
        except Exception as e:
            results.append((name, False, str(e)))
            import traceback
            traceback.print_exc()
    
    # 汇总
    print("\n" + "="*60)
    print("                    测试结果汇总")
    print("="*60)
    
    passed = sum(1 for _, s, _ in results if s)
    failed = len(results) - passed
    
    for name, success, error in results:
        status = "✅" if success else "❌"
        print(f"  {status} {name}")
        if error:
            print(f"      错误: {error}")
    
    print(f"\n总计: {passed}/{len(results)} 通过")
    
    if failed == 0:
        print("\n🎉 所有集成测试通过!")
    else:
        print(f"\n⚠️ {failed} 个测试失败")
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
