"""Student Python SDK for the multi-agent supply chain experiment.

Usage:
    from sdk.agent_sdk import AgentSDK

    def my_strategy(state):
        commands = {}
        # Find zones where A1 can be picked up
        for zid in sdk.find_zones(output="A1", ready=True):
            cmd = sdk.navigate_to(zone_id=zid, action="pick:A1",
                                  from_position=state["vehicles"]["v1"]["position"])
            if cmd:
                commands["v1"] = cmd
        return commands

    sdk = AgentSDK("ws://localhost:8765")
    sdk.run(my_strategy)
"""

import asyncio
import json
import math
import threading
from typing import Callable, Optional

try:
    import websockets
except ImportError:
    print("Please install websockets: pip install websockets")
    raise


class AgentSDK:
    def __init__(self, server_url: str = "ws://localhost:8765"):
        self.server_url = server_url
        self._ws = None
        self._state = None
        self._graph = None
        self._nodes = {}
        self._adjacency = {}
        self._zone_map = {}       # {zone_id: {"node": ..., "position": [x,y]}}
        self._map_width = 0
        self._map_height = 0
        self._collision_radius = 0.3
        self._zone_interaction_radius = 0.6
        self._raw_production_time = 3.0
        self._recipes = {}
        self._orders_timeout_base = 45.0
        self._loop = None
        self._running = False
        self._callback = None

    @property
    def state(self) -> Optional[dict]:
        return self._state

    def get_graph(self) -> dict:
        return self._graph or {}

    @property
    def map_size(self) -> tuple[float, float]:
        """Map dimensions (width, height) in meters."""
        return (self._map_width, self._map_height)

    @property
    def collision_radius(self) -> float:
        return self._collision_radius

    @property
    def zone_interaction_radius(self) -> float:
        return self._zone_interaction_radius

    @property
    def raw_production_time(self) -> float:
        return self._raw_production_time

    @property
    def recipes(self) -> dict:
        return self._recipes

    @property
    def orders_timeout_base(self) -> float:
        return self._orders_timeout_base

    def get_zone_position(self, zone_id: str) -> Optional[list[float]]:
        """Get zone position [x, y] from the initial graph data."""
        info = self._zone_map.get(zone_id)
        return info.get("position") if info else None

    # --- Pathfinding ---

    def plan_path(self, start_node: str, end_node: str) -> list[str]:
        """Find shortest path using Dijkstra. Returns node ID list."""
        if start_node == end_node:
            return [start_node]

        dist = {start_node: 0.0}
        prev = {start_node: None}
        heap = [(0.0, start_node)]
        visited = set()

        import heapq

        while heap:
            d, u = heapq.heappop(heap)
            if u in visited:
                continue
            visited.add(u)

            if u == end_node:
                path = []
                node = end_node
                while node is not None:
                    path.append(node)
                    node = prev[node]
                return list(reversed(path))

            for neighbor, weight in self._adjacency.get(u, []):
                if neighbor in visited:
                    continue
                new_dist = d + weight
                if new_dist < dist.get(neighbor, float("inf")):
                    dist[neighbor] = new_dist
                    prev[neighbor] = u
                    heapq.heappush(heap, (new_dist, neighbor))

        return []

    def nodes_to_points(self, node_ids: list[str]) -> list[list[float]]:
        """Convert node IDs to x,y coordinate pairs."""
        points = []
        for nid in node_ids:
            if nid in self._nodes:
                n = self._nodes[nid]
                points.append([n["x"], n["y"]])
        return points

    def find_nearest_node(self, x: float, y: float) -> Optional[str]:
        """Find the nearest graph node to a given position."""
        best_id = None
        best_dist = float("inf")
        for nid, node in self._nodes.items():
            d = math.hypot(node["x"] - x, node["y"] - y)
            if d < best_dist:
                best_dist = d
                best_id = nid
        return best_id

    # --- Zone queries ---

    def find_zones(self, output: str = None, input: str = None,
                   ready: bool = None, zone_type: str = None) -> list[str]:
        """Find zones matching criteria. Returns list of zone IDs.

        Args:
            output: Zone must produce this item (in outputs)
            input: Zone must accept this item (in inputs)
            ready: Zone must be ready for interaction
            zone_type: Zone type filter ("raw_material"/"processing"/"consumer")
        """
        zones = self._state.get("zones", {}) if self._state else {}
        result = []
        for zid, z in zones.items():
            if zone_type and z.get("type") != zone_type:
                continue
            if output and output not in z.get("outputs", []):
                continue
            if input and input not in z.get("inputs", []):
                continue
            if ready is not None and z.get("ready") != ready:
                continue
            result.append(zid)
        return result

    def get_zone(self, zone_id: str) -> Optional[dict]:
        """Get zone data by ID."""
        if self._state:
            return self._state.get("zones", {}).get(zone_id)
        return None

    # --- Navigation ---

    def navigate_to(self, zone_id: str, action=None,
                    from_position: list[float] = None,
                    speed: float = None) -> Optional[dict]:
        """Build a command dict to navigate to a zone.

        Args:
            zone_id: Target zone ID (for pathfinding only)
            action: Action to execute. Can be:
                - str: "pick" or "drop" (converted to dict without target_zone)
                - dict: {"type": "pick"/"drop", "target_zone": str}
                        (passed through as-is)
                - None: no action
            from_position: Starting position [x, y]. If None, returns None.
            speed: Optional speed override (m/s), clamped to [0, max_speed]

        Returns:
            {"path": [[x,y],...], "action": {...}, "speed": ...} or None
        """
        zone = self.get_zone(zone_id)
        if not zone:
            return None

        target_node = zone.get("node_id")
        if not target_node:
            return None

        if from_position is None:
            return None

        nearest = self.find_nearest_node(from_position[0], from_position[1])
        if not nearest:
            return None

        path_nodes = self.plan_path(nearest, target_node)
        if not path_nodes:
            return None

        path_points = self.nodes_to_points(path_nodes)

        # 透传 action：dict 直接用，字符串转 dict（不带 target_zone）
        action_dict = None
        if isinstance(action, dict):
            action_dict = action
        elif isinstance(action, str):
            if action == "pick" or action.startswith("pick:"):
                action_dict = {"type": "pick"}
            elif action == "drop":
                action_dict = {"type": "drop"}
            elif action == "abandon":
                action_dict = {"type": "abandon"}

        cmd = {"path": path_points, "action": action_dict}
        if speed is not None:
            cmd["speed"] = speed
        return cmd

    def send_commands(self, commands: dict):
        """Send vehicle commands. Called internally by run()."""
        if self._ws and self._running:
            msg = json.dumps({
                "type": "command",
                "vehicles": commands,
            })
            asyncio.run_coroutine_threadsafe(self._ws.send(msg), self._loop)

    # --- Connection ---

    async def _connect(self):
        self._ws = await websockets.connect(self.server_url)
        await self._ws.send(json.dumps({"role": "student"}))

        msg = await self._ws.recv()
        data = json.loads(msg)
        if data.get("type") == "graph_info":
            self._graph = data["data"]
            g = self._graph
            self._nodes = g.get("nodes", {})
            self._zone_map = g.get("zones", {})
            self._map_width = g.get("map_width", 0)
            self._map_height = g.get("map_height", 0)
            self._collision_radius = g.get("collision_radius", 0.3)
            self._zone_interaction_radius = g.get("zone_interaction_radius", 0.6)
            self._raw_production_time = g.get("raw_material_production_time", 3.0)
            self._recipes = g.get("recipes", {})
            self._orders_timeout_base = g.get("orders_timeout_base", 45.0)
            self._adjacency = {}
            for edge in g.get("edges", []):
                self._adjacency.setdefault(edge["from"], []).append(
                    (edge["to"], edge["distance"])
                )
                self._adjacency.setdefault(edge["to"], []).append(
                    (edge["from"], edge["distance"])
                )

        print(f"[SDK] Connected to {self.server_url}")
        print(f"[SDK] Graph loaded: {len(self._nodes)} nodes")

    async def _receive_loop(self):
        try:
            async for message in self._ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "state":
                    self._state = data
                    if self._callback:
                        try:
                            commands = self._callback(data)
                            if commands:
                                for vid, cmd in commands.items():
                                    action = cmd.get("action")
                                    path = cmd.get("path", [])
                                    if action:
                                        print(f"[CMD] {vid}: {action} | path({len(path)} pts)")
                                await self._ws.send(json.dumps({
                                    "type": "command",
                                    "vehicles": commands,
                                }))
                        except Exception as e:
                            print(f"[SDK] Callback error: {e}")

                elif msg_type == "game_over":
                    self._state = data
                    print(f"[SDK] Game over! Final score: {data.get('score', 0)}")
                    if self._callback:
                        try:
                            self._callback(data)
                        except Exception:
                            pass
                    self._running = False
                    break

                elif msg_type == "game_status":
                    status = data.get("status")
                    print(f"[SDK] Game status: {status}")
                    if status == "ended":
                        self._running = False
                        break

        except websockets.exceptions.ConnectionClosed:
            print("[SDK] Connection closed")
        finally:
            self._running = False

    def run(self, callback: Callable[[dict], Optional[dict]]):
        """Start the main loop.

        callback(state) is called each tick with the current state.
        It should return a commands dict or None.
        """
        self._callback = callback
        self._running = True

        async def main():
            await self._connect()
            await self._receive_loop()

        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(main())
        except KeyboardInterrupt:
            print("\n[SDK] Interrupted")
        finally:
            self._loop.close()

    def run_async(self, callback: Callable[[dict], Optional[dict]]):
        """Non-blocking run - starts in a background thread."""
        thread = threading.Thread(target=self.run, args=(callback,), daemon=True)
        thread.start()
        return thread
