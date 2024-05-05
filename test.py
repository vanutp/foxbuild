from time import time

import asyncio
from pathlib import Path

from foxbuild.runner import run_check

s = time()
res = asyncio.run(run_check(Path('data/runs/24610014884').absolute()))
print(f'Run took {int((time() - s) * 1000)} ms')
print(res[1][0]['stderr'])
