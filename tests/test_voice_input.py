#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Voice Input Driver - 测试语音输入驱动
"""

import os
import sys
import time
import logging

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_tts_engine():
    """测试 TTS 引擎"""
    print("=" * 60)
    print("测试 TTS 引擎")
    print("=" * 60)
    
    from drivers.voice_input_driver import MockTTSEngine, PyTTSEngine
    
    # Mock TTS
    mock_tts = MockTTSEngine()
    mock_tts.speak("测试文本", rate=150)
    assert len(mock_tts.spoken_texts) == 1
    print("✅ MockTTSEngine 测试通过")
    
    # 估算时长
    duration = mock_tts.get_duration("北京天气", rate=150)
    assert duration > 0
    print(f"✅ 时长估算: '北京天气' = {duration:.2f}s")


def test_vision_adapter():
    """测试 AutoGLM 视觉适配器"""
    print("\n" + "=" * 60)
    print("测试 AutoGLMVisionAdapter")
    print("=" * 60)
    
    from drivers.voice_input_driver import AutoGLMVisionAdapter
    
    # Mock AutoGLM Driver
    class MockAutoGLMDriver:
        def ask(self, question):
            if "位置" in question or "坐标" in question:
                return "(0.85, 0.92)"
            if "文字" in question or "内容" in question:
                return "北京天气"
            return "未知"
        
        def checkpoint(self, description):
            if "聆听" in description or "录音" in description:
                return True
            return False
    
    adapter = AutoGLMVisionAdapter(MockAutoGLMDriver())
    
    # 测试 find_element
    pos = adapter.find_element("麦克风图标")
    assert pos == (0.85, 0.92), f"Expected (0.85, 0.92), got {pos}"
    print("✅ find_element 测试通过")
    
    # 测试 check_state
    result = adapter.check_state("正在聆听语音")
    assert result == True
    print("✅ check_state 测试通过")
    
    # 测试 read_text
    text = adapter.read_text("input_field")
    assert text == "北京天气"
    print("✅ read_text 测试通过")


def test_voice_input_driver_mock():
    """测试 VoiceInputDriver (Mock 模式)"""
    print("\n" + "=" * 60)
    print("测试 VoiceInputDriver (Mock 模式)")
    print("=" * 60)
    
    from drivers.voice_input_driver import VoiceInputDriver, MockTTSEngine, InputConfig
    from drivers.mock_driver import MockDriver
    
    # 完整的 Mock AutoGLM Driver
    class MockAutoGLMDriver:
        def __init__(self):
            self.driver = MockDriver()
            self._step = 0
        
        def execute_step(self, goal, expect=None):
            from tactical.autoglm_driver import StepResult
            self._step += 1
            print(f"  [MockAutoGLM] execute_step: {goal}")
            return StepResult(success=True, state="操作完成")
        
        def ask(self, question):
            print(f"  [MockAutoGLM] ask: {question}")
            if "位置" in question or "坐标" in question:
                return "(0.90, 0.95)"
            if "文字" in question or "内容" in question:
                return "北京天气"  # 返回与输入匹配的文字
            return "正常"
        
        def checkpoint(self, description):
            print(f"  [MockAutoGLM] checkpoint: {description}")
            # 第一次检查返回 True (进入聆听状态)
            return True
    
    # 配置
    config = InputConfig(
        max_retries=2,
        listen_wait=0.5,
        recognition_wait=0.5,
        similarity_threshold=0.8
    )
    
    # 初始化
    autoglm = MockAutoGLMDriver()
    tts = MockTTSEngine()
    driver = VoiceInputDriver(autoglm, tts, config)
    
    # 测试输入
    print("\n开始语音输入测试...")
    result = driver.type_text("北京天气")
    
    print(f"\n结果:")
    print(f"  成功: {result.success}")
    print(f"  期望: {result.input_text}")
    print(f"  识别: {result.recognized_text}")
    print(f"  尝试: {result.attempts}")
    
    assert result.success, "语音输入应该成功"
    assert result.recognized_text == "北京天气"
    print("✅ VoiceInputDriver Mock 测试通过")


def test_similarity():
    """测试相似度计算"""
    print("\n" + "=" * 60)
    print("测试相似度计算")
    print("=" * 60)
    
    from drivers.voice_input_driver import VoiceInputDriver
    
    # 使用静态方法测试
    calc = VoiceInputDriver._calculate_similarity
    
    # 完全匹配
    s1 = calc(None, "北京天气", "北京天气")
    assert s1 == 1.0, f"完全匹配应为 1.0, got {s1}"
    print(f"✅ '北京天气' vs '北京天气' = {s1:.1%}")
    
    # 忽略标点
    s2 = calc(None, "北京天气", "北京天气，")
    assert s2 == 1.0, f"忽略标点应为 1.0, got {s2}"
    print(f"✅ '北京天气' vs '北京天气，' = {s2:.1%}")
    
    # 部分匹配
    s3 = calc(None, "北京天气", "北京")
    assert 0.4 < s3 < 0.7, f"部分匹配应在 0.4-0.7, got {s3}"
    print(f"✅ '北京天气' vs '北京' = {s3:.1%}")
    
    # 同音字误差
    s4 = calc(None, "北京", "背景")
    print(f"✅ '北京' vs '背景' = {s4:.1%} (同音字误差)")


def test_all():
    """运行所有测试"""
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "=" * 60)
    print("开始测试 Voice Input Driver")
    print("=" * 60 + "\n")
    
    try:
        test_tts_engine()
        test_vision_adapter()
        test_similarity()
        test_voice_input_driver_mock()
        
        print("\n" + "=" * 60)
        print("✅ 所有 Voice Input Driver 测试通过!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_all()
