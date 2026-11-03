"""Bounded image bytes from explicit CDN policy; never called by a scheduler.

Network/decoder boundaries are injectable for offline tests. Real HTTPS connects
to a validated IP with the original hostname for TLS, not a second DNS lookup.
"""
from dataclasses import dataclass
import hashlib
import http.client
import io
import ipaddress
import multiprocessing
import socket
import ssl
import time
import threading
from urllib.parse import urlsplit,urljoin


class ImageSafetyError(ValueError):pass


@dataclass(frozen=True)
class ImageLimits:
    hosts: tuple[str,...]=('img.alicdn.com','gw.alicdn.com')
    max_bytes: int=4*1024*1024
    max_pixels: int=12_000_000
    max_edge: int=4096
    total_seconds: float=20
    worker_seconds: float=4
    redirects: int=2


def checked_url(url,limits):
    try:
        p=urlsplit(url)
        host=(p.hostname or '').lower()
        if (not limits.hosts or p.scheme!='https' or host not in limits.hosts or p.port not in (None,443)
            or p.username is not None or p.password is not None or p.fragment or any(ord(c)<33 for c in url) or len(url)>8192):
            raise ImageSafetyError('image_url_not_allowed')
        host.encode('ascii')
    except (ValueError,UnicodeError) as exc:raise ImageSafetyError('image_url_not_allowed') from exc
    return p


def public_addresses(addresses):
    result=[]
    try:
        for text in addresses:
            address=ipaddress.ip_address(text)
            if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped:address=address.ipv4_mapped
            if not address.is_global or address.is_multicast or address.is_reserved or address.is_unspecified:
                raise ImageSafetyError('image_address_not_public')
            result.append(str(address))
    except ValueError as exc:raise ImageSafetyError('image_address_not_public') from exc
    if not result:raise ImageSafetyError('image_dns_empty')
    return sorted(set(result))


def _worker(kind,value,limits,pipe):
    try:
        if kind=='dns':
            answer=sorted({r[4][0] for r in socket.getaddrinfo(value,443,type=socket.SOCK_STREAM)})
        elif kind=='https':
            answer=PinnedHTTPS._fetch(*value)
        else:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS=limits.max_pixels
            with Image.open(io.BytesIO(value),formats=['PNG','JPEG','WEBP']) as image:
                w,h=image.size;fmt=image.format
                if w<=0 or h<=0 or max(w,h)>limits.max_edge or w*h>limits.max_pixels:raise ImageSafetyError('image_pixels_exceeded')
                if getattr(image,'n_frames',1)!=1:raise ImageSafetyError('animated_image_not_allowed')
                image.verify()
            with Image.open(io.BytesIO(value),formats=['PNG','JPEG','WEBP']) as image:image.load()
            answer=dict(width=w,height=h,format=fmt,mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}[fmt])
        pipe.send((True,answer))
    except Exception as exc:
        pipe.send((False,str(exc) if isinstance(exc,ImageSafetyError) else 'image_decode_or_dns_failed'))
    finally:pipe.close()


def bounded_worker(kind,value,limits,timeout):
    if timeout<=0:raise ImageSafetyError('image_deadline')
    ctx=multiprocessing.get_context('spawn');receiver,sender=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_worker,args=(kind,value,limits,sender),daemon=True)
    try:
        process.start();sender.close()
        if not receiver.poll(timeout):raise ImageSafetyError('image_worker_timeout')
        try:ok,result=receiver.recv()
        except EOFError as exc:raise ImageSafetyError('image_worker_failed') from exc
        if not ok:raise ImageSafetyError(result)
        return result
    finally:
        receiver.close();sender.close()
        if process.pid:
            process.join(.2)
            if process.is_alive():process.terminate();process.join(1)
            if process.is_alive():process.kill();process.join(1)
            if process.is_alive():raise ImageSafetyError('image_worker_cleanup_failed')
            process.close()


class PinnedHTTPS:
    def __call__(self,url,address,deadline,max_bytes):
        # A total deadline must cover TLS and slow/trickled response headers,
        # not only a per-socket timeout. The worker is terminated on expiry.
        return bounded_worker('https',(url,address,deadline,max_bytes),ImageLimits(),deadline-time.monotonic())

    @staticmethod
    def _fetch(url,address,deadline,max_bytes):
        p=urlsplit(url);host=p.hostname
        class Connection(http.client.HTTPSConnection):
            def connect(inner):
                sock=socket.create_connection((address,443),timeout=max(.01,deadline-time.monotonic()))
                try:inner.sock=inner._context.wrap_socket(sock,server_hostname=host)
                except BaseException:sock.close();raise
                if ipaddress.ip_address(inner.sock.getpeername()[0])!=ipaddress.ip_address(address):
                    inner.close();raise ImageSafetyError('image_peer_mismatch')
        conn=Connection(host,443,context=ssl.create_default_context(),timeout=max(.01,deadline-time.monotonic()))
        try:
            conn.request('GET',(p.path or '/')+('?' + p.query if p.query else ''),headers={'Accept':'image/png,image/jpeg,image/webp','User-Agent':'SecondPick-image-evidence/1'})
            response=conn.getresponse()
            headers={k.lower():v for k,v in response.getheaders()}
            if response.status in (301,302,303,307,308):return response.status,headers,b''
            if response.status!=200:raise ImageSafetyError('image_http_status')
            chunks=[];count=0
            while True:
                if time.monotonic()>=deadline:raise ImageSafetyError('image_deadline')
                if conn.sock:conn.sock.settimeout(max(.01,deadline-time.monotonic()))
                chunk=response.read1(min(65536,max_bytes+1-count))
                if not chunk:break
                count+=len(chunk)
                if count>max_bytes:raise ImageSafetyError('image_bytes_exceeded')
                chunks.append(chunk)
            return response.status,headers,b''.join(chunks)
        finally:conn.close()


_decode_cache={}
_decode_lock=threading.Lock()


def validate_bytes(data,limits=ImageLimits(),*,timeout=None):
    if not data or len(data)>limits.max_bytes:raise ImageSafetyError('image_bytes_exceeded')
    # Cache only successfully decoded exact bytes under the same resource policy.
    # Callers still check source, ownership, path and expected SHA on every use.
    digest=hashlib.sha256(data).hexdigest()
    key=(digest,limits.max_bytes,limits.max_pixels,limits.max_edge,bounded_worker)
    budget=timeout if timeout is not None else limits.worker_seconds
    started=time.monotonic()
    if budget<=0 or not _decode_lock.acquire(timeout=budget):raise ImageSafetyError('image_worker_timeout')
    try:
        if key in _decode_cache:return dict(_decode_cache[key])
        remaining=budget-(time.monotonic()-started)
        if remaining<=0:raise ImageSafetyError('image_worker_timeout')
        metadata=bounded_worker('decode',data,limits,remaining)
        value=dict(metadata,bytes=len(data),sha256=digest)
        if len(_decode_cache)>=64:_decode_cache.pop(next(iter(_decode_cache)))
        _decode_cache[key]=value
        return dict(value)
    finally:_decode_lock.release()


def fetch_image(url,*,limits=ImageLimits(),resolver=None,transport=None):
    """No retries; every redirect is separately checked and resolved/pinned."""
    deadline=time.monotonic()+limits.total_seconds
    transport=transport or PinnedHTTPS()
    for hop in range(limits.redirects+1):
        p=checked_url(url,limits)
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ImageSafetyError('image_deadline')
        addresses=public_addresses(resolver(p.hostname) if resolver else bounded_worker('dns',p.hostname,limits,min(remaining,limits.worker_seconds)))
        if time.monotonic()>=deadline:raise ImageSafetyError('image_deadline')
        status,headers,data=transport(url,addresses[0],deadline,limits.max_bytes)
        if time.monotonic()>=deadline:raise ImageSafetyError('image_deadline')
        if status in (301,302,303,307,308):
            if hop==limits.redirects or not headers.get('location'):raise ImageSafetyError('image_redirect_limit')
            url=urljoin(url,headers['location']);continue
        if status!=200:raise ImageSafetyError('image_http_status')
        metadata=validate_bytes(data,limits,timeout=min(limits.worker_seconds,max(.001,deadline-time.monotonic())))
        if time.monotonic()>=deadline:raise ImageSafetyError('image_deadline')
        return data,dict(metadata,final_url=url)
    raise ImageSafetyError('image_redirect_limit')
