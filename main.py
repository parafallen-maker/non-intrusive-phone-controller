"""Main FastAPI application"""
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from config import settings, ensure_directories
from tactical.models import (
    NetworkConfig, AutoGLMRequest, ExecutionRequest,
    ScanRequest, LogEntry, HealthStatus,
    S3Command, S3Response
)
from tactical.autoglm_client import AutoGLMClient
from tactical.action_translator import ActionTranslator
from tactical.execution_engine import ExecutionEngine
from drivers import WiFiDriver


# Setup logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Global instances
driver: Optional[WiFiDriver] = None
autoglm_client: Optional[AutoGLMClient] = None
action_translator: Optional[ActionTranslator] = None
execution_engine: Optional[ExecutionEngine] = None
log_queue: asyncio.Queue = asyncio.Queue()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager"""
    global s3_manager, autoglm_client, action_translator, execution_engine
    
    # Startup
    logger.info("Starting AutoGLM-S3 Service...")
    ensure_directories()
    
    # Initialize S3 manager
    try:
        s3_manager = S3DeviceManager(settings.dll_path)
        logger.info("S3 Device Manager initialized")
    except Exception as e:
        logger.error(f"Failed to initialize S3 manager: {e}")
    
    # Initialize AutoGLM client (lazy init, requires API key)
    try:
        if settings.zhipuai_api_key:
            autoglm_client = AutoGLMClient()
            logger.info("AutoGLM Client initialized")
        else:
            logger.warning("AutoGLM API key not set, will initialize on first request")
    except Exception as e:
        logger.error(f"Failed to initialize AutoGLM client: {e}")
    
    # Initialize translator and executor
    action_translator = ActionTranslator()
    execution_engine = ExecutionEngine(s3_manager)
    
    # Register log callback
    async def log_callback(log_entry: LogEntry):
        await log_queue.put(log_entry)
    
    execution_engine.register_log_callback(log_callback)
    
    logger.info("Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down service...")


# Create FastAPI app
app = FastAPI(
    title="AutoGLM-S3 Service",
    description="AutoGLM phone control via S3 mechanical arm",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Mount screenshots directory
screenshots_dir = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(screenshots_dir, exist_ok=True)

# 文件锁，防止读写冲突
import threading
screenshot_locks = {}
screenshot_lock_mutex = threading.Lock()

def get_screenshot_lock(filename):
    """获取指定文件的锁"""
    with screenshot_lock_mutex:
        if filename not in screenshot_locks:
            screenshot_locks[filename] = threading.Lock()
        return screenshot_locks[filename]

# Custom endpoint for screenshots with proper cache control
@app.get("/screenshots/{filename}")
async def get_screenshot(filename: str):
    """Serve screenshot with no-cache headers - read entire file to memory to avoid length mismatch"""
    filepath = os.path.join(screenshots_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Screenshot not found")
    
    # 获取文件锁并读取整个文件到内存
    lock = get_screenshot_lock(filename)
    with lock:
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")
    
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Length": str(len(content))
        }
    )



# ==================== Web Interface ====================

@app.get("/")
async def root():
    """Serve web interface"""
    static_index = os.path.join(static_dir, "index.html")
    if os.path.exists(static_index):
        return FileResponse(static_index)
    return {"message": "AutoGLM-S3 Service API", "docs": "/docs"}


# ==================== Configuration Endpoints ====================

@app.post("/api/config/network")
async def configure_network(config: NetworkConfig):
    """Configure network and API settings"""
    global autoglm_client
    
    try:
        # Update API key if provided
        if config.api_key:
            autoglm_client = AutoGLMClient(api_key=config.api_key)
            logger.info("AutoGLM client reconfigured with new API key")
        
        # Verify device connectivity
        if s3_manager:
            status = s3_manager.get_device_status(config.device_ip)
            if not status.online:
                raise HTTPException(status_code=400, detail=f"Device {config.device_ip} not reachable")
        
        return {
            "success": True,
            "message": "Network configured successfully",
            "device_ip": config.device_ip,
            "device_online": status.online if s3_manager else False
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Network configuration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scan")
async def scan_devices(request: ScanRequest):
    """Scan LAN for S3 devices"""
    if not s3_manager:
        raise HTTPException(status_code=503, detail="S3 manager not available")
    
    try:
        import time
        start = time.time()
        devices = s3_manager.scan_devices(request.port)
        scan_time = time.time() - start
        
        return {
            "success": True,
            "devices": devices,
            "scan_time": scan_time,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== AutoGLM Endpoints ====================

@app.post("/api/glm/infer")
async def autoglm_infer(request: AutoGLMRequest):
    """AutoGLM inference"""
    if not autoglm_client:
        raise HTTPException(status_code=503, detail="AutoGLM client not initialized. Please configure API key.")
    
    try:
        # Capture screenshot if requested
        screenshot_path = None
        if request.include_screenshot and s3_manager:
            logger.info(f"Capturing screenshot from {request.device_ip}")
            screenshot_path = s3_manager.capture_screenshot(request.device_ip)
            if not screenshot_path:
                logger.warning("Screenshot capture failed, proceeding without image")
        
        # Call AutoGLM
        response = autoglm_client.infer(request, screenshot_path)
        
        if not response.success:
            raise HTTPException(status_code=500, detail=response.error)
        
        return response.model_dump()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AutoGLM inference failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Execution Endpoints ====================

@app.post("/api/plan/translate")
async def translate_actions(request: AutoGLMRequest):
    """Translate AutoGLM actions to execution plan"""
    if not autoglm_client:
        raise HTTPException(status_code=503, detail="AutoGLM client not initialized")
    
    try:
        # Get AutoGLM response
        screenshot_path = None
        if request.include_screenshot and s3_manager:
            screenshot_path = s3_manager.capture_screenshot(request.device_ip)
        
        glm_response = autoglm_client.infer(request, screenshot_path)
        
        if not glm_response.success:
            raise HTTPException(status_code=500, detail=glm_response.error)
        
        # Translate to execution plan
        plan = action_translator.create_execution_plan(
            device_ip=request.device_ip,
            instruction=request.instruction,
            actions=glm_response.actions
        )
        
        return plan.model_dump()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Action translation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/execute/run")
async def execute_plan(request: ExecutionRequest):
    """Execute action plan"""
    if not execution_engine:
        raise HTTPException(status_code=503, detail="Execution engine not initialized")
    
    try:
        # Create or get plan
        if request.plan_id:
            # Execute existing plan
            plan = execution_engine.active_plans.get(request.plan_id)
            if not plan:
                raise HTTPException(status_code=404, detail="Plan not found")
        else:
            # Create new plan from instruction
            if not request.instruction:
                raise HTTPException(status_code=400, detail="Either plan_id or instruction required")
            
            # Get AutoGLM response
            glm_request = AutoGLMRequest(
                instruction=request.instruction,
                device_ip=request.device_ip,
                include_screenshot=True
            )
            
            screenshot_path = None
            if s3_manager:
                screenshot_path = s3_manager.capture_screenshot(request.device_ip)
            
            glm_response = autoglm_client.infer(glm_request, screenshot_path)
            
            if not glm_response.success:
                raise HTTPException(status_code=500, detail=glm_response.error)
            
            # Create plan
            plan = action_translator.create_execution_plan(
                device_ip=request.device_ip,
                instruction=request.instruction,
                actions=glm_response.actions
            )
        
        # Execute plan
        result = await execution_engine.execute_plan(
            plan=plan,
            auto_retry=request.auto_retry,
            max_retries=request.max_retries
        )
        
        return result.model_dump()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Telemetry Endpoints ====================

@app.get("/api/telemetry/stream")
async def stream_logs(request: Request):
    """Stream real-time logs via SSE"""
    
    async def event_generator():
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                # Wait for log entry
                try:
                    log_entry = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                    yield {
                        "event": "log",
                        "data": log_entry.model_dump_json()
                    }
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {
                        "event": "ping",
                        "data": "keepalive"
                    }
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
    
    return EventSourceResponse(event_generator())


@app.get("/api/health")
async def health_check():
    """Health check"""
    try:
        # Check S3 devices
        device_statuses = []
        if s3_manager:
            # Quick scan
            devices = s3_manager.scan_devices()
            for device_ip in devices[:5]:  # Limit to 5
                status = s3_manager.get_device_status(device_ip)
                device_statuses.append(status)
        
        health = HealthStatus(
            autoglm_available=autoglm_client is not None and autoglm_client.is_available(),
            s3_devices=device_statuses,
            camera_available=True,  # TODO: actual camera check
            dll_loaded=s3_manager is not None and s3_manager.is_available(),
            timestamp=datetime.now()
        )
        
        return health.model_dump()
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/s3/tap")
async def s3_tap(request: dict):
    """Direct S3 tap command"""
    if not s3_manager:
        raise HTTPException(status_code=503, detail="S3 manager not available")
    
    device_ip = request.get("device_ip")
    x = request.get("x")
    y = request.get("y")
    count = request.get("count", 1)
    
    command = S3Command(
        command_type="move_click",
        params={"x": x, "y": y, "click_count": count, "delay_ms": 0}
    )
    
    response = s3_manager.execute_command(device_ip, command)
    return response.model_dump()


@app.post("/api/s3/swipe")
async def s3_swipe(request: dict):
    """Direct S3 swipe command"""
    if not s3_manager:
        raise HTTPException(status_code=503, detail="S3 manager not available")
    
    device_ip = request.get("device_ip")
    command = S3Command(
        command_type="drag",
        params={
            "start_x": request.get("start_x"),
            "start_y": request.get("start_y"),
            "end_x": request.get("end_x"),
            "end_y": request.get("end_y")
        }
    )
    
    response = s3_manager.execute_command(device_ip, command)
    return response.model_dump()


@app.post("/api/s3/long_press")
async def s3_long_press(request: dict):
    """Direct S3 long press command"""
    if not s3_manager:
        raise HTTPException(status_code=503, detail="S3 manager not available")
    
    device_ip = request.get("device_ip")
    duration = request.get("duration", 1000)
    
    command = S3Command(
        command_type="move_click",
        params={
            "x": request.get("x"),
            "y": request.get("y"),
            "click_count": 1,
            "delay_ms": duration
        }
    )
    
    response = s3_manager.execute_command(device_ip, command)
    return response.model_dump()


@app.post("/api/s3/screenshot")
async def s3_screenshot(request: dict):
    """Direct S3 screenshot command with fixed 270° rotation
    
    Request JSON:
    {
        "device_ip": "192.168.31.102"
    }
    """
    if not s3_manager:
        raise HTTPException(status_code=503, detail="S3 manager not available")
    
    device_ip = request.get("device_ip")
    if not device_ip:
        return {
            "success": False,
            "error": "Device IP is required"
        }
    
    # 固定旋转角度为 270°（rotation=3）
    rotation = 3
    
    logger.info(f"Screenshot request for device: {device_ip}, rotation: {rotation}")
    photo_path = s3_manager.capture_screenshot(device_ip, rotation=rotation)
    
    if photo_path:
        logger.info(f"Screenshot successful: {photo_path} (rotation mode: {rotation})")
        return {
            "success": True,
            "path": photo_path,
            "message": "Screenshot captured",
            "rotation": rotation
        }
    else:
        logger.warning(f"Screenshot failed for device {device_ip}. Check if device supports /capture endpoint.")
        return {
            "success": False,
            "error": "Screenshot failed. Device may not support /capture API or requires authentication. Check server logs for details."
        }


@app.get("/api/s3/status")
async def s3_status(device_ip: str):
    """Get device status"""
    if not s3_manager:
        raise HTTPException(status_code=503, detail="S3 manager not available")
    
    if not device_ip:
        raise HTTPException(status_code=400, detail="Device IP is required")
    
    logger.info(f"Status request for device: {device_ip}")
    result = s3_manager.controller.get_status(device_ip)
    
    return result


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "AutoGLM-S3 Service",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
