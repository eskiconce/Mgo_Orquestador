#!/usr/bin/env python3
"""
Script para incrementar versiones del Orquestador.
Uso:
  python3 bump_version.py patch   # 0.9.0 -> 0.9.1
  python3 bump_version.py minor   # 0.9.x -> 0.10.0
  python3 bump_version.py major   # 0.x -> 1.0.0
"""
import sys
import re

MAIN_FILE = "core/version.py"

def bump(bump_type):
    with open(MAIN_FILE, "r") as f:
        content = f.read()
    
    major_match = re.search(r"VERSION_MAJOR\s*=\s*(\d+)", content)
    minor_match = re.search(r"VERSION_MINOR\s*=\s*(\d+)", content)
    patch_match = re.search(r"VERSION_PATCH\s*=\s*(\d+)", content)
    
    major = int(major_match.group(1))
    minor = int(minor_match.group(1))
    patch = int(patch_match.group(1)) if patch_match else 0
    
    if bump_type == "patch":
        patch += 1
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        print("Uso: python3 bump_version.py [patch|minor|major]")
        return
    
    content = re.sub(r"VERSION_MAJOR\s*=\s*\d+", f"VERSION_MAJOR = {major}", content)
    content = re.sub(r"VERSION_MINOR\s*=\s*\d+", f"VERSION_MINOR = {minor}", content)
    content = re.sub(r"VERSION_PATCH\s*=\s*\d+", f"VERSION_PATCH = {patch}", content)
    
    with open(MAIN_FILE, "w") as f:
        f.write(content)
    
    print(f"Version actualizada: v{major}.{minor}.{patch}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 bump_version.py [patch|minor|major]")
        sys.exit(1)
    bump(sys.argv[1])
