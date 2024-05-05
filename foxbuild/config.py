from joserfc.rfc7518.rsa_key import RSAKey
from pathlib import Path
from pydantic import BeforeValidator, AfterValidator, field_validator, Field
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings
from typing import Annotated


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

    use_sandbox: bool = True

    gh_app_id: int
    gh_key: Annotated[RSAKey, BeforeValidator(lambda data: RSAKey.import_key(data))]

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
        if v is None:
            dirname = info.field_name.removesuffix('_dir').replace('_', '-')
            res = info.data['data_dir'] / dirname
        else:
            res = v
        if info.field_name != 'global_profile_dir':
            res.mkdir(parents=True, exist_ok=True)
        return res


config = Config(_env_file='.env')
(config.profiles_dir / 'tmp').parent.mkdir(exist_ok=True)

__all__ = ['config']
