"""简化版学生代码 — 供应链运输 Demo

策略：贪心响应式。每辆车根据当前状态：
  - 手里有原料 → 送到需要它的加工区（drop）
  - 手里有成品 → 送到需要它的用户区（drop）
  - 空车 → 去取最紧急的成品 / 原料（pick）

不包含：避碰、速度控制、路径偏移。纯粹演示 SDK 用法。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.agent_sdk import AgentSDK

SERVER_URL = "ws://localhost:8765"
sdk = AgentSDK(SERVER_URL)


def my_strategy(state):
    """每 tick 调用一次，返回指令字典。"""

    # ================================================================
    # 1. 从 state 中提取关键信息
    # ================================================================
    vehicles = state.get("vehicles", {})   # 所有车辆 {"v1": {...}, "v2": {...}}
    zones = state.get("zones", {})         # 所有区域 {"raw_a1": {...}, "proc_b1": {...}}
    orders = state.get("orders", [])       # 当前活跃订单 [{"product": "B1", "deadline": 45, ...}]
    current_time = state["time"]           # 当前游戏时间（秒）

    commands = {}  # 本 tick 要发送的指令 {"v1": {"path": [...], "action": {...}}}

    # 统计所有原料物品名称（A1, A2, A3, A4）
    raw_items = set()
    for z in zones.values():
        if z.get("type") == "raw_material":
            raw_items.update(z.get("outputs", []))

    # ================================================================
    # 2. 遍历每辆车，决定要做什么
    # ================================================================
    for vid, v in vehicles.items():
        # status 为 "idle" 时才需要分配新任务
        if v["status"] != "idle":
            continue

        carrying = v["carrying"]       # 当前携带的物品 ID，None 表示空车
        pos = v["position"]            # 当前位置 [x, y]

        # ----------------------------------------------------------
        # 情况 A：车上带着原料（A1/A2/A3/A4）→ 送到加工区
        # ----------------------------------------------------------
        if carrying and carrying in raw_items:
            # find_zones(input=...) 查找"接受该物品"的区域
            # 即：哪些加工区需要这个原料？
            for zid in sdk.find_zones(input=carrying):
                zone = zones[zid]
                # 如果该区域已有的该原料数量 < 1，说明缺货，送去
                if zone["items"].get(carrying, 0) < 1:
                    # navigate_to: 从当前位置规划到目标区域的路径
                    # action="drop": 到达后执行放下物品
                    cmd = sdk.navigate_to(zid, action="drop", from_position=pos)
                    if cmd:
                        commands[vid] = cmd
                    break

            # 如果所有加工区都不缺这个原料，随便送一个
            if vid not in commands:
                for zid in sdk.find_zones(input=carrying):
                    cmd = sdk.navigate_to(zid, action="drop", from_position=pos)
                    if cmd:
                        commands[vid] = cmd
                    break

        # ----------------------------------------------------------
        # 情况 B：车上带着成品（B1/B2/B3）→ 送到有订单的用户区
        # ----------------------------------------------------------
        elif carrying:
            # 查找接受这个成品的区域（用户区）
            for zid in sdk.find_zones(input=carrying):
                zone = zones[zid]
                order = zone.get("order")
                # 检查：区域就绪 + 有订单 + 订单状态为 pending + 订单需要这个成品
                if (zone.get("ready")
                        and order
                        and order.get("status") == "pending"
                        and order.get("required") == carrying):
                    cmd = sdk.navigate_to(zid, action="drop", from_position=pos)
                    if cmd:
                        commands[vid] = cmd
                    break

        # ----------------------------------------------------------
        # 情况 C：空车 → 去取东西
        # ----------------------------------------------------------
        else:
            assigned = False

            # 优先级 1：取已完成的成品，送到用户区（得分最快）
            # 按订单 deadline 排序，优先处理紧急订单
            for order in sorted(orders, key=lambda o: o["deadline"]):
                product = order["product"]  # 如 "B1"

                # find_zones(output=..., ready=True)
                # 查找"产出该成品"且"已就绪"的区域（加工区成品待取）
                for zid in sdk.find_zones(output=product, ready=True):
                    # action="pick"：SDK 转为 {"type": "pick"}，到达区域后自动捡起产出物
                    # 也可以用 dict 指定 target_zone，只在到达该区域时触发：
                    #   action={"type": "pick", "target_zone": zid}
                    cmd = sdk.navigate_to(zid, action="pick", from_position=pos)
                    if cmd:
                        commands[vid] = cmd
                        assigned = True
                        break
                if assigned:
                    break

            if assigned:
                continue

            # 优先级 2：没有成品可取 → 去原料区取原料
            # 遍历紧急订单，看加工区缺什么原料
            for order in sorted(orders, key=lambda o: o["deadline"]):
                product = order["product"]

                # 找到能产出该成品的加工区
                for pzid in sdk.find_zones(output=product):
                    pz = zones[pzid]

                    # 检查加工区缺什么原料（items 中该原料数量 < 1）
                    # 加工区的 inputs 字段列出需要的原料，如 ["A1", "A2", "A3"]
                    for needed_item in pz.get("inputs", []):
                        if pz["items"].get(needed_item, 0) >= 1:
                            continue  # 该原料已有，不缺

                        # 找到能产出该原料且已就绪的原料区
                        # find_zones(output=..., ready=True)
                        for rzid in sdk.find_zones(output=needed_item, ready=True):
                            cmd = sdk.navigate_to(rzid, action="pick", from_position=pos)
                            if cmd:
                                commands[vid] = cmd
                                assigned = True
                                break
                        if assigned:
                            break
                    if assigned:
                        break
                if assigned:
                    break

    # ================================================================
    # 3. 返回指令
    # ================================================================
    # 返回格式：{"v1": {"path": [[x,y], ...], "action": {"type": "pick"}},
    #            "v2": {"path": [[x,y], ...], "action": {"type": "drop"}}}
    #
    # 指令字段说明：
    #   path:   x,y 坐标列表，车辆沿路径移动。空数组 [] = 不改变路径
    #   action: 要执行的动作（服务器不读 item 字段，自动根据区域类型处理）
    #     - {"type": "pick"}                     捡起该区域的产出物（原料或成品）
    #     - {"type": "pick", "target_zone": "z"} 只在到达指定区域时才捡
    #     - {"type": "drop"}                     放下当前携带的物品
    #     - {"type": "drop", "target_zone": "z"} 只在到达指定区域时才放
    #     - {"type": "abandon"}                  丢弃当前携带的物品（任何位置）
    #     - null                                 不改变当前动作
    #   speed:  可选，设置车辆速度（米/秒）

    return commands


if __name__ == "__main__":
    print("=== 简化版供应链 Demo ===")
    print("连接到:", SERVER_URL)
    print("策略：贪心响应式（无避碰）")
    print("等待游戏开始...")
    sdk.run(my_strategy)
