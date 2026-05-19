# 多智能体供应链协同实验平台 — 服务端

## 项目简介

多智能体供应链协同实验平台的服务端。负责管理游戏状态、处理车辆指令、碰撞检测、订单生成和积分计算。通过 WebSocket 与学生端（Agent SDK）和前端可视化进行通信，是整个系统的核心和唯一真值来源（Single Source of Truth）。

## 系统架构

```
学生 Python (agent_sdk.py) ──WebSocket──→ game_server.py ──WebSocket──→ 前端 (renderer.js)
                                              │
                                         game_engine.py  ← tick 循环，每秒 30 次
                                              │
                                         models.py       ← 所有数据类
                                         pathfinding.py  ← 图信息提取 & 边距离计算
                                         recorder.py     ← 游戏录像
```

### 连接流程

1. 学生 SDK 通过 WebSocket 连接到服务器，发送 `{"role": "student"}`
2. 服务器返回 `graph_info`（地图节点、边、区域、配置信息）
3. 前端浏览器连接，发送 `{"role": "viewer"}`
4. 前端收到状态更新，显示"已连接"
5. 前端点击"开始"按钮，发送 `start_game` 消息
6. 服务器启动 tick 循环，游戏开始
7. 游戏时长到达 `config.json` 中设定的 `duration` 后结束

### 角色区分

连接时通过第一条消息的 `role` 字段区分：

- `role: "student"` — 学生端连接，全局只允许一个，接收状态广播 + 发送控制指令
- `role: "viewer"`（默认）— 前端可视化连接，可多个，接收状态广播 + 发送控制命令（开始/重置）

## 快速启动

### 环境要求

- Python 3.10+
- 依赖：`websockets >= 12.0`

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务器

```bash
# 默认端口 8765
python server/game_server.py

# 自定义端口和配置
python server/game_server.py --host 0.0.0.0 --port 9000 --config my_config.json --map my_map.json

# 录像 HTTP 服务端口（默认 8766）
python server/game_server.py --recording-port 9001
```

### 一键启动（Windows）

双击 `start.bat`，会自动启动服务器、学生端 Agent 和前端可视化。

## 文件结构

```
server/
├── game_server.py    # WebSocket 服务器，连接管理和消息路由
├── game_engine.py    # 游戏引擎，tick 循环和核心逻辑
├── models.py         # 所有数据模型（车辆、区域、订单等）
├── pathfinding.py    # 图信息提取和边距离计算
└── recorder.py       # 游戏录像记录和 HTTP 回放服务
```

## 模块详解

### game_server.py — WebSocket 服务器

`GameServer` 类，负责：

- **连接管理**：区分学生端和查看端连接，维护连接池
- **消息路由**：
  - 学生端 → 接收 `command` 消息，调用 `process_commands()` 处理车辆指令
  - 查看端 → 接收 `start_game`（开始游戏）和 `reset_game`（重置游戏）消息
- **状态广播**：每个 tick 向所有连接的客户端发送完整状态快照
- **录像服务**：通过独立 HTTP 端口提供录像文件下载

#### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `localhost` | 服务器监听地址 |
| `--port` | `8765` | WebSocket 端口 |
| `--config` | `config.json` | 游戏配置文件路径 |
| `--map` | `map.json` | 地图文件路径 |
| `--recording-port` | `8766` | 录像 HTTP 服务端口 |

#### WebSocket 消息协议

**学生端 → 服务器**

| 消息类型 | 格式 | 说明 |
|----------|------|------|
| 角色声明 | `{"role": "student"}` | 第一条消息，声明身份 |
| 车辆指令 | `{"type": "command", "vehicles": {"v1": {"path": [[x,y],...], "action": {...}, "speed": 10}}}` | 控制车辆移动和动作 |

**查看端 → 服务器**

| 消息类型 | 格式 | 说明 |
|----------|------|------|
| 角色声明 | `{"role": "viewer"}` | 第一条消息，声明身份 |
| 开始游戏 | `{"type": "start_game"}` | 前端点击"开始"按钮触发 |
| 重置游戏 | `{"type": "reset_game"}` | 前端点击"重置"按钮触发 |

**服务器 → 客户端**

| 消息类型 | 格式 | 说明 |
|----------|------|------|
| 图信息 | `{"type": "graph_info", "data": {...}}` | 连接后发送，包含地图完整信息 |
| 状态快照 | `{"type": "state", "time": ..., "vehicles": {...}, "zones": {...}, ...}` | 每 tick 广播 |
| 游戏状态 | `{"type": "game_status", "status": "waiting"/"ready"/"running"/"ended"}` | 状态变更时发送 |
| 游戏结束 | `{"type": "game_over", ...}` | 最终状态快照，含完整积分 |

### game_engine.py — 游戏引擎

核心逻辑，包含游戏初始化、tick 循环、指令处理和状态快照生成。

#### 主要函数

| 函数 | 说明 |
|------|------|
| `load_config(path)` | 加载 `config.json` 配置 |
| `load_map(path)` | 加载 `map.json` 地图数据 |
| `init_game_state(config, map_data)` | 根据配置和地图初始化游戏状态 |
| `process_commands(state, commands)` | 处理学生端发送的车辆指令 |
| `tick(state, dt)` | 执行一个 tick 的所有逻辑 |
| `is_game_over(state)` | 判断游戏是否结束 |
| `get_state_snapshot(state)` | 生成广播用的状态快照 |

#### Tick 执行顺序

每个 tick（默认 1/30 秒）按以下顺序执行：

1. **移动车辆** — 沿 x,y 路径点移动，根据速度和 dt 计算位移
2. **碰撞检测** — 两车中心距离 < `collision_radius × 2` 时触发碰撞，扣除 `collision_penalty` 分，1 秒冷却期内不重复扣分
3. **区域交互** — 执行车辆的 `pending_action`（pick/drop/abandon），需在 `zone_interaction_radius` 半径内
4. **原料区冷却** — 更新原料区的生产倒计时，完成后增加库存
5. **加工区生产** — 更新加工区的加工倒计时，完成后标记 `product_ready`
6. **订单生成** — 每隔 `check_interval` 秒检查，以 `generation_probability` 概率为空闲用户区生成订单
7. **超时扣分** — 超出 deadline 的订单每秒扣除 `overtime_penalty_rate` 分
8. **更新积分** — 计算 `完成订单价值 + 投递奖励 - 碰撞扣分 - 超时扣分`

#### 积分计算

```
总分 = completed_orders_value + drop_reward_total - collision_penalty_total - overtime_penalty_total
```

| 积分项 | 说明 |
|--------|------|
| `completed_orders_value` | 完成订单获得的积分（每个订单 = 对应配方的 value 值） |
| `drop_reward_total` | 向加工区投递原料时获得的额外奖励 |
| `collision_penalty_total` | 碰撞扣除的积分（每次碰撞扣 `collision_penalty` 分） |
| `overtime_penalty_total` | 订单超时扣除的积分（每秒扣 `overtime_penalty_rate` 分） |

### models.py — 数据模型

所有核心数据类，使用 Python `dataclass` 定义。

#### 枚举类型

| 枚举 | 值 | 说明 |
|------|-----|------|
| `ZoneType` | `raw_material` / `processing` / `consumer` | 区域类型 |
| `VehicleStatus` | `moving` / `idle` | 车辆状态（自动根据路径判断） |
| `OrderStatus` | `pending` / `completed` / `timeout` | 订单状态 |
| `ProcessingStatus` | `idle` / `collecting` / `processing` / `product_ready` | 加工区状态 |

#### 核心数据类

| 类名 | 说明 | 关键字段 |
|------|------|----------|
| `Node` | 地图节点 | `id`, `x`, `y` |
| `Edge` | 地图边 | `from_node`, `to_node`, `distance` |
| `Recipe` | 加工配方 | `id`, `inputs`（原料列表）, `processing_time`, `value` |
| `RawMaterialZone` | 原料区 | `product`, `stock`, `max_stock`, `cooldown_remaining`, `production_time` |
| `ProcessingZone` | 加工区 | `recipe`, `inventory`, `status`, `processing_remaining`, `product_ready` |
| `ConsumerZone` | 用户区 | `current_order` |
| `Order` | 订单 | `consumer_id`, `required_product`, `deadline`, `status` |
| `Vehicle` | 车辆 | `position`, `speed`, `max_speed`, `carrying`, `path`, `pending_action`, `collision_cooldown` |
| `GameState` | 游戏状态 | 包含所有上述数据，以及积分统计和配置 |

#### 车辆行为

- `set_path(new_path)` — 设置新路径，智能找到最近的路径段作为起点，避免车辆倒退
- `tick(dt)` — 根据速度和 dt 沿路径移动，自动更新位置和朝向角度
- `status` 属性 — 有未走完路径时为 `MOVING`，否则为 `IDLE`

#### 加工区行为

- `can_accept_material(item)` — 判断是否能接受某原料（配方需要且库存未满）
- `place_material(item)` — 放入原料，如果材料齐了自动开始加工
- `try_pick_product()` — 取走成品，取走后如果材料已备齐则自动开始下一批加工
- `tick(dt)` — 加工倒计时更新，完成后标记 `product_ready`

#### 原料区行为

- `tick(dt)` — 生产倒计时更新，到时间后增加库存，库存满时停止生产
- `try_pick()` — 取走一个库存，库存减 1

### pathfinding.py — 路径与图

- `compute_edge_distance(n1, n2)` — 计算两节点间的欧几里得距离
- `get_graph_info(state)` — 从游戏状态提取完整的图信息（节点、边、区域、配置），用于发送给学生端和前端

### recorder.py — 录像服务

- 记录每帧状态快照和学生指令
- 通过 HTTP 端口提供录像文件下载
- 支持前端回放（`replay.html`）

## 配置文件

### config.json — 游戏参数

```json
{
  "game": {
    "duration": 300,              // 游戏时长（秒）
    "tick_rate": 30,              // 每 tick 频率（Hz）
    "collision_radius": 1.0,      // 碰撞检测半径（米）
    "collision_penalty": 5,       // 碰撞扣分
    "zone_interaction_radius": 3.0  // 区域交互半径（米）
  },
  "map": {
    "width": 200,                 // 地图宽度（米）
    "height": 200,                // 地图高度（米）
    "map_file": "map.json",       // 地图文件路径
    "background_image": "data.png" // 背景图（相对于 frontend/）
  },
  "vehicles": {
    "count": 10,                  // 车辆数量
    "speed": 20,                  // 车辆速度（米/秒）
    "start_nodes": ["n104", ...]  // 车辆初始位置节点
  },
  "orders": {
    "check_interval": 2.0,        // 订单检查间隔（秒）
    "generation_probability": 1,  // 订单生成概率（0~1）
    "timeout_base": 80.0,         // 订单超时时间（秒）
    "overtime_penalty_rate": 0.5  // 超时每秒扣分
  },
  "raw_materials": {
    "production_time": 10.0,      // 原料生产时间（秒）
    "max_stock": 2                // 原料区最大库存
  },
  "processing": {
    "max_queue": 3                // 加工区最大材料队列
  }
}
```

### map.json — 地图定义

包含以下部分：

```json
{
  "nodes": {
    "n1": {"x": 10.0, "y": 20.0},   // 节点 ID → 坐标（米）
    ...
  },
  "edges": [
    ["n1", "n2"],                     // 无向边（节点 ID 对）
    ...
  ],
  "zones": {
    "raw_a1": {
      "type": "raw_material",         // 区域类型
      "node": "n5",                   // 所在节点
      "product": "A1",                // 产出物品
      "drop_reward": 0.0              // 投递奖励
    },
    "proc_b1": {
      "type": "processing",
      "node": "n10",
      "recipe": "B1"                  // 使用的配方 ID
    },
    "consumer_1": {
      "type": "consumer",
      "node": "n15"
    }
  },
  "recipes": {
    "B1": {
      "inputs": ["A1", "A2", "A3"],   // 所需原料
      "processing_time": 5.0,          // 加工时间（秒）
      "value": 100                     // 订单价值
    }
  }
}
```

可使用 `tools/map_editor.html` 可视化编辑地图（支持边选择/删除、撤销/重做、网格吸附、右键菜单、复制粘贴等）。

## 供应链规则

### 原料区 → 加工区 → 用户区

```
原料区（A1~A4）──pick──→ 车辆 ──drop──→ 加工区（B1/B2/B3）──pick──→ 车辆 ──drop──→ 用户区（订单）
```

### 配方

| 成品 | 所需原料 | 加工时间 | 订单价值 |
|------|----------|----------|----------|
| B1 | A1 + A2 + A3 | 5 秒 | 100 分 |
| B2 | A3 + A4 | 5 秒 | 100 分 |
| B3 | A2 + A3 | 5 秒 | 100 分 |

### 关键规则

- 车辆一次只能携带一件物品
- 所有车辆速度相同（可在指令中单独设置 `speed`）
- 原料区库存达到上限后停止生产，取走后才继续
- 加工区同一时间只加工一个订单，但可以预存下一批原料
- 加工区成品待取时仍可放入新材料
- 用户区按概率生成订单，每个订单有 deadline
- 超时订单仍保持 `PENDING` 状态，每秒扣除 `overtime_penalty_rate` 分，直到完成投递

## API 参考

### 车辆指令格式

学生端发送的车辆控制指令：

```json
{
  "type": "command",
  "vehicles": {
    "v1": {
      "path": [[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
      "action": {"type": "pick", "target_zone": "raw_a1"},
      "speed": 15
    },
    "v2": {
      "path": [],
      "action": null
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | `[[x,y],...]` | 路径点列表。空数组 `[]` 表示不切换路径，保持当前路径 |
| `action` | `dict/null` | 动作指令。`null` 表示不改变当前动作 |
| `speed` | `float` | 可选，覆盖车辆速度（米/秒），会被 clamp 到 `[0, max_speed]` |

**Action 类型**：

| type | 说明 | 额外字段 |
|------|------|----------|
| `pick` | 捡起区域产出物（原料或成品） | `target_zone`（可选）：只在到达指定区域时触发 |
| `drop` | 放下携带的物品 | `target_zone`（可选）：只在到达指定区域时触发 |
| `abandon` | 丢弃携带的物品（任何位置） | 无 |

- 未指定 `target_zone` 时，车辆路过任何匹配区域都会触发动作
- 指定 `target_zone` 时，只有到达该区域才触发

### 状态快照格式

每个 tick 广播给所有客户端的完整状态：

```json
{
  "type": "state",
  "time": 12.5,
  "score": 250.0,
  "status": "running",
  "vehicles": {
    "v1": {
      "position": [10.0, 20.0],
      "angle": 0.785,
      "carrying": "A1",
      "status": "moving",
      "speed": 20.0,
      "max_speed": 20.0,
      "path_preview": [[30.0, 40.0], [50.0, 60.0]]
    }
  },
  "zones": {
    "raw_a1": {
      "type": "raw_material",
      "position": [10.0, 20.0],
      "node_id": "n5",
      "inputs": [],
      "outputs": ["A1"],
      "items": {"A1": 1},
      "progress": null,
      "ready": true,
      "drop_reward": 0.0
    },
    "proc_b1": {
      "type": "processing",
      "position": [30.0, 40.0],
      "node_id": "n10",
      "inputs": ["A1", "A2", "A3"],
      "outputs": ["B1"],
      "items": {"A1": 1, "A2": 0, "A3": 0},
      "progress": 3.5,
      "ready": false,
      "status": "processing"
    },
    "consumer_1": {
      "type": "consumer",
      "position": [50.0, 60.0],
      "node_id": "n15",
      "inputs": ["B1", "B2", "B3"],
      "outputs": [],
      "items": {},
      "progress": null,
      "ready": true,
      "order": {
        "order_id": "o1",
        "required": "B1",
        "deadline": 95.0,
        "status": "pending"
      }
    }
  },
  "orders": [
    {"id": "o1", "consumer": "consumer_1", "product": "B1", "deadline": 95.0, "status": "pending"}
  ],
  "completed_orders_value": 100.0,
  "completed_orders_count": 1,
  "drop_reward_total": 0.0,
  "material_rewards": {"A1": 0.0, "A2": 0.0, "A3": 0.0, "A4": 0.0},
  "collision_penalty": 5.0,
  "overtime_penalty": 2.5
}
```

### 区域统一数据格式

所有区域类型（原料区/加工区/用户区）共享相同的字段结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `string` | `"raw_material"` / `"processing"` / `"consumer"` |
| `position` | `[x, y]` | 区域中心坐标（米） |
| `node_id` | `string` | 所在图节点 ID |
| `inputs` | `[string]` | 该区域接受什么物品（可以 drop） |
| `outputs` | `[string]` | 该区域产出什么物品（可以 pick） |
| `items` | `{item_id: count}` | 当前持有的物品 |
| `progress` | `float/null` | 生产剩余时间（秒），`null` 表示无进度 |
| `ready` | `bool` | 是否可立即交互 |
