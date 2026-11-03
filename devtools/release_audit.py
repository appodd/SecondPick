"""Read-only release-tree scan. Never print matched values or read ignored runtime data."""
from __future__ import annotations

import json
import re
import subprocess


PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "provider_key": rb"\b(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16})\b",
    "personal_home": rb"(?:[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Example\b|TestUser\b)[^\s\"'<>\\/]+|/(?:Users)/(?!example\b|testuser\b)[^\s\"'<>/]+)",
    "contact_email": rb"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(?:com|cn|net|org|edu)(?:\.[A-Za-z]{2,})?\b",
    "platform_record": rb"(?:goofish\.com/(?:item|personal)[^\s\"']*[?&](?:id|userId)=\d{9,}|(?:sellerId|userId)[\"']?\s*[:=]\s*[\"']?\d{10,})",
    "phone_context": r"(?:手机号|联系电话|收货电话)\s*[:：=]\s*[\"']?1[3-9]\d{9}".encode(),
}


def sensitive_matches(label: str, raw: bytes, path: str) -> list:
    if label == "contact_email" and path == "THIRD_PARTY_NOTICES.md":
        # Exact upstream copyright lines from locked cookie/set-cookie-parser
        # packages, not project users' contact information. Keep legal notices.
        for line in (
            b"Copyright (c) 2012-2014 Roman Shtylman <shtylman" + b"@gmail.com>",
            b"Copyright (c) 2015 Douglas Christopher Wilson <doug" + b"@somethingdoug.com>",
            b"Copyright (c) 2015 Nathan Friedly <nathan" + b"@nfriedly.com> (http://nfriedly.com/)",
        ):
            raw = raw.replace(line, b"")
    matches = re.findall(PATTERNS[label], raw, flags=re.I)
    if label == "contact_email" and path in {"tests/test_goofish_import.py", "tests/test_p4_image_evidence.py"}:
        matches = [m for m in matches if m not in {b"user" + b"@www.goofish.com", b"p" + b"@img.alicdn.com"}]
    return matches


def audit(ref: str = "HEAD") -> dict:
    entries = subprocess.check_output(["git", "ls-tree", "-rz", ref]).split(b"\0")
    findings = []
    files = 0
    for entry in filter(None, entries):
        meta, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = meta.split()
        path = raw_path.decode("utf-8")
        if kind != b"blob":
            findings.append({"path": path, "kind": "unexpected_git_entry"})
            continue
        files += 1
        if mode == b"120000":
            findings.append({"path": path, "kind": "symlink"})
        if (path.startswith("data/") and not path.endswith("/.gitkeep")) or re.search(
            r"(?i)(?:\.(?:sqlite\d*|db|dpapi|pem|key|zip|log)$|(?:^|/)\.env(?:\.|$)|(?:^|/)(?:node_modules|browser-profile|artifacts)/)", path
        ):
            findings.append({"path": path, "kind": "excluded_artifact"})
        raw = subprocess.check_output(["git", "cat-file", "blob", oid])
        if len(raw) > 10 * 1024 * 1024:
            findings.append({"path": path, "kind": "large_file"})
        if b"\0" in raw[:8192]:
            continue
        for label in PATTERNS:
            matches = sensitive_matches(label, raw, path)
            count = len(matches)
            if count:
                findings.append({"path": path, "kind": label, "count": count})
    return {"ref": ref, "files": files, "findings": findings}


if __name__ == "__main__":
    import sys
    print(json.dumps(audit(sys.argv[1] if len(sys.argv) > 1 else "HEAD"), ensure_ascii=False, indent=2))
