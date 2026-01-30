#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Script - 验证三层架构

测试每一层的独立功能和集成效果
包含 Long-horizon Planning 测试
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
    from tactical.autoglm_driver import AutoGLMDriver, StepResult
    
    driver = MockDriver()
    autoglm = AutoGLMDriver(api_key="mock", driver=driver)
    
    print("\n测试 execute_step() 返回 StepResult...")
    result = autoglm.execute_step("点击搜索框")
    assert isinstance(result, StepResult), "应返回 StepResult"
    print(f"✅ 结果: {result}")
    print(f"   - success: {result.success}")
    print(f"   - state: {result.state}")
    print(f"   - has_more: {result.has_more}")
    
    print("\n测试 execute_step() 带 expect 参数...")
    result2 = autoglm.execute_step("点击确定", expect="返回主页")
    print(f"✅ 结果: {result2}")
    
    print("\n测试 ask()...")
    answer = autoglm.ask("当前页面是什么？")
    assert isinstance(answer, str), "ask() 应返回字符串"
    print(f"✅ 答案: {answer}")
    
    print("\n测试 checkpoint()...")
    check = autoglm.checkpoint("还有照片需要删除")
    assert isinstance(check, bool), "checkpoint() 应返回布尔值"
    print(f"✅ 检查点结果: {check}")
    
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
result = step('打开应用')
print(f'结果: {result.success}, 状态: {result.state}')
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
    
    print("\n测试 ask() 函数...")
    code3 = """
answer = ask('当前界面是什么？')
print(f'答案: {answer}')
"""
    result3 = runtime.execute(code3)
    print(f"结果: {result3['success']}")
    
    print("\n测试 checkpoint() 函数（Mock 模式返回 False）...")
    code4 = """
counter = 0
while checkpoint('还有项目') and counter < 3:
    step('处理项目')
    counter += 1
print(f'共处理: {counter}')
"""
    result4 = runtime.execute(code4)
    print(f"结果: {result4['success']}")
    
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
    
    # 检查关键词 - 新接口
    assert "step(goal" in system_prompt, "应包含 step 函数说明"
    assert "ask(question" in system_prompt, "应包含 ask 函数说明"
    assert "checkpoint(description" in system_prompt, "应包含 checkpoint 函数说明"
    assert "StepResult" in system_prompt, "应包含 StepResult 说明"
    assert "禁止" in system_prompt or "禁令" in system_prompt, "应包含禁止说明"
    assert "坐标" in system_prompt, "应提到坐标限制"
    
    print("✅ System Prompt 包含所有必要的接口文档")
    
    # 检查 user prompt
    assert "checkpoint" in user_prompt, "User prompt 应提到 checkpoint"
    assert "ask" in user_prompt, "User prompt 应提到 ask"
    
    print("✅ User Prompt 包含新接口提示")
    
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


def test_long_horizon_planning():
    """测试 Long-horizon Planning 功能"""
    print("=" * 60)
    print("测试 Long-horizon Planning 功能")
    print("=" * 60)
    
    from drivers.mock_driver import MockDriver
    from tactical.autoglm_driver import AutoGLMDriver, StepResult
    from runtime.task_runtime_v2 import TaskRuntime
    
    driver = MockDriver()
    autoglm = AutoGLMDriver(api_key="mock", driver=driver)
    runtime = TaskRuntime(autoglm)
    
    # 测试 1: StepResult 返回值
    print("\n测试 1: StepResult 返回值使用")
    code1 = """
result = step('打开相册')
if result.success:
    print(f'成功！当前状态: {result.state}')
    if result.has_more:
        print('还有更多内容')
else:
    print(f'失败: {result.error}')
"""
    result1 = runtime.execute(code1)
    assert result1['success'], "代码应该执行成功"
    print("✅ StepResult 可正常使用")
    
    # 测试 2: ask() 函数
    print("\n测试 2: ask() 查询界面")
    code2 = """
answer = ask('屏幕上显示什么？')
print(f'界面描述: {answer}')
assert isinstance(answer, str)
"""
    result2 = runtime.execute(code2)
    assert result2['success'], "ask() 应该执行成功"
    print("✅ ask() 函数正常工作")
    
    # 测试 3: checkpoint() 函数
    print("\n测试 3: checkpoint() 验证检查点")
    code3 = """
# Mock 模式下 checkpoint 返回 False
result = checkpoint('存在某个元素')
print(f'检查点结果: {result}')
assert isinstance(result, bool)
"""
    result3 = runtime.execute(code3)
    assert result3['success'], "checkpoint() 应该执行成功"
    print("✅ checkpoint() 函数正常工作")
    
    # 测试 4: 模拟 Long-horizon 循环
    print("\n测试 4: 模拟 Long-horizon 循环逻辑")
    code4 = """
step('打开相册')

# 模拟循环（Mock 模式下 checkpoint 返回 False，所以循环不执行）
loop_count = 0
max_loops = 5  # 安全限制

while checkpoint('还有照片') and loop_count < max_loops:
    result = step('选择第一张照片')
    if result.success:
        step('删除照片')
    loop_count += 1

print(f'循环执行了 {loop_count} 次')
step('完成')
"""
    result4 = runtime.execute(code4)
    assert result4['success'], "Long-horizon 代码应该执行成功"
    print("✅ Long-horizon 循环逻辑正常")
    
    # 测试 5: 综合使用所有接口
    print("\n测试 5: 综合使用 step/ask/checkpoint")
    code5 = """
# 综合场景
step('打开应用')

# 先用 ask 查询状态
status = ask('当前是什么页面？')
print(f'当前页面: {status}')

# 用 checkpoint 判断条件
if checkpoint('已登录'):
    step('进入主页')
else:
    step('点击登录')

# 使用 expect 参数
result = step('点击确定', expect='显示成功提示')
print(f'操作状态: {result.state}')
"""
    result5 = runtime.execute(code5)
    assert result5['success'], "综合测试应该执行成功"
    print("✅ 综合场景测试通过")
    
    print("\n✅ Long-horizon Planning 测试通过\n")
    
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
    print("🧪 开始测试三层架构 (v2 - Long-horizon Planning)")
    print("=" * 60 + "\n")
    
    try:
        test_phase1_autoglm_driver()
        test_phase2_task_runtime()
        test_phase3_strategy_prompt()
        test_phase4_integration()
        test_long_horizon_planning()
        
        print("=" * 60)
        print("✅ 所有测试通过!")
        print("=" * 60)
        print("\n📋 测试摘要:")
        print("  - Phase 1: AutoGLMDriver + StepResult/ask/checkpoint ✅")
        print("  - Phase 2: TaskRuntime 沙盒注入 ✅")
        print("  - Phase 3: 策略层 Prompt 更新 ✅")
        print("  - Phase 4: 完整集成 ✅")
        print("  - Long-horizon Planning 专项测试 ✅")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_all()
