# Licensed under a 3-clause BSD style license - see LICENSE.rst
# -*- coding: utf-8 -*-
"""
desispec.spectra
================

Class for dealing with a group of spectra from multiple bands
and the associated fibermap information.

"""
from __future__ import absolute_import, division, print_function

import os
import re
import warnings
import time
import copy
import numbers

import numpy as np
from astropy.table import Table

from desiutil.depend import add_dependencies
from desiutil.io import encode_table

from .maskbits import specmask
from .resolution import Resolution

class Spectra(object):
    """Represents a grouping of spectra.

    This class contains an "extended" fibermap that has information about
    the night and exposure of each spectrum.  For each band, this class has 
    the wavelength grid, flux, ivar, mask, and resolution arrays.

    Parameters
    ----------
    bands : :class:`list`
        List of strings used to identify the bands.
    wave : :class:`dict`
        Dictionary of arrays specifying the wavelength grid.
    flux : :class:`dict`
        Dictionary of arrays specifying the flux for each spectrum.
    ivar : :class:`dict`
        Dictionary of arrays specifying the inverse variance.
    mask : :class:`dict`, optional
        Dictionary of arrays specifying the bitmask.
    resolution_data : :class:`dict`, optional
        Dictionary of arrays specifying the block diagonal resolution matrix.
        The object for each band must be in one of the formats supported
        by the Resolution class constructor.
    fibermap
        Extended fibermap to use. If not specified, a fake one is created.
    meta : :class:`dict`, optional
        Dictionary of arbitrary properties.
    extra : :class:`dict`, optional
        Optional dictionary of dictionaries containing extra
        floating point arrays.  The top-level is a dictionary over bands
        and each value is a dictionary containing string keys and values
        which are arrays of the same size as the flux array.
    single : :class:`bool`, optional
        If ``True``, store data in memory as single precision.
    scores
        QA scores table.
    extra_catalog : numpy or astropy Table, optional
        optional table of metadata, rowmatched to fibermap,
        e.g. a redshift catalog for these spectra
    """
    def __init__(self, bands=[], wave={}, flux={}, ivar={}, mask=None, resolution_data=None,
        fibermap=None, meta=None, extra=None, single=False, scores=None, extra_catalog=None):
        
        self._bands = bands
        self._single = single
        self._ftype = np.float64
        if single:
            self._ftype = np.float32

        if scores is not None:
            self.scores = Table(scores)
        else:
            self.scores = None

        self.meta = None
        if meta is None:
            self.meta = {}
        else:
            self.meta = meta.copy()

        nspec = 0

        # check consistency of input dimensions
        for b in self._bands:
            if wave[b].ndim != 1:
                raise RuntimeError("wavelength array for band {} should have dim == 1".format(b))
            if flux[b].ndim != 2:
                raise RuntimeError("flux array for band {} should have dim == 2".format(b))
            if flux[b].shape[1] != wave[b].shape[0]:
                raise RuntimeError("flux array wavelength dimension for band {} does not match wavelength grid".format(b))
            if nspec is None:
                nspec = flux[b].shape[0]
            if fibermap is not None:
                if len(fibermap) != flux[b].shape[0]:
                    raise RuntimeError("flux array number of spectra for band {} does not match fibermap".format(b))
            if ivar[b].shape != flux[b].shape:
                raise RuntimeError("ivar array dimensions do not match flux for band {}".format(b))
            if mask is not None:
                if mask[b].shape != flux[b].shape:
                    raise RuntimeError("mask array dimensions do not match flux for band {}".format(b))
                if mask[b].dtype not in (int, np.int64, np.int32, np.uint64, np.uint32):
                    raise RuntimeError("bad mask type {}".format(mask.dtype))
            if resolution_data is not None:
                if resolution_data[b].ndim != 3:
                    raise RuntimeError("resolution array for band {} should have dim == 3".format(b))
                if resolution_data[b].shape[0] != flux[b].shape[0]:
                    raise RuntimeError("resolution array spectrum dimension for band {} does not match flux".format(b))
                if resolution_data[b].shape[2] != wave[b].shape[0]:
                    raise RuntimeError("resolution array wavelength dimension for band {} does not match grid".format(b))
            if extra is not None:
                for ex in extra[b].items():
                    if ex[1].shape != flux[b].shape:
                        raise RuntimeError("extra arrays must have the same shape as the flux array")

        if fibermap is not None and extra_catalog is not None:
            if len(fibermap) != len(extra_catalog):
                raise ValueError('fibermap and extra_catalog have different number of entries {} != {}'.format(
                    len(fibermap), len(extra_catalog) ))

            if ('TARGETID' in fibermap.dtype.names) and ('TARGETID' in extra_catalog.dtype.names):
                if not np.all(fibermap['TARGETID'] == extra_catalog['TARGETID']):
                    raise ValueError('TARGETID mismatch between fibermap and extra_catalog')

        # copy data

        if fibermap is not None:
            self.fibermap = fibermap.copy()
        else:
            self.fibermap = None

        if extra_catalog is not None:
            self.extra_catalog = extra_catalog.copy()
        else:
            self.extra_catalog = None

        self.wave = {}
        self.flux = {}
        self.ivar = {}

        if mask is None:
            self.mask = None
        else:
            self.mask = {}
        
        if resolution_data is None:
            self.resolution_data = None
            self.R = None
        else:
            self.resolution_data = {}
            self.R = {}
        
        if extra is None:
            self.extra = None
        else:
            self.extra = {}

        for b in self._bands:
            self.wave[b] = np.copy(wave[b].astype(self._ftype))
            self.flux[b] = np.copy(flux[b].astype(self._ftype))
            self.ivar[b] = np.copy(ivar[b].astype(self._ftype))
            if mask is not None:
                self.mask[b] = np.copy(mask[b])
            if resolution_data is not None:
                self.resolution_data[b] = resolution_data[b].astype(self._ftype)
                self.R[b] = np.array( [ Resolution(r) for r in resolution_data[b] ] )
            if extra is not None:
                self.extra[b] = {}
                for ex in extra[b].items():
                    self.extra[b][ex[0]] = np.copy(ex[1].astype(self._ftype))


    @property
    def bands(self):
        """
        (list): the list of valid bands.
        """
        return self._bands

    @property
    def ftype(self):
        """
        (numpy.dtype): the data type used for floating point numbers.
        """
        return self._ftype


    def wavelength_grid(self, band):
        """
        Return the wavelength grid for a band.

        Args:
            band (str): the name of the band.

        Returns (array):
            an array containing the wavelength values.

        """
        if band not in self.bands:
            raise KeyError("{} is not a valid band".format(band))
        return self.wave[band]


    def target_ids(self):
        """
        Return list of unique target IDs.

        The target IDs are sorted by the order that they first appear.

        Returns (array):
            an array of integer target IDs.
        """
        uniq, indices = np.unique(self.fibermap["TARGETID"], return_index=True)
        return uniq[indices.argsort()]


    def num_spectra(self):
        """
        Get the number of spectra contained in this group.

        Returns (int):
            Number of spectra contained in this group.
        """
        if self.fibermap is not None:
            return len(self.fibermap)
        else:
            return 0


    def num_targets(self):
        """
        Get the number of distinct targets.

        Returns (int):
            Number of unique targets with spectra in this object.
        """
        if self.fibermap is not None:
            return len(np.unique(self.fibermap["TARGETID"]))
        else:
            return 0


    def select(self, nights=None, bands=None, targets=None, fibers=None, invert=False):
        """
        Select a subset of the data.

        This filters the data based on a logical AND of the different
        criteria, optionally inverting that selection.

        Args:
            nights (list): optional list of nights to select.
            bands (list): optional list of bands to select.
            targets (list): optional list of target IDs to select.
            fibers (list): list/array of fiber indices to select.
            invert (bool): after combining all criteria, invert selection.

        Returns (Spectra):
            a new Spectra object containing the selected data.
        """
        keep_bands = None
        if bands is None:
            keep_bands = self.bands
        else:
            keep_bands = [ x for x in self.bands if x in bands ]
        if len(keep_bands) == 0:
            raise RuntimeError("no valid bands were selected!")

        if 'NIGHT' in self.fibermap.colnames: # not present in data model of coadds
            keep_nights = None
            if nights is None:
                keep_nights = [ True for x in self.fibermap["NIGHT"] ]
            else:
                keep_nights = [ (x in nights) for x in self.fibermap["NIGHT"] ]
            if sum(keep_nights) == 0:
                raise RuntimeError("no valid nights were selected!")
        else:
            keep_nights = np.ones(len(self.fibermap), bool)

        keep_targets = None
        if targets is None:
            keep_targets = [ True for x in self.fibermap["TARGETID"] ]
        else:
            keep_targets = [ (x in targets) for x in self.fibermap["TARGETID"] ]
        if sum(keep_targets) == 0:
            raise RuntimeError("no valid targets were selected!")

        keep_fibers = None
        if fibers is None:
            keep_fibers = [ True for x in self.fibermap["FIBER"] ]
        else:
            keep_fibers = [ (x in fibers) for x in self.fibermap["FIBER"] ]
        if sum(keep_fibers) == 0:
            raise RuntimeError("no valid fibers were selected!")

        keep_rows = [ (x and y and z) for x, y, z in zip(keep_nights, keep_targets, keep_fibers) ]
        if invert:
            keep_rows = [ not x for x in keep_rows ]

        keep = [ i for i, x in enumerate(keep_rows) if x ]
        if len(keep) == 0:
            raise RuntimeError("selection has no spectra")

        keep_wave = {}
        keep_flux = {}
        keep_ivar = {}
        keep_mask = None
        keep_res = None
        keep_extra = None
        if self.mask is not None:
            keep_mask = {}
        if self.resolution_data is not None:
            keep_res = {}
        if self.extra is not None:
            keep_extra = {}

        for b in keep_bands:
            keep_wave[b] = self.wave[b]
            keep_flux[b] = self.flux[b][keep,:]
            keep_ivar[b] = self.ivar[b][keep,:]
            if self.mask is not None:
                keep_mask[b] = self.mask[b][keep,:]
            if self.resolution_data is not None:
                keep_res[b] = self.resolution_data[b][keep,:,:]
            if self.extra is not None:
                keep_extra[b] = {}
                for ex in self.extra[b].items():
                    keep_extra[b][ex[0]] = ex[1][keep,:]

        ret = Spectra(keep_bands, keep_wave, keep_flux, keep_ivar, 
            mask=keep_mask, resolution_data=keep_res, 
            fibermap=self.fibermap[keep], meta=self.meta, extra=keep_extra,
            single=self._single)

        return ret

    def __getitem__(self, index):
        """Slice spectra by index"""
        if isinstance(index, numbers.Integral):
            index = slice(index, index+1)

        bands = copy.copy(self.bands)
        flux = dict()
        ivar = dict()
        wave = dict()
        mask = dict() if self.mask is not None else None
        rdat = dict() if self.resolution_data is not None else None
        extra = dict() if self.extra is not None else None

        for band in bands:
            flux[band] = self.flux[band][index].copy()
            ivar[band] = self.ivar[band][index].copy()
            wave[band] = self.wave[band].copy()
            if self.mask is not None:
                mask[band] = self.mask[band][index].copy()
            if self.resolution_data is not None:
                rdat[band] = self.resolution_data[band][index].copy()
            if self.extra is not None:
                extra[band] = dict()
                for col in self.extra[band]:
                    extra[band][col] = self.extra[band][col][index].copy()

        if self.fibermap is not None:
            fibermap = self.fibermap[index].copy()
        else:
            fibermap = None

        if self.extra_catalog is not None:
            extra_catalog = self.extra_catalog[index].copy()
        else:
            extra_catalog = None

        if self.scores is not None:
            scores = Table()
            for col in self.scores.dtype.names:
                scores[col] = self.scores[col][index].copy()
        else:
            scores = None

        sp = Spectra(bands, wave, flux, ivar,
            mask=mask, resolution_data=rdat, fibermap=fibermap,
            meta=self.meta, extra=extra, scores=scores, extra_catalog=extra_catalog,
        )
        return sp

    def update(self, other):
        """
        Overwrite or append new data.

        Given another Spectra object, compare the fibermap information with
        the existing one.  For spectra that already exist, overwrite existing 
        data with the new values.  For spectra that do not exist, append that 
        data to the end of the spectral data.

        Args:
            other (Spectra): the new data to add.

        Returns:
            nothing (object updated in place).

        Note: does not support updating extra_catalog
        """

        # Does the other Spectra object have any data?

        if other.num_spectra() == 0:
            return

        # Do we have new bands to add?

        newbands = []
        for b in other.bands:
            if b not in self.bands:
                newbands.append(b)
            else:
                if not np.allclose(self.wave[b], other.wave[b]):
                    raise RuntimeError("band {} has an incompatible wavelength grid".format(b))

        bands = list(self.bands)
        bands.extend(newbands)

        # Are we adding mask data in this update?

        add_mask = False
        if other.mask is None:
            if self.mask is not None:
                raise RuntimeError("existing spectra has a mask, cannot "
                    "update it to a spectra with no mask")
        else:
            if self.mask is None:
                add_mask = True

        # Are we adding resolution data in this update?

        ndiag = {}

        add_res = False
        if other.resolution_data is None:
            if self.resolution_data is not None:
                raise RuntimeError("existing spectra has resolution data, cannot "
                    "update it to a spectra with none")
        else:
            if self.resolution_data is not None:
                for b in self.bands:
                    ndiag[b] = self.resolution_data[b].shape[1]
                for b in other.bands:
                    odiag = other.resolution_data[b].shape[1]
                    if b not in self.bands:
                        ndiag[b] = odiag
                    else:
                        if odiag != ndiag[b]:
                            raise RuntimeError("Resolution matrices for a"
                                " given band must have the same dimensoins")
            else:
                add_res = True
                for b in other.bands:
                    ndiag[b] = other.resolution_data[b].shape[1]

        # Are we adding extra data in this update?

        add_extra = False
        if other.extra is None:
            if self.extra is not None:
                raise RuntimeError("existing spectra has extra data, cannot "
                    "update it to a spectra with none")
        else:
            if self.extra is None:
                add_extra = True

        # Compute which targets / exposures are new

        nother = len(other.fibermap)
        exists = np.zeros(nother, dtype=np.int)

        indx_original = []

        if self.fibermap is not None:
            for r in range(nother):
                expid = other.fibermap[r]["EXPID"]
                fiber = other.fibermap[r]["FIBER"]
                for i, row in enumerate(self.fibermap):
                    if (expid == row["EXPID"]) and (fiber == row["FIBER"]):
                        indx_original.append(i)
                        exists[r] += 1

        if len(np.where(exists > 1)[0]) > 0:
            raise RuntimeError("found duplicate spectra (same EXPID and FIBER) in the fibermap")

        indx_exists = np.where(exists == 1)[0]
        indx_new = np.where(exists == 0)[0]

        # Make new data arrays of the correct size to hold both the old and 
        # new data

        nupdate = len(indx_exists)
        nnew = len(indx_new)

        if self.fibermap is None:
            nold = 0
            newfmap = other.fibermap.copy()
        else:
            nold = len(self.fibermap)
            newfmap = encode_table(np.zeros( (nold + nnew, ),
                                   dtype=self.fibermap.dtype))
        
        newwave = {}
        newflux = {}
        newivar = {}
        
        newmask = None
        if add_mask or self.mask is not None:
            newmask = {}
        
        newres = None
        newR = None
        if add_res or self.resolution_data is not None:
            newres = {}
            newR = {}

        newextra = None
        if add_extra or self.extra is not None:
            newextra = {}

        for b in bands:
            nwave = None
            if b in self.bands:
                nwave = self.wave[b].shape[0]
                newwave[b] = self.wave[b]
            else:
                nwave = other.wave[b].shape[0]
                newwave[b] = other.wave[b].astype(self._ftype)
            newflux[b] = np.zeros( (nold + nnew, nwave), dtype=self._ftype)
            newivar[b] = np.zeros( (nold + nnew, nwave), dtype=self._ftype)
            if newmask is not None:
                newmask[b] = np.zeros( (nold + nnew, nwave), dtype=np.uint32)
                newmask[b][:,:] = specmask["NODATA"]
            if newres is not None:
                newres[b] = np.zeros( (nold + nnew, ndiag[b], nwave), dtype=self._ftype)
            if newextra is not None:
                newextra[b] = {}

        # Copy the old data

        if nold > 0:
            # We have some data (i.e. we are not starting with an empty Spectra)
            newfmap[:nold] = self.fibermap

            for b in self.bands:
                newflux[b][:nold,:] = self.flux[b]
                newivar[b][:nold,:] = self.ivar[b]
                if self.mask is not None:
                    newmask[b][:nold,:] = self.mask[b]
                elif add_mask:
                    newmask[b][:nold,:] = 0
                if self.resolution_data is not None:
                    newres[b][:nold,:,:] = self.resolution_data[b]
                if self.extra is not None:
                    for ex in self.extra[b].items():
                        newextra[b][ex[0]] = np.zeros( newflux[b].shape,
                            dtype=self._ftype)
                        newextra[b][ex[0]][:nold,:] = ex[1]

        # Update existing spectra

        for i, s in enumerate(indx_exists):
            row = indx_original[i]
            for b in other.bands:
                newflux[b][row,:] = other.flux[b][s,:].astype(self._ftype)
                newivar[b][row,:] = other.ivar[b][s,:].astype(self._ftype)
                if other.mask is not None:
                    newmask[b][row,:] = other.mask[b][s,:]
                else:
                    newmask[b][row,:] = 0
                if other.resolution_data is not None:
                    newres[b][row,:,:] = other.resolution_data[b][s,:,:].astype(self._ftype)
                if other.extra is not None:
                    for ex in other.extra[b].items():
                        if ex[0] not in newextra[b]:
                            newextra[b][ex[0]] = np.zeros(newflux[b].shape,
                                dtype=self._ftype)
                        newextra[b][ex[0]][row,:] = ex[1][s,:].astype(self._ftype)

        # Append new spectra

        if nnew > 0:
            newfmap[nold:] = other.fibermap[indx_new]

            for b in other.bands:
                newflux[b][nold:,:] = other.flux[b][indx_new].astype(self._ftype)
                newivar[b][nold:,:] = other.ivar[b][indx_new].astype(self._ftype)
                if other.mask is not None:
                    newmask[b][nold:,:] = other.mask[b][indx_new]
                else:
                    newmask[b][nold:,:] = 0
                if other.resolution_data is not None:
                    newres[b][nold:,:,:] = other.resolution_data[b][indx_new].astype(self._ftype)
                if other.extra is not None:
                    for ex in other.extra[b].items():
                        if ex[0] not in newextra[b]:
                            newextra[b][ex[0]] = np.zeros(newflux[b].shape,
                                dtype=self._ftype)
                        newextra[b][ex[0]][nold:,:] = ex[1][indx_new].astype(self._ftype)

        # Update all sparse resolution matrices

        for b in bands:
            if newres is not None:
                newR[b] = np.array( [ Resolution(r) for r in newres[b] ] )

        # Swap data into place

        self._bands = bands
        self.wave = newwave
        self.fibermap = newfmap
        self.flux = newflux
        self.ivar = newivar
        self.mask = newmask
        self.resolution_data = newres
        self.R = newR
        self.extra = newextra

        return

def stack(speclist):
    """
    Stack a list of spectra, return a new spectra object

    Args:
        speclist : list of Spectra objects

    returns stacked Spectra object

    Note: all input spectra must have the same bands, wavelength grid,
    and include or not the same optional elements (mask, fibermap, extra, ...).
    The returned Spectra have the meta from the first input Spectra.

    Also see Spectra.update, which is less efficient but more flexible for
    handling heterogeneous inputs
    """
    flux = dict()
    ivar = dict()
    wave = dict()
    bands = copy.copy(speclist[0].bands)
    for band in bands:
        flux[band] = np.vstack([sp.flux[band] for sp in speclist])
        ivar[band] = np.vstack([sp.ivar[band] for sp in speclist])
        wave[band] = speclist[0].wave[band].copy()

    if speclist[0].mask is not None:
        mask = dict()
        for band in bands:
            mask[band] = np.vstack([sp.mask[band] for sp in speclist])
    else:
        mask = None

    if speclist[0].resolution_data is not None:
        rdat = dict()
        for band in bands:
            rdat[band] = np.vstack([sp.resolution_data[band] for sp in speclist])
    else:
        rdat = None

    if speclist[0].fibermap is not None:
        if isinstance(speclist[0].fibermap, np.ndarray):
            #- note named arrays need hstack not vstack
            fibermap = np.hstack([sp.fibermap for sp in speclist])
        else:
            import astropy.table
            if isinstance(speclist[0].fibermap, astropy.table.Table):
                fibermap = astropy.table.vstack([sp.fibermap for sp in speclist])
            else:
                raise ValueError("Can't stack fibermaps of type {}".format(
                    type(speclist[0].fibermap)))
    else:
        fibermap = None

    if speclist[0].extra_catalog is not None:
        if isinstance(speclist[0].extra_catalog, np.ndarray):
            #- note named arrays need hstack not vstack
            extra_catalog = np.hstack([sp.extra_catalog for sp in speclist])
        else:
            import astropy.table
            if isinstance(speclist[0].extra_catalog, astropy.table.Table):
                extra_catalog = astropy.table.vstack([sp.extra_catalog for sp in speclist])
            else:
                raise ValueError("Can't stack extra_catalogs of type {}".format(
                    type(speclist[0].extra_catalog)))
    else:
        extra_catalog = None

    if speclist[0].extra is not None:
        extra = dict()
        for band in bands:
            extra[band] = dict()
            for col in speclist[0].extra[band]:
                extra[band][col] = np.concatenate([sp.extra[band][col] for sp in speclist])
    else:
        extra = None

    if speclist[0].scores is not None:
        scores = Table()
        for col in speclist[0].scores.dtype.names:
            scores[col] = np.concatenate([sp.scores[col] for sp in speclist])
    else:
        scores = None

    sp = Spectra(bands, wave, flux, ivar,
        mask=mask, resolution_data=rdat, fibermap=fibermap,
        meta=speclist[0].meta, extra=extra, scores=scores,
        extra_catalog=extra_catalog,
    )
    return sp
