"""A bounded use case for bundling packaging.version."""

import json
import sys

from packaging.version import InvalidVersion, Version


def describe(value: str) -> dict:
    try:
        version = Version(value)
    except InvalidVersion:
        return {"input": value, "valid": False}
    return {
        "input": value,
        "valid": True,
        "normalized": str(version),
        "epoch": version.epoch,
        "release": version.release,
        "pre": version.pre,
        "post": version.post,
        "dev": version.dev,
        "local": version.local,
        "is_prerelease": version.is_prerelease,
    }


if __name__ == "__main__":
    print(json.dumps([describe(value) for value in sys.argv[1:]], sort_keys=True))
