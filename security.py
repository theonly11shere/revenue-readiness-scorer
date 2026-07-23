#!/usr/bin/env python3
"""Security Module — SSRF protection, DNS rebinding guard, input sanitization."""
import ipaddress
import re
import socket
import urllib.parse
from typing import Tuple
from config import PRIVATE_IP_RANGES, BLOCKED_PORTS

class SecurityGuard:
    _PRIVATE_NETWORKS = [ipaddress.ip_network(r) for r in PRIVATE_IP_RANGES]

    @classmethod
    def validate_url(cls, url: str) -> Tuple[bool, str]:
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            return False, "Invalid URL format"
        if parsed.scheme not in ("http", "https"):
            return False, f"URL scheme must be http or https, got: {parsed.scheme}"
        host = parsed.hostname
        if not host:
            return False, "URL must have a valid hostname"
        port = parsed.port
        if port and port in BLOCKED_PORTS:
            return False, f"Port {port} is blocked for security reasons"
        if host.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False, "Localhost access is not permitted"
        try:
            resolved_ips = socket.getaddrinfo(host, None)
            for _, _, _, _, sockaddr in resolved_ips:
                ip = sockaddr[0]
                if cls._is_private_ip(ip):
                    return False, "URL resolves to a private/internal IP address"
        except socket.gaierror:
            return False, "Could not resolve hostname"
        except Exception:
            pass
        if len(url) > 2048:
            return False, "URL too long"
        return True, ""

    @classmethod
    def _is_private_ip(cls, ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            for network in cls._PRIVATE_NETWORKS:
                if ip in network:
                    return True
            return False
        except ValueError:
            return False

    @classmethod
    def sanitize_for_html(cls, text: str) -> str:
        if not text:
            return ""
        return text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#x27;")

    @classmethod
    def sanitize_domain(cls, domain: str) -> str:
        domain = domain.strip().lower()
        domain = re.sub(r'^https?://', '', domain)
        domain = re.sub(r'^www\.', '', domain)
        domain = domain.split('/')[0].split('?')[0].split('#')[0]
        if not re.match(r'^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)*$', domain):
            return ""
        return domain

class RateLimitExceeded(Exception):
    pass
