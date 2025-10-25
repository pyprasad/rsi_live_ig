import logging, sys

def setup_logging(level="INFO"):
    lvl = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("live")
    logger.setLevel(lvl)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        f = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%H:%M:%S")
        h.setFormatter(f)
        logger.addHandler(h)
    return logger
