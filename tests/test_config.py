from types import SimpleNamespace
from unittest.mock import patch

import pytest

from renus.config.config import Config, _as_mapping, _load_module, _traverse

@pytest.fixture(autouse=True)
def reset_config_cache():
    Config._cache = {}
    Config._lock = __import__("threading").RLock()
    yield
    Config._cache = {}

def _seed(name, data):
    Config._cache[name] = data
    return Config(name)

class TestLoadModule:

    def test_imports_real_module(self):
        with patch.object(
            __import__("importlib"), "import_module", return_value=object()
        ) as imp:
            assert _load_module("app") is imp.return_value

    def test_missing_module_degrades_to_empty_dict(self):
        result = _load_module("does_not_exist_anywhere")
        assert result == {}
        assert isinstance(result, dict)

class TestTraverse:

    def test_resolves_nested_namespace(self):
        obj = SimpleNamespace(a=SimpleNamespace(b=SimpleNamespace(c=1)))
        assert _traverse(obj, ("a", "b", "c")) == 1

    def test_missing_attribute_returns_sentinel(self):
        assert _traverse({}, ("missing",)) is _traverse({}, ("also", "missing",))

class TestAsMapping:

    def test_mapping_passthrough(self):
        assert _as_mapping({"k": 1}) == {"k": 1}

    def test_namespace_vars(self):
        assert _as_mapping(SimpleNamespace(x=1)) == {"x": 1}

    def test_other_types_are_none(self):
        assert _as_mapping("nope") is None
        assert _as_mapping(42) is None

class TestConfigCache:

    def test_construct_on_cold_miss_loads_and_caches(self):
        loaded = {"debug": True}
        with patch(
            "renus.config.config._load_module", return_value=loaded
        ) as load:
            cfg = Config("app")

        assert cfg.loaded is loaded
        assert Config._cache["app"] is loaded
        load.assert_called_once_with("app")

    def test_repeated_construction_hits_cache_no_reimport(self):
        loaded = {"debug": True}
        with patch("renus.config.config._load_module", return_value=loaded) as load:
            Config("app")
            cfg2 = Config("app")

        assert cfg2.loaded is loaded
        load.assert_called_once_with("app")

    def test_cache_is_shared_across_instances(self):
        _seed("shared", {"v": 1})
        assert Config("shared").loaded == {"v": 1}

class TestConfigGet:

    def test_plain_read(self):
        cfg = _seed("app", SimpleNamespace(debug=True))
        assert cfg.get("debug") is True

    def test_dotted_key_read(self):
        ns = SimpleNamespace(db=SimpleNamespace(replica_uri="mongodb://rs"))
        cfg = _seed("app", ns)
        assert cfg.get("db.replica_uri") == "mongodb://rs"

    def test_missing_with_default(self):
        cfg = _seed("app", {})
        assert cfg.get("nope", "fallback") == "fallback"

    def test_missing_without_default_returns_none(self):
        cfg = _seed("app", {})
        assert cfg.get("nope") is None

    def test_default_ignores_second_positional(self):
        cfg = _seed("app", {})
        assert cfg.get("nope", "first", "second") == "first"

class TestConfigAttrs:

    def test_getattr_shortcut(self):
        cfg = _seed("app", SimpleNamespace(debug=False))
        assert cfg.debug is False

    def test_getattr_missing_raises(self):
        cfg = _seed("app", {})
        with pytest.raises(AttributeError):
            cfg.missing_attr

    def test_getitem(self):
        ns = SimpleNamespace(nested=SimpleNamespace(k=7))
        cfg = _seed("app", ns)
        assert cfg["nested.k"] == 7

    def test_getitem_missing_raises_keyerror(self):
        cfg = _seed("app", {})
        with pytest.raises(KeyError):
            cfg["missing"]

class TestConfigView:

    def test_items_returns_mapping(self):
        cfg = _seed("app", {"a": 1})
        assert cfg.items() == {"a": 1}

    def test_snapshot_returns_plain_dict(self):
        cfg = _seed("app", {"a": 1, "b": {"c": 2}})
        snap = cfg.snapshot()
        assert snap == {"a": 1, "b": {"c": 2}}
        assert type(snap) is dict

    def test_snapshot_empty_namespace(self):
        cfg = _seed("app", {})
        assert cfg.snapshot() == {}

class TestConfigName:

    def test_name_is_kept_on_instance(self):
        cfg = _seed("my.config", {"v": 1})
        assert cfg.name == "my.config"
