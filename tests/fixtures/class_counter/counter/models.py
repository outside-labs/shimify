BIAS = 1
UNUSED = 99


def spare_helper(value):
    return value * 10


class Counter:
    """A whole unit, including methods unused by the first call."""

    LABEL: str = "counter"
    calls: int = 0

    def __init__(self, value: int = 2):
        self.value = value

    @property
    def score(self) -> int:
        return self.value + BIAS

    @staticmethod
    def normalize(text: str) -> str:
        return text.strip()

    @staticmethod
    def token(value=(1, 2)):
        return value

    @classmethod
    def make(cls, value: int = 2):
        cls.calls = cls.calls + 1
        return cls(value)

    def unused_api(self):
        return spare_helper(self.value)


class Unused:
    def value(self):
        return UNUSED
