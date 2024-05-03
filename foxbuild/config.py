from joserfc.rfc7518.rsa_key import RSAKey
from pathlib import Path
from pydantic import BeforeValidator, AfterValidator
from pydantic_settings import BaseSettings
from typing import Annotated


class Config(BaseSettings):
    host: str
    port: int
    debug: bool = False

    tmp_dir: Annotated[Path, AfterValidator(lambda path: path.absolute())]

    gh_app_id: int
    gh_key: Annotated[RSAKey, BeforeValidator(lambda data: RSAKey.import_key(data))]


config = Config(_env_file='.env')
config.tmp_dir.mkdir(exist_ok=True)

__all__ = ['config']
