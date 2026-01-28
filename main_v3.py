#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Main Entry - The Pipeline

串联整个链路: 用户输入 → LLM 生成代码 → TaskRuntime 执行 → AutoGLMDriver 驱动

实时打印: [LLM] Plan -> [AutoGLM] See -> [Arm] Act
"""

import os
import sys
import logging
from typing import Optional

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from drivers.base_driver import BaseDriver
from tactical.autoglm_driver import AutoGLMDriver, SafetyError, MaxRetryError
from runtime.task_runtime_v2 import TaskRuntime
from brain.strategy_prompt import get_strategy_prompt, create_user_prompt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class SemanticAgent:
    """语义代理 - 完整的三层架构
    
    L1 策略层 (LLM): 生成 Python 代码
    L2 运行时 (TaskRuntime): 执行代码，提供 step() 接口
    L3 战术层 (AutoGLMDriver): 实现 step() 的微观闭环
    """
    
    def __init__(
        self,
        zhipuai_api_key: str,
        driver: BaseDriver,
        strategy_model: str = "glm-4-flash",
        tactical_model: str = "autoglm-phone"
    ):
        """初始化
        
        Args:
            zhipuai_api_key: 智谱 API Key
            driver: 硬件驱动
            strategy_model: 策略层模型（用于代码生成）
            tactical_model: 战术层模型（用于视觉定位）
        """
        self.zhipuai_api_key = zhipuai_api_key
        self.strategy_model = strategy_model
        
        # 初始化 L3 战术层
        self.autoglm_driver = AutoGLMDriver(
            api_key=zhipuai_api_key,
            driver=driver,
            model=tactical_model
        )
        
        # 初始化 L2 运行时
        self.runtime = TaskRuntime(self.autoglm_driver)
        
        # 初始化 L1 策略层客户端
        self.llm_client = None
        self._init_llm_client()
        
        logger.info("[SemanticAgent] ✅ 初始化完成")
        logger.info(f"  - 策略层: {strategy_model}")
        logger.info(f"  - 战术层: {tactical_model}")
    
    def _init_llm_client(self):
        """初始化 LLM 客户端"""
        try:
            from zhipuai import ZhipuAI
            self.llm_client = ZhipuAI(api_key=self.zhipuai_api_key)
            logger.info("[SemanticAgent] ✅ LLM 客户端初始化成功")
        except ImportError:
            logger.error("[SemanticAgent] ❌ zhipuai 未安装")
        except Exception as e:
            logger.error(f"[SemanticAgent] ❌ LLM 客户端初始化失败: {e}")
    
    def execute_task(self, user_instruction: str) -> dict:
        """执行用户任务
        
        Args:
            user_instruction: 用户自然语言指令
            
        Returns:
            dict: 执行结果
        """
        logger.info("=" * 80)
        logger.info(f"[SemanticAgent] 🎯 用户任务: {user_instruction}")
        logger.info("=" * 80)
        
        # Step 1: 请求 LLM 生成代码
        logger.info("\n[LLM] 📝 Plan - 生成执行脚本...")
        code = self._call_llm(user_instruction)
        
        if code is None:
            logger.error("[LLM] ❌ 代码生成失败")
            return {
                'success': False,
                'error': 'LLM 代码生成失败',
                'code': None
            }
        
        logger.info("\n[LLM] ✅ 生成的代码:")
        logger.info("-" * 60)
        for i, line in enumerate(code.split('\n'), 1):
            logger.info(f"  {i:2d} | {line}")
        logger.info("-" * 60)
        
        # Step 2: 执行代码
        logger.info("\n[Runtime] ⚙️  Execute - 开始执行...")
        result = self.runtime.execute(code)
        
        # Step 3: 输出结果
        logger.info("\n" + "=" * 80)
        if result['success']:
            logger.info(f"[SemanticAgent] ✅ 任务完成!")
            logger.info(f"  - 执行步骤: {result['steps']}")
            logger.info(f"  - 重试次数: {result['retries']}")
        else:
            logger.error(f"[SemanticAgent] ❌ 任务失败: {result['error']}")
            logger.error(f"  - 已执行步骤: {result['steps']}")
            logger.error(f"  - 重试次数: {result['retries']}")
        logger.info("=" * 80)
        
        return {
            'success': result['success'],
            'error': result.get('error'),
            'code': code,
            'steps': result['steps'],
            'retries': result['retries'],
            'log': result['log']
        }
    
    def _call_llm(self, user_instruction: str) -> Optional[str]:
        """调用 LLM 生成代码
        
        Args:
            user_instruction: 用户指令
            
        Returns:
            str: Python 代码，或 None（失败）
        """
        if not self.llm_client:
            logger.warning("[LLM] Mock 模式，返回示例代码")
            return f"step('打开应用')\nstep('{user_instruction}')"
        
        system_prompt = get_strategy_prompt()
        user_prompt = create_user_prompt(user_instruction)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            response = self.llm_client.chat.completions.create(
                model=self.strategy_model,
                messages=messages,
                temperature=0.3,
                max_tokens=2000
            )
            
            code = response.choices[0].message.content.strip()
            
            # 清理可能的 Markdown 代码块标记
            if code.startswith('```python'):
                code = code[len('```python'):].strip()
            if code.startswith('```'):
                code = code[3:].strip()
            if code.endswith('```'):
                code = code[:-3].strip()
            
            return code
            
        except Exception as e:
            logger.error(f"[LLM] API 错误: {e}")
            return None


def main():
    """主函数"""
    print("=" * 80)
    print("🤖 Semantic Agent - 三层架构手机控制系统")
    print("=" * 80)
    print("\n架构:")
    print("  L1 策略层 (LLM)      → 生成 Python 脚本")
    print("  L2 运行时 (Runtime)   → 执行代码，提供 step()")
    print("  L3 战术层 (AutoGLM)  → 视觉定位 + 微观闭环")
    print("=" * 80)
    
    # 1. 检查 API Key
    api_key = os.getenv('ZHIPUAI_API_KEY')
    if not api_key or api_key == 'your_api_key_here':
        print("\n⚠️ 请配置 ZHIPUAI_API_KEY 环境变量:")
        print("   export ZHIPUAI_API_KEY='your_actual_key'")
        print("\n当前将使用 Mock 模式运行...")
        api_key = "mock"
    else:
        print(f"\n✅ API Key 已配置: {api_key[:8]}...")
    
    # 2. 选择驱动
    print("\n选择硬件驱动:")
    print("  1. Mock (测试模式)")
    print("  2. Serial (串口/机械臂)")
    print("  3. WiFi (ESP32-S3)")
    
    driver = None
    try:
        choice = input("\n请选择 (1-3, 默认 1): ").strip() or "1"
        
        if choice == "1":
            from drivers.mock_driver import MockDriver
            driver = MockDriver()
            print("✅ 使用 Mock 驱动")
            
        elif choice == "2":
            from drivers.serial_driver import SerialDriver
            port = input("串口 (默认 /dev/ttyUSB0): ").strip() or "/dev/ttyUSB0"
            driver = SerialDriver(port=port)
            print(f"✅ 使用 Serial 驱动: {port}")
            
        elif choice == "3":
            from drivers.wifi_driver import WiFiDriver
            ip = input("ESP32 IP (默认 192.168.1.100): ").strip() or "192.168.1.100"
            driver = WiFiDriver(device_ip=ip)
            print(f"✅ 使用 WiFi 驱动: {ip}")
            
        else:
            print("❌ 无效选择，使用 Mock 驱动")
            from drivers.mock_driver import MockDriver
            driver = MockDriver()
            
    except ImportError as e:
        print(f"⚠️ 驱动加载失败: {e}")
        print("使用 Mock 驱动...")
        from drivers.mock_driver import MockDriver
        driver = MockDriver()
    
    # 3. 创建 SemanticAgent
    agent = SemanticAgent(
        zhipuai_api_key=api_key,
        driver=driver,
        strategy_model="glm-4-flash",
        tactical_model="autoglm-phone"
    )
    
    # 4. 交互循环
    print("\n" + "=" * 80)
    print("📱 输入任务指令开始执行 (输入 'quit' 退出)")
    print("=" * 80)
    
    while True:
        try:
            instruction = input("\n🎯 任务: ").strip()
            
            if not instruction:
                continue
            
            if instruction.lower() in ['quit', 'exit', 'q']:
                print("\n👋 再见!")
                break
            
            # 执行任务
            result = agent.execute_task(instruction)
            
            # 显示摘要
            print("\n📊 执行摘要:")
            print(f"  - 状态: {'✅ 成功' if result['success'] else '❌ 失败'}")
            if not result['success']:
                print(f"  - 错误: {result['error']}")
            print(f"  - 步骤: {result['steps']}")
            print(f"  - 重试: {result['retries']}")
            
        except KeyboardInterrupt:
            print("\n\n👋 中断，再见!")
            break
        except Exception as e:
            logger.error(f"错误: {e}")
            import traceback
            traceback.print_exc()
            continue


def demo():
    """演示模式"""
    print("=" * 80)
    print("🎬 Semantic Agent 演示模式")
    print("=" * 80)
    
    from drivers.mock_driver import MockDriver
    
    driver = MockDriver()
    agent = SemanticAgent(
        zhipuai_api_key="demo",
        driver=driver
    )
    
    # 测试任务
    test_tasks = [
        "打开微信，给张三发消息'晚上吃饭'",
        "清空购物车",
        "给前 3 个视频点赞",
    ]
    
    for task in test_tasks:
        print(f"\n\n{'='*80}")
        print(f"测试任务: {task}")
        print('='*80)
        
        result = agent.execute_task(task)
        
        print(f"\n结果: {'✅' if result['success'] else '❌'}")
        print(f"步骤: {result['steps']}, 重试: {result['retries']}")
        
        input("\n按回车继续...")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Semantic Agent - 三层架构手机控制')
    parser.add_argument('--demo', action='store_true', help='运行演示')
    
    args = parser.parse_args()
    
    if args.demo:
        demo()
    else:
        main()
