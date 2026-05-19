"""WebSocket game server."""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets

from server.game_engine import (
    get_state_snapshot,
    init_game_state,
    is_game_over,
    load_config,
    load_map,
    process_commands,
    tick,
)
from server.pathfinding import get_graph_info
from server.recorder import Recorder


class GameServer:
    def __init__(self, config_path="config.json", map_path="map.json"):
        self.config = load_config(config_path)
        self.map_data = load_map(map_path)
        self.state = None
        self.student_ws = None
        self.viewer_ws_set: set = set()
        self.game_task = None
        self.running = False
        self.recorder = Recorder()

    def reset(self):
        self.state = init_game_state(self.config, self.map_data)
        self.running = False
        self.game_task = None

    async def broadcast_to_viewers(self, message: dict):
        if not self.viewer_ws_set:
            return
        msg_str = json.dumps(message, ensure_ascii=False)
        dead = set()
        for ws in list(self.viewer_ws_set):
            try:
                await ws.send(msg_str)
            except websockets.exceptions.ConnectionClosed:
                dead.add(ws)
        self.viewer_ws_set -= dead

    async def send_to_student(self, message: dict):
        if self.student_ws:
            try:
                await self.student_ws.send(json.dumps(message, ensure_ascii=False))
            except websockets.exceptions.ConnectionClosed:
                self.student_ws = None

    async def broadcast_status(self, status: str):
        msg = {"type": "game_status", "status": status}
        if self.state:
            self.state.status = status
        await self.broadcast_to_viewers(msg)
        await self.send_to_student(msg)

    async def game_loop(self):
        """Main game loop running as an asyncio task."""
        tick_rate = self.config["game"]["tick_rate"]
        dt = 1.0 / tick_rate

        await self.broadcast_status("running")

        graph_info = get_graph_info(self.state)
        self.recorder.start(self.config, graph_info)

        while self.running and not is_game_over(self.state):
            try:
                tick(self.state, dt)

                snapshot = get_state_snapshot(self.state)
                self.recorder.record_frame(snapshot)
                await self.broadcast_to_viewers(snapshot)
                await self.send_to_student(snapshot)
            except Exception as e:
                print(f"[Server] Error in game loop: {e}")
                import traceback
                traceback.print_exc()
                break

            await asyncio.sleep(dt)

        self.running = False
        final = get_state_snapshot(self.state)
        self.recorder.stop(final)
        final["type"] = "game_over"
        await self.broadcast_to_viewers(final)
        await self.send_to_student(final)
        await self.broadcast_status("ended")

    async def handle_student(self, websocket):
        """Handle student SDK connection."""
        if self.student_ws is not None:
            await websocket.send(json.dumps({"type": "error", "message": "Student already connected"}))
            await websocket.close()
            return

        self.student_ws = websocket
        print(f"[Server] Student connected from {websocket.remote_address}")

        # Send graph info for path planning
        graph_info = get_graph_info(self.state)
        await self.send_to_student({"type": "graph_info", "data": graph_info})

        # Notify viewers
        if self.state.status == "waiting":
            self.state.status = "ready"
        await self.broadcast_status(self.state.status)

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "command":
                    if self.running:
                        commands = data.get("vehicles", {})
                        process_commands(self.state, commands)
                        self.recorder.record_command(
                            self.recorder.tick_count - 1,
                            self.state.time,
                            commands,
                        )

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            print("[Server] Student disconnected")
            self.student_ws = None
            if self.running:
                self.running = False
            self.state.status = "waiting"
            await self.broadcast_status("waiting")

    async def handle_viewer(self, websocket):
        """Handle frontend viewer connection."""
        self.viewer_ws_set.add(websocket)
        print(f"[Server] Viewer connected from {websocket.remote_address}")

        # Send current status
        status = self.state.status if self.state else "waiting"
        await websocket.send(json.dumps({"type": "game_status", "status": status}))

        # Send current state if game is running
        if self.state and self.running:
            snapshot = get_state_snapshot(self.state)
            await websocket.send(json.dumps(snapshot, ensure_ascii=False))

        # Send graph info for rendering
        graph_info = get_graph_info(self.state)
        await websocket.send(json.dumps({"type": "graph_info", "data": graph_info}))

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "start_game":
                    if self.state and not self.running and self.student_ws is not None:
                        self.running = True
                        self.game_task = asyncio.create_task(self.game_loop())
                    elif self.student_ws is None:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Waiting for student to connect",
                        }))

                elif data.get("type") == "reset_game":
                    if self.running:
                        self.running = False
                        if self.game_task:
                            self.game_task.cancel()
                        if self.state:
                            snapshot = get_state_snapshot(self.state)
                            self.recorder.stop(snapshot)
                    self.recorder = Recorder()
                    self.reset()
                    new_status = "ready" if self.student_ws is not None else "waiting"
                    await self.broadcast_status(new_status)
                    graph_info = get_graph_info(self.state)
                    await self.broadcast_to_viewers({"type": "graph_info", "data": graph_info})

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.viewer_ws_set.discard(websocket)
            print("[Server] Viewer disconnected")

    async def handler(self, websocket):
        """Route connections based on role."""
        try:
            data = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            msg = json.loads(data)
            role = msg.get("role", "viewer")

            if role == "student":
                await self.handle_student(websocket)
            else:
                await self.handle_viewer(websocket)
        except (asyncio.TimeoutError, json.JSONDecodeError, websockets.exceptions.ConnectionClosed):
            pass

    async def start(self, host="localhost", port=8765, recording_port=8766):
        self.reset()
        print(f"[Server] Starting on ws://{host}:{port}")
        print(f"[Server] Recording files on http://{host}:{recording_port}")
        print("[Server] Waiting for student connection...")

        http_server = await asyncio.start_server(
            self.recorder.handle_http, host, recording_port
        )
        async with websockets.serve(self.handler, host, port, ping_interval=60, ping_timeout=120):
            await asyncio.Future()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Agent Supply Chain Game Server")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8765, help="Server port")
    parser.add_argument("--config", default="config.json", help="Config file path")
    parser.add_argument("--map", default="map.json", help="Map file path")
    parser.add_argument("--recording-port", type=int, default=8766, help="Recording HTTP port")
    args = parser.parse_args()

    server = GameServer(config_path=args.config, map_path=args.map)
    asyncio.run(server.start(host=args.host, port=args.port, recording_port=args.recording_port))


if __name__ == "__main__":
    main()
