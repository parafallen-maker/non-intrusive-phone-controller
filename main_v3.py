#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Main Entry - The Pipeline (v3.2 with Cloud Skill System)

串联整个链路: 用户输入 → 技能检索 → LLM 生成代码 → TaskRuntime 执行 → 技能蒸馏

功能增强:
- 技能检索: 执行前先检查是否有匹配的现成技能
- 技能蒸馏: 执行成功后自动提取可复用技能
- Long-horizon Planning: 支持 step/ask/checkpoint 接口
- 云端同步: 技能可在多设备间共享
"""

import os
import sys
import logging
from typing import Optional, Tuple

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from drivers.base_driver import BaseDriver
from tactical.autoglm_driver import AutoGLMDriver, SafetyError, MaxRetryError, StepResult
from runtime.task_runtime_v2 import TaskRuntime
from brain.strategy_prompt import get_strategy_prompt, create_user_prompt

# 新的技能系统
from skills import SkillManager, Skill, SkillMatch, init_skill_manager

# 向后兼容：尝试导入旧的蒸馏器
try:
    from skills.skill_distiller import SkillDistiller, ExecutionTrace, DistilledSkill
    HAS_LEGACY_DISTILLER = True
except ImportError:
    HAS_LEGACY_DISTILLER = False
    SkillDistiller = None
    ExecutionTrace = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class SemanticAgent:
    """语义代理 - 完整的三层架构 + 技能系统
    
    L1 策略层 (LLM): 生成 Python 代码
    L2 运行时 (TaskRuntime): 执行代码，提供 step()/ask()/checkpoint()
    L3 战术层 (AutoGLMDriver): 实现微观闭环
    
    技能系统 v2:
    - SkillManager: 统一的技能管理入口
    - 支持本地/云端存储
    - 多设备共享
    """
    
    def __init__(
        self,
        zhipuai_api_key: str,
        driver: BaseDriver,
        strategy_model: str = "glm-4-flash",
        tactical_model: str = "autoglm-phone",
        skill_store_path: str = "./skill_store",
        enable_skills: bool = True,
        skill_match_threshold: float = 0.7,
        # 云端配置（可选）
        skill_api_url: Optional[str] = None,
        skill_api_key: Optional[str] = None,
        device_id: Optional[str] = None
    ):
        """初始化
        
        Args:
            zhipuai_api_key: 智谱 API Key
            driver: 硬件驱动
            strategy_model: 策略层模型 (用于代码生成)
            tactical_model: 战术层模型 (用于视觉定位)
            skill_store_path: 技能存储路径
            enable_skills: 是否启用技能系统
            skill_match_threshold: 技能匹配阈值 (0-1)
            skill_api_url: 云端技能服务 URL（可选）
            skill_api_key: 云端技能服务 API Key（可选）
            device_id: 设备 ID（可选）
        """
        self.zhipuai_api_key = zhipuai_api_key
        self.strategy_model = strategy_model
        self.enable_skills = enable_skills
        self.skill_match_threshold = skill_match_threshold
        
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
        
        # 初始化技能系统 v2
        self.skill_manager: Optional[SkillManager] = None
        if enable_skills:
            self._init_skill_system(
                skill_store_path,
                skill_api_url,
                skill_api_key,
                device_id
            )
        
        logger.info("[SemanticAgent] 初始化完成")
        logger.info(f"  - 策略层: {strategy_model}")
        logger.info(f"  - 战术层: {tactical_model}")
        logger.info(f"  - 技能系统: {'启用' if enable_skills else '禁用'}")
        if self.skill_manager:
            stats = self.skill_manager.get_stats()
            logger.info(f"  - 本地技能数: {stats.get('local_count', 0)}")
            logger.info(f"  - 云端连接: {'是' if stats.get('has_remote') else '否'}")
    
    def _init_llm_client(self):
        """初始化 LLM 客户端"""
        try:
            from zhipuai import ZhipuAI
            self.llm_client = ZhipuAI(api_key=self.zhipuai_api_key)
            logger.info("[SemanticAgent] LLM 客户端初始化成功")
        except ImportError:
            logger.error("[SemanticAgent] zhipuai 未安装")
        except Exception as e:
            logger.error(f"[SemanticAgent] LLM 客户端初始化失败: {e}")
    
    def _init_skill_system(
        self,
        skill_store_path: str,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        device_id: Optional[str] = None
    ):
        """初始化技能系统 v2
        
        支持本地或云端模式
        """
        try:
            # 从环境变量获取配置（如果未提供）
            api_url = api_url or os.getenv("SKILL_API_URL")
            api_key = api_key or os.getenv("SKILL_API_KEY")
            device_id = device_id or os.getenv("DEVICE_ID")
            
            if api_url and api_key and device_id:
                # 云端模式
                self.skill_manager = SkillManager.create_cloud(
                    local_dir=skill_store_path,
                    api_url=api_url,
                    api_key=api_key,
                    device_id=device_id
                )
                logger.info(f"[SemanticAgent] 技能系统初始化成功（云端模式）")
            else:
                # 本地模式
                self.skill_manager = SkillManager.create_local(skill_store_path)
                logger.info(f"[SemanticAgent] 技能系统初始化成功（本地模式）")
            
            skill_count = len(self.skill_manager.list_all())
            logger.info(f"[SemanticAgent] 已加载 {skill_count} 个技能")
            
        except Exception as e:
            logger.error(f"[SemanticAgent] 技能系统初始化失败: {e}")
            self.skill_manager = None
    
    def _search_skill(self, instruction: str) -> Optional[Tuple[Skill, float]]:
        """搜索匹配的技能
        
        Args:
            instruction: 用户指令
            
        Returns:
            (技能, 匹配分数) 或 None
        """
        if not self.skill_manager:
            return None
        
        matches = self.skill_manager.search(
            instruction,
            limit=1,
            min_score=self.skill_match_threshold
        )
        
        if matches:
            match = matches[0]
            return (match.skill, match.score)
        
        return None
    
    def _distill_and_save_skill(
        self,
        instruction: str,
        code: str,
        execution_log: list,
        success: bool
    ):
        """蒸馏并保存技能
        
        Args:
            instruction: 用户指令
            code: 执行的代码
            execution_log: 执行日志
            success: 是否成功
        """
        if not self.skill_manager:
            return
        
        if not success:
            logger.debug("[SemanticAgent] 执行失败，跳过技能蒸馏")
            return
        
        # 检查是否已存在相似技能
        if not self.skill_manager.should_distill(instruction):
            logger.debug("[SemanticAgent] 已存在相似技能，跳过蒸馏")
            return
        
        try:
            # 创建技能
            skill = Skill(
                id=f"skill_{hash(instruction) % 100000:05d}",
                name=self._extract_skill_name(instruction),
                description=instruction,
                code=code,
                tags=self._extract_tags(instruction),
                source="distilled"
            )
            
            # 保存
            skill_id = self.skill_manager.save(skill)
            logger.info(f"[SemanticAgent] 技能已蒸馏保存: {skill.name} ({skill_id})")
            
        except Exception as e:
            logger.warning(f"[SemanticAgent] 技能蒸馏失败: {e}")
    
    def _extract_skill_name(self, instruction: str) -> str:
        """从指令中提取技能名称"""
        # 简单实现：取前20个字符
        name = instruction[:20].strip()
        if len(instruction) > 20:
            name += "..."
        return name
    
    def _extract_tags(self, instruction: str) -> list:
        """从指令中提取标签"""
        tags = []
        
        # 应用名称识别
        app_keywords = {
            "微信": ["微信", "社交"],
            "支付宝": ["支付宝", "支付"],
            "淘宝": ["淘宝", "购物"],
            "抖音": ["抖音", "短视频"],
            "微博": ["微博", "社交"],
            "美团": ["美团", "外卖"],
            "高德": ["高德", "导航"],
            "地图": ["地图", "导航"],
        }
        
        for keyword, app_tags in app_keywords.items():
            if keyword in instruction:
                tags.extend(app_tags)
                break
        
        # 动作识别
        action_keywords = {
            "发送": "发送",
            "点赞": "点赞",
            "评论": "评论",
            "搜索": "搜索",
            "打开": "打开",
            "返回": "导航",
        }
        
        for keyword, tag in action_keywords.items():
            if keyword in instruction:
                tags.append(tag)
        
        return list(set(tags))  # 去重
    
    def execute_task(self, user_instruction: str) -> dict:
        """执行用户任务
        
        流程:
        1. 搜索匹配技能 (如果启用)
        2. 使用技能代码或调用 LLM 生成代码
        3. 执行代码
        4. 蒸馏并保存技能 (如果启用且成功)
        
        Args:
            user_instruction: 用户自然语言指令
            
        Returns:
            dict: 执行结果
        """
        logger.info("=" * 80)
        logger.info(f"[SemanticAgent] 任务: {user_instruction}")
        logger.info("=" * 80)
        
        code = None
        skill_used = None
        
        # Step 1: 检索已有技能
        if self.enable_skills and self.skill_manager:
            logger.info("\n[Skill] 检索匹配技能...")
            skill_match = self._search_skill(user_instruction)
            
            if skill_match:
                skill, score = skill_match
                logger.info(f"[Skill] 找到匹配技能: {skill.name} (分数: {score:.2f})")
                logger.info(f"[Skill] 技能描述: {skill.description}")
                
                # 使用技能代码
                code = skill.code
                skill_used = skill
            else:
                logger.info("[Skill] 未找到匹配技能，将生成新代码")
        
        # Step 2: 如果没有匹配技能，调用 LLM 生成代码
        if code is None:
            logger.info("\n[LLM] Plan - 生成执行脚本...")
            code = self._call_llm(user_instruction)
            
            if code is None:
                logger.error("[LLM] 代码生成失败")
                return {
                    'success': False,
                    'error': 'LLM 代码生成失败',
                    'code': None,
                    'skill_used': None
                }
        
        logger.info("\n[Code] 执行代码:")
        logger.info("-" * 60)
        for i, line in enumerate(code.split('\n'), 1):
            logger.info(f"  {i:2d} | {line}")
        logger.info("-" * 60)
        
        # Step 3: 执行代码
        logger.info("\n[Runtime] Execute - 开始执行...")
        result = self.runtime.execute(code)
        
        # Step 4: 蒸馏保存技能 (仅对新生成的代码)
        if self.enable_skills and skill_used is None:
            self._distill_and_save_skill(
                instruction=user_instruction,
                code=code,
                execution_log=result.get('log', []),
                success=result['success']
            )
        
        # Step 5: 更新技能使用统计 (如果使用了技能)
        if skill_used and self.skill_manager:
            self.skill_manager.record_usage(skill_used.id, result['success'])
        
        # Step 6: 输出结果
        logger.info("\n" + "=" * 80)
        if result['success']:
            logger.info(f"[SemanticAgent] 任务完成!")
            logger.info(f"  - 执行步骤: {result['steps']}")
            logger.info(f"  - 重试次数: {result['retries']}")
            if skill_used:
                logger.info(f"  - 使用技能: {skill_used.name}")
        else:
            logger.error(f"[SemanticAgent] 任务失败: {result['error']}")
            logger.error(f"  - 已执行步骤: {result['steps']}")
            logger.error(f"  - 重试次数: {result['retries']}")
        logger.info("=" * 80)
        
        return {
            'success': result['success'],
            'error': result.get('error'),
            'code': code,
            'steps': result['steps'],
            'retries': result['retries'],
            'log': result['log'],
            'skill_used': skill_used.name if skill_used else None
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
    print("Semantic Agent - 三层架构手机控制系统 v3.1")
    print("=" * 80)
    print("\n架构:")
    print("  L1 策略层 (LLM)      -> 生成 Python 脚本")
    print("  L2 运行时 (Runtime)  -> 执行代码，提供 step()/ask()/checkpoint()")
    print("  L3 战术层 (AutoGLM)  -> 视觉定位 + 微观闭环")
    print("\n技能系统:")
    print("  - SkillRegistry      -> 技能存储与检索")
    print("  - SkillDistiller     -> 执行成功后自动蒸馏技能")
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
        tactical_model="autoglm-phone",
        enable_skills=True,
        skill_store_path="./skill_store"
    )
    
    # 显示已有技能
    if agent.skill_registry:
        skills = agent.skill_registry.list_all()
        if skills:
            print(f"\n已加载 {len(skills)} 个技能:")
            for s in skills[:5]:
                print(f"  - {s.name}: {s.description[:40]}...")
            if len(skills) > 5:
                print(f"  ... 还有 {len(skills) - 5} 个技能")
    
    # 4. 交互循环
    print("\n" + "=" * 80)
    print("输入任务指令开始执行")
    print("命令: 'quit' 退出 | 'skills' 查看技能 | 'clear' 清空技能")
    print("=" * 80)
    
    while True:
        try:
            instruction = input("\n任务: ").strip()
            
            if not instruction:
                continue
            
            if instruction.lower() in ['quit', 'exit', 'q']:
                print("\n再见!")
                break
            
            if instruction.lower() == 'skills':
                # 显示所有技能
                if agent.skill_registry:
                    skills = agent.skill_registry.list_all()
                    if skills:
                        print(f"\n已保存 {len(skills)} 个技能:")
                        for s in skills:
                            print(f"  [{s.id}] {s.name}")
                            print(f"       描述: {s.description}")
                            print(f"       使用: {s.usage_count}次, 成功率: {s.success_rate:.0%}")
                    else:
                        print("\n暂无保存的技能")
                continue
            
            if instruction.lower() == 'clear':
                # 清空技能
                if agent.skill_registry:
                    for skill in list(agent.skill_registry.skills.values()):
                        agent.skill_registry.delete(skill.id)
                    print("\n已清空所有技能")
                continue
            
            # 执行任务
            result = agent.execute_task(instruction)
            
            # 显示摘要
            print("\n执行摘要:")
            print(f"  - 状态: {'成功' if result['success'] else '失败'}")
            if not result['success']:
                print(f"  - 错误: {result['error']}")
            print(f"  - 步骤: {result['steps']}")
            print(f"  - 重试: {result['retries']}")
            if result.get('skill_used'):
                print(f"  - 使用技能: {result['skill_used']}")
            
        except KeyboardInterrupt:
            print("\n\n中断，再见!")
            break
        except Exception as e:
            logger.error(f"错误: {e}")
            import traceback
            traceback.print_exc()
            continue


def demo():
    """演示模式"""
    print("=" * 80)
    print("Semantic Agent 演示模式 (含技能系统)")
    print("=" * 80)
    
    from drivers.mock_driver import MockDriver
    
    driver = MockDriver()
    agent = SemanticAgent(
        zhipuai_api_key="demo",
        driver=driver,
        enable_skills=True,
        skill_store_path="./demo_skill_store"
    )
    
    # 测试任务
    test_tasks = [
        "打开微信，给张三发消息'晚上吃饭'",
        "清空购物车里所有商品",
        "给前 3 个视频点赞",
    ]
    
    for task in test_tasks:
        print(f"\n\n{'='*80}")
        print(f"测试任务: {task}")
        print('='*80)
        
        result = agent.execute_task(task)
        
        print(f"\n结果: {'成功' if result['success'] else '失败'}")
        print(f"步骤: {result['steps']}, 重试: {result['retries']}")
        if result.get('skill_used'):
            print(f"使用技能: {result['skill_used']}")
        
        input("\n按回车继续...")
    
    # 显示蒸馏的技能
    print("\n\n" + "=" * 80)
    print("蒸馏的技能:")
    print("=" * 80)
    
    if agent.skill_registry:
        for skill in agent.skill_registry.list_all():
            print(f"\n[{skill.id}] {skill.name}")
            print(f"  描述: {skill.description}")
            print(f"  代码:\n{skill.code}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Semantic Agent - 三层架构手机控制 v3.1')
    parser.add_argument('--demo', action='store_true', help='运行演示')
    parser.add_argument('--no-skills', action='store_true', help='禁用技能系统')
    parser.add_argument('--skill-store', type=str, default='./skill_store', help='技能存储路径')
    
    args = parser.parse_args()
    
    if args.demo:
        demo()
    else:
        main()
