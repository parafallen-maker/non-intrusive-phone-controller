"""AutoGLM client for phone control"""
import logging
import base64
from typing import Optional, List, Dict, Any
from zhipuai import ZhipuAI

from models import AutoGLMRequest, AutoGLMResponse, AutoGLMAction
from config import settings


logger = logging.getLogger(__name__)


class AutoGLMClient:
    """AutoGLM API client"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize AutoGLM client
        
        Args:
            api_key: API key (defaults to settings)
        """
        self.api_key = api_key or settings.zhipuai_api_key
        if not self.api_key:
            raise ValueError("AutoGLM API key not provided")
        
        self.client = ZhipuAI(api_key=self.api_key)
        self.model = settings.zhipuai_model
        
    def infer(self, request: AutoGLMRequest, screenshot_path: Optional[str] = None) -> AutoGLMResponse:
        """Call AutoGLM inference
        
        Args:
            request: AutoGLM request
            screenshot_path: Path to screenshot image
            
        Returns:
            AutoGLM response with action plan
        """
        try:
            # Build messages
            messages = []
            
            # Add system prompt
            system_prompt = (
                "You are an AI assistant controlling an Android phone through a mechanical arm. "
                "Analyze the screen and provide step-by-step actions to complete the user's task. "
                "Available actions: Tap, Swipe, Type, Back, Home, Long Press, Double Tap, Wait, Take_over. "
                "For Tap and coordinate-based actions, use normalized coordinates (0.0-1.0). "
                "Respond with a structured action plan."
            )
            messages.append({"role": "system", "content": system_prompt})
            
            # Add screenshot if provided
            if request.include_screenshot and screenshot_path:
                try:
                    with open(screenshot_path, 'rb') as f:
                        image_data = base64.b64encode(f.read()).decode('utf-8')
                    
                    messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            },
                            {
                                "type": "text",
                                "text": f"Current screen shown above. Task: {request.instruction}"
                            }
                        ]
                    })
                except Exception as e:
                    logger.warning(f"Failed to load screenshot: {e}")
                    messages.append({
                        "role": "user",
                        "content": f"Task: {request.instruction}"
                    })
            else:
                messages.append({
                    "role": "user",
                    "content": f"Task: {request.instruction}"
                })
            
            # Call API
            logger.info(f"Calling AutoGLM with instruction: {request.instruction}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000
            )
            
            # Parse response
            raw_response = response.model_dump()
            content = response.choices[0].message.content
            
            logger.info(f"AutoGLM response: {content}")
            
            # Extract actions from response
            actions = self._parse_actions(content)
            
            return AutoGLMResponse(
                success=True,
                actions=actions,
                raw_response=raw_response,
                session_id=request.session_id
            )
            
        except Exception as e:
            logger.error(f"AutoGLM inference failed: {e}")
            return AutoGLMResponse(
                success=False,
                actions=[],
                raw_response={},
                error=str(e)
            )
    
    def _parse_actions(self, content: str) -> List[AutoGLMAction]:
        """Parse actions from AutoGLM response
        
        Args:
            content: Response content
            
        Returns:
            List of actions
        """
        actions = []
        
        # Simple parsing logic - will be enhanced based on actual AutoGLM response format
        # Expected format examples:
        # "1. Tap(0.5, 0.3) - Click on search icon"
        # "2. Type('美食') - Enter search query"
        # "3. Wait(2) - Wait for results"
        
        lines = content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Remove numbering
            if line[0].isdigit() and '.' in line[:5]:
                line = line.split('.', 1)[1].strip()
            
            # Parse action
            try:
                # Extract action type
                if '(' in line:
                    action_part = line.split('(')[0].strip()
                    params_part = line.split('(', 1)[1].split(')')[0]
                    reasoning = line.split(')', 1)[1].strip() if ')' in line and len(line.split(')', 1)) > 1 else None
                    if reasoning and reasoning.startswith('-'):
                        reasoning = reasoning[1:].strip()
                    
                    # Parse parameters
                    params = {}
                    if action_part.upper() == "TAP":
                        coords = [float(x.strip()) for x in params_part.split(',')]
                        params = {'x': coords[0], 'y': coords[1]}
                    elif action_part.upper() == "SWIPE":
                        coords = [float(x.strip()) for x in params_part.split(',')]
                        params = {'start_x': coords[0], 'start_y': coords[1], 
                                 'end_x': coords[2], 'end_y': coords[3]}
                    elif action_part.upper() == "TYPE":
                        params = {'text': params_part.strip('\'"')}
                    elif action_part.upper() == "WAIT":
                        params = {'duration': float(params_part)}
                    elif action_part.upper() == "LONG PRESS" or action_part.upper() == "LONGPRESS":
                        coords = [float(x.strip()) for x in params_part.split(',')]
                        params = {'x': coords[0], 'y': coords[1], 'duration': coords[2] if len(coords) > 2 else 1.0}
                    
                    actions.append(AutoGLMAction(
                        action=action_part.title(),
                        params=params,
                        reasoning=reasoning
                    ))
                else:
                    # Actions without parameters (Back, Home, etc.)
                    action_text = line.split('-')[0].strip() if '-' in line else line
                    reasoning = line.split('-', 1)[1].strip() if '-' in line else None
                    
                    actions.append(AutoGLMAction(
                        action=action_text.title(),
                        params={},
                        reasoning=reasoning
                    ))
                    
            except Exception as e:
                logger.warning(f"Failed to parse action line: {line}, error: {e}")
                continue
        
        return actions
    
    def is_available(self) -> bool:
        """Check if AutoGLM is available"""
        try:
            # Simple health check - could be improved
            return bool(self.api_key)
        except:
            return False
