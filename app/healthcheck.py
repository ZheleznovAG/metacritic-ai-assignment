"""Container readiness probe, fixed loopback URL; IMP-01 / R-DEP-01."""

import json
import sys
from http.client import HTTPConnection

if __name__ == "__main__":
    try:
        client = HTTPConnection("127.0.0.1", 8000, timeout=5)
        client.request("GET", "/health/ready/", headers={"Host": "localhost"})
        response = client.getresponse()
        valid = response.status == 200 and json.loads(response.read())["status"] == "ready"
        client.close()
    except (OSError, ValueError, KeyError):
        valid = False
    sys.exit(0 if valid else 1)
