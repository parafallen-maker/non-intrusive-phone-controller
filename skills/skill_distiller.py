#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能蒸馏器 (Skill Distiller)
实现 Task 5.2: 从一次性执行中蒸馏可复用技能

核心功能:
- 分析执行轨迹
- 提取可复用模式
- 生成参数化技能
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
    instruction: str           # 原始指令
    code: str                  # 执行的代码
    steps: List[str]           # 步骤列表
    success: bool              # 是否成功
    timestamp: str = ""        # 时间戳
    duration: float = 0.0      # 耗时(秒)
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class DistilledSkill:
    """蒸馏后的技能"""
    name: str                  # 技能名称
    description: str           # 描述
    code: str                  # 参数化代码
    parameters: List[str]      # 参数列表
    tags: List[str]            # 标签
    source_instruction: str    # 原始指令


class SkillDistiller:
    """技能蒸馏器
    
    从执行轨迹中提取可复用的技能模板。
    
    蒸馏策略:
    1. 识别重复模式 (循环结构)
    2. 提取变量 (数字、应用名等)
    3. 生成参数化代码
    4. 生成语义描述
    
    Usage:
        distiller = SkillDistiller()
        
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
            steps=[...],
            success=True
        )
        
        skill = distiller.distill(trace)
        # skill.code 将是参数化版本
    """
    
    # 应用名称模式
    APP_PATTERNS = [
        r'打开(\w+)',
        r'启动(\w+)',
        r'进入(\w+)',
    ]
    
    # 数字模式
    NUMBER_PATTERNS = [
        r'第(\d+)条',
        r'第(\d+)个',
        r'前(\d+)条',
        r'(\d+)次',
    ]
    
    def __init__(self):
        """初始化蒸馏器"""
        pass
    
    def distill(self, trace: ExecutionTrace) -> Optional[DistilledSkill]:
        """从执行轨迹蒸馏技能
        
        Args:
            trace: 执行轨迹
            
        Returns:
            蒸馏后的技能，如果不可蒸馏返回 None
        """
        if not trace.success:
            logger.warning("[Distiller] Cannot distill from failed execution")
            return None
        
        # 分析代码
        analysis = self._analyze_code(trace.code)
        
        # 生成参数化代码
        parameterized_code, params = self._parameterize(trace.code, analysis)
        
        # 生成名称和描述
        name = self._generate_name(trace.instruction)
        description = self._generate_description(trace.instruction, params)
        
        # 提取标签
        tags = self._extract_tags(trace.instruction)
        
        return DistilledSkill(
            name=name,
            description=description,
            code=parameterized_code,
            parameters=params,
            tags=tags,
            source_instruction=trace.instruction
        )
    
    def _analyze_code(self, code: str) -> Dict[str, Any]:
        """分析代码结构
        
        返回:
            {
                'has_loop': bool,
                'numbers': List[int],
                'apps': List[str],
                'step_count': int,
                'patterns': List[str]
            }
        """
        analysis = {
            'has_loop': False,
            'numbers': [],
            'apps': [],
            'step_count': 0,
            'patterns': []
        }
        
        # 检查循环
        analysis['has_loop'] = 'for ' in code or 'while ' in code
        
        # 提取数字
        for pattern in self.NUMBER_PATTERNS:
            matches = re.findall(pattern, code)
            analysis['numbers'].extend([int(m) for m in matches])
        
        # 提取应用名
        for pattern in self.APP_PATTERNS:
            matches = re.findall(pattern, code)
            analysis['apps'].extend(matches)
        
        # 统计步骤数
        analysis['step_count'] = len(re.findall(r'step\(', code))
        
        # 识别重复模式
        analysis['patterns'] = self._find_patterns(code)
        
        return analysis
    
    def _find_patterns(self, code: str) -> List[str]:
        """识别重复模式"""
        patterns = []
        
        # 查找相似的 step 调用
        steps = re.findall(r'step\(["\'](.+?)["\']\)', code)
        
        # 检查数字递增模式 (第1条, 第2条, 第3条)
        for i, step in enumerate(steps):
            if re.search(r'第\d+', step):
                patterns.append('numbered_sequence')
                break
        
        # 检查重复动作
        step_actions = [re.sub(r'\d+', 'N', s) for s in steps]
        from collections import Counter
        action_counts = Counter(step_actions)
        for action, count in action_counts.items():
            if count >= 2:
                patterns.append(f'repeat:{action}')
        
        return patterns
    
    def _parameterize(
        self,
        code: str,
        analysis: Dict[str, Any]
    ) -> Tuple[str, List[str]]:
        """参数化代码
        
        Returns:
            (参数化后的代码, 参数列表)
        """
        params = []
        new_code = code
        
        # 检测是否有重复数字模式需要转为循环
        if not analysis['has_loop'] and 'numbered_sequence' in analysis.get('patterns', []):
            new_code, params = self._convert_to_loop(code, analysis)
            return new_code, params
        
        # 参数化数字
        if analysis['numbers']:
            max_num = max(analysis['numbers']) if analysis['numbers'] else 0
            if max_num > 0:
                # 替换范围数字
                new_code = re.sub(
                    r'range\((\d+)\)',
                    'range(count)',
                    new_code
                )
                if 'count' not in params:
                    params.append('count')
        
        # 参数化应用名
        if analysis['apps']:
            app_name = analysis['apps'][0]
            new_code = new_code.replace(f'"{app_name}"', '"{{app_name}}"')
            new_code = new_code.replace(f"'{app_name}'", "'{{app_name}}'")
            if 'app_name' not in params:
                params.append('app_name')
        
        return new_code, params
    
    def _convert_to_loop(
        self,
        code: str,
        analysis: Dict[str, Any]
    ) -> Tuple[str, List[str]]:
        """将重复步骤转换为循环"""
        lines = code.strip().split('\n')
        new_lines = []
        numbered_steps = []
        other_steps = []
        
        # 分离编号步骤和其他步骤
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if re.search(r'第\d+', line):
                numbered_steps.append(line)
            else:
                other_steps.append(line)
        
        # 添加前置步骤
        for step in other_steps:
            if numbered_steps and lines.index(step.strip() if step.strip() in [l.strip() for l in lines] else step) < lines.index(numbered_steps[0].strip() if numbered_steps[0].strip() in [l.strip() for l in lines] else numbered_steps[0]):
                new_lines.append(step)
        
        # 如果有编号步骤，转为循环
        if numbered_steps:
            # 提取模板
            template = re.sub(r'第\d+', '第{i+1}', numbered_steps[0])
            template = re.sub(r'step\(["\']', 'step(f"', template)
            template = re.sub(r'["\']\)', '")', template)
            
            count = len(numbered_steps)
            new_lines.append(f"\nfor i in range(count):  # count={count}")
            new_lines.append(f"    {template}")
        
        # 添加后置步骤
        for step in other_steps:
            if step not in new_lines:
                new_lines.append(step)
        
        return '\n'.join(new_lines), ['count']
    
    def _generate_name(self, instruction: str) -> str:
        """生成技能名称"""
        # 移除数字和量词
        name = re.sub(r'\d+', '', instruction)
        name = re.sub(r'前|后|第|条|个|次', '', name)
        name = name.strip()
        
        # 截断
        if len(name) > 20:
            name = name[:20]
        
        return name or "自动化任务"
    
    def _generate_description(
        self,
        instruction: str,
        params: List[str]
    ) -> str:
        """生成技能描述"""
        desc = instruction
        
        # 添加参数说明
        if params:
            param_desc = ', '.join([f'{p}=可配置' for p in params])
            desc = f"{instruction}（参数: {param_desc}）"
        
        return desc
    
    def _extract_tags(self, instruction: str) -> List[str]:
        """从指令中提取标签"""
        tags = []
        
        # 应用名标签
        app_keywords = ['微信', '抖音', '淘宝', '支付宝', '微博', '计算器', '设置', '相册', '相机']
        for app in app_keywords:
            if app in instruction:
                tags.append(app)
        
        # 动作标签
        action_keywords = {
            '点赞': '社交',
            '评论': '社交',
            '转发': '社交',
            '分享': '社交',
            '发送': '消息',
            '搜索': '搜索',
            '购买': '购物',
            '支付': '支付',
        }
        for keyword, tag in action_keywords.items():
            if keyword in instruction:
                tags.append(tag)
                if keyword not in tags:
                    tags.append(keyword)
        
        return list(set(tags))


def distill_and_register(
    trace: ExecutionTrace,
    registry: Optional['SkillRegistry'] = None
) -> Optional[str]:
    """蒸馏并注册技能（便捷函数）
    
    Args:
        trace: 执行轨迹
        registry: 技能注册表（可选，使用默认）
        
    Returns:
        技能 ID 或 None
    """
    distiller = SkillDistiller()
    skill = distiller.distill(trace)
    
    if not skill:
        return None
    
    # 获取注册表
    if registry is None:
        from skills.skill_registry import get_default_registry
        registry = get_default_registry()
    
    # 注册
    skill_id = registry.register(
        name=skill.name,
        description=skill.description,
        code=skill.code,
        tags=skill.tags,
        source='distilled'
    )
    
    return skill_id


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== Task 5.2 SkillDistiller 测试 ===\n")
    
    distiller = SkillDistiller()
    
    # 测试用例 1: 重复步骤转循环
    print("--- 测试 1: 重复步骤 → 循环 ---")
    trace1 = ExecutionTrace(
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
    
    skill1 = distiller.distill(trace1)
    if skill1:
        print(f"✅ 技能名称: {skill1.name}")
        print(f"   描述: {skill1.description}")
        print(f"   参数: {skill1.parameters}")
        print(f"   标签: {skill1.tags}")
        print(f"   参数化代码:\n{skill1.code}")
    
    # 测试用例 2: 已有循环
    print("\n--- 测试 2: 已有循环结构 ---")
    trace2 = ExecutionTrace(
        instruction="刷抖音10个视频",
        code='''
step("打开抖音")
for i in range(10):
    step("观看当前视频")
    step("双击点赞")
    step("向上滑动")
''',
        steps=["打开抖音", "观看当前视频", "双击点赞", "向上滑动"],
        success=True
    )
    
    skill2 = distiller.distill(trace2)
    if skill2:
        print(f"✅ 技能名称: {skill2.name}")
        print(f"   描述: {skill2.description}")
        print(f"   参数: {skill2.parameters}")
        print(f"   标签: {skill2.tags}")
        print(f"   参数化代码:\n{skill2.code}")
    
    # 测试用例 3: 简单任务
    print("\n--- 测试 3: 简单任务 ---")
    trace3 = ExecutionTrace(
        instruction="打开计算器",
        code='''step("打开计算器")''',
        steps=["打开计算器"],
        success=True
    )
    
    skill3 = distiller.distill(trace3)
    if skill3:
        print(f"✅ 技能名称: {skill3.name}")
        print(f"   参数: {skill3.parameters}")
        print(f"   标签: {skill3.tags}")
    
    # 测试失败的执行
    print("\n--- 测试 4: 失败的执行（不应蒸馏）---")
    trace4 = ExecutionTrace(
        instruction="测试任务",
        code='step("test")',
        steps=["test"],
        success=False
    )
    
    skill4 = distiller.distill(trace4)
    print(f"结果: {'❌ 正确返回 None' if skill4 is None else '错误: 不应该蒸馏'}")
    
    print("\n=== 测试完成 ===")
