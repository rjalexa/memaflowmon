#!/usr/bin/env python3
"""
Cross-platform script to extract hostname and IP address on Linux and Mac
"""

import socket


def get_hostname_and_ip():
    """
    Extract the hostname and IP address of the machine.
    Works on both Linux and macOS.

    Returns:
        dict: A dictionary containing 'hostname' and 'ip' keys

    Example:
        >>> info = get_hostname_and_ip()
        >>> print(info)
        {'hostname': 'my-machine', 'ip': '192.168.1.100'}
    """
    try:
        # Get hostname
        hostname = socket.gethostname()

        # Get IP address
        # This method works on both Linux and Mac
        # It connects to an external address (doesn't actually send data)
        # to determine which network interface would be used
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Connect to a public DNS server (doesn't need to be reachable)
            s.connect(("8.8.8.8", 80))
            ip_address = s.getsockname()[0]
        except Exception:
            # Fallback method if the above fails
            ip_address = socket.gethostbyname(hostname)
        finally:
            s.close()

        return {"hostname": hostname, "ip": ip_address}

    except Exception as e:
        return {"hostname": None, "ip": None, "error": str(e)}


if __name__ == "__main__":
    import platform

    print("=" * 50)
    print(f"Platform: {platform.system()} {platform.release()}")
    print("=" * 50)

    # Get primary hostname and IP
    info = get_hostname_and_ip()
    print("\nPrimary Network Info:")
    print(f"Hostname: {info.get('hostname')}")
    print(f"IP Address: {info.get('ip')}")

    if "error" in info:
        print(f"Error: {info['error']}")
