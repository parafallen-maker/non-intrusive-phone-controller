#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一技能管理器
整合本地存储、远程存储、同步、蒸馏、匹配等功能
提供简洁的高级 API
"""

import os
import logging
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime

from .protocols import Skill, SkillMatch, SkillStore, SkillDistillerProtocol, SyncStatus
from .local_store import LocalSkillStore, MockLocalSkillStore
from .remote_store import RemoteSkillStore, MockRemoteSkillStore
from .sync_manager import SkillSyncManager

logger = logging.getLogger(__name__)


class SkillManager:
    """统一技能管理器
    
    整合所有技能系统功能:
    - 本地/远程存储
    - 同步管理
    - 技能蒸馏
    - 语义搜索
    
    设计原则:
    - 简洁的高级 API
    - 可配置的后端（本地/云端）
    - 自动同步
    - 向后兼容
    
    Usage:
        # 最简配置（仅本地）
        manager = SkillManager.create_local("./skills")
        
        # 云端配置
        manager = SkillManager.create_cloud(
            local_dir="./skills",
            api_url="https://skills.example.com/api/v1",
            api_key="sk-xxx",
            device_id="device-001"
        )
        
        # 使用
        skill = manager.distill(task, trace)  # 从执行中蒸馏
        matches = manager.search("发朋友圈")   # 搜索技能
        skill = manager.get_best_match("给张三点赞")  # 获取最佳匹配
    """
    
    def __init__(
        self,
        local_store: SkillStore,
        remote_store: Optional[SkillStore] = None,
        distiller: Optional[SkillDistillerProtocol] = None,
        auto_sync: bool = True,
        sync_interval: int = 60
    ):
        self.local = local_store
        self.remote = remote_store
        self.distiller = distiller
        
        # 创建同步管理器
        self.sync_manager = SkillSyncManager(local_store, remote_store)
        
        # 自动启动同步
        if auto_sync and remote_store:
            self.sync_manager.start_background_sync(sync_interval)
        
        # 统计
        self._stats = {
            "searches": 0,
            "saves": 0,
            "distills": 0,
            "hits": 0,
            "misses": 0
        }
        
        logger.info("[SkillManager] Initialized")
    
    # ========== 工厂方法 ==========
    
    @classmethod
    def create_local(
        cls,
        base_dir: str,
        distiller: Optional[SkillDistillerProtocol] = None
    ) -> "SkillManager":
        """创建仅本地的管理器"""
        local = LocalSkillStore(base_dir)
        return cls(local, None, distiller, auto_sync=False)
    
    @classmethod
    def create_cloud(
        cls,
        local_dir: str,
        api_url: str,
        api_key: str,
        device_id: str,
        distiller: Optional[SkillDistillerProtocol] = None,
        auto_sync: bool = True,
        sync_interval: int = 60
    ) -> "SkillManager":
        """创建云端同步的管理器"""
        local = LocalSkillStore(local_dir)
        remote = RemoteSkillStore(api_url, api_key, device_id)
        return cls(local, remote, distiller, auto_sync, sync_interval)
    
    @classmethod
    def create_mock(cls) -> "SkillManager":
        """创建 Mock 管理器（用于测试）"""
        local = MockLocalSkillStore()
        remote = MockRemoteSkillStore()
        return cls(local, remote, None, auto_sync=False)
    
    # ========== 核心 API ==========
    
    def save(self, skill: Skill) -> str:
        """保存技能"""
        self._stats["saves"] += 1
        return self.sync_manager.save(skill)
    
    def get(self, skill_id: str) -> Optional[Skill]:
        """获取技能"""
        return self.sync_manager.get(skill_id)
    
    def delete(self, skill_id: str) -> bool:
        """删除技能"""
        return self.sync_manager.delete(skill_id)
    
    def list_all(self) -> List[Skill]:
        """列出所有技能"""
        return self.sync_manager.list_all()
    
    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.5
    ) -> List[SkillMatch]:
        """搜索技能
        
        Args:
            query: 搜索查询
            limit: 最大返回数量
            min_score: 最小匹配分数
        
        Returns:
            匹配的技能列表
        """
        self._stats["searches"] += 1
        
        matches = self.sync_manager.search(query, limit)
        
        # 过滤低分匹配
        matches = [m for m in matches if m.score >= min_score]
        
        if matches:
            self._stats["hits"] += 1
        else:
            self._stats["misses"] += 1
        
        return matches
    
    def get_best_match(
        self,
        query: str,
        min_score: float = 0.7
    ) -> Optional[Skill]:
        """获取最佳匹配的技能
        
        Args:
            query: 搜索查询
            min_score: 最小匹配分数
        
        Returns:
            最佳匹配的技能，如果没有足够好的匹配返回 None
        """
        matches = self.search(query, limit=1, min_score=min_score)
        
        if matches:
            return matches[0].skill
        return None
    
    # ========== 技能蒸馏 ==========
    
    def distill(
        self,
        task: str,
        trace: Any,
        success: bool = True
    ) -> Optional[Skill]:
        """从执行轨迹中蒸馏技能
        
        Args:
            task: 任务描述
            trace: 执行轨迹（步骤列表）
            success: 执行是否成功
        
        Returns:
            蒸馏出的技能，如果失败返回 None
        """
        if not success:
            logger.debug("[SkillManager] Skipping distill for failed task")
            return None
        
        if not self.distiller:
            logger.warning("[SkillManager] No distiller configured")
            return None
        
        self._stats["distills"] += 1
        
        try:
            skill = self.distiller.distill(task, trace)
            if skill:
                self.save(skill)
                logger.info(f"[SkillManager] Distilled skill: {skill.name}")
            return skill
        except Exception as e:
            logger.error(f"[SkillManager] Distill failed: {e}")
            return None
    
    def should_distill(self, task: str) -> bool:
        """判断任务是否值得蒸馏
        
        Args:
            task: 任务描述
        
        Returns:
            是否应该蒸馏
        """
        # 检查是否已存在相似技能
        matches = self.search(task, limit=1, min_score=0.9)
        if matches:
            logger.debug(f"[SkillManager] Similar skill exists: {matches[0].skill.name}")
            return False
        
        return True
    
    # ========== 统计更新 ==========
    
    def record_usage(self, skill_id: str, success: bool):
        """记录技能使用情况"""
        self.sync_manager.update_stats(skill_id, success)
    
    # ========== 同步控制 ==========
    
    def sync(self) -> SyncStatus:
        """手动触发同步"""
        return self.sync_manager.sync()
    
    def get_sync_status(self) -> SyncStatus:
        """获取同步状态"""
        return self.sync_manager.get_sync_status()
    
    # ========== 状态查询 ==========
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        sync_stats = self.sync_manager.get_stats()
        
        return {
            **self._stats,
            "sync": sync_stats,
            "local_count": len(self.local.list_all()),
            "has_remote": self.remote is not None,
            "has_distiller": self.distiller is not None
        }
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        status = {
            "local": "ok",
            "remote": "ok" if self.remote else "not_configured",
            "distiller": "ok" if self.distiller else "not_configured"
        }
        
        # 检查本地存储
        try:
            self.local.list_all()
        except Exception as e:
            status["local"] = f"error: {e}"
        
        # 检查远程存储
        if self.remote:
            try:
                self.remote.get_sync_status()
            except Exception as e:
                status["remote"] = f"error: {e}"
        
        return status
    
    # ========== 生命周期 ==========
    
    def shutdown(self):
        """关闭管理器"""
        self.sync_manager.stop_background_sync()
        logger.info("[SkillManager] Shutdown complete")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()


# ========== 便捷函数 ==========

_default_manager: Optional[SkillManager] = None


def get_default_manager() -> Optional[SkillManager]:
    """获取默认管理器"""
    return _default_manager


def set_default_manager(manager: SkillManager):
    """设置默认管理器"""
    global _default_manager
    _default_manager = manager


def init_skill_manager(
    local_dir: str = "./skills",
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    device_id: Optional[str] = None
) -> SkillManager:
    """初始化技能管理器
    
    从环境变量或参数配置管理器
    """
    # 从环境变量获取配置
    api_url = api_url or os.getenv("SKILL_API_URL")
    api_key = api_key or os.getenv("SKILL_API_KEY")
    device_id = device_id or os.getenv("DEVICE_ID")
    
    if api_url and api_key and device_id:
        manager = SkillManager.create_cloud(
            local_dir=local_dir,
            api_url=api_url,
            api_key=api_key,
            device_id=device_id
        )
    else:
        manager = SkillManager.create_local(local_dir)
    
    set_default_manager(manager)
    return manager
