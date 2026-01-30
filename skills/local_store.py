#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
本地技能存储
基于文件系统的技能存储实现，包装现有的 SkillRegistry
"""

import os
import json
import logging
from typing import Optional, List
from datetime import datetime
from dataclasses import asdict

from .protocols import Skill, SkillMatch, SkillStore, SyncStatus

logger = logging.getLogger(__name__)


class LocalSkillStore(SkillStore):
    """本地文件存储实现
    
    存储结构：
        skills_dir/
        ├── skills/
        │   ├── {skill_id}.json
        │   └── ...
        ├── index.json          # 技能索引
        └── embeddings.json     # 向量缓存
    
    Usage:
        store = LocalSkillStore("./data/skills")
        store.save(skill)
        matches = store.search("发朋友圈")
    """
    
    def __init__(
        self,
        base_dir: str,
        embedding_model: str = "text-embedding-3-small"
    ):
        self.base_dir = base_dir
        self.skills_dir = os.path.join(base_dir, "skills")
        self.index_path = os.path.join(base_dir, "index.json")
        self.embeddings_path = os.path.join(base_dir, "embeddings.json")
        self.embedding_model = embedding_model
        
        # 确保目录存在
        os.makedirs(self.skills_dir, exist_ok=True)
        
        # 加载索引
        self._index: dict = self._load_index()
        
        # 加载嵌入缓存
        self._embeddings: dict = self._load_embeddings()
        
        # 嵌入客户端（延迟初始化）
        self._embedding_client = None
    
    def _load_index(self) -> dict:
        """加载技能索引"""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[LocalStore] Failed to load index: {e}")
        return {"skills": {}, "updated_at": None}
    
    def _save_index(self):
        """保存技能索引"""
        self._index["updated_at"] = datetime.now().isoformat()
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2)
    
    def _load_embeddings(self) -> dict:
        """加载嵌入缓存"""
        if os.path.exists(self.embeddings_path):
            try:
                with open(self.embeddings_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[LocalStore] Failed to load embeddings: {e}")
        return {}
    
    def _save_embeddings(self):
        """保存嵌入缓存"""
        with open(self.embeddings_path, 'w', encoding='utf-8') as f:
            json.dump(self._embeddings, f)
    
    def _get_skill_path(self, skill_id: str) -> str:
        """获取技能文件路径"""
        return os.path.join(self.skills_dir, f"{skill_id}.json")
    
    def _skill_to_dict(self, skill: Skill) -> dict:
        """将 Skill 转换为字典"""
        return asdict(skill)
    
    def _dict_to_skill(self, data: dict) -> Skill:
        """将字典转换为 Skill"""
        return Skill(**data)
    
    # ========== SkillStore 协议实现 ==========
    
    def save(self, skill: Skill) -> str:
        """保存技能"""
        skill_path = self._get_skill_path(skill.id)
        
        # 更新时间戳
        skill.updated_at = datetime.now().isoformat()
        
        # 保存技能文件
        with open(skill_path, 'w', encoding='utf-8') as f:
            json.dump(self._skill_to_dict(skill), f, ensure_ascii=False, indent=2)
        
        # 更新索引
        self._index["skills"][skill.id] = {
            "name": skill.name,
            "tags": skill.tags,
            "updated_at": skill.updated_at
        }
        self._save_index()
        
        # 生成嵌入
        self._update_embedding(skill)
        
        logger.info(f"[LocalStore] Saved skill: {skill.id} ({skill.name})")
        return skill.id
    
    def get(self, skill_id: str) -> Optional[Skill]:
        """获取技能"""
        skill_path = self._get_skill_path(skill_id)
        
        if not os.path.exists(skill_path):
            return None
        
        try:
            with open(skill_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return self._dict_to_skill(data)
        except Exception as e:
            logger.error(f"[LocalStore] Failed to load skill {skill_id}: {e}")
            return None
    
    def delete(self, skill_id: str) -> bool:
        """删除技能"""
        skill_path = self._get_skill_path(skill_id)
        
        if not os.path.exists(skill_path):
            return False
        
        try:
            os.remove(skill_path)
            
            # 从索引移除
            if skill_id in self._index["skills"]:
                del self._index["skills"][skill_id]
                self._save_index()
            
            # 从嵌入缓存移除
            if skill_id in self._embeddings:
                del self._embeddings[skill_id]
                self._save_embeddings()
            
            logger.info(f"[LocalStore] Deleted skill: {skill_id}")
            return True
        except Exception as e:
            logger.error(f"[LocalStore] Failed to delete skill {skill_id}: {e}")
            return False
    
    def list_all(self) -> List[Skill]:
        """列出所有技能"""
        skills = []
        
        for skill_id in self._index.get("skills", {}):
            skill = self.get(skill_id)
            if skill:
                skills.append(skill)
        
        return skills
    
    def search(self, query: str, limit: int = 10) -> List[SkillMatch]:
        """语义搜索技能"""
        matches = []
        
        # 生成查询嵌入
        query_embedding = self._get_embedding(query)
        
        if query_embedding is None:
            # 如果无法生成嵌入，退化为关键词匹配
            return self._keyword_search(query, limit)
        
        # 计算相似度
        for skill_id, skill_embedding in self._embeddings.items():
            if isinstance(skill_embedding, list):
                similarity = self._cosine_similarity(query_embedding, skill_embedding)
                skill = self.get(skill_id)
                if skill:
                    matches.append(SkillMatch(
                        skill=skill,
                        score=similarity,
                        matched_field="embedding"
                    ))
        
        # 排序并限制数量
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]
    
    def update_stats(self, skill_id: str, success: bool) -> None:
        """更新使用统计"""
        skill = self.get(skill_id)
        if not skill:
            return
        
        skill.use_count += 1
        if success:
            skill.success_count += 1
        
        self.save(skill)
    
    def get_sync_status(self) -> SyncStatus:
        """获取同步状态（本地存储无同步）"""
        return SyncStatus(
            last_sync=self._index.get("updated_at", ""),
            pending_uploads=0,
            pending_downloads=0,
            conflicts=0
        )
    
    # ========== 嵌入相关 ==========
    
    def _get_embedding_client(self):
        """获取嵌入客户端"""
        if self._embedding_client is None:
            try:
                from openai import OpenAI
                self._embedding_client = OpenAI()
            except ImportError:
                logger.warning("[LocalStore] OpenAI not installed, using mock embeddings")
                return None
            except Exception as e:
                logger.warning(f"[LocalStore] Failed to init OpenAI: {e}")
                return None
        return self._embedding_client
    
    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本嵌入"""
        client = self._get_embedding_client()
        if not client:
            return None
        
        try:
            response = client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.warning(f"[LocalStore] Failed to get embedding: {e}")
            return None
    
    def _update_embedding(self, skill: Skill):
        """更新技能的嵌入向量"""
        # 构建嵌入文本
        embed_text = f"{skill.name} {skill.description} {' '.join(skill.tags)}"
        
        embedding = self._get_embedding(embed_text)
        if embedding:
            self._embeddings[skill.id] = embedding
            self._save_embeddings()
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        if len(a) != len(b):
            return 0.0
        
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x ** 2 for x in a) ** 0.5
        norm_b = sum(x ** 2 for x in b) ** 0.5
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
    
    def _keyword_search(self, query: str, limit: int) -> List[SkillMatch]:
        """关键词搜索（退化方案）"""
        matches = []
        query_lower = query.lower()
        
        for skill_id in self._index.get("skills", {}):
            skill = self.get(skill_id)
            if not skill:
                continue
            
            # 计算匹配分数
            score = 0.0
            matched_field = ""
            
            # 名称匹配（最高权重）
            if query_lower in skill.name.lower():
                score += 0.5
                matched_field = "name"
            
            # 描述匹配
            if query_lower in skill.description.lower():
                score += 0.3
                matched_field = matched_field or "description"
            
            # 标签匹配
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 0.2
                    matched_field = matched_field or "tags"
                    break
            
            if score > 0:
                matches.append(SkillMatch(
                    skill=skill,
                    score=score,
                    matched_field=matched_field
                ))
        
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]


# ========== Mock 实现（用于测试） ==========

class MockLocalSkillStore(SkillStore):
    """内存中的 Mock 存储，用于测试"""
    
    def __init__(self):
        self._skills: dict = {}
    
    def save(self, skill: Skill) -> str:
        self._skills[skill.id] = skill
        return skill.id
    
    def get(self, skill_id: str) -> Optional[Skill]:
        return self._skills.get(skill_id)
    
    def delete(self, skill_id: str) -> bool:
        if skill_id in self._skills:
            del self._skills[skill_id]
            return True
        return False
    
    def list_all(self) -> List[Skill]:
        return list(self._skills.values())
    
    def search(self, query: str, limit: int = 10) -> List[SkillMatch]:
        matches = []
        query_lower = query.lower()
        
        for skill in self._skills.values():
            score = 0.0
            if query_lower in skill.name.lower():
                score = 0.8
            elif query_lower in skill.description.lower():
                score = 0.5
            
            if score > 0:
                matches.append(SkillMatch(skill=skill, score=score, matched_field="name"))
        
        return matches[:limit]
    
    def update_stats(self, skill_id: str, success: bool) -> None:
        if skill_id in self._skills:
            self._skills[skill_id].use_count += 1
            if success:
                self._skills[skill_id].success_count += 1
    
    def get_sync_status(self) -> SyncStatus:
        return SyncStatus(
            last_sync=datetime.now().isoformat(),
            pending_uploads=0,
            pending_downloads=0,
            conflicts=0
        )
