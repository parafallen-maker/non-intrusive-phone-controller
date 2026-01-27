"""Execution engine for running S3 commands"""
import logging
import time
import asyncio
from typing import Dict, Optional
from datetime import datetime

from models import (
    ExecutionPlan, ExecutionStep, ExecutionResult,
    S3Command, LogEntry
)
from s3_manager import S3DeviceManager


logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Execute S3 command plans"""
    
    def __init__(self, s3_manager: S3DeviceManager):
        """Initialize execution engine
        
        Args:
            s3_manager: S3 device manager
        """
        self.s3_manager = s3_manager
        self.active_plans: Dict[str, ExecutionPlan] = {}
        self.log_callbacks = []
    
    def register_log_callback(self, callback):
        """Register callback for real-time logs"""
        self.log_callbacks.append(callback)
    
    async def _emit_log(self, level: str, source: str, message: str, data: Optional[Dict] = None):
        """Emit log entry to all callbacks"""
        log_entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            source=source,
            message=message,
            data=data
        )
        
        for callback in self.log_callbacks:
            try:
                await callback(log_entry)
            except Exception as e:
                logger.error(f"Log callback failed: {e}")
    
    async def execute_plan(
        self, 
        plan: ExecutionPlan,
        auto_retry: bool = True,
        max_retries: int = 2
    ) -> ExecutionResult:
        """Execute execution plan
        
        Args:
            plan: Execution plan
            auto_retry: Enable auto retry on failure
            max_retries: Max retries per step
            
        Returns:
            Execution result
        """
        self.active_plans[plan.plan_id] = plan
        
        await self._emit_log("INFO", "Executor", f"Starting execution plan {plan.plan_id}")
        await self._emit_log("INFO", "Executor", f"Instruction: {plan.instruction}")
        await self._emit_log("INFO", "Executor", f"Total steps: {len(plan.steps)}")
        
        start_time = time.time()
        completed = 0
        failed = 0
        
        for step in plan.steps:
            await self._emit_log("INFO", "Executor", f"Step {step.step_id}/{len(plan.steps)}: {step.action}")
            
            # Execute step with retry
            success = await self._execute_step(
                plan.device_ip,
                step,
                auto_retry,
                max_retries
            )
            
            if success:
                completed += 1
                await self._emit_log("SUCCESS", "Executor", f"Step {step.step_id} completed")
            else:
                failed += 1
                await self._emit_log("ERROR", "Executor", f"Step {step.step_id} failed: {step.error}")
                
                # Stop on critical failure
                if not auto_retry:
                    break
        
        execution_time = time.time() - start_time
        
        # Capture final screenshot
        final_screenshot = None
        try:
            await self._emit_log("INFO", "Executor", "Capturing final screenshot...")
            screenshot_path = self.s3_manager.capture_screenshot(plan.device_ip)
            if screenshot_path:
                final_screenshot = screenshot_path
                await self._emit_log("SUCCESS", "Executor", f"Final screenshot saved: {screenshot_path}")
        except Exception as e:
            await self._emit_log("WARNING", "Executor", f"Failed to capture final screenshot: {e}")
        
        result = ExecutionResult(
            plan_id=plan.plan_id,
            success=(failed == 0),
            total_steps=len(plan.steps),
            completed_steps=completed,
            failed_steps=failed,
            execution_time=execution_time,
            steps=plan.steps,
            final_screenshot=final_screenshot
        )
        
        await self._emit_log(
            "SUCCESS" if result.success else "ERROR",
            "Executor",
            f"Execution completed: {completed}/{len(plan.steps)} successful, {failed} failed, {execution_time:.2f}s"
        )
        
        return result
    
    async def _execute_step(
        self,
        device_ip: str,
        step: ExecutionStep,
        auto_retry: bool,
        max_retries: int
    ) -> bool:
        """Execute single step
        
        Args:
            device_ip: Target device IP
            step: Execution step
            auto_retry: Enable retry
            max_retries: Max retries
            
        Returns:
            Success status
        """
        step.status = "running"
        step.start_time = datetime.now()
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    await self._emit_log("INFO", "Executor", f"Retry attempt {attempt}/{max_retries}")
                
                # Handle different action types
                if step.action == "s3_move_click":
                    result = await self._execute_s3_command(
                        device_ip,
                        S3Command(command_type="move_click", params=step.params)
                    )
                elif step.action == "s3_drag":
                    result = await self._execute_s3_command(
                        device_ip,
                        S3Command(command_type="drag", params=step.params)
                    )
                elif step.action == "s3_home":
                    result = await self._execute_s3_command(
                        device_ip,
                        S3Command(command_type="home", params={})
                    )
                elif step.action == "wait":
                    duration = step.params.get('duration', 1.0)
                    await self._emit_log("INFO", "Executor", f"Waiting {duration}s...")
                    await asyncio.sleep(duration)
                    result = {'success': True}
                elif step.action == "manual_intervention":
                    await self._emit_log("WARNING", "Executor", f"Manual intervention required: {step.params.get('reason')}")
                    step.status = "skipped"
                    step.end_time = datetime.now()
                    return True
                elif step.action == "manual_type":
                    await self._emit_log("WARNING", "Executor", f"Manual typing required: {step.params.get('text')}")
                    await self._emit_log("WARNING", "Executor", step.params.get('note', ''))
                    step.status = "skipped"
                    step.end_time = datetime.now()
                    return True
                else:
                    raise ValueError(f"Unknown action: {step.action}")
                
                # Check result
                if result.get('success'):
                    step.status = "success"
                    step.result = result
                    step.end_time = datetime.now()
                    return True
                else:
                    error = result.get('error', 'Command failed')
                    if not auto_retry or attempt >= max_retries:
                        step.status = "failed"
                        step.error = error
                        step.end_time = datetime.now()
                        return False
                    else:
                        await self._emit_log("WARNING", "Executor", f"Step failed: {error}, retrying...")
                        step.retry_count += 1
                        await asyncio.sleep(0.5)
                        
            except Exception as e:
                error = str(e)
                logger.error(f"Step execution error: {error}")
                
                if not auto_retry or attempt >= max_retries:
                    step.status = "failed"
                    step.error = error
                    step.end_time = datetime.now()
                    return False
                else:
                    await self._emit_log("ERROR", "Executor", f"Step error: {error}, retrying...")
                    step.retry_count += 1
                    await asyncio.sleep(0.5)
        
        step.status = "failed"
        step.error = f"Max retries ({max_retries}) exceeded"
        step.end_time = datetime.now()
        return False
    
    async def _execute_s3_command(self, device_ip: str, command: S3Command) -> Dict:
        """Execute S3 command (async wrapper)
        
        Args:
            device_ip: Device IP
            command: S3 command
            
        Returns:
            Command result dict
        """
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            self.s3_manager.execute_command,
            device_ip,
            command
        )
        
        return {
            'success': response.success,
            'message': response.message,
            'data': response.data,
            'error': response.error
        }
