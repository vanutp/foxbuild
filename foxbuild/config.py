import sys

import enum
import os
import yaml
from enum import Enum
from joserfc.rfc7518.rsa_key import RSAKey
from pathlib import Path
from pydantic import BeforeValidator, AfterValidator, field_validator
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings
from typing import Annotated


class OperationMode(Enum):
    local = enum.auto()
    standalone = enum.auto()


class Config(BaseSettings):
    host: str
    port: int
    debug: bool = False

    data_dir: Annotated[Path, AfterValidator(lambda path: path.absolute())]
    runs_dir: Path = None
    repos_dir: Path = None
    profiles_dir: Path = None
    global_profile_dir: Path = None
    nix_cache_dir: Path = None
    empty_dir: Path = None

    mode: OperationMode = None
    always_use_sandbox: bool = None

    gh_app_id: int | None = None
    gh_key: (
        Annotated[RSAKey, BeforeValidator(lambda data: RSAKey.import_key(data))] | None
    ) = None

    # noinspection PyNestedDecorators
    @field_validator('mode', mode='before')
    @classmethod
    def default_mode(cls, v: Path | None):
        if v is not None:
            return v
        if len(sys.argv) > 1 and sys.argv[1] == 'server':
            return OperationMode.standalone
        else:
            return OperationMode.local

    # noinspection PyNestedDecorators
    @field_validator('always_use_sandbox', mode='before')
    @classmethod
    def default_always_use_sandbox(cls, v: Path | None, info: ValidationInfo):
        if v is not None:
            return v
        return info.data['mode'] == OperationMode.standalone

    # noinspection PyNestedDecorators
    @field_validator(
        'runs_dir',
        'repos_dir',
        'profiles_dir',
        'global_profile_dir',
        'nix_cache_dir',
        'empty_dir',
        mode='before',
    )
    @classmethod
    def default_dirs(cls, v: Path | None, info: ValidationInfo):
        if 'data_dir' not in info.data:
            # pydantic won't show errors until everything is validated
            # we don't want to show all _dir fields as errored if data_dir is not set
            return ''
        if v is None:
            dirname = info.field_name.removesuffix('_dir').replace('_', '-')
            res = info.data['data_dir'] / dirname
        else:
            res = v
        if info.field_name != 'global_profile_dir':
            res.mkdir(parents=True, exist_ok=True)
        return res


config_home = Path(os.getenv('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'))
config_file = config_home / 'foxbuild' / 'config.yml'
if config_file.is_file():
    config_values = yaml.safe_load(config_file.read_text())
else:
    config_values = {}
config = Config(**config_values, _env_file='.env', _env_prefix='FOXBUILD_')
(config.profiles_dir / 'tmp').parent.mkdir(exist_ok=True)

__all__ = ['OperationMode', 'config']
