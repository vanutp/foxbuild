import logging

logging.basicConfig(
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    level=logging.INFO,
)
logging.getLogger('foxbuild.runner').setLevel(logging.DEBUG)
logging.getLogger('foxbuild.utils').setLevel(logging.DEBUG)
