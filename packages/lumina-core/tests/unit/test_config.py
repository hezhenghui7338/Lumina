"""Config path resolution."""

from lumina_core.config import bundle_root, load_models_config


def test_load_models_config_from_dev_tree():
    cfg = load_models_config()
    assert cfg.summarize.model == "qwen3.5:4b"


def test_bundle_root_none_in_dev():
    assert bundle_root() is None
