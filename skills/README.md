# Skills 模块

独立的技能管理系统，支持本地/云端存储，可跨设备共享技能库。

## 特性

- 🔌 **解耦设计**：基于协议的接口设计，支持本地/远程实现切换
- ☁️ **云端同步**：自动同步到云端，多设备共享技能库
- 🔍 **语义搜索**：基于向量嵌入的语义匹配
- 📊 **使用统计**：记录技能使用次数和成功率
- 🔄 **冲突处理**：智能处理多设备同步冲突

## 架构

```
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
```

## 快速开始

### 仅本地模式

```python
from skills import SkillManager, Skill

# 创建管理器
manager = SkillManager.create_local("./skills")

# 保存技能
skill = Skill(
    id="wechat_post",
    name="发朋友圈",
    description="在微信中发送一条朋友圈动态",
    code="""
step("点击发现")
step("点击朋友圈")
step("点击右上角相机图标")
step("输入文字内容")
step("点击发表")
""",
    tags=["微信", "社交"]
)
manager.save(skill)

# 搜索技能
matches = manager.search("发朋友圈")
for match in matches:
    print(f"{match.skill.name}: {match.score:.2f}")

# 获取最佳匹配
best = manager.get_best_match("给张三朋友圈点赞")
if best:
    print(f"执行技能: {best.name}")
```

### 云端同步模式

```python
from skills import SkillManager

# 创建带云端同步的管理器
manager = SkillManager.create_cloud(
    local_dir="./skills",
    api_url="https://skills.example.com/api/v1",
    api_key="sk-xxx",
    device_id="device-001"
)

# 使用方式与本地相同，自动同步到云端
skill = manager.get_best_match("发微信")
```

### 环境变量配置

```bash
export SKILL_API_URL="https://skills.example.com/api/v1"
export SKILL_API_KEY="sk-xxx"
export DEVICE_ID="device-001"
```

```python
from skills import init_skill_manager

# 自动从环境变量读取配置
manager = init_skill_manager(local_dir="./skills")
```

## 核心 API

### SkillManager

统一的技能管理入口。

```python
# 工厂方法
manager = SkillManager.create_local(base_dir)           # 仅本地
manager = SkillManager.create_cloud(local_dir, ...)     # 云端同步
manager = SkillManager.create_mock()                    # 测试用

# 基础操作
skill_id = manager.save(skill)          # 保存
skill = manager.get(skill_id)           # 获取
manager.delete(skill_id)                # 删除
skills = manager.list_all()             # 列出所有

# 搜索
matches = manager.search("发朋友圈", limit=10, min_score=0.5)
best = manager.get_best_match("发朋友圈", min_score=0.7)

# 使用统计
manager.record_usage(skill_id, success=True)

# 同步控制
status = manager.sync()                 # 手动同步
status = manager.get_sync_status()      # 获取状态

# 健康检查
health = manager.health_check()

# 生命周期
manager.shutdown()
# 或使用 context manager
with SkillManager.create_local("./skills") as manager:
    ...
```

### Skill 数据模型

```python
from skills import Skill

skill = Skill(
    id="unique_id",              # 唯一标识
    name="技能名称",              # 名称
    description="技能描述",       # 描述
    code="step('...')",          # 技能代码
    tags=["标签1", "标签2"],      # 标签
    parameters={"key": "value"}, # 参数
)

# 访问属性
print(skill.use_count)          # 使用次数
print(skill.success_count)      # 成功次数
print(skill.success_rate)       # 成功率

# 序列化
data = skill.to_dict()
json_str = skill.to_json()

# 反序列化
skill = Skill.from_dict(data)
skill = Skill.from_json(json_str)
```

## 云端部署

### 启动服务

```bash
cd skills
pip install fastapi uvicorn
python cloud_service.py
```

### API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | /health | 健康检查 |
| GET | /skills | 列出所有技能 |
| GET | /skills/{id} | 获取单个技能 |
| POST | /skills | 创建技能 |
| PUT | /skills/{id} | 更新技能 |
| DELETE | /skills/{id} | 删除技能 |
| POST | /skills/search | 搜索技能 |
| POST | /skills/sync | 同步技能 |
| POST | /skills/stats | 更新统计 |

### Docker 部署

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY skills/ ./skills/

ENV SKILL_API_KEY=your-api-key
EXPOSE 8080

CMD ["uvicorn", "skills.cloud_service:app", "--host", "0.0.0.0", "--port", "8080"]
```

## 自定义扩展

### 实现自定义存储

```python
from skills.protocols import SkillStore, Skill, SkillMatch, SyncStatus
from typing import Optional, List

class MyCustomStore(SkillStore):
    """自定义存储实现"""
    
    def save(self, skill: Skill) -> str:
        # 实现保存逻辑
        ...
    
    def get(self, skill_id: str) -> Optional[Skill]:
        # 实现获取逻辑
        ...
    
    def delete(self, skill_id: str) -> bool:
        # 实现删除逻辑
        ...
    
    def list_all(self) -> List[Skill]:
        # 实现列表逻辑
        ...
    
    def search(self, query: str, limit: int = 10) -> List[SkillMatch]:
        # 实现搜索逻辑
        ...
    
    def update_stats(self, skill_id: str, success: bool) -> None:
        # 实现统计更新
        ...
    
    def get_sync_status(self) -> SyncStatus:
        # 返回同步状态
        ...

# 使用自定义存储
from skills import SkillManager, SkillSyncManager

custom_store = MyCustomStore()
sync_manager = SkillSyncManager(custom_store)
manager = SkillManager(custom_store, None, None, auto_sync=False)
```

### 集成技能蒸馏器

```python
from skills.protocols import SkillDistillerProtocol

class MyDistiller(SkillDistillerProtocol):
    def distill(self, task: str, trace) -> Optional[Skill]:
        # 从执行轨迹蒸馏技能
        ...

manager = SkillManager.create_local(
    base_dir="./skills",
    distiller=MyDistiller()
)

# 蒸馏技能
skill = manager.distill(task="发朋友圈", trace=execution_trace, success=True)
```

## 文件结构

```
skills/
├── __init__.py          # 模块入口和导出
├── protocols.py         # 协议定义（接口）
├── local_store.py       # 本地文件存储
├── remote_store.py      # 远程 API 客户端
├── sync_manager.py      # 同步管理器
├── skill_manager.py     # 统一管理器
├── cloud_service.py     # 云端 FastAPI 服务
└── README.md            # 本文档
```

## 测试

```bash
cd semantic-agent
python3 tests/test_skills_module.py
```

## 版本历史

- **v2.0.0** - 完全重构，支持云端同步
  - 新增 SkillManager 统一管理器
  - 新增 SyncManager 同步管理
  - 新增 RemoteSkillStore 云端存储
  - 基于协议的解耦设计
  
- **v1.0.0** - 初始版本
  - 基础技能注册和搜索
  - 本地文件存储
