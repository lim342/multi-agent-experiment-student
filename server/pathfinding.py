import math

from server.models import GameState, Node


def compute_edge_distance(n1: Node, n2: Node) -> float:
    """Compute Euclidean distance between two nodes."""
    return math.sqrt((n1.x - n2.x) ** 2 + (n1.y - n2.y) ** 2)


def get_graph_info(state: GameState) -> dict:
    """Return graph info for the SDK client."""
    map_cfg = state.config.get("map", {})
    return {
        "nodes": {nid: {"x": n.x, "y": n.y} for nid, n in state.nodes.items()},
        "edges": [
            {"from": e.from_node, "to": e.to_node, "distance": e.distance}
            for e in state.edges
        ],
        "zones": {
            z.id: {"node": z.node_id, "position": list(z.position)}
            for z in state.get_all_zones().values()
        },
        "map_width": map_cfg.get("width", 16),
        "map_height": map_cfg.get("height", 16),
        "background_image": map_cfg.get("background_image", ""),
        "collision_radius": state.config.get("game", {}).get("collision_radius", 0.3),
        "zone_interaction_radius": state.config.get("game", {}).get("zone_interaction_radius", 0.6),
        "raw_material_production_time": state.config.get("raw_materials", {}).get("production_time", 3.0),
        "recipes": {rid: {"processing_time": r.processing_time} for rid, r in state.recipes.items()},
        "orders_timeout_base": state.config.get("orders", {}).get("timeout_base", 45.0),
    }
