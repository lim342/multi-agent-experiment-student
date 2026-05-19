"""Records game sessions for replay and model training."""

import copy
import json
import os
import time
from typing import Optional
from urllib.parse import unquote


class Recorder:
    def __init__(self, output_dir: str = "recordings"):
        self.output_dir = output_dir
        self.frames: list[dict] = []
        self.commands: list[dict] = []
        self.graph_info: Optional[dict] = None
        self.config: Optional[dict] = None
        self.tick_count: int = 0
        self.recording: bool = False
        os.makedirs(output_dir, exist_ok=True)

    def start(self, config: dict, graph_info: dict):
        self.frames = []
        self.commands = []
        self.graph_info = graph_info
        self.config = config
        self.tick_count = 0
        self.recording = True

    def record_frame(self, snapshot: dict):
        if not self.recording:
            return
        frame = copy.deepcopy(snapshot)
        frame["_tick"] = self.tick_count
        self.frames.append(frame)
        self.tick_count += 1

    def record_command(self, tick: int, time_val: float, vehicles: dict):
        if not self.recording:
            return
        self.commands.append({
            "tick": tick,
            "time": round(time_val, 3),
            "vehicles": vehicles,
        })

    def stop(self, final_snapshot: dict) -> Optional[str]:
        if not self.recording:
            return None
        self.recording = False

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"game_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)

        game_config = self.config.get("game", {}) if self.config else {}
        metadata = {
            "version": 1,
            "recorded_at": timestamp,
            "duration": game_config.get("duration", 300),
            "tick_rate": game_config.get("tick_rate", 30),
            "final_score": final_snapshot.get("score", 0),
            "final_status": final_snapshot.get("status", "ended"),
            "config": self.config,
            "completed_orders_count": final_snapshot.get("completed_orders_count", 0),
            "completed_orders_value": final_snapshot.get("completed_orders_value", 0),
            "collision_penalty": final_snapshot.get("collision_penalty", 0),
            "overtime_penalty": final_snapshot.get("overtime_penalty", 0),
            "drop_reward_total": final_snapshot.get("drop_reward_total", 0),
        }

        recording = {
            "metadata": metadata,
            "graph_info": self.graph_info,
            "commands": self.commands,
            "frames": self.frames,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(recording, f, ensure_ascii=False)

        print(f"[Recorder] Saved {len(self.frames)} frames, "
              f"{len(self.commands)} commands to {filepath}")
        return filepath

    def list_recordings(self) -> list[str]:
        """Return list of recording filenames sorted newest first."""
        if not os.path.isdir(self.output_dir):
            return []
        files = [f for f in os.listdir(self.output_dir) if f.endswith(".json")]
        files.sort(reverse=True)
        return files

    async def handle_http(self, reader, writer):
        """Handle a single HTTP request for recording files."""
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return
            request = request_line.decode("utf-8", errors="ignore").strip()
            parts = request.split()
            if len(parts) < 2:
                writer.close()
                return
            method, path = parts[0], parts[1]
            # Consume remaining headers
            while True:
                line = await reader.readline()
                if line == b"\r\n" or line == b"\n" or not line:
                    break

            if method != "GET":
                self._send_json(writer, 405, {"error": "Method not allowed"})
                return

            decoded_path = unquote(path)

            if decoded_path in ("/", "/list"):
                files = self.list_recordings()
                self._send_json(writer, 200, files)
            else:
                # Serve a specific recording file
                filename = decoded_path.lstrip("/")
                filepath = os.path.join(self.output_dir, filename)
                if not os.path.isfile(filepath):
                    self._send_json(writer, 404, {"error": "Not found"})
                    return
                with open(filepath, "r", encoding="utf-8") as f:
                    data = f.read().encode("utf-8")
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                    b"\r\n"
                )
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    def _send_json(self, writer, status, data):
        body = json.dumps(data).encode("utf-8")
        reason = "OK" if status == 200 else "Not Found" if status == 404 else "Error"
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n".encode()
        )
        writer.write(body)
