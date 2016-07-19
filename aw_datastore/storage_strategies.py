import json
import os
import logging
from typing import Mapping, List, Union, Sequence

import appdirs

from aw_core.models import Event

try:
    import pymongo
except ImportError:
    logging.warning("Could not import pymongo, not available as a datastore backend")


class StorageStrategy():
    """
    Interface for storage methods.

    Implementations require:
     - insert_one
     - get

    Optional:
     - insert_many
    """

    def create_bucket(self):
        raise NotImplementedError

    def get_bucket(self, bucket: str):
        return self.metadata(bucket)

    # Deprecated, use self.get_bucket instead
    def metadata(self, bucket: str):
        raise NotImplementedError

    def get_events(self, bucket: str):
        return self.get(bucket)

    # Deprecated, use self.get_events instead
    def get(self, bucket: str):
        raise NotImplementedError

    # TODO: Rename to insert_event, or create self.event.insert somehow
    def insert(self, bucket: str, events: Union[Event, Sequence[Event]]):
        #if not (isinstance(events, Event) or isinstance(events, Sequence[Event])) \
        #    and isinstance(events, dict) or isinstance(events, Sequence[dict]):
        #    logging.warning("Events are of type dict, please turn them into proper Events")

        if isinstance(events, Event) or isinstance(events, dict):
            self.insert_one(bucket, events)
        elif isinstance(events, Sequence):
            self.insert_many(bucket, events)
        else:
            print("Argument events wasn't a valid type")

    def insert_one(self, bucket: str, event: Event):
        raise NotImplementedError

    def insert_many(self, bucket: str, events: Sequence[Event]):
        for activity in events:
            self.insert_one(bucket, activity)


class MongoDBStorageStrategy(StorageStrategy):
    """Uses a MongoDB server as backend"""

    def __init__(self):
        self.logger = logging.getLogger("datastore-mongodb")

        if 'pymongo' not in vars() and 'pymongo' not in globals():
            self.logger.error("Cannot use the MongoDB backend without pymongo installed")
            exit(1)

        try:
            self.client = pymongo.MongoClient(serverSelectionTimeoutMS=5000)
            self.client.server_info() # Try to connect to the server to make sure that it's available
        except pymongo.errors.ServerSelectionTimeoutError:
            self.logger.error("Couldn't connect to MongoDB server at localhost")
            exit(1)

        # TODO: Readd testing ability
        #self.db = self.client["activitywatch" if not testing else "activitywatch_testing"]
        self.db = self.client["activitywatch"]

    def get(self, bucket: str):
        return list(self.db[bucket].find())

    def insert_one(self, bucket: str, event: Event):
        self.db[bucket].insert_one(event)


class MemoryStorageStrategy(StorageStrategy):
    """For storage of data in-memory, useful primarily in testing"""

    def __init__(self):
        self.logger = logging.getLogger("datastore-memory")
        #self.logger.warning("Using in-memory storage, any events stored will not be persistent and will be lost when server is shut down. Use the --storage parameter to set a different storage method.")
        self.db = {}  # type: Mapping[str, Mapping[str, List[Event]]]

    def get(self, bucket: str):
        if bucket not in self.db:
            return []
        return self.db[bucket]

    def insert_one(self, bucket: str, event: Event):
        if bucket not in self.db:
            self.db[bucket] = []
        self.db[bucket].append(event)


class FileStorageStrategy(StorageStrategy):
    """For storage of data in JSON files, useful as a zero-dependency/databaseless solution"""

    def __init__(self):
        self.logger = logging.getLogger("datastore-files")

    @staticmethod
    def _get_bucketsdir():
        buckets_dir = appdirs.user_data_dir("aw-server", "activitywatch") + "/" + "buckets"
        if not os.path.exists(buckets_dir):
            os.makedirs(buckets_dir)
        return buckets_dir

    def _get_filename(self, bucket: str):
        bucket_dir = self._get_bucketsdir() + "/" + bucket
        if not os.path.exists(bucket_dir):
            os.makedirs(bucket_dir)
        return "{bucket_dir}/events-0.json".format(bucket_dir=bucket_dir)

    def get(self, bucket: str):
        filename = self._get_filename(bucket)
        if not os.path.isfile(filename):
            return []
        with open(filename) as f:
            data = json.load(f)
        return data

    def create_bucket(self):
        raise NotImplementedError

    def buckets(self):
        return [self.metadata(bucket_id) for bucket_id in os.listdir(self._get_bucketsdir())]

    def metadata(self, bucket: str):
        return {
            "id": bucket,
            "hostname": "unknown",
            "client": "unknown"
        }

    def insert_one(self, bucket: str, event: Event):
        self.insert_many(bucket, [event])

    def insert_many(self, bucket: str, events: Sequence[Event]):
        filename = self._get_filename(bucket)

        if os.path.isfile(filename):
            with open(filename, "r") as f:
                data = json.load(f)
        else:
            data = []

        data.extend([event.to_json_dict() for event in events])
        with open(filename, "w") as f:
            json.dump(data, f)
