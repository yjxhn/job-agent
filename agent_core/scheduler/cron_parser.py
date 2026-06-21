"""Human-readable time interval parsing."""

def parse(text: str) -> int:
    t = text.strip().lower()
    if t.endswith("h"):
        return int(t[:-1])
    if t.endswith("m"):
        return max(1, int(t[:-1]) // 60)
    if t.endswith("d"):
        return int(t[:-1]) * 24
    return int(t) if t.isdigit() else 6

def fmt(hours: int) -> str:
    if hours >= 24 and hours % 24 == 0:
        return f"{hours // 24}d"
    return f"{hours}h"
