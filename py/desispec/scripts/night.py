# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-
"""
desispec.scripts.night
======================

Entry points for start/update/end night scripts.
"""
from __future__ import absolute_import, division, print_function, unicode_literals


def parse_night(stage, *args):
    """Parse command-line options for start/update/end night scripts.

    Parameters
    ----------
    stage : :class:`str`
        The stage of the launch, one of 'start', 'update', 'end'.
    args : iterable
        Additional arguments are parsed for test purposes.

    Returns
    -------
    :class:`argparse.Namespace`
        The parsed command-line options.
    """
    from os.path import basename
    from sys import argv
    from argparse import ArgumentParser
    desc = {'start': 'Begin DESI pipeline processing for a particular night.',
            'update': 'Run DESI pipeline on new data for a particular night.',
            'end': 'Conclude DESI pipeline processing for a particular night.'}
    prsr = ArgumentParser(prog=basename(argv[0]), description=desc[stage])
    prsr.add_argument('-s', '--stage', default=stage,
                      choices=('start', 'update', 'end'),
                      help='Override value of stage for testing purposes.')
    prsr.add_argument('night', metavar='YYYYMMDD', help='Night ID.')
    if len(args) > 0:
        options = prsr.parse_args(args)
    else:  # pragma: no cover
        options = prsr.parse_args()
    return options


def validate_inputs(options):
    """Ensure that all inputs to the start/update/end night scripts are valid.

    Parameters
    ----------
    options : :class:`argparse.Namespace`
        The parsed command-line options.

    Returns
    -------
    :class:`int`
        An integer suitable for passing to :func:`sys.exit`.
    """
    from os import environ
    from desiutil.log import get_logger
    log = get_logger()
    try:
        night = options.night
    except AttributeError:
        log.critical("'night' attribute not set!")
        return 1
    try:
        int_night = int(night)
    except ValueError:
        log.critical("Could not convert 'night' = '{0}' to integer!".format(night))
        return 2
    year = int_night // 10000
    month = (int_night - year*10000) // 100
    day = int_night - year*10000 - month*100
    try:
        assert 1969 < year < 2038
        assert 0 < month < 13
        assert 0 < day < 32
    except AssertionError:
        log.critical("Value for 'night' = '{0}' is not a valid calendar date!".format(night))
        return 3
    for k in ('DESI_SPECTRO_REDUX', 'SPECPROD'):
        try:
            val = environ[k]
        except KeyError:
            log.critical("{0} is not set!".format(k))
            return 4
        else:
            log.info('{0}={1}'.format(k, val))
    return 0


def update_logger(log, filename):
    """Reconfigure the default logging object.

    Parameters
    ----------
    log : :class:`logging.Logger`
        Log object to reconfigure.
    filename : :class:`str`
        Filename to associate with a :class:`~logging.handlers.FileHandler`
        object.

    Returns
    -------
    :class:`logging.Logger`
        The updated object.
    """
    from logging import FileHandler
    fmt = None
    if log.hasHandlers():
        for h in log.handlers:
            if fmt is None:
                fmt = h.formatter
            log.removeHandler(h)
    h = FileHandler(filename)
    h.setFormatter(fmt)
    log.addHandler(h)
    return log


def main():
    """Entry point for :command:`desi_start_night`,
    :command:`desi_update_night` and :command:`desi_end_night`.

    Returns
    -------
    :class:`int`
        An integer suitable for passing to :func:`sys.exit`.
    """
    from os import basename, environ
    from os.path import join
    from sys import argv
    from time import sleep
    from desiutil.log import get_logger
    log = get_logger()
    stage = basename(argv[0]).split('_')[1]
    options = parse_night(stage)
    status = validate_inputs(options)
    logfile = join(environ['HOME'], 'desi_{0.stage}_night_{0.night}.log'.format(options))
    log = update_logger(log, logfile)
    log.info("Called with night = {0}.".format(options.night))
    sleep(120)
    log.info("All done.")
    return status
