# A bounded extraction example; no application code runs during generation.
import hashlib
import json

PREFIX = "sha256:"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def checksum(value):
    return PREFIX + digest(value)


def decode(value):
    return json.loads(value)
