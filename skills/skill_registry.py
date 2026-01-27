#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
技能注册表 (Skill Registry)
实现 Task 5.1: 技能记忆系统

核心功能:
- 技能存储与检索
- 语义相似度搜索
- 技能描述索引
"""

import os
import json
import hashlib
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """技能定义"""
    id: str                      # 唯一标识 (基于内容的 hash)
    name: str                    # 技能名称
    description: str             # 语义描述
    code: str                    # Python 代码
    tags: List[str] = field(default_factory=list)     # 标签
    usage_count: int = 0         # 使用次数
    success_rate: float = 1.0    # 成功率
    created_at: str = ""         # 创建时间
    updated_at: str = ""         # 更新时间
    source: str = "manual"       # 来源 (manual/distilled/generated)
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


class SkillRegistry:
    """技能注册表
    
    管理可复用的自动化技能脚本。
    
    Usage:
        registry = SkillRegistry("/path/to/skills")
        
        # 注册技能
        skill_id = registry.register(
            name="微信朋友圈点赞",
            description="打开微信朋友圈并给指定数量的帖子点赞",
            code='''
            step("打开微信")
            step("点击发现")
            step("点击朋友圈")
            for i in range(count):
                step(f"点击第{i+1}条的点赞")
            ''',
            tags=["微信", "社交", "点赞"]
        )
        
        # 搜索技能
        skills = registry.search("朋友圈点赞")
        
        # 获取技能
        skill = registry.get(skill_id)
    """
    
    INDEX_FILE = "index.json"
    
    def __init__(self, storage_path: str = "./skill_store"):
        """初始化技能注册表
        
        Args:
            storage_path: 技能存储目录
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.index_path = self.storage_path / self.INDEX_FILE
        self.skills: Dict[str, Skill] = {}
        
        # 加载索引
        self._load_index()
    
    def _load_index(self):
        """加载技能索引"""
        if self.index_path.exists():
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for skill_data in data.get('skills', []):
                        skill = Skill(**skill_data)
                        self.skills[skill.id] = skill
                logger.info(f"[SkillRegistry] Loaded {len(self.skills)} skills")
            except Exception as e:
                logger.error(f"[SkillRegistry] Failed to load index: {e}")
                self.skills = {}
        else:
            logger.info("[SkillRegistry] No index found, starting fresh")
    
    def _save_index(self):
        """保存技能索引"""
        data = {
            'version': '1.0',
            'updated_at': datetime.now().isoformat(),
            'skills': [asdict(s) for s in self.skills.values()]
        }
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _generate_id(self, name: str, code: str) -> str:
        """生成技能 ID (基于内容 hash)"""
        content = f"{name}:{code}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def register(
        self,
        name: str,
        description: str,
        code: str,
        tags: Optional[List[str]] = None,
        source: str = "manual"
    ) -> str:
        """注册新技能
        
        Args:
            name: 技能名称
            description: 语义描述
            code: Python 代码
            tags: 标签列表
            source: 来源
            
        Returns:
            技能 ID
        """
        skill_id = self._generate_id(name, code)
        
        # 检查是否已存在
        if skill_id in self.skills:
            logger.info(f"[SkillRegistry] Skill already exists: {skill_id}")
            return skill_id
        
        skill = Skill(
            id=skill_id,
            name=name,
            description=description,
            code=code,
            tags=tags or [],
            source=source
        )
        
        self.skills[skill_id] = skill
        
        # 同时保存到独立文件
        skill_file = self.storage_path / f"{skill_id}.json"
        with open(skill_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(skill), f, ensure_ascii=False, indent=2)
        
        # 更新索引
        self._save_index()
        
        logger.info(f"[SkillRegistry] Registered skill: {name} ({skill_id})")
        return skill_id
    
    def get(self, skill_id: str) -> Optional[Skill]:
        """获取技能
        
        Args:
            skill_id: 技能 ID
            
        Returns:
            Skill 对象或 None
        """
        return self.skills.get(skill_id)
    
    def search(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[Skill]:
        """搜索技能
        
        使用简单的关键词匹配进行搜索。
        未来可以升级为向量相似度搜索。
        
        Args:
            query: 搜索关键词
            tags: 过滤标签
            limit: 最大返回数量
            
        Returns:
            匹配的技能列表
        """
        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for skill in self.skills.values():
            # 标签过滤
            if tags and not any(t in skill.tags for t in tags):
                continue
            
            # 计算匹配分数
            score = self._calculate_match_score(skill, query_lower, query_words)
            
            if score > 0:
                results.append((skill, score))
        
        # 按分数排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return [s for s, _ in results[:limit]]
    
    def _calculate_match_score(
        self,
        skill: Skill,
        query_lower: str,
        query_words: set
    ) -> float:
        """计算匹配分数"""
        score = 0.0
        
        # 名称匹配 (权重高)
        name_lower = skill.name.lower()
        if query_lower in name_lower:
            score += 10.0
        for word in query_words:
            if word in name_lower:
                score += 3.0
        
        # 描述匹配 (权重中)
        desc_lower = skill.description.lower()
        if query_lower in desc_lower:
            score += 5.0
        for word in query_words:
            if word in desc_lower:
                score += 1.5
        
        # 标签匹配 (权重中)
        tags_lower = [t.lower() for t in skill.tags]
        for word in query_words:
            if word in tags_lower:
                score += 2.0
        
        # 使用频率加成
        score += min(skill.usage_count * 0.1, 2.0)
        
        # 成功率加成
        score *= skill.success_rate
        
        return score
    
    def list_all(self) -> List[Skill]:
        """列出所有技能"""
        return list(self.skills.values())
    
    def delete(self, skill_id: str) -> bool:
        """删除技能
        
        Args:
            skill_id: 技能 ID
            
        Returns:
            是否删除成功
        """
        if skill_id not in self.skills:
            return False
        
        del self.skills[skill_id]
        
        # 删除文件
        skill_file = self.storage_path / f"{skill_id}.json"
        if skill_file.exists():
            skill_file.unlink()
        
        # 更新索引
        self._save_index()
        
        logger.info(f"[SkillRegistry] Deleted skill: {skill_id}")
        return True
    
    def update_stats(
        self,
        skill_id: str,
        success: bool
    ):
        """更新技能统计信息
        
        Args:
            skill_id: 技能 ID
            success: 是否执行成功
        """
        skill = self.skills.get(skill_id)
        if not skill:
            return
        
        skill.usage_count += 1
        
        # 更新成功率 (滑动平均)
        alpha = 0.1  # 平滑系数
        skill.success_rate = (1 - alpha) * skill.success_rate + alpha * (1.0 if success else 0.0)
        skill.updated_at = datetime.now().isoformat()
        
        self._save_index()
    
    def export(self, output_path: str) -> str:
        """导出所有技能为 JSON
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            导出的文件路径
        """
        data = {
            'version': '1.0',
            'exported_at': datetime.now().isoformat(),
            'count': len(self.skills),
            'skills': [asdict(s) for s in self.skills.values()]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return output_path
    
    def import_from_file(self, file_path: str) -> int:
        """从 JSON 文件导入技能
        
        Args:
            file_path: JSON 文件路径
            
        Returns:
            导入的技能数量
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        imported = 0
        for skill_data in data.get('skills', []):
            if skill_data.get('id') not in self.skills:
                skill = Skill(**skill_data)
                self.skills[skill.id] = skill
                imported += 1
        
        self._save_index()
        return imported


# ========== 全局实例 ==========

_default_registry: Optional[SkillRegistry] = None


def get_default_registry() -> SkillRegistry:
    """获取默认技能注册表"""
    global _default_registry
    if _default_registry is None:
        _default_registry = SkillRegistry()
    return _default_registry


# ========== 测试代码 ==========

if __name__ == '__main__':
    import tempfile
    import shutil
    
    print("=== Task 5.1 SkillRegistry 测试 ===\n")
    
    # 使用临时目录测试
    temp_dir = tempfile.mkdtemp()
    print(f"使用临时目录: {temp_dir}\n")
    
    try:
        registry = SkillRegistry(temp_dir)
        
        # 注册技能
        print("--- 注册技能 ---")
        
        skill1_id = registry.register(
            name="微信朋友圈点赞",
            description="打开微信朋友圈并给多条帖子点赞",
            code='''
step("打开微信")
step("点击发现")
step("点击朋友圈")
for i in range(count):
    step(f"点击第{i+1}条的点赞")
    step("向下滑动")
''',
            tags=["微信", "社交", "点赞"]
        )
        print(f"✅ 注册: 微信朋友圈点赞 ({skill1_id})")
        
        skill2_id = registry.register(
            name="抖音刷视频",
            description="打开抖音自动刷视频并点赞",
            code='''
step("打开抖音")
for i in range(count):
    step("观看当前视频")
    step("双击点赞")
    step("向上滑动")
''',
            tags=["抖音", "视频", "点赞"]
        )
        print(f"✅ 注册: 抖音刷视频 ({skill2_id})")
        
        skill3_id = registry.register(
            name="计算器加法",
            description="使用计算器进行简单加法计算",
            code='''
step("打开计算器")
step("点击数字1")
step("点击加号")
step("点击数字1")
step("点击等号")
''',
            tags=["计算器", "工具"]
        )
        print(f"✅ 注册: 计算器加法 ({skill3_id})")
        
        print(f"\n总技能数: {len(registry.list_all())}")
        
        # 搜索测试
        print("\n--- 搜索测试 ---")
        
        results = registry.search("点赞")
        print(f"搜索 '点赞': 找到 {len(results)} 个结果")
        for skill in results:
            print(f"  - {skill.name} (tags: {skill.tags})")
        
        results = registry.search("微信朋友圈")
        print(f"\n搜索 '微信朋友圈': 找到 {len(results)} 个结果")
        for skill in results:
            print(f"  - {skill.name}")
        
        results = registry.search("计算", tags=["工具"])
        print(f"\n搜索 '计算' + 标签 '工具': 找到 {len(results)} 个结果")
        for skill in results:
            print(f"  - {skill.name}")
        
        # 获取技能
        print("\n--- 获取技能 ---")
        skill = registry.get(skill1_id)
        if skill:
            print(f"获取 {skill1_id}: {skill.name}")
            print(f"  描述: {skill.description}")
            print(f"  标签: {skill.tags}")
        
        # 更新统计
        print("\n--- 更新统计 ---")
        registry.update_stats(skill1_id, success=True)
        registry.update_stats(skill1_id, success=True)
        registry.update_stats(skill1_id, success=False)
        
        skill = registry.get(skill1_id)
        print(f"使用次数: {skill.usage_count}")
        print(f"成功率: {skill.success_rate:.2f}")
        
        # 导出
        print("\n--- 导出测试 ---")
        export_path = os.path.join(temp_dir, "export.json")
        registry.export(export_path)
        print(f"导出到: {export_path}")
        
        # 验证索引文件
        print("\n--- 验证存储 ---")
        files = os.listdir(temp_dir)
        print(f"存储目录文件: {files}")
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)
    
    print("\n=== 测试完成 ===")
