import asyncio
import time
import importlib
import os

SERVER_IP = "127.0.0.1"
SERVER_PORT = 19132

LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 19133

sessions = {}
SESSION_TIMEOUT = 30

PACKET_RATE_LIMIT = 200

stats = {
    "packets_in": 0,
    "packets_out": 0
}

plugins = []


def load_config():
    global SERVER_IP, SERVER_PORT, LISTEN_IP, LISTEN_PORT

    try:
        with open("config.txt") as f:
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    value = value.replace('"', '')

                    if key == "server-name":
                        SERVER_IP = value
                    elif key == "port":
                        SERVER_PORT = int(value)
                    elif key == "listen-server":
                        LISTEN_IP = value
                    elif key == "listen-port":
                        LISTEN_PORT = int(value)

        print(f"[Config] Remote server: {SERVER_IP}:{SERVER_PORT}")
        print(f"[Config] Listening on: {LISTEN_IP}:{LISTEN_PORT}")

    except FileNotFoundError:
        print("[Config] config.txt not found, using defaults")


def load_plugins():
    if not os.path.isdir("plugins"):
        os.mkdir("plugins")

    for file in os.listdir("plugins"):
        if file.endswith(".py"):
            name = file[:-3]
            try:
                module = importlib.import_module(f"plugins.{name}")
                plugins.append(module)
                print(f"[Plugin] Loaded {name}")
            except Exception as e:
                print(f"[Plugin] Failed {name}: {e}")


class BedrockProxy(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        print(f"[Proxy] Listening on {LISTEN_IP}:{LISTEN_PORT}")

        asyncio.create_task(self.cleanup_sessions())
        asyncio.create_task(self.print_stats())

    def datagram_received(self, data, addr):
        now = time.time()
        stats["packets_in"] += 1

        session = sessions.get(addr)

        if not session:
            sessions[addr] = {
                "creating": True,
                "last_seen": now,
                "packet_count": 0,
                "last_reset": now
            }

            print(f"[Proxy] New client: {addr}")

            for plugin in plugins:
                if hasattr(plugin, "on_connect"):
                    plugin.on_connect(addr)

            asyncio.create_task(self.create_session(addr, data))
            return

        if now - session["last_reset"] >= 1:
            session["packet_count"] = 0
            session["last_reset"] = now

        session["packet_count"] += 1

        if session["packet_count"] > PACKET_RATE_LIMIT:
            return

        session["last_seen"] = now

        if "transport" in session:

            for plugin in plugins:
                if hasattr(plugin, "on_client_packet"):
                    result = plugin.on_client_packet(data, addr)
                    if result is None:
                        return
                    data = result

            session["transport"].sendto(data)

    async def create_session(self, addr, first_packet):
        loop = asyncio.get_running_loop()

        if "transport" in sessions.get(addr, {}):
            return

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: ServerSide(self, addr),
                remote_addr=(SERVER_IP, SERVER_PORT)
            )

            sessions[addr] = {
                "transport": transport,
                "last_seen": time.time(),
                "packet_count": 0,
                "last_reset": time.time()
            }

            print(f"[Session] Created for {addr}")

            transport.sendto(first_packet)

        except Exception as e:
            print(f"[Error] Session failed {addr}: {e}")
            sessions.pop(addr, None)

    async def cleanup_sessions(self):
        while True:
            now = time.time()

            for addr in list(sessions.keys()):
                session = sessions.get(addr)

                if now - session.get("last_seen", 0) > SESSION_TIMEOUT:
                    print(f"[Session] Timeout {addr}")

                    for plugin in plugins:
                        if hasattr(plugin, "on_disconnect"):
                            plugin.on_disconnect(addr)

                    if "transport" in session:
                        session["transport"].close()

                    sessions.pop(addr, None)

            await asyncio.sleep(5)

    async def print_stats(self):
        while True:
            print(
                f"[Stats] Clients: {len(sessions)} | "
                f"In: {stats['packets_in']} | Out: {stats['packets_out']}"
            )
            await asyncio.sleep(5)


class ServerSide(asyncio.DatagramProtocol):
    def __init__(self, proxy, client_addr):
        self.proxy = proxy
        self.client_addr = client_addr

    def datagram_received(self, data, addr):
        stats["packets_out"] += 1

        session = sessions.get(self.client_addr)
        if session:
            session["last_seen"] = time.time()

        for plugin in plugins:
            if hasattr(plugin, "on_server_packet"):
                result = plugin.on_server_packet(data, self.client_addr)
                if result is None:
                    return
                data = result

        self.proxy.transport.sendto(data, self.client_addr)

    def connection_lost(self, exc):
        if self.client_addr in sessions:
            print(f"[Session] Closed {self.client_addr}")

            for plugin in plugins:
                if hasattr(plugin, "on_disconnect"):
                    plugin.on_disconnect(self.client_addr)

            sessions.pop(self.client_addr, None)


async def main():
    load_config()
    load_plugins()

    loop = asyncio.get_running_loop()

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: BedrockProxy(),
        local_addr=(LISTEN_IP, LISTEN_PORT)
    )

    try:
        await asyncio.Future()
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
