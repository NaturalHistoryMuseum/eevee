import dictdiffer

from eevee.versioning import Versioned


class RecordToMongoConverter(Versioned):
    """
    This class provides functions to convert a record into a document to be inserted into mongo.
    """

    def __init__(self, version, ingestion_time):
        """
        :param version:         the current version
        :param ingestion_time:  the time of the ingestion operation
        """
        super().__init__(version)
        self.version = version
        self.ingestion_time = ingestion_time

    def for_insert(self, record):
        """
        Returns the dictionary that should be inserted into mongo to add the record's information to the collection.

        :param record:  the record
        :return: a dict
        """
        # convert the record to a dict according to the records requirements
        converted_record = record.convert(self.version)
        mongo_doc = {
            'id': record.id,
            # keep a record of when this record was first ingested and last ingested, these are the actual times not
            # version times and are not used in the actual search index
            'first_ingested': self.ingestion_time,
            'last_ingested': self.ingestion_time,
            # store a full copy of the data in this record in case versioning isn't in use and for ease of access to the
            # current data if it is. This is a little wasteful if versioning is occurring but shouldn't really cause
            # any unreasonable strain
            'data': converted_record,
        }
        # store some extra details if the ingested data should be versioned
        if self.version:
            # add versioning fields to the mongo doc
            mongo_doc.update({
                # store the latest version in it's own field for easy access. Mongo supports index access to arrays so
                # the first version of a record is easy to get to using "versions.0", however negative indexes are not
                # permitted and therefore "versions.-1" doesn't work. This field just makes it easier to query the mongo
                # collection later
                'latest_version': self.version,
                # sorted list of versions, with the oldest first, newest last
                'versions': [self.version],
                # a dict of the incremental changes made by each version
                'diffs': {self.version: list(dictdiffer.diff({}, converted_record))},
                # deletes list
                'deletes': []
            })
        return mongo_doc

    def for_update(self, record, mongo_doc):
        """
        Returns a dict to update the mongo representation of the given record with the new record version.

        :param record:      the record
        :param mongo_doc:   the existing mongo document
        :return: a dict
        """
        # use a pair of dicts to record any updates required on the mongo document
        sets = {}
        pushes = {}

        # convert the record to a dict according to the records requirements
        converted_record = record.convert(self.version)

        if self.version:
            # generate a diff of the new record against the existing version in mongo
            diff = list(dictdiffer.diff(mongo_doc['data'], converted_record))
            # if the record itself has changed, we'll make updates, if not we won't
            if diff:
                # set some new values
                sets.update({
                    'latest_version': self.version,
                    'last_ingested': self.ingestion_time,
                    'data': converted_record,
                    f'diffs.{self.version}': diff,
                })
                # add the new version to the end of the versions array to ensure the sort order is maintained
                pushes.update({'versions': self.version})
        else:
            sets.update({
                'last_ingested': self.ingestion_time,
                'data': converted_record,
            })

        # create a mongo update operation if there are changes
        update = {}
        if sets:
            update['$set'] = sets
        if pushes:
            update['$push'] = pushes
        return update