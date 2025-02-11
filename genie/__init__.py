# Import logging last to not take in synapseclient logging
import logging

from . import process_functions
from . import bed
from . import vcf
from . import bedSP
from . import workflow
from . import clinical
from . import seg
from . import cbs
from . import maf
from . import mafSP
from . import clinicalSP
from . import cna
from . import fusions
from . import sampleRetraction
from . import patientRetraction
# from . import patientCounts
from . import mutationsInCis
# from . import vitalStatus
from . import assay

from .__version__ import __version__

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
