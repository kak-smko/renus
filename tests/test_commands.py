from __future__ import annotations

import datetime
import importlib.util
import json
import os
import sqlite3
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from renus.db import Database, SQLiteAdapter, register_adapter

from renus.commands.base import BaseCommand
from renus.commands.help import Help, discover_commands
from renus.commands.cli import execute_handler, find_command, get_version, run
from renus.commands.app.run import (
    add_routes,
    add_temp,
    to_camel_case,
    to_plural,
    run as app_run,
)
from renus.commands.create.run import (
    DATABASES,
    TEMPLATES,
    package_name,
    run as create_run,
    sanitize,
)
from renus.commands.db.run import (
    MongoJSONEncoder,
    backup_table_paginated,
    delete_all_records,
    mongo_json_decoder,
    resolve_driver,
    restore_table_paginated,
    run as db_run,
)
from renus.commands.extension.build import _add_route, _remove_route
from renus.commands.routing import include_router_in_index, remove_router_from_index
from renus.commands.extension.run import (
    check_version,
    download,
    get_available_versions,
    install_app,
    is_upgrade,
    load_apps,
    load_installed,
    match_version,
    parse_version_tuple,
    run as extension_run,
    write_lock,
)
import renus.commands.extension.run as extension_run_module
from renus.config import Config

create_module = sys.modules["renus.commands.create.run"]

@pytest.fixture(autouse=True)
def clean_config_cache():
    original_cache = dict(Config._cache)
    yield
    Config._cache.clear()
    Config._cache.update(original_cache)

class TestCommandDiscoveryAndHelp:

    def test_discover_framework_commands(self):
        commands = discover_commands()
        assert "app" in commands
        assert "db" in commands
        assert "extension" in commands

    def test_discover_project_commands(self, tmp_path):
        proj_commands = tmp_path / "commands"
        proj_commands.mkdir()
        custom_cmd = proj_commands / "greet"
        custom_cmd.mkdir()
        run_file = custom_cmd / "run.py"
        run_file.write_text('DESCRIPTION = "Greet the user"\ndef run(args=None): print("hello")\n')

        commands = discover_commands(project_dir=tmp_path)
        assert "greet" in commands
        assert "Greet the user" in commands["greet"]

    def test_help_prints_without_error(self, capsys):
        Help()
        out = capsys.readouterr().out
        assert "app" in out
        assert "db" in out
        assert "extension" in out
        assert "renus extension codenus/kit" in out
        assert "renus extension --remove codenus/kit" in out

class TestCLIRunner:

    def test_run_empty_argv_shows_help(self, capsys):
        code = run([])
        assert code == 0
        out = capsys.readouterr().out
        assert "app" in out
        assert "db" in out

    def test_run_help_flags(self, capsys):
        for flag in ("--help", "-h", "help"):
            code = run(["renus", flag])
            assert code == 0
            out = capsys.readouterr().out
            assert "app" in out

    def test_run_version_flags(self, capsys):
        for flag in ("--version", "-v", "version"):
            code = run(["renus", flag])
            assert code == 0
            out = capsys.readouterr().out
            assert "renus 3.0.0" in out

    def test_run_unknown_command_suggests_match(self, capsys):
        code = run(["renus", "extensio"])
        assert code == 1
        out = capsys.readouterr().out
        assert "Command 'extensio' not found" in out
        assert "Did you mean: extension?" in out

    def test_execute_class_based_command(self):
        class MyCustomCommand(BaseCommand):
            name = "custom"
            description = "Custom test command"

            def run(self, args: list[str] | None = None) -> int:
                return 42

        assert execute_handler(MyCustomCommand, ["foo"]) == 42

class TestCreateProject:

    def test_constants(self):
        assert TEMPLATES == ("api", "mvp", "extension")
        assert DATABASES == ("mongodb", "mysql", "sqlite", "none")

    def test_sanitize_and_package_name(self):
        assert sanitize("  Example ") == "example"
        assert sanitize("!!!") == "myproject"
        assert package_name("my app") == "my_app"
        assert package_name("proj") == "proj"

    @pytest.mark.parametrize("template", ["api"])
    @pytest.mark.parametrize("database", DATABASES)
    def test_generates_runnable_project(self, tmp_path, monkeypatch, template, database):
        monkeypatch.chdir(tmp_path)
        name = f"gen_{template}_{database.replace('none', 'no')}"
        rc = create_run([name, template, database])
        assert rc == 0
        project_root = tmp_path / name
        assert (project_root / "README.md").exists()
        assert (project_root / "__init__.py").exists()
        assert (project_root / "main.py").exists()
        assert not (project_root / "controllers.py").exists()
        assert not (project_root / "routes.py").exists()
        import ast
        ast.parse((project_root / "main.py").read_text())

    def test_generate_api_sqlite_has_adapter_and_decorated_routes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = create_run(["webapi", "api", "sqlite"])
        assert rc == 0
        main = (tmp_path / "webapi" / "main.py").read_text()
        assert "SQLiteAdapter" in main
        assert '@app.get("/items")' in main
        assert '@app.get("/items/{id}")' in main
        assert 'from webapi.' not in main

    def test_generate_none_has_no_database(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = create_run(["nodb", "api", "none"])
        assert rc == 0
        project_root = tmp_path / "nodb"
        main = (project_root / "main.py").read_text()

        assert "from renus.db" not in main
        assert '@app.get("/ping")' in main
        assert not (project_root / "app.py").exists()
        assert not (project_root / "models.py").exists()
        assert not (project_root / "controllers.py").exists()
        assert not (project_root / "routes.py").exists()

    @pytest.mark.parametrize("database", ["sqlite", "mongodb", "mysql"])
    def test_generated_database_api_uses_one_main_file(self, tmp_path, monkeypatch, database):
        monkeypatch.chdir(tmp_path)
        project_root = tmp_path / f"single_{database}"
        assert create_run([f"single_{database}", "api", database]) == 0
        main = (project_root / "main.py").read_text()
        assert "app = App(" in main
        assert "class Item(Model):" in main
        assert '@app.get("/items")' in main
        assert '@app.post("/items")' in main
        assert '@app.put("/items/{id}")' in main
        assert '@app.delete("/items/{id}")' in main
        assert not (project_root / "app.py").exists()
        assert not (project_root / "models.py").exists()
        assert not (project_root / "controllers.py").exists()
        assert not (project_root / "routes.py").exists()

    def test_create_aborts_on_existing_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "exists").mkdir()
        (tmp_path / "exists" / "a.txt").write_text("x")
        rc = create_run(["exists", "api", "sqlite"])
        assert rc == 1

    def test_mvp_fetches_project_from_git(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetched: dict[str, str] = {}

        def fake_fetch(dest, repo=create_module.MVP_REPO_URL, branch=create_module.MVP_REPO_BRANCH):
            fetched["dest"] = dest
            fetched["repo"] = repo
            os.makedirs(dest, exist_ok=True)
            Path(dest, "main.py").write_text("# codenus starter\n")
            Path(dest, "README.md").write_text("# codenus\n")
            return True

        monkeypatch.setattr(create_module, "fetch_project", fake_fetch)
        rc = create_run(["mvpapp", "mvp", "sqlite"])

        assert rc == 0
        project = tmp_path / "mvpapp"
        assert (project / "main.py").exists()
        assert (project / "README.md").exists()
        assert fetched["dest"] == str(project)
        assert fetched["repo"] == create_module.MVP_REPO_URL
        database_config = (project / "config" / "database.py").read_text()
        requirements = (project / "requirements.txt").read_text()
        assert "SQLiteAdapter" in database_config
        assert '"database": "./mvpapp.db"' in database_config
        assert "renus[server]" in requirements

    @pytest.mark.parametrize(
        ("database", "adapter", "requirement"),
        [
            ("sqlite", "SQLiteAdapter", "renus[server]"),
            ("mongodb", "MongoDBAdapter", "renus[server,mongo]"),
            ("mysql", "MySQLAdapter", "renus[server,mysql]"),
        ],
    )
    def test_mvp_configures_selected_database(
        self, tmp_path, monkeypatch, database, adapter, requirement
    ):
        monkeypatch.chdir(tmp_path)

        def fake_fetch(dest, repo=create_module.MVP_REPO_URL, branch=create_module.MVP_REPO_BRANCH):
            Path(dest).mkdir(parents=True, exist_ok=True)
            Path(dest, "config").mkdir()
            Path(dest, "config", "database.py").write_text("old adapter config\n")
            Path(dest, "requirements.txt").write_text("renus[server,mongo]\nPillow\n")
            return True

        monkeypatch.setattr(create_module, "fetch_project", fake_fetch)
        assert create_run([f"starter_{database}", "mvp", database]) == 0

        project = tmp_path / f"starter_{database}"
        database_config = (project / "config" / "database.py").read_text()
        requirements = (project / "requirements.txt").read_text()
        assert adapter in database_config
        assert requirement in requirements
        assert "Pillow" in requirements
        if database != "mongodb":
            assert "MongoDBAdapter" not in database_config
        compile(database_config, str(project / "config" / "database.py"), "exec")

    def test_database_less_mvp_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert create_run(["nodbmvp", "mvp", "none"]) == 1
        assert not (tmp_path / "nodbmvp").exists()

    def test_mvp_fetch_failure_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(create_module, "fetch_project", lambda *a, **k: False)
        assert create_run(["nomvp", "mvp", "sqlite"]) == 1

    def test_extension_template_adds_local_command_to_mvp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def fake_fetch(dest, repo=create_module.MVP_REPO_URL, branch=create_module.MVP_REPO_BRANCH):
            Path(dest).mkdir(parents=True, exist_ok=True)
            Path(dest, "main.py").write_text("# MVP scaffold\\n")
            return True

        monkeypatch.setattr(create_module, "fetch_project", fake_fetch)
        assert create_run(["extensionapp", "extension", "sqlite"]) == 0

        project = tmp_path / "extensionapp"
        command = project / "commands" / "local" / "run.py"
        command_source = command.read_text(encoding="utf-8")
        compile(command_source, str(command), "exec")
        assert (project / "main.py").exists()
        assert (project / "commands" / "__init__.py").exists()
        assert (project / "commands" / "local" / "__init__.py").exists()
        database_config = (project / "config" / "database.py").read_text()
        requirements = (project / "requirements.txt").read_text()
        assert "SQLiteAdapter" in database_config
        assert "renus[server]" in requirements
        assert "def _create_extension" in command_source
        assert '"-new-extension": "new-extension"' in command_source
        assert "def _install_local" in command_source

    def test_archive_url_is_derived_from_repo(self):
        assert create_module._archive_url() == (
            "https://codeload.github.com/kak-smko/codenus/tar.gz/refs/heads/master"
        )

    def test_clone_project_without_git_returns_false(self, monkeypatch):
        monkeypatch.setattr(create_module.shutil, "which", lambda name: None)
        assert create_module.clone_project(create_module.MVP_REPO_URL, "/tmp/unused") is False

    def test_download_project_extracts_repo_root(self, tmp_path, monkeypatch):
        import io
        import tarfile

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for member_name, data in (
                ("codenus-master/main.py", b"print('hi')\n"),
                ("codenus-master/app/__init__.py", b""),
            ):
                info = tarfile.TarInfo(member_name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        payload = buffer.getvalue()

        class _Response:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(create_module.urllib.request, "urlopen", lambda *a, **k: _Response())
        dest = tmp_path / "fetched"

        assert create_module.download_project(create_module.MVP_REPO_URL, str(dest)) is True
        assert (dest / "main.py").read_text() == "print('hi')\n"
        assert (dest / "app" / "__init__.py").exists()

class TestAppScaffolding:

    def test_to_camel_case(self):
        assert to_camel_case("user_profile") == "UserProfile"
        assert to_camel_case("post") == "Post"

    def test_to_plural_comprehensive(self):

        assert to_plural("category") == "categories"
        assert to_plural("city") == "cities"
        assert to_plural("day") == "days"
        assert to_plural("boy") == "boys"

        assert to_plural("knife") == "knives"
        assert to_plural("life") == "lives"
        assert to_plural("wife") == "wives"

        assert to_plural("leaf") == "leaves"
        assert to_plural("half") == "halves"

        assert to_plural("bus") == "buses"
        assert to_plural("box") == "boxes"
        assert to_plural("buzz") == "buzzes"
        assert to_plural("church") == "churches"
        assert to_plural("dish") == "dishes"

        assert to_plural("focus") == "foci"
        assert to_plural("cactus") == "cacti"

        assert to_plural("post") == "posts"
        assert to_plural("user") == "users"

    def test_add_temp_generates_model_validation_and_repository(self, tmp_path):
        add_temp(
            name="article",
            names="articles",
            name_camel="Article",
            names_camel="Articles",
            name_db="articles",
            folder=[],
            base_dir=str(tmp_path),
        )

        app_dir = tmp_path / "app" / "article"
        assert (app_dir / "controller.py").exists()
        assert (app_dir / "model.py").exists()
        assert (app_dir / "route.py").exists()
        assert (tmp_path / "frontend" / "admin" / "src" / "views" / "article.vue").exists()

        ctrl_code = (app_dir / "controller.py").read_text()

        assert "request.db.repository(Article)" in ctrl_code
        assert "self.repo:Repository[Article]" in ctrl_code
        assert "table = Table(Article, self.request)" in ctrl_code
        assert "return JsonResponse(await table.index())" in ctrl_code
        assert "payload = Article(dict(payload))" in ctrl_code
        assert "await self.repo.create(payload)" in ctrl_code
        assert "payload = Validate(Article,dict(payload),None)" in ctrl_code
        assert "await self.repo.where(Article.id == id).update(payload)" in ctrl_code
        assert "await self.repo.delete(Article.id == id)" in ctrl_code

        model_code = (app_dir / "model.py").read_text()

        assert "class Article(Model):" in model_code
        assert "from renus.db import DatabaseField, Field, Model" in model_code
        assert "id: str = Field(database=DatabaseField(primary_key=True))" in model_code
        assert "class Meta:" in model_code
        assert "timestamps = True" in model_code
        assert 'soft_delete = True' in model_code


    @staticmethod
    def _count_in(text: str, needle: str) -> int:
        return text.count(needle)

    def test_route_generation_with_and_without_kit_extension(self, tmp_path):

        add_temp(
            name="tag",
            names="tags",
            name_camel="Tag",
            names_camel="Tags",
            name_db="tags",
            folder=[],
            base_dir=str(tmp_path),
        )
        plain_route = (tmp_path / "app" / "tag" / "route.py").read_text()
        assert "router = Router()" in plain_route
        assert 'router.include(admin_router)' in plain_route

        kit_ext_dir = tmp_path / "app" / "extension" / "codenus" / "kit"
        kit_ext_dir.mkdir(parents=True)
        (kit_ext_dir / "middlewares").mkdir()
        (kit_ext_dir / "middlewares" / "auth.py").write_text("# kit auth middleware\n")

        add_temp(
            name="order",
            names="orders",
            name_camel="Order",
            names_camel="Orders",
            name_db="orders",
            folder=[],
            base_dir=str(tmp_path),
        )
        kit_route = (tmp_path / "app" / "order" / "route.py").read_text()
        assert "from app.extension.codenus.kit.middlewares.auth import AuthMiddleware" in kit_route
        assert "from app.extension.codenus.kit.middlewares.permission import PermissionMiddleware" in kit_route
        assert "AuthMiddleware" in kit_route
        assert 'PermissionMiddleware("admin")' in kit_route
        assert "router.include(admin_router)" in kit_route
        assert "router.include(user_router)" in kit_route
        assert "router.include(home_router)" in kit_route

    def test_app_run_cli(self, tmp_path):
        code = app_run(["invoice"], base_dir=str(tmp_path))
        assert code == 0
        assert (tmp_path / "app" / "invoice" / "controller.py").exists()
        assert (tmp_path / "app" / "invoice" / "model.py").exists()
        routes_index = (tmp_path / "routes" / "api.py").read_text()
        assert "from app.invoice.route import router as invoice_route" in routes_index
        assert "router.include(invoice_route)" in routes_index

class TestGeneratedScaffoldRunsAgainstDatabase:

    @pytest.mark.asyncio
    async def test_generated_model_supports_repository_crud(self, tmp_path):
        add_temp(
            name="widget",
            names="widgets",
            name_camel="Widget",
            names_camel="Widgets",
            name_db="widgets",
            folder=[],
            base_dir=str(tmp_path),
        )

        model_path = tmp_path / "app" / "widget" / "model.py"
        spec = importlib.util.spec_from_file_location("scaffold_widget_model", model_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)

        widget = mod.Widget

        validated = widget({"id": "w1", "name": "gadget"})
        assert validated.name == "gadget"
        assert widget.__db_metadata__.table == "widgets"

        db = Database(SQLiteAdapter({"database": ":memory:"}))
        await db.connect()
        await db.create_schema([widget])

        repo = db.repository(widget)
        await repo.create(widget(id="w1", name="gadget"))
        await repo.create(widget(id="w2", name="thing"))

        rows = [dict(r) for r in await repo.query().all()]
        assert {r["id"] for r in rows} == {"w1", "w2"}

        await repo.update(widget.id == "w1", values={"name": "doohickey"})
        loaded = (await repo.query().where(widget.id == "w1").all())[0]
        assert loaded.name == "doohickey"

        await repo.delete(widget.id == "w2")
        remaining = await repo.query().all()
        assert len(remaining) == 1
        assert remaining[0].id == "w1"

        await db.disconnect()

class TestDatabaseAndDbModel:

    def test_mongo_json_encoder_and_decoder(self):
        now = datetime.datetime(2026, 9, 5, 12, 0, 0)
        sample = {
            "name": "Renus",
            "date": now,
            "int_val": 42,
        }
        encoded = json.dumps(sample, cls=MongoJSONEncoder)
        decoded = json.loads(encoded, object_hook=mongo_json_decoder)
        assert decoded["name"] == "Renus"
        assert decoded["int_val"] == 42
        assert isinstance(decoded["date"], datetime.datetime)

    @pytest.mark.asyncio
    async def test_paginated_backup_and_restore_with_db_model(self, tmp_path):
        db_file = str(tmp_path / "store.sqlite")
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT);")
        for i in range(25):
            conn.execute(f"INSERT INTO products (name) VALUES ('Product-{i}');")
        conn.commit()
        conn.close()

        Config._cache["database"] = SimpleNamespace(driver="sqlite", database=db_file)

        register_adapter("sqlite", SQLiteAdapter)

        backup_dir = str(tmp_path / "db_backup")
        backed_up = await backup_table_paginated("products", path=backup_dir, per_page=10)
        assert backed_up == 25
        assert (tmp_path / "db_backup" / "products.json").exists()

        await delete_all_records("products")
        conn = sqlite3.connect(db_file)
        count = conn.execute("SELECT count(*) FROM products;").fetchone()[0]
        conn.close()
        assert count == 0

        json_file = str(tmp_path / "db_backup" / "products.json")
        restored = await restore_table_paginated("products", file_path=json_file, chunk_size=10)
        assert restored == 25

        conn = sqlite3.connect(db_file)
        count = conn.execute("SELECT count(*) FROM products;").fetchone()[0]
        conn.close()
        assert count == 25

class TestExtensionCommands:

    def test_parse_version_tuple_and_is_upgrade(self):
        assert parse_version_tuple("1.2.3") == (1, 2, 3)
        assert parse_version_tuple("v2.0.1") == (2, 0, 1)

        assert is_upgrade("1.2.0", "1.1.0") is True
        assert is_upgrade("2.0.0", "1.9.9") is True
        assert is_upgrade("1.0.0", "1.0.0") is False
        assert is_upgrade("1.0.0", "1.2.0") is False

    def test_match_version_wildcards(self):
        available = ["1.0.0", "1.1.0", "1.2.0", "1.2.3", "1.2.8", "1.9.0", "2.0.0", "2.1.0"]

        assert match_version("*", available) == "2.1.0"

        assert match_version("1.*", available) == "1.9.0"

        assert match_version("1.2.*", available) == "1.2.8"

        assert match_version("1.2.3", available) == "1.2.3"

    def test_download_resolves_wildcard_before_requesting_zip(self, tmp_path):
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("install.py", "")
        responses = iter(
            [
                (200, {}, b'["1.0.0"]'),
                (200, {"version": "1.0.0"}, archive.getvalue()),
            ]
        )
        requested_urls = []

        def fake_http_get(url, timeout=30):
            requested_urls.append(url)
            return next(responses)

        with (
            patch.object(extension_run_module, "http_get", side_effect=fake_http_get),
            patch.object(extension_run_module, "install_app"),
        ):
            result = download(
                "codenus/kit",
                "1.*",
                {},
                base_dir=str(tmp_path),
            )

        assert result == "1.0.0"
        assert requested_urls == [
            "https://codenus.com/app/versions/codenus/kit",
            "https://codenus.com/app/codenus/kit/1.0.0",
        ]

    def test_download_fails_cleanly_when_wildcard_cannot_be_resolved(self, tmp_path):
        with patch.object(extension_run_module, "get_available_versions", return_value=[]):
            result = download(
                "codenus/kit",
                "1.*",
                {},
                base_dir=str(tmp_path),
            )

        assert result is None
        assert not (tmp_path / "extension").exists()

    def test_extension_command_returns_failure_when_download_fails(self, tmp_path):
        with (
            patch.object(extension_run_module, "load_apps", return_value={}),
            patch.object(extension_run_module, "load_installed", return_value={}),
            patch.object(extension_run_module, "download", return_value=None),
            patch.object(extension_run_module, "write_lock"),
        ):
            result = extension_run(["codenus/kit==1.*"], base_dir=str(tmp_path))

        assert result == 1

    def test_http_get_retries_transient_network_failures(self):
        from urllib.error import URLError

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "text/plain"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"ok"

        with (
            patch.object(
                extension_run_module.urllib.request,
                "urlopen",
                side_effect=[URLError("temporarily unavailable"), FakeResponse()],
            ) as mock_urlopen,
            patch.object(extension_run_module.time, "sleep"),
        ):
            status, headers, body = extension_run_module.http_get(
                "https://example.test/archive.zip"
            )

        assert mock_urlopen.call_count == 2
        assert status == 200
        assert headers == {"content-type": "text/plain"}
        assert body == b"ok"

    def test_manifest_and_lock_json_round_trip(self, tmp_path):
        (tmp_path / "extension.json").write_text(
            '{"apps": {"codenus/kit": "1.2.*"}}', encoding="utf-8"
        )
        assert load_apps(base_dir=str(tmp_path)) == {"codenus/kit": "1.2.*"}

        installed = {"codenus/kit": "1.2.3", "codenus/blog": "0.1.0"}
        write_lock(installed, base_dir=str(tmp_path))
        assert (tmp_path / "extension-lock.json").exists()
        assert load_installed(base_dir=str(tmp_path)) == installed

        assert load_apps(base_dir=str(tmp_path / "nope")) == {}
        assert load_installed(base_dir=str(tmp_path / "nope")) == {}

    def test_extension_route_scaffold_uses_kit_extension_name_alias(self, tmp_path):
        install = SimpleNamespace(route="codenus.kit.routes")
        _add_route(install, "codenus/kit", base_dir=str(tmp_path))

        route_source = (
            tmp_path / "app" / "extension" / "codenus" / "kit" / "route.py"
        ).read_text()
        assert "router as codenus_kit_router" in route_source
        assert "router.include(codenus_kit_router)" in route_source
        routes_index = (tmp_path / "routes" / "api.py").read_text()
        assert "router.include(codenus_kit_route)" in routes_index

    def test_extension_route_removal_removes_index_mount(self, tmp_path):
        install = SimpleNamespace(route="codenus.kit.routes")
        _add_route(install, "codenus/kit", base_dir=str(tmp_path))
        from renus.commands.extension.build import _remove_route

        _remove_route(install, "codenus/kit", base_dir=str(tmp_path))
        routes_index = (tmp_path / "routes" / "api.py").read_text()
        assert "codenus_kit_route" not in routes_index

    def test_update_vs_upgrade_modes(self):
        mock_install = MagicMock()
        mock_install.update = MagicMock()
        mock_install.upgrade = MagicMock()
        mock_install.setup = MagicMock()
        mock_install.cls = [("my_cls", "base_pkg", "BaseClass", "SubClass")]

        mock_install.route = ""
        mock_install.imprt = ""
        mock_install.command = ""
        mock_install.admin_templates = ""
        mock_install.index_templates = ""
        mock_install.component_templates = ""
        mock_install.config = ""
        mock_install.dependencies = ()

        with (
            patch("importlib.import_module", return_value=mock_install),
            patch.object(extension_run_module, "_add_cls") as mock_add_cls,
        ):
            install_app("codenus/test_pkg", installed={}, mode="update")
            mock_install.update.assert_called_once()
            mock_install.upgrade.assert_not_called()
            mock_install.setup.assert_not_called()
            mock_add_cls.assert_not_called()

        mock_install.reset_mock()
        with (
            patch("importlib.import_module", return_value=mock_install),
            patch.object(extension_run_module, "_add_cls") as mock_add_cls,
        ):
            install_app("codenus/test_pkg", installed={}, mode="upgrade")
            mock_install.upgrade.assert_called_once()
            mock_install.update.assert_not_called()
            mock_install.setup.assert_not_called()
            mock_add_cls.assert_called_once()

    def test_no_requests_library_in_commands(self):
        import renus.commands.app.run
        import renus.commands.base
        import renus.commands.db.run
        import renus.commands.extension.run
        import renus.commands.help
        import renus.commands.cli
        import renus.commands.run

        modules = [
            renus.commands.app.run,
            renus.commands.base,
            renus.commands.cli,
            renus.commands.db.run,
            renus.commands.extension.run,
            renus.commands.help,
            renus.commands.run,
        ]
        for mod in modules:
            assert "requests" not in sys.modules or not hasattr(mod, "requests")
