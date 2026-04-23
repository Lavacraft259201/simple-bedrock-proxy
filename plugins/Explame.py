def on_connect(addr):
    print(f"[PLUGIN] Player joined {addr}")

def on_disconnect(addr):
    print(f"[PLUGIN] Player left {addr}")

def on_client_packet(data, addr):
    return data

def on_server_packet(data, addr):
    return data
