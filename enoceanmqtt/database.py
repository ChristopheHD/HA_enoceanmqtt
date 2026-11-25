# Author: Charles Huet <charles.huet@gmail.com>
"""Device database of enoceanmqtt (TinyDB), shared by its threads"""

import os
import threading

from tinydb import TinyDB
from tinydb.table import Table


class LockedTable(Table):
    '''Table whose accesses are serialized: MQTT messages and EnOcean telegrams are handled
    by different threads, and TinyDB rewrites the whole file on each change'''
    _lock = threading.RLock()

    def _read_table(self):
        with self._lock:
            return super()._read_table()

    def _update_table(self, updater):
        with self._lock:
            super()._update_table(updater)


class Database(TinyDB):
    '''TinyDB database whose tables are locked'''
    table_class = LockedTable


def open_database(db_file):
    '''open the device database. Only its owner can read it: it holds the keys of secure devices.'''
    database = Database(db_file, indent=4)
    if os.path.exists(db_file):
        os.chmod(db_file, 0o600)
    return database
