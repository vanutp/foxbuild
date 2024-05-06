from time import time

import asyncio
from pathlib import Path

from foxbuild.runner import Runner

s = time()
res = asyncio.run(Runner(Path('data/runs/24610014884').absolute()).run_check())
print(f'Run took {int((time() - s) * 1000)} ms')
print(res[1][0]['stderr'])
