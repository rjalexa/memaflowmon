#!/usr/bin/env python3
"""
sendmail function to alert of backup anomalies
"""

import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from pathlib import Path


def load_env_file(env_path: str = ".env") -> Dict[str, str]:
    """
    Load environment variables from .env file.

    Args:
        env_path: Path to the .env file

    Returns:
        Dictionary containing environment variables

    Raises:
        FileNotFoundError: If .env file doesn't exist
        ValueError: If .env file is malformed
    """
    env_vars = {}
    env_file = Path(env_path)

    if not env_file.exists():
        raise FileNotFoundError(f".env file not found at: {env_path}")

    with open(env_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Parse KEY=VALUE format
            match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
            if match:
                key, value = match.groups()
                # Remove surrounding quotes if present
                value = value.strip('"').strip("'")
                env_vars[key] = value
            else:
                print(f"Warning: Skipping malformed line {line_num}: {line}")

    return env_vars


def extract_mailto_recipients(env_vars: Dict[str, str]) -> List[str]:
    """
    Extract all MAILTO* recipients from environment variables.

    Args:
        env_vars: Dictionary of environment variables

    Returns:
        List of email addresses
    """
    recipients = []

    # Find all MAILTO* keys and sort them
    mailto_keys = sorted([k for k in env_vars.keys() if k.startswith("MAILTO")])

    for key in mailto_keys:
        email = env_vars[key].strip()
        if email and "@" in email:
            recipients.append(email)
        else:
            print(f"Warning: Invalid email address for {key}: {email}")

    return recipients


def send_email(
    env_path: str = ".env",
    subject_override: Optional[str] = None,
    body_override: Optional[str] = None,
    html_body: bool = False,
) -> bool:
    """
    Send an email using configuration from .env file.

    Args:
        env_path: Path to the .env file (default: ".env")
        subject_override: Override the subject from .env file
        body_override: Override the body from .env file
        html_body: If True, send body as HTML

    Returns:
        True if email was sent successfully, False otherwise

    Raises:
        ValueError: If required environment variables are missing
    """
    try:
        # Load environment variables
        print(f"Loading configuration from {env_path}...")
        env_vars = load_env_file(env_path)

        # Validate required variables
        required_vars = ["MAILUSER", "MAILPASS", "MAILSMTP"]
        missing_vars = [var for var in required_vars if var not in env_vars]
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        # Extract configuration
        mail_user = env_vars["MAILUSER"]
        mail_pass = env_vars["MAILPASS"]
        mail_smtp = env_vars["MAILSMTP"]

        # Parse SMTP server and port
        if ":" in mail_smtp:
            smtp_server, smtp_port = mail_smtp.split(":")
            smtp_port = int(smtp_port)
        else:
            smtp_server = mail_smtp
            smtp_port = 587  # Default SMTP port

        # Get recipients
        recipients = extract_mailto_recipients(env_vars)
        if not recipients:
            raise ValueError("No valid MAILTO recipients found in .env file")

        # Get subject and body
        subject = subject_override or env_vars.get("MAILSUBJECT", "No Subject")
        body = body_override or env_vars.get("MAILBODY", "")

        print(f"Preparing email to {len(recipients)} recipient(s)...")
        print(f"Recipients: {', '.join(recipients)}")

        # Create message
        msg = MIMEMultipart("alternative")
        msg["From"] = mail_user
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject

        # Attach body
        mime_type = "html" if html_body else "plain"
        msg.attach(MIMEText(body, mime_type))

        # Send email
        print(f"Connecting to SMTP server {smtp_server}:{smtp_port}...")
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.set_debuglevel(0)  # Set to 1 for verbose output

            # Start TLS encryption
            print("Starting TLS encryption...")
            server.starttls()

            # Login
            print("Logging in...")
            server.login(mail_user, mail_pass)

            # Send email
            print("Sending email...")
            server.send_message(msg)

        print("✓ Email sent successfully!")
        return True

    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
        return False
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
        return False
    except smtplib.SMTPAuthenticationError:
        print("✗ Authentication failed. Please check MAILUSER and MAILPASS.")
        return False
    except smtplib.SMTPException as e:
        print(f"✗ SMTP error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {type(e).__name__}: {e}")
        return False


def main():
    """Example usage of the send_email function."""
    import sys

    # Check if .env file path is provided as argument
    env_file = sys.argv[1] if len(sys.argv) > 1 else ".env"

    # Send email using configuration from .env file
    success = send_email(env_path=env_file)

    # Exit with appropriate status code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
