"""
战术层模块 - AutoGLM 感知决策执行

包含:
- AutoGLMDriver: 新的三层架构驱动
- StepResult: 步骤执行结果（支持 Long-horizon Planning）
- VisionAdapter: 视觉适配器
"""

# 延迟导入，避免循环依赖
def __getattr__(name):
    if name == 'AutoGLMDriver':
        from .autoglm_driver import AutoGLMDriver
        return AutoGLMDriver
    elif name == 'StepResult':
        from .autoglm_driver import StepResult
        return StepResult
    elif name == 'VisionAdapter':
        from .vision_adapter import VisionAdapter
        return VisionAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'AutoGLMDriver',
    'StepResult',
    'VisionAdapter',
]
