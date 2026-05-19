# Copyright 2026 中山大学智能工程学院谭晓军教授课题组
# SPDX-License-Identifier: Apache-2.0

"""Core data models for the multi-agent supply chain experiment."""

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ZoneType(Enum):
    RAW_MATERIAL = "raw_material"
    PROCESSING = "processing"
    CONSUMER = "consumer"


class VehicleStatus(Enum):
    MOVING = "moving"
    IDLE = "idle"


class OrderStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    TIMEOUT = "timeout"


class ProcessingStatus(Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    PROCESSING = "processing"
    PRODUCT_READY = "product_ready"


@dataclass
class Node:
    id: str
    x: float
    y: float


@dataclass
class Edge:
    from_node: str
    to_node: str
    distance: float


@dataclass
class Recipe:
    id: str
    inputs: list[str]
    processing_time: float
    value: float


@dataclass
class RawMaterialZone:
    id: str
    node_id: str
    product: str
    production_time: float
    max_stock: int
    stock: int = 0
    cooldown_remaining: float = 0.0
    drop_reward: float = 0.0
    position: tuple[float, float] = (0, 0)

    def tick(self, dt: float):
        if self.stock >= self.max_stock:
            self.cooldown_remaining = 0.0
            return
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= dt
            if self.cooldown_remaining <= 0:
                self.stock += 1
                self.cooldown_remaining = self.production_time
        else:
            self.cooldown_remaining = self.production_time

    def try_pick(self) -> bool:
        if self.stock > 0:
            self.stock -= 1
            return True
        return False


@dataclass
class ProcessingZone:
    id: str
    node_id: str
    recipe_id: str
    recipe: Recipe = None
    status: ProcessingStatus = ProcessingStatus.IDLE
    inventory: dict[str, int] = field(default_factory=dict)
    processing_remaining: float = 0.0
    product_ready: bool = False
    product_id: Optional[str] = None
    position: tuple[float, float] = (0, 0)

    def __post_init__(self):
        if self.recipe and not self.inventory:
            self.inventory = {item: 0 for item in self.recipe.inputs}

    def can_accept_material(self, material: str) -> bool:
        if not self.recipe:
            return False
        if material not in self.recipe.inputs:
            return False
        return self.inventory.get(material, 0) < self.recipe.inputs.count(material)

    def place_material(self, material: str) -> bool:
        if not self.can_accept_material(material):
            return False
        self.inventory[material] = self.inventory.get(material, 0) + 1
        if self.status == ProcessingStatus.IDLE:
            if self._check_recipe_complete():
                self._start_processing()
        return True

    def _check_recipe_complete(self) -> bool:
        if not self.recipe:
            return False
        for item in self.recipe.inputs:
            count_needed = self.recipe.inputs.count(item)
            if self.inventory.get(item, 0) < count_needed:
                return False
        return True

    def _start_processing(self):
        self.status = ProcessingStatus.PROCESSING
        self.processing_remaining = self.recipe.processing_time
        for item in self.recipe.inputs:
            self.inventory[item] -= self.recipe.inputs.count(item)

    def tick(self, dt: float):
        if self.status == ProcessingStatus.PROCESSING:
            self.processing_remaining -= dt
            if self.processing_remaining <= 0:
                self.product_ready = True
                self.product_id = self.recipe_id
                self.status = ProcessingStatus.PRODUCT_READY
                self.processing_remaining = 0

    def try_pick_product(self) -> Optional[str]:
        if self.product_ready and self.product_id:
            product = self.product_id
            self.product_ready = False
            self.product_id = None
            if self._check_recipe_complete():
                self._start_processing()
            else:
                self.status = ProcessingStatus.IDLE
            return product
        return None


@dataclass
class ConsumerZone:
    id: str
    node_id: str
    current_order: Optional[str] = None
    position: tuple[float, float] = (0, 0)


@dataclass
class Order:
    id: str
    consumer_id: str
    required_product: str
    created_at: float
    deadline: float
    status: OrderStatus = OrderStatus.PENDING
    completed_at: Optional[float] = None


@dataclass
class Vehicle:
    id: str
    position: list[float]
    angle: float = 0.0
    speed: float = 80.0
    max_speed: float = 80.0
    path: list[list[float]] = field(default_factory=list)
    current_path_index: int = 0
    carrying: Optional[str] = None
    pending_action: Optional[dict] = None  # {"type": "pick"/"drop"/"abandon", "target_zone": str}
    collision_cooldown: float = 0.0

    @property
    def status(self) -> VehicleStatus:
        if self.path and self.current_path_index < len(self.path):
            return VehicleStatus.MOVING
        return VehicleStatus.IDLE

    def set_path(self, new_path: list[list[float]]):
        self.path = new_path
        if not new_path:
            self.current_path_index = 0
            return
        px, py = self.position
        best_dist = float("inf")
        best_idx = 0
        # Find the closest path segment, target its endpoint so vehicle keeps moving forward
        for i in range(len(new_path) - 1):
            ax, ay = new_path[i]
            bx, by = new_path[i + 1]
            abx, aby = bx - ax, by - ay
            apx, apy = px - ax, py - ay
            ab_sq = abx * abx + aby * aby
            if ab_sq > 0:
                t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_sq))
                cx, cy = ax + t * abx, ay + t * aby
            else:
                cx, cy = ax, ay
            dx, dy = cx - px, cy - py
            d = dx * dx + dy * dy
            if d < best_dist:
                best_dist = d
                best_idx = i + 1
        self.current_path_index = best_idx

    def tick(self, dt: float):
        if self.collision_cooldown > 0:
            self.collision_cooldown -= dt

        if not self.path or self.current_path_index >= len(self.path):
            return

        target = self.path[self.current_path_index]
        dx = target[0] - self.position[0]
        dy = target[1] - self.position[1]
        dist = math.sqrt(dx * dx + dy * dy)

        move_dist = self.speed * dt

        if dist <= move_dist:
            self.position = [target[0], target[1]]
            self.current_path_index += 1
            if self.current_path_index < len(self.path):
                next_target = self.path[self.current_path_index]
                self.angle = math.atan2(
                    next_target[1] - self.position[1],
                    next_target[0] - self.position[0],
                )
        else:
            ratio = move_dist / dist
            self.position[0] += dx * ratio
            self.position[1] += dy * ratio
            self.angle = math.atan2(dy, dx)



@dataclass
class GameState:
    time: float = 0.0
    score: float = 0.0
    collision_penalty_total: float = 0.0
    overtime_penalty_total: float = 0.0
    completed_orders_value: float = 0.0
    completed_orders_count: int = 0
    drop_reward_total: float = 0.0
    material_rewards: dict = field(default_factory=dict)
    status: str = "waiting"
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    adjacency: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    raw_zones: dict[str, RawMaterialZone] = field(default_factory=dict)
    processing_zones: dict[str, ProcessingZone] = field(default_factory=dict)
    consumer_zones: dict[str, ConsumerZone] = field(default_factory=dict)
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    recipes: dict[str, Recipe] = field(default_factory=dict)
    order_counter: int = 0
    random_seed: Optional[int] = None
    config: dict = field(default_factory=dict)

    @property
    def total_score(self) -> float:
        return self.completed_orders_value + self.drop_reward_total - self.collision_penalty_total - self.overtime_penalty_total

    def get_all_zones(self) -> dict:
        zones = {}
        for z in self.raw_zones.values():
            zones[z.id] = z
        for z in self.processing_zones.values():
            zones[z.id] = z
        for z in self.consumer_zones.values():
            zones[z.id] = z
        return zones

    def find_zone_at(self, position: list[float], radius: float) -> Optional[str]:
        for zone in self.get_all_zones().values():
            dx = zone.position[0] - position[0]
            dy = zone.position[1] - position[1]
            if math.sqrt(dx * dx + dy * dy) <= radius:
                return zone.id
        return None

    def generate_order_id(self) -> str:
        self.order_counter += 1
        return f"o{self.order_counter}"
