# Import logging last to not take in synapseclient logging
import logging

from . import process_functions

from .__version__ import __version__

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
