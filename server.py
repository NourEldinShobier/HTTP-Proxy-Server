import re
import sys
import os
import enum
import socket
import threading

cache = {}


class HttpRequestInfo(object):
    def __init__(self, client_info,
                 method: str,
                 requested_host: str,
                 requested_port: int,
                 requested_path: str,
                 headers: list):
        self.method = method
        self.client_address_info = client_info
        self.requested_host = requested_host
        self.requested_port = requested_port
        self.requested_path = requested_path
        self.headers = headers
        self.is_relative = True

    def to_http_string(self):
        total_string = ''

        if not self.is_relative:
            # CASE: Absolute Path
            port_segment = '' if self.requested_port == 80 else f':{self.requested_port}'
            request_line = f"{self.method} http://{self.requested_host}{port_segment}{self.requested_path} HTTP/1.0\r\n"
            total_string += request_line
        else:
            # CASE: Relative Path
            request_line = f"{self.method} {self.requested_path} HTTP/1.0\r\n"
            total_string += request_line

            # Attach Port to Host
            port_segment = '' if self.requested_port == 80 else f':{self.requested_port}'
            host_line = f'Host: {self.requested_host}{port_segment}\r\n'

            # Append host header along with port if exists
            total_string += host_line

            # Remove host from headers, to avoid duplication in next step
            self.headers.pop(0)

        # Add headers
        stringified = [": ".join([k, v]) for (k, v) in self.headers]
        headers_line = "\r\n".join(stringified)
        total_string += headers_line

        # Add host back to headers if relative
        if self.is_relative:
            self.headers.insert(0, ['Host', self.requested_host])

        total_string += '\r\n\r\n'

        return total_string

    def to_byte_array(self, http_string):
        return bytes(http_string, "UTF-8")

    def display(self):
        print(f"Client:", self.client_address_info)
        print(f"Method:", self.method)
        print(f"Host:", self.requested_host)
        print(f"Port:", self.requested_port)
        print(f"Path:", self.requested_path)
        stringified = [": ".join([k, v]) for (k, v) in self.headers]
        print("Headers:\n", "\n".join(stringified))


class HttpErrorResponse(object):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def to_http_string(self):
        return f'HTTP/1.0 {self.code} {self.message}'

    def to_byte_array(self, http_string):
        return bytes(http_string, "UTF-8")

    def display(self):
        print(self.to_http_string())


class HttpRequestState(enum.Enum):
    INVALID_INPUT = 0
    NOT_SUPPORTED = 1
    GOOD = 2
    PLACEHOLDER = -1


def entry_point(proxy_port_number):
    proxy_socket = setup_sockets(proxy_port_number)
    do_socket_logic(proxy_socket)


def setup_sockets(proxy_port_number: int):
    proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_socket.bind(('127.0.0.1', proxy_port_number))
    proxy_socket.listen(20)

    print("[+] Starting HTTP proxy on port:", proxy_port_number)

    return proxy_socket


def do_socket_logic(proxy_socket):
    while True:
        client_socket, client_address = proxy_socket.accept()

        print(f'[+] Connection established with: {client_address}')

        request_handler = threading.Thread(target=handle_request, args=(client_socket, client_address))
        request_handler.start()


def http_request_pipeline(source_addr, http_raw_data):
    validity = check_http_request_validity(http_raw_data.decode('utf-8'))

    if validity == HttpRequestState.GOOD:
        info = parse_http_request(source_addr, http_raw_data.decode('utf-8'))
        return info, None

    elif validity == HttpRequestState.INVALID_INPUT:
        error = HttpErrorResponse('400', 'Bad Request')
        return None, error

    else:
        error = HttpErrorResponse('501', 'Not Implemented')
        return None, error


def handle_request(client_socket, client_address):
    http_raw_data = client_socket.recv(10000)
    info, error = http_request_pipeline(client_address, http_raw_data)

    if error is None:
        entry = cache.get(f'{info.requested_host}{info.requested_path}')

        if entry is None:
            print('[+] None cached request...')
            # connect with remote server
            proxy_temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            proxy_temp_socket.connect((info.requested_host, info.requested_port))
            proxy_temp_socket.send(info.to_byte_array(info.to_http_string()))
            reply = proxy_temp_socket.recv(10000)

            cache[f'{info.requested_host}{info.requested_path}'] = reply

            client_socket.send(reply)

            proxy_temp_socket.close()
        else:
            print('[+] Cached Request...')
            client_socket.send(entry)

        client_socket.close()
    else:
        print('[+] Error response...')
        client_socket.send(error.to_byte_array(error.to_http_string()))
        client_socket.close()


def parse_http_request(source_addr, http_raw_data: str):
    lines: list = list(filter(''.__ne__, http_raw_data.split('\r\n')))
    headers: list = []

    # Parse method & path

    first_line = lines.pop(0).split(' ')

    method = first_line[0]

    # Parse headers

    for header_line in lines:
        header_line = header_line.split(' ')
        header_line[0] = header_line[0][0:-1]
        headers.append(header_line)

    # Parse host if exists

    if first_line[1].startswith('/'):
        requested_path = first_line[1]
        requested_host = headers[0][1]
    else:
        requested_path = first_line[1]
        requested_host = None

    info = HttpRequestInfo(client_info=source_addr,
                           method=method,
                           requested_host=requested_host,
                           requested_port=0,
                           requested_path=requested_path,
                           headers=headers)

    info = sanitize_http_request(info)

    # info.display()
    return info


def check_http_request_validity(http_raw_data) -> HttpRequestState:
    lines: list = list(filter(''.__ne__, http_raw_data.split('\r\n')))
    headers: list = []

    methods = ["GET", "POST", "HEAD", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"]

    # 1) validate first line
    first_line_segments = lines.pop(0).split(' ')

    if len(first_line_segments) != 3:
        return HttpRequestState.INVALID_INPUT
    elif first_line_segments[2] != 'HTTP/1.0':
        return HttpRequestState.INVALID_INPUT
    elif methods.count(first_line_segments[0]) == 0:
        return HttpRequestState.INVALID_INPUT

    # 2) check relative | absolute VS. host header existence
    elif len(re.compile(r"Host: ").findall(http_raw_data)) == 0 and first_line_segments[1].startswith('/'):
        return HttpRequestState.INVALID_INPUT

    # 3) validate headers
    regex = '([\\w-]+): (.*)'

    for line in lines:
        g = re.search(regex, line)

        if g is not None:
            headers.append([g.group(1), g.group(2)])
        else:
            return HttpRequestState.INVALID_INPUT

    # 4) check method
    if first_line_segments[0] != 'GET':
        return HttpRequestState.NOT_SUPPORTED

    return HttpRequestState.GOOD


def sanitize_http_request(request_info: HttpRequestInfo):
    # separate port & host & path
    regex = '(https?://)?([^:^/]*):?(\\d*)?(.*)?'
    if request_info.requested_host is not None:
        # CASE: Relative Path
        request_info.is_relative = True
        groups = re.search(regex, request_info.requested_host)

        request_info.headers[0][1] = groups.group(2)  # host_name
        request_info.requested_host = groups.group(2)  # host_name

        requested_port: str = groups.group(3) if groups.group(3) != '' else '80'
        request_info.requested_port = int(requested_port)

    else:
        # CASE: Absolute Path
        request_info.is_relative = False
        groups = re.search(regex, request_info.requested_path)

        request_info.requested_host = groups.group(2)  # host_name

        requested_port: str = groups.group(3) if groups.group(3) != '' else '80'
        request_info.requested_port = int(requested_port)

        request_info.requested_path = groups.group(4) if groups.group(4) != '' else '/'

    return request_info


def get_arg(param_index, default=None):
    try:
        return sys.argv[param_index]
    except IndexError as e:
        if default:
            return default
        else:
            print(e)
            print(
                f"[FATAL] The comand-line argument #[{param_index}] is missing")
            exit(-1)  # Program execution failed.


def check_file_name():
    script_name = os.path.basename(__file__)
    import re
    matches = re.findall(r"(\d{4}_){,2}lab2\.py", script_name)
    if not matches:
        print(f"[WARN] File name is invalid [{script_name}]")
    else:
        print(f"[LOG] File name is correct.")


def main():
    print("\n\n")
    print("*" * 50)
    print(f"[LOG] Printing command line arguments [{', '.join(sys.argv)}]")
    check_file_name()
    print("*" * 50)

    # This argument is optional, defaults to 18888
    proxy_port_number = get_arg(1, 18888)
    entry_point(proxy_port_number)


if __name__ == "__main__":
    main()
