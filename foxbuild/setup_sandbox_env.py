import logging
import os.path

from pathlib import Path
from tempfile import TemporaryDirectory

from foxbuild.config import config
from foxbuild.utils import async_check_output, NIX, get_sandbox_prefix

logger = logging.getLogger(__name__)

ENV_DIR = Path(__file__).absolute().parent.parent / 'env'


async def setup_sandbox_env():
    if not config.use_sandbox:
        raise ValueError('Set USE_SANDBOX=True first')

    if config.global_profile_dir.exists():
        if not config.global_profile_dir.is_symlink():
            raise ValueError('Global profile directory must be a symlink')
        config.global_profile_dir.unlink()

    logger.info('Creating profile')
    with TemporaryDirectory() as tempdir:
        tmp_profile = os.path.join(tempdir, 'profile')
        await async_check_output(
            NIX,
            'profile',
            'install',
            '--profile',
            tmp_profile,
            str(ENV_DIR),
            cwd=ENV_DIR,
        )

        await async_check_output(
            NIX,
            'build',
            '--out-link',
            str(config.global_profile_dir),
            tmp_profile,
            cwd=ENV_DIR,
        )

    logger.info('Updating nix cache')
    sandbox_prefix = get_sandbox_prefix(writable_nix_cache=True)
    await async_check_output(
        *sandbox_prefix,
        'bash',
        '-c',
        'nix eval --raw nixpkgs#hello && nix eval --raw poetry2nix',
        cwd=config.empty_dir
    )
