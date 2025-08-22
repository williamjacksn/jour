import gen
import pathlib

THIS_FILE = pathlib.PurePosixPath(
    pathlib.Path(__file__).relative_to(pathlib.Path().resolve())
)
ACTIONS_CHECKOUT = {"name": "Check out repository", "uses": "actions/checkout@v5"}
push_or_dispatch = (
    "github.event_name == 'push' || github.event_name == 'workflow_dispatch'"
)

workflow = {
    "name": "Build and deploy app",
    "on": {
        "pull_request": {"branches": ["main"]},
        "push": {"branches": ["main"]},
        "workflow_dispatch": {},
    },
    "permissions": {},
    "env": {
        "_workflow_file_generator": "ci/gen-github-workflows.py",
        "image_name": "ghcr.io/${{ github.repository }}",
    },
    "concurrency": {"group": "build-and-deploy"},
    "jobs": {
        "build": {
            "name": "Build the container image",
            "permissions": {"packages": "write"},
            "runs-on": "ubuntu-latest",
            "steps": [
                {
                    "name": "Set up Docker Buildx",
                    "uses": "docker/setup-buildx-action@v3",
                },
                {
                    "name": "Build the container image",
                    "uses": "docker/build-push-action@v6",
                    "with": {
                        "cache-from": "type=gha",
                        "cache-to": "type=gha,mode=max",
                        "tags": "${{ env.image_name }}:latest",
                    },
                },
                {
                    "name": "Log in to GitHub container registry",
                    "if": push_or_dispatch,
                    "uses": "docker/login-action@v3",
                    "with": {
                        "password": "${{ github.token }}",
                        "registry": "ghcr.io",
                        "username": "${{ github.actor }}",
                    },
                },
                {
                    "name": "Push latest image to registry",
                    "if": push_or_dispatch,
                    "uses": "docker/build-push-action@v6",
                    "with": {
                        "cache-from": "type=gha",
                        "push": True,
                        "tags": "${{ env.image_name }}:latest",
                    },
                },
            ],
        },
        "deploy": {
            "name": "Deploy the app",
            "needs": "build",
            "if": push_or_dispatch,
            "runs-on": "ubuntu-latest",
            "steps": [
                ACTIONS_CHECKOUT,
                {
                    "name": "Deploy the app",
                    "run": "sh ci/ssh-deploy.sh",
                    "env": {
                        "SSH_HOST": "${{ secrets.ssh_host }}",
                        "SSH_PRIVATE_KEY": "${{ secrets.ssh_private_key }}",
                        "SSH_USER": "${{ secrets.ssh_user }}",
                    },
                },
            ],
        },
    },
}

gen.gen(workflow, ".github/workflows/build-and-deploy.yaml")

target = ".github/workflows/ruff.yaml"
ruff = {
    "name": "Ruff",
    "on": {"pull_request": {"branches": ["main"]}, "push": {"branches": ["main"]}},
    "permissions": {"contents": "read"},
    "env": {"description": f"This workflow ({target}) was generated from {THIS_FILE}"},
    "jobs": {
        "ruff-check": {
            "name": "Run ruff check",
            "runs-on": "ubuntu-latest",
            "steps": [
                ACTIONS_CHECKOUT,
                {"name": "Run ruff check", "run": "sh ci/ruff-check.sh"},
            ],
        },
        "ruff-format": {
            "name": "Run ruff format",
            "runs-on": "ubuntu-latest",
            "steps": [
                ACTIONS_CHECKOUT,
                {"name": "Run ruff format", "run": "sh ci/ruff-format.sh"},
            ],
        },
    },
}

gen.gen(ruff, ".github/workflows/ruff.yaml")
