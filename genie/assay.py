import os
import logging
import subprocess
import yaml

import pandas as pd

from .example_filetype_format import FileTypeFormat
from . import process_functions

logger = logging.getLogger(__name__)


class Assayinfo(FileTypeFormat):
    '''
    Assay information file type
    '''
    _fileType = "assayinfo"

    _process_kwargs = ["newPath", "databaseSynId"]

    def _validateFilename(self, filepath_list):
        assert os.path.basename(filepath_list[0]) == "assay_information.yaml"

    def process_steps(self, assay_info_df, newPath, databaseSynId):
        # databaseSynId = kwargs['databaseSynId']
        # Must pass in a list
        process_assay_info_df = self._process(assay_info_df)
        col = ['SEQ_ASSAY_ID', 'is_paired_end', 'library_selection',
               'library_strategy', 'platform', 'read_length',
               'instrument_model', 'gene_padding', 'number_of_genes',
               'variant_classifications', 'CENTER']
        process_functions.updateData(
            self.syn,
            databaseSynId,
            process_assay_info_df,
            self.center,
            col=col,
            filterByColumn="CENTER",
            toDelete=True)
        process_assay_info_df.to_csv(newPath, sep="\t", index=False)
        return(newPath)

    def _process(self, df):
        '''
        Processing function for Assay information
        - Standardizes SEQ_ASSAY_ID
        - Default 10 for gene_padding
        - Fills in variant_classifications

        Args:
            df: Assay information dataframe

        Returns:
            dataframe: Processed dataframe
        '''
        seq_assay_ids = [
            assay.upper().replace('_', '-') for assay in df['SEQ_ASSAY_ID']]
        df['SEQ_ASSAY_ID'] = seq_assay_ids
        if process_functions.checkColExist(df, "gene_padding"):
            df['gene_padding'] = df['gene_padding'].fillna(10)
            df['gene_padding'] = df['gene_padding'].astype(int)
        else:
            df['gene_padding'] = 10

        if not process_functions.checkColExist(df, "variant_classifications"):
            df['variant_classifications'] = pd.np.nan

        df['CENTER'] = self.center
        return(df)

    def _get_dataframe(self, filepath_list):
        '''
        Takes in yaml file, returns dataframe
        '''
        filepath = filepath_list[0]
        try:
            with open(filepath, 'r') as yamlfile:
                # https://github.com/yaml/pyyaml/wiki/PyYAML-yaml.load(input)-Deprecation
                # Must add this because yaml load deprecation
                panel_info_dict = yaml.load(yamlfile, Loader=yaml.FullLoader)
        except Exception:
            raise ValueError(
                "assay_information.yaml: Can't read in your file. "
                "Please make sure the file is a correctly formatted yaml")
        assay_info_df = pd.DataFrame(panel_info_dict)
        assay_info_df = assay_info_df.transpose()
        assay_info_df['SEQ_ASSAY_ID'] = assay_info_df.index
        assay_info_df.reset_index(drop=True, inplace=True)
        return(assay_info_df)

    def _validate(self, assay_info_df):
        '''
        Validates the values of assay information file

        Args:
            assay_info_df: assay information dataframe

        Returns:
            tuple: error and warning
        '''

        total_error = ""
        warning = ""

        if process_functions.checkColExist(assay_info_df, "SEQ_ASSAY_ID"):
            all_seq_assays = assay_info_df.SEQ_ASSAY_ID.unique()
            if not all([assay.startswith(self.center)
                        for assay in all_seq_assays]):
                total_error += \
                    "Assay_information.yaml: Please make sure your all your" +\
                    " SEQ_ASSAY_IDs start with your center abbreviation.\n"
        else:
            total_error += \
                "Assay_information.yaml: Must have SEQ_ASSAY_ID column.\n"

        read_group_dict = process_functions.get_gdc_data_dictionary(
            "read_group")
        read_group_headers = read_group_dict['properties']

        warn, error = process_functions.check_col_and_values(
            assay_info_df,
            'is_paired_end',
            [True, False],
            filename="Assay_information.yaml",
            required=True)
        warning += warn
        total_error += error

        warn, error = process_functions.check_col_and_values(
            assay_info_df, 'library_selection',
            read_group_headers['library_selection']['enum'],
            filename="Assay_information.yaml",
            required=True)

        warning += warn
        total_error += error
        warn, error = process_functions.check_col_and_values(
            assay_info_df,
            'library_strategy',
            read_group_headers['library_strategy']['enum'],
            filename="Assay_information.yaml",
            required=True)

        warning += warn
        total_error += error
        warn, error = process_functions.check_col_and_values(
            assay_info_df,
            'platform',
            read_group_headers['platform']['enum'],
            filename="Assay_information.yaml",
            required=True)

        warning += warn
        total_error += error

        instrument_model = read_group_headers['instrument_model']['enum']
        instrument_model.append(None)
        warn, error = process_functions.check_col_and_values(
            assay_info_df,
            'instrument_model',
            instrument_model,
            filename="Assay_information.yaml",
            required=True)

        warning += warn
        total_error += error

        variant_classes = \
            ['Splice_Site', 'Nonsense_Mutation', 'Frame_Shift_Del',
             'Frame_Shift_Ins', 'Nonstop_Mutation', 'Translation_Start_Site',
             'In_Frame_Ins', 'In_Frame_Del', 'Missense_Mutation',
             'Intron', 'Splice_Region', 'Silent', 'RNA', "5'UTR", "3'UTR",
             'IGR', "5'Flank", "3'Flank", None]
        warn, error = process_functions.check_col_and_values(
            assay_info_df,
            'variant_classifications',
            variant_classes,
            filename="Assay_information.yaml",
            na_allowed=True)

        warning += warn
        total_error += error

        # if not process_functions.checkColExist(
        #         assay_info_df, "target_capture_kit"):
        #     total_error += ("Assay_information.yaml: "
        #                     "Must have target_capture_kit column.\n")

        if process_functions.checkColExist(assay_info_df, "read_length"):
            if not all([process_functions.checkInt(i)
                       for i in assay_info_df["read_length"]
                       if i is not None and not pd.isnull(i)]):
                total_error += \
                    ("Assay_information.yaml: "
                     "Please double check your read_length.  "
                     "It must be an integer or null.\n")
        else:
            total_error += \
                ("Assay_information.yaml: "
                 "Must have read_length column.\n")

        if process_functions.checkColExist(assay_info_df, "number_of_genes"):
            if not all([process_functions.checkInt(i)
                       for i in assay_info_df["number_of_genes"]]):
                total_error += \
                    ("Assay_information.yaml: "
                     "Please double check your number_of_genes. "
                     "It must be an integer.\n")
        else:
            total_error += \
                ("Assay_information.yaml: "
                 "Must have number_of_genes column.\n")

        if process_functions.checkColExist(assay_info_df, "gene_padding"):
            if not all([process_functions.checkInt(i)
                        for i in assay_info_df["gene_padding"]
                        if i is not None and not pd.isnull(i)]):
                total_error += \
                    ("Assay_information.yaml: "
                     "Please double check your gene_padding. "
                     "It must be an integer or blank.\n")
        else:
            warning += \
                ("Assay_information.yaml: "
                 "gene_padding is by default 10 if not specified.\n")

        return(total_error, warning)
