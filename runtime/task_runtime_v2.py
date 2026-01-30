#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Task Runtime - The Logic Container

创建一个能运行 LLM 代码的沙盒，只暴露语义接口。

核心功能:
1. 准备 locals 字典，注入语义控制函数
2. step(goal, expect) 透传调用 AutoGLMDriver.execute_step()
3. ask(question) 查询当前界面状态
4. checkpoint(description) 验证检查点
5. 异常处理: SafetyError 或 MaxRetryError 立即终止并报警

Long-horizon Planning 支持:
- step() 返回 StepResult，包含状态反馈
- ask() 允许策略层动态查询界面
- checkpoint() 支持循环终止判断
"""

import os
import sys
import logging
from typing import Optional, Dict, Any, Callable
from io import StringIO

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tactical.autoglm_driver import AutoGLMDriver, SafetyError, MaxRetryError, StepResult

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class TaskRuntime:
    """任务运行时 - 代码执行沙盒
    
    职责:
    1. 创建安全的执行环境 (只注入必要的函数)
    2. 提供 step(goal, expect) 接口 (透传给 AutoGLMDriver)
    3. 提供 ask(question) 查询界面状态
    4. 提供 checkpoint(description) 验证检查点
    5. 处理异常 (SafetyError/MaxRetryError)
    6. 捕获执行日志
    
    Example:
        driver = AutoGLMDriver(api_key, hardware_driver)
        runtime = TaskRuntime(driver)
        
        code = '''
        step('打开相册')
        
        # 使用 checkpoint 实现 Long-horizon Planning
        while checkpoint('还有照片需要删除'):
            step('长按第一张照片', expect='进入选择模式')
            step('点击删除')
            step('确认删除')
        
        # 使用 ask 动态查询
        answer = ask('当前界面显示什么?')
        print(f'界面状态: {answer}')
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
                logger.info("[TaskRuntime] 执行完成")
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
            logger.error(f"[TaskRuntime] 安全检查失败: {e}")
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
            logger.error(f"[TaskRuntime] 达到最大重试次数: {e}")
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
            logger.error(f"[TaskRuntime] 执行异常: {e}")
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
        
        def step(goal: str, expect: str = None) -> StepResult:
            """语义操作接口 - 透传给 AutoGLMDriver
            
            Args:
                goal: 语义目标描述 (如 "点击搜索框")
                expect: 期望结果描述 (可选, 如 "显示搜索页面")
                
            Returns:
                StepResult: 包含 success, state, has_more 属性
                
            Raises:
                SafetyError: 安全检查失败
                MaxRetryError: 达到最大重试次数
                
            Example:
                result = step('点击确定按钮', expect='返回主页面')
                if result.success:
                    print(f'当前状态: {result.state}')
            """
            log_msg = f"step('{goal}'"
            if expect:
                log_msg += f", expect='{expect}'"
            log_msg += ")"
            
            logger.info(f"[TaskRuntime] -> {log_msg}")
            self.execution_log.append(log_msg)
            
            result = self.autoglm_driver.execute_step(goal, expect)
            
            logger.info(f"[TaskRuntime] <- {result}")
            return result
        
        def ask(question: str) -> str:
            """查询当前界面状态
            
            Args:
                question: 问题 (如 "当前页面是什么?")
                
            Returns:
                str: AutoGLM 对当前界面的回答
                
            Example:
                answer = ask('屏幕上显示多少张照片?')
                if '0' in answer:
                    print('没有照片了')
            """
            logger.info(f"[TaskRuntime] -> ask('{question}')")
            self.execution_log.append(f"ask('{question}')")
            
            answer = self.autoglm_driver.ask(question)
            
            logger.info(f"[TaskRuntime] <- '{answer}'")
            return answer
        
        def checkpoint(description: str) -> bool:
            """验证检查点 - 支持循环终止判断
            
            Args:
                description: 期望状态描述 (如 "还有照片需要删除")
                
            Returns:
                bool: 当前界面是否符合描述
                
            Example:
                # 循环删除直到没有照片
                while checkpoint('还有照片需要删除'):
                    step('删除第一张照片')
            """
            logger.info(f"[TaskRuntime] -> checkpoint('{description}')")
            self.execution_log.append(f"checkpoint('{description}')")
            
            result = self.autoglm_driver.checkpoint(description)
            
            logger.info(f"[TaskRuntime] <- {result}")
            return result
        
        # 注入语义控制函数
        local_env = {
            # 核心语义接口
            'step': step,
            'ask': ask,
            'checkpoint': checkpoint,
            
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
        """停止执行 (用于外部中断)"""
        if self.is_running:
            logger.warning("[TaskRuntime] 收到停止信号")
            self.is_running = False
    
    def get_last_error(self) -> Optional[Exception]:
        """获取最后的错误"""
        return self.last_error


# ==================== 测试 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("TaskRuntime 测试 (v2 - Long-horizon Planning)")
    print("=" * 60)
    
    # 创建 Mock 环境
    from drivers.mock_driver import MockDriver
    from tactical.autoglm_driver import create_autoglm_driver
    
    mock_driver = MockDriver()
    autoglm_driver = create_autoglm_driver(driver=mock_driver)
    runtime = TaskRuntime(autoglm_driver)
    
    # 测试 1: 简单任务
    print("\n测试 1: 简单任务")
    code1 = """
result = step('打开应用')
print(f'步骤结果: {result.success}, 状态: {result.state}')

result = step('点击搜索', expect='显示搜索页面')
print(f'步骤结果: {result}')
"""
    result1 = runtime.execute(code1)
    print(f"执行结果: {result1}")
    
    # 测试 2: 使用 ask 查询界面
    print("\n测试 2: 使用 ask 查询界面")
    code2 = """
answer = ask('当前界面是什么?')
print(f'界面状态: {answer}')
"""
    result2 = runtime.execute(code2)
    print(f"执行结果: {result2}")
    
    # 测试 3: 使用 checkpoint 循环
    print("\n测试 3: 使用 checkpoint 循环 (Mock 模式下 checkpoint 返回 False)")
    code3 = """
step('打开相册')

# 在实际环境中，checkpoint 会通过视觉判断
# Mock 模式下直接返回 False，循环不会执行
counter = 0
while checkpoint('还有照片需要删除') and counter < 5:
    step('删除第一张照片')
    counter += 1

print(f'共执行 {counter} 次删除')
"""
    result3 = runtime.execute(code3)
    print(f"执行结果: {result3}")
    
    # 测试 4: 综合 Long-horizon 任务
    print("\n测试 4: 综合 Long-horizon 任务")
    code4 = """
# 模拟：删除所有去年的照片
step('打开相册')
step('进入去年的相簿')

# 查询照片数量
count = ask('当前显示多少张照片?')
print(f'照片数量: {count}')

# 逐个删除
for i in range(2):  # Mock 环境中只执行 2 次
    result = step(f'长按第{i+1}张照片', expect='进入选择模式')
    if result.success:
        step('点击删除')
        step('确认删除')
    else:
        print(f'选择失败: {result.error}')
        break

step('返回主页')
"""
    result4 = runtime.execute(code4)
    print(f"执行结果: {result4}")
    
    # 显示执行日志
    print("\n执行日志:")
    for log in result4.get('log', []):
        print(f"  {log}")
