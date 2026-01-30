#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能同步管理器
管理本地与云端技能库的同步
"""

import time
import logging
import threading
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
from dataclasses import dataclass

from .protocols import Skill, SkillMatch, SkillStore, SyncStatus

logger = logging.getLogger(__name__)


@dataclass
class ConflictResolution:
    """冲突解决结果"""
    skill_id: str
    resolution: str  # local/remote/merge
    resolved_skill: Optional[Skill]


class SkillSyncManager:
    """技能同步管理器
    
    职责：
    - 管理本地和远程存储的同步
    - 处理冲突
    - 提供统一的读写接口
    
    同步策略：
    - 写入优先本地，异步同步到云端
    - 读取优先本地缓存，未命中查云端
    - 冲突时默认使用最新版本
    
    Usage:
        from skills import LocalSkillStore, RemoteSkillStore, SkillSyncManager
        
        local = LocalSkillStore("./skills")
        remote = RemoteSkillStore(api_url, api_key, device_id)
        
        manager = SkillSyncManager(local, remote)
        manager.start_background_sync(interval=60)
        
        # 统一接口
        skill_id = manager.save(skill)
        matches = manager.search("朋友圈点赞")
    """
    
    def __init__(
        self,
        local_store: SkillStore,
        remote_store: Optional[SkillStore] = None,
        conflict_resolver: Optional[Callable[[Skill, Skill], Skill]] = None
    ):
        self.local = local_store
        self.remote = remote_store
        self.conflict_resolver = conflict_resolver or self._default_conflict_resolver
        
        # 同步状态
        self._sync_thread: Optional[threading.Thread] = None
        self._sync_running = False
        self._last_sync: Optional[str] = None
        
        # 统计
        self._stats = {
            "total_saves": 0,
            "total_searches": 0,
            "sync_count": 0,
            "conflicts_resolved": 0
        }
    
    # ========== 统一读写接口 ==========
    
    def save(self, skill: Skill) -> str:
        """保存技能（本地优先，异步同步）"""
        self._stats["total_saves"] += 1
        
        # 先保存到本地
        skill_id = self.local.save(skill)
        
        # 异步同步到远程
        if self.remote:
            threading.Thread(
                target=self._async_save_remote,
                args=(skill,),
                daemon=True
            ).start()
        
        return skill_id
    
    def _async_save_remote(self, skill: Skill):
        """异步保存到远程"""
        try:
            self.remote.save(skill)
            logger.debug(f"[SyncManager] Synced to remote: {skill.id}")
        except Exception as e:
            logger.warning(f"[SyncManager] Remote save failed: {e}")
    
    def get(self, skill_id: str) -> Optional[Skill]:
        """获取技能（本地优先）"""
        # 先查本地
        skill = self.local.get(skill_id)
        if skill:
            return skill
        
        # 查远程
        if self.remote:
            skill = self.remote.get(skill_id)
            if skill:
                # 缓存到本地
                self.local.save(skill)
                return skill
        
        return None
    
    def delete(self, skill_id: str) -> bool:
        """删除技能"""
        local_result = self.local.delete(skill_id)
        
        if self.remote:
            threading.Thread(
                target=lambda: self.remote.delete(skill_id),
                daemon=True
            ).start()
        
        return local_result
    
    def list_all(self) -> List[Skill]:
        """列出所有技能"""
        return self.local.list_all()
    
    def search(self, query: str, limit: int = 10) -> List[SkillMatch]:
        """搜索技能"""
        self._stats["total_searches"] += 1
        
        # 优先本地搜索
        local_matches = self.local.search(query, limit)
        
        # 如果本地结果不足且有远程存储，补充远程结果
        if len(local_matches) < limit and self.remote:
            try:
                remote_matches = self.remote.search(query, limit)
                # 合并结果，去重
                seen_ids = {m.skill.id for m in local_matches}
                for m in remote_matches:
                    if m.skill.id not in seen_ids:
                        local_matches.append(m)
                        # 缓存到本地
                        self.local.save(m.skill)
            except Exception as e:
                logger.warning(f"[SyncManager] Remote search failed: {e}")
        
        # 按分数排序
        local_matches.sort(key=lambda m: m.score, reverse=True)
        return local_matches[:limit]
    
    def update_stats(self, skill_id: str, success: bool) -> None:
        """更新使用统计"""
        self.local.update_stats(skill_id, success)
        
        if self.remote:
            threading.Thread(
                target=lambda: self.remote.update_stats(skill_id, success),
                daemon=True
            ).start()
    
    # ========== 同步控制 ==========
    
    def sync(self) -> SyncStatus:
        """执行完整同步"""
        if not self.remote:
            return SyncStatus(
                last_sync=datetime.now().isoformat(),
                pending_uploads=0,
                pending_downloads=0,
                conflicts=0
            )
        
        self._stats["sync_count"] += 1
        logger.info("[SyncManager] Starting sync...")
        
        conflicts = 0
        
        # 1. 上传本地新增/修改
        local_skills = self.local.list_all()
        for skill in local_skills:
            try:
                remote_skill = self.remote.get(skill.id)
                if remote_skill:
                    # 检查冲突
                    if remote_skill.updated_at > skill.updated_at:
                        # 远程更新，可能需要合并
                        resolved = self.conflict_resolver(skill, remote_skill)
                        self.local.save(resolved)
                        conflicts += 1
                        self._stats["conflicts_resolved"] += 1
                else:
                    # 远程没有，上传
                    self.remote.save(skill)
            except Exception as e:
                logger.warning(f"[SyncManager] Sync error for {skill.id}: {e}")
        
        # 2. 下载远程新增
        try:
            remote_skills = self.remote.list_all()
            local_ids = {s.id for s in local_skills}
            
            for skill in remote_skills:
                if skill.id not in local_ids:
                    self.local.save(skill)
        except Exception as e:
            logger.warning(f"[SyncManager] Download failed: {e}")
        
        self._last_sync = datetime.now().isoformat()
        
        status = SyncStatus(
            last_sync=self._last_sync,
            pending_uploads=0,
            pending_downloads=0,
            conflicts=conflicts
        )
        
        logger.info(f"[SyncManager] Sync complete. Conflicts: {conflicts}")
        return status
    
    def start_background_sync(self, interval: int = 60):
        """启动后台同步"""
        if self._sync_thread and self._sync_thread.is_alive():
            logger.warning("[SyncManager] Background sync already running")
            return
        
        self._sync_running = True
        self._sync_thread = threading.Thread(
            target=self._background_sync_loop,
            args=(interval,),
            daemon=True
        )
        self._sync_thread.start()
        logger.info(f"[SyncManager] Background sync started (interval={interval}s)")
    
    def stop_background_sync(self):
        """停止后台同步"""
        self._sync_running = False
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
        logger.info("[SyncManager] Background sync stopped")
    
    def _background_sync_loop(self, interval: int):
        """后台同步循环"""
        while self._sync_running:
            try:
                self.sync()
            except Exception as e:
                logger.error(f"[SyncManager] Background sync error: {e}")
            
            # 等待下次同步
            for _ in range(interval):
                if not self._sync_running:
                    break
                time.sleep(1)
    
    def _default_conflict_resolver(self, local: Skill, remote: Skill) -> Skill:
        """默认冲突解决：使用最新版本"""
        if remote.updated_at > local.updated_at:
            logger.info(f"[SyncManager] Conflict resolved: using remote version for {local.id}")
            return remote
        else:
            logger.info(f"[SyncManager] Conflict resolved: using local version for {local.id}")
            return local
    
    # ========== 状态查询 ==========
    
    def get_sync_status(self) -> SyncStatus:
        """获取同步状态"""
        remote_status = self.remote.get_sync_status() if self.remote else None
        
        return SyncStatus(
            last_sync=self._last_sync or "",
            pending_uploads=remote_status.pending_uploads if remote_status else 0,
            pending_downloads=remote_status.pending_downloads if remote_status else 0,
            conflicts=0
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "local_count": len(self.local.list_all()),
            "remote_connected": self.remote is not None,
            "last_sync": self._last_sync
        }
