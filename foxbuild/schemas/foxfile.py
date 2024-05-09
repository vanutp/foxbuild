from pathlib import Path
from pydantic import BaseModel, StringConstraints, field_validator, Field
from pydantic_core.core_schema import ValidationInfo
from typing import Annotated


class EnvSettings:
    use_flake: str | bool | None = None
    nixpkgs: str | None = None
    packages: (
        list[Annotated[str, StringConstraints(pattern=r'[a-zA-Z_][\w\-]+')]] | None
    ) = None
    image: str | None = None

    @field_validator('use_flake')
    @classmethod
    def v_use_flake(cls, v: str | bool, info: ValidationInfo):
        if v is True:
            res = '.'
        elif not v:
            return v
        else:
            res = v
        path, *_ = res.split('#', 1)
        basedir = Path('/meow')
        resolved = (basedir / path).resolve()
        if not resolved.is_relative_to(basedir):
            raise ValueError('path must be relative')
        if info.data.get('nixpkgs'):
            raise ValueError('nixpkgs is incompatible with use_flake')
        if info.data.get('packages'):
            raise ValueError('packages is incompatible with use_flake')
        return res


class _ConditionSettings:
    if_: Annotated[str, Field(alias='if')] | None = None


class StageDef(EnvSettings, _ConditionSettings, BaseModel):
    needs: str | None = None
    run: str


class WorkflowDef(_ConditionSettings, BaseModel):
    stages: list[str]


class Foxfile(EnvSettings, BaseModel):
    nix_paths: list[str] | None = ['flake.nix', 'flake.lock', 'shell.nix']
    stages: dict[str, StageDef]
    workflows: dict[str, WorkflowDef]
