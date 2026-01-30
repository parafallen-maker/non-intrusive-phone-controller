#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能云服务 API
独立部署的 RESTful 服务，供多设备共享技能库
"""

import os
import uuid
import logging
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 假设我们有数据库模块
# from .database import get_db, SkillModel

logger = logging.getLogger(__name__)


# ========== Pydantic 模型 ==========

class SkillCreate(BaseModel):
    """创建技能请求"""
    name: str
    description: str = ""
    code: str = ""
    tags: List[str] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)
    source_device: str = ""


class SkillUpdate(BaseModel):
    """更新技能请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    tags: Optional[List[str]] = None
    parameters: Optional[dict] = None


class SkillResponse(BaseModel):
    """技能响应"""
    id: str
    name: str
    description: str
    code: str
    tags: List[str]
    parameters: dict
    source_device: str
    created_at: str
    updated_at: str
    use_count: int
    success_count: int


class SearchRequest(BaseModel):
    """搜索请求"""
    query: str
    limit: int = 10
    min_score: float = 0.5
    tags: Optional[List[str]] = None


class SearchResult(BaseModel):
    """搜索结果"""
    skill: SkillResponse
    score: float
    matched_field: str


class SyncRequest(BaseModel):
    """同步请求"""
    device_id: str
    skills: List[SkillCreate]
    last_sync: Optional[str] = None


class SyncResponse(BaseModel):
    """同步响应"""
    updated: List[SkillResponse]
    deleted: List[str]
    conflicts: List[str]
    server_time: str


class StatsUpdate(BaseModel):
    """统计更新"""
    skill_id: str
    success: bool


# ========== 内存存储（示例） ==========
# 生产环境应替换为数据库

class InMemoryStore:
    """内存存储（示例用）"""
    
    def __init__(self):
        self._skills: dict = {}
        self._embeddings: dict = {}
    
    def save(self, skill_id: str, data: dict):
        self._skills[skill_id] = data
    
    def get(self, skill_id: str) -> Optional[dict]:
        return self._skills.get(skill_id)
    
    def delete(self, skill_id: str) -> bool:
        if skill_id in self._skills:
            del self._skills[skill_id]
            return True
        return False
    
    def list_all(self) -> List[dict]:
        return list(self._skills.values())
    
    def search(self, query: str, limit: int = 10) -> List[tuple]:
        """简单关键词搜索"""
        results = []
        query_lower = query.lower()
        
        for skill_id, skill in self._skills.items():
            score = 0.0
            matched = ""
            
            if query_lower in skill.get("name", "").lower():
                score = 0.8
                matched = "name"
            elif query_lower in skill.get("description", "").lower():
                score = 0.5
                matched = "description"
            elif any(query_lower in tag.lower() for tag in skill.get("tags", [])):
                score = 0.4
                matched = "tags"
            
            if score > 0:
                results.append((skill, score, matched))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]


# 全局存储实例
store = InMemoryStore()


# ========== FastAPI 应用 ==========

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger.info("Skill Cloud Service starting...")
    yield
    logger.info("Skill Cloud Service shutting down...")


app = FastAPI(
    title="Skill Cloud Service",
    description="多设备共享技能库云服务",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== 认证依赖 ==========

async def verify_api_key(x_api_key: str = Header(None)):
    """验证 API Key"""
    expected_key = os.getenv("SKILL_API_KEY", "dev-key")
    
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    
    if x_api_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    return x_api_key


# ========== API 路由 ==========

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "skill_count": len(store.list_all())
    }


@app.get("/skills", response_model=List[SkillResponse])
async def list_skills(
    tags: Optional[str] = Query(None, description="逗号分隔的标签过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: str = Depends(verify_api_key)
):
    """列出所有技能"""
    skills = store.list_all()
    
    # 标签过滤
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        skills = [
            s for s in skills
            if any(t in s.get("tags", []) for t in tag_list)
        ]
    
    # 分页
    skills = skills[offset:offset + limit]
    
    return [_to_response(s) for s in skills]


@app.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    _: str = Depends(verify_api_key)
):
    """获取单个技能"""
    skill = store.get(skill_id)
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    return _to_response(skill)


@app.post("/skills", response_model=SkillResponse)
async def create_skill(
    skill: SkillCreate,
    _: str = Depends(verify_api_key)
):
    """创建技能"""
    skill_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    
    data = {
        "id": skill_id,
        "name": skill.name,
        "description": skill.description,
        "code": skill.code,
        "tags": skill.tags,
        "parameters": skill.parameters,
        "source_device": skill.source_device,
        "created_at": now,
        "updated_at": now,
        "use_count": 0,
        "success_count": 0
    }
    
    store.save(skill_id, data)
    logger.info(f"Created skill: {skill_id} ({skill.name})")
    
    return _to_response(data)


@app.put("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    updates: SkillUpdate,
    _: str = Depends(verify_api_key)
):
    """更新技能"""
    skill = store.get(skill_id)
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    # 应用更新
    update_data = updates.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        skill[key] = value
    
    skill["updated_at"] = datetime.now().isoformat()
    store.save(skill_id, skill)
    
    logger.info(f"Updated skill: {skill_id}")
    return _to_response(skill)


@app.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    _: str = Depends(verify_api_key)
):
    """删除技能"""
    if not store.delete(skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    
    logger.info(f"Deleted skill: {skill_id}")
    return {"status": "deleted", "id": skill_id}


@app.post("/skills/search", response_model=List[SearchResult])
async def search_skills(
    request: SearchRequest,
    _: str = Depends(verify_api_key)
):
    """搜索技能"""
    results = store.search(request.query, request.limit)
    
    # 过滤低分
    results = [(s, score, matched) for s, score, matched in results if score >= request.min_score]
    
    # 标签过滤
    if request.tags:
        results = [
            (s, score, matched) for s, score, matched in results
            if any(t in s.get("tags", []) for t in request.tags)
        ]
    
    return [
        SearchResult(
            skill=_to_response(skill),
            score=score,
            matched_field=matched
        )
        for skill, score, matched in results
    ]


@app.post("/skills/sync", response_model=SyncResponse)
async def sync_skills(
    request: SyncRequest,
    _: str = Depends(verify_api_key)
):
    """同步技能"""
    updated = []
    conflicts = []
    
    for skill_data in request.skills:
        # 检查是否已存在
        existing = None
        for s in store.list_all():
            if s.get("name") == skill_data.name:
                existing = s
                break
        
        if existing:
            # 冲突检测（简化版）
            if existing.get("source_device") != request.device_id:
                conflicts.append(existing["id"])
                continue
            
            # 更新现有技能
            existing.update({
                "description": skill_data.description,
                "code": skill_data.code,
                "tags": skill_data.tags,
                "parameters": skill_data.parameters,
                "updated_at": datetime.now().isoformat()
            })
            store.save(existing["id"], existing)
            updated.append(_to_response(existing))
        else:
            # 创建新技能
            skill_id = str(uuid.uuid4())[:8]
            now = datetime.now().isoformat()
            
            data = {
                "id": skill_id,
                "name": skill_data.name,
                "description": skill_data.description,
                "code": skill_data.code,
                "tags": skill_data.tags,
                "parameters": skill_data.parameters,
                "source_device": request.device_id,
                "created_at": now,
                "updated_at": now,
                "use_count": 0,
                "success_count": 0
            }
            store.save(skill_id, data)
            updated.append(_to_response(data))
    
    return SyncResponse(
        updated=updated,
        deleted=[],
        conflicts=conflicts,
        server_time=datetime.now().isoformat()
    )


@app.post("/skills/stats")
async def update_stats(
    stats: StatsUpdate,
    _: str = Depends(verify_api_key)
):
    """更新使用统计"""
    skill = store.get(stats.skill_id)
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    skill["use_count"] = skill.get("use_count", 0) + 1
    if stats.success:
        skill["success_count"] = skill.get("success_count", 0) + 1
    
    store.save(stats.skill_id, skill)
    
    return {"status": "updated"}


# ========== 辅助函数 ==========

def _to_response(skill: dict) -> SkillResponse:
    """转换为响应模型"""
    return SkillResponse(
        id=skill.get("id", ""),
        name=skill.get("name", ""),
        description=skill.get("description", ""),
        code=skill.get("code", ""),
        tags=skill.get("tags", []),
        parameters=skill.get("parameters", {}),
        source_device=skill.get("source_device", ""),
        created_at=skill.get("created_at", ""),
        updated_at=skill.get("updated_at", ""),
        use_count=skill.get("use_count", 0),
        success_count=skill.get("success_count", 0)
    )


# ========== 启动入口 ==========

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "cloud_service:app",
        host="0.0.0.0",
        port=8080,
        reload=True
    )
