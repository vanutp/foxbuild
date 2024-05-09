import logging

from foxbuild.config import config

logging.basicConfig(
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    level=logging.INFO,
)
if config.debug:
    logging.getLogger('foxbuild.sandbox').setLevel(logging.DEBUG)
    logging.getLogger('foxbuild.utils').setLevel(logging.DEBUG)
