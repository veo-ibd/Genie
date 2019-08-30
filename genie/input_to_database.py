#!/usr/bin/env python3
import datetime
import logging
import os
import shutil
import time

import synapseclient
import synapseutils
import pandas as pd

from .config import PROCESS_FILES
from . import process_functions
from . import validate
from . import toRetract
from . import input_to_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

'''
TODO:
Could potentially get all the inforamation of the file entity right here
To avoid the syn.get rest call later which doesn't actually download the file
'''

# def rename_file(ent):
#     '''
#     Gets file from synapse and renames the file if necessary.

#     Adds the expected name as an annotation to a Synapse File object.

#     Args:
#         synid : Synapse id or entity

#     Returns:
#         entity with annotation set for path of corrected file
#     '''
#     dirpath = os.path.dirname(ent.path)
#     expectedpath = os.path.join(dirpath, ent.name)

#     ent.annotations.expectedPath = expectedpath
#     return ent


def entity_date_to_timestamp(entity_date_time):
    """Convert Synapse object date/time string (from modifiedOn or createdOn properties) to a timestamp.
    """

    date_and_time = entity_date_time.split(".")[0]
    date_time_obj = datetime.datetime.strptime(date_and_time, "%Y-%m-%dT%H:%M:%S")
    return synapseclient.utils.to_unix_epoch_time(date_time_obj)


def get_center_input_files(syn, synid, center, process="main"):
    '''
    This function walks through each center's input directory
    to get a list of tuples of center files

    Args:
        syn: Synapse object
        synid: Center input folder synid
        center: Center name
        process: Process type includes, main, vcf, maf and mafSP.
                 Defaults to main such that the vcf

    Returns:
        List of entities with the correct format to pass into validation
    '''
    logger.info("GETTING {center} INPUT FILES".format(center=center))
    clinical_pair_name = [
        "data_clinical_supp_sample_{center}.txt".format(center=center),
        "data_clinical_supp_patient_{center}.txt".format(center=center)]

    center_files = synapseutils.walk(syn, synid)
    clinicalpair_entities = []
    prepared_center_file_list = []

    for _, _, entities in center_files:
        for name, ent_synid in entities:
            # This is to remove vcfs from being validated during main
            # processing. Often there are too many vcf files, and it is
            # not necessary for them to be run everytime.
            if name.endswith(".vcf") and process != "vcf":
                continue

            ent = syn.get(ent_synid)
            logger.debug(ent)

            # Clinical file can come as two files.
            # The two files need to be merged together which is
            # why there is this format

            if name in clinical_pair_name:
                clinicalpair_entities.append(ent)
                continue

            prepared_center_file_list.append([ent])

    if clinicalpair_entities:
        # clinicalpair_entities = [x for x in clinicalpair]
        prepared_center_file_list.append(clinicalpair_entities)

    return prepared_center_file_list


def check_existing_file_status(validation_statusdf, error_trackerdf, entities):
    '''
    This function checks input files against the existing validation and error
    tracking dataframe

    Args:
        validation_statusdf: Validation status dataframe
        error_trackerdf: Error tracking dataframe
        entities: list of center input entites

    Returns:
        dict: Input file status
            status_list: file validation status
            error_list: Errors of the files if they exist,
            to_validate: Boolean value for whether of not an input
                         file needs to be validated
    '''
    if len(entities) > 2:
        raise ValueError(
            "There should never be more than 2 files being validated.")

    statuses = []
    errors = []

    for ent in entities:
        to_validate = False
        version_number = str(ent.properties.versionNumber)

        # Get the current status and errors from the tables.
        current_status = validation_statusdf[(validation_statusdf['id'] == ent.id) & (validation_statusdf['versionNumber'] == version_number)]
        current_error = error_trackerdf[(error_trackerdf['id'] == ent.id) & (error_trackerdf['versionNumber'] == version_number)]

        if current_status.empty:
            to_validate = True
        else:
            # This to_validate is here, because the following is a
            # sequential check of whether files need to be validated
            statuses.append(current_status['status'].values[0])
            if current_error.empty:
                to_validate = \
                    current_status['status'].values[0] == "INVALID"
            else:
                errors.append(current_error['errors'].values[0])
            # Add Name check here (must add name of the entity as a column)
            if current_status['md5'].values[0] != ent.md5 or \
               current_status['name'].values[0] != ent.name:
                to_validate = True
            else:
                status_str = "{filename} ({id}.{version}) FILE STATUS IS: {filestatus}"
                logger.info(status_str.format(filename=ent.name, id=ent.id,
                                              version=ent.properties.versionNumber,
                                              filestatus=current_status['status'].values[0]))

    return({
        'status_list': statuses,
        'error_list': errors,
        'to_validate': to_validate})


def _send_validation_error_email(syn, filenames, message, file_users):
    '''
    Sends validation error email

    Args:
        syn: Synapse object
        filenames: invalid filenames
        message: error message
        file_users: List of unique synapse user profiles of
                    users that created and most recently
                    modified the file
    '''
    # Send email the first time the file is invalid
    incorrect_files = ", ".join(filenames)
    usernames = ", ".join([
        syn.getUserProfile(user)['userName']
        for user in file_users])
    email_message = (
        "Dear {username},\n\n"
        "Your files ({filenames}) are invalid! "
        "Here are the reasons why:\n\n{error_message}".format(
            username=usernames,
            filenames=incorrect_files,
            error_message=message))
    syn.sendMessage(
        file_users, "GENIE Validation Error", email_message)


def _get_status_and_error_list(syn, valid, message, filetype, entities):
    '''
    Helper function to return the status and error list of the
    files based on validation result.

    Args:
        syn: Synapse object
        valid: Boolean value of results of validation
        message: Validation message
        filetype: File type
        entities: List of Synapse Entities

    Returns:
        tuple: input_status_list - status of input files list,
               invalid_errors_list - error list
    '''
    if valid:
        input_status_list = [
            [ent.id, ent.path, ent.md5, "VALIDATED",
             ent.name, entity_date_to_timestamp(ent.properties.modifiedOn), filetype,
             str(ent.properties.versionNumber)]
            for ent in entities]
        invalid_errors_list = None
    else:
        input_status_list = [
            [ent.id, ent.path, ent.md5, "INVALID",
             ent.name, entity_date_to_timestamp(ent.properties.modifiedOn), filetype, 
             str(ent.properties.versionNumber)]
            for ent in entities]
        invalid_errors_list = [
            [ent.id, message, ent.name, str(ent.properties.versionNumber)]
            for ent in entities]
    return(input_status_list, invalid_errors_list)


def validatefile(syn, entities, validation_statusdf, error_trackerdf,
                 center, threads, testing, oncotree_link):
    '''Validate a list of entities.

    If a file has not changed, then it doesn't need to be validated.

    Args:
        syn: Synapse object
        entities: A list of entities for a single file 'type' (usually a single file, but clinical can have two)
        validation_statusdf: Validation status dataframe
        error_trackerdf: Invalid files error tracking dataframe
        center: Center of interest
        testing: Boolean determining whether using testing parameter
        oncotree_link: Oncotree url

    Returns:
        tuple: input_status_list - status of input files,
               invalid_errors_list - error list

    '''

    filepaths = [entity.path for entity in entities]
    filenames = [entity.name for entity in entities]

    logger.info(
        "VALIDATING {filenames}".format(filenames=", ".join(filenames)))

    file_users = [entities[0].modifiedBy, entities[0].createdBy]

    check_file_status = check_existing_file_status(
        validation_statusdf, error_trackerdf, entities)

    status_list = check_file_status['status_list']
    error_list = check_file_status['error_list']
    # Need to figure out to how to remove this
    # This must pass in filenames, because filetype is determined by entity name
    # Not by actual path of file
    filetype = validate.determine_filetype(syn, filenames, center)
    if check_file_status['to_validate']:
        valid, message, filetype = validate.validate_single_file(
            syn,
            filepaths,
            center,
            filetype=filetype,
            oncotreelink=oncotree_link,
            testing=testing)
        logger.info("VALIDATION COMPLETE")
        input_status_list, invalid_errors_list = _get_status_and_error_list(
            syn, valid, message, filetype,
            entities)
        # Send email the first time the file is invalid
        if invalid_errors_list is not None:
            _send_validation_error_email(syn, filenames, message, file_users)
    else:
        input_status_list = [
            [ent.id, path, ent.md5, status, filename, entity_date_to_timestamp(ent.properties.modifiedOn), filetype, str(ent.properties.versionNumber)]
            for ent, path, status, filename in
            zip(entities, filepaths, status_list, filenames)]
        invalid_errors_list = [
            [entity.id, error, filename, str(ent.properties.versionNumber)]
            for entity, error, filename in
            zip(entities, error_list, filenames)]
    return(input_status_list, invalid_errors_list)


def processfiles(syn, validfiles, center, path_to_genie, threads,
                 center_mapping_df, oncotreeLink, databaseToSynIdMappingDf,
                 validVCF=None, vcf2mafPath=None,
                 veppath=None, vepdata=None,
                 processing="main", test=False, reference=None):
    '''
    Processing validated files

    Args:
        syn: Synapse object
        validfiles: pandas dataframe containing validated files
                    has 'id', 'path', and 'fileType' column
        center: GENIE center name
        path_to_genie: Path to GENIE workdir
        threads: Threads used
        center_mapping_df: Center mapping dataframe
        oncotreeLink: Link to oncotree
        databaseToSynIdMappingDf: Database to synapse id mapping dataframe
        validVCF: Valid vcf files
        vcf2mafPath: Path to vcf2maf
        veppath: Path to vep
        vepdata: Path to vep index files
        processing: Processing type. Defaults to main
        test: Test flag
        reference: Reference file for vcf2maf
    '''
    logger.info("PROCESSING {} FILES: {}".format(center, len(validfiles)))
    center_staging_folder = os.path.join(path_to_genie, center)
    center_staging_synid = center_mapping_df.query(
        "center == 'SAGE'").stagingSynId.iloc[0]

    if not os.path.exists(center_staging_folder):
        os.makedirs(center_staging_folder)

    if processing != 'vcf':
        for fileSynId, filePath, fileType in zip(validfiles['id'],
                                                 validfiles['path'],
                                                 validfiles['fileType']):
            filename = os.path.basename(filePath)
            newPath = os.path.join(center_staging_folder, filename)
            # store = True
            synId = databaseToSynIdMappingDf.Id[
                databaseToSynIdMappingDf['Database'] == fileType]
            if len(synId) == 0:
                synId = None
            else:
                synId = synId[0]
            if fileType is not None and (processing == "main" or processing == fileType):
                processor = PROCESS_FILES[fileType](syn, center, threads)
                processor.process(
                    filePath=filePath, newPath=newPath,
                    parentId=center_staging_synid, databaseSynId=synId,
                    oncotreeLink=oncotreeLink,
                    fileSynId=fileSynId, validVCF=validVCF,
                    path_to_GENIE=path_to_genie, vcf2mafPath=vcf2mafPath,
                    veppath=veppath, vepdata=vepdata,
                    processing=processing,
                    databaseToSynIdMappingDf=databaseToSynIdMappingDf,
                    reference=reference, test=test)

    else:
        filePath = None
        newPath = None
        fileType = None
        synId = databaseToSynIdMappingDf.Id[
            databaseToSynIdMappingDf['Database'] == processing][0]
        fileSynId = None
        processor = PROCESS_FILES[processing](syn, center, threads)
        processor.process(
            filePath=filePath, newPath=newPath,
            parentId=center_staging_synid, databaseSynId=synId,
            oncotreeLink=oncotreeLink,
            fileSynId=fileSynId, validVCF=validVCF,
            path_to_GENIE=path_to_genie, vcf2mafPath=vcf2mafPath,
            veppath=veppath, vepdata=vepdata,
            processing=processing,
            databaseToSynIdMappingDf=databaseToSynIdMappingDf,
            reference=reference)

    logger.info("ALL DATA STORED IN DATABASE")

# def _create_maf_db(syn, foo):
#     maf_database_ent = syn.get(maf_database_synid)
#     print(maf_database_ent)
#     maf_columns = list(syn.getTableColumns(maf_database_synid))
#     schema = synapseclient.Schema(
#         name='Narrow MAF {current_time} Database'.format(
#             current_time=time.time()),
#         columns=maf_columns,
#         parent=process_functions.getDatabaseSynId(
#             syn, "main",
#             databaseToSynIdMappingDf=database_synid_mappingdf))
#     schema.primaryKey = maf_database_ent.primaryKey
#     new_maf_database = syn.store(schema)

# TODO: Should split this into 3 funcitons
# so that unit tests are easier to write


def create_and_archive_maf_database(syn, database_synid_mappingdf):
    '''
    Creates new MAF database and archives the old database in the staging site

    Args:
        syn: Synapse object
        databaseToSynIdMappingDf: Database to synapse id mapping dataframe

    Return:
        Editted database to synapse id mapping dataframe
    '''
    maf_database_synid = process_functions.getDatabaseSynId(
        syn, "vcf2maf", databaseToSynIdMappingDf=database_synid_mappingdf)
    maf_database_ent = syn.get(maf_database_synid)
    maf_columns = list(syn.getTableColumns(maf_database_synid))
    schema = synapseclient.Schema(
        name='Narrow MAF {current_time} Database'.format(
            current_time=time.time()),
        columns=maf_columns,
        parent=process_functions.getDatabaseSynId(
            syn, "main", databaseToSynIdMappingDf=database_synid_mappingdf))
    schema.primaryKey = maf_database_ent.primaryKey
    new_maf_database = syn.store(schema)
    # Store in the new database synid
    database_synid_mappingdf['Id'][
        database_synid_mappingdf[
            'Database'] == 'vcf2maf'] = new_maf_database.id

    vcf2maf_mappingdf = database_synid_mappingdf[
        database_synid_mappingdf['Database'] == 'vcf2maf']
    # vcf2maf_mappingdf['Id'][0] = newMafDb.id
    # Update this synid later
    syn.store(synapseclient.Table("syn12094210", vcf2maf_mappingdf))
    # Move and archive old mafdatabase (This is the staging synid)
    maf_database_ent.parentId = "syn7208886"
    maf_database_ent.name = "ARCHIVED " + maf_database_ent.name
    syn.store(maf_database_ent)
    # maf_database_synid = new_maf_database.id
    # Remove can download permissions from project GENIE team
    syn.setPermissions(new_maf_database.id, 3326313, [])
    return(database_synid_mappingdf)


def email_duplication_error(syn, duplicated_filesdf):
    '''
    Sends an email if there is a duplication error

    Args:
        syn: Synapse object
        duplicated_filesdf: dataframe with 'id', 'name' column
    '''
    if not duplicated_filesdf.empty:
        incorrect_files = [
            name for synId, name in zip(duplicated_filesdf['id'],
                                        duplicated_filesdf['name'])]
        incorrect_filenames = ", ".join(incorrect_files)
        incorrect_ent = syn.get(duplicated_filesdf['id'].iloc[0])
        send_to_users = set([incorrect_ent.modifiedBy,
                             incorrect_ent.createdBy])
        usernames = ", ".join(
            [syn.getUserProfile(user)['userName'] for user in send_to_users])
        error_email = (
            "Dear {},\n\n"
            "Your files ({}) are duplicated!  FILES SHOULD BE UPLOADED AS "
            "NEW VERSIONS AND THE ENTIRE DATASET SHOULD BE "
            "UPLOADED EVERYTIME".format(usernames, incorrect_filenames))
        syn.sendMessage(
            list(send_to_users), "GENIE Validation Error", error_email)


def get_duplicated_files(validation_statusdf, duplicated_error_message):
    '''
    Check for duplicated files.  There should be no duplication,
    files should be uploaded as new versions and the entire dataset
    should be uploaded everytime

    Args:
        validation_statusdf: dataframe with 'name' and 'id' column
        duplicated_error_message: Error message for duplicated files

    Returns:
        dataframe with 'id', 'name' and 'errors' of duplicated files
    '''
    logger.info("CHECK FOR DUPLICATED FILES")
    duplicated_filesdf = validation_statusdf[
        validation_statusdf['name'].duplicated(keep=False)]
    # cbs/seg files should not be duplicated.
    cbs_seg_files = validation_statusdf.query(
        'name.str.endswith("cbs") or name.str.endswith("seg")')
    if len(cbs_seg_files) > 1:
        duplicated_filesdf = duplicated_filesdf.append(cbs_seg_files)
    # clinical files should not be duplicated.
    clinical_files = validation_statusdf.query(
        'name.str.startswith("data_clinical_supp")')
    if len(clinical_files) > 2:
        duplicated_filesdf = duplicated_filesdf.append(clinical_files)
    duplicated_filesdf.drop_duplicates("id", inplace=True)
    logger.info("THERE ARE {} DUPLICATED FILES".format(
        len(duplicated_filesdf)))
    duplicated_filesdf['errors'] = duplicated_error_message
    return(duplicated_filesdf)


def update_status_and_error_tables(syn,
                                   center,
                                   input_valid_statuses,
                                   invalid_errors,
                                   validation_status_table,
                                   error_tracker_table):
    '''
    Update validation status and error tracking table

    Args:
        syn: Synapse object
        center: Center
        input_valid_status: list of lists of validation status
        invalid_errors: List of lists of invalid errors
        validation_status_table: Synapse table query of validation status
        error_tracker_table: Synapse table query of error tracker

    Returns:
        input validation status dataframe
    '''
    input_valid_statusdf = pd.DataFrame(input_valid_statuses,
                                        columns=["id", 'path', 'md5', 'status',
                                                 'name', 'modifiedOn',
                                                 'fileType'])

    duplicated_file_error = (
        "DUPLICATED FILENAME! FILES SHOULD BE UPLOADED AS NEW VERSIONS "
        "AND THE ENTIRE DATASET SHOULD BE UPLOADED EVERYTIME")
    duplicated_filesdf = get_duplicated_files(input_valid_statusdf,
                                              duplicated_file_error)
    # Send an email if there are any duplicated files
    if not duplicated_filesdf.empty:
        email_duplication_error(syn, duplicated_filesdf)
    duplicated_idx = input_valid_statusdf['id'].isin(duplicated_filesdf['id'])
    input_valid_statusdf['status'][duplicated_idx] = "INVALID"
    # Create invalid error synapse table
    logger.info("UPDATE INVALID FILE REASON DATABASE")
    invalid_errorsdf = pd.DataFrame(invalid_errors,
                                    columns=["id", 'errors', 'name'])
    # Remove fixed duplicated files
    # This makes sure that the files removed actually had duplicated file
    # errors and not some other error
    dup_ids = invalid_errorsdf['id'][
        invalid_errorsdf['errors'] == duplicated_file_error]
    remove_ids = dup_ids[~dup_ids.isin(duplicated_filesdf['id'])]
    invalid_errorsdf = invalid_errorsdf[~invalid_errorsdf['id'].isin(remove_ids)]
    # Append duplicated file errors
    invalid_errorsdf = invalid_errorsdf.append(
        duplicated_filesdf[['id', 'errors', 'name']])
    invalid_errorsdf['center'] = center
    invalidIds = input_valid_statusdf['id'][input_valid_statusdf['status'] == "INVALID"]
    invalid_errorsdf = invalid_errorsdf[invalid_errorsdf['id'].isin(invalidIds)]
    process_functions.updateDatabase(syn, error_tracker_table.asDataFrame(),
                                     invalid_errorsdf,
                                     error_tracker_table.tableId,
                                     ["id"], to_delete=True)

    logger.info("UPDATE VALIDATION STATUS DATABASE")
    input_valid_statusdf['center'] = center
    # Remove fixed duplicated files
    input_valid_statusdf = input_valid_statusdf[
        ~input_valid_statusdf['id'].isin(remove_ids)]

    process_functions.updateDatabase(syn,
                                     validation_status_table.asDataFrame(),
                                     input_valid_statusdf[["id", 'md5', 'status', 'name', 'center', 'modifiedOn']],
                                     validation_status_table.tableId,
                                     ["id"],
                                     to_delete=True)

    return(input_valid_statusdf)


def validation(syn, center, process,
               center_mapping_df, database_synid_mappingdf,
               thread, testing, oncotree_link):
    '''
    Validation of all center files

    Args:
        syn: Synapse object
        center: Center name
        process: main, vcf, maf
        center_mapping_df: center mapping dataframe
        thread: Unused parameter for now
        testing: True if testing
        oncotreeLink: Link to oncotree

    Returns:
        dataframe: Valid files
    '''
    center_input_synid = center_mapping_df['inputSynId'][
        center_mapping_df['center'] == center][0]
    logger.info("Center: " + center)
    center_files = get_center_input_files(syn, center_input_synid, center,
                                          process)

    # If a center has no files, then return empty list
    if not center_files:
        logger.info("{} has not uploaded any files".format(center))
        return([])
    else:
        validation_status_synid = process_functions.getDatabaseSynId(
            syn, "validationStatus",
            databaseToSynIdMappingDf=database_synid_mappingdf)
        error_tracker_synid = process_functions.getDatabaseSynId(
            syn, "errorTracker",
            databaseToSynIdMappingDf=database_synid_mappingdf)

        # Make sure the vcf validation statuses don't get wiped away
        # If process is not vcf, the vcf files are not downloaded
        add_query_str = "and name not like '%.vcf'" if process != "vcf" else ''

        validation_status_table = syn.tableQuery(
            "SELECT id,md5,status,name,center,modifiedOn,versionNumber FROM {synid} "
            "where center = '{center}' {add}".format(
                synid=validation_status_synid,
                center=center,
                add=add_query_str))
        validation_statusdf = validation_status_table.asDataFrame()
        validation_statusdf['versionNumber'] = validationStatusDf.versionNumber.astype(str)

        error_tracker_table = syn.tableQuery(
            "SELECT id,center,errors,name,versionNumber FROM {synid} "
            "where center = '{center}' {add}".format(
                synid=error_tracker_synid,
                center=center,
                add=add_query_str))
        error_trackerdf = error_tracker_table.asDataFrame()
        error_trackerdf['versionNumber'] = validationStatusDf.versionNumber.astype(str)


        input_valid_statuses = []
        invalid_errors = []

        for ents in center_files:
            status, errors = validatefile(syn, ents,
                                          validation_statusdf,
                                          error_trackerdf,
                                          center='SAGE', threads=1,
                                          testing=False,
                                          oncotree_link=oncotree_link)
            input_valid_statuses.extend(status)
            if errors is not None:
                invalid_errors.extend(errors)

        input_valid_statusdf = update_status_and_error_tables(
            syn,
            center,
            input_valid_statuses,
            invalid_errors,
            validation_status_table,
            error_tracker_table)

        valid_filesdf = input_valid_statusdf.query('status == "VALIDATED"')

        return(valid_filesdf[['id', 'path', 'fileType']])


def center_input_to_database(
        syn, center, process, testing,
        only_validate, vcf2maf_path, vep_path,
        vep_data, database_to_synid_mappingdf,
        center_mapping_df, reference=None,
        delete_old=False, oncotree_link=None, thread=1):
    if only_validate:
        log_path = os.path.join(
            process_functions.SCRIPT_DIR,
            "{}_validation_log.txt".format(center))
    else:
        log_path = os.path.join(
            process_functions.SCRIPT_DIR,
            "{}_{}_log.txt".format(center, process))

    logFormatter = logging.Formatter(
        "%(asctime)s [%(name)s][%(levelname)s] %(message)s")
    fileHandler = logging.FileHandler(log_path, mode='w')
    fileHandler.setFormatter(logFormatter)
    logger.addHandler(fileHandler)

    if testing:
        logger.info("###########################################")
        logger.info("############NOW IN TESTING MODE############")
        logger.info("###########################################")

    # ----------------------------------------
    # Start input to staging process
    # ----------------------------------------
    '''
    # path_to_genie = os.path.realpath(os.path.join(
    #    process_functions.SCRIPT_DIR, "../"))
    Make the synapsecache dir the genie input folder for now
    The main reason for this is because the .synaspecache dir
    is mounted by batch
    '''
    path_to_genie = os.path.expanduser("~/.synapseCache")
    # Create input and staging folders
    if not os.path.exists(os.path.join(path_to_genie, center, "input")):
        os.makedirs(os.path.join(path_to_genie, center, "input"))
    if not os.path.exists(os.path.join(path_to_genie, center, "staging")):
        os.makedirs(os.path.join(path_to_genie, center, "staging"))

    if delete_old:
        process_functions.rmFiles(os.path.join(path_to_genie, center))

    validFiles = validation(
        syn, center, process, center_mapping_df,
        database_to_synid_mappingdf, thread,
        testing, oncotree_link)

    if len(validFiles) > 0 and not only_validate:
        # Reorganize so BED file are always validated and processed first
        validBED = [
            os.path.basename(i).endswith('.bed') for i in validFiles['path']]
        beds = validFiles[validBED]
        validFiles = beds.append(validFiles)
        validFiles.drop_duplicates(inplace=True)
        # Valid vcf files
        validVCF = [
            i for i in validFiles['path']
            if os.path.basename(i).endswith('.vcf')]

        processTrackerSynId = process_functions.getDatabaseSynId(
            syn, "processTracker",
            databaseToSynIdMappingDf=database_to_synid_mappingdf)
        # Add process tracker for time start
        processTracker = syn.tableQuery(
            "SELECT timeStartProcessing FROM {} "
            "where center = '{}' and "
            "processingType = '{}'".format(
                processTrackerSynId, center, process))
        processTrackerDf = processTracker.asDataFrame()
        if len(processTrackerDf) == 0:
            new_rows = [[
                center,
                str(int(time.time()*1000)),
                str(int(time.time()*1000)),
                process]]

            syn.store(synapseclient.Table(
                processTrackerSynId, new_rows))
        else:
            processTrackerDf['timeStartProcessing'][0] = \
                str(int(time.time()*1000))
            syn.store(synapseclient.Table(
                processTrackerSynId, processTrackerDf))

        processfiles(syn, validFiles, center, path_to_genie, thread,
                     center_mapping_df, oncotree_link,
                     database_to_synid_mappingdf,
                     validVCF=validVCF,
                     vcf2mafPath=vcf2maf_path,
                     veppath=vep_path, vepdata=vep_data,
                     test=testing, processing=process, reference=reference)

        # Should add in this process end tracking
        # before the deletion of samples
        processTracker = syn.tableQuery(
            "SELECT timeEndProcessing FROM {synid} where center = '{center}' "
            "and processingType = '{processtype}'".format(
                synid=processTrackerSynId,
                center=center,
                processtype=process))
        processTrackerDf = processTracker.asDataFrame()
        processTrackerDf['timeEndProcessing'][0] = str(int(time.time()*1000))
        syn.store(synapseclient.Table(processTrackerSynId, processTrackerDf))

        logger.info("SAMPLE/PATIENT RETRACTION")
        toRetract.retract(syn, testing)

    else:
        messageOut = \
            "{} does not have any valid files" if not only_validate \
            else "ONLY VALIDATION OCCURED FOR {}"
        logger.info(messageOut.format(center))

    # Store log file
    log_folder_synid = process_functions.getDatabaseSynId(
        syn, "logs", databaseToSynIdMappingDf=database_to_synid_mappingdf)
    syn.store(synapseclient.File(log_path, parentId=log_folder_synid))
    os.remove(log_path)
    logger.info("ALL PROCESSES COMPLETE")
