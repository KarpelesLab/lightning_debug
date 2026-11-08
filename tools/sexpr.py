"""Tiny S-expression parser/serializer good enough for KiCad files."""
import re


class Str(str):
    """A quoted string token."""


_tok = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def _unesc(s):
    return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def parse(text):
    stack = [[]]
    pos = 0
    n = len(text)
    while pos < n:
        m = _tok.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError("parse error at %d: %r" % (pos, text[pos:pos + 40]))
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            lst = stack.pop()
            stack[-1].append(lst)
        elif m.group(3) is not None:
            stack[-1].append(Str(_unesc(m.group(3))))
        elif m.group(4):
            stack[-1].append(m.group(4))
    return stack[0][0] if len(stack[0]) == 1 else stack[0]


def dump(node, indent=0):
    if isinstance(node, Str):
        return '"' + node.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(node, list):
        simple = all(not isinstance(c, list) for c in node)
        if simple:
            return "(" + " ".join(dump(c) for c in node) + ")"
        pad = "\t" * (indent + 1)
        out = "(" + dump(node[0])
        for c in node[1:]:
            if isinstance(c, list):
                out += "\n" + pad + dump(c, indent + 1)
            else:
                out += " " + dump(c)
        out += "\n" + "\t" * indent + ")"
        return out
    if isinstance(node, float):
        s = ("%.4f" % node).rstrip("0").rstrip(".")
        return s if s not in ("-0", "") else "0"
    return str(node)


def find(node, key):
    for c in node:
        if isinstance(c, list) and c and c[0] == key:
            return c
    return None


def findall(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]
