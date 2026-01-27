#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
规划器 (Planner)
实现 Task 4.2: 战略层 LLM - 生成 Python 代码

核心功能:
- 连接 LLM API (GPT-4o / Claude / GLM-4)
- 拼接 System Prompt
- 提取代码块
- 自动重试
"""

import re
import logging
from typing import Optional, Callable
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class PlanResult:
    """规划结果"""
    success: bool
    code: Optional[str] = None
    raw_response: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 1


class Planner:
    """规划器 - 连接战略层 LLM
    
    将用户的自然语言指令转换为可执行的 Python 代码。
    
    Usage:
        planner = Planner(api_key="xxx", provider="zhipu")
        result = planner.plan("给朋友圈前3条点赞")
        if result.success:
            runtime.execute(result.code)
    """
    
    SUPPORTED_PROVIDERS = ['zhipu', 'openai', 'anthropic', 'mock']
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = 'zhipu',
        model: Optional[str] = None,
        lite_prompt: bool = False
    ):
        """初始化规划器
        
        Args:
            api_key: API Key
            provider: LLM 提供商 (zhipu/openai/anthropic/mock)
            model: 模型名称（可选，使用默认）
            lite_prompt: 是否使用轻量版 Prompt
        """
        self.provider = provider
        self.api_key = api_key
        self.lite_prompt = lite_prompt
        
        # 默认模型
        self.model = model or {
            'zhipu': 'glm-4-flash',
            'openai': 'gpt-4o',
            'anthropic': 'claude-3-5-sonnet-20241022',
            'mock': 'mock',
        }.get(provider, 'glm-4-flash')
        
        # 初始化客户端
        self.client = None
        if provider != 'mock':
            self._init_client()
    
    def _init_client(self):
        """初始化 LLM 客户端"""
        if self.provider == 'zhipu':
            try:
                from zhipuai import ZhipuAI
                self.client = ZhipuAI(api_key=self.api_key)
            except ImportError:
                logger.warning("zhipuai not installed")
                
        elif self.provider == 'openai':
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except ImportError:
                logger.warning("openai not installed")
                
        elif self.provider == 'anthropic':
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.warning("anthropic not installed")
    
    def plan(self, instruction: str, max_retries: int = 1) -> PlanResult:
        """生成执行计划（Python 代码）
        
        Args:
            instruction: 用户自然语言指令
            max_retries: 最大重试次数
            
        Returns:
            PlanResult: 规划结果
        """
        # 导入 prompts
        try:
            from runtime.prompts import get_system_prompt, validate_code
        except ImportError:
            from prompts import get_system_prompt, validate_code
        
        system_prompt = get_system_prompt(lite=self.lite_prompt)
        
        attempts = 0
        last_error = None
        
        while attempts <= max_retries:
            attempts += 1
            logger.info(f"[Planner] Attempt {attempts}/{max_retries + 1}: {instruction[:50]}...")
            
            try:
                # 调用 LLM
                raw_response = self._call_llm(system_prompt, instruction)
                
                if not raw_response:
                    last_error = "Empty response from LLM"
                    continue
                
                logger.info(f"[Planner] Raw response: {raw_response[:200]}...")
                
                # 提取代码块
                code = self._extract_code(raw_response)
                
                if not code:
                    last_error = "No code block found in response"
                    logger.warning(f"[Planner] {last_error}")
                    continue
                
                # 验证代码
                is_valid, reason = validate_code(code)
                if not is_valid:
                    last_error = f"Code validation failed: {reason}"
                    logger.warning(f"[Planner] {last_error}")
                    continue
                
                # 成功
                return PlanResult(
                    success=True,
                    code=code,
                    raw_response=raw_response,
                    attempts=attempts
                )
                
            except Exception as e:
                last_error = str(e)
                logger.error(f"[Planner] Error: {e}")
        
        return PlanResult(
            success=False,
            error=last_error,
            attempts=attempts
        )
    
    def _call_llm(self, system_prompt: str, user_message: str) -> Optional[str]:
        """调用 LLM API
        
        Args:
            system_prompt: 系统提示
            user_message: 用户消息
            
        Returns:
            LLM 响应文本
        """
        if self.provider == 'mock':
            return self._mock_response(user_message)
        
        if not self.client:
            raise RuntimeError(f"LLM client not initialized for provider: {self.provider}")
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        if self.provider == 'zhipu':
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000
            )
            return response.choices[0].message.content
            
        elif self.provider == 'openai':
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000
            )
            return response.choices[0].message.content
            
        elif self.provider == 'anthropic':
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                max_tokens=2000
            )
            return response.content[0].text
        
        return None
    
    def _extract_code(self, text: str) -> Optional[str]:
        """从响应中提取 Python 代码块
        
        支持的格式:
        ```python
        code
        ```
        
        ```
        code
        ```
        
        或直接识别 step() 调用
        """
        # 尝试匹配 ```python ... ```
        python_match = re.search(r'```python\s*\n(.*?)```', text, re.DOTALL)
        if python_match:
            return python_match.group(1).strip()
        
        # 尝试匹配 ``` ... ```
        code_match = re.search(r'```\s*\n(.*?)```', text, re.DOTALL)
        if code_match:
            code = code_match.group(1).strip()
            # 检查是否包含 step()
            if 'step(' in code:
                return code
        
        # 尝试直接查找 step() 调用
        lines = text.split('\n')
        code_lines = []
        in_code = False
        
        for line in lines:
            stripped = line.strip()
            if 'step(' in stripped or stripped.startswith('for ') or stripped.startswith('if '):
                in_code = True
            if in_code:
                if stripped and not stripped.startswith('#'):
                    code_lines.append(line)
                elif not stripped and code_lines:
                    # 空行且已有代码，可能是代码结束
                    pass
        
        if code_lines:
            code = '\n'.join(code_lines)
            if 'step(' in code:
                return code
        
        return None
    
    def _mock_response(self, instruction: str) -> str:
        """Mock 响应（用于测试）"""
        # 简单的模板匹配
        if '点赞' in instruction and '朋友圈' in instruction:
            # 提取数字
            import re
            nums = re.findall(r'\d+', instruction)
            count = int(nums[0]) if nums else 3
            return f'''好的，我来帮你实现这个任务。

```python
step("打开微信")
step("点击发现")
step("点击朋友圈")

for i in range({count}):
    step(f"点击第{{i+1}}条朋友圈的点赞按钮")
    step("向下滑动到下一条")

step("返回桌面")
```
'''
        
        if '计算器' in instruction:
            return '''```python
step("打开计算器应用")
step("点击数字1")
step("点击加号按钮")
step("点击数字1")
step("点击等号按钮")
```
'''
        
        # 默认响应
        return f'''```python
step("{instruction}")
```
'''


# ========== 工厂函数 ==========

def create_planner(
    api_key: Optional[str] = None,
    provider: str = 'mock'
) -> Planner:
    """创建规划器
    
    Args:
        api_key: API Key
        provider: 提供商 (zhipu/openai/anthropic/mock)
        
    Returns:
        Planner 实例
    """
    return Planner(api_key=api_key, provider=provider)


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== Task 4.2 Planner 测试 ===\n")
    
    # 使用 Mock 模式测试
    planner = Planner(provider='mock')
    
    test_instructions = [
        "给微信朋友圈前3条点赞",
        "打开计算器计算 1+1",
        "打开设置",
    ]
    
    for instruction in test_instructions:
        print(f"--- 指令: {instruction} ---")
        result = planner.plan(instruction)
        
        if result.success:
            print(f"✅ 成功！尝试次数: {result.attempts}")
            print(f"生成的代码:\n{result.code}")
        else:
            print(f"❌ 失败: {result.error}")
        print()
    
    # 测试代码提取
    print("--- 代码提取测试 ---")
    test_texts = [
        "这是一段说明\n```python\nstep('test')\n```\n后续文字",
        "直接输出：\nstep('action1')\nstep('action2')",
        "没有代码的回复",
    ]
    
    for text in test_texts:
        code = planner._extract_code(text)
        print(f"输入: {text[:30]}...")
        print(f"提取: {code}")
        print()
    
    print("=== 测试完成 ===")
