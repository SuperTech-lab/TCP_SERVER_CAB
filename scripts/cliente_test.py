import socket
from sctlab.config.settings import TCP_PORT, TCP_SERVER_HOST

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((TCP_SERVER_HOST, TCP_PORT))

print("Conectado. Enviando SUB...")
s.sendall(b"SUB\n")

while True:
    data = s.recv(4096)
    if not data:
        break
    print(data.decode().strip())
