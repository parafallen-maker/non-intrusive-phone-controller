#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
模型接口测试脚本
检查 LLM 和 Vision 模型调用是否正常
"""

import os
import sys
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_dependencies():
    """检查依赖包"""
    print("\n" + "=" * 50)
    print("1. 检查依赖包")
    print("=" * 50)
    
    deps = {
        'zhipuai': False,
        'openai': False,
        'anthropic': False,
        'httpx': False,
        'pydantic': False,
    }
    
    for pkg in deps:
        try:
            __import__(pkg)
            deps[pkg] = True
            print(f"  ✅ {pkg} 已安装")
        except ImportError:
            print(f"  ❌ {pkg} 未安装")
    
    return deps


def check_env_variables():
    """检查环境变量"""
    print("\n" + "=" * 50)
    print("2. 检查环境变量 / API Keys")
    print("=" * 50)
    
    env_vars = {
        'ZHIPUAI_API_KEY': os.environ.get('ZHIPUAI_API_KEY', ''),
        'OPENAI_API_KEY': os.environ.get('OPENAI_API_KEY', ''),
        'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY', ''),
    }
    
    # 尝试从 .env 文件读取
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        print(f"  📄 发现 .env 文件: {env_file}")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"\'')
                    if key in env_vars and not env_vars[key]:
                        env_vars[key] = value
    
    results = {}
    for key, value in env_vars.items():
        if value:
            masked = value[:8] + '...' + value[-4:] if len(value) > 16 else '***'
            print(f"  ✅ {key}: {masked}")
            results[key] = value
        else:
            print(f"  ⚠️  {key}: 未设置")
            results[key] = None
    
    return results


def test_zhipu_api(api_key: str):
    """测试智谱 AI API"""
    print("\n" + "=" * 50)
    print("3. 测试智谱 AI (ZhipuAI) API")
    print("=" * 50)
    
    if not api_key:
        print("  ⚠️  跳过: ZHIPUAI_API_KEY 未设置")
        return False
    
    try:
        from zhipuai import ZhipuAI
        client = ZhipuAI(api_key=api_key)
        
        # 测试 GLM-4 文本生成
        print("  🔄 测试 glm-4-flash 模型...")
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {"role": "user", "content": "说'测试成功'两个字"}
            ],
            max_tokens=50
        )
        
        result = response.choices[0].message.content
        print(f"  ✅ glm-4-flash 响应: {result[:50]}...")
        
        # 测试视觉模型
        print("  🔄 测试 glm-4v-flash 视觉模型...")
        response = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这是什么?请简短回答"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "https://img.qichacha.com/Product/ee16ca7e-f20e-436a-acfe-e0f59e4535c7.jpg"
                            }
                        }
                    ]
                }
            ],
            max_tokens=100
        )
        result = response.choices[0].message.content
        print(f"  ✅ glm-4v-flash 响应: {result[:50]}...")
        
        return True
        
    except Exception as e:
        print(f"  ❌ 智谱 API 错误: {e}")
        return False


def test_openai_api(api_key: str):
    """测试 OpenAI API"""
    print("\n" + "=" * 50)
    print("4. 测试 OpenAI API")
    print("=" * 50)
    
    if not api_key:
        print("  ⚠️  跳过: OPENAI_API_KEY 未设置")
        return False
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        print("  🔄 测试 gpt-4o-mini 模型...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": "Say 'test successful' in Chinese, just 2 words"}
            ],
            max_tokens=50
        )
        
        result = response.choices[0].message.content
        print(f"  ✅ gpt-4o-mini 响应: {result[:50]}...")
        return True
        
    except Exception as e:
        print(f"  ❌ OpenAI API 错误: {e}")
        return False


def test_anthropic_api(api_key: str):
    """测试 Anthropic API"""
    print("\n" + "=" * 50)
    print("5. 测试 Anthropic (Claude) API")
    print("=" * 50)
    
    if not api_key:
        print("  ⚠️  跳过: ANTHROPIC_API_KEY 未设置")
        return False
    
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        
        print("  🔄 测试 claude-3-5-sonnet 模型...")
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=50,
            messages=[
                {"role": "user", "content": "Say 'test successful' in Chinese, just 2 words"}
            ]
        )
        
        result = response.content[0].text
        print(f"  ✅ claude-3-5-sonnet 响应: {result[:50]}...")
        return True
        
    except Exception as e:
        print(f"  ❌ Anthropic API 错误: {e}")
        return False


def test_planner_mock():
    """测试 Planner Mock 模式"""
    print("\n" + "=" * 50)
    print("6. 测试 Planner (Mock 模式)")
    print("=" * 50)
    
    try:
        from runtime.planner import Planner
        
        planner = Planner(provider='mock')
        
        test_instructions = [
            "给微信朋友圈前3条点赞",
            "打开计算器",
        ]
        
        for instruction in test_instructions:
            result = planner.plan(instruction)
            if result.success:
                print(f"  ✅ '{instruction[:15]}...' -> 生成 {len(result.code)} 字符代码")
            else:
                print(f"  ❌ '{instruction}' 失败: {result.error}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Planner 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_planner_real(api_key: str, provider: str):
    """测试 Planner 真实调用"""
    print("\n" + "=" * 50)
    print(f"7. 测试 Planner (真实调用 - {provider})")
    print("=" * 50)
    
    if not api_key:
        print(f"  ⚠️  跳过: {provider.upper()}_API_KEY 未设置")
        return False
    
    try:
        from runtime.planner import Planner
        
        planner = Planner(api_key=api_key, provider=provider)
        
        instruction = "打开微信"
        print(f"  🔄 测试指令: '{instruction}'")
        
        result = planner.plan(instruction)
        
        if result.success:
            print(f"  ✅ 成功! 生成代码:")
            for line in result.code.split('\n')[:5]:
                print(f"      {line}")
            if result.code.count('\n') > 5:
                print(f"      ... (共 {result.code.count(chr(10)) + 1} 行)")
            return True
        else:
            print(f"  ❌ 失败: {result.error}")
            return False
        
    except Exception as e:
        print(f"  ❌ Planner 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试流程"""
    print("=" * 50)
    print("       模型接口测试")
    print("=" * 50)
    
    # 1. 检查依赖
    deps = check_dependencies()
    
    # 2. 检查环境变量
    env_vars = check_env_variables()
    
    # 3. 测试智谱 API
    zhipu_ok = False
    if deps.get('zhipuai'):
        zhipu_ok = test_zhipu_api(env_vars.get('ZHIPUAI_API_KEY'))
    
    # 4. 测试 OpenAI API
    openai_ok = False
    if deps.get('openai'):
        openai_ok = test_openai_api(env_vars.get('OPENAI_API_KEY'))
    
    # 5. 测试 Anthropic API
    anthropic_ok = False
    if deps.get('anthropic'):
        anthropic_ok = test_anthropic_api(env_vars.get('ANTHROPIC_API_KEY'))
    
    # 6. 测试 Planner Mock
    mock_ok = test_planner_mock()
    
    # 7. 测试 Planner 真实调用
    real_ok = False
    if zhipu_ok:
        real_ok = test_planner_real(env_vars.get('ZHIPUAI_API_KEY'), 'zhipu')
    elif openai_ok:
        real_ok = test_planner_real(env_vars.get('OPENAI_API_KEY'), 'openai')
    
    # 汇总
    print("\n" + "=" * 50)
    print("       测试结果汇总")
    print("=" * 50)
    
    results = [
        ("智谱 AI API", zhipu_ok),
        ("OpenAI API", openai_ok),
        ("Anthropic API", anthropic_ok),
        ("Planner Mock", mock_ok),
        ("Planner 真实调用", real_ok),
    ]
    
    for name, ok in results:
        status = "✅ 通过" if ok else "❌ 未通过/跳过"
        print(f"  {name}: {status}")
    
    passed = sum(1 for _, ok in results if ok)
    print(f"\n  总计: {passed}/{len(results)} 通过")
    
    if passed >= 2:  # Mock + 至少一个真实 API
        print("\n🎉 模型接口基本正常!")
    else:
        print("\n⚠️  建议配置至少一个 API Key")
        print("   在 .env 文件中设置 ZHIPUAI_API_KEY 或 OPENAI_API_KEY")


if __name__ == '__main__':
    main()
