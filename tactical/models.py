"""Pydantic models for request/response validation"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


# ==================== Configuration Models ====================

class NetworkConfig(BaseModel):
    """Network configuration"""
    device_ip: str = Field(..., description="S3 device IP address")
    api_key: Optional[str] = Field(None, description="AutoGLM API key (overrides env)")
    

class CalibrationPoint(BaseModel):
    """Screen calibration point"""
    screen_x: float = Field(..., ge=0, le=1, description="Screen X ratio (0-1)")
    screen_y: float = Field(..., ge=0, le=1, description="Screen Y ratio (0-1)")
    physical_x: float = Field(..., description="Physical X coordinate")
    physical_y: float = Field(..., description="Physical Y coordinate")


class CalibrationConfig(BaseModel):
    """Calibration configuration"""
    device_ip: str
    points: List[CalibrationPoint] = Field(..., min_length=4)
    screen_width: int = Field(..., gt=0)
    screen_height: int = Field(..., gt=0)


# ==================== AutoGLM Models ====================

class AutoGLMRequest(BaseModel):
    """AutoGLM inference request"""
    instruction: str = Field(..., description="Natural language instruction")
    device_ip: str = Field(..., description="Target device IP")
    include_screenshot: bool = Field(True, description="Include current screenshot")
    session_id: Optional[str] = Field(None, description="Session ID for context")
    

class ActionType(str):
    """Supported action types"""
    LAUNCH = "Launch"
    TAP = "Tap"
    TYPE = "Type"
    SWIPE = "Swipe"
    BACK = "Back"
    HOME = "Home"
    LONG_PRESS = "Long Press"
    DOUBLE_TAP = "Double Tap"
    WAIT = "Wait"
    TAKE_OVER = "Take_over"


class AutoGLMAction(BaseModel):
    """Single action from AutoGLM"""
    action: str = Field(..., description="Action type")
    params: Optional[Dict[str, Any]] = Field(None, description="Action parameters")
    reasoning: Optional[str] = Field(None, description="Action reasoning")


class AutoGLMResponse(BaseModel):
    """AutoGLM inference response"""
    success: bool
    actions: List[AutoGLMAction]
    raw_response: Dict[str, Any]
    session_id: Optional[str] = None
    error: Optional[str] = None


# ==================== S3 Command Models ====================

class S3Command(BaseModel):
    """S3 device command"""
    command_type: Literal["move_click", "drag", "home", "play_audio", "capture", "get_status"]
    params: Dict[str, Any]
    

class S3Response(BaseModel):
    """S3 command response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ==================== Execution Models ====================

class ExecutionStep(BaseModel):
    """Single execution step"""
    step_id: int
    action: str
    params: Dict[str, Any]
    status: Literal["pending", "running", "success", "failed", "skipped"]
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0


class ExecutionPlan(BaseModel):
    """Execution plan"""
    plan_id: str
    device_ip: str
    instruction: str
    steps: List[ExecutionStep]
    created_at: datetime
    

class ExecutionRequest(BaseModel):
    """Execution request"""
    plan_id: Optional[str] = Field(None, description="Execute existing plan")
    instruction: Optional[str] = Field(None, description="New instruction to infer and execute")
    device_ip: str
    auto_retry: bool = Field(True, description="Auto retry on failure")
    max_retries: int = Field(2, ge=0, le=5, description="Max retries per step")


class ExecutionResult(BaseModel):
    """Execution result"""
    plan_id: str
    success: bool
    total_steps: int
    completed_steps: int
    failed_steps: int
    execution_time: float
    steps: List[ExecutionStep]
    final_screenshot: Optional[str] = None
    error: Optional[str] = None


# ==================== Telemetry Models ====================

class LogEntry(BaseModel):
    """Log entry for command line display"""
    timestamp: datetime
    level: Literal["INFO", "WARNING", "ERROR", "SUCCESS"]
    source: str
    message: str
    data: Optional[Dict[str, Any]] = None


class DeviceStatus(BaseModel):
    """Device status"""
    device_ip: str
    online: bool
    system_state: Optional[str] = None
    wifi_rssi: Optional[int] = None
    uptime: Optional[int] = None
    last_check: datetime


class HealthStatus(BaseModel):
    """System health status"""
    autoglm_available: bool
    s3_devices: List[DeviceStatus]
    camera_available: bool
    dll_loaded: bool
    timestamp: datetime


# ==================== Scan Models ====================

class ScanRequest(BaseModel):
    """Device scan request"""
    port: int = Field(8888, ge=1, le=65535)
    timeout: int = Field(5, ge=1, le=30, description="Scan timeout in seconds")


class ScanResult(BaseModel):
    """Device scan result"""
    devices: List[str]
    scan_time: float
    timestamp: datetime
