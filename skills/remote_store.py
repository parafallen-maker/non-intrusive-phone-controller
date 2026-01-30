#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
远程技能存储 - 云端 API 客户端
支持多设备共享技能库
"""

import json
import time
import logging
import hashlib
from typing import Optional, List, Dict, Any
from dataclasses import asdict
from datetime import datetime

from .protocols import Skill, SkillMatch, SkillStore, SyncEvent, SyncStatus

logger = logging.getLogger(__name__)


class RemoteSkillStore:
    """远程技能存储
    
    通过 HTTP API 与云端技能库交互，实现：
    - 多设备技能共享
    - 增量同步
    - 冲突解决
    
    Usage:
        store = RemoteSkillStore(
            api_url="https://skills.example.com/api",
            api_key="your_api_key",
            device_id="device_001"
        )
        
        # 保存技能（自动同步到云端）
        skill_id = store.save(skill)
        
        # 搜索（优先本地缓存，必要时查云端）
        matches = store.search("朋友圈点赞")
        
        # 手动同步
        store.sync()
    """
    
    def __init__(
        self,
        api_url: str,
        api_key: str,
        device_id: str,
        cache_ttl: int = 300,  # 缓存有效期（秒）
        timeout: int = 10
    ):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.device_id = device_id
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        
        # 本地缓存
        self._cache: Dict[str, Skill] = {}
        self._cache_time: float = 0
        
        # 待同步队列
        self._pending_events: List[SyncEvent] = []
        
        # HTTP 客户端
        self._session = None
        self._init_session()
    
    def _init_session(self):
        """初始化 HTTP 会话"""
        try:
            import httpx
            self._session = httpx.Client(
                base_url=self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "X-Device-ID": self.device_id,
                    "Content-Type": "application/json"
                },
                timeout=self.timeout
            )
            logger.info(f"[RemoteSkillStore] Connected to {self.api_url}")
        except ImportError:
            logger.warning("[RemoteSkillStore] httpx not installed, using requests")
            try:
                import requests
                self._session = requests.Session()
                self._session.headers.update({
                    "Authorization": f"Bearer {self.api_key}",
                    "X-Device-ID": self.device_id,
                    "Content-Type": "application/json"
                })
            except ImportError:
                logger.error("[RemoteSkillStore] No HTTP client available")
                self._session = None
    
    def _request(self, method: str, endpoint: str, data: Any = None) -> Optional[Dict]:
        """发送 HTTP 请求"""
        if not self._session:
            logger.error("[RemoteSkillStore] No HTTP session")
            return None
        
        url = f"{self.api_url}{endpoint}"
        
        try:
            if hasattr(self._session, 'request'):
                # httpx
                response = self._session.request(
                    method, endpoint,
                    json=data if data else None
                )
                response.raise_for_status()
                return response.json()
            else:
                # requests
                response = self._session.request(
                    method, url,
                    json=data if data else None,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as e:
            logger.error(f"[RemoteSkillStore] Request failed: {e}")
            return None
    
    # ========== SkillStore 协议实现 ==========
    
    def save(self, skill: Skill) -> str:
        """保存技能到云端"""
        skill.device_id = self.device_id
        skill.updated_at = datetime.now().isoformat()
        
        data = skill.to_dict()
        result = self._request("POST", "/skills", data)
        
        if result and result.get("success"):
            skill_id = result.get("id", skill.id)
            self._cache[skill_id] = skill
            logger.info(f"[RemoteSkillStore] Saved skill: {skill.name} ({skill_id})")
            return skill_id
        else:
            # 保存失败，加入待同步队列
            event = SyncEvent(
                event_type="create",
                skill_id=skill.id,
                skill_data=data,
                timestamp=datetime.now().isoformat(),
                device_id=self.device_id
            )
            self._pending_events.append(event)
            logger.warning(f"[RemoteSkillStore] Queued for sync: {skill.name}")
            return skill.id
    
    def get(self, skill_id: str) -> Optional[Skill]:
        """获取技能"""
        # 先查缓存
        if skill_id in self._cache:
            return self._cache[skill_id]
        
        # 查云端
        result = self._request("GET", f"/skills/{skill_id}")
        if result and result.get("skill"):
            skill = Skill.from_dict(result["skill"])
            self._cache[skill_id] = skill
            return skill
        
        return None
    
    def delete(self, skill_id: str) -> bool:
        """删除技能"""
        result = self._request("DELETE", f"/skills/{skill_id}")
        
        if result and result.get("success"):
            self._cache.pop(skill_id, None)
            logger.info(f"[RemoteSkillStore] Deleted skill: {skill_id}")
            return True
        else:
            # 删除失败，加入队列
            event = SyncEvent(
                event_type="delete",
                skill_id=skill_id,
                skill_data=None,
                timestamp=datetime.now().isoformat(),
                device_id=self.device_id
            )
            self._pending_events.append(event)
            return False
    
    def list_all(self) -> List[Skill]:
        """列出所有技能"""
        # 检查缓存是否有效
        if time.time() - self._cache_time < self.cache_ttl and self._cache:
            return list(self._cache.values())
        
        result = self._request("GET", "/skills")
        if result and result.get("skills"):
            skills = [Skill.from_dict(s) for s in result["skills"]]
            self._cache = {s.id: s for s in skills}
            self._cache_time = time.time()
            return skills
        
        return list(self._cache.values())
    
    def search(self, query: str, limit: int = 10) -> List[SkillMatch]:
        """搜索技能"""
        result = self._request("POST", "/skills/search", {
            "query": query,
            "limit": limit
        })
        
        if result and result.get("matches"):
            matches = []
            for m in result["matches"]:
                skill = Skill.from_dict(m["skill"])
                matches.append(SkillMatch(
                    skill=skill,
                    score=m.get("score", 0.0),
                    matched_field=m.get("matched_field", "semantic")
                ))
            return matches
        
        # 云端搜索失败，本地搜索
        return self._local_search(query, limit)
    
    def _local_search(self, query: str, limit: int) -> List[SkillMatch]:
        """本地缓存搜索（降级方案）"""
        query_lower = query.lower()
        matches = []
        
        for skill in self._cache.values():
            score = 0.0
            
            # 名称匹配
            if query_lower in skill.name.lower():
                score += 0.5
            
            # 描述匹配
            if query_lower in skill.description.lower():
                score += 0.3
            
            # 标签匹配
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 0.2
                    break
            
            if score > 0:
                matches.append(SkillMatch(skill=skill, score=score, matched_field="keyword"))
        
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]
    
    def update_stats(self, skill_id: str, success: bool) -> None:
        """更新使用统计"""
        self._request("POST", f"/skills/{skill_id}/stats", {
            "success": success,
            "device_id": self.device_id,
            "timestamp": datetime.now().isoformat()
        })
    
    # ========== 同步相关 ==========
    
    def sync(self) -> SyncStatus:
        """执行同步"""
        # 上传待同步事件
        uploaded = 0
        for event in self._pending_events[:]:
            result = self._request("POST", "/sync/event", asdict(event))
            if result and result.get("success"):
                self._pending_events.remove(event)
                uploaded += 1
        
        # 拉取更新
        last_sync = self._cache_time or 0
        result = self._request("GET", f"/sync/updates?since={last_sync}")
        
        downloaded = 0
        if result and result.get("updates"):
            for update in result["updates"]:
                if update["type"] == "create" or update["type"] == "update":
                    skill = Skill.from_dict(update["skill"])
                    self._cache[skill.id] = skill
                    downloaded += 1
                elif update["type"] == "delete":
                    self._cache.pop(update["skill_id"], None)
                    downloaded += 1
        
        self._cache_time = time.time()
        
        return SyncStatus(
            last_sync=datetime.now().isoformat(),
            pending_uploads=len(self._pending_events),
            pending_downloads=0,
            conflicts=0
        )
    
    def get_sync_status(self) -> SyncStatus:
        """获取同步状态"""
        return SyncStatus(
            last_sync=datetime.fromtimestamp(self._cache_time).isoformat() if self._cache_time else "",
            pending_uploads=len(self._pending_events),
            pending_downloads=0,
            conflicts=0
        )


class MockRemoteSkillStore(RemoteSkillStore):
    """Mock 远程存储（测试用）"""
    
    def __init__(self, device_id: str = "mock_device"):
        self.device_id = device_id
        self._cache: Dict[str, Skill] = {}
        self._cache_time = time.time()
        self._pending_events = []
    
    def _request(self, method: str, endpoint: str, data: Any = None) -> Optional[Dict]:
        """Mock 请求"""
        logger.info(f"[MockRemote] {method} {endpoint}")
        return {"success": True}
    
    def save(self, skill: Skill) -> str:
        skill.device_id = self.device_id
        self._cache[skill.id] = skill
        return skill.id
    
    def get(self, skill_id: str) -> Optional[Skill]:
        return self._cache.get(skill_id)
    
    def delete(self, skill_id: str) -> bool:
        return self._cache.pop(skill_id, None) is not None
    
    def list_all(self) -> List[Skill]:
        return list(self._cache.values())
    
    def search(self, query: str, limit: int = 10) -> List[SkillMatch]:
        return self._local_search(query, limit)
