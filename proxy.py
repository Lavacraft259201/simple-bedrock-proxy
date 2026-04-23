import asyncio
import time

SERVER_IP = "127.0.0.1"
SERVER_PORT = 19132

LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 19133

sessions = {}
SESSION_TIMEOUT = 30


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


class BedrockProxy(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        print(f"[Proxy] Listening on {LISTEN_IP}:{LISTEN_PORT}")
        asyncio.create_task(self.cleanup_sessions())

    def datagram_received(self, data, addr):
        now = time.time()

        if addr not in sessions:
            sessions[addr] = {
                "creating": True,
                "last_seen": now
            }

            print(f"[Proxy] New client: {addr}")
            asyncio.create_task(self.create_session(addr, data))
            return

        session = sessions[addr]
        session["last_seen"] = now

        if "transport" in session:
            session["transport"].sendto(data)

    async def create_session(self, addr, first_packet):
        loop = asyncio.get_running_loop()

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: ServerSide(self, addr),
                remote_addr=(SERVER_IP, SERVER_PORT)
            )

            sessions[addr] = {
                "transport": transport,
                "last_seen": time.time()
            }

            print(f"[Session] Created for {addr}")

            transport.sendto(first_packet)

        except Exception as e:
            print(f"[Error] Session failed {addr}: {e}")
            sessions.pop(addr, None)

    async def cleanup_sessions(self):
        while True:
            now = time.time()

            to_delete = [
                addr for addr, s in sessions.items()
                if now - s.get("last_seen", 0) > SESSION_TIMEOUT
            ]

            for addr in to_delete:
                print(f"[Session] Timeout {addr}")
                session = sessions.pop(addr, None)

                if session and "transport" in session:
                    session["transport"].close()

            await asyncio.sleep(5)


class ServerSide(asyncio.DatagramProtocol):
    def __init__(self, proxy, client_addr):
        self.proxy = proxy
        self.client_addr = client_addr

    def datagram_received(self, data, addr):
        session = sessions.get(self.client_addr)

        if session:
            session["last_seen"] = time.time()

        self.proxy.transport.sendto(data, self.client_addr)

    def connection_lost(self, exc):
        if self.client_addr in sessions:
            print(f"[Session] Closed {self.client_addr}")
            sessions.pop(self.client_addr, None)


async def main():
    load_config()

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
