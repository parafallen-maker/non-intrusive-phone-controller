# 三层架构实现文档

## 🎯 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│  L1 策略层 (Strategy Layer)                                      │
│  - 模型: GPT-4 / Claude / glm-4-flash                           │
│  - 职责: 长程规划、逻辑编排、状态管理                            │
│  - 输出: Python 脚本 (用 for/while 调用 step())                  │
│  - 禁止: 输出任何坐标                                           │
└─────────────────────────────────────────────────────────────────┘
                    ↓ Python 代码
┌─────────────────────────────────────────────────────────────────┐
│  L2 运行时 (Runtime Layer)                                       │
│  - 组件: TaskRuntime                                            │
│  - 职责: 沙盒执行、提供 step() 接口、异常处理                    │
│  - 接口: step(goal: str) -> bool                                │
└─────────────────────────────────────────────────────────────────┘
                    ↓ step("点击搜索框")
┌─────────────────────────────────────────────────────────────────┐
│  L3 战术层 (Tactical Layer)                                      │
│  - 模型: AutoGLM (autoglm-phone)                                │
│  - 职责: Grounding (视觉定位) + 微观验证                         │
│  - 流程: 截图 → 定位坐标 → 执行 → 验证 → 重试                   │
│  - 输出: Tap(0.23, 0.67) 等精确坐标                             │
└─────────────────────────────────────────────────────────────────┘
                    ↓ 机械臂指令
┌─────────────────────────────────────────────────────────────────┐
│  驱动层 (Driver Layer)                                           │
│  - Serial / WiFi / Mock                                         │
│  - 职责: 硬件控制                                               │
└─────────────────────────────────────────────────────────────────┘
```

## 📁 文件结构

```
semantic-agent/
├── brain/
│   └── strategy_prompt.py          # L1: 策略层 Prompt 设计
├── runtime/
│   └── task_runtime_v2.py          # L2: 任务运行时沙盒
├── tactical/
│   └── autoglm_driver.py           # L3: AutoGLM 驱动封装
├── drivers/
│   ├── base_driver.py              # 驱动基类
│   ├── mock_driver.py              # Mock 驱动
│   ├── serial_driver.py            # 串口驱动
│   └── wifi_driver.py              # WiFi 驱动
├── main_v3.py                      # 主入口（集成三层）
└── tests/
    └── test_three_layers.py        # 测试脚本
```

## 🔧 核心组件

### 1. AutoGLMDriver (L3 战术层)

**职责**: 持有 Camera 和 RoboticArm，实现微观闭环

**核心方法**: `execute_step(goal: str) -> bool`

**闭环流程**:
1. **Capture**: 截图
2. **Plan**: 调用 AutoGLM API (输入截图+goal)，获取动作 (Type + Coords)
3. **Act**: 将动作转换为机械臂指令并执行
4. **Verify**: 执行后 sleep(2.0)，再次截图，调用 AutoGLM 确认
5. **Retry**: 如果失败，自动重试 1 次

**特点**:
- 内部自动重试（默认 2 次）
- 验证失败抛出 `MaxRetryError`
- 安全检查失败抛出 `SafetyError`

### 2. TaskRuntime (L2 运行时)

**职责**: 创建沙盒环境，执行 LLM 生成的代码

**核心方法**: `execute(code: str) -> Dict`

**环境准备**:
- 只注入 `step()` 函数
- 提供基本 Python 内置函数 (range, len, print 等)
- 禁止危险函数 (open, exec, import 等)

**异常处理**:
- `SafetyError` → 立即终止并报警
- `MaxRetryError` → 立即终止并报警
- 其他异常 → 捕获并返回错误信息

### 3. Strategy Prompt (L1 策略层)

**职责**: 训练 LLM 只做逻辑规划，绝不碰坐标

**核心约束**:
1. **视觉禁令**: 不知道分辨率，看不见屏幕，禁止输出坐标
2. **唯一接口**: 只能使用 `step(goal="自然语言描述")`
3. **逻辑编排**: 重复任务必须用 for/while 循环

**输出格式**: 只输出 Python 代码，不要解释或 Markdown 标记

## 🎬 工作流程

### 示例: "给前 10 条视频点赞"

#### Step 1: 用户输入
```
用户: "给前 10 条视频点赞"
```

#### Step 2: L1 策略层生成代码
```python
# LLM (glm-4-flash) 输出:
step('打开短视频应用')

for i in range(10):
    step('点赞当前视频')
    step('滑动到下一个视频')
```

#### Step 3: L2 运行时执行
```python
# TaskRuntime 逐行执行代码
# 每次调用 step() 透传给 AutoGLMDriver
```

#### Step 4: L3 战术层处理每个 step()

以 `step('点赞当前视频')` 为例:

1. **Capture**: 截图当前界面
2. **Plan**: 
   ```
   AutoGLM 输入: 截图 + "点赞当前视频"
   AutoGLM 输出: Tap(0.85, 0.45) - 点击点赞按钮
   ```
3. **Act**: 机械臂执行 Tap(0.85, 0.45)
4. **Verify**: 
   - 等待 2 秒
   - 再次截图
   - AutoGLM 判断: "点赞按钮已变红，操作成功"
5. **Return**: 返回 True

#### Step 5: 循环执行
```
step('打开短视频应用')     → AutoGLM → Tap(0.5, 0.3)  → ✅
step('点赞当前视频')       → AutoGLM → Tap(0.85, 0.45) → ✅
step('滑动到下一个视频')   → AutoGLM → Swipe(0.5, 0.7, 0.5, 0.3) → ✅
step('点赞当前视频')       → AutoGLM → Tap(0.85, 0.45) → ✅
...
```

## 🔑 关键设计

### 1. 坐标控制权移交

❌ **旧逻辑**: LLM 分析截图 → LLM 输出 tap(500, 800) → 机械臂执行

✅ **新逻辑**: LLM 禁止接触坐标 → LLM 输出 step("点击搜索框") → AutoGLM 分析截图并输出 tap(500, 800) → 机械臂执行

**原因**: 通用 LLM 对截图的坐标预测能力远弱于 AutoGLM

### 2. 微观验证权移交

❌ **旧逻辑**: LLM 规划一步 → 机械臂动 → 截图回传 LLM → LLM 问"成功了吗？"

✅ **新逻辑**: 截图回传给 AutoGLM。AutoGLM 在 step() 函数内部自闭环：操作后自动再看一眼，确认 UI 变了才返回 True

**原因**: 减少与云端 LLM 的网络交互（降低延迟），让"手眼协调"在本地闭环

### 3. 逻辑容器引入

❌ **旧逻辑**: 线性对话。用户说一句，Agent 做一步

✅ **新逻辑**: 代码即行动。LLM 针对复杂任务生成 Python 脚本，利用 Python 的 for/while 循环来控制 AutoGLM 的多次调用

**原因**: 复杂任务需要状态管理，代码比对话更适合表达逻辑

## 🚀 使用方式

### 方式 1: 命令行交互

```bash
cd semantic-agent
python main_v3.py
```

```
🎯 任务: 给前 10 条视频点赞

[LLM] 📝 Plan - 生成执行脚本...
[LLM] ✅ 生成的代码:
  1 | step('打开短视频应用')
  2 | for i in range(10):
  3 |     step('点赞当前视频')
  4 |     step('滑动到下一个视频')

[Runtime] ⚙️  Execute - 开始执行...
[AutoGLMDriver] 步骤 #1: 打开短视频应用
[AutoGLMDriver] 📸 a. Capture - 获取截图
[AutoGLMDriver] 🧠 b. Plan - 调用 AutoGLM 分析
...
```

### 方式 2: 演示模式

```bash
python main_v3.py --demo
```

### 方式 3: API 调用

```python
from main_v3 import SemanticAgent
from drivers.mock_driver import MockDriver

driver = MockDriver()
agent = SemanticAgent(
    zhipuai_api_key="your_key",
    driver=driver
)

result = agent.execute_task("打开微信，给张三发消息'晚上吃饭'")
print(result)
```

## 🧪 测试

```bash
cd semantic-agent
python tests/test_three_layers.py
```

测试覆盖:
- Phase 1: AutoGLMDriver 单独测试
- Phase 2: TaskRuntime 单独测试
- Phase 3: 策略层 Prompt 验证
- Phase 4: 完整集成测试

## 📊 性能指标

| 指标 | 说明 |
|------|------|
| `total_steps` | 执行的 step() 总数 |
| `total_retries` | AutoGLM 重试次数 |
| `success_rate` | 成功率 = (成功步骤 / 总步骤) |

## ⚠️ 注意事项

1. **API Key**: 需要配置 `ZHIPUAI_API_KEY` 环境变量
2. **模型选择**: 
   - 策略层推荐: `glm-4-flash` (快速且便宜)
   - 战术层必须: `autoglm-phone` (专用手机控制)
3. **重试次数**: 默认 2 次，可在 AutoGLMDriver 初始化时调整
4. **验证延迟**: 默认 2 秒，可根据实际界面响应速度调整

## 🔮 未来优化

1. **验证智能化**: AutoGLM 验证改用专门的 prompt 模板
2. **上下文记忆**: 在 step() 中传递前序操作的上下文
3. **多模态输入**: 支持语音指令
4. **技能学习**: 记录成功的操作轨迹，供后续参考
