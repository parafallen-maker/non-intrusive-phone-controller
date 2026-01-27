#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
运行时沙盒 (Task Runtime)
实现 Task 3.1: 逻辑容器运行时

核心功能:
- exec() 执行 LLM 生成的 Python 代码
- 只暴露安全的 step() 函数
- 沙盒化：屏蔽对底层对象的直接访问
- 完整的异常捕获和日志记录
"""

import sys
import logging
import traceback
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field
from io import StringIO


logger = logging.getLogger(__name__)


@dataclass
class ExecutionLog:
    """执行日志条目"""
    step_num: int
    goal: str
    success: bool
    error: Optional[str] = None


@dataclass
class RuntimeResult:
    """运行时执行结果"""
    success: bool
    logs: List[ExecutionLog] = field(default_factory=list)
    output: str = ""
    error: Optional[str] = None
    total_steps: int = 0
    failed_steps: int = 0


class TaskRuntime:
    """任务运行时 - LLM 代码执行沙盒
    
    这是语义容器架构的核心组件，负责:
    1. 执行 LLM 生成的 Python 代码
    2. 只暴露 step(goal) 函数给代码
    3. 屏蔽危险操作（文件、网络、系统调用等）
    4. 记录每一步的执行日志
    
    Usage:
        runtime = TaskRuntime(driver, vision, capture_func)
        result = runtime.execute('''
            for i in range(3):
                step(f"点击第{i+1}个点赞按钮")
        ''')
    """
    
    def __init__(
        self,
        step_function: Callable[[str], bool],
        max_steps: int = 50,
        timeout_per_step: float = 30.0
    ):
        """初始化运行时
        
        Args:
            step_function: 绑定好的 step 函数 (goal: str) -> bool
            max_steps: 最大步数限制（防止无限循环）
            timeout_per_step: 每步超时时间
        """
        self.step_function = step_function
        self.max_steps = max_steps
        self.timeout_per_step = timeout_per_step
        
        # 执行状态
        self.step_count = 0
        self.logs: List[ExecutionLog] = []
        self._stop_requested = False
    
    def _create_step_wrapper(self) -> Callable[[str], bool]:
        """创建带计数和日志的 step 包装函数"""
        
        def step(goal: str) -> bool:
            """执行单步目标
            
            这是 LLM 代码中唯一可用的函数。
            
            Args:
                goal: 语义目标描述 (如 "点击设置按钮")
                
            Returns:
                bool: 是否成功
            """
            # 检查是否请求停止
            if self._stop_requested:
                logger.warning("[Runtime] Stop requested, aborting")
                raise RuntimeError("Execution stopped by user")
            
            # 检查步数限制
            self.step_count += 1
            if self.step_count > self.max_steps:
                logger.error(f"[Runtime] Max steps ({self.max_steps}) exceeded")
                raise RuntimeError(f"Maximum steps ({self.max_steps}) exceeded")
            
            logger.info(f"[Runtime] Step {self.step_count}: {goal}")
            
            try:
                # 调用实际的 step 函数
                success = self.step_function(goal)
                
                # 记录日志
                self.logs.append(ExecutionLog(
                    step_num=self.step_count,
                    goal=goal,
                    success=success
                ))
                
                return success
                
            except Exception as e:
                # 记录失败
                self.logs.append(ExecutionLog(
                    step_num=self.step_count,
                    goal=goal,
                    success=False,
                    error=str(e)
                ))
                logger.error(f"[Runtime] Step failed: {e}")
                raise
        
        return step
    
    def _create_safe_globals(self) -> Dict[str, Any]:
        """创建安全的全局命名空间
        
        只允许基本的 Python 内置函数，屏蔽危险操作。
        """
        # 允许的内置函数
        safe_builtins = {
            # 基础
            'print': print,
            'len': len,
            'range': range,
            'enumerate': enumerate,
            'zip': zip,
            'map': map,
            'filter': filter,
            'sorted': sorted,
            'reversed': reversed,
            'list': list,
            'dict': dict,
            'set': set,
            'tuple': tuple,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'abs': abs,
            'min': min,
            'max': max,
            'sum': sum,
            'any': any,
            'all': all,
            'isinstance': isinstance,
            'type': type,
            # 字符串操作
            'format': format,
            'repr': repr,
            # 异常
            'Exception': Exception,
            'ValueError': ValueError,
            'TypeError': TypeError,
            'RuntimeError': RuntimeError,
            # 特殊值
            'True': True,
            'False': False,
            'None': None,
        }
        
        return {
            '__builtins__': safe_builtins,
            '__name__': '__runtime__',
            '__doc__': None,
        }
    
    def _create_safe_locals(self, step_func: Callable) -> Dict[str, Any]:
        """创建安全的局部命名空间
        
        只注入 step() 函数，屏蔽其他所有对象。
        """
        return {
            'step': step_func,
            # 可以添加其他安全的辅助函数
        }
    
    def execute(self, code: str) -> RuntimeResult:
        """执行 Python 代码
        
        Args:
            code: LLM 生成的 Python 代码字符串
            
        Returns:
            RuntimeResult: 执行结果
        """
        # 重置状态
        self.step_count = 0
        self.logs = []
        self._stop_requested = False
        
        # 创建 step 包装函数
        step_wrapper = self._create_step_wrapper()
        
        # 创建安全的执行环境
        safe_globals = self._create_safe_globals()
        safe_locals = self._create_safe_locals(step_wrapper)
        
        # 捕获 print 输出
        output_buffer = StringIO()
        safe_globals['__builtins__']['print'] = lambda *args, **kwargs: print(*args, **kwargs, file=output_buffer)
        
        logger.info(f"[Runtime] Executing code:\n{code}")
        
        try:
            # 编译代码（提前检查语法错误）
            compiled = compile(code, '<runtime>', 'exec')
            
            # 执行
            exec(compiled, safe_globals, safe_locals)
            
            # 成功
            output = output_buffer.getvalue()
            failed = sum(1 for log in self.logs if not log.success)
            
            return RuntimeResult(
                success=True,
                logs=self.logs,
                output=output,
                total_steps=self.step_count,
                failed_steps=failed
            )
            
        except SyntaxError as e:
            logger.error(f"[Runtime] Syntax error: {e}")
            return RuntimeResult(
                success=False,
                logs=self.logs,
                error=f"Syntax error: {e}",
                total_steps=self.step_count
            )
            
        except Exception as e:
            logger.error(f"[Runtime] Execution error: {e}")
            logger.error(traceback.format_exc())
            return RuntimeResult(
                success=False,
                logs=self.logs,
                error=str(e),
                total_steps=self.step_count,
                failed_steps=sum(1 for log in self.logs if not log.success)
            )
    
    def stop(self):
        """请求停止执行"""
        self._stop_requested = True
        logger.info("[Runtime] Stop requested")


# ========== 便捷工厂函数 ==========

def create_runtime(driver, vision, capture_func=None) -> TaskRuntime:
    """创建完整的运行时环境
    
    Args:
        driver: BaseDriver 实例
        vision: VisionAdapter 实例
        capture_func: 截图函数（可选）
        
    Returns:
        TaskRuntime: 配置好的运行时
    """
    # 导入微观闭环
    try:
        from tactical.micro_loop import execute_step, StepFailedError
    except ImportError:
        from micro_loop import execute_step, StepFailedError
    
    # 创建绑定的 step 函数
    def bound_step(goal: str) -> bool:
        try:
            result = execute_step(
                goal=goal,
                driver=driver,
                vision=vision,
                capture_func=capture_func,
                max_retries=1,
                cooldown=1.5,
                verify=True
            )
            return result.success
        except StepFailedError:
            return False
    
    return TaskRuntime(step_function=bound_step)


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== Task 3.1 TaskRuntime 测试 ===\n")
    
    # 创建模拟的 step 函数
    step_counter = [0]
    
    def mock_step(goal: str) -> bool:
        step_counter[0] += 1
        print(f"  [Mock Step {step_counter[0]}] {goal}")
        return True
    
    runtime = TaskRuntime(step_function=mock_step, max_steps=10)
    
    # 测试 1: 简单循环
    print("--- 测试 1: 简单循环 ---")
    code1 = '''
for i in range(3):
    step(f"点击第{i+1}个点赞按钮")
'''
    result = runtime.execute(code1)
    print(f"✅ 成功: {result.success}, 总步数: {result.total_steps}")
    
    # 测试 2: 条件判断
    print("\n--- 测试 2: 条件判断 ---")
    step_counter[0] = 0
    code2 = '''
step("打开设置")
step("找到WiFi选项")
step("点击WiFi")
'''
    result = runtime.execute(code2)
    print(f"✅ 成功: {result.success}, 总步数: {result.total_steps}")
    
    # 测试 3: 语法错误
    print("\n--- 测试 3: 语法错误 ---")
    code3 = '''
for i in range(3)  # 缺少冒号
    step("test")
'''
    result = runtime.execute(code3)
    print(f"❌ 失败（预期）: {result.success}, 错误: {result.error}")
    
    # 测试 4: 禁止危险操作
    print("\n--- 测试 4: 禁止危险操作 ---")
    code4 = '''
import os  # 应该被阻止
os.system("ls")
'''
    result = runtime.execute(code4)
    print(f"❌ 失败（预期）: {result.success}, 错误: {result.error}")
    
    print("\n=== 测试完成 ===")
