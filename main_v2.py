#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Semantic Agent - 重构后的简化入口

重构核心思想:
============
AutoGLM (autoglm-phone) 是专用的手机控制模型，本身就是"端到端"的。
不需要:
- Planner 生成 Python 代码
- VisionAdapter 单独分析截图
- TaskRuntime 执行沙盒代码

只需要:
1. 截图
2. 发送给 AutoGLM
3. 执行返回的操作
4. 循环

架构:
=====
用户指令 → AutoGLMController → Driver
              ↑        ↓
         截图 ←← 执行操作
"""

import os
import sys
import logging
from typing import Optional

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """主函数"""
    print("=" * 60)
    print("🤖 Semantic Agent - AutoGLM 手机控制系统")
    print("=" * 60)
    
    # 1. 检查 API Key
    api_key = os.getenv('ZHIPUAI_API_KEY')
    if not api_key or api_key == 'your_api_key_here':
        print("\n⚠️ 请配置 ZHIPUAI_API_KEY 环境变量:")
        print("   export ZHIPUAI_API_KEY='your_actual_key'")
        print("\n当前将使用 Mock 模式运行演示...")
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
    
    # 3. 创建控制器
    from core.autoglm_controller import AutoGLMController
    
    controller = AutoGLMController(
        api_key=api_key,
        driver=driver,
        model="autoglm-phone",
        max_loops=20,
        action_delay=0.5
    )
    
    if api_key != "mock" and controller.is_available():
        print("✅ AutoGLM 控制器初始化成功")
    else:
        print("⚠️ AutoGLM 客户端未初始化，将使用离线模式")
    
    # 4. 交互循环
    print("\n" + "=" * 60)
    print("📱 输入任务指令开始执行 (输入 'quit' 退出)")
    print("=" * 60)
    
    while True:
        try:
            instruction = input("\n🎯 任务: ").strip()
            
            if not instruction:
                continue
            
            if instruction.lower() in ['quit', 'exit', 'q']:
                print("\n👋 再见!")
                break
            
            # 执行任务
            print(f"\n📲 开始执行: {instruction}")
            print("-" * 40)
            
            result = controller.execute_task(instruction)
            
            print("-" * 40)
            if result['success']:
                print(f"✅ 任务完成!")
                print(f"   循环次数: {result['loops']}")
                print(f"   操作次数: {result['actions']}")
            else:
                print(f"❌ 任务失败: {result.get('error', '未知错误')}")
                print(f"   循环次数: {result.get('loops', 0)}")
                print(f"   操作次数: {result.get('actions', 0)}")
            
        except KeyboardInterrupt:
            print("\n\n👋 中断，再见!")
            break
        except Exception as e:
            logger.error(f"错误: {e}")
            continue


def run_demo():
    """运行演示"""
    print("=" * 60)
    print("🎬 Semantic Agent 演示")
    print("=" * 60)
    
    from drivers.mock_driver import MockDriver
    from core.autoglm_controller import AutoGLMController
    
    driver = MockDriver()
    controller = AutoGLMController(
        api_key="demo",
        driver=driver,
        max_loops=5
    )
    
    # 模拟解析测试
    test_cases = [
        "Tap(0.5, 0.3) - 点击搜索框",
        "Swipe(0.5, 0.8, 0.5, 0.2) - 向上滑动",
        "Type('美食') - 输入搜索词",
        "Task_finished - 任务完成",
        "Take_over - 需要人工处理验证码"
    ]
    
    print("\n📝 测试 AutoGLM 响应解析:")
    print("-" * 40)
    
    for content in test_cases:
        actions = controller._parse_actions(content)
        if actions:
            a = actions[0]
            print(f"  输入: {content}")
            print(f"  解析: {a.action} | params={a.params}")
            print()
    
    print("✅ 解析测试完成")
    
    # 显示驱动日志
    print("\n📋 驱动操作日志:")
    for action in driver.get_actions_log():
        print(f"  {action}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Semantic Agent - AutoGLM 手机控制')
    parser.add_argument('--demo', action='store_true', help='运行演示')
    
    args = parser.parse_args()
    
    if args.demo:
        run_demo()
    else:
        main()
