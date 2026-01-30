#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Skills 模块协议定义
定义标准接口，支持本地/远程实现的解耦
"""

from typing import Optional, List, Dict, Any, Tuple, Protocol, runtime_checkable
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import json


# ============================================================
# 枚举类型
# ============================================================

class SkillType(Enum):
    """技能类型"""
    PROCEDURAL = "procedural"    # 过程式（step代码）
    DECLARATIVE = "declarative"  # 声明式（自然语言）
    TEMPLATE = "template"        # 模板（需参数填充）


class SkillSource(Enum):
    """技能来源"""
    MANUAL = "manual"           # 手动创建
    DISTILLED = "distilled"     # 蒸馏生成
    IMPORTED = "imported"       # 外部导入
    SYNCED = "synced"           # 云端同步


# ============================================================
# 数据模型
# ============================================================

@dataclass
class Skill:
    """技能定义（过程式）"""
    id: str
    name: str
    description: str
    code: str = ""  # 技能代码（可选，声明式技能可为空）
    tags: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    use_count: int = 0       # 使用次数
    success_count: int = 0   # 成功次数
    created_at: str = ""
    updated_at: str = ""
    source: str = "manual"
    version: int = 1
    device_id: Optional[str] = None  # 来源设备
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.use_count == 0:
            return 1.0
        return self.success_count / self.use_count
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Skill':
        return cls(**data)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Skill':
        return cls.from_dict(json.loads(json_str))


@dataclass
class TriggerCondition:
    """触发条件"""
    keywords: List[str] = field(default_factory=list)
    intents: List[str] = field(default_factory=list)
    contexts: List[str] = field(default_factory=list)
    
    def matches(self, query: str) -> float:
        """计算匹配分数（0-1）"""
        score = 0.0
        query_lower = query.lower()
        
        for kw in self.keywords:
            if kw.lower() in query_lower:
                score += 0.3
        
        for intent in self.intents:
            if any(word in query_lower for word in intent.lower().split()):
                score += 0.2
        
        return min(score, 1.0)


@dataclass
class DeclarativeSkill:
    """声明式技能"""
    id: str
    name: str
    description: str
    trigger: TriggerCondition
    behavior: str  # 自然语言行为描述
    parameters: Dict[str, Any] = field(default_factory=dict)
    preferences: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    source: str = "manual"
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['trigger'] = asdict(self.trigger)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeclarativeSkill':
        trigger_data = data.pop('trigger', {})
        trigger = TriggerCondition(**trigger_data)
        return cls(trigger=trigger, **data)


@dataclass
class ExecutionTrace:
    """执行轨迹"""
    instruction: str
    code: str
    steps: List[str]
    success: bool
    timestamp: str = ""
    duration: float = 0.0
    device_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class SkillMatch:
    """技能匹配结果"""
    skill: Skill
    score: float
    matched_field: str = "semantic"  # semantic/keyword/name/description/tags


# ============================================================
# 协议定义（接口）
# ============================================================

@runtime_checkable
class SkillStore(Protocol):
    """技能存储协议 - 本地/远程统一接口"""
    
    def save(self, skill: Skill) -> str:
        """保存技能，返回 ID"""
        ...
    
    def get(self, skill_id: str) -> Optional[Skill]:
        """获取技能"""
        ...
    
    def delete(self, skill_id: str) -> bool:
        """删除技能"""
        ...
    
    def list_all(self) -> List[Skill]:
        """列出所有技能"""
        ...
    
    def search(self, query: str, limit: int = 10) -> List[SkillMatch]:
        """搜索技能"""
        ...
    
    def update_stats(self, skill_id: str, success: bool) -> None:
        """更新使用统计"""
        ...


@runtime_checkable
class SkillMatcher(Protocol):
    """技能匹配器协议"""
    
    def index(self, skill_id: str, text: str) -> None:
        """索引技能"""
        ...
    
    def match(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """匹配技能，返回 [(skill_id, score)]"""
        ...
    
    def remove(self, skill_id: str) -> None:
        """移除索引"""
        ...


@runtime_checkable  
class SkillDistillerProtocol(Protocol):
    """技能蒸馏器协议"""
    
    def distill(self, trace: ExecutionTrace) -> Optional[Skill]:
        """从执行轨迹蒸馏技能"""
        ...
    
    def should_distill(self, trace: ExecutionTrace) -> bool:
        """判断是否应该蒸馏"""
        ...


# ============================================================
# 同步相关
# ============================================================

@dataclass
class SyncEvent:
    """同步事件"""
    event_type: str  # create/update/delete
    skill_id: str
    skill_data: Optional[Dict[str, Any]]
    timestamp: str
    device_id: str


@dataclass
class SyncStatus:
    """同步状态"""
    last_sync: str
    pending_uploads: int
    pending_downloads: int
    conflicts: int
