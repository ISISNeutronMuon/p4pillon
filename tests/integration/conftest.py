import pytest
import yaml


@pytest.fixture
def ntscalar_config():
    with open("ntscalar_config.yml", "r") as f:
        ntscalar_dict = yaml.load(f, Loader=yaml.SafeLoader)
        f.close()
    return ntscalar_dict
