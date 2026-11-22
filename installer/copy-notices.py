"""Copy notices for the Python runtime and dependencies bundled with Melora."""

import importlib.metadata
import shutil
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", destination / "Python.txt")

dependencies = ["fastapi", "uvicorn", "anyio", "pyinstaller"]
visited = set()
while dependencies:
    name = canonicalize_name(dependencies.pop())
    if name in visited:
        continue
    visited.add(name)
    distribution = importlib.metadata.distribution(name)
    for file in distribution.files or ():
        if ".dist-info" in str(file) and file.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
            shutil.copyfile(distribution.locate_file(file), destination / f"{name}-{file.name}")
    for item in distribution.requires or ():
        requirement = Requirement(item)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            dependencies.append(requirement.name)
