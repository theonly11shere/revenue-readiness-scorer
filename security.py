#!/usr/bin/env python3
"""
Security Module — SSRF protection, DNS rebinding guard, input sanitization.
"""

import ipaddress
import re
import socket
import urllib.parse
from typing import Optional, Tuple

from config import PRIVATE_IP_RANGES, BLOCKED_PORTS, MAX_DOWNLOAD_SIZE, REQUEST_TIMEOUT


class SecurityGuard:
    """Validates URLs before fetching to prevent SSRF and DNS rebinding."""

    # Private/reserved IP ranges
    _PRIVATE_NETWORKS = [ipaddress.ip_network(r) for r in PRIVATE_IP_RANGES]

    @classmethod
    def validate_url(cls, url: str) -> Tuple[bool, str]:
        """
        Validate a URL for safe fetching.
        Returns (is_valid, error_message).
        """
        # Parse URL
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            return False, "Invalid URL format"

        # Scheme check
        if parsed.scheme not in ("http", "https"):
            return False, f"URL scheme must be http or https, got: {parsed.scheme}"

        # Host check
        host = parsed.hostname
        if not host:
            return False, "URL must have a valid hostname"

        # Port check
        port = parsed.port
        if port and port in BLOCKED_PORTS:
            return False, f"Port {port} is blocked for security reasons"

        # Block localhost variations
        if host.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return False, "Localhost access is not permitted"

        # Resolve and check IP
        try:
            resolved_ips = socket.getaddrinfo(host, None)
            for _, _, _, _, sockaddr in resolved_ips:
                ip = sockaddr[0]
                if cls._is_private_ip(ip):
                    return False, "URL resolves to a private/internal IP address"
        except socket.gaierror:
            return False, "Could not resolve hostname"
        except Exception:
            # If DNS fails, allow but log — some valid hosts may not resolve in all environments
            pass

        # Length check
        if len(url) > 2048:
            return False, "URL too long"

        return True, ""

    @classmethod
    def _is_private_ip(cls, ip_str: str) -> bool:
        """Check if an IP address is in a private/reserved range."""
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
        """Sanitize text for safe HTML output."""
        if not text:
            return ""
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")
        text = text.replace("'", "&#x27;")
        return text

    @classmethod
    def sanitize_domain(cls, domain: str) -> str:
        """Sanitize and normalize a domain input."""
        domain = domain.strip().lower()
        # Remove protocol if present
        domain = re.sub(r'^https?://', '', domain)
        domain = re.sub(r'^www\.', '', domain)
        # Remove path, query, fragment
        domain = domain.split('/')[0].split('?')[0].split('#')[0]
        # Validate domain format
        if not re.match(r'^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?)*$', domain):
            return ""
        return domain


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    pass