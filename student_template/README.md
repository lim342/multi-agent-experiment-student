# 多智能体供应链协同实验平台 — 学生端

## 实验简介

在这个实验中，你将编写 Python 程序控制多辆车辆，在 2D 地图上完成供应链运输任务。目标是：**最大化最终积分**。

供应链流程：

```
原料区（产出 A1~A4）──取货──→ 车辆 ──送货──→ 加工区（产出 B1/B2/B3）──取货──→ 车辆 ──送货──→ 用户区（订单）
```

你需要协调多辆车辆，高效地完成原料采集 → 加工投料 → 成品投递的完整供应链循环。

## 快速开始

### 1. 环境准备

```bash
# 确保已安装 Python 3.10+
python --version

# 安装依赖
pip install websockets
```

### 2. 启动服务器

在终端中运行：

```bash
python server/game_server.py --port 8765
```

### 3. 启动你的 Agent

在另一个终端中运行：

```bash
python student_template/student.py
```

### 4. 打开前端可视化

在浏览器中打开 `frontend/index.html`，点击"开始"按钮启动游戏。

### 5. 一键启动（Windows）

双击 `start.bat`，自动启动所有服务。

## 文件结构

```
student_template/
├── student.py        ← 你的主代码（修改这个文件）
└── README.md         ← 本文档

sdk/
├── agent_sdk.py      ← Agent SDK（不要修改）
└── __init__.py
```

你只需要修改 `student_template/student.py`，SDK 文件不要动。

## 编写你的策略

### 基本框架

```python
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.agent_sdk import AgentSDK

SERVER_URL = "ws://localhost:8765"
sdk = AgentSDK(SERVER_URL)


def my_strategy(state):
    """每 tick 调用一次。返回指令字典或 None。"""

    # 从 state 中提取信息
    vehicles = state.get("vehicles", {})
    zones = state.get("zones", {})
    orders = state.get("orders", [])
    current_time = state["time"]

    commands = {}

    for vid, v in vehicles.items():
        # 只给空闲的车辆分配任务
        if v["status"] != "idle":
            continue

        pos = v["position"]
        carrying = v["carrying"]

        # 你的逻辑...

    return commands


if __name__ == "__main__":
    sdk.run(my_strategy)
```

### state 数据结构

每 tick 你会收到一个完整的 `state` 字典：

```python
state = {
    "type": "state",
    "time": 12.5,                     # 当前游戏时间（秒）
    "score": 250.0,                   # 当前积分
    "status": "running",              # 游戏状态

    # ===== 所有车辆 =====
    "vehicles": {
        "v1": {
            "position": [10.0, 20.0], # 当前位置 [x, y]（米）
            "angle": 0.785,           # 朝向角度（弧度）
            "carrying": "A1",         # 携带的物品 ID，None 表示空车
            "status": "moving",       # "moving" 或 "idle"
            "speed": 20.0,            # 当前速度（米/秒）
            "max_speed": 20.0,        # 最大速度（米/秒）
            "path_preview": [[...]]   # 剩余路径点
        },
        "v2": { ... }
    },

    # ===== 所有区域 =====
    "zones": {
        "raw_a1": {
            "type": "raw_material",   # 区域类型
            "position": [10.0, 20.0], # 区域中心坐标
            "node_id": "n5",          # 所在图节点
            "inputs": [],             # 接受什么物品（可 drop）
            "outputs": ["A1"],        # 产出什么物品（可 pick）
            "items": {"A1": 1},       # 当前持有的物品
            "progress": null,         # 生产剩余时间，null 表示无进度
            "ready": true             # 是否可立即交互
        },
        "proc_b1": {
            "type": "processing",
            "inputs": ["A1", "A2", "A3"],
            "outputs": ["B1"],
            "items": {"A1": 1, "A2": 0, "A3": 0},
            "progress": 3.5,          # 加工剩余秒数
            "ready": false            # 成品未就绪
        },
        "consumer_1": {
            "type": "consumer",
            "inputs": ["B1", "B2", "B3"],
            "outputs": [],
            "ready": true,
            "order": {                # 当前订单（null 表示无订单）
                "order_id": "o1",
                "required": "B1",     # 需要的成品
                "deadline": 95.0,     # 截止时间（秒）
                "status": "pending"   # 订单状态
            }
        }
    },

    # ===== 活跃订单 =====
    "orders": [
        {"id": "o1", "consumer": "consumer_1", "product": "B1", "deadline": 95.0, "status": "pending"}
    ],

    # ===== 积分详情 =====
    "completed_orders_value": 100.0,  # 完成订单获得的积分
    "completed_orders_count": 1,      # 完成订单数量
    "drop_reward_total": 0.0,         # 投递奖励
    "collision_penalty": 5.0,         # 碰撞扣分
    "overtime_penalty": 2.5           # 超时扣分
}
```

### 区域数据查询技巧

所有区域使用统一的 `inputs`/`outputs`/`items`/`progress`/`ready` 格式，无需按类型分支：

```python
zones = state["zones"]

# 哪里可以取 A1？（outputs 包含 A1 且已就绪）
pick_a1_zones = [zid for zid, z in zones.items()
                 if "A1" in z["outputs"] and z["ready"]]

# A1 该送到哪里？（inputs 包含 A1）
drop_a1_zones = [zid for zid, z in zones.items()
                 if "A1" in z["inputs"]]

# 哪些加工区缺 A1？
need_a1 = [zid for zid, z in zones.items()
           if "A1" in z["inputs"] and z["items"].get("A1", 0) < 1]

# 哪些成品已就绪可以取？
ready_products = [zid for zid, z in zones.items()
                  if z["ready"] and z["type"] == "processing"]

# 哪些用户区有紧急订单？
urgent = sorted(
    [(zid, z["order"]) for zid, z in zones.items()
     if z.get("order") and z["order"]["status"] == "pending"],
    key=lambda x: x[1]["deadline"]
)
```

## SDK API 参考

### AgentSDK 类

```python
sdk = AgentSDK("ws://localhost:8765")
```

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `sdk.state` | `dict/null` | 最新状态快照 |
| `sdk.map_size` | `(width, height)` | 地图尺寸（米） |
| `sdk.collision_radius` | `float` | 碰撞检测半径（米） |
| `sdk.zone_interaction_radius` | `float` | 区域交互半径（米） |
| `sdk.raw_production_time` | `float` | 原料生产时间（秒） |
| `sdk.recipes` | `dict` | 所有配方信息 |
| `sdk.orders_timeout_base` | `float` | 订单超时时间（秒） |

#### 路径规划方法

##### `plan_path(start_node, end_node) → list[str]`

用 Dijkstra 算法找最短路径，返回节点 ID 列表。

```python
path_nodes = sdk.plan_path("n1", "n10")  # → ["n1", "n3", "n7", "n10"]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `start_node` | `str` | 起始节点 ID |
| `end_node` | `str` | 目标节点 ID |
| **返回** | `list[str]` | 节点 ID 列表，找不到返回 `[]` |

##### `nodes_to_points(node_ids) → list[list[float]]`

将节点 ID 列表转换为 `[x, y]` 坐标列表。

```python
points = sdk.nodes_to_points(["n1", "n10"])
# → [[10.0, 20.0], [50.0, 60.0]]
```

##### `find_nearest_node(x, y) → str | None`

找到离指定坐标最近的图节点。

```python
node = sdk.find_nearest_node(15.3, 22.1)  # → "n3"
```

#### 区域查询方法

##### `find_zones(output=None, input=None, ready=None, zone_type=None) → list[str]`

按条件查找区域，返回匹配的区域 ID 列表。

```python
# 找产出 A1 且已就绪的区域
sdk.find_zones(output="A1", ready=True)  # → ["raw_a1"]

# 找接受 A1 的区域
sdk.find_zones(input="A1")  # → ["proc_b1", "proc_b3"]

# 找所有加工区
sdk.find_zones(zone_type="processing")  # → ["proc_b1", "proc_b2", "proc_b3"]

# 找已就绪的加工区（有成品可取）
sdk.find_zones(zone_type="processing", ready=True)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `output` | `str` | 区域必须产出该物品（`outputs` 包含） |
| `input` | `str` | 区域必须接受该物品（`inputs` 包含） |
| `ready` | `bool` | 区域必须已就绪 |
| `zone_type` | `str` | 区域类型：`"raw_material"` / `"processing"` / `"consumer"` |
| **返回** | `list[str]` | 匹配的区域 ID 列表 |

##### `get_zone(zone_id) → dict | None`

获取指定区域的完整数据。

```python
zone = sdk.get_zone("proc_b1")
# → {"type": "processing", "inputs": ["A1","A2","A3"], "outputs": ["B1"], ...}
```

##### `get_zone_position(zone_id) → list[float] | None`

获取指定区域的位置坐标 `[x, y]`。

```python
pos = sdk.get_zone_position("raw_a1")  # → [10.0, 20.0]
```

#### 导航方法

##### `navigate_to(zone_id, action=None, from_position=None, speed=None) → dict | None`

生成导航到指定区域的指令。自动完成：找最近节点 → Dijkstra 最短路径 → 转坐标。

```python
# 从当前位置导航到原料区，执行取货
cmd = sdk.navigate_to("raw_a1", action="pick", from_position=[15.0, 20.0])
# → {"path": [[15.0, 20.0], [12.0, 20.0], [10.0, 20.0]], "action": {"type": "pick"}}

# 带目标区域的 drop（只在到达指定区域时触发）
cmd = sdk.navigate_to("proc_b1",
    action={"type": "drop", "target_zone": "proc_b1"},
    from_position=vehicle["position"])

# 自定义速度
cmd = sdk.navigate_to("raw_a1", action="pick", from_position=pos, speed=10.0)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `zone_id` | `str` | 目标区域 ID |
| `action` | `str/dict/None` | 动作指令（见下方说明） |
| `from_position` | `[x, y]` | 起始位置，`None` 时返回 `None` |
| `speed` | `float` | 可选，覆盖车辆速度 |
| **返回** | `dict/None` | `{"path": [...], "action": {...}}` 或 `None` |

**Action 参数格式**：

| 值 | 转换结果 | 说明 |
|----|----------|------|
| `"pick"` | `{"type": "pick"}` | 捡起产出物 |
| `"pick:ABC"` | `{"type": "pick"}` | 同上（忽略冒号后内容） |
| `"drop"` | `{"type": "drop"}` | 放下携带的物品 |
| `"abandon"` | `{"type": "abandon"}` | 丢弃携带的物品 |
| `{"type": "pick", "target_zone": "z"}` | 原样使用 | 只在到达指定区域时捡起 |
| `{"type": "drop", "target_zone": "z"}` | 原样使用 | 只在到达指定区域时放下 |
| `None` | 不包含 action | 不设置动作 |

#### 运行方法

##### `run(callback)`

启动主循环（阻塞）。callback 函数每 tick 调用一次。

```python
def my_strategy(state):
    # ... 处理逻辑 ...
    return commands  # 返回指令字典或 None

sdk.run(my_strategy)
```

##### `run_async(callback) → Thread`

非阻塞版本，在后台线程中运行。

```python
thread = sdk.run_async(my_strategy)
# 可以继续做其他事情...
thread.join()  # 等待结束
```

## 返回指令格式

你的策略函数应该返回一个字典，key 是车辆 ID，value 是指令：

```python
commands = {
    "v1": {
        "path": [[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],  # 路径点
        "action": {"type": "pick"},                             # 动作
        "speed": 15.0                                           # 可选，覆盖速度
    },
    "v2": {
        "path": [],    # 空数组 = 不切换路径，保持当前路径
        "action": null  # null = 不改变当前动作
    }
}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `path` | `[[x,y],...]` | 是 | 路径点列表。`[]` 不切换路径 |
| `action` | `dict/null` | 是 | 动作指令。`null` 不改变动作 |
| `speed` | `float` | 否 | 车辆速度（米/秒），会被限制在 `[0, max_speed]` |

**Action 类型一览**：

| type | 说明 | 额外字段 |
|------|------|----------|
| `pick` | 捡起区域产出物 | `target_zone`（可选） |
| `drop` | 放下携带的物品 | `target_zone`（可选） |
| `abandon` | 丢弃物品（任何位置） | 无 |

- 不指定 `target_zone`：路过任何匹配区域都会触发
- 指定 `target_zone`：只有到达该区域才触发

## 供应链规则详解

### 原料区

- 产出物品 A1、A2、A3、A4
- 有生产冷却时间（`raw_production_time` 秒），库存达到上限后停止生产
- 取走后开始生产下一件

### 加工区

- 接收原料，加工后产出成品
- 同一时间只加工一个订单，但可以预存下一批原料

| 成品 | 所需原料 | 加工时间 | 订单价值 |
|------|----------|----------|----------|
| B1 | A1 + A2 + A3 | 5 秒 | 100 分 |
| B2 | A3 + A4 | 5 秒 | 100 分 |
| B3 | A2 + A3 | 5 秒 | 100 分 |

- 成品待取时仍可放入新材料（预存下一批）
- 取走成品后如果材料已备齐，自动开始下一批加工

### 用户区

- 按概率随机生成订单，每个订单有截止时间（deadline）
- 订单需要的成品随机选择（B1/B2/B3）
- 将正确的成品送到对应的用户区即可完成订单

### 车辆

- 每辆车一次只能携带一件物品
- 所有车辆最大速度相同
- 车辆状态：`"idle"`（空闲）/ `"moving"`（移动中）
- 只有 `idle` 的车辆才能分配新任务

### 积分

```
总分 = 完成订单价值 + 投递奖励 - 碰撞扣分 - 超时扣分
```

| 积分项 | 说明 |
|--------|------|
| 完成订单价值 | 每个订单 = 成品对应配方的 value 值 |
| 投递奖励 | 向加工区投递原料时可能获得额外奖励 |
| 碰撞扣分 | 两车距离过近时扣分，1 秒冷却 |
| 超时扣分 | 超出 deadline 后每秒扣分，直到订单完成 |

## 策略建议

### 1. 贪心策略（入门）

模板中已提供的基础策略：每辆车根据当前状态做决策。

```python
if carrying raw material:
    → 送到需要它的加工区（drop）
elif carrying product:
    → 送到有订单的用户区（drop）
else:
    → 去取最紧急的成品或原料（pick）
```

### 2. 优化方向

以下是一些可以提升性能的方向：

- **避碰**：检测其他车辆位置，规划时避开碰撞区域
- **速度控制**：在拥挤区域减速，空旷区域加速
- **预判**：提前将原料送到即将需要的加工区
- **订单优先级**：按 deadline 排序，优先完成即将超时的订单
- **负载均衡**：均匀分配任务给所有车辆，避免某些车空闲
- **路径偏移**：在碰撞风险时微调路径，绕开其他车辆
- **并行投递**：多辆车同时运输不同的原料到同一个加工区

### 3. 常见错误

- 忘记检查 `v["status"] == "idle"`，给移动中的车辆发指令
- `from_position` 传了 `None`，导致 `navigate_to` 返回 `None`
- 不检查区域 `ready` 状态，车辆到了发现不能取货
- 不看 `orders` 列表，不知道用户区需要什么
- 所有车辆都去同一个区域，导致碰撞

## 示例代码

### 完整的最小示例

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sdk.agent_sdk import AgentSDK

sdk = AgentSDK("ws://localhost:8765")


def my_strategy(state):
    vehicles = state.get("vehicles", {})
    zones = state.get("zones", {})
    orders = state.get("orders", [])
    commands = {}

    for vid, v in vehicles.items():
        if v["status"] != "idle":
            continue

        pos = v["position"]
        carrying = v["carrying"]

        if carrying:
            # 带着东西 → 送到需要的地方
            for zid in sdk.find_zones(input=carrying):
                cmd = sdk.navigate_to(zid, action="drop", from_position=pos)
                if cmd:
                    commands[vid] = cmd
                    break
        else:
            # 空车 → 去取东西
            # 优先取成品
            for order in sorted(orders, key=lambda o: o["deadline"]):
                for zid in sdk.find_zones(output=order["product"], ready=True):
                    cmd = sdk.navigate_to(zid, action="pick", from_position=pos)
                    if cmd:
                        commands[vid] = cmd
                        break
                if vid in commands:
                    break

            # 没有成品 → 取原料
            if vid not in commands:
                for zid in sdk.find_zones(zone_type="raw_material", ready=True):
                    cmd = sdk.navigate_to(zid, action="pick", from_position=pos)
                    if cmd:
                        commands[vid] = cmd
                        break

    return commands


if __name__ == "__main__":
    sdk.run(my_strategy)
```

### 手动构建路径（不使用 navigate_to）

```python
# 如果你想完全手动控制路径
nearest = sdk.find_nearest_node(v["position"][0], v["position"][1])
target_zone = sdk.get_zone("raw_a1")
target_node = target_zone["node_id"]

path_nodes = sdk.plan_path(nearest, target_node)
path_points = sdk.nodes_to_points(path_nodes)

commands[vid] = {
    "path": path_points,
    "action": {"type": "pick", "target_zone": "raw_a1"},
    "speed": 10.0
}
```

## 调试技巧

### 1. 打印状态信息

```python
def my_strategy(state):
    print(f"Time: {state['time']:.1f}s  Score: {state['score']:.1f}")

    for vid, v in state["vehicles"].items():
        if v["carrying"]:
            print(f"  {vid}: carrying {v['carrying']} at {v['position']}")

    for order in state["orders"]:
        print(f"  Order {order['id']}: need {order['product']}, deadline in {order['deadline'] - state['time']:.1f}s")

    # ... your logic ...
```

### 2. 使用前端可视化

打开 `frontend/index.html` 实时观察车辆移动和区域状态。

### 3. 录像回放

游戏结束后，录像保存在 `recordings/` 目录下。打开 `frontend/replay.html` 可以回放游戏过程。

### 4. 检查 SDK 指令日志

SDK 会在终端打印发送的指令：

```
[CMD] v1: {"type": "pick"} | path(5 pts)
[CMD] v3: {"type": "drop"} | path(3 pts)
```
