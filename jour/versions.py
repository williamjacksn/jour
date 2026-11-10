import json
import pathlib

data: dict = json.loads(pathlib.Path("package.json").read_text())
dependencies: dict[str, str] = data["dependencies"]

bi: str = dependencies["bootstrap-icons"]
bs: str = dependencies["bootstrap"]
hx: str = dependencies["htmx.org"]
