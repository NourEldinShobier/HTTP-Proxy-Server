import socket
import time

start_time = time.time()

'''
Tested:
"GET / HTTP/1.0\r\nHost: www.google.com:4000\r\n\r\n"
"GET http://www.facebook.com:2500/ HTTP/1.0\r\n"
"GET http://www.google.com:4000/ HTTP/1.0\r\n"
"GET / HTTP/1.0\r\nHost: www.google.com\r\nAccept: application/json\r\n\r\n"
"GET http://info.cern.ch/hypertext/WWW/TheProject.html HTTP/1.0\r\n"
"GET http://info.cern.ch/ HTTP/1.0\r\n"
'''

'''
Failed:
"GET http://info.cern.ch/hypertext/WWW/TheProject.html HTTP/1.0\r\n"
'''

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect(('127.0.0.1', 18888))
client_socket.send(bytes("GET / HTTP/1.0\r\nHost: www.google.com\r\n\r\n", 'utf-8'))
reply = client_socket.recv(10000)

print(reply.decode('utf-8'))
print("\n\n--- %s seconds ---" % (time.time() - start_time))
