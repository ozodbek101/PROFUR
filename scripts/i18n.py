"""Translation catalogs without GNU gettext.

Uzbek is the source language: every msgid in templates and Python code is the
Uzbek text, and English / Russian live in locale/<lang>/LC_MESSAGES/django.po.

    python scripts/i18n.py extract   # scan code, add new strings to the .po files, drop unused ones
    python scripts/i18n.py compile   # write django.mo next to each django.po
    python scripts/i18n.py check     # fail if a string is untranslated, a placeholder is wrong,
                                     # or a committed .mo is stale (used in CI)

Workflow when you change UI text: extract → translate the empty msgstr entries in
both .po files → compile → commit .po and .mo together.
"""

from __future__ import annotations

import ast
import io
import re
import struct
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALE_DIR = ROOT / "locale"
SOURCE_DIRS = ["apps", "config"]
TEMPLATE_DIRS = ["templates", "apps"]

PLURAL_FORMS = {
    "en": "nplurals=2; plural=(n != 1);",
    "ru": (
        "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 "
        "&& (n%100<10 || n%100>=20) ? 1 : 2);"
    ),
}
LANGUAGE_NAMES = {"en": "English", "ru": "Russian"}

# Python call names that mark a string, with the argument layout they take.
SIMPLE = {"_", "gettext", "gettext_lazy", "gettext_noop"}
CONTEXT = {"pgettext", "pgettext_lazy"}
PLURAL = {"ngettext", "ngettext_lazy"}
CONTEXT_PLURAL = {"npgettext", "npgettext_lazy"}


# --------------------------------------------------------------------------- model


@dataclass
class Entry:
    msgid: str
    msgctxt: str | None = None
    msgid_plural: str | None = None
    msgstr: list[str] = field(default_factory=lambda: [""])
    refs: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)

    @property
    def key(self) -> tuple[str | None, str]:
        return (self.msgctxt, self.msgid)

    @property
    def translated(self) -> bool:
        return all(s.strip() for s in self.msgstr) and "fuzzy" not in self.flags


# --------------------------------------------------------------------------- extract


def _python_messages(source: str, filename: str):
    """Yield (ctx, msgid, plural, line) for every literal gettext call."""
    tree = ast.parse(source, filename)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name is None:
            continue
        args = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None for a in node.args]
        if name in SIMPLE and args[:1] and args[0] is not None:
            yield None, args[0], None, node.lineno
        elif name in CONTEXT and len(args) >= 2 and None not in args[:2]:
            yield args[0], args[1], None, node.lineno
        elif name in PLURAL and len(args) >= 2 and None not in args[:2]:
            yield None, args[0], args[1], node.lineno
        elif name in CONTEXT_PLURAL and len(args) >= 3 and None not in args[:3]:
            yield args[0], args[1], args[2], node.lineno


def _template_messages(source: str, filename: str):
    """Run Django's templatize (what makemessages feeds to xgettext) and read its calls."""
    from django.utils.translation.template import templatize

    # Strip indentation: the output is only tokenized, never run, and the
    # template's own indentation would otherwise trip the tokenizer.
    code = "\n".join(line.lstrip() for line in templatize(source, origin=filename).split("\n"))
    tokens = [t for t in tokenize.generate_tokens(io.StringIO(code).readline)
              if t.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)]
    for i, tok in enumerate(tokens):
        if tok.type != tokenize.NAME or tok.string not in SIMPLE | CONTEXT | PLURAL | CONTEXT_PLURAL:
            continue
        if i + 1 >= len(tokens) or tokens[i + 1].string != "(":
            continue
        strings, j = [], i + 2
        while j < len(tokens) and tokens[j].type == tokenize.STRING:
            strings.append(ast.literal_eval(tokens[j].string))
            j += 1
            if j < len(tokens) and tokens[j].string == ",":
                j += 1
        line = tok.start[0]  # templatize keeps the template's line breaks
        name = tok.string
        if name in SIMPLE and strings:
            yield None, strings[0], None, line
        elif name in CONTEXT and len(strings) >= 2:
            yield strings[0], strings[1], None, line
        elif name in PLURAL and len(strings) >= 2:
            yield None, strings[0], strings[1], line
        elif name in CONTEXT_PLURAL and len(strings) >= 3:
            yield strings[0], strings[1], strings[2], line


def collect() -> dict[tuple[str | None, str], Entry]:
    found: dict[tuple[str | None, str], Entry] = {}

    def add(ctx, msgid, plural, ref):
        if not msgid:
            return
        entry = found.setdefault((ctx, msgid), Entry(msgid=msgid, msgctxt=ctx))
        if plural and not entry.msgid_plural:
            entry.msgid_plural = plural
        entry.refs.append(ref)

    for base in SOURCE_DIRS:
        for path in sorted((ROOT / base).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "/migrations/" in rel or "/tests" in rel or rel.endswith("tests.py"):
                continue
            for ctx, msgid, plural, line in _python_messages(path.read_text(encoding="utf-8"), rel):
                add(ctx, msgid, plural, f"{rel}:{line}")
    seen = set()
    for base in TEMPLATE_DIRS:
        for path in sorted((ROOT / base).rglob("*.html")):
            if path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(ROOT).as_posix()
            for ctx, msgid, plural, line in _template_messages(path.read_text(encoding="utf-8"), rel):
                add(ctx, msgid, plural, f"{rel}:{line}")
    return found


# --------------------------------------------------------------------------- .po io


def _unquote(s: str) -> str:
    return ast.literal_eval(s)


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def read_po(path: Path) -> tuple[str, dict[tuple[str | None, str], Entry]]:
    header, entries = "", {}
    if not path.exists():
        return header, entries
    current: Entry | None = None
    target: tuple[str, int] | None = None
    raw: dict[str, str] = {}

    def flush():
        nonlocal current, raw, header
        if current is None:
            return
        if current.msgid == "" and current.msgctxt is None:
            header = current.msgstr[0]
        else:
            entries[current.key] = current
        current, raw = None, {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            flush()
            target = None
            continue
        if line.startswith("#~"):
            continue
        if line.startswith("#,"):
            current = current or Entry(msgid="")
            current.flags |= {f.strip() for f in line[2:].split(",") if f.strip()}
            continue
        if line.startswith("#:"):
            current = current or Entry(msgid="")
            current.refs.extend(line[2:].split())
            continue
        if line.startswith("#"):
            continue
        current = current or Entry(msgid="")
        m = re.match(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+(".*")$', line)
        if m:
            kw, idx, value = m.group(1), m.group(2), _unquote(m.group(3))
            if kw == "msgctxt":
                current.msgctxt, target = value, ("msgctxt", 0)
            elif kw == "msgid":
                current.msgid, target = value, ("msgid", 0)
            elif kw == "msgid_plural":
                current.msgid_plural, target = value, ("msgid_plural", 0)
            else:
                i = int(idx) if idx is not None else 0
                while len(current.msgstr) <= i:
                    current.msgstr.append("")
                current.msgstr[i], target = value, ("msgstr", i)
        elif line.startswith('"') and target:
            value = _unquote(line)
            kw, i = target
            if kw == "msgstr":
                current.msgstr[i] += value
            else:
                setattr(current, kw, (getattr(current, kw) or "") + value)
    flush()
    return header, entries


def write_po(path: Path, lang: str, entries: list[Entry]) -> None:
    out = [
        f"# {LANGUAGE_NAMES[lang]} translation of Mebel Ombori. Source language: Uzbek (uz).",
        "# Edit msgstr values, then run: python scripts/i18n.py compile",
        "#",
        'msgid ""',
        'msgstr ""',
        _quote("Project-Id-Version: mebel-ombori\n"),
        _quote(f"Language: {lang}\n"),
        _quote("MIME-Version: 1.0\n"),
        _quote("Content-Type: text/plain; charset=UTF-8\n"),
        _quote("Content-Transfer-Encoding: 8bit\n"),
        _quote(f"Plural-Forms: {PLURAL_FORMS[lang]}\n"),
        "",
    ]
    for e in entries:
        for i in range(0, len(e.refs), 4):
            out.append("#: " + " ".join(e.refs[i : i + 4]))
        flags = set(e.flags)
        if re.search(r"%\(\w+\)[sd]|%[sd]", e.msgid):
            flags.add("python-format")
        if flags:
            out.append("#, " + ", ".join(sorted(flags)))
        if e.msgctxt is not None:
            out.append("msgctxt " + _quote(e.msgctxt))
        out.append("msgid " + _quote(e.msgid))
        if e.msgid_plural is not None:
            out.append("msgid_plural " + _quote(e.msgid_plural))
            for i, s in enumerate(e.msgstr):
                out.append(f"msgstr[{i}] " + _quote(s))
        else:
            out.append("msgstr " + _quote(e.msgstr[0]))
        out.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")


def nplurals(lang: str) -> int:
    return int(re.search(r"nplurals=(\d+)", PLURAL_FORMS[lang]).group(1))


def po_path(lang: str) -> Path:
    return LOCALE_DIR / lang / "LC_MESSAGES" / "django.po"


# --------------------------------------------------------------------------- .mo


def mo_bytes(lang: str, entries: dict[tuple[str | None, str], Entry]) -> bytes:
    header = (
        f"Project-Id-Version: mebel-ombori\nLanguage: {lang}\nMIME-Version: 1.0\n"
        f"Content-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n"
        f"Plural-Forms: {PLURAL_FORMS[lang]}\n"
    )
    pairs = {b"": header.encode()}
    for e in entries.values():
        if not e.translated:
            continue
        key = e.msgid if e.msgid_plural is None else e.msgid + "\0" + e.msgid_plural
        if e.msgctxt is not None:
            key = e.msgctxt + "\x04" + key
        pairs[key.encode()] = "\0".join(e.msgstr).encode()
    keys = sorted(pairs)
    n = len(keys)
    orig_off, trans_off = 28, 28 + n * 8
    data_off = trans_off + n * 8
    ids, strs, otab, ttab = b"", b"", [], []
    for k in keys:
        otab.append((len(k), len(ids)))
        ids += k + b"\0"
    for k in keys:
        v = pairs[k]
        ttab.append((len(v), len(strs)))
        strs += v + b"\0"
    out = struct.pack("<7I", 0x950412DE, 0, n, orig_off, trans_off, 0, data_off)
    for length, off in otab:
        out += struct.pack("<2I", length, data_off + off)
    for length, off in ttab:
        out += struct.pack("<2I", length, data_off + len(ids) + off)
    return out + ids + strs


# --------------------------------------------------------------------------- commands


def cmd_extract() -> int:
    found = collect()
    for lang in PLURAL_FORMS:
        _, old = read_po(po_path(lang))
        merged = []
        for key in sorted(found, key=lambda k: (found[k].refs[0], k[1])):
            new = found[key]
            entry = Entry(msgid=new.msgid, msgctxt=new.msgctxt, msgid_plural=new.msgid_plural, refs=new.refs)
            size = nplurals(lang) if new.msgid_plural else 1
            prev = old.get(key)
            if prev and (prev.msgid_plural is None) == (new.msgid_plural is None):
                entry.msgstr = (prev.msgstr + [""] * size)[:size]
                entry.flags = prev.flags - {"python-format"}
            else:
                entry.msgstr = [""] * size
            merged.append(entry)
        write_po(po_path(lang), lang, merged)
        missing = sum(1 for e in merged if not e.translated)
        dropped = len(set(old) - set(found))
        print(f"{lang}: {len(merged)} strings, {missing} untranslated, {dropped} removed")
    return 0


def cmd_compile() -> int:
    for lang in PLURAL_FORMS:
        _, entries = read_po(po_path(lang))
        po_path(lang).with_suffix(".mo").write_bytes(mo_bytes(lang, entries))
        print(f"{lang}: compiled {sum(e.translated for e in entries.values())} strings")
    return 0


PLACEHOLDER = re.compile(r"%\((\w+)\)[sd]")


def cmd_check() -> int:
    problems = []
    found = collect()
    for lang in PLURAL_FORMS:
        path = po_path(lang)
        _, entries = read_po(path)
        for key in found.keys() - entries.keys():
            problems.append(f"{lang}: not in .po (run extract): {key[1]!r}")
        for e in entries.values():
            if not e.translated:
                problems.append(f"{lang}: untranslated: {e.msgid!r}")
                continue
            want = set(PLACEHOLDER.findall(e.msgid)) | set(PLACEHOLDER.findall(e.msgid_plural or ""))
            for s in e.msgstr:
                got = set(PLACEHOLDER.findall(s))
                if got - want or (e.msgid_plural is None and got != want):
                    problems.append(f"{lang}: placeholders {sorted(got)} != {sorted(want)} in {e.msgid!r}")
        mo = path.with_suffix(".mo")
        if not mo.exists() or mo.read_bytes() != mo_bytes(lang, entries):
            problems.append(f"{lang}: {mo.relative_to(ROOT).as_posix()} is stale (run compile)")
    for p in problems:
        print(p)
    print("i18n check: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    commands = {"extract": cmd_extract, "compile": cmd_compile, "check": cmd_check}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(__doc__)
        sys.exit(2)
    sys.path.insert(0, str(ROOT))
    sys.exit(commands[sys.argv[1]]())
