import json
import pathlib

data: dict = json.loads(pathlib.Path("package.json").read_text())
dependencies: dict = data.get("dependencies")

bi: str = dependencies.get("bootstrap-icons")
bs: str = dependencies.get("bootstrap")
hx: str = dependencies.get("htmx.org")
