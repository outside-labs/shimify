# Shimify 0.2.1

Tightens the conservative callable-extraction boundary. An import with a
standard-library spelling must resolve to the actual standard library. Local
source files such as `math.py` or `hashlib.py` are refused during extraction so
relocating the output cannot silently substitute a different implementation.
Class definitions nested inside functions are also explicitly refused, matching
the documented first extraction subset.

The module bundler already rejects standard-library shadowing. Its behavior and
the 0.2 symbol/runtime report schemas remain unchanged.

Verification: 53 regression/differential tests with the pinned real-package
pilot, source/wheel builds, strict metadata and file allowlists, and installed
wheel extraction. Cross-platform and final-main CI remain publication gates.
