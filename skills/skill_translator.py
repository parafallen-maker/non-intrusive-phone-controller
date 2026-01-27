#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能翻译器 (Skill Translator)
将声明式技能描述翻译为可执行的 step() 代码

双层架构的桥梁:
- 输入: DeclarativeSkill 的自然语言行为描述
- 输出: TaskRuntime 可执行的 Python 代码
"""

import re
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """翻译结果"""
    success: bool
    code: Optional[str] = None
    skill_prompt: Optional[str] = None
    error: Optional[str] = None


class SkillTranslator:
    """技能翻译器
    
    将声明式技能的 behavior 描述翻译为 step() 调用序列。
    
    翻译流程:
    1. 解析技能的行为描述
    2. 拼接成 LLM Prompt
    3. 调用 Planner 生成代码
    4. 验证并返回
    
    Usage:
        from skills.declarative_skill import DeclarativeSkill
        
        skill = DeclarativeSkill(
            name="微信朋友圈点赞",
            behavior="...",
            parameters={"count": {"default": 3}}
        )
        
        translator = SkillTranslator(planner)
        result = translator.translate(skill, params={"count": 5})
        
        if result.success:
            runtime.execute(result.code)
    """
    
    TRANSLATION_PROMPT = '''
你是一个代码生成器，将技能的行为描述转换为 step() 调用序列。

## 规则

1. **只使用 step() 函数**
   - step("语义描述") 是唯一的执行指令
   - 描述应该是自然语言，描述要做什么

2. **禁止使用坐标/颜色**
   - ❌ step("点击坐标(100, 200)")
   - ✅ step("点击微信图标")

3. **支持 Python 控制流**
   - for 循环
   - if 条件
   - 变量

4. **代码格式**
   - 直接输出可执行代码
   - 不要包含 import 语句
   - 用 ```python 包裹

## 技能信息

{skill_prompt}

## 参数

{params_str}

## 用户指令

{instruction}

## 生成代码
'''

    def __init__(self, planner: Optional['Planner'] = None):
        """初始化
        
        Args:
            planner: Planner 实例（如果不提供，创建 mock）
        """
        self.planner = planner
        
        if planner is None:
            # 延迟导入，避免循环依赖
            try:
                from runtime.planner import Planner
                self.planner = Planner(provider='mock')
            except ImportError:
                pass
    
    def translate(
        self,
        skill: 'DeclarativeSkill',
        instruction: str = "",
        params: Optional[Dict[str, Any]] = None
    ) -> TranslationResult:
        """翻译技能为可执行代码
        
        Args:
            skill: 声明式技能
            instruction: 用户原始指令
            params: 参数覆盖
            
        Returns:
            TranslationResult
        """
        try:
            # 1. 生成技能 Prompt
            skill_prompt = skill.to_prompt()
            
            # 2. 处理参数
            final_params = self._merge_params(skill, params)
            params_str = self._format_params(final_params)
            
            # 3. 构建完整 Prompt
            full_prompt = self.TRANSLATION_PROMPT.format(
                skill_prompt=skill_prompt,
                params_str=params_str,
                instruction=instruction or f"执行技能: {skill.name}"
            )
            
            # 4. 检查是否有缓存代码
            if skill.cached_code and not params:
                return TranslationResult(
                    success=True,
                    code=skill.cached_code,
                    skill_prompt=skill_prompt
                )
            
            # 5. 调用 Planner
            if self.planner:
                result = self.planner.plan(full_prompt)
                if result.success:
                    # 替换参数
                    code = self._inject_params(result.code, final_params)
                    return TranslationResult(
                        success=True,
                        code=code,
                        skill_prompt=skill_prompt
                    )
                else:
                    return TranslationResult(
                        success=False,
                        error=result.error,
                        skill_prompt=skill_prompt
                    )
            
            # 6. 无 Planner，尝试简单转换
            code = self._simple_translate(skill, final_params)
            return TranslationResult(
                success=True,
                code=code,
                skill_prompt=skill_prompt
            )
            
        except Exception as e:
            logger.error(f"[Translator] Error: {e}")
            return TranslationResult(
                success=False,
                error=str(e)
            )
    
    def _merge_params(
        self,
        skill: 'DeclarativeSkill',
        override: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """合并参数（默认值 + 覆盖值）"""
        result = {}
        
        # 填充默认值
        for name, spec in skill.parameters.items():
            if isinstance(spec, dict) and 'default' in spec:
                result[name] = spec['default']
            elif not isinstance(spec, dict):
                result[name] = spec
        
        # 应用覆盖
        if override:
            result.update(override)
        
        return result
    
    def _format_params(self, params: Dict[str, Any]) -> str:
        """格式化参数为字符串"""
        if not params:
            return "无参数"
        
        lines = []
        for name, value in params.items():
            lines.append(f"- {name} = {value}")
        return "\n".join(lines)
    
    def _inject_params(self, code: str, params: Dict[str, Any]) -> str:
        """将参数注入代码"""
        result = code
        
        # 简单的变量替换
        for name, value in params.items():
            # 替换 {name} 格式
            result = result.replace(f"{{{name}}}", str(value))
            # 在代码开头添加变量定义
            if name not in result:
                continue
        
        # 添加参数定义到代码开头
        param_defs = []
        for name, value in params.items():
            if isinstance(value, str):
                param_defs.append(f'{name} = "{value}"')
            else:
                param_defs.append(f'{name} = {value}')
        
        if param_defs:
            result = "\n".join(param_defs) + "\n\n" + result
        
        return result
    
    def _simple_translate(
        self,
        skill: 'DeclarativeSkill',
        params: Dict[str, Any]
    ) -> str:
        """简单转换（不依赖 LLM）
        
        从行为描述中提取步骤，生成基本代码。
        """
        behavior = skill.behavior
        
        # 提取步骤
        steps = []
        
        # 匹配 "1. xxx" 或 "- xxx" 格式的步骤
        step_patterns = [
            r'^\d+\.\s*(.+)$',      # 1. 步骤
            r'^[a-z]\.\s*(.+)$',    # a. 步骤
            r'^-\s*(.+)$',          # - 步骤
            r'^•\s*(.+)$',          # • 步骤
        ]
        
        for line in behavior.split('\n'):
            line = line.strip()
            for pattern in step_patterns:
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    step_text = match.group(1).strip()
                    # 过滤掉太短或包含特殊字符的步骤
                    if len(step_text) > 2 and not step_text.startswith('#'):
                        steps.append(step_text)
                    break
        
        # 生成代码
        code_lines = []
        
        # 参数定义
        for name, value in params.items():
            if isinstance(value, str):
                code_lines.append(f'{name} = "{value}"')
            else:
                code_lines.append(f'{name} = {value}')
        
        if code_lines:
            code_lines.append("")
        
        # 步骤调用
        in_loop = False
        for step in steps:
            # 检查是否是循环步骤
            if '每' in step or '对于' in step or '循环' in step:
                # 开始循环块
                count_param = params.get('count', 3)
                code_lines.append(f"for i in range({count_param}):")
                in_loop = True
            elif in_loop and ('下一' in step or '滑动' in step):
                # 循环内的步骤
                code_lines.append(f'    step("{step}")')
            elif in_loop and ('返回' in step or '完成' in step):
                # 结束循环
                in_loop = False
                code_lines.append(f'step("{step}")')
            elif in_loop:
                code_lines.append(f'    step("{step}")')
            else:
                code_lines.append(f'step("{step}")')
        
        return "\n".join(code_lines)


class SkillEnhancedPlanner:
    """技能增强的规划器
    
    结合技能库进行代码生成，优先使用已有技能。
    
    流程:
    1. 语义匹配用户指令
    2. 如果匹配到技能，翻译技能
    3. 否则，使用原始 Planner
    """
    
    def __init__(
        self,
        planner: 'Planner',
        skill_registry: Optional['DeclarativeSkillRegistry'] = None,
        semantic_matcher: Optional['SemanticMatcher'] = None
    ):
        self.planner = planner
        self.skill_registry = skill_registry
        self.semantic_matcher = semantic_matcher
        self.translator = SkillTranslator(planner)
    
    def plan(
        self,
        instruction: str,
        skill_threshold: float = 0.5
    ) -> 'PlanResult':
        """智能规划
        
        Args:
            instruction: 用户指令
            skill_threshold: 技能匹配阈值
            
        Returns:
            PlanResult
        """
        from runtime.planner import PlanResult
        
        # 1. 尝试匹配技能
        matched_skill = self._match_skill(instruction, skill_threshold)
        
        if matched_skill:
            logger.info(f"[SkillPlanner] Matched skill: {matched_skill.name}")
            
            # 2. 翻译技能
            result = self.translator.translate(
                matched_skill,
                instruction=instruction
            )
            
            if result.success:
                return PlanResult(
                    success=True,
                    code=result.code,
                    raw_response=f"[Skill: {matched_skill.name}]\n{result.skill_prompt}"
                )
        
        # 3. 降级到原始 Planner
        logger.info("[SkillPlanner] No skill matched, using raw planner")
        return self.planner.plan(instruction)
    
    def _match_skill(
        self,
        instruction: str,
        threshold: float
    ) -> Optional['DeclarativeSkill']:
        """匹配技能"""
        if not self.skill_registry:
            return None
        
        # 语义匹配
        if self.semantic_matcher:
            matches = self.semantic_matcher.match(instruction, top_k=1, threshold=threshold)
            if matches:
                skill_id, score = matches[0]
                return self.skill_registry.get(skill_id)
        
        # 降级到关键词匹配
        matches = self.skill_registry.match_intent(instruction, threshold=threshold)
        if matches:
            return matches[0]
        
        return None


# ========== 测试代码 ==========

if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/Users/Ljc_1/Downloads/非侵入式手机控制/semantic-agent')
    
    from skills.declarative_skill import DeclarativeSkill, TriggerCondition, Preference
    
    print("=== 技能翻译器测试 ===\n")
    
    # 创建测试技能
    skill = DeclarativeSkill(
        name="微信朋友圈点赞",
        description="给微信朋友圈点赞",
        trigger=TriggerCondition(keywords=["朋友圈", "点赞"]),
        behavior="""
目标：给微信朋友圈点赞

步骤：
1. 打开微信应用
2. 点击发现标签
3. 点击朋友圈入口
4. 对于每条帖子：点击点赞按钮
5. 向下滑动到下一条
6. 返回桌面

注意：每次点赞后等待1秒
""",
        parameters={
            "count": {"type": "int", "default": 3, "description": "点赞数量"}
        }
    )
    
    # 测试简单翻译（无 LLM）
    print("--- 简单翻译（无 LLM）---")
    translator = SkillTranslator(planner=None)
    result = translator.translate(skill, params={"count": 5})
    
    if result.success:
        print("✅ 翻译成功")
        print(f"生成代码:\n{result.code}")
    else:
        print(f"❌ 翻译失败: {result.error}")
    
    # 测试带 Mock Planner 的翻译
    print("\n--- Mock Planner 翻译 ---")
    try:
        from runtime.planner import Planner
        planner = Planner(provider='mock')
        translator_with_planner = SkillTranslator(planner)
        
        result2 = translator_with_planner.translate(
            skill,
            instruction="帮我给朋友圈前3条点赞"
        )
        
        if result2.success:
            print("✅ 翻译成功")
            print(f"生成代码:\n{result2.code}")
    except Exception as e:
        print(f"跳过: {e}")
    
    print("\n=== 测试完成 ===")
