"""
desispec.io.database
====================

Code for interacting with the file metadatabase.
"""
from __future__ import absolute_import, division, print_function
import sqlite3
from astropy.io import fits
import numpy as np
from glob import glob
import os
import re
from datetime import datetime
from .crc import cksum
from ..log import get_logger, DEBUG
from collections import namedtuple
from matplotlib.patches import Circle, Polygon, Wedge
from matplotlib.collections import PatchCollection


Brick = namedtuple('Brick', ['id', 'name', 'q', 'row', 'col', 'ra', 'dec',
                             'ra1', 'ra2', 'dec1', 'dec2', 'area'])

class Tile(object):
    """Simple object to store individual tile data.
    """
    radius = 1.605  # degrees

    def __init__(self, tileid, ra, dec, in_desi):
        self._id = tileid
        self._ra = ra
        self._dec = dec
        self._in_desi = bool(in_desi)
        self.cos_radius = np.cos(np.radians(self.radius))
        self.area = 2.0*np.pi*(1.0 - np.cos(np.radians(radius)))  # steradians
        self._circum_square = None

    @property
    def id(self):
        return self._id

    @property
    def ra(self):
        return self._ra

    @property
    def dec(self):
        return self._dec

    @property
    def in_desi(self):
        return self._in_desi

    def offset(self, shift=10.0):
        """Provide an offset to move RA away from wrap-around.

        Parameters
        ----------
        shift : :class:`float`, optional
            Amount to offset.

        Returns
        -------
        :class:`float`
            An amount to offset.
        """
        if self.ra < shift:
            return shift
        if self.ra > 360.0 - shift:
            return -shift
        return 0.0

    def brick_offset(self, brick):
        """Offset a brick in the same way as a tile.

        Parameters
        ----------
        brick : Brick
            A brick.

        Returns
        -------
        :func:`tuple`
            A tuple containing the shifted ra1 and ra2.
        """
        brick_ra1 = brick.ra1 + self.offset()
        brick_ra2 = brick.ra2 + self.offset()
        if brick_ra1 < 0:
            brick_ra1 += 360.0
        if brick_ra1 > 360.0:
            brick_ra1 -= 360.0
        if brick_ra2 < 0:
            brick_ra2 += 360.0
        if brick_ra2 > 360.0:
            brick_ra2 -= 360.0
        return (brick_ra1, brick_ra2)

    @property
    def circum_square(self):
        """Given a `tile`, return the square that circumscribes it.

        Returns
        -------
        :func:`tuple`
            A tuple of RA, Dec, suitable for plotting.
        """
        if self._circum_square is None:
            tile_ra = self.ra + self.offset()
            ra = [tile_ra - self.radius,
                  tile_ra + self.radius,
                  tile_ra + self.radius,
                  tile_ra - self.radius,
                  tile_ra - self.radius]
            dec = [self.dec - self.radius,
                   self.dec - self.radius,
                   self.dec + self.radius,
                   self.dec + self.radius,
                   self.dec - self.radius]
            self._circum_square = (ra, dec)
        return self._circum_square

    def petals(self, Npetals=10):
        """Convert a tile into a set of Wedge objects.

        Parameters
        ----------
        Npetals : :class:`int`, optional
            Number of petals.

        Returns
        -------
        :class:`list`
            A list of Wedge objects.
        """
        p = list()
        petal_angle = 360.0/Npetals
        tile_ra = self.ra + self.offset()
        for k in range(Npetals):
            petal = Wedge((tile_ra, self.dec), self.radius, petal_angle*k,
                          petal_angle*(k+1), facecolor='b')
            p.append(petal)
        return p

    def overlapping_bricks(self, candidates, map_petals=False):
        """Convert a list of potentially overlapping bricks into actual overlaps.

        Parameters
        ----------
        candidates : :class:`list`
            A list of candidate bricks.
        map_petals : bool, optional
            If ``True`` a map of petal number to a list of overlapping bricks
            is returned.

        Returns
        -------
        :class:`list`
            A list of Polygon objects.
        """
        petals = self.petals()
        petal2brick = dict()
        bricks = list()
        for b in candidates:
            b_ra1, b_ra2 = self.brick_offset(b)
            brick_corners = np.array([[b_ra1, b.dec1],
                                      [b_ra2, b.dec1],
                                      [b_ra2, b.dec2],
                                      [b_ra1, b.dec2]])
            brick = Polygon(brick_corners, closed=True, facecolor='r')
            for i, p in enumerate(petals):
                if brick.get_path().intersects_path(p.get_path()):
                    brick.set_facecolor('g')
                    if i in petal2brick:
                        petal2brick[i].append(b.id)
                    else:
                        petal2brick[i] = [b.id]
            bricks.append(brick)
        if map_petals:
            return petal2brick
        return bricks

class RawDataCursor(sqlite3.Cursor):
    """Allow simple object-oriented interaction with raw data database.
    """

    def __init__(self, *args, **kwargs):
        super(RawDataCursor, self).__init__(*args, **kwargs)
        return

    def load_brick(self, fitsfile, fix_area=False):
        """Load a bricks FITS file into the database.

        Parameters
        ----------
        fitsfile : :class:`str`
            The name of a bricks file.
        fix_area : :class:`bool`, optional
            If ``True``, deal with missing area column.
        """
        with fits.open(fitsfile) as f:
            brickdata = f[1].data
        bricklist = [ brickdata[col].tolist() for col in brickdata.names ]
        if fix_area:
            #
            # This formula computes area in *steradians*.
            #
            area = ((np.radians(brickdata['ra2']) -
                     np.radians(brickdata['ra1'])) *
                    (np.sin(np.radians(brickdata['dec2'])) -
                     np.sin(np.radians(brickdata['dec1']))))
            bricklist.append(area.tolist())
        insert = """INSERT INTO brick
            (brickname, brickid, brickq, brickrow, brickcol,
            ra, dec, ra1, ra2, dec1, dec2, area)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?);"""
        self.executemany(insert, zip(*bricklist))
        return

    def load_tile(tilefile):
        """Load tile FITS file into the database.

        Parameters
        ----------
        tilefile : :class:`str`
            The name of a tile file.
        """
        with fits.open(filefile) as f:
            tile_data = f[1].data
        tile_list = [tile_data['TILEID'].tolist(), tile_data['RA'].tolist(),
                     tile_data['DEC'].tolist(), tile_data['PASS'].tolist(),
                     tile_data['IN_DESI'].tolist()]
        insert = """INSERT INTO tile (tileid, ra, dec, pass, in_desi)
                    VALUES (?, ?, ?, ?, ?);"""
        self.executemany(insert, zip(*tile_list))
        return

    def is_night(self, night):
        """Returns ``True`` if the night is in the night table.

        Parameters
        ----------
        night : :class:`int` or :class:`str`
            Night name.

        Returns
        -------
        :class:`bool`
            ``True`` if the night is in the night table.
        """
        if isinstance(night, str):
            n = (int(night),)
        else:
            n = (night,)
        q = "SELECT night FROM night WHERE night = ?;"
        self.execute(q, n)
        rows = self.fetchall()
        return len(rows) == 1

    def load_night(self, nights):
        """Load a night or multiple nights into the night table.

        Parameters
        ----------
        nights : :class:`int`, :class:`str` or :class:`list`
            A single night or list of nights.
        """
        if isinstance(nights, str):
            my_nights = [int(nights)]
        elif isinstance(nights, int):
            my_nights = [nights]
        else:
            my_nights = [int(n) for n in nights]
        insert = """INSERT INTO night (night)
            VALUES (?);"""
        self.executemany(insert, zip(my_nights))
        return

    def is_flavor(self, flavor):
        """Returns ``True`` if the flavor is in the exposureflavor table.

        Parameters
        ----------
        flavor : :class:`str`
            A flavor name.

        Returns
        -------
        :class:`bool`
            ``True`` if the flavor is in the flavor table.
        """
        f = (flavor,)
        q = "SELECT flavor FROM exposureflavor WHERE flavor = ?;"
        self.execute(q, f)
        rows = self.fetchall()
        return len(rows) == 1

    def load_flavor(self, flavors):
        """Load a flavor or multiple flavors into the exposureflavor table.

        Parameters
        ----------
        flavors : :class:`list` or :class:`str`
            One or more flavor names.
        """
        if isinstance(flavors, str):
            my_flavors = [flavors]
        else:
            my_flavors = flavors
        insert = """INSERT INTO exposureflavor (flavor)
            VALUES (?);"""
        self.executemany(insert, zip(my_flavors))
        return

    def get_bricks(self, tile):
        """Get the bricks that overlap a tile.

        Parameters
        ----------
        tile : Tile
            A Tile object.

        Returns
        -------
        :class:`list`
            A list of Brick objects that overlap `tile`.
        """
        #
        # RA wrap around can be handled by the requirements:
        # cos(tile.ra - ra1) > cos(tile_radius) or
        # cos(tile.ra - ra2) > cos(tile_radius)
        #
        # However sqlite3 doesn't have trig functions, so we do that "offboard".
        #
        q = """SELECT * FROM brick AS b
               WHERE (? + {0:f} > b.dec1)
               AND   (? - {0:f} < b.dec2)
               ORDER BY dec, ra;""".format(tile.radius)
        self.execute(q, (tile.dec, tile.dec))
        bricks = list()
        for b in map(Brick._make, self.fetchall()):
            if ((np.cos(np.radians(tile.ra - b.ra1)) > tile.cos_radius) or
                (np.cos(np.radians(tile.ra - b.ra2)) > tile.cos_radius)):
                bricks.append(b)
        return bricks

    def get_bricks_by_name(self, bricknames):
        """Search for and return brick data given the brick names.

        Parameters
        ----------
        bricknames : :class:`list` or :class:`str`
            Look up one or more brick names.

        Returns
        -------
        :class:`list`
            A list of Brick objects.
        """
        if isinstance(bricknames, str):
            b = [bricknames]
        else:
            b = bricknames
        q = "SELECT * FROM brick WHERE brickname IN ({})".format(','.join(['?']*len(b)))
        self.execute(q, b)
        bricks = list()
        for b in map(Brick._make, self.fetchall()):
            bricks.append(b)
        return bricks

    def get_brickid_by_name(self, bricknames):
        """Return the brickids that correspond to a set of bricknames.

        Parameters
        ----------
        bricknames : :class:`list` or :class:`str`
            Look up one or more brick names.

        Returns
        -------
        :class:`dict`
            A mapping of brick name to brick id.
        """
        bid = dict()
        bricks = self.get_bricks_by_name(bricknames)
        for b in bricks:
            bid[b.name] = b.id
        return bid

    def get_tile(self, tileid, N_tiles=28810):
        """Get the tile specified by `tileid` or a random tile.

        Parameters
        ----------
        tileid : :class:`int`
            Tile ID number.  Set to a non-positive integer to return a
            random tile.
        N_tiles : :class:`int`, optional
            Override the number of tiles.

        Returns
        -------
        Tile
            A tile object.
        """
        #
        # tileid is 1-indexed.
        #
        if tileid < 1:
            i = np.random.randint(1, N_tiles+1)
        else:
            i = tileid
        q = "SELECT tileid, ra, dec, in_desi FROM tiles WHERE tileid = ?";
        self.execute(q, (i,))
        rows = self.fetchall()
        return Tile(*(rows[0]))

    def get_all_tiles(obs_pass=0, limit=0):
        """Get all tiles from the database.

        Parameters
        ----------
        obs_pass : :class:`int`, optional
            Select only tiles from this pass.
        limit : :class:`int`, optional
            Limit the number of tiles returned

        Returns
        -------
        :class:`list`
            A lit of Tiles.
        """
        q = "SELECT tileid, ra, dec, in_desi FROM tiles WHERE in_desi = ?"
        params = (1, )
        if obs_pass > 0:
            q += " AND pass = ?"
            params = (1, obs_pass)
        if limit > 0:
            q += " LIMIT {0:d}".format(limit)
        q += ';'
        self.execute(q, params)
        tiles = list()
        for row in self.fetchall():
            tiles.append(Tile(*row))
        return tiles

    def load_tile2brick(self, obs_pass=0):
        """Load the tile2brick table using simulated tiles.

        Parameters
        ----------
        obs_pass : :class:`int`, optional
            Select only tiles from this pass.
        """
        tiles = self.get_all_tiles(obs_pass=obs_pass)
        insert = "INSERT INTO tile2brick (tileid, petalid, brickid) VALUES (?, ?, ?);"
        for tile in tiles:
            # petal2brick[tile.id] = dict()
            candidate_bricks = self.get_bricks(tile)
            petal2brick = tile.get_overlapping_bricks(candidate_bricks, map_petals=True)
            for p in petal2brick:
                nb = len(petal2brick[p])
                self.executemany(insert, zip([tile.id]*nb, [p]*nb, petal2brick[p]))
        return

    def load_data(self, datapath):
        """Load a night or multiple nights into the night table.

        Parameters
        ----------
        datapath : :class:`str`
            Name of a data directory.

        Returns
        -------
        :class:`list`
            A list of the exposure numbers found.
        """
        from ..log import desi_logger
        fibermaps = glob(os.path.join(datapath, 'fibermap*.fits'))
        if len(fibermaps) == 0:
            return []
        # fibermap_ids = self.load_file(fibermaps)
        fibermapre = re.compile(r'fibermap-([0-9]{8})\.fits')
        exposures = [ int(fibermapre.findall(f)[0]) for f in fibermaps ]
        frame_data = list()
        frame2brick_data = list()
        for k, f in enumerate(fibermaps):
            with fits.open(f) as hdulist:
                fiberhdr = hdulist['FIBERMAP'].header
                night = int(fiberhdr['NIGHT'])
                dateobs = datetime.strptime(fiberhdr['DATE-OBS'],
                                            '%Y-%m-%dT%H:%M:%S')
                bricknames = list(set(hdulist['FIBERMAP'].data['BRICKNAME'].tolist()))
            datafiles = glob(os.path.join(datapath, 'desi-*-{0:08d}.fits'.format(exposures[k])))
            if len(datafiles) == 0:
                datafiles = glob(os.path.join(datapath, 'pix-*-{0:08d}.fits'.format(exposures[k])))
            desi_logger.debug("Found datafiles: {0}.".format(", ".join(datafiles)))
            # datafile_ids = self.load_file(datafiles)
            with fits.open(datafiles[0]) as hdulist:
                exptime = hdulist[0].header['EXPTIME']
                flavor = hdulist[0].header['FLAVOR']
            if not self.is_night(night):
                self.load_night(night)
            if not self.is_flavor(flavor):
                self.load_flavor(flavor)
            frame_data.append((
                frames[k], # frameid, e.g. b0-00012345
                band, # b, r, z
                spectrograph, # 0-9
                exposures[k], # expid
                night, # night
                flavor, # flavor
                0.0, # telra
                0.0, # teldec
                -1, # tileid
                exptime, # exptime
                dateobs, # dateobs
                0.0, # alt
                0.0)) # az
            brickids = self.get_brickid_by_name(bricknames)
            for i in brickids:
                frame2brick_data.append( (frames[k], brickids[i]) )
        insert = """INSERT INTO frame
            (expid, night, flavor, telra, teldec, tileid, exptime, dateobs, alt, az)
            VALUES (?,?,?,?,?,?,?,?,?,?);"""
        self.executemany(insert, frame_data)
        insert = """INSERT INTO frame2brick
            (expid,brickid) VALUES (?,?);"""
        self.executemany(insert, frame2brick_data)
        return exposures


def main():
    """Entry point for command-line script.

    Returns
    -------
    :class:`int`
        An integer suitable for passing to :func:`sys.exit`.
    """
    #
    # command-line arguments
    #
    from argparse import ArgumentParser
    from pkg_resources import resource_filename
    parser = ArgumentParser(description=("Create and load a DESI metadata "+
                                         "database."))
    parser.add_argument('-a', '--area', action='store_true', dest='fixarea',
        help='If area is not specified in the brick file, recompute it.')
    parser.add_argument('-b', '--bricks', action='store', dest='brickfile',
        default='bricks-0.50-2.fits', metavar='FILE',
        help='Read brick data from FILE.')
    parser.add_argument('-c', '--clobber', action='store_true', dest='clobber',
        help='Delete any existing file before loading.')
    parser.add_argument('-d', '--data', action='store', dest='datapath',
        default=os.path.join(os.environ['DESI_SPECTRO_SIM'],
                             os.environ['PRODNAME']),
        metavar='DIR', help='Load the data in DIR.')
    parser.add_argument('-f', '--filename', action='store', dest='dbfile',
        default='metadata.db', metavar='FILE',
        help="Store data in FILE.")
    parser.add_argument('-s', '--simulate', action='store_true',
        dest='simulate', help="Run a simulation using DESI tiles.")
    parser.add_argument('-t', '--tiles', action='store', dest='tilefile',
        default='desi-tiles.fits', metavar='FILE',
        help='Read tile data from FILE.')
    parser.add_argument('-v', '--verbose', action='store_true', dest='verbose',
        help='Print extra information.')
    options = parser.parse_args()
    #
    # Logging
    #
    if options.verbose:
        log = get_logger(DEBUG)
    else:
        log = get_logger()
    #
    # Create the file.
    #
    dbfile = os.path.join(options.datapath, 'etc', options.dbfile)
    if options.clobber and os.path.exists(dbfile):
        log.info("Removing file: {0}.".format(dbfile))
        os.remove(dbfile)
    if os.path.exists(dbfile):
        script = None
    else:
        schema = resource_filename('desispec', 'data/db/raw_data.sql')
        log.info("Reading schema from {0}.".format(schema))
        with open(schema) as sql:
            script = sql.read()
    conn = sqlite3.connect(dbfile)
    c = conn.cursor(RawDataCursor)
    if script is not None:
        c.executescript(script)
        c.connection.commit()
        log.info("Created schema.")
        brickfile = os.path.join(options.datapath, options.brickfile)
        c.load_brick(brickfile, fix_area=options.fixarea)
        c.connection.commit()
        log.info("Loaded bricks from {0}.".format(brickfile))
    tilefile = os.path.join(options.datapath, options.tilefile)
    if os.path.exists(tilefile):
        c.load_tile(tilefile)
        c.connection.commit()
    if options.simulate:
        c.load_tile2brick(obs_pass=1)
    else:
        exposurepaths = glob(os.path.join(options.datapath,
                                          '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'))
        exposures = list()
        for e in exposurepaths:
            log.info("Loading exposures in {0}.".format(e))
            exposures += c.load_data(e)
    c.connection.commit()
    c.connection.close()
    log.info("Loaded exposures: {0}".format(', '.join(map(str,exposures))))
    return 0
