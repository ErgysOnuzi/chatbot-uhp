"""Ndihmës për lidhjen e një domeni të ri me këtë aplikacion."""

import ipaddress
import re
from urllib.parse import urlsplit


_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_domain(value: str) -> str:
    """Pranon një URL ose emër domeni dhe kthen domenin bazë ASCII."""
    raw = (value or "").strip().lower()
    if not raw:
        raise ValueError("Shkruani domenin që keni blerë.")

    if "://" in raw:
        domain = urlsplit(raw).hostname or ""
    else:
        domain = raw.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]

    domain = domain.rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]

    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("Vendosni emrin e domenit, jo adresën IP të serverit.")

    if not domain or len(domain) > 253 or "." not in domain:
        raise ValueError("Domeni nuk është i saktë. Shembull: universiteti-yt.com")

    labels = domain.split(".")
    if any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise ValueError("Domeni përmban karaktere të palejuara. Përdorni vetëm shkronja, numra dhe viza.")
    if labels[-1].isdigit():
        raise ValueError("Domeni duhet të përfundojë me një prapashtesë si .com, .org ose .net.")
    return domain


def build_domain_plan(domain_value: str, server_ip: str) -> dict:
    """Kthen vlerat që duhet të vendosen te Namecheap dhe Coolify."""
    domain = normalize_domain(domain_value)
    try:
        parsed_ip = ipaddress.ip_address((server_ip or "").strip())
    except ValueError as exc:
        raise ValueError("SERVER_PUBLIC_IP nuk përmban një IPv4 të saktë.") from exc
    if parsed_ip.version != 4:
        raise ValueError("SERVER_PUBLIC_IP duhet të jetë një adresë IPv4.")

    ip = str(parsed_ip)
    return {
        "domain": domain,
        "server_ip": ip,
        "records": [
            {
                "type": "A Record",
                "host": "@",
                "value": ip,
                "ttl": "Automatic",
                "purpose": f"Lidh domenin bazë {domain}",
            },
            {
                "type": "CNAME Record",
                "host": "www",
                "value": domain,
                "ttl": "Automatic",
                "purpose": f"Lidh www.{domain}",
            },
        ],
        "coolify_domains": [f"https://{domain}", f"https://www.{domain}"],
        "verification_commands": [
            f"dig +short @1.1.1.1 {domain} A",
            f"dig +short @1.1.1.1 www.{domain} CNAME",
        ],
    }
