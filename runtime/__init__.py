"""
运行时模块 - 代码执行沙盒

包含:
- TaskRuntime: 代码执行沙盒
- StepResult: 步骤执行结果（从 tactical 重导出）
"""

from .task_runtime_v2 import TaskRuntime
from tactical.autoglm_driver import StepResult

__all__ = [
    'TaskRuntime',
    'StepResult',
]
