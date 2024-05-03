from time import time

import asyncio
from pathlib import Path

from foxbuild.runner import run_check

s = time()
asyncio.run(run_check(Path('tmp/24573239854')))
print(f'Run took {int((time() - s) * 1000)} ms')
