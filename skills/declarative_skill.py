#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
声明式技能模型 (Declarative Skill)
借鉴 Claude Skills 的设计理念

核心特点:
- 自然语言定义行为
- 语义触发匹配
- 技能组合与继承
- 偏好/约束声明
"""

import json
import hashlib
import logging
from typing import Optional, List, Dict, Any, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from enum import Enum


logger = logging.getLogger(__name__)


class SkillType(Enum):
    """技能类型"""
    ATOMIC = "atomic"          # 原子技能（不可分解）
    COMPOSITE = "composite"    # 组合技能（引用其他技能）
    TEMPLATE = "template"      # 模板技能（需要参数填充）


@dataclass
class TriggerCondition:
    """触发条件"""
    keywords: List[str] = field(default_factory=list)    # 关键词触发
    intents: List[str] = field(default_factory=list)     # 意图触发
    contexts: List[str] = field(default_factory=list)    # 上下文触发
    
    def matches(self, query: str) -> float:
        """计算匹配分数（0-1）"""
        score = 0.0
        query_lower = query.lower()
        
        # 关键词匹配
        for kw in self.keywords:
            if kw.lower() in query_lower:
                score += 0.3
        
        # 意图匹配（简单实现，可升级为向量相似度）
        for intent in self.intents:
            if any(word in query_lower for word in intent.lower().split()):
                score += 0.2
        
        return min(score, 1.0)


@dataclass
class Preference:
    """行为偏好"""
    name: str
    description: str
    enabled: bool = True
    priority: int = 0  # 优先级，数字越大越重要


@dataclass
class DeclarativeSkill:
    """声明式技能定义
    
    Claude Skills 风格的技能模型，使用自然语言描述行为。
    
    Usage:
        skill = DeclarativeSkill(
            name="微信朋友圈点赞",
            description="帮助用户给微信朋友圈的帖子点赞",
            trigger=TriggerCondition(
                keywords=["朋友圈", "点赞"],
                intents=["给朋友圈点赞", "支持一下好友"]
            ),
            behavior='''
            目标：给朋友圈帖子点赞
            
            步骤：
            1. 确认用户想要点赞的数量（默认3条）
            2. 打开微信应用
            3. 进入发现页面
            4. 进入朋友圈
            5. 对每条帖子：
               - 找到点赞按钮
               - 如果未点赞，则点击点赞
               - 如果已点赞，则跳过
            6. 完成后返回确认
            
            注意事项：
            - 操作前先截图确认当前界面
            - 每步完成后验证状态
            - 遇到异常暂停并询问用户
            ''',
            preferences=[
                Preference("确认模式", "每个重要操作前询问用户", enabled=False),
                Preference("截图记录", "保存每步操作的截图", enabled=True),
            ],
            requires=["打开应用", "滚动列表"],  # 依赖的其他技能
        )
    """
    
    # 基本信息
    id: str = ""
    name: str = ""
    description: str = ""
    
    # 触发条件
    trigger: TriggerCondition = field(default_factory=TriggerCondition)
    
    # 行为描述（自然语言）
    behavior: str = ""
    
    # 参数定义
    parameters: Dict[str, Any] = field(default_factory=dict)
    # 示例: {"count": {"type": "int", "default": 3, "description": "点赞数量"}}
    
    # 偏好设置
    preferences: List[Preference] = field(default_factory=list)
    
    # 约束条件
    constraints: List[str] = field(default_factory=list)
    # 示例: ["不要点赞广告帖子", "跳过已点赞的内容"]
    
    # 依赖技能
    requires: List[str] = field(default_factory=list)
    
    # 类型
    skill_type: SkillType = SkillType.ATOMIC
    
    # 元数据
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"
    created_at: str = ""
    updated_at: str = ""
    author: str = "user"
    
    # 执行统计
    usage_count: int = 0
    success_rate: float = 1.0
    
    # 关联的过程式代码（可选，用于缓存）
    cached_code: Optional[str] = None
    
    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
    
    def _generate_id(self) -> str:
        """生成技能ID"""
        content = f"{self.name}:{self.behavior[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def matches(self, query: str) -> float:
        """检查是否匹配用户查询
        
        Returns:
            匹配分数 0-1
        """
        score = self.trigger.matches(query)
        
        # 名称匹配加分
        if self.name.lower() in query.lower():
            score += 0.3
        
        # 描述匹配加分
        desc_words = set(self.description.lower().split())
        query_words = set(query.lower().split())
        overlap = len(desc_words & query_words)
        if overlap > 0:
            score += overlap * 0.1
        
        return min(score, 1.0)
    
    def get_enabled_preferences(self) -> List[Preference]:
        """获取启用的偏好"""
        return [p for p in self.preferences if p.enabled]
    
    def to_prompt(self) -> str:
        """转换为 LLM 可用的 Prompt 格式"""
        prompt_parts = [
            f"## 技能: {self.name}",
            f"\n### 描述\n{self.description}",
            f"\n### 行为规范\n{self.behavior}",
        ]
        
        if self.parameters:
            params_str = "\n".join([
                f"- {k}: {v.get('description', '')} (默认: {v.get('default', 'N/A')})"
                for k, v in self.parameters.items()
            ])
            prompt_parts.append(f"\n### 参数\n{params_str}")
        
        if self.constraints:
            constraints_str = "\n".join([f"- {c}" for c in self.constraints])
            prompt_parts.append(f"\n### 约束条件\n{constraints_str}")
        
        enabled_prefs = self.get_enabled_preferences()
        if enabled_prefs:
            prefs_str = "\n".join([f"- {p.name}: {p.description}" for p in enabled_prefs])
            prompt_parts.append(f"\n### 偏好设置\n{prefs_str}")
        
        return "\n".join(prompt_parts)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        data = asdict(self)
        data['skill_type'] = self.skill_type.value
        data['trigger'] = asdict(self.trigger)
        data['preferences'] = [asdict(p) for p in self.preferences]
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DeclarativeSkill':
        """从字典创建"""
        # 处理嵌套类型
        if 'trigger' in data and isinstance(data['trigger'], dict):
            data['trigger'] = TriggerCondition(**data['trigger'])
        if 'preferences' in data:
            data['preferences'] = [
                Preference(**p) if isinstance(p, dict) else p 
                for p in data['preferences']
            ]
        if 'skill_type' in data and isinstance(data['skill_type'], str):
            data['skill_type'] = SkillType(data['skill_type'])
        return cls(**data)


class DeclarativeSkillRegistry:
    """声明式技能注册表
    
    管理声明式技能，支持语义匹配和技能组合。
    """
    
    INDEX_FILE = "declarative_index.json"
    
    def __init__(self, storage_path: str = "./skill_store"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.skills: Dict[str, DeclarativeSkill] = {}
        self._dependency_graph: Dict[str, Set[str]] = {}  # 依赖图
        
        self._load_index()
    
    def _load_index(self):
        """加载索引"""
        index_path = self.storage_path / self.INDEX_FILE
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for skill_data in data.get('skills', []):
                        skill = DeclarativeSkill.from_dict(skill_data)
                        self.skills[skill.id] = skill
                        self._update_dependency_graph(skill)
                logger.info(f"[DeclarativeRegistry] Loaded {len(self.skills)} skills")
            except Exception as e:
                logger.error(f"[DeclarativeRegistry] Load error: {e}")
    
    def _save_index(self):
        """保存索引"""
        index_path = self.storage_path / self.INDEX_FILE
        data = {
            'version': '2.0',
            'type': 'declarative',
            'updated_at': datetime.now().isoformat(),
            'skills': [s.to_dict() for s in self.skills.values()]
        }
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _update_dependency_graph(self, skill: DeclarativeSkill):
        """更新依赖图"""
        self._dependency_graph[skill.id] = set(skill.requires)
    
    def register(self, skill: DeclarativeSkill) -> str:
        """注册技能"""
        self.skills[skill.id] = skill
        self._update_dependency_graph(skill)
        self._save_index()
        logger.info(f"[DeclarativeRegistry] Registered: {skill.name} ({skill.id})")
        return skill.id
    
    def get(self, skill_id: str) -> Optional[DeclarativeSkill]:
        """获取技能"""
        return self.skills.get(skill_id)
    
    def find_by_name(self, name: str) -> Optional[DeclarativeSkill]:
        """按名称查找"""
        for skill in self.skills.values():
            if skill.name == name:
                return skill
        return None
    
    def match_intent(self, query: str, threshold: float = 0.3) -> List[DeclarativeSkill]:
        """语义意图匹配
        
        Args:
            query: 用户查询
            threshold: 最低匹配分数
            
        Returns:
            匹配的技能列表（按分数排序）
        """
        results = []
        for skill in self.skills.values():
            score = skill.matches(query)
            if score >= threshold:
                results.append((skill, score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in results]
    
    def get_dependencies(self, skill_id: str) -> List[DeclarativeSkill]:
        """获取技能的所有依赖（递归）"""
        visited = set()
        result = []
        
        def dfs(sid: str):
            if sid in visited:
                return
            visited.add(sid)
            
            skill = self.find_by_name(sid) or self.get(sid)
            if skill:
                for dep in skill.requires:
                    dfs(dep)
                result.append(skill)
        
        dfs(skill_id)
        return result[:-1]  # 排除自身
    
    def compose_skill(
        self,
        name: str,
        component_names: List[str],
        description: str = ""
    ) -> DeclarativeSkill:
        """组合多个技能为新技能"""
        behaviors = []
        all_requires = set()
        all_tags = set()
        
        for comp_name in component_names:
            comp = self.find_by_name(comp_name)
            if comp:
                behaviors.append(f"### {comp.name}\n{comp.behavior}")
                all_requires.update(comp.requires)
                all_tags.update(comp.tags)
        
        composite = DeclarativeSkill(
            name=name,
            description=description or f"组合技能: {', '.join(component_names)}",
            behavior="\n\n".join(behaviors),
            requires=list(all_requires),
            tags=list(all_tags),
            skill_type=SkillType.COMPOSITE
        )
        
        return composite
    
    def list_all(self) -> List[DeclarativeSkill]:
        """列出所有技能"""
        return list(self.skills.values())


# ========== 预定义的基础技能 ==========

BUILTIN_SKILLS = [
    DeclarativeSkill(
        name="打开应用",
        description="打开指定的手机应用",
        trigger=TriggerCondition(
            keywords=["打开", "启动", "进入"],
            intents=["打开应用", "启动程序"]
        ),
        behavior="""
目标：打开指定的手机应用

步骤：
1. 返回手机桌面
2. 寻找目标应用图标
3. 如果在当前页面找不到，左右滑动查找
4. 点击应用图标
5. 等待应用启动完成
6. 验证应用已打开

参数：
- app_name: 要打开的应用名称
""",
        parameters={
            "app_name": {"type": "str", "description": "应用名称", "required": True}
        },
        tags=["基础", "导航"],
        skill_type=SkillType.TEMPLATE
    ),
    
    DeclarativeSkill(
        name="滚动列表",
        description="在列表中滚动浏览内容",
        trigger=TriggerCondition(
            keywords=["滚动", "翻页", "下一页", "向下"],
            intents=["滚动页面", "查看更多"]
        ),
        behavior="""
目标：在列表或页面中滚动

步骤：
1. 确认当前界面是可滚动的
2. 执行滚动手势（向上滑动查看更多）
3. 等待新内容加载
4. 验证滚动成功（内容已更新）

参数：
- direction: 滚动方向（up/down/left/right）
- distance: 滚动距离（小/中/大）
""",
        parameters={
            "direction": {"type": "str", "default": "up", "description": "滚动方向"},
            "distance": {"type": "str", "default": "中", "description": "滚动距离"}
        },
        tags=["基础", "导航"],
        skill_type=SkillType.TEMPLATE
    ),
    
    DeclarativeSkill(
        name="微信朋友圈点赞",
        description="给微信朋友圈的帖子点赞",
        trigger=TriggerCondition(
            keywords=["朋友圈", "点赞", "微信"],
            intents=["给朋友圈点赞", "支持好友", "点赞朋友圈"]
        ),
        behavior="""
目标：给微信朋友圈帖子点赞

前置条件：
- 手机已解锁
- 微信已登录

步骤：
1. 打开微信应用
2. 点击底部"发现"标签
3. 点击"朋友圈"入口
4. 等待朋友圈加载完成
5. 对于每条要点赞的帖子：
   a. 找到帖子的互动区域
   b. 点击评论图标展开操作菜单
   c. 点击"赞"按钮
   d. 验证点赞成功（爱心变红）
   e. 向上滑动到下一条
6. 完成指定数量后停止
7. 返回确认结果

注意事项：
- 如果帖子已点赞（爱心是红色），跳过
- 广告帖子建议跳过
- 每次点赞后短暂等待，避免操作过快
""",
        parameters={
            "count": {"type": "int", "default": 3, "description": "点赞数量"}
        },
        constraints=[
            "不要重复点赞已点过的帖子",
            "跳过广告内容",
            "操作间隔不少于1秒"
        ],
        preferences=[
            Preference("确认模式", "点赞前询问用户确认", enabled=False),
            Preference("截图记录", "保存操作截图", enabled=True),
        ],
        requires=["打开应用", "滚动列表"],
        tags=["微信", "社交", "点赞"],
        skill_type=SkillType.COMPOSITE
    ),
]


def load_builtin_skills(registry: DeclarativeSkillRegistry):
    """加载内置技能"""
    for skill in BUILTIN_SKILLS:
        if not registry.find_by_name(skill.name):
            registry.register(skill)
    logger.info(f"[Builtin] Loaded {len(BUILTIN_SKILLS)} builtin skills")


# ========== 测试代码 ==========

if __name__ == '__main__':
    import tempfile
    import shutil
    
    print("=== 声明式技能系统测试 ===\n")
    
    temp_dir = tempfile.mkdtemp()
    print(f"临时目录: {temp_dir}\n")
    
    try:
        registry = DeclarativeSkillRegistry(temp_dir)
        
        # 加载内置技能
        print("--- 加载内置技能 ---")
        load_builtin_skills(registry)
        print(f"已注册 {len(registry.list_all())} 个技能\n")
        
        # 意图匹配测试
        print("--- 意图匹配测试 ---")
        test_queries = [
            "帮我给朋友圈点个赞",
            "给好友的动态支持一下",
            "打开微信",
            "向下翻一翻",
            "刷抖音",  # 应该没有匹配
        ]
        
        for query in test_queries:
            matches = registry.match_intent(query)
            if matches:
                print(f"查询: '{query}'")
                print(f"  匹配: {[s.name for s in matches]}")
            else:
                print(f"查询: '{query}' -> 无匹配")
        
        # 技能依赖
        print("\n--- 技能依赖 ---")
        wechat_skill = registry.find_by_name("微信朋友圈点赞")
        if wechat_skill:
            deps = registry.get_dependencies(wechat_skill.id)
            print(f"'{wechat_skill.name}' 依赖: {[d.name for d in deps]}")
        
        # 转换为 Prompt
        print("\n--- Prompt 格式 ---")
        if wechat_skill:
            prompt = wechat_skill.to_prompt()
            print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
        
        # 自定义技能
        print("\n--- 创建自定义技能 ---")
        custom_skill = DeclarativeSkill(
            name="抖音点赞",
            description="给抖音视频点赞",
            trigger=TriggerCondition(
                keywords=["抖音", "点赞", "双击"],
                intents=["给抖音点赞", "喜欢这个视频"]
            ),
            behavior="""
目标：给抖音视频点赞

步骤：
1. 打开抖音
2. 双击屏幕中央点赞
3. 验证红心出现
""",
            tags=["抖音", "社交", "点赞"]
        )
        registry.register(custom_skill)
        print(f"✅ 注册: {custom_skill.name}")
        
        # 再次匹配
        matches = registry.match_intent("刷抖音点赞")
        print(f"查询 '刷抖音点赞' -> {[s.name for s in matches]}")
        
    finally:
        shutil.rmtree(temp_dir)
    
    print("\n=== 测试完成 ===")
