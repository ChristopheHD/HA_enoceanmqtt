# Author: Charles Huet <charles.huet@gmail.com>
"""Persistence of the security state of secure EnOcean devices in the device database"""

from tinydb.table import Document


class SecureStore():
    '''Security state of secure devices, in a table of the device database.

    The record of a device holds its state as reported by the EnOcean library (key and rolling codes),
    and the sender address it was paired from. Records are identified by the address of the device.'''
    TABLE = 'secure_devices'

    def __init__(self, database):
        self._table = database.table(self.TABLE)
        self._records = {record['address']: dict(record) for record in self._table.all()}

    def states(self):
        '''state of each secure device, by address'''
        return {address: record['state'] for address, record in self._records.items() if 'state' in record}

    def sender(self, address):
        '''sender address the device was paired from, None if unknown'''
        return self._records.get(address, {}).get('sender')

    def save_state(self, address, state):
        '''persist the state of a device'''
        self._save(address, state=state)

    def save_sender(self, address, sender):
        '''persist the sender address the device was paired from'''
        self._save(address, sender=sender)

    def _save(self, address, **fields):
        record = self._records.setdefault(address, {'address': address})
        record.update(fields)
        self._table.upsert(Document(record, doc_id=address))
