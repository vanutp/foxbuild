import asyncio
import os.path
from asyncio import create_subprocess_exec

import json
import logging
import re
import shutil
import yaml
from hashlib import sha1
from pathlib import Path
from pydantic import ValidationError
from subprocess import PIPE, DEVNULL
from tempfile import TemporaryDirectory
from yaml import YAMLError

from foxbuild.config import config, OperationMode
from foxbuild.const import DEFAULT_IMAGE, SANDBOX_WORKDIR
from foxbuild.exceptions import ConfigurationError
from foxbuild.sandbox import Sandbox
from foxbuild.schemas import StageResult, StandaloneRunInfo, WorkflowResult, RunResult
from foxbuild.schemas.foxfile import Foxfile, StageDef, WorkflowDef, EnvSettings
from foxbuild.utils import async_check_output, NIX, BASH, JQ, GIT


async def checkout_repo(run_info: StandaloneRunInfo, at: str | Path):
    repo_path = config.repos_dir / run_info.provider / run_info.repo_name
    if repo_path.is_dir():
        await async_check_output(
            GIT, 'remote', 'set-url', 'origin', run_info.clone_url, cwd=repo_path
        )
        await async_check_output(GIT, 'fetch', cwd=repo_path)
    else:
        repo_path.mkdir(parents=True)
        await async_check_output(
            GIT,
            'clone',
            '--mirror',
            run_info.clone_url,
            '.',
            cwd=repo_path,
        )
    await async_check_output(
        GIT,
        'clone',
        repo_path,
        '.',
        cwd=at,
    )
    await async_check_output(
        GIT,
        'switch',
        '-d',
        run_info.commit_sha,
        cwd=at,
    )
