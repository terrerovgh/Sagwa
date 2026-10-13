#!/usr/bin/env python3
"""Inspect staged blobs without printing secrets; refuse private files or oversized blobs."""
import re
import subprocess
import sys

def git(*args):
    return subprocess.check_output(["git", *args])

def inspect(path, content):
    issues = []
    parts = path.lower().split("/")
    if any(p in {".private", ".state", "node_modules", "managed_components", "backups", ".venv", ".git", ".coord"} for p in parts):
        issues.append("private/runtime directory")
    public_receipts = {"README.md", "edge-m.json", "edge-n2.json", "weather-deployed.json", "higgsfield.json", "development-setup.json"}
    if "evidence" in parts and not (len(parts) == 3 and parts[:2] == ["docs", "evidence"] and path.split("/")[-1] in public_receipts):
        issues.append("unreviewed evidence path")
    if any(p.startswith(".env") and p != ".env.example" for p in parts):
        issues.append("environment file")
    if len(content) > 10 * 1024 * 1024:
        issues.append("blob exceeds 10 MiB")
    patterns = [rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
                rb"\b(?:sk-(?:or-v1-|ant-|proj-|svcacct-)?[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{20,}|tskey-(?:auth|api)-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})\b",
                rb"(?i)(?:password|api_key|apiKey|admin_token|access_token)\s*[:=]\s*[\"'][A-Za-z0-9/+_.-]{24,}[\"']"]
    if any(re.search(pattern, content) for pattern in patterns):
        issues.append("possible credential (value withheld)")
    return issues

def main():
    problems = []
    count, total = 0, 0
    for raw in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0"):
        if not raw:
            continue
        path = raw.decode()
        content = git("show", ":" + path)
        count += 1
        total += len(content)
        for issue in inspect(path, content):
            problems.append((path, issue))
    for path, issue in problems:
        print(f"BLOCK: {path}: {issue}", file=sys.stderr)
    print(f"Inspected {count} staged blobs, {total} bytes; findings: {len(problems)}")
    return bool(problems)

if __name__ == "__main__":
    sys.exit(main())
