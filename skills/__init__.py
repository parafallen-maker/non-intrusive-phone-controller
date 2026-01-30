#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Skills 模块
============

独立的技能管理系统，支持：
- 本地/云端存储
- 多设备同步
- 语义搜索
- 技能蒸馏

设计目标：
- 解耦：可独立部署为云服务
- 共享：多设备统一技能库
- 扩展：易于添加新的存储后端

快速开始
--------

最简配置（仅本地）::

    from skills import SkillManager, Skill
    
    manager = SkillManager.create_local("./skills")
    
    # 保存技能
    skill = Skill(
        id="skill_001",
        name="发朋友圈",
        description="在微信中发送朋友圈",
        code="step('点击发现') ..."
    )
    manager.save(skill)
    
    # 搜索技能
    matches = manager.search("发朋友圈")

云端配置::

    from skills import SkillManager
    
    manager = SkillManager.create_cloud(
        local_dir="./skills",
        api_url="https://skills.example.com/api/v1",
        api_key="sk-xxx",
        device_id="device-001"
    )
    
    # 使用方式相同，自动同步

架构
----

::

    ┌─────────────────────────────────────────────────────────────┐
    │                     SkillManager                            │
    │  (统一 API: save/get/search/distill)                        │
    └─────────────────────┬───────────────────────────────────────┘
                          │
    ┌─────────────────────┴───────────────────────────────────────┐
    │                   SyncManager                               │
    │  (本地优先写入、异步同步、冲突处理)                            │
    └──────────────┬─────────────────────────┬────────────────────┘
                   │                         │
    ┌──────────────┴──────────┐ ┌────────────┴────────────────────┐
    │    LocalSkillStore      │ │      RemoteSkillStore           │
    │  (文件系统 + 嵌入缓存)    │ │   (HTTP API + 本地缓存)         │
    └─────────────────────────┘ └─────────────────────────────────┘

协议接口
--------

所有存储后端实现 ``SkillStore`` 协议::

    class SkillStore(Protocol):
        def save(self, skill: Skill) -> str: ...
        def get(self, skill_id: str) -> Optional[Skill]: ...
        def delete(self, skill_id: str) -> bool: ...
        def list_all(self) -> List[Skill]: ...
        def search(self, query: str, limit: int = 10) -> List[SkillMatch]: ...

云端部署
--------

技能服务可独立部署，提供 REST API::

    GET  /skills                 # 列出所有技能
    GET  /skills/{id}            # 获取技能
    POST /skills                 # 创建技能
    PUT  /skills/{id}            # 更新技能
    DELETE /skills/{id}          # 删除技能
    POST /skills/search          # 搜索技能
    POST /skills/sync            # 同步技能

客户端通过 ``RemoteSkillStore`` 访问。
"""

# ========== 协议和数据模型 ==========
from .protocols import (
    # 数据模型
    Skill,
    DeclarativeSkill,
    TriggerCondition,
    ExecutionTrace,
    SkillMatch,
    SyncEvent,
    SyncStatus,
    
    # 协议接口
    SkillStore,
    SkillMatcher,
    SkillDistillerProtocol,
)

# ========== 存储实现 ==========
from .local_store import (
    LocalSkillStore,
    MockLocalSkillStore,
)

from .remote_store import (
    RemoteSkillStore,
    MockRemoteSkillStore,
)

# ========== 同步管理 ==========
from .sync_manager import (
    SkillSyncManager,
    ConflictResolution,
)

# ========== 统一管理器 ==========
from .skill_manager import (
    SkillManager,
    get_default_manager,
    set_default_manager,
    init_skill_manager,
)

# ========== 向后兼容：原有组件 ==========
# 这些组件保持原有接口，同时可以与新系统集成

try:
    from .skill_registry import SkillRegistry
except ImportError:
    SkillRegistry = None

try:
    from .skill_distiller import SkillDistiller
except ImportError:
    SkillDistiller = None

try:
    from .semantic_matcher import SemanticMatcher
except ImportError:
    SemanticMatcher = None

try:
    from .declarative_skill import DeclarativeSkillDefinition
except ImportError:
    DeclarativeSkillDefinition = None

try:
    from .bidirectional_distiller import BidirectionalDistiller
except ImportError:
    BidirectionalDistiller = None

try:
    from .skill_translator import SkillTranslator
except ImportError:
    SkillTranslator = None


# ========== 版本信息 ==========
__version__ = "2.0.0"
__all__ = [
    # 核心数据模型
    "Skill",
    "DeclarativeSkill",
    "TriggerCondition",
    "ExecutionTrace",
    "SkillMatch",
    "SyncEvent",
    "SyncStatus",
    
    # 协议接口
    "SkillStore",
    "SkillMatcher",
    "SkillDistillerProtocol",
    
    # 存储实现
    "LocalSkillStore",
    "MockLocalSkillStore",
    "RemoteSkillStore",
    "MockRemoteSkillStore",
    
    # 同步管理
    "SkillSyncManager",
    "ConflictResolution",
    
    # 统一管理器
    "SkillManager",
    "get_default_manager",
    "set_default_manager",
    "init_skill_manager",
    
    # 向后兼容
    "SkillRegistry",
    "SkillDistiller",
    "SemanticMatcher",
    "DeclarativeSkillDefinition",
    "BidirectionalDistiller",
    "SkillTranslator",
]
