#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
双向技能蒸馏器 (Bidirectional Skill Distiller)
实现过程式代码与声明式技能的双向转换

功能:
1. 执行轨迹 → 声明式技能 (提升)
2. 声明式技能 → 过程式代码 (翻译)
3. 自动优化技能描述
"""

import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime


logger = logging.getLogger(__name__)


@dataclass
class ExecutionTrace:
    """执行轨迹"""
    instruction: str           # 用户原始指令
    code: str                  # 执行的代码
    steps: List[str]           # 步骤列表
    success: bool              # 是否成功
    timestamp: str = ""
    duration: float = 0.0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class BidirectionalDistiller:
    """双向技能蒸馏器
    
    将执行轨迹提升为声明式技能。
    
    蒸馏策略:
    1. 从代码中提取步骤结构
    2. 识别参数和循环模式
    3. 生成自然语言行为描述
    4. 推断触发条件和标签
    
    Usage:
        distiller = BidirectionalDistiller()
        
        trace = ExecutionTrace(
            instruction="给微信朋友圈前3条点赞",
            code='''
            step("打开微信")
            step("点击发现")
            for i in range(3):
                step(f"点击第{i+1}条的点赞")
            ''',
            steps=["打开微信", "点击发现", ...],
            success=True
        )
        
        skill = distiller.distill_to_declarative(trace)
        # 返回 DeclarativeSkill
    """
    
    # 应用关键词映射
    APP_KEYWORDS = {
        '微信': ['微信', 'wechat'],
        '抖音': ['抖音', 'douyin', 'tiktok'],
        '淘宝': ['淘宝', 'taobao'],
        '支付宝': ['支付宝', 'alipay'],
        '微博': ['微博', 'weibo'],
        '计算器': ['计算器', 'calculator'],
        '设置': ['设置', 'settings'],
    }
    
    # 动作关键词映射
    ACTION_KEYWORDS = {
        '点赞': ['点赞', '赞', 'like'],
        '评论': ['评论', 'comment'],
        '分享': ['分享', 'share'],
        '搜索': ['搜索', 'search'],
        '滑动': ['滑动', '翻页', 'scroll', 'swipe'],
        '点击': ['点击', '按', 'click', 'tap'],
    }
    
    def __init__(self):
        pass
    
    def distill_to_declarative(
        self,
        trace: ExecutionTrace
    ) -> Optional['DeclarativeSkill']:
        """从执行轨迹蒸馏为声明式技能
        
        Args:
            trace: 执行轨迹
            
        Returns:
            DeclarativeSkill 或 None（如果不可蒸馏）
        """
        if not trace.success:
            logger.warning("[Distiller] Cannot distill from failed execution")
            return None
        
        # 延迟导入避免循环依赖
        from skills.declarative_skill import (
            DeclarativeSkill, TriggerCondition, Preference, SkillType
        )
        
        # 1. 分析代码结构
        analysis = self._analyze_code(trace.code)
        
        # 2. 生成技能名称
        name = self._generate_name(trace.instruction)
        
        # 3. 生成行为描述
        behavior = self._generate_behavior(trace, analysis)
        
        # 4. 提取参数
        parameters = self._extract_parameters(trace.code, analysis)
        
        # 5. 推断触发条件
        trigger = self._infer_trigger(trace.instruction)
        
        # 6. 提取标签
        tags = self._extract_tags(trace.instruction)
        
        # 7. 生成约束条件
        constraints = self._generate_constraints(analysis)
        
        # 8. 确定技能类型
        skill_type = SkillType.TEMPLATE if parameters else SkillType.ATOMIC
        
        # 9. 创建声明式技能
        skill = DeclarativeSkill(
            name=name,
            description=self._generate_description(trace.instruction),
            trigger=trigger,
            behavior=behavior,
            parameters=parameters,
            constraints=constraints,
            preferences=[
                Preference("验证模式", "每步执行后验证结果", enabled=True),
                Preference("截图记录", "保存操作截图", enabled=True),
            ],
            tags=tags,
            skill_type=skill_type,
            cached_code=self._parameterize_code(trace.code, analysis)
        )
        
        logger.info(f"[Distiller] Distilled skill: {name}")
        return skill
    
    def _analyze_code(self, code: str) -> Dict[str, Any]:
        """分析代码结构"""
        analysis = {
            'has_loop': False,
            'loop_var': None,
            'loop_count': None,
            'steps': [],
            'numbers': [],
            'apps': [],
            'actions': []
        }
        
        # 检查循环
        loop_match = re.search(r'for\s+(\w+)\s+in\s+range\((\d+)\)', code)
        if loop_match:
            analysis['has_loop'] = True
            analysis['loop_var'] = loop_match.group(1)
            analysis['loop_count'] = int(loop_match.group(2))
        
        # 提取步骤
        step_matches = re.findall(r'step\(["\'](.+?)["\']\)', code)
        analysis['steps'] = step_matches
        
        # 提取数字
        number_matches = re.findall(r'\d+', code)
        analysis['numbers'] = [int(n) for n in number_matches]
        
        # 识别应用
        for app, keywords in self.APP_KEYWORDS.items():
            for kw in keywords:
                if kw in code.lower():
                    analysis['apps'].append(app)
                    break
        
        # 识别动作
        for action, keywords in self.ACTION_KEYWORDS.items():
            for kw in keywords:
                if kw in code.lower():
                    analysis['actions'].append(action)
                    break
        
        return analysis
    
    def _generate_name(self, instruction: str) -> str:
        """生成技能名称"""
        # 移除数字和量词
        name = re.sub(r'\d+', '', instruction)
        name = re.sub(r'前|后|第|条|个|次|帮我|给我', '', name)
        name = name.strip()
        
        if len(name) > 15:
            name = name[:15]
        
        return name or "自动化任务"
    
    def _generate_description(self, instruction: str) -> str:
        """生成简短描述"""
        return f"自动执行: {instruction}"
    
    def _generate_behavior(
        self,
        trace: ExecutionTrace,
        analysis: Dict[str, Any]
    ) -> str:
        """生成自然语言行为描述"""
        parts = []
        
        # 目标
        parts.append(f"目标：{trace.instruction}")
        parts.append("")
        
        # 前置条件
        parts.append("前置条件：")
        parts.append("- 手机已解锁")
        if analysis['apps']:
            parts.append(f"- {analysis['apps'][0]}已安装")
        parts.append("")
        
        # 步骤
        parts.append("步骤：")
        step_num = 1
        
        for i, step in enumerate(analysis['steps']):
            # 检查是否在循环中（简化逻辑）
            if analysis['has_loop'] and '第' in step and '{' in step:
                if step_num == len(analysis['steps']) - 1:
                    # 循环步骤的描述
                    count = analysis['loop_count'] or 3
                    parts.append(f"{step_num}. 重复以下操作 {count} 次：")
                    parts.append(f"   a. {step.replace('{i+1}', 'N')}")
                    step_num += 1
            else:
                parts.append(f"{step_num}. {step}")
                step_num += 1
        
        parts.append("")
        
        # 注意事项
        parts.append("注意事项：")
        parts.append("- 每步操作后验证执行结果")
        if '点赞' in trace.instruction:
            parts.append("- 如果已点赞则跳过")
        parts.append("- 遇到异常时暂停并报告")
        
        return "\n".join(parts)
    
    def _extract_parameters(
        self,
        code: str,
        analysis: Dict[str, Any]
    ) -> Dict[str, Dict]:
        """提取参数定义"""
        params = {}
        
        # 循环次数参数
        if analysis['has_loop'] and analysis['loop_count']:
            params['count'] = {
                'type': 'int',
                'default': analysis['loop_count'],
                'description': '执行次数'
            }
        
        # 应用名称参数
        if analysis['apps']:
            params['app_name'] = {
                'type': 'str',
                'default': analysis['apps'][0],
                'description': '目标应用'
            }
        
        return params
    
    def _infer_trigger(self, instruction: str) -> 'TriggerCondition':
        """推断触发条件"""
        from skills.declarative_skill import TriggerCondition
        
        keywords = []
        intents = []
        
        # 提取关键词
        for app, kws in self.APP_KEYWORDS.items():
            if any(kw in instruction for kw in kws):
                keywords.append(app)
        
        for action, kws in self.ACTION_KEYWORDS.items():
            if any(kw in instruction for kw in kws):
                keywords.append(action)
        
        # 生成意图变体
        intents.append(instruction)
        intents.append(re.sub(r'\d+', 'N', instruction))  # 数字替换
        
        return TriggerCondition(
            keywords=keywords,
            intents=intents
        )
    
    def _extract_tags(self, instruction: str) -> List[str]:
        """提取标签"""
        tags = []
        
        # 应用标签
        for app, kws in self.APP_KEYWORDS.items():
            if any(kw in instruction for kw in kws):
                tags.append(app)
        
        # 动作标签
        for action, kws in self.ACTION_KEYWORDS.items():
            if any(kw in instruction for kw in kws):
                tags.append(action)
        
        return list(set(tags))
    
    def _generate_constraints(self, analysis: Dict[str, Any]) -> List[str]:
        """生成约束条件"""
        constraints = []
        
        if '点赞' in analysis['actions']:
            constraints.append("不重复点赞已点过的内容")
            constraints.append("跳过广告内容")
        
        if analysis['has_loop']:
            constraints.append("操作间隔不少于1秒")
        
        return constraints
    
    def _parameterize_code(
        self,
        code: str,
        analysis: Dict[str, Any]
    ) -> str:
        """参数化代码（缓存用）"""
        result = code
        
        # 替换循环次数为参数
        if analysis['has_loop'] and analysis['loop_count']:
            result = re.sub(
                r'range\(\d+\)',
                'range(count)',
                result
            )
        
        return result


def upgrade_procedural_to_declarative(
    trace: ExecutionTrace,
    registry: Optional['DeclarativeSkillRegistry'] = None
) -> Optional[str]:
    """便捷函数：将过程式执行提升为声明式技能
    
    Args:
        trace: 执行轨迹
        registry: 声明式技能注册表
        
    Returns:
        技能ID 或 None
    """
    distiller = BidirectionalDistiller()
    skill = distiller.distill_to_declarative(trace)
    
    if not skill:
        return None
    
    if registry:
        return registry.register(skill)
    
    return skill.id


# ========== 测试代码 ==========

if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/Users/Ljc_1/Downloads/非侵入式手机控制/semantic-agent')
    
    print("=== 双向技能蒸馏器测试 ===\n")
    
    distiller = BidirectionalDistiller()
    
    # 测试用例 1: 朋友圈点赞
    print("--- 测试 1: 执行轨迹 → 声明式技能 ---")
    trace1 = ExecutionTrace(
        instruction="给微信朋友圈前3条点赞",
        code='''
step("打开微信")
step("点击发现")
step("点击朋友圈")

for i in range(3):
    step(f"点击第{i+1}条的点赞按钮")
    step("向下滑动到下一条")

step("返回桌面")
''',
        steps=[
            "打开微信", "点击发现", "点击朋友圈",
            "点击第1条的点赞按钮", "向下滑动到下一条",
            "点击第2条的点赞按钮", "向下滑动到下一条",
            "点击第3条的点赞按钮", "向下滑动到下一条",
            "返回桌面"
        ],
        success=True
    )
    
    skill1 = distiller.distill_to_declarative(trace1)
    if skill1:
        print(f"✅ 蒸馏成功!")
        print(f"   名称: {skill1.name}")
        print(f"   描述: {skill1.description}")
        print(f"   参数: {skill1.parameters}")
        print(f"   标签: {skill1.tags}")
        print(f"   触发词: {skill1.trigger.keywords}")
        print(f"\n   行为描述:")
        print("   " + skill1.behavior.replace("\n", "\n   "))
        print(f"\n   缓存代码:")
        print("   " + skill1.cached_code.replace("\n", "\n   "))
    
    # 测试用例 2: 简单任务
    print("\n--- 测试 2: 简单任务 ---")
    trace2 = ExecutionTrace(
        instruction="打开抖音",
        code='step("打开抖音")',
        steps=["打开抖音"],
        success=True
    )
    
    skill2 = distiller.distill_to_declarative(trace2)
    if skill2:
        print(f"✅ 蒸馏成功: {skill2.name}")
        print(f"   类型: {skill2.skill_type.value}")
        print(f"   标签: {skill2.tags}")
    
    # 测试失败的执行
    print("\n--- 测试 3: 失败的执行 ---")
    trace3 = ExecutionTrace(
        instruction="测试",
        code='step("test")',
        steps=["test"],
        success=False
    )
    
    skill3 = distiller.distill_to_declarative(trace3)
    print(f"结果: {'❌ 正确拒绝' if skill3 is None else '错误'}")
    
    print("\n=== 测试完成 ===")
