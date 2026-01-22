import socket

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(("localhost", 65432))

print("Conectado. Enviando SUB...")
s.sendall(b"SUB\n")

while True:
    data = s.recv(4096)
    if not data:
        break
    print(data.decode().strip())
