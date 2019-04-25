import synapseclient
import argparse
import synapseutils as synu


def create_test_center(syn, projectid):
    '''
    Create test center input and staging folders

    Args:
        syn: Synapse object
        projectid: Synapse id of blank project

    Returns:
        string: Center input and staging synapse ids
    '''
    copied_dirs = synu.copy(syn, "syn11487362", projectid)
    center1_input = copied_dirs['syn11601335']
    center1_staging = copied_dirs['syn11601337']
    center2_input = copied_dirs['syn11601340']
    center2_staging = copied_dirs['syn11601342']
    return(center1_input, center1_staging, center2_input, center2_staging)


def main(syn, db_synid_mapping_table_synid, projectid):
    '''
    Create center input/staging, copies over relevant databases,
    updates database to synapse id table

    Args:
        syn: Synapse object
        db_synid_mapping_table_synid: model db to stage synid
        projectid: Synapse id of blank project
    '''

    center1_input, center1_staging, center2_input, center2_staging = \
        create_test_center(syn, projectid)
    db_synid_mapping_table = syn.tableQuery(
        "select * from {} where Id is not null and Database <> 'main'".format(
            db_synid_mapping_table_synid))
    db_synid_mapping_tabledf = db_synid_mapping_table.asDataFrame()

    new_rows = []
    copied_entities = {}
    for database, synid, in \
        zip(db_synid_mapping_tabledf['Database'],
            db_synid_mapping_tabledf['Id']):

        # Table may have already been copied
        if synid in copied_entities.keys():
            new_rows.append([database, copied_entities[synid]])
        else:
            copied_map = synu.copy(
                    syn, synid, projectid,
                    setProvenance=None, updateExisting=True)
            copied_synid = copied_map[synid]
            copied_entities[synid] = copied_synid
            new_rows.append([database, copied_synid])

            # save database to synid mapping id for the end
            if database == "dbMapping":
                db_mapping = copied_synid
            # Must store new center env
            elif database == "centerMapping":
                center_map = syn.tableQuery(
                    'select * from {}'.format(copied_synid))
                syn.delete(center_map.asRowSet())
                new_folders = [
                    ['SAGE', center1_input, center1_staging, True, True],
                    ['TEST', center2_input, center2_staging, False, True]]
                syn.store(synapseclient.Table(copied_synid, new_folders))
    # Take copied database to synaspe id mapping table, remove everything
    # and append correct synapse ids
    new_db_map = syn.tableQuery('select * from {}'.format(db_mapping))
    syn.delete(new_db_map.asRowSet())
    syn.store(synapseclient.Table(db_mapping, new_rows))


if __name__ == "__main__":
    """
    Set up GENIE-like monolithic structure
    """
    parser = argparse.ArgumentParser(
        description='Sets up GENIE-like monolithic infrastructure')
    parser.add_argument(
        "db_synid_mapping_table",
        help="Synapse id of 'database to Synapse id table'")
    parser.add_argument(
        "projectid",
        help="Synapse id of 'test project'")
    args = parser.parse_args()
    syn = synapseclient.login()
    db_synid_mapping_table = args.db_synid_mapping_table
    projectid = args.projectid
    main(syn, db_synid_mapping_table, projectid)
