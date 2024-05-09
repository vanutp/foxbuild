from time import time

import asyncio
from pathlib import Path

from foxbuild.runner import Runner

s = time()
runner = Runner(Path('/home/fox/playground/tgpy_test').absolute(), None)
res = asyncio.run(runner.run())
print(f'Run took {int((time() - s) * 1000)} ms')
print(res)
