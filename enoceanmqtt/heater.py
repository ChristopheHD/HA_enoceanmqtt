# Author: Charles Huet <charles.huet@gmail.com>
"""EEP D2-33-00 heaters: answers expected by the acknowledge mechanism of the EEP"""

import datetime

from enocean.protocol.constants import RORG

MID_GATEWAY_REQUEST = 0
MID_PROGRAM = 2
MID_TIME_AND_DATE = 3
MID_REQUEST_AND_STATUS = 8

REQ_EXTERNAL_TEMPERATURE = 0
REQ_PROGRAM = 2
REQ_TIME_AND_DATE = 3
REQ_INFORMATION = 4
REQ_ACKNOWLEDGE = 15


def is_heater(sensor):
    '''whether a sensor is an EEP D2-33-00 heater'''
    return (sensor.get('rorg'), sensor.get('func'), sensor.get('type')) == (RORG.VLD, 0x33, 0x00)


def is_program(data):
    '''whether the data of a message to a heater is a program (setpoint)'''
    return data.get('MID') == MID_PROGRAM


def answer(mid, req, program):
    '''data of the answer to a message of a heater, None if it needs no answer.

    program is the data of the last program sent to the heater, None if there was none.'''
    if mid == MID_REQUEST_AND_STATUS and req == REQ_PROGRAM:
        # Program request: send the program again, the heater is stopped without one
        return program
    if mid == MID_REQUEST_AND_STATUS and req == REQ_TIME_AND_DATE:
        now = datetime.datetime.now()
        return {'MID': MID_TIME_AND_DATE, 'DAY': now.day, 'MON': now.month, 'YR': now.year,
                'MIN': now.minute, 'HR': now.hour, 'DAYW': now.weekday()}
    if (mid == MID_REQUEST_AND_STATUS and req in (REQ_EXTERNAL_TEMPERATURE, REQ_INFORMATION)) \
            or 9 <= mid <= 13:
        # Event data, or external temperature request (no external temperature):
        # acknowledge frame
        return {'MID': MID_GATEWAY_REQUEST, 'REQ': REQ_ACKNOWLEDGE}
    # Acknowledge frames need no answer. Sensor parameters requests are not answered
    # as the gateway does not manage them: answering would overwrite the heater settings
    return None
