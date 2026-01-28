#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Task Runtime - The Logic Container

创建一个能运行 LLM 代码的沙盒，只暴露语义接口。

核心功能:
1. 准备 locals 字典，只注入 step 函数
2. step(goal) 直接透传调用 AutoGLMDriver.execute_step(goal)
3. 异常处理: SafetyError 或 MaxRetryError 立即终止并报警
"""

import os
import sys
import logging
from typing import Optional, Dict, Any, Callable
from io import StringIO

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tactical.autoglm_driver import AutoGLMDriver, SafetyError, MaxRetryError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class TaskRuntime:
    """任务运行时 - 代码执行沙盒
    
    职责:
    1. 创建安全的执行环境（只注入必要的函数）
    2. 提供 step(goal) 接口（透传给 AutoGLMDriver）
    3. 处理异常（SafetyError/MaxRetryError）
    4. 捕获执行日志
    
    Example:
        driver = AutoGLMDriver(api_key, hardware_driver)
        runtime = TaskRuntime(driver)
        
        code = '''
        step('打开购物车')
        for i in range(3):
            step(f'选中第{i+1}个商品')
            step('点击删除')
        '''
        
        result = runtime.execute(code)
    """
    
    def __init__(self, autoglm_driver: AutoGLMDriver):
        """初始化
        
        Args:
            autoglm_driver: AutoGLMDriver 实例
        """
        self.autoglm_driver = autoglm_driver
        
        # 执行状态
        self.is_running = False
        self.last_error: Optional[Exception] = None
        
        # 日志捕获
        self.execution_log = []
        
        logger.info("[TaskRuntime] 初始化完成")
    
    def execute(self, code: str) -> Dict[str, Any]:
        """执行 LLM 生成的代码
        
        Args:
            code: Python 代码字符串
            
        Returns:
            Dict: 执行结果
            {
                'success': bool,
                'error': Optional[str],
                'steps': int,
                'retries': int,
                'log': List[str]
            }
        """
        logger.info("=" * 60)
        logger.info("[TaskRuntime] 开始执行代码")
        logger.info("=" * 60)
        logger.info(f"代码:\n{code}")
        logger.info("-" * 60)
        
        self.is_running = True
        self.last_error = None
        self.execution_log = []
        
        try:
            # 准备执行环境
            local_env = self._prepare_environment()
            
            # 捕获 stdout
            old_stdout = sys.stdout
            sys.stdout = StringIO()
            
            try:
                # 执行代码
                exec(code, {}, local_env)
                
                # 成功
                logger.info("=" * 60)
                logger.info("[TaskRuntime] ✅ 执行完成")
                logger.info("=" * 60)
                
                stats = self.autoglm_driver.get_stats()
                
                return {
                    'success': True,
                    'error': None,
                    'steps': stats['total_steps'],
                    'retries': stats['total_retries'],
                    'log': self.execution_log
                }
                
            finally:
                # 恢复 stdout
                captured_output = sys.stdout.getvalue()
                sys.stdout = old_stdout
                if captured_output:
                    logger.debug(f"捕获的输出:\n{captured_output}")
        
        except SafetyError as e:
            logger.error("=" * 60)
            logger.error(f"[TaskRuntime] 🚨 安全检查失败: {e}")
            logger.error("=" * 60)
            self.last_error = e
            
            return {
                'success': False,
                'error': f'SafetyError: {e}',
                'steps': self.autoglm_driver.get_stats()['total_steps'],
                'retries': self.autoglm_driver.get_stats()['total_retries'],
                'log': self.execution_log
            }
        
        except MaxRetryError as e:
            logger.error("=" * 60)
            logger.error(f"[TaskRuntime] ❌ 达到最大重试次数: {e}")
            logger.error("=" * 60)
            self.last_error = e
            
            return {
                'success': False,
                'error': f'MaxRetryError: {e}',
                'steps': self.autoglm_driver.get_stats()['total_steps'],
                'retries': self.autoglm_driver.get_stats()['total_retries'],
                'log': self.execution_log
            }
        
        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"[TaskRuntime] ❌ 执行异常: {e}")
            logger.error("=" * 60)
            self.last_error = e
            
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'error': f'ExecutionError: {e}',
                'steps': self.autoglm_driver.get_stats()['total_steps'],
                'retries': self.autoglm_driver.get_stats()['total_retries'],
                'log': self.execution_log
            }
        
        finally:
            self.is_running = False
    
    def _prepare_environment(self) -> Dict[str, Any]:
        """准备执行环境 - 只注入必要的函数
        
        Returns:
            Dict: locals 字典
        """
        
        def step(goal: str) -> bool:
            """语义操作接口 - 透传给 AutoGLMDriver
            
            Args:
                goal: 语义目标描述
                
            Returns:
                bool: 成功返回 True
                
            Raises:
                SafetyError: 安全检查失败
                MaxRetryError: 达到最大重试次数
            """
            logger.info(f"[TaskRuntime] → step('{goal}')")
            self.execution_log.append(f"step('{goal}')")
            
            result = self.autoglm_driver.execute_step(goal)
            
            return result
        
        # 只注入 step 函数
        # 不提供其他危险函数（如 open, exec, import 等）
        local_env = {
            'step': step,
            # 允许基本的 Python 内置函数
            'range': range,
            'len': len,
            'print': print,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'True': True,
            'False': False,
            'None': None,
        }
        
        return local_env
    
    def stop(self):
        """停止执行（用于外部中断）"""
        if self.is_running:
            logger.warning("[TaskRuntime] ⚠️ 收到停止信号")
            self.is_running = False
    
    def get_last_error(self) -> Optional[Exception]:
        """获取最后的错误"""
        return self.last_error


# ==================== 测试 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("TaskRuntime 测试")
    print("=" * 60)
    
    # 创建 Mock 环境
    from drivers.mock_driver import MockDriver
    from tactical.autoglm_driver import create_autoglm_driver
    
    mock_driver = MockDriver()
    autoglm_driver = create_autoglm_driver(driver=mock_driver)
    runtime = TaskRuntime(autoglm_driver)
    
    # 测试简单代码
    print("\n测试 1: 简单任务")
    code1 = """
step('打开应用')
step('点击搜索')
"""
    result1 = runtime.execute(code1)
    print(f"结果: {result1}")
    
    # 测试循环
    print("\n测试 2: 循环任务")
    code2 = """
step('打开相册')
for i in range(3):
    step(f'选择第{i+1}张照片')
step('删除')
"""
    result2 = runtime.execute(code2)
    print(f"结果: {result2}")
    
    # 显示驱动日志
    print("\n驱动操作日志:")
    for action in mock_driver.get_actions_log():
        print(f"  {action}")
