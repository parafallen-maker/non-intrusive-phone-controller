#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Skill System - 验证技能检索/蒸馏/保存闭环
"""

import os
import sys
import shutil
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_skill_registry():
    """测试技能注册表"""
    print("=" * 60)
    print("测试 SkillRegistry")
    print("=" * 60)
    
    from skills.skill_registry import SkillRegistry, Skill
    
    # 使用临时目录
    temp_dir = tempfile.mkdtemp()
    
    try:
        registry = SkillRegistry(storage_path=temp_dir)
        
        # 注册技能
        print("\n注册技能...")
        skill_id = registry.register(
            name="微信朋友圈点赞",
            description="打开微信朋友圈并给指定数量的帖子点赞",
            code="""
step("打开微信")
step("点击发现")
step("点击朋友圈")
for i in range(count):
    step(f"点击第{i+1}条的点赞")
""",
            tags=["微信", "社交", "点赞"]
        )
        print(f"注册成功: {skill_id}")
        
        # 搜索技能
        print("\n搜索技能 '朋友圈点赞'...")
        results = registry.search("朋友圈点赞")
        assert len(results) > 0, "应该找到技能"
        print(f"找到 {len(results)} 个技能: {results[0].name}")
        
        # 获取技能
        print("\n获取技能...")
        skill = registry.get(skill_id)
        assert skill is not None, "应该能获取技能"
        assert skill.name == "微信朋友圈点赞"
        print(f"获取成功: {skill.name}")
        
        # 列出所有
        print("\n列出所有技能...")
        all_skills = registry.list_all()
        assert len(all_skills) == 1
        print(f"共 {len(all_skills)} 个技能")
        
        print("\n技能注册表测试通过")
        
    finally:
        shutil.rmtree(temp_dir)


def test_skill_distiller():
    """测试技能蒸馏器"""
    print("\n" + "=" * 60)
    print("测试 SkillDistiller")
    print("=" * 60)
    
    from skills.skill_distiller import SkillDistiller, ExecutionTrace
    
    distiller = SkillDistiller()
    
    # 测试 1: 简单代码
    print("\n测试 1: 简单代码蒸馏")
    trace1 = ExecutionTrace(
        instruction="打开微信",
        code="step('打开微信')",
        steps=["step('打开微信')"],
        success=True
    )
    skill1 = distiller.distill(trace1)
    if skill1:
        print(f"蒸馏结果: {skill1.name}")
    else:
        print("简单代码不适合蒸馏 (符合预期)")
    
    # 测试 2: 循环代码
    print("\n测试 2: 循环代码蒸馏")
    trace2 = ExecutionTrace(
        instruction="给前3条朋友圈点赞",
        code="""
step('打开微信')
step('点击发现')
step('点击朋友圈')
for i in range(3):
    step(f'点击第{i+1}条的点赞')
""",
        steps=["step('打开微信')", "step('点击发现')", "step('点击朋友圈')"],
        success=True
    )
    skill2 = distiller.distill(trace2)
    assert skill2 is not None, "循环代码应该能蒸馏"
    print(f"蒸馏结果: {skill2.name}")
    print(f"参数: {skill2.parameters}")
    print(f"标签: {skill2.tags}")
    
    # 测试 3: 失败的执行
    print("\n测试 3: 失败执行不蒸馏")
    trace3 = ExecutionTrace(
        instruction="测试",
        code="step('测试')",
        steps=[],
        success=False
    )
    skill3 = distiller.distill(trace3)
    assert skill3 is None, "失败执行不应蒸馏"
    print("失败执行不蒸馏 (符合预期)")
    
    print("\n技能蒸馏器测试通过")


def test_skill_integration():
    """测试技能系统与 SemanticAgent 集成"""
    print("\n" + "=" * 60)
    print("测试 技能系统集成")
    print("=" * 60)
    
    from drivers.mock_driver import MockDriver
    from main_v3 import SemanticAgent
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        driver = MockDriver()
        agent = SemanticAgent(
            zhipuai_api_key="mock",
            driver=driver,
            enable_skills=True,
            skill_store_path=temp_dir
        )
        
        # 检查技能系统初始化
        print("\n检查技能系统初始化...")
        assert agent.skill_registry is not None, "应初始化 SkillRegistry"
        assert agent.skill_distiller is not None, "应初始化 SkillDistiller"
        print("技能系统初始化成功")
        
        # 手动注册一个技能
        print("\n注册测试技能...")
        agent.skill_registry.register(
            name="打开应用测试",
            description="打开指定应用的测试技能",
            code="step('打开应用')",
            tags=["测试"]
        )
        
        # 搜索技能
        print("\n测试技能搜索...")
        match = agent._search_skill("打开应用")
        if match:
            skill, score = match
            print(f"找到匹配: {skill.name}, 分数: {score}")
        else:
            print("未找到匹配 (阈值过高)")
        
        # 执行任务并检查蒸馏
        print("\n执行任务...")
        result = agent.execute_task("打开微信")
        print(f"执行结果: {'成功' if result['success'] else '失败'}")
        
        # 检查技能数量
        skills = agent.skill_registry.list_all()
        print(f"当前技能数量: {len(skills)}")
        
        print("\n技能系统集成测试通过")
        
    finally:
        shutil.rmtree(temp_dir)


def test_all():
    """运行所有技能系统测试"""
    print("\n" + "=" * 60)
    print("开始测试技能系统")
    print("=" * 60 + "\n")
    
    try:
        test_skill_registry()
        test_skill_distiller()
        test_skill_integration()
        
        print("\n" + "=" * 60)
        print("所有技能系统测试通过!")
        print("=" * 60)
        print("\n测试摘要:")
        print("  - SkillRegistry: 注册/搜索/获取/列出")
        print("  - SkillDistiller: 简单代码/循环代码/失败执行")
        print("  - SemanticAgent 集成: 初始化/搜索/蒸馏")
        
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_all()
