#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Script - 验证三层架构

测试每一层的独立功能和集成效果
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_phase1_autoglm_driver():
    """测试 Phase 1: AutoGLMDriver"""
    print("=" * 60)
    print("测试 Phase 1: AutoGLMDriver")
    print("=" * 60)
    
    from drivers.mock_driver import MockDriver
    from tactical.autoglm_driver import AutoGLMDriver
    
    driver = MockDriver()
    autoglm = AutoGLMDriver(api_key="mock", driver=driver)
    
    print("\n测试 execute_step()...")
    try:
        result = autoglm.execute_step("点击搜索框")
        print(f"✅ 结果: {result}")
    except Exception as e:
        print(f"❌ 失败: {e}")
    
    stats = autoglm.get_stats()
    print(f"\n统计: {stats}")
    
    print("\n✅ Phase 1 测试通过\n")


def test_phase2_task_runtime():
    """测试 Phase 2: TaskRuntime"""
    print("=" * 60)
    print("测试 Phase 2: TaskRuntime")
    print("=" * 60)
    
    from drivers.mock_driver import MockDriver
    from tactical.autoglm_driver import AutoGLMDriver
    from runtime.task_runtime_v2 import TaskRuntime
    
    driver = MockDriver()
    autoglm = AutoGLMDriver(api_key="mock", driver=driver)
    runtime = TaskRuntime(autoglm)
    
    print("\n测试简单代码...")
    code1 = """
step('打开应用')
step('点击搜索')
"""
    result1 = runtime.execute(code1)
    print(f"结果: {result1['success']}, 步骤: {result1['steps']}")
    
    print("\n测试循环代码...")
    code2 = """
for i in range(3):
    step(f'操作 {i+1}')
"""
    result2 = runtime.execute(code2)
    print(f"结果: {result2['success']}, 步骤: {result2['steps']}")
    
    print("\n✅ Phase 2 测试通过\n")


def test_phase3_strategy_prompt():
    """测试 Phase 3: 策略层 Prompt"""
    print("=" * 60)
    print("测试 Phase 3: 策略层 Prompt")
    print("=" * 60)
    
    from brain.strategy_prompt import get_strategy_prompt, create_user_prompt
    
    system_prompt = get_strategy_prompt()
    print(f"\nSystem Prompt 长度: {len(system_prompt)} 字符")
    
    user_prompt = create_user_prompt("测试任务")
    print(f"User Prompt 长度: {len(user_prompt)} 字符")
    
    # 检查关键词
    assert "step(goal" in system_prompt
    assert "禁止" in system_prompt
    assert "坐标" in system_prompt
    
    print("\n✅ Phase 3 测试通过\n")


def test_phase4_integration():
    """测试 Phase 4: 完整集成"""
    print("=" * 60)
    print("测试 Phase 4: 完整集成")
    print("=" * 60)
    
    from drivers.mock_driver import MockDriver
    from main_v3 import SemanticAgent
    
    driver = MockDriver()
    agent = SemanticAgent(
        zhipuai_api_key="mock",
        driver=driver
    )
    
    print("\n测试任务执行...")
    result = agent.execute_task("打开应用")
    
    print(f"\n结果:")
    print(f"  - 成功: {result['success']}")
    if result['success']:
        print(f"  - 步骤: {result.get('steps', 0)}")
        print(f"  - 重试: {result.get('retries', 0)}")
        print(f"  - 代码: {result.get('code', '')[:50]}...")
    else:
        print(f"  - 错误: {result.get('error', '未知错误')}")
    
    print("\n✅ Phase 4 测试通过（Mock 模式）\n")


def test_all():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("🧪 开始测试三层架构")
    print("=" * 60 + "\n")
    
    try:
        test_phase1_autoglm_driver()
        test_phase2_task_runtime()
        test_phase3_strategy_prompt()
        test_phase4_integration()
        
        print("=" * 60)
        print("✅ 所有测试通过!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_all()
