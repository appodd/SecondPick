"""pytest-only guard: deny external sockets, DNS workers and real Codex launch."""
import ipaddress
from pathlib import Path
import socket
import subprocess


def pytest_configure(config):
    original_dns=socket.getaddrinfo
    original_connect=socket.create_connection
    original_popen=subprocess.Popen
    def local(host):
        if host in ('localhost',None,''):return True
        try:return ipaddress.ip_address(host).is_loopback
        except ValueError:return False
    def dns(host,*args,**kwargs):
        if not local(host):raise AssertionError('P4 offline test attempted external DNS; inject a resolver')
        return original_dns(host,*args,**kwargs)
    def connect(address,*args,**kwargs):
        if not local(address[0]):raise AssertionError('P4 offline test attempted external socket')
        return original_connect(address,*args,**kwargs)
    def popen(command,*args,**kwargs):
        first=command[0] if isinstance(command,(list,tuple)) else command.split()[0]
        if 'codex' in Path(str(first)).name.lower():raise AssertionError('P4 offline test attempted real Codex CLI')
        return original_popen(command,*args,**kwargs)
    socket.getaddrinfo=dns;socket.create_connection=connect;subprocess.Popen=popen
    from shopping_agent import image_safety
    original_worker=image_safety.bounded_worker
    def worker(kind,*args,**kwargs):
        if kind in ('dns','https'):raise AssertionError('P4 offline test attempted real network worker; inject a transport/resolver')
        return original_worker(kind,*args,**kwargs)
    image_safety.bounded_worker=worker
