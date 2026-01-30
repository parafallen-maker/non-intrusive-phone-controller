"""Action translator: AutoGLM actions -> S3 commands"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from models import (
    AutoGLMAction, ExecutionPlan, ExecutionStep, 
    S3Command
)


logger = logging.getLogger(__name__)


class ActionTranslator:
    """Translate AutoGLM actions to S3 commands"""
    
    def __init__(self):
        """Initialize translator"""
        self.action_handlers = {
            'Tap': self._handle_tap,
            'Swipe': self._handle_swipe,
            'Type': self._handle_type,
            'Back': self._handle_back,
            'Home': self._handle_home,
            'Long Press': self._handle_long_press,
            'Longpress': self._handle_long_press,
            'Double Tap': self._handle_double_tap,
            'Doubletap': self._handle_double_tap,
            'Wait': self._handle_wait,
            'Take_over': self._handle_takeover,
        }
    
    def create_execution_plan(
        self, 
        device_ip: str,
        instruction: str, 
        actions: List[AutoGLMAction]
    ) -> ExecutionPlan:
        """Create execution plan from AutoGLM actions
        
        Args:
            device_ip: Target device IP
            instruction: Original instruction
            actions: List of AutoGLM actions
            
        Returns:
            Execution plan with translated steps
        """
        plan_id = str(uuid.uuid4())
        steps = []
        
        for idx, action in enumerate(actions):
            step = self._translate_action(idx + 1, action)
            steps.append(step)
        
        return ExecutionPlan(
            plan_id=plan_id,
            device_ip=device_ip,
            instruction=instruction,
            steps=steps,
            created_at=datetime.now()
        )
    
    def _translate_action(self, step_id: int, action: AutoGLMAction) -> ExecutionStep:
        """Translate single action to execution step
        
        Args:
            step_id: Step ID
            action: AutoGLM action
            
        Returns:
            Execution step
        """
        action_type = action.action.title()
        handler = self.action_handlers.get(action_type)
        
        if not handler:
            logger.warning(f"Unknown action type: {action_type}")
            return ExecutionStep(
                step_id=step_id,
                action="unknown",
                params={'original': action.model_dump()},
                status="pending"
            )
        
        try:
            translated = handler(action.params or {})
            return ExecutionStep(
                step_id=step_id,
                action=translated['action'],
                params=translated['params'],
                status="pending"
            )
        except Exception as e:
            logger.error(f"Failed to translate action {action_type}: {e}")
            return ExecutionStep(
                step_id=step_id,
                action="error",
                params={'error': str(e)},
                status="failed",
                error=str(e)
            )
    
    def _handle_tap(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Tap action
        
        Args:
            params: {'x': float, 'y': float}
            
        Returns:
            S3 command params
        """
        x = params.get('x', 0.5)
        y = params.get('y', 0.5)
        
        # Validate coordinates
        x = max(0.0, min(1.0, float(x)))
        y = max(0.0, min(1.0, float(y)))
        
        return {
            'action': 's3_move_click',
            'params': {
                'x': x,
                'y': y,
                'click_count': 1,
                'delay_ms': 0
            }
        }
    
    def _handle_swipe(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Swipe action
        
        Args:
            params: {'start_x': float, 'start_y': float, 'end_x': float, 'end_y': float}
            
        Returns:
            S3 command params
        """
        start_x = max(0.0, min(1.0, float(params.get('start_x', 0.5))))
        start_y = max(0.0, min(1.0, float(params.get('start_y', 0.5))))
        end_x = max(0.0, min(1.0, float(params.get('end_x', 0.5))))
        end_y = max(0.0, min(1.0, float(params.get('end_y', 0.5))))
        
        return {
            'action': 's3_drag',
            'params': {
                'start_x': start_x,
                'start_y': start_y,
                'end_x': end_x,
                'end_y': end_y
            }
        }
    
    def _handle_type(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Type action
        
        通过语音输入实现文字输入:
        1. 点击语音输入按钮
        2. TTS 播放文字
        3. 手机 STT 识别
        
        Args:
            params: {'text': str}
            
        Returns:
            Voice input action params
        """
        text = params.get('text', '')
        
        return {
            'action': 'voice_type',
            'params': {
                'text': text,
                'method': 'tts_stt',  # TTS播放 + STT识别
                'note': '使用语音输入: 点击麦克风 → TTS播放 → 等待识别'
            }
        }
    
    def _handle_back(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Back action
        
        Note: Requires Android system back gesture (swipe from left edge)
        
        Args:
            params: Empty dict
            
        Returns:
            S3 command params for back gesture
        """
        return {
            'action': 's3_drag',
            'params': {
                'start_x': 0.01,
                'start_y': 0.5,
                'end_x': 0.3,
                'end_y': 0.5
            }
        }
    
    def _handle_home(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Home action
        
        Note: Requires Android home gesture (swipe up from bottom)
        
        Args:
            params: Empty dict
            
        Returns:
            S3 command params for home gesture
        """
        return {
            'action': 's3_drag',
            'params': {
                'start_x': 0.5,
                'start_y': 0.98,
                'end_x': 0.5,
                'end_y': 0.5
            }
        }
    
    def _handle_long_press(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Long Press action
        
        Args:
            params: {'x': float, 'y': float, 'duration': float}
            
        Returns:
            S3 command params
        """
        x = max(0.0, min(1.0, float(params.get('x', 0.5))))
        y = max(0.0, min(1.0, float(params.get('y', 0.5))))
        duration = int(params.get('duration', 1.0) * 1000)  # Convert to ms
        
        return {
            'action': 's3_move_click',
            'params': {
                'x': x,
                'y': y,
                'click_count': 1,
                'delay_ms': duration
            }
        }
    
    def _handle_double_tap(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Double Tap action
        
        Args:
            params: {'x': float, 'y': float}
            
        Returns:
            S3 command params
        """
        x = max(0.0, min(1.0, float(params.get('x', 0.5))))
        y = max(0.0, min(1.0, float(params.get('y', 0.5))))
        
        return {
            'action': 's3_move_click',
            'params': {
                'x': x,
                'y': y,
                'click_count': 2,
                'delay_ms': 0
            }
        }
    
    def _handle_wait(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Wait action
        
        Args:
            params: {'duration': float}
            
        Returns:
            Wait command params
        """
        duration = float(params.get('duration', 1.0))
        
        return {
            'action': 'wait',
            'params': {
                'duration': duration
            }
        }
    
    def _handle_takeover(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Take_over action (manual intervention)
        
        Args:
            params: Optional dict with reason
            
        Returns:
            Manual intervention params
        """
        reason = params.get('reason', 'Manual intervention required (e.g., login, captcha)')
        
        return {
            'action': 'manual_intervention',
            'params': {
                'reason': reason,
                'note': 'Execution paused. Please complete the action manually and resume.'
            }
        }
