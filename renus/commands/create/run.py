from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from io import BytesIO
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import termios
    import tty

from renus.rich import Terminal

DESCRIPTION = "Create a new Renus project (create [name] [template] [database])."

TEMPLATES = ("api", "mvp", "extension")
DATABASES = ("mongodb", "mysql", "sqlite", "none")

def _is_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False

def _read_key() -> str:
    if not _is_tty():
        return sys.stdin.readline()
    if os.name == "nt":
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return f"\x1b[{ch2}"
        return ch

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = ch
                while True:
                    nxt = sys.stdin.read(1)
                    seq += nxt
                    if nxt in ("A", "B", "C", "D") or nxt not in "[O":
                        break
                return seq
            if ch in ("\r", "\n"):
                return "\r"
            if ch == "\x03":
                return "\x03"
            if ch.isprintable() or ch == "\x7f":
                return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def _clear_line() -> None:
    sys.stdout.write("\r\x1b[K")

def _move_up(n: int) -> None:
    if n > 0:
        sys.stdout.write(f"\x1b[{n}A")

def select(prompt: str, options: list[str]) -> str:
    """Prompt the user to choose one option interactively."""
    if not options:
        raise ValueError("select() requires at least one option")

    if not _is_tty():
        return options[0]

    selected = 0
    sys.stdout.write(f"{prompt}\n")
    for i, opt in enumerate(options):
        arrow = ">" if i == selected else " "
        sys.stdout.write(f"{arrow} {opt}\n")
    sys.stdout.flush()

    try:
        while True:
            key = _read_key()
            if key == "\x1b[A":
                selected = max(0, selected - 1)
            elif key == "\x1b[B":
                selected = min(len(options) - 1, selected + 1)
            elif key in ("\r", "\n"):
                break
            elif key == "\x03":
                raise KeyboardInterrupt

            _move_up(len(options))
            for i, opt in enumerate(options):
                arrow = ">" if i == selected else " "
                _clear_line()
                sys.stdout.write(f"{arrow} {opt}\n")
            sys.stdout.flush()
    finally:
        _move_up(len(options))
        _clear_line()
        for opt in options:
            _clear_line()
            sys.stdout.write(f"  {opt}\n")
        sys.stdout.flush()

    return options[selected]

def prompt_name() -> str | None:
    """Prompt for a project name and return it or None."""
    name = input("project name: ").strip()
    return name or None

def sanitize(name: str) -> str:
    """Return a filesystem-safe lowercase project directory name."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s)
    s = re.sub(r"^[^a-z0-9]+", "", s)
    return s or "myproject"

def package_name(name: str) -> str:
    """Return a valid Python package name from a directory name."""
    pkg = re.sub(r"[^a-z0-9_]+", "_", name.lower())
    pkg = pkg.strip("_")
    return pkg or "app"

def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

INIT_TEMPLATE = '"""The {pkg} application package."""\n'


MAIN_TEMPLATE = '''from __future__ import annotations

import os

from renus.app import App
from renus.db import Database, DatabaseField, Field, Model
from renus.response import JsonResponse

class Item(Model):
    """A portable domain model (validation + persistence)."""

    id: str = Field(database=DatabaseField(primary_key=True))
    name: str = Field(max_len=120)
    payload: dict | None = None

    class Meta:
        soft_delete = True
        timestamps = True

def _adapter():
{adapter_body}
db = Database(_adapter())

async def on_startup() -> None:
    await db.connect()
    await db.create_schema([Item])

async def on_shutdown() -> None:
    await db.disconnect()

app = App(on_startup=[on_startup], on_shutdown=[on_shutdown])
app.state["db"] = db

@app.get("/items")
async def index(request):
    records = await request.db.repository(Item).query().all()
    return JsonResponse([dict(record) for record in records])

@app.post("/items")
async def store(request):
    data = await request.form()
    await request.db.repository(Item).create(Item(**dict(data or {{}})))
    return JsonResponse({{"msg": "stored"}})

@app.get("/items/{{id}}")
async def show(request, id):
    record = await request.db.repository(Item).query(Item.id == id).first()
    if record is None:
        return JsonResponse({{"msg": "not found"}})
    return JsonResponse(dict(record))

@app.put("/items/{{id}}")
async def update(request, id):
    data = await request.form()
    await request.db.repository(Item).update(Item.id == id, values=dict(data or {{}}))
    return JsonResponse({{"msg": "updated"}})

@app.delete("/items/{{id}}")
async def delete_item(request, id):
    await request.db.repository(Item).delete(Item.id == id)
    return JsonResponse({{"msg": "deleted"}})

def main() -> None:
    app.run("{pkg}.main:app", host="127.0.0.1", port=int(os.environ.get("RENUS_PORT", "8000")))

if __name__ == "__main__":
    main()
'''.lstrip()

NODB_MAIN_TEMPLATE = '''from __future__ import annotations

import os

from renus.app import App
from renus.response import JsonResponse

app = App()

@app.get("/ping")
async def ping(request):
    return JsonResponse({{"msg": "pong", "method": request.method}})

def main() -> None:
    app.run("{pkg}.main:app", host="127.0.0.1", port=int(os.environ.get("RENUS_PORT", "8000")))

if __name__ == "__main__":
    main()
'''.lstrip()

ADAPTER_BODIES: dict[str, str] = {
    "sqlite": '''    from renus.db import SQLiteAdapter

    return SQLiteAdapter({"database": os.path.join(".", "{pkg}.db")})
''',
    "mongodb": '''    from renus.db import MongoDBAdapter

    return MongoDBAdapter({
        "uri": os.environ.get("RENUS_MONGO_URI", "mongodb://localhost:27017"),
        "database": os.environ.get("RENUS_MONGO_DB", "{pkg}_app"),
    })
''',
    "mysql": '''    from renus.db import MySQLAdapter

    return MySQLAdapter({
        "host": os.environ.get("RENUS_MYSQL_HOST", "localhost"),
        "port": int(os.environ.get("RENUS_MYSQL_PORT", "3306")),
        "username": os.environ.get("RENUS_MYSQL_USER", "root"),
        "password": os.environ.get("RENUS_MYSQL_PASSWORD", ""),
        "database": os.environ.get("RENUS_MYSQL_DB", "{pkg}"),
    })
''',
    "none": "",
}

def _readme(name: str, template: str, database: str) -> str:
    db_line = database.capitalize() if database != "none" else "No database (database-less app)"
    endpoints = (
        "\n| `GET` | `/ping` | Health check |\n" if database == "none"
        else (
            "\n| Method | Path            | Action          |\n"
            "| ------ | -------------- | --------------- |\n"
            "| GET    | `/items`       | List items      |\n"
            "| POST   | `/items`       | Create item     |\n"
            "| GET    | `/items/{id}`  | Show one item   |\n"
            "| PUT    | `/items/{id}`  | Update item     |\n"
            "| DELETE | `/items/{id}`  | Delete item     |\n"
        )
    )
    return (
        f"# {name}\n\n"
        f"A Renus project generated with ``renus create`` (template: **{template}**).\n\n"
        f"- **Database:** {db_line}\n\n"
        f"## Run\n\n```bash\npip install \"renus[server]\"\npython -m {name}.main\n```\n\n"
        f"## Endpoints\n{endpoints}"
    )

GITIGNORE = '''__pycache__/
*.py[cod]
*.db
config/
.venv/
venv/
.env
'''

def generate_api(root: str, name: str, pkg: str, database: str) -> bool:
    """Scaffold an API project in the given root directory."""
    _write(os.path.join(root, "README.md"), _readme(name, "api", database))
    _write(os.path.join(root, ".gitignore"), GITIGNORE)
    _write(os.path.join(root, "__init__.py"), INIT_TEMPLATE.format(pkg=pkg))

    if database == "none":
        _write(os.path.join(root, "main.py"), NODB_MAIN_TEMPLATE.format(pkg=pkg))
        return True

    _write(
        os.path.join(root, "main.py"),
        MAIN_TEMPLATE.format(
            pkg=pkg,
            adapter_body=ADAPTER_BODIES[database].replace("{pkg}", pkg),
        ),
    )
    return True

MVP_REPO_URL = "https://github.com/kak-smko/codenus"
MVP_REPO_BRANCH = "master"

def _archive_url(repo: str = MVP_REPO_URL, branch: str = MVP_REPO_BRANCH) -> str:
    slug = repo.rstrip("/").removesuffix(".git")
    slug = slug.split("github.com/", 1)[-1]
    return f"https://codeload.github.com/{slug}/tar.gz/refs/heads/{branch}"

def clone_project(repo: str, dest: str, branch: str | None = None) -> bool:
    """Clone a repository into dest if git is available."""
    git = shutil.which("git")
    if not git:
        return False

    cmd = [git, "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo, dest]

    try:
        result = subprocess.run(cmd, capture_output=True, check=False)
    except OSError:
        return False

    if result.returncode != 0:
        return False

    shutil.rmtree(os.path.join(dest, ".git"), ignore_errors=True)
    return True

def download_project(repo: str, dest: str, branch: str | None = None) -> bool:
    """Download and extract a project tarball into dest."""
    url = _archive_url(repo, branch or MVP_REPO_BRANCH)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "renus-create"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except (OSError, http.client.HTTPException, ValueError):
        return False

    try:
        with tarfile.open(fileobj=BytesIO(payload), mode="r:gz") as archive:
            members = archive.getmembers()
            if not members:
                return False
            top = members[0].name.split("/", 1)[0]
            for member in members:
                member.name = member.name[len(top):].lstrip("/")
            members = [m for m in members if m.name and not m.name.startswith("..")]
            os.makedirs(dest, exist_ok=True)
            _extract_archive(archive, members, dest)
    except (tarfile.TarError, OSError):
        return False
    return True

def _extract_archive(
    archive: tarfile.TarFile, members: list[tarfile.TarInfo], dest: str
) -> None:
    root = os.path.realpath(dest)
    for member in members:
        target = os.path.realpath(os.path.join(dest, member.name))
        if target != root and not target.startswith(root + os.sep):
            raise tarfile.TarError(f"unsafe path in archive: {member.name}")

    try:
        archive.extractall(path=dest, members=members, filter="data")
    except TypeError:
        archive.extractall(path=dest, members=members)

def fetch_project(
    dest: str, repo: str = MVP_REPO_URL, branch: str = MVP_REPO_BRANCH
) -> bool:
    """Fetch a project by cloning, falling back to a tarball download."""
    if clone_project(repo, dest, branch):
        return True
    shutil.rmtree(dest, ignore_errors=True)
    return download_project(repo, dest, branch)

def generate_mvp(root: str, name: str, pkg: str, database: str) -> bool:
    """Scaffold an MVP project by fetching it into the root directory."""
    Terminal.cyan.print(f"Fetching MVP project from {MVP_REPO_URL}...")
    if fetch_project(root):
        return True

    Terminal.red.print(f"Error: could not fetch the MVP project from {MVP_REPO_URL}.")
    Terminal.dim.print("Requires network access and 'git' (or GitHub reachability) — check and retry.")
    return False


LOCAL_EXTENSION_COMMAND = Path(__file__).with_name("local_run_template.py").read_text(
    encoding="utf-8"
)


def generate_extension(root: str, name: str, pkg: str, database: str) -> bool:
    """Create the MVP scaffold and add its local-extension management command."""
    if not generate_mvp(root, name, pkg, database):
        return False

    commands_dir = os.path.join(root, "commands")
    local_dir = os.path.join(commands_dir, "local")
    try:
        os.makedirs(local_dir, exist_ok=True)
        for init_path in (
            os.path.join(commands_dir, "__init__.py"),
            os.path.join(local_dir, "__init__.py"),
        ):
            if not os.path.exists(init_path):
                _write(init_path, "")
        _write(os.path.join(local_dir, "run.py"), LOCAL_EXTENSION_COMMAND)
    except OSError as exc:
        Terminal.red.print(f"Error: could not add the local extension command: {exc}")
        return False

    return True

GENERATORS = {
    "api": generate_api,
    "mvp": generate_mvp,
    "extension": generate_extension,
}

def _run_generator(template: str, root: str, name: str, pkg: str, database: str) -> bool:
    generator = GENERATORS[template]
    if generator(root, name, pkg, database) is False:
        return False

    detail = "" if template in ("mvp", "extension") else f" (database: {database})"
    Terminal.green.print(f"Project '{name}' created with template '{template}'{detail}.")
    return True


def configure_eslint(root: str) -> bool:
    """Install ESLint and add a Vue ESLint config to generated frontends."""
    project = Path(root)
    config = '''import js from '@eslint/js'
import globals from 'globals'
import pluginVue from 'eslint-plugin-vue'

export default [
  {
    files: ['**/*.{js,mjs,jsx,vue}'],
    ignores: ['**/node_modules/**', '**/dist/**', '**/coverage/**'],
    languageOptions: {
      globals: globals.browser,
    },
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    rules: {
      'vue/no-v-text-v-html-on-component': 'off',
      'vue/multi-word-component-names': 'off',
    },
  },
]
'''
    npm = shutil.which("npm")
    if npm is None:
        Terminal.red.print("Error: npm is required to install ESLint.")
        return False

    for frontend in ("admin", "index"):
        frontend_dir = project / "frontend" / frontend
        package_path = frontend_dir / "package.json"
        if not package_path.is_file():
            continue

        try:
            result = subprocess.run(
                [npm, "install", "--save-dev", "eslint", "@eslint/js", "eslint-plugin-vue", "globals"],
                cwd=frontend_dir,
                check=False,
            )
            if result.returncode != 0:
                Terminal.red.print(f"Error: npm failed to install ESLint for {frontend}.")
                return False

            package = json.loads(package_path.read_text(encoding="utf-8"))
            package.setdefault("scripts", {})["lint"] = "eslint ."
            package_path.write_text(
                json.dumps(package, indent=2) + "\n",
                encoding="utf-8",
            )
            (frontend_dir / "eslint.config.js").write_text(config, encoding="utf-8")
        except (OSError, ValueError) as exc:
            Terminal.red.print(f"Error: could not configure ESLint for {frontend}: {exc}")
            return False

        if result.returncode != 0:
            Terminal.red.print(f"Error: npm failed to install ESLint for {frontend}.")
            return False

        Terminal.green.print(f"ESLint configured for frontend/{frontend}.")

    return True

def _resolve_args(args: list[str] | None) -> tuple[str | None, str | None, str | None]:
    if not args:
        return None, None, None
    name: str | None = args[0].strip() or None
    template: str | None = None
    database: str | None = None

    for token in args[1:]:
        tok = token.strip().lower()
        if tok in TEMPLATES:
            template = tok
        elif tok in DATABASES:
            database = tok
        else:
            Terminal.yellow.print(f"Ignoring unknown argument '{token}' (expected template/database).")

    return name, template, database

def _select_optional(prompt: str, options: list[str], default: str) -> str:
    if _is_tty():
        return select(prompt, options)
    return default

def run(args: list[str] | None = None) -> int:
    """Create a new Renus project from the given arguments."""
    try:
        name, template, database = _resolve_args(args)
        if name is None:
            Terminal.bold.print("Renus Create")
            name = prompt_name()
            if not name:
                Terminal.red.print("Error: project name cannot be empty.")
                return 1

        dir_name = sanitize(name)
        pkg = package_name(dir_name)

        out_dir = os.path.abspath(dir_name)
        if os.path.exists(out_dir) and os.listdir(out_dir):
            Terminal.red.print(f"Error: directory '{dir_name}' already exists and is not empty.")
            return 1

        if template is None:
            template = _select_optional("project template:", list(TEMPLATES), "api")

        if database is None:
            database = _select_optional("database:", list(DATABASES), "sqlite")

        if template not in TEMPLATES:
            Terminal.red.print(f"Error: unknown template '{template}' (expected one of {', '.join(TEMPLATES)}).")
            return 1
        if database not in DATABASES:
            Terminal.red.print(f"Error: unknown database '{database}' (expected one of {', '.join(DATABASES)}).")
            return 1

        if not _run_generator(template, out_dir, dir_name, pkg, database):
            return 1

        install_eslint = False
        if template in ("mvp", "extension"):
            install_eslint = _select_optional(
                "install ESLint for the frontends?",
                ["No", "Yes"],
                "No",
            ) == "Yes"
        if install_eslint and not configure_eslint(out_dir):
            return 1

        Terminal.cyan.print(f"Created project in '{out_dir}'. Run: cd {dir_name} && renus run dev")
        return 0
    except KeyboardInterrupt:
        Terminal.red.print("\nCancelled.")
        return 1

__all__ = [
    "DESCRIPTION",
    "MVP_REPO_URL",
    "fetch_project",
    "package_name",
    "run",
    "sanitize",
    "select",
]
