"""Configuration management"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings"""
    
    # AutoGLM API
    zhipuai_api_key: str = ""
    zhipuai_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipuai_model: str = "autoglm-phone"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    
    # S3 Device
    default_s3_port: int = 8888
    dll_path: str = "../dll接口/lgb.dll"
    
    # Camera
    camera_index: int = 0
    photo_dir: str = "./screenshots"
    temp_dir: str = "./temp"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "./logs/autoglm_service.log"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()


def ensure_directories():
    """Create necessary directories"""
    os.makedirs(settings.photo_dir, exist_ok=True)
    os.makedirs(settings.temp_dir, exist_ok=True)
    os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
