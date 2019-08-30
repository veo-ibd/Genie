import logging
import os

import synapseclient

from .example_filetype_format import FileTypeFormat

logger = logging.getLogger(__name__)


class workflow(FileTypeFormat):

    _fileType = "md"

    _process_kwargs = ["databaseSynId"]

    def _validateFilename(self):
        assert os.path.basename(self.file_path_list[0]).startswith(self.center) and \
               os.path.basename(self.file_path_list[0]).endswith(".md")

    def process_steps(self, databaseSynId):
        self.syn.store(synapseclient.File(self.file_path_list[0], parent=databaseSynId))
