# Semantic Agent - 语义容器架构

基于**语义容器架构**的物理Agent系统，实现 Brain (LLM) + Tactical (AutoGLM) + Hardware 的双脑协作。

## 🎯 项目特点

- **双脑架构**：战略层LLM生成Python逻辑代码，战术层AutoGLM处理视觉感知与执行
- **多硬件支持**：统一驱动抽象层，支持串口机械臂和WiFi/ESP32-S3
- **安全第一**：`@safe_guard` 装饰器实施物理边界检查，防止危险动作
- **Code as Action**：逻辑与执行完全解耦，LLM只写业务流程

## 📁 项目结构

```
semantic-agent/
├── drivers/              # 硬件驱动层 (Task 1.1 完成)
│   ├── base_driver.py   # 抽象基类 + @safe_guard + SafetyError
│   ├── serial_driver.py # 串口驱动 (GRBL)
│   ├── wifi_driver.py   # WiFi驱动 (ESP32-S3)
│   └── __init__.py
├── tactical/            # 战术层 (AutoGLM)
│   ├── autoglm_client.py
│   ├── action_translator.py
│   ├── execution_engine.py
│   └── models.py
├── runtime/             # 运行时容器 (待实现)
│   └── task_runtime.py  # 沙盒执行环境
├── skills/              # 技能系统 (待实现)
│   ├── skill_registry.py
│   └── skill_distiller.py
├── static/              # Web 前端
├── main.py              # FastAPI 服务器
├── config.py            # 配置管理
└── requirements.txt
```

## ⚙️ 安装

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 ZHIPU_API_KEY
```

## 🚀 使用

### 1. 启动 Web 服务

```bash
python main.py
```

访问 http://localhost:8000

### 2. Python API 使用

```python
from drivers import WiFiDriver, SerialDriver, MockDriver

# WiFi 驱动 (ESP32-S3)
driver = WiFiDriver(device_ip="192.168.1.100")
driver.connect()
driver.tap(0.5, 0.5)  # 点击屏幕中心
driver.swipe(0.2, 0.8, 0.8, 0.2)  # 滑动
driver.screenshot()  # 截图

# 串口驱动 (GRBL)
driver = SerialDriver(port="COM3")
driver.connect()
driver.tap(0.5, 0.5)

# Mock 驱动 (测试)
driver = MockDriver()
driver.connect()
driver.tap(0.5, 0.5)  # 只记录日志，不执行
```

### 3. 安全检查测试

```python
from drivers import SafetyError

try:
    driver.tap(1.5, 0.5)  # 超出边界
except SafetyError as e:
    print(f"被阻止: {e}")
```

## ✅ 已完成 (Phase 1-5)

- [x] **Task 1.1**: 安全层 (`@safe_guard` + `SafetyError`)
- [x] **Task 1.2**: 驱动抽象 (`BaseDriver`, `SerialDriver`, `WiFiDriver`)
- [x] 战术层移植 (AutoGLM集成)
- [x] Web API 移植
- [x] 多硬件后端支持

## 🔜 待实现

- [ ] **Task 2.1**: 微观闭环 (`execute_step` with verify)
- [ ] **Task 3.1**: 运行时沙盒 (`TaskRuntime` + `exec()`)
- [ ] **Task 4**: 战略层 LLM (GPT-4/Claude 生成代码)
- [ ] **Task 5**: 技能系统 (保存/检索/蒸馏)

## 📝 核心概念

### 语义容器架构

```
用户指令 "给前3条朋友圈点赞"
    ↓
Brain (GPT-4): 生成 Python 代码
    for i in range(3):
        step("点击第{}个点赞按钮".format(i))
    ↓
Runtime: 执行代码，调用 step()
    ↓
Tactical (AutoGLM): 每个 step() 触发
    1. Capture: 截图
    2. Predict: AutoGLM 推理动作
    3. Act: 驱动机械臂
    4. Verify: 再次截图确认
    ↓
Hardware: 物理执行 (带 @safe_guard 保护)
```

### 安全守卫

所有物理动作都受 `@safe_guard` 保护：

```python
@safe_guard
def tap(self, x: float, y: float):
    # 自动检查 0.0 <= x <= 1.0
    # 自动检查 0.0 <= y <= 1.0
    # 超出范围抛出 SafetyError
    ...
```

## 🤝 贡献

欢迎提交 PR！

## 📄 License

MIT
