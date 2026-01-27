#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
语义匹配器 (Semantic Matcher)
基于向量相似度的意图匹配

支持多种后端:
- 本地: sentence-transformers
- API: OpenAI embeddings / ZhipuAI embeddings
- 降级: 关键词 TF-IDF
"""

import json
import logging
import hashlib
from typing import Optional, List, Dict, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import numpy as np


logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    """嵌入结果"""
    text: str
    vector: List[float]
    model: str


class SemanticMatcher:
    """语义匹配器
    
    使用向量相似度进行意图匹配，支持多种嵌入后端。
    
    Usage:
        matcher = SemanticMatcher(provider='local')
        
        # 索引技能
        matcher.index_skill("skill_1", "微信朋友圈点赞", "帮助用户给朋友圈点赞")
        matcher.index_skill("skill_2", "打开应用", "启动手机上的应用程序")
        
        # 查询匹配
        results = matcher.match("帮我给好友的动态点个赞")
        # [("skill_1", 0.85), ("skill_2", 0.32)]
    """
    
    def __init__(
        self,
        provider: str = 'tfidf',
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        cache_path: Optional[str] = None
    ):
        """初始化
        
        Args:
            provider: 嵌入提供商 (local/openai/zhipu/tfidf)
            api_key: API Key（API 模式需要）
            model_name: 模型名称
            cache_path: 向量缓存路径
        """
        self.provider = provider
        self.api_key = api_key
        self.model_name = model_name
        self.cache_path = Path(cache_path) if cache_path else None
        
        # 技能索引 {skill_id: (text, vector)}
        self.skill_index: Dict[str, Tuple[str, np.ndarray]] = {}
        
        # TF-IDF 索引（降级方案）
        self._tfidf_vocab: Dict[str, int] = {}
        self._tfidf_idf: Dict[str, float] = {}
        
        # 初始化嵌入模型
        self.embedder = None
        self._init_embedder()
    
    def _init_embedder(self):
        """初始化嵌入模型"""
        if self.provider == 'local':
            try:
                from sentence_transformers import SentenceTransformer
                model_name = self.model_name or 'paraphrase-multilingual-MiniLM-L12-v2'
                self.embedder = SentenceTransformer(model_name)
                logger.info(f"[SemanticMatcher] Loaded local model: {model_name}")
            except ImportError:
                logger.warning("[SemanticMatcher] sentence-transformers not installed, falling back to TF-IDF")
                self.provider = 'tfidf'
                
        elif self.provider == 'openai':
            try:
                from openai import OpenAI
                self.embedder = OpenAI(api_key=self.api_key)
                self.model_name = self.model_name or 'text-embedding-3-small'
            except ImportError:
                logger.warning("[SemanticMatcher] openai not installed, falling back to TF-IDF")
                self.provider = 'tfidf'
                
        elif self.provider == 'zhipu':
            try:
                from zhipuai import ZhipuAI
                self.embedder = ZhipuAI(api_key=self.api_key)
                self.model_name = self.model_name or 'embedding-2'
            except ImportError:
                logger.warning("[SemanticMatcher] zhipuai not installed, falling back to TF-IDF")
                self.provider = 'tfidf'
    
    def _embed(self, text: str) -> np.ndarray:
        """生成文本嵌入向量"""
        if self.provider == 'local' and self.embedder:
            vector = self.embedder.encode(text, convert_to_numpy=True)
            return vector
            
        elif self.provider == 'openai' and self.embedder:
            response = self.embedder.embeddings.create(
                model=self.model_name,
                input=text
            )
            return np.array(response.data[0].embedding)
            
        elif self.provider == 'zhipu' and self.embedder:
            response = self.embedder.embeddings.create(
                model=self.model_name,
                input=text
            )
            return np.array(response.data[0].embedding)
            
        else:
            # TF-IDF 降级
            return self._tfidf_embed(text)
    
    def _tfidf_embed(self, text: str) -> np.ndarray:
        """TF-IDF 嵌入（降级方案）"""
        # 简单的字符级分词
        words = list(text)
        
        # 更新词汇表
        for word in words:
            if word not in self._tfidf_vocab:
                self._tfidf_vocab[word] = len(self._tfidf_vocab)
        
        # 生成向量
        vector = np.zeros(max(len(self._tfidf_vocab), 1000))
        word_count = {}
        for word in words:
            word_count[word] = word_count.get(word, 0) + 1
        
        for word, count in word_count.items():
            if word in self._tfidf_vocab:
                idx = self._tfidf_vocab[word]
                if idx < len(vector):
                    # TF
                    tf = count / len(words) if words else 0
                    # 简化 IDF
                    idf = self._tfidf_idf.get(word, 1.0)
                    vector[idx] = tf * idf
        
        # 归一化
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        
        return vector
    
    def _cosine_similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """计算余弦相似度"""
        # 确保维度一致
        min_len = min(len(v1), len(v2))
        v1 = v1[:min_len]
        v2 = v2[:min_len]
        
        dot = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(dot / (norm1 * norm2))
    
    def index_skill(
        self,
        skill_id: str,
        name: str,
        description: str,
        keywords: Optional[List[str]] = None,
        behavior: Optional[str] = None
    ):
        """索引技能
        
        将技能的语义信息转换为向量并存储。
        
        Args:
            skill_id: 技能ID
            name: 技能名称
            description: 技能描述
            keywords: 关键词列表
            behavior: 行为描述
        """
        # 组合文本
        text_parts = [name, description]
        if keywords:
            text_parts.extend(keywords)
        if behavior:
            # 只取行为描述的前200字
            text_parts.append(behavior[:200])
        
        combined_text = " ".join(text_parts)
        
        # 生成向量
        vector = self._embed(combined_text)
        
        # 存储
        self.skill_index[skill_id] = (combined_text, vector)
        
        logger.debug(f"[SemanticMatcher] Indexed: {skill_id} ({name})")
    
    def remove_skill(self, skill_id: str):
        """移除技能索引"""
        if skill_id in self.skill_index:
            del self.skill_index[skill_id]
    
    def match(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.0
    ) -> List[Tuple[str, float]]:
        """匹配查询
        
        Args:
            query: 用户查询
            top_k: 返回前K个结果
            threshold: 最低相似度阈值
            
        Returns:
            [(skill_id, score), ...] 按相似度降序
        """
        if not self.skill_index:
            return []
        
        # 查询向量
        query_vector = self._embed(query)
        
        # 计算相似度
        results = []
        for skill_id, (text, skill_vector) in self.skill_index.items():
            score = self._cosine_similarity(query_vector, skill_vector)
            if score >= threshold:
                results.append((skill_id, score))
        
        # 排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    def save_index(self, path: str):
        """保存索引到文件"""
        data = {
            'provider': self.provider,
            'model_name': self.model_name,
            'skills': {}
        }
        
        for skill_id, (text, vector) in self.skill_index.items():
            data['skills'][skill_id] = {
                'text': text,
                'vector': vector.tolist()
            }
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        
        logger.info(f"[SemanticMatcher] Saved index: {path}")
    
    def load_index(self, path: str):
        """从文件加载索引"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for skill_id, skill_data in data.get('skills', {}).items():
            self.skill_index[skill_id] = (
                skill_data['text'],
                np.array(skill_data['vector'])
            )
        
        logger.info(f"[SemanticMatcher] Loaded {len(self.skill_index)} skills")


class HybridMatcher:
    """混合匹配器
    
    结合语义匹配和关键词匹配，提供更准确的结果。
    """
    
    def __init__(
        self,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        **kwargs
    ):
        """初始化
        
        Args:
            semantic_weight: 语义匹配权重
            keyword_weight: 关键词匹配权重
        """
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        
        self.semantic_matcher = SemanticMatcher(**kwargs)
        
        # 关键词索引 {skill_id: keywords}
        self.keyword_index: Dict[str, List[str]] = {}
    
    def index_skill(
        self,
        skill_id: str,
        name: str,
        description: str,
        keywords: Optional[List[str]] = None,
        behavior: Optional[str] = None
    ):
        """索引技能"""
        # 语义索引
        self.semantic_matcher.index_skill(
            skill_id, name, description, keywords, behavior
        )
        
        # 关键词索引
        all_keywords = [name] + (keywords or [])
        # 从描述中提取关键词
        all_keywords.extend(description.split()[:10])
        self.keyword_index[skill_id] = [k.lower() for k in all_keywords]
    
    def _keyword_score(self, query: str, skill_id: str) -> float:
        """计算关键词匹配分数"""
        keywords = self.keyword_index.get(skill_id, [])
        if not keywords:
            return 0.0
        
        query_lower = query.lower()
        matches = sum(1 for kw in keywords if kw in query_lower)
        return matches / len(keywords) if keywords else 0.0
    
    def match(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.1
    ) -> List[Tuple[str, float]]:
        """混合匹配
        
        Args:
            query: 用户查询
            top_k: 返回前K个
            threshold: 最低分数阈值
            
        Returns:
            [(skill_id, score), ...]
        """
        # 语义匹配
        semantic_results = self.semantic_matcher.match(query, top_k=top_k * 2)
        
        # 计算混合分数
        results = []
        seen = set()
        
        for skill_id, semantic_score in semantic_results:
            keyword_score = self._keyword_score(query, skill_id)
            
            combined_score = (
                self.semantic_weight * semantic_score +
                self.keyword_weight * keyword_score
            )
            
            if combined_score >= threshold:
                results.append((skill_id, combined_score))
                seen.add(skill_id)
        
        # 补充纯关键词匹配（可能语义没匹配到）
        for skill_id in self.keyword_index:
            if skill_id not in seen:
                keyword_score = self._keyword_score(query, skill_id)
                if keyword_score > 0.3:  # 关键词强匹配
                    combined_score = self.keyword_weight * keyword_score
                    if combined_score >= threshold:
                        results.append((skill_id, combined_score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


# ========== 测试代码 ==========

if __name__ == '__main__':
    print("=== 语义匹配器测试 ===\n")
    
    # 使用 TF-IDF 测试（不需要额外依赖）
    print("--- TF-IDF 模式 ---")
    matcher = SemanticMatcher(provider='tfidf')
    
    # 索引技能
    matcher.index_skill(
        "skill_1",
        "微信朋友圈点赞",
        "帮助用户给微信朋友圈的帖子点赞",
        keywords=["微信", "朋友圈", "点赞", "社交"]
    )
    
    matcher.index_skill(
        "skill_2",
        "打开应用",
        "打开手机上的应用程序",
        keywords=["打开", "启动", "应用", "程序"]
    )
    
    matcher.index_skill(
        "skill_3",
        "抖音刷视频",
        "在抖音上浏览和点赞视频",
        keywords=["抖音", "视频", "点赞", "刷"]
    )
    
    # 测试查询
    test_queries = [
        "给朋友圈点个赞",
        "帮我打开微信",
        "刷一刷抖音",
        "支持一下好友的动态",
        "启动计算器",
    ]
    
    print("\n查询测试:")
    for query in test_queries:
        results = matcher.match(query, top_k=3, threshold=0.0)
        print(f"  '{query}'")
        for skill_id, score in results:
            print(f"    -> {skill_id}: {score:.3f}")
        if not results:
            print("    -> 无匹配")
        print()
    
    # 混合匹配器测试
    print("--- 混合匹配模式 ---")
    hybrid = HybridMatcher(provider='tfidf')
    
    hybrid.index_skill(
        "skill_1",
        "微信朋友圈点赞",
        "帮助用户给微信朋友圈的帖子点赞",
        keywords=["微信", "朋友圈", "点赞"]
    )
    
    hybrid.index_skill(
        "skill_2",
        "打开应用",
        "打开手机上的应用程序",
        keywords=["打开", "启动", "应用"]
    )
    
    for query in ["给朋友圈点赞", "打开微信"]:
        results = hybrid.match(query, top_k=3)
        print(f"'{query}' -> {results}")
    
    print("\n=== 测试完成 ===")
