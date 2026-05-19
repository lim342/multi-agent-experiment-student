"""Game engine: tick loop, state updates, collision, order generation."""

import json
import math
import random
from itertools import combinations
from typing import Optional

from server.models import (
    ConsumerZone,
    Edge,
    GameState,
    Node,
    Order,
    OrderStatus,
    ProcessingZone,
    RawMaterialZone,
    Recipe,
    Vehicle,
)
from server.pathfinding import compute_edge_distance


def load_config(path: str = "config.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_map(path: str = "map.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def init_game_state(config: dict, map_data: dict) -> GameState:
    """Initialize game state from config and map data."""
    state = GameState(config=config)

    # Nodes
    for nid, ndata in map_data["nodes"].items():
        state.nodes[nid] = Node(id=nid, x=ndata["x"], y=ndata["y"])

    # Edges (bidirectional)
    for edge_def in map_data["edges"]:
        n1 = state.nodes[edge_def[0]]
        n2 = state.nodes[edge_def[1]]
        dist = compute_edge_distance(n1, n2)
        state.edges.append(Edge(from_node=n1.id, to_node=n2.id, distance=dist))
        state.adjacency.setdefault(n1.id, []).append((n2.id, dist))
        state.adjacency.setdefault(n2.id, []).append((n1.id, dist))

    # Recipes
    for rid, rdata in map_data["recipes"].items():
        state.recipes[rid] = Recipe(
            id=rid,
            inputs=rdata["inputs"],
            processing_time=rdata["processing_time"],
            value=rdata["value"],
        )

    # Zones
    interaction_radius = config["game"]["zone_interaction_radius"]
    production_time = config["raw_materials"]["production_time"]
    max_stock = config["raw_materials"]["max_stock"]

    for zid, zdata in map_data["zones"].items():
        node = state.nodes[zdata["node"]]
        pos = (node.x, node.y)

        if zdata["type"] == "raw_material":
            state.raw_zones[zid] = RawMaterialZone(
                id=zid,
                node_id=zdata["node"],
                product=zdata["product"],
                production_time=production_time,
                max_stock=max_stock,
                stock=1,
                cooldown_remaining=production_time,
                drop_reward=zdata.get("drop_reward", 0.0),
                position=pos,
            )
        elif zdata["type"] == "processing":
            recipe = state.recipes[zdata["recipe"]]
            state.processing_zones[zid] = ProcessingZone(
                id=zid,
                node_id=zdata["node"],
                recipe_id=zdata["recipe"],
                recipe=recipe,
                position=pos,
            )
        elif zdata["type"] == "consumer":
            state.consumer_zones[zid] = ConsumerZone(
                id=zid,
                node_id=zdata["node"],
                position=pos,
            )

    # Build material drop reward mapping
    state.material_rewards = {z.product: z.drop_reward for z in state.raw_zones.values()}

    # Vehicles
    vehicle_config = config["vehicles"]
    start_nodes = vehicle_config["start_nodes"]
    speed = vehicle_config["speed"]
    count = min(vehicle_config["count"], len(start_nodes))

    for i in range(count):
        vid = f"v{i + 1}"
        node = state.nodes[start_nodes[i]]
        state.vehicles[vid] = Vehicle(
            id=vid,
            position=[node.x, node.y],
            speed=speed,
            max_speed=speed,
        )

    return state


def process_commands(state: GameState, commands: dict):
    """Process student commands for all vehicles."""
    for vid, cmd in commands.items():
        if vid not in state.vehicles:
            continue
        vehicle = state.vehicles[vid]

        # Update path if provided
        new_path = cmd.get("path", [])
        if new_path:
            vehicle.set_path(new_path)

        # Set pending action
        action = cmd.get("action")
        if action is not None:
            vehicle.pending_action = action

        # Set speed (clamped to [0, max_speed])
        speed = cmd.get("speed")
        if speed is not None:
            vehicle.speed = max(0.0, min(float(speed), vehicle.max_speed))


def tick(state: GameState, dt: float):
    """Run one game tick."""
    state.time += dt

    # 1. Move vehicles
    for vehicle in state.vehicles.values():
        vehicle.tick(dt)

    # 2. Collision detection
    collision_radius = state.config["game"]["collision_radius"]
    collision_penalty = state.config["game"]["collision_penalty"]
    vehicle_list = list(state.vehicles.values())
    for i in range(len(vehicle_list)):
        for j in range(i + 1, len(vehicle_list)):
            v1, v2 = vehicle_list[i], vehicle_list[j]
            dx = v1.position[0] - v2.position[0]
            dy = v1.position[1] - v2.position[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < collision_radius * 2:
                if v1.collision_cooldown <= 0 and v2.collision_cooldown <= 0:
                    state.collision_penalty_total += collision_penalty
                    v1.collision_cooldown = 1.0
                    v2.collision_cooldown = 1.0

    # 3. Zone interactions and action execution
    interaction_radius = state.config["game"]["zone_interaction_radius"]
    for vehicle in state.vehicles.values():
        if vehicle.pending_action is None:
            continue

        action = vehicle.pending_action

        # Abandon: discard carried item anywhere, no score
        if action["type"] == "abandon":
            if vehicle.carrying is not None:
                vehicle.carrying = None
            vehicle.pending_action = None
            continue

        zone_id = state.find_zone_at(vehicle.position, interaction_radius)
        if zone_id is None:
            continue

        # 校验目标区域（未指定 target_zone 时路过即触发）
        if action.get("target_zone") is not None and zone_id != action["target_zone"]:
            continue

        # Pick action: pick whatever the zone produces (no item name needed)
        if action["type"] == "pick":
            if vehicle.carrying is None:
                if zone_id in state.raw_zones:
                    zone = state.raw_zones[zone_id]
                    if zone.stock > 0:
                        zone.try_pick()
                        vehicle.carrying = zone.product
                        vehicle.pending_action = None
                elif zone_id in state.processing_zones:
                    zone = state.processing_zones[zone_id]
                    if zone.product_ready:
                        product = zone.try_pick_product()
                        if product:
                            vehicle.carrying = product
                            vehicle.pending_action = None

        # Drop action
        elif action["type"] == "drop" and vehicle.carrying is not None:
            item = vehicle.carrying
            if zone_id in state.processing_zones:
                zone = state.processing_zones[zone_id]
                if zone.can_accept_material(item):
                    zone.place_material(item)
                    state.drop_reward_total += state.material_rewards.get(item, 0)
                    vehicle.carrying = None
                    vehicle.pending_action = None
            elif zone_id in state.consumer_zones:
                zone = state.consumer_zones[zone_id]
                if zone.current_order:
                    order = state.orders.get(zone.current_order)
                    if order and order.status == OrderStatus.PENDING and order.required_product == item:
                        order.status = OrderStatus.COMPLETED
                        order.completed_at = state.time
                        state.completed_orders_value += state.recipes[item].value
                        state.completed_orders_count += 1
                        zone.current_order = None
                        vehicle.carrying = None
                        vehicle.pending_action = None

    # 4. Update raw material zones
    for zone in state.raw_zones.values():
        zone.tick(dt)

    # 5. Update processing zones
    for zone in state.processing_zones.values():
        zone.tick(dt)

    # 6. Generate orders
    check_interval = state.config["orders"]["check_interval"]
    prob = state.config["orders"]["generation_probability"]
    timeout_base = state.config["orders"]["timeout_base"]

    for zid, zone in state.consumer_zones.items():
        if zone.current_order is None:
            if random.random() < prob * dt / check_interval:
                order_id = state.generate_order_id()
                deadline = state.time + timeout_base
                order = Order(
                    id=order_id,
                    consumer_id=zid,
                    required_product=random.choice(list(state.recipes.keys())),
                    created_at=state.time,
                    deadline=deadline,
                )
                state.orders[order_id] = order
                zone.current_order = order_id

    # 7. Check order timeouts
    penalty_rate = state.config["orders"]["overtime_penalty_rate"]
    for order in state.orders.values():
        if order.status == OrderStatus.PENDING and state.time > order.deadline:
            overtime = state.time - order.deadline
            state.overtime_penalty_total += penalty_rate * dt

    # 8. Update score
    state.score = state.total_score


def is_game_over(state: GameState) -> bool:
    duration = state.config["game"]["duration"]
    return state.time >= duration


def get_state_snapshot(state: GameState) -> dict:
    """Generate a state snapshot for broadcasting to clients."""
    vehicles = {}
    for vid, v in state.vehicles.items():
        vehicles[vid] = {
            "position": v.position,
            "angle": v.angle,
            "carrying": v.carrying,
            "status": v.status.value,
            "speed": round(v.speed, 2),
            "max_speed": round(v.max_speed, 2),
            "path_preview": v.path[v.current_path_index:] if v.path else [],
        }

    zones = {}
    for zid, z in state.raw_zones.items():
        zones[zid] = {
            "type": "raw_material",
            "position": list(z.position),
            "node_id": z.node_id,
            "inputs": [],
            "outputs": [z.product],
            "items": {z.product: z.stock},
            "progress": round(z.cooldown_remaining, 2) if z.cooldown_remaining > 0 else None,
            "ready": z.stock > 0,
            "drop_reward": z.drop_reward,
        }
    for zid, z in state.processing_zones.items():
        zones[zid] = {
            "type": "processing",
            "position": list(z.position),
            "node_id": z.node_id,
            "inputs": list(z.recipe.inputs) if z.recipe else [],
            "outputs": [z.recipe_id],
            "items": dict(z.inventory),
            "progress": round(z.processing_remaining, 2) if z.processing_remaining > 0 else None,
            "ready": z.product_ready,
            "status": z.status.value,
        }
    for zid, z in state.consumer_zones.items():
        zone_data = {
            "type": "consumer",
            "position": list(z.position),
            "node_id": z.node_id,
            "inputs": list(state.recipes.keys()),
            "outputs": [],
            "items": {},
            "progress": None,
            "ready": False,
            "order": None,
        }
        if z.current_order and z.current_order in state.orders:
            order = state.orders[z.current_order]
            zone_data["order"] = {
                "order_id": order.id,
                "required": order.required_product,
                "deadline": round(order.deadline, 2),
                "status": order.status.value,
            }
            zone_data["ready"] = order.status == OrderStatus.PENDING
        zones[zid] = zone_data

    orders = []
    for o in state.orders.values():
        if o.status == OrderStatus.PENDING:
            orders.append({
                "id": o.id,
                "consumer": o.consumer_id,
                "product": o.required_product,
                "deadline": round(o.deadline, 2),
                "status": o.status.value,
            })

    return {
        "type": "state",
        "time": round(state.time, 2),
        "score": round(state.score, 2),
        "status": state.status,
        "vehicles": vehicles,
        "zones": zones,
        "orders": orders,
        "completed_orders_value": round(state.completed_orders_value, 2),
        "completed_orders_count": state.completed_orders_count,
        "drop_reward_total": round(state.drop_reward_total, 2),
        "material_rewards": state.material_rewards,
        "collision_penalty": round(state.collision_penalty_total, 2),
        "overtime_penalty": round(state.overtime_penalty_total, 2),
    }
