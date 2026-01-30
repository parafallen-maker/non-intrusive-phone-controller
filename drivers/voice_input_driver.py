#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Voice Input Driver - 通过 TTS + 语音输入法实现非接触式文字输入

核心流程:
1. 点击输入框激活键盘
2. 点击语音输入按钮
3. 等待语音输入激活
4. TTS 播放文字
5. 等待识别完成
6. 验证输入结果

依赖:
- AutoGLMDriver: 提供 ask(), checkpoint(), execute_step()
- TTSEngine: 提供 speak() 播放文字
"""

import re
import time
import logging
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from difflib import SequenceMatcher

if TYPE_CHECKING:
    from tactical.autoglm_driver import AutoGLMDriver

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class VoiceInputResult:
    """语音输入结果"""
    success: bool
    input_text: str          # 期望输入的文字
    recognized_text: str     # 实际识别的文字
    attempts: int            # 尝试次数
    error: Optional[str] = None


@dataclass
class InputConfig:
    """输入配置"""
    tts_rate: int = 150           # TTS 语速
    tts_volume: float = 0.9       # TTS 音量 (0.0 - 1.0)
    listen_wait: float = 2.0      # 等待语音激活的时间(秒)
    recognition_wait: float = 2.0  # 识别后等待时间(秒)
    char_delay: float = 0.1       # 每字符额外等待时间
    max_retries: int = 3          # 最大重试次数
    similarity_threshold: float = 0.80  # 相似度阈值


# ============================================================
# TTS 引擎
# ============================================================

class TTSEngine:
    """TTS 引擎基类"""
    
    def speak(self, text: str, rate: int = 150, volume: float = 0.9) -> None:
        raise NotImplementedError
    
    def get_duration(self, text: str, rate: int = 150) -> float:
        """估算播放时长(秒)"""
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        chinese_time = chinese_chars / (rate / 60)
        other_time = (other_chars / 5) / (rate / 60)
        return chinese_time + other_time + 0.5


class PyTTSEngine(TTSEngine):
    """使用 pyttsx3 的 TTS 引擎"""
    
    def __init__(self):
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self._available = True
            logger.info("[PyTTS] 初始化成功")
        except ImportError:
            logger.warning("[PyTTS] pyttsx3 未安装，使用 Mock 模式")
            self._available = False
    
    def speak(self, text: str, rate: int = 150, volume: float = 0.9) -> None:
        logger.info(f"[TTS] 播放: '{text}'")
        
        if not self._available:
            time.sleep(self.get_duration(text, rate))
            return
        
        self.engine.setProperty('rate', rate)
        self.engine.setProperty('volume', volume)
        self.engine.say(text)
        self.engine.runAndWait()


class MockTTSEngine(TTSEngine):
    """Mock TTS 引擎 (用于测试)"""
    
    def __init__(self):
        self.spoken_texts = []
    
    def speak(self, text: str, rate: int = 150, volume: float = 0.9) -> None:
        logger.info(f"[MockTTS] 播放: '{text}'")
        self.spoken_texts.append(text)
        time.sleep(self.get_duration(text, rate))


# ============================================================
# AutoGLM 视觉适配器
# ============================================================

class AutoGLMVisionAdapter:
    """使用 AutoGLM 作为视觉后端
    
    封装 AutoGLMDriver 的 ask/checkpoint 方法，提供:
    - find_element(): 查找元素位置
    - check_state(): 检测界面状态
    - read_text(): 读取屏幕文字
    """
    
    def __init__(self, autoglm_driver: 'AutoGLMDriver'):
        self.driver = autoglm_driver
    
    def find_element(self, description: str) -> Optional[tuple]:
        """查找元素位置
        
        Args:
            description: 元素描述（如"麦克风图标"）
            
        Returns:
            (x, y): 归一化坐标，如 (0.85, 0.92)
        """
        answer = self.driver.ask(
            f"请找到'{description}'在屏幕上的位置，"
            f"返回其中心点的归一化坐标，格式为 (x, y)，"
            f"x 和 y 的范围是 0.0 到 1.0。只返回坐标，如 (0.85, 0.92)"
        )
        
        # 解析坐标
        match = re.search(r'\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)', answer)
        if match:
            x, y = float(match.group(1)), float(match.group(2))
            if 0 <= x <= 1 and 0 <= y <= 1:
                logger.info(f"[Vision] 找到 '{description}' 位置: ({x}, {y})")
                return (x, y)
        
        logger.warning(f"[Vision] 未找到 '{description}'，响应: {answer}")
        return None
    
    def check_state(self, state_description: str) -> bool:
        """检测界面状态
        
        Args:
            state_description: 状态描述（如"正在聆听"）
            
        Returns:
            bool: 当前界面是否符合描述
        """
        result = self.driver.checkpoint(state_description)
        logger.info(f"[Vision] 检查状态 '{state_description}': {result}")
        return result
    
    def read_text(self, region: str = "input_field") -> str:
        """读取屏幕文字
        
        Args:
            region: 区域类型 ("input_field", "recognition_result", "full_screen")
            
        Returns:
            识别到的文字
        """
        prompts = {
            "input_field": "输入框中显示的文字内容是什么？只返回文字本身，不要其他解释",
            "recognition_result": "屏幕上显示的语音识别结果是什么？只返回识别出的文字",
            "keyboard_visible": "键盘是否已弹出？回答是或否",
        }
        
        prompt = prompts.get(region, f"屏幕上{region}区域的文字是什么？只返回文字")
        answer = self.driver.ask(prompt)
        
        logger.info(f"[Vision] 读取 '{region}': {answer}")
        return answer.strip()


# ============================================================
# 核心类: VoiceInputDriver
# ============================================================

class VoiceInputDriver:
    """语音输入驱动 - 通过 TTS + 语音输入法实现文字输入
    
    使用 AutoGLM 进行:
    - 定位麦克风图标
    - 检测"正在聆听"状态
    - 读取/验证输入结果
    
    使用示例:
        driver = VoiceInputDriver(autoglm_driver, tts_engine)
        result = driver.type_text("北京天气")
        if result.success:
            print(f"输入成功: {result.recognized_text}")
    """
    
    def __init__(
        self,
        autoglm_driver: 'AutoGLMDriver',
        tts_engine: TTSEngine = None,
        config: InputConfig = None
    ):
        self.autoglm = autoglm_driver
        self.vision = AutoGLMVisionAdapter(autoglm_driver)
        self.tts = tts_engine or PyTTSEngine()
        self.config = config or InputConfig()
    
    # ========== 主入口 ==========
    
    def type_text(self, text: str) -> VoiceInputResult:
        """通过语音输入文字
        
        Args:
            text: 要输入的文字
            
        Returns:
            VoiceInputResult: 输入结果
        """
        logger.info(f"[VoiceInput] 开始输入: '{text}'")
        
        for attempt in range(1, self.config.max_retries + 1):
            logger.info(f"[VoiceInput] 第 {attempt} 次尝试")
            
            try:
                # Step 1: 点击语音按钮
                if not self._tap_voice_button():
                    continue
                
                # Step 2: 等待聆听状态
                if not self._wait_for_listening():
                    continue
                
                # Step 3: TTS 播放文字
                self._speak_text(text)
                
                # Step 4: 等待识别完成
                self._wait_for_recognition(text)
                
                # Step 5: 验证输入结果
                recognized = self._verify_input(text)
                
                if recognized is not None:
                    logger.info(f"[VoiceInput] ✅ 输入成功!")
                    return VoiceInputResult(
                        success=True,
                        input_text=text,
                        recognized_text=recognized,
                        attempts=attempt
                    )
                
                # 识别失败，清空重试
                logger.warning(f"[VoiceInput] 验证失败，准备重试")
                self._clear_input()
                
            except Exception as e:
                logger.error(f"[VoiceInput] 尝试 {attempt} 异常: {e}")
        
        logger.error(f"[VoiceInput] ❌ 输入失败，已尝试 {self.config.max_retries} 次")
        return VoiceInputResult(
            success=False,
            input_text=text,
            recognized_text="",
            attempts=self.config.max_retries,
            error="达到最大重试次数"
        )
    
    # ========== Step 1: 点击语音按钮 ==========
    
    def _tap_voice_button(self) -> bool:
        """点击语音输入按钮"""
        logger.info("[VoiceInput] Step 1: 点击语音按钮")
        
        # 使用 AutoGLM execute_step 直接执行
        result = self.autoglm.execute_step(
            goal="点击键盘上的语音输入按钮或麦克风图标",
            expect="进入语音输入状态，显示正在聆听的界面"
        )
        
        if result.success:
            logger.info("[VoiceInput] 语音按钮点击成功")
            return True
        
        # 备选：手动查找并点击
        logger.warning("[VoiceInput] execute_step 失败，尝试手动定位")
        
        for desc in ["语音输入按钮", "麦克风图标", "🎤", "voice button"]:
            pos = self.vision.find_element(desc)
            if pos:
                self.autoglm.driver.tap(pos[0], pos[1])
                time.sleep(0.5)
                return True
        
        logger.error("[VoiceInput] 未找到语音输入按钮")
        return False
    
    # ========== Step 2: 等待聆听状态 ==========
    
    def _wait_for_listening(self) -> bool:
        """等待进入聆听状态"""
        logger.info("[VoiceInput] Step 2: 等待聆听状态")
        
        timeout = self.config.listen_wait + 2.0
        start = time.time()
        
        while time.time() - start < timeout:
            # 检查多种可能的状态描述
            if self.vision.check_state("正在聆听语音") or \
               self.vision.check_state("显示麦克风波形或正在录音") or \
               self.vision.check_state("请说话"):
                logger.info("[VoiceInput] ✅ 进入聆听状态")
                time.sleep(0.3)  # 短暂稳定
                return True
            
            time.sleep(0.3)
        
        logger.warning("[VoiceInput] 等待聆听状态超时")
        return False
    
    # ========== Step 3: TTS 播放 ==========
    
    def _speak_text(self, text: str) -> None:
        """通过 TTS 播放文字"""
        logger.info(f"[VoiceInput] Step 3: TTS 播放 '{text}'")
        
        self.tts.speak(
            text,
            rate=self.config.tts_rate,
            volume=self.config.tts_volume
        )
        
        logger.info("[VoiceInput] TTS 播放完成")
    
    # ========== Step 4: 等待识别 ==========
    
    def _wait_for_recognition(self, text: str) -> None:
        """等待语音识别完成"""
        # 基础等待 + 按字符数增加
        base_wait = self.config.recognition_wait
        char_wait = len(text) * self.config.char_delay
        total_wait = base_wait + char_wait
        
        logger.info(f"[VoiceInput] Step 4: 等待识别完成 ({total_wait:.1f}s)")
        time.sleep(total_wait)
    
    # ========== Step 5: 验证结果 ==========
    
    def _verify_input(self, expected_text: str) -> Optional[str]:
        """验证输入结果"""
        logger.info("[VoiceInput] Step 5: 验证输入结果")
        
        # 读取输入框内容
        actual_text = self.vision.read_text("input_field")
        
        if not actual_text or actual_text in ["无", "空", "没有", "error"]:
            logger.warning("[VoiceInput] 无法读取输入框内容")
            return None
        
        # 计算相似度
        similarity = self._calculate_similarity(expected_text, actual_text)
        logger.info(
            f"[VoiceInput] 验证: 期望='{expected_text}', "
            f"实际='{actual_text}', 相似度={similarity:.1%}"
        )
        
        if similarity >= self.config.similarity_threshold:
            return actual_text
        
        logger.warning(
            f"[VoiceInput] 相似度不足: {similarity:.1%} < {self.config.similarity_threshold:.1%}"
        )
        return None
    
    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """计算两个字符串的相似度"""
        # 预处理：去除空格和标点
        clean = lambda s: re.sub(r'[\s\.,;:!?，。；：！？、]', '', s)
        c1, c2 = clean(s1), clean(s2)
        
        if not c1 or not c2:
            return 0.0
        
        return SequenceMatcher(None, c1, c2).ratio()
    
    # ========== 辅助方法 ==========
    
    def _clear_input(self) -> None:
        """清空输入框"""
        logger.info("[VoiceInput] 清空输入框")
        
        # 使用 AutoGLM 执行清空操作
        self.autoglm.execute_step(
            goal="清空输入框内容",
            expect="输入框为空"
        )


# ============================================================
# 工厂函数
# ============================================================

def create_voice_input_driver(
    autoglm_driver: 'AutoGLMDriver',
    use_mock_tts: bool = False,
    config: InputConfig = None
) -> VoiceInputDriver:
    """创建语音输入驱动
    
    Args:
        autoglm_driver: AutoGLM 驱动实例
        use_mock_tts: 是否使用 Mock TTS
        config: 输入配置
    """
    tts = MockTTSEngine() if use_mock_tts else PyTTSEngine()
    return VoiceInputDriver(autoglm_driver, tts, config)


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    print("=" * 60)
    print("VoiceInputDriver 模块加载成功")
    print("=" * 60)
    print("\n使用示例:")
    print("""
    from tactical.autoglm_driver import create_autoglm_driver
    from drivers.voice_input_driver import create_voice_input_driver
    
    # 初始化
    autoglm = create_autoglm_driver(api_key="your_key")
    voice_driver = create_voice_input_driver(autoglm)
    
    # 输入文字
    result = voice_driver.type_text("北京天气")
    print(f"成功: {result.success}, 识别: {result.recognized_text}")
    """)
