import ipaddress
import re
import socket

from paramiko import SSHClient, RejectPolicy

from .config import settings
from .models import NodeStatus


def connect() -> SSHClient:
    addr_info = socket.getaddrinfo(
        settings.face_host, 22, socket.AF_INET, socket.SOCK_STREAM
    )
    family, socktype, proto, _, sockaddr = addr_info[0]
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(settings.ssh_timeout_seconds)
    sock.connect(sockaddr)

    client = SSHClient()
    client.set_missing_host_key_policy(RejectPolicy())
    client.load_system_host_keys()
    client.connect(
        hostname=settings.face_host,
        sock=sock,
        username=settings.ssh_username,
        key_filename=settings.ssh_key_path,
        timeout=settings.ssh_timeout_seconds,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


class RouterOSError(RuntimeError):
    """Raised when a RouterOS command returns something on stderr."""


def run_command(client: SSHClient, command: str) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=settings.ssh_timeout_seconds)
    output = stdout.read().decode()
    error = stderr.read().decode()
    if error.strip():
        raise RouterOSError(f"RouterOS error for '{command}': {error.strip()}")
    return output


def _parse_terse_fields(line: str) -> dict[str, str]:
    return dict(re.findall(r'([\w-]+)=("[^"]*"|\S+)', line))


def fetch_ospf_neighbors(client: SSHClient) -> dict[str, bool]:
    """
    Returns {interface_name: is_full_adjacency} for every OSPF
    neighbor currently listed. A node with a fully dead adjacency may
    not appear in the output at all - the caller must treat a missing
    entry as unavailable, not as an error.
    """
    output = run_command(client, "/routing/ospf/neighbor/print terse")
    neighbors: dict[str, bool] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = _parse_terse_fields(line)
        interface = fields.get("interface")
        state = fields.get("state", "").strip('"')
        if interface:
            neighbors[interface] = state.lower().startswith("full")
    return neighbors


def fetch_node_tunnel_ips(client: SSHClient) -> dict[str, str]:
    """
    Discovers every spoke by reading face's own /ip/address
    entries inside tunnel_network, instead of keeping a static node
    list in config. Each tunnel is a /30 point-to-point link, so
    face's own address on it determines the other host
    unambiguously - no need to ask for the peer's address directly.
    A new spoke shows up here the moment its tunnel address exists on
    face, no code or config change needed.

    Worth a sanity check against real face: the `in` operator here
    mirrors the one already proven for routing-filter dst matching,
    but this is /ip/address, a different context - confirm it filters
    the way you'd expect before relying on it.

    Returns {interface_name: peer_ip}.
    """
    output = run_command(
        client,
        f"/ip/address/print terse where address in {settings.tunnel_network}",
    )
    node_ips: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        fields = _parse_terse_fields(line)
        interface = fields.get("interface")
        own_address = fields.get("address")
        if not interface or not own_address:
            continue
        try:
            iface = ipaddress.ip_interface(own_address)
        except ValueError:
            continue
        if iface.network.prefixlen != 30:
            continue
        peers = [host for host in iface.network.hosts() if host != iface.ip]
        if len(peers) != 1:
            continue
        node_ips[interface] = str(peers[0])
    return node_ips


def fetch_avg_rtt(
        client: SSHClient, target_ip: str, count: int | None = None
) -> float | int | None:
    """
    Active /ping from face to target_ip, in the same SSH session.
    Returns None on 100% packet loss or if the summary line couldn't
    be parsed. Blocks for roughly `count` seconds on RouterOS - only
    call this for nodes already known to be up.
    """
    count = count or settings.ping_count
    output = run_command(client, f"/ping address={target_ip} count={count}")
    match = re.search(r"avg-rtt=(\d+(?:\.\d+)?)ms", output)
    return float(match.group(1)) if match else None


def fetch_failover_routes(client: SSHClient) -> dict[str, dict]:
    """
    Every default-route candidate in routing-table=remote, with
    its distance and whether RouterOS currently has it active - NOT
    filtered down to just the active one, on purpose. With both
    candidates in hand, role (primary/secondary) can be worked out from
    distance instead of hardcoded in config: lower distance is
    primary by RouterOS's own convention, and the leading "A" flag
    in terse output says which one actually won right now.
    Returns {interface_name: {"distance": int, "active": bool}}.
    """
    output = run_command(
        client,
        f"/ip/route/print terse where routing-table={settings.routing_table} "
        f"dst-address=0.0.0.0/0",
    )
    routes: dict[str, dict] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue

        flags_match = re.match(r"^\d+\s+([A-Za-z]*)\s", line)
        flags = flags_match.group(1) if flags_match else ""

        fields = _parse_terse_fields(line)
        gw = fields.get("immediate-gw", "")
        interface_match = re.search(r"%(\S+)", gw)
        distance = fields.get("distance")
        if not interface_match or distance is None:
            continue

        routes[interface_match.group(1)] = {
            "distance": int(distance),
            "active": "A" in flags,
        }
    return routes


def apply_failover_state(nodes: dict[str, NodeStatus], routes: dict[str, dict]) -> None:
    """
    Role and active state are both derived straight from what face
    reports for routing-table=remote - lower distance is primary,
    RouterOS's own "A" flag says who are actually active right now.
    Nothing about which node is "supposed" to be primary is
    hardcoded anywhere in this service; swap the priority on face and
    the next poll just picks that up.
    """
    if len(routes) < 2:
        return
    ordered = sorted(routes.items(), key=lambda item: item[1]["distance"])
    for rank, (name, info) in enumerate(ordered):
        if name not in nodes:
            continue
        nodes[name].role = "primary" if rank == 0 else "secondary"
        nodes[name].active = info["active"]


def poll_face() -> list[NodeStatus]:
    """
    One SSH session, start to finish: discover spokes from face's
    own tunnel addresses, OSPF adjacency for each, RTT only for the
    ones that are up, then the active failover interface. This is a
    blocking, synchronous call - run it via asyncio.to_thread from
    async code.
    """
    client = connect()
    try:
        node_ips = fetch_node_tunnel_ips(client)
        adjacency = fetch_ospf_neighbors(client)

        nodes: dict[str, NodeStatus] = {}
        for name, tunnel_ip in node_ips.items():
            is_up = adjacency.get(name, False)
            rtt = fetch_avg_rtt(client, tunnel_ip) if is_up else None
            nodes[name] = NodeStatus(name=name, available=is_up, avg_rtt_ms=rtt)

        routes = fetch_failover_routes(client)
        apply_failover_state(nodes, routes)

        return list(nodes.values())
    finally:
        client.close()
