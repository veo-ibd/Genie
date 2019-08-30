from __future__ import absolute_import
from .bed import bed
import os
import logging
logger = logging.getLogger(__name__)


class bedSP(bed):

    _fileType = "bedSP"

    def _validateFilename(self):
        assert os.path.basename(self.file_path_list[0]).startswith(
            "nonGENIE_%s-" % self.center) and \
               os.path.basename(self.file_path_list[0]).endswith(".bed")
