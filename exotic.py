# Copyright (c) 2002-2019, California Institute of Technology.
# All rights reserved.  Based on Government Sponsored Research under contracts NNN12AA01C, NAS7-1407 and/or NAS7-03001.

# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#    1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
#    2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#    3. Neither the name of the California Institute of Technology (Caltech), its operating division the Jet Propulsion Laboratory (JPL), the National Aeronautics and Space Administration (NASA), nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE CALIFORNIA INSTITUTE OF TECHNOLOGY BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


####################################################################
# EXOplanet Transit Interpretation Code (EXOTIC)
#
# Authors: Ethan Blaser, Rob Zellem, Kyle Pearson, Tamim Fatahi, Marlee Smith, Aaron Tran, John Engelke, Sujay Nair, Jon Varghese, Michael Fitzgerald
# Supplemental Code: Kyle Pearson, Gael Roudier, and Jason Eastman
####################################################################

# EXOTIC version number
# Now adhering to the Semantic Versioning 2.0.0
# Given a version number MAJOR.MINOR.PATCH, increment the:
# MAJOR version when you make incompatible API changes,
# MINOR version when you add functionality in a backwards compatible manner, and
# PATCH version when you make backwards compatible bug fixes.
# Additional labels for pre-release and build metadata are available as extensions to the MAJOR.MINOR.PATCH format.
# https://semver.org
versionid = "0.12.1"


# --IMPORTS -----------------------------------------------------------
print("Importing Python Packages - please wait.")

import itertools
import threading
import time
import sys

print('Python Version: %s' % sys.version)

# To increase memory allocation for EXOTIC; allows for more fits files
# import resource
# resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

# here is the animation
def animate():
    for c in itertools.cycle(['|', '/', '-', '\\']):
        if done:
            break
        sys.stdout.write('\rThinking ' + c)
        sys.stdout.flush()
        time.sleep(0.1)
    # sys.stdout.write('\nDone!     \n')
    # print('\nDone!     \n')


done = False
t = threading.Thread(target=animate, daemon=True)
t.start()

import os
import json
import logging
import platform
import argparse
import glob as g
from io import StringIO

# data processing
import pandas
import requests
import numpy as np

# julian conversion imports
import dateutil.parser as dup

# UTC to BJD converter import
from barycorrpy import utc_tdb

# Curve fitting imports
from scipy.optimize import least_squares

# Pyplot imports
import matplotlib.pyplot as plt
from astropy.visualization import astropy_mpl_style
from matplotlib.animation import FuncAnimation

plt.style.use(astropy_mpl_style)

# MCMC imports
import pymc3 as pm
import theano.compile.ops as tco
import theano.tensor as tt

# astropy imports
import astropy.time
import astropy.coordinates
from astropy.io import fits
from astropy.stats import sigma_clip
import astropy.units as u
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.wcs import WCS

# Image alignment import
import astroalign as aa

# photometry
from photutils import CircularAperture
from photutils import aperture_photometry

# cross corrolation imports
from skimage.registration import phase_cross_correlation

# Lightcurve imports
# TODO fix conflicts
from gaelLCFuncs import *
from occultquad import *

# long process here
# time.sleep(10)
done = True

# ################### START PROPERTIES ########################################
# CONFIGURATIONS
requests_timeout = 16, 512  # connection timeout, response timeout in secs.

# SHARED CONSTANTS
pi = 3.14159
au = 1.496e11  # m
rsun = 6.955e8  # m
rjup = 7.1492e7  # m
G = 0.00029591220828559104  # day, AU, Msun

# SHARED LAMBDAS
# keplerian semi-major axis (au)
sa = lambda m, P: (G*m*P**2/(4*pi**2))**(1./3)
# ################### END PROPERTIES ##########################################


# ---HELPER FUNCTIONS----------------------------------------------------------------------
# Function that bins an array
def binner(arr, n, err=''):
    if len(err) == 0:
        ecks = np.pad(arr.astype(float), (0, ((n - arr.size % n) % n)), mode='constant', constant_values=np.NaN).reshape(-1, n)
        arr = np.nanmean(ecks, axis=1)
        return arr
    else:
        ecks = np.pad(arr.astype(float), (0, ((n - arr.size % n) % n)), mode='constant', constant_values=np.NaN).reshape(-1, n)
        why = np.pad(err.astype(float), (0, ((n - err.size % n) % n)), mode='constant', constant_values=np.NaN).reshape(-1, n)
        weights = 1./(why**2.)
        # Calculate the weighted average
        arr = np.nansum(ecks * weights, axis=1) / np.nansum(weights, axis=1)
        err = np.array([np.sqrt(1. / np.nansum(1. / (np.array(i) ** 2.))) for i in why])
        return arr, err


# ################### START ARCHIVE SCRAPER (PRIORS) ##########################
def dataframe_to_jsonfile(dataframe, filename):
    jsondata = json.loads(dataframe.to_json(orient='table', index=False))
    with open(filename, "w") as f:
        f.write(json.dumps(jsondata['data'], indent=4))


def tap_query(base_url, query, dataframe=True):
    # table access protocol query

    # build url
    uri_full = base_url
    for k in query:
        if k != "format":
            uri_full += "{} {} ".format(k, query[k])

    uri_full = uri_full[:-1] + "&format={}".format(query.get("format", "csv"))
    uri_full = uri_full.replace(' ', '+')
    print(uri_full)

    response = requests.get(uri_full, timeout=requests_timeout)
    # TODO check status_code?

    if dataframe:
        return pandas.read_csv(StringIO(response.text))
    else:
        return response.text


def new_scrape(filename="eaConf.json"):

    # scrape_new()
    uri_ipac_base = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query="
    uri_ipac_query = {
        # Table columns: https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html
        "select"   : "pl_name,hostname,tran_flag,pl_massj,pl_radj,pl_ratdor,"
                     "pl_orbper,pl_orbpererr1,pl_orbpererr2,pl_orbeccen,"
                     "pl_orbincl,pl_orblper,pl_tranmid,pl_tranmiderr1,pl_tranmiderr2,"
                     "st_teff,st_tefferr1,st_tefferr2,st_met,st_meterr1,st_meterr2,"
                     "st_logg,st_loggerr1,st_loggerr2,st_mass,st_rad,ra,dec",
        "from"     : "ps",  # Table name
        "where"    : "tran_flag = 1 and default_flag = 1",
        "order by" : "pl_name",
        "format"   : "csv"
    }

    default = tap_query(uri_ipac_base, uri_ipac_query)

    # fill in missing columns
    uri_ipac_query['where'] = 'tran_flag=1'
    extra = tap_query(uri_ipac_base, uri_ipac_query)

    # for each planet
    for i in default.pl_name:

        # extract rows for each planet
        ddata = default.loc[default.pl_name == i]
        edata = extra.loc[extra.pl_name == i]

        # for each nan column in default
        nans = ddata.isna()
        for k in ddata.keys():
            if nans[k].bool():  # if col value is nan
                if not edata[k].isna().all():  # if replacement data exists
                    # replace with first index
                    default.loc[default.pl_name == i, k] = edata[k][edata[k].notna()].values[0]
                    # TODO could use mean for some variables (not mid-transit)
                    # print(i,k,edata[k][edata[k].notna()].values[0])
                else:
                    # permanent nans - require manual entry
                    if k == 'pl_orblper':  # omega
                        default.loc[default.pl_name == i, k] = 0
                    elif k == 'pl_ratdor':  # a/R*
                        # Kepler's 3rd law
                        semi = sa(ddata.st_mass.values[0], ddata.pl_orbper.values[0])
                        default.loc[default.pl_name == i, k] = semi*au / (ddata.st_rad.values[0]*rsun)
                    elif k == 'pl_orbincl':  # inclination
                        default.loc[default.pl_name == i, k] = 90
                    elif k == "pl_orbeccen":  # eccentricity
                        default.loc[default.pl_name == i, k] = 0
                    elif k == "st_met":  # [Fe/H]
                        default.loc[default.pl_name == i, k] = 0

    dataframe_to_jsonfile(default, filename)


def new_getParams(data):
    # translate data from Archive keys to Ethan Keys

    planetDictionary = {
        'ra': data['ra'],
        'dec': data['dec'],
        'pName': data['pl_name'],
        'sName': data['hostname'],
        'pPer': data['pl_orbper'],
        'pPerUnc': data['pl_orbpererr1'],
        'midT': data['pl_tranmid'],
        'midTUnc': data['pl_tranmiderr1'],
        'rprs': data['pl_radj']*rjup/(data['st_rad']*rsun),
        'aRs': data['pl_ratdor'],
        'inc': data['pl_orbincl'],
        'ecc': data.get('pl_orbeccen', 0),
        'teff': data['st_teff'],
        'teffUncPos': data['st_tefferr1'],
        'teffUncNeg': data['st_tefferr2'],
        'met': data['st_met'],
        'metUncPos': data['st_meterr1'],
        'metUncNeg': data['st_meterr2'],
        'logg': data['st_logg'],
        'loggUncPos': data['st_loggerr1'],
        'loggUncNeg': data['st_loggerr2'],
        'flag': data['tran_flag']
    }

    return planetDictionary
# ################### END ARCHIVE SCRAPER (PRIORS) ############################


# Method that gets and returns the julian time of the observation
def getJulianTime(hdul):
    exptime_offset = 0
    # Grab the BJD first
    if 'BJD_TDB' in hdul[0].header:
        julianTime = float(hdul[0].header['BJD_TDB'])
        # If the time is from the beginning of the observation, then need to calculate mid-exposure time
        if "start" in hdul[0].header.comments['BJD_TDB']:
            exptime_offset = hdul[0].header['EXPTIME'] / 2. / 60. / 60. / 24.  # assume exptime is in seconds for now
    elif 'BJD' in hdul[0].header:
        julianTime = float(hdul[0].header['BJD'])
        # If the time is from the beginning of the observation, then need to calculate mid-exposure time
        if "start" in hdul[0].header.comments['BJD']:
            exptime_offset = hdul[0].header['EXPTIME'] / 2. / 60. / 60. / 24.  # assume exptime is in seconds for now
    # then the DATE-OBS
    elif "UT-OBS" in hdul[0].header:
        gDateTime = hdul[0].header['UT-OBS']  # gets the gregorian date and time from the fits file header
        dt = dup.parse(gDateTime)
        time = astropy.time.Time(dt)
        julianTime = time.jd
        # If the time is from the beginning of the observation, then need to calculate mid-exposure time
        if "start" in hdul[0].header.comments['UT-OBS']:
            exptime_offset = hdul[0].header['EXPTIME'] / 2. / 60. / 60. / 24.  # assume exptime is in seconds for now
    # Then Julian Date
    elif 'JULIAN' in hdul[0].header:
        julianTime = float(hdul[0].header['JULIAN'])
        # If the time is from the beginning of the observation, then need to calculate mid-exposure time
        if "start" in hdul[0].header.comments['JULIAN']:
            exptime_offset = hdul[0].header['EXPTIME'] / 2. / 60. / 60. / 24.  # assume exptime is in seconds for now
    # Then MJD-OBS last, as in the MicroObservatory headers, it has less precision
    elif "MJD-OBS" in hdul[0].header:
        julianTime = float(hdul[0].header["MJD-OBS"]) + 2400000.5
        # If the time is from the beginning of the observation, then need to calculate mid-exposure time
        if "start" in hdul[0].header.comments['MJD-OBS']:
            exptime_offset = hdul[0].header['EXPTIME'] / 2. / 60. / 60. / 24.  # assume exptime is in seconds for now
    else:
        gDateTime = hdul[0].header['DATE-OBS']  # gets the gregorian date and time from the fits file header
        dt = dup.parse(gDateTime)
        time = astropy.time.Time(dt)
        julianTime = time.jd
        # If the time is from the beginning of the observation, then need to calculate mid-exposure time
        if "start" in hdul[0].header.comments['DATE-OBS']:
            exptime_offset = hdul[0].header['EXPTIME'] / 2. / 60. / 60. / 24.  # assume exptime is in seconds for now

    # If the mid-exposure time is given in the fits header, then no offset is needed to calculate the mid-exposure time
    return julianTime + exptime_offset


# Method that gets and returns the current phase of the target
def getPhase(curTime, pPeriod, tMid):
    phase = ((curTime - tMid) / pPeriod) % 1
    if phase >= .5:
        return -1 * (1 - phase)
    else:
        return phase


# Method that gets and returns the airmass from the fits file (Really the Altitude)
def getAirMass(hdul, ra, dec, lati, longit, elevation):
    # Grab airmass from image header; if not listed, calculate it from TELALT; if that isn't listed, then calculate it the hard way
    if 'AIRMASS' in hdul[0].header:
        am = float(hdul[0].header['AIRMASS'])
    elif 'TELALT' in hdul[0].header:
        alt = float(hdul[0].header['TELALT'])  # gets the airmass from the fits file header in (sec(z)) (Secant of the zenith angle)
        cosam = np.cos((np.pi / 180) * (90.0 - alt))
        am = 1 / cosam
    else:
        # pointing = SkyCoord(str(astropy.coordinates.Angle(raStr+" hours").deg)+" "+str(astropy.coordinates.Angle(decStr+" degrees").deg ), unit=(u.deg, u.deg), frame='icrs')
        pointing = SkyCoord(str(ra)+" "+str(dec), unit=(u.deg, u.deg), frame='icrs')

        location = EarthLocation.from_geodetic(lat=lati*u.deg, lon=longit*u.deg, height=elevation)
        time = astropy.time.Time(getJulianTime(hdul), format='jd', scale='utc', location=location)
        pointingAltAz = pointing.transform_to(AltAz(obstime=time, location=location))
        am = float(pointingAltAz.secz)
    return am


# Validate user input
def user_input(prompt, type_, val1=None, val2=None, val3=None):
    while True:
        try:
            option = type_(input(prompt))
        except ValueError:
            print('Sorry, not a valid data type.')
            continue
        if type_ == str and val1 and val2:
            option = option.lower()
            if option not in (val1, val2):
                print("Sorry, your response was not valid.")
            else:
                return option
        elif type_ == int and val1 and val2 and val3:
            if option not in (val1, val2, val3):
                print("Sorry, your response was not valid.")
            else:
                return option
        elif type_ == int and val1 and val2:
            if option not in (val1, val2):
                print("Sorry, your response was not valid.")
            else:
                return option
        elif type_ == int or type_ == float or type_ == str:
            return option


# Create a save directory within the current working directory
def create_directory():
    while True:
        try:
            directoryname = input('Enter the name for your new directory: ')
            newdirectoryPath = os.getcwd()
            savedirectory = newdirectoryPath + '/' + directoryname + '/'
            os.mkdir(savedirectory)
        except OSError:
            print("Creation of the directory %s failed" % savedirectory)
        else:
            print("Successfully created the directory %s " % savedirectory)
            return savedirectory


# Check user's inits.json for user information and planetary parameters
def inits_file(initspath, dictinfo, dictplanet):
    with open(initspath) as json_file:
        data = json.load(json_file)

    initdictinfo = data['user_info']
    initdictplanet = data['planetary_parameters']

    for key, key2 in zip(dictinfo, initdictinfo[0]):
        dictinfo[key] = initdictinfo[0][key2]

    for key, key2 in zip(dictplanet, initdictplanet[0]):
        dictplanet[key] = initdictplanet[0][key2]

    return dictinfo, dictplanet


# --------PLANETARY PARAMETERS UI------------------------------------------
# Get the user's confirmation of values that will later be used in lightcurve fit
def get_planetary_parameters(candplanetbool, userpdict, pdict=None):
    print('\n*******************************************')
    print("Planetary Parameters for Lightcurve Fitting\n")

    # The order of planet_params list must match the pDict that is declared when scraping the NASA Exoplanet Archive
    planet_params = ["Target Star RA in the form: HH:MM:SS (ignore the decimal values)",
                     "Target Star DEC in form: <sign>DD:MM:SS (ignore the decimal values and don't forget the '+' or '-' sign!)",
                     "Planet's Name",
                     "Host Star's Name",
                     "Orbital Period (days)",
                     "Orbital Period Uncertainty (days) \nKeep in mind that 1.2e-34 is the same as 1.2 x 10^-34",
                     "Published Mid-Transit Time (BJD_UTC)",
                     "Mid-Transit Time Uncertainty (JD)",
                     "Ratio of Planet to Stellar Radius (Rp/Rs)",
                     "Ratio of Distance to Stellar Radius (a/Rs)",
                     "Orbital Inclination (deg)",
                     "Orbital Eccentricity (0 if null)",
                     "Star Effective Temperature (K)",
                     "Star Effective Temperature Positive Uncertainty (K)",
                     "Star Effective Temperature Negative Uncertainty (K)",
                     "Star Metallicity ([FE/H])",
                     "Star Metallicity Positive Uncertainty ([FE/H])",
                     "Star Metallicity Negative Uncertainty ([FE/H])",
                     "Star Surface Gravity (log(g))",
                     "Star Surface Gravity Positive Uncertainty (log(g))",
                     "Star Surface Gravity Negative Uncertainty (log(g))"]

    # Conversion between hours to degrees if user entered ra and dec
    if userpdict['ra'] is None:
        userpdict['ra'] = input('\nEnter the %s: ' % planet_params[0])
    if userpdict['dec'] is None:
        userpdict['dec'] = input('\nEnter the %s: ' % planet_params[1])
    userpdict['ra'], userpdict['dec'] = radec_hours_to_degree(userpdict['ra'], userpdict['dec'])

    radeclist = ['ra', 'dec']
    if not candplanetbool:
        for idx, item in enumerate(radeclist):
            if pdict[item] - 0.00556 <= userpdict[item] <= pdict[item] + 0.00556:
                continue
            else:
                print("\n\n*** WARNING: %s initialization file's %s does not match the NASA Exoplanet Archive. ***\n" % (pdict['pName'], planet_params[idx]))
                print("\tNASA Exoplanet Archive value: %s" % pdict[item])
                print("\tInitialization file value: %s" % userpdict[item])
                print("\nWould you like to: (1) use NASA Exoplanet Archive value, (2) use initialization file value, or (3) enter in a new value.")
                option = user_input('Which option do you choose? (1/2/3): ', type_=int, val1=1, val2=2, val3=3)
                if option == 1:
                    userpdict[item] = pdict[item]
                elif option == 2:
                    continue
                else:
                    userpdict['ra'] = user_input('Enter the ' + planet_params[0] + ': ', type_=str)
                    userpdict['dec'] = user_input('Enter the ' + planet_params[1] + ': ', type_=str)
                    break

    if type(userpdict['ra']) and type(userpdict['dec']) is str:
        userpdict['ra'], userpdict['dec'] = radec_hours_to_degree(userpdict['ra'], userpdict['dec'])

    # Exoplanet confirmed in NASA Exoplanet Archive
    if not candplanetbool:
        print('\n\n*** Here are the values scraped from the NASA Exoplanet Archive for %s that were not set (or set to null) in your initialization file. ***' % pdict['pName'])
        print('For each planetary parameter, enter "y" if you agree and "n" if you disagree.')
        # print('enter "1" to use NASA Exoplanet Archive value, "2" to use initialization file value, or "3" to enter a new value if you ')
        # print('decided to use an initialization file.')

        for i, key in enumerate(userpdict):
            if key in ('ra', 'dec'):
                continue
            if key in ('pName', 'sName'):
                userpdict[key] = pdict[key]
            # Initialization planetary parameters match NEA
            if pdict[key] == userpdict[key]:
                continue
            # Initialization planetary parameters don't match NASA Exoplanet Archive
            if userpdict[key] is not None:
                print("\n\n*** WARNING: %s initialization file's %s does not match the NASA Exoplanet Archive. ***\n" % (pdict['pName'], planet_params[i]))
                print("\tNASA Exoplanet Archive value: %s" % pdict[key])
                print("\tInitialization file value: %s" % userpdict[key])
                print("\nWould you like to: (1) use NASA Exoplanet Archive value, (2) use initialization file value, or (3) enter in a new value.")
                option = user_input('Which option do you choose? (1/2/3): ', type_=int, val1=1, val2=2, val3=3)
                if option == 1:
                    userpdict[key] = pdict[key]
                elif option == 2:
                    continue
                else:
                    userpdict[key] = user_input('Enter the ' + planet_params[i] + ': ', type_=type(userpdict[key]))
            # Did not use initialization file
            else:
                print('\n' + pdict['pName'] + ' ' + planet_params[i] + ': ' + str(pdict[key]))
                agreement = user_input('Do you agree? (y/n): ', type_=str, val1='y', val2='n')
                if agreement == 'y':
                    userpdict[key] = pdict[key]
                else:
                    userpdict[key] = user_input('Enter the ' + planet_params[i] + ': ', type_=type(pdict[key]))

    # Exoplanet not confirmed in NASA Exoplanet Archive
    else:
        for i, key in enumerate(userpdict):
            if key in ('ra', 'dec'):
                continue
            # Used initialization file and is not empty
            if userpdict[key] is not None:
                agreement = user_input('%s: %s \nDo you agree? (y/n): '
                                       % (planet_params[i], userpdict[key]), type_=str, val1='y', val2='n')
                if agreement == 'y':
                    continue
                else:
                    userpdict[key] = user_input('Enter the ' + planet_params[i] + ': ', type_=type(userpdict[key]))
            # Did not use initialization file
            else:
                if key in ('pName', 'sName'):
                    userpdict[key] = input('\nEnter the ' + planet_params[i] + ': ')
                else:
                    userpdict[key] = user_input('Enter the ' + planet_params[i] + ': ', type_=float)
    return userpdict


def radec_hours_to_degree(ra, dec):
    while True:
        try:
            ra = ra.replace(' ', '').replace(':', ' ')
            dec = dec.replace(' ', '').replace(':', ' ')
            c = SkyCoord(ra + ' ' + dec, unit=(u.hourangle, u.deg))
            return c.ra.degree, c.dec.degree
        except ValueError:
            print('Error: The format is not correct, please try again.')
            ra = input('Input the right ascension of target (HH:MM:SS): ')
            dec = input('Input the declination of target (<sign>DD:MM:SS): ')


# Check if user's directory contains imaging files that are able to be reduced
def check_file_extensions(directory, filename):
    # Find fits files
    file_extensions = ['.fits', '.fit', '.fts']
    inputfiles = []

    while True:
        try:
            # Add / to end of directory if user does not input it
            if directory[-1] != "/":
                directory += "/"

            if os.path.isdir(directory):
                # Loop until we find something
                for exti in file_extensions:
                    for file in os.listdir(directory):
                        if file.lower().endswith(exti.lower()):
                            inputfiles.append(os.path.join(directory, file))
                    # If we find files, then stop the for loop and while loop
                    if inputfiles:
                        return directory, inputfiles

                # If we don't find any files, then we need the user to check their directory and loop over again
                if not inputfiles:
                    raise FileNotFoundError

            # If the directory does not exist
            else:
                raise OSError

        except FileNotFoundError:
            extaddoption = user_input("\nError: " + filename + " files not found with .fits, .fit or .fts extensions in " + directory +
                                      ".\nWould you like to enter in an extension related to .FITS? (y/n): ", type_=str, val1='y', val2='n')
            if extaddoption == 'y':
                file_extensions.append(input('Please enter the extension you want to add (EX: .FITS): '))
            else:
                directory = input("Enter the directory path where " + filename + " files are located: ")
        except OSError:
            print("Error: No such directory exists. Please try again.")
            directory = input("Enter the directory path where " + filename + " files are located: ")


# Check for WCS in the user's imaging data and possibly plate solves.
def check_wcs(fits_file, saveDirectory):
    hdulist = fits.open(name=fits_file, memmap=False, cache=False, lazy_load_hdus=False)  # opens the fits file
    header = hdulist[0].header
    hdulist.close()  # close stream
    del hdulist

    # MJD seems sometimes throw off an error. Deleted since not important for plate solving
    try:
        del header['MJD-OBS']
    except:
        pass

    # Gets the WCS of the header and checks to see if it exists
    wcsheader = WCS(header)
    wcsExists = wcsheader.is_celestial

    # If the fits file has WCS info, ask the user if they trust it
    if wcsExists:
        trustWCS = user_input('The imaging data from your file has WCS information. Do you trust this? (y/n): ', type_=str, val1='y', val2='n')
    else:
        trustWCS = 'n'

    if trustWCS == 'n':
        plateSol = user_input("\nWould you like to upload the your image for a plate solution?"
                              "\nDISCLAIMER: One of your imaging files will be publicly viewable on nova.astrometry.net. (y/n): ", type_=str, val1='y', val2='n')
        # Plate solve the fits file
        if plateSol == 'y':
            print("\nGetting the plate solution for your imaging file. Please wait.")
            global done
            done = False
            t = threading.Thread(target=animate, daemon=True)
            t.start()

            # Plate solves the first imaging file
            imagingFile = fits_file
            wcsFile = plate_solution(imagingFile, saveDirectory)
            done = True

            # Return plate solution from nova.astrometry.net
            return wcsFile
        else:
            # User either did not want a plate solution or had one in file header and decided not to use it,
            # therefore return nothing
            return False
    else:
        # User trusted their imaging file header's WCS
        return fits_file


# Gets the WCS of a .fits file for the user from nova.astrometry.net w/ API key
def plate_solution(fits_file, saveDirectory):
    default_url = 'http://nova.astrometry.net/api/'

    # Login to Exoplanet Watch's profile w/ API key. If session fails, allow 5 attempts of
    # rejoining before returning False and informing user of technical failure.
    for i in range(5):
        try:
            r = requests.post(default_url + 'login', data={'request-json': json.dumps({"apikey": "vfsyxlmdxfryhprq"})})
            sess = r.json()['session']
            break
        except KeyError:
            if i == 4:
                print('Imaging file could not receive a plate solution due to technical difficulties '
                      'from nova.astrometry.net. Please try again later. Data reduction will continue.')
                return False
            time.sleep(5)
            continue

    # Saves session number to upload imaging file
    files = {'file': open(fits_file, 'rb')}
    headers = {'request-json': json.dumps({"session": sess}), 'allow_commercial_use': 'n',
               'allow_modifications': 'n', 'publicly_visible': 'n'}

    # Uploads the .fits file to nova.astrometry.net
    r = requests.post(default_url + 'upload', files=files, data=headers)

    # Saves submission id for checking on the status of image uploaded
    sub_id = r.json()['subid']
    submissions_url = 'http://nova.astrometry.net/api/submissions/%s' % sub_id

    # Once the image has successfully been plate solved, the following loop will break
    while True:
        r = requests.get(submissions_url)
        if r.json()['job_calibrations']:
            break
        time.sleep(5)

    # Checks the job id's status for parameters
    job_id = r.json()['jobs']
    job_url = 'http://nova.astrometry.net/api/jobs/%s' % job_id[0]
    wcs_file = saveDirectory + 'newfits.fits'

    # Checks the job id's status
    while True:
        r = requests.get(job_url)

        # If the new-fits-file is successful and downloadable, the following will execute
        if r.json()['status'] == 'success':
            fits_download_url = 'http://nova.astrometry.net/new_fits_file/%s' % job_id[0]

            # Gets the new-fits-file and downloads it
            r = requests.get(fits_download_url)
            with open(wcs_file, 'wb') as f:
                f.write(r.content)
            print('\n\nSuccess. ')
            return wcs_file

        # If the new-fits-file failed, inform user and exit
        elif r.json()['status'] == 'failure':
            print('\n\n.FITS file has failed to be given WCS.')
            return False
        time.sleep(5)


# Getting the right ascension and declination for every pixel in imaging file if there is a plate solution
def get_radec(hdulWCSrd):
    wcsheader = WCS(hdulWCSrd[0].header)
    xaxis = np.arange(hdulWCSrd[0].header['NAXIS1'])
    yaxis = np.arange(hdulWCSrd[0].header['NAXIS2'])
    x, y = np.meshgrid(xaxis, yaxis)
    ra, dec = wcsheader.all_pix2world(x, y, 0)
    return ra, dec


# Check the ra and dec against the plate solution to see if the user entered in the correct values
def check_targetpixelwcs(pixx, pixy, expra, expdec, ralist, declist):
    while True:
        try:
            # Margins are within 20 arcseconds ~ 0.00556 degrees
            if expra - 0.00556 >= ralist[pixy][pixx] or ralist[pixy][pixx] >= expra + 0.00556:
                print('\nError: The X Pixel Coordinate entered does not match the right ascension.')
                raise ValueError
            if expdec - 0.00556 >= declist[pixy][pixx] or declist[pixy][pixx] >= expdec + 0.00556:
                print('\nError: The Y Pixel Coordinate entered does not match the declination.')
                raise ValueError
            return pixx, pixy
        except ValueError:
            repixopt = user_input('Would you like to re-enter the pixel coordinates? (y/n): ', type_=str, val1='y', val2='n')

            # User wants to change their coordinates
            if repixopt == 'y':
                # Checks for the closest pixel location in ralist and declist for expected ra and dec
                dist = (ralist - expra) ** 2 + (declist - expdec) ** 2
                pixy, pixx = np.unravel_index(dist.argmin(), dist.shape)
                searchopt = user_input('Here are the suggested pixel coordinates: X Pixel: %s Y Pixel: %s'
                                       '\nWould you like to use these? (y/n): ' % (pixx, pixy), type_=str, val1='y', val2='n')
                # Use the coordinates found by code
                if searchopt == 'y':
                    return pixx, pixy
                # User enters their own coordinates to be re-checked
                else:
                    pixx = user_input("Please re-enter the target star's X Pixel Coordinate: ", type_=int)
                    pixy = user_input("Please re-enter the target star's Y Pixel Coordinate: ", type_=int)
            else:
                # User does not want to change coordinates even though they don't match the expected ra and dec
                return pixx, pixy


# Aligns imaging data from .fits file to easily track the host and comparison star's positions
def image_alignment(sortedallImageData):
    boollist = []
    notAligned = 0

    # Align images from .FITS files and catch exceptions if images can't be aligned. Keep two lists: newlist for
    # images aligned and boollist for discarded images to delete .FITS data from airmass and times.
    for i, image_file in enumerate(sortedallImageData):
        try:
            sortedallImageData[i], footprint = aa.register(image_file, sortedallImageData[0])
            boollist.append(True)
        except:
            notAligned += 1
            boollist.append(False)

    unalignedBoolList = np.array(boollist)

    if notAligned > 0:
        print('\n\n*********************************************************************')
        print('WARNING: From the given imaging files: ' + str(notAligned) + ' of ' +
              str(len(sortedallImageData) + notAligned) + ' were not aligned.')
        print('*********************************************************************')
        time.sleep(5)

    return sortedallImageData, unalignedBoolList, boollist


# defines the star point spread function as a 2D Gaussian
def star_psf(x, y, x0, y0, a, sigx, sigy, b):
    gaus = a * np.exp(-(x - x0) ** 2 / (2 * sigx ** 2)) * np.exp(-(y - y0) ** 2 / (2 * sigy ** 2)) + b
    return gaus


# Method uses the Full Width Half Max to estimate the standard deviation of the star's psf
def estimate_sigma(x, maxidx=-1):
    if maxidx == -1:
        maxidx = np.argmax(x)
    lower = np.abs(x - 0.5 * np.nanmax(x))[:maxidx].argmin()
    upper = np.abs(x - 0.5 * np.nanmax(x))[maxidx:].argmin() + maxidx
    FWHM = upper - lower
    return FWHM / (2 * np.sqrt(2 * np.log(2)))


def gaussian_psf(x,y,x0,y0,a,sigx,sigy,rot, b):
    rx = (x-x0)*np.cos(rot) - (y-y0)*np.sin(rot)
    ry = (x-x0)*np.sin(rot) + (y-y0)*np.cos(rot)
    gausx = np.exp(-(rx)**2 / (2*sigx**2) )
    gausy = np.exp(-(ry)**2 / (2*sigy**2) )
    return a*gausx*gausy + b


def fit_psf(data,pos,init,lo,up,psf_function=gaussian_psf,lossfn='linear',box=15):
    xv,yv = mesh_box(pos, box)
    def fcn2min(pars):
        model = psf_function(xv,yv,*pars)
        return (data[yv,xv]-model).flatten()
    res = least_squares(fcn2min,x0=[*pos,*init],bounds=[lo,up],loss=lossfn,jac='3-point')
    return res.x


def mesh_box(pos,box):
    pos = [int(np.round(pos[0])), int(np.round(pos[1]))]
    x = np.arange(pos[0]-box, pos[0]+box+1)
    y = np.arange(pos[1]-box, pos[1]+box+1)
    xv, yv = np.meshgrid(x, y)
    return xv.astype(int), yv.astype(int)


# Method fits a 2D gaussian function that matches the star_psf to the star image and returns its pixel coordinates
def fit_centroid(data, pos, init=None, box=10):

    # get sub field in image
    xv, yv = mesh_box(pos, box)
    wx, wy = pos # could take flux weighted centroid if not crowded

    if init:
        pass
    else:
        init = [np.nanmax(data[yv,xv])-np.nanmin(data[yv,xv]), 1, 1, 0, np.nanmin(data[yv,xv])]

    try:
        # fit gaussian PSF
        pars = fit_psf(
            data,
            [wx, wy],  # position estimate
            init,    # initial guess: [amp, sigx, sigy, rotation, bg]
            [wx-5, wy-5, 0, 0, 0, -np.pi/4, np.nanmin(data)-1 ], # lower bound: [xc, yc, amp, sigx, sigy, rotation,  bg]
            [wx+5, wy+5, 1e7, 20, 20, np.pi/4, np.nanmax(data[yv,xv])+1 ], # upper bound
            psf_function=gaussian_psf,
            box=box  # only fit a subregion +/- 5 px from centroid
        )
    except:
        import pdb; pdb.set_trace()

    return pars


# Method calculates the flux of the star (uses the skybg_phot method to do backgorund sub)
def getFlux(data, xc, yc, r=5, dr=5):

    if dr > 0:
        bgflux = skybg_phot(data, xc, yc, r, dr)
    else:
        bgflux = 0
    positions = [(xc, yc)]
    data = data-bgflux
    data[data < 0] = 0

    apertures = CircularAperture(positions, r=r)
    phot_table = aperture_photometry(data, apertures, method='exact')

    return float(phot_table['aperture_sum']), bgflux


def skybg_phot(data, xc, yc, r=10, dr=5):
    # create a crude annulus to mask out bright background pixels
    xv, yv = mesh_box([xc, yc], np.round(r+dr))
    rv = ((xv-xc)**2 + (yv-yc)**2)**0.5
    mask = (rv > r) & (rv < (r+dr))
    cutoff = np.percentile(data[yv, xv][mask], 50)
    dat = np.copy(data)
    dat[dat > cutoff] = cutoff # ignore bright pixels like stars
    return min(np.mean(dat[yv, xv][mask]), np.median(dat[yv, xv][mask]))


# Mid-Transit Time Prior Helper Functions
def numberOfTransitsAway(timeData, period, originalT):
    return int((np.nanmin(timeData) - originalT) / period) + 1


def nearestTransitTime(timeData, period, originalT):
    nearT = ((numberOfTransitsAway(timeData, period, originalT) * period) + originalT)
    return nearT


# Mid-Transit Time Error Helper Functions
def propMidTVariance(uncertainP, uncertainT, timeData, period, originalT):
    n = numberOfTransitsAway(timeData, period, originalT)
    varTMid = n * n * uncertainP + uncertainT
    return varTMid


def uncTMid(uncertainP, uncertainT, timeData, period, originalT):
    n = numberOfTransitsAway(timeData, period, originalT)
    midErr = np.sqrt((n * n * uncertainP * uncertainP) + 2 * n * uncertainP * uncertainT + (uncertainT * uncertainT))
    return midErr


def transitDuration(rStar, rPlan, period, semi):
    rSun = 6.957 * 10 ** 8  # m
    tDur = (period / np.pi) * np.arcsin((np.sqrt((rStar * rSun + rPlan * rSun) ** 2)) / (semi * rStar * rSun))
    return tDur


# calculates chi squared which is used to determine the quality of the LC fit
def chisquared(observed_values, expected_values, uncertainty):
    for chiCount in range(0, len(observed_values)):
        zeta = ((observed_values[chiCount] - expected_values[chiCount]) / uncertainty[chiCount])
        chiToReturn = np.sum(zeta ** 2)
        return chiToReturn


# make and plot the chi squared traces
def plotChi2Trace(myTrace, myFluxes, myTimes, theAirmasses, uncertainty, targetname, date):
    print("Performing Chi^2 Burn")
    print("Please be patient- this step can take a few minutes.")
    global done
    done = False
    t = threading.Thread(target=animate, daemon=True)
    t.start()

    midTArr = myTrace.get_values('Tmid', combine=False)
    radiusArr = myTrace.get_values('RpRs', combine=False)
    am1Arr = myTrace.get_values('Am1', combine=False)
    am2Arr = myTrace.get_values('Am2', combine=False)

    allchiSquared = []
    for chain in myTrace.chains:
        chiSquaredList1 = []
        for counter in np.arange(len(midTArr[chain])):  # [::25]:
            # first chain
            midT1 = midTArr[chain][counter]
            rad1 = radiusArr[chain][counter]
            am11 = am1Arr[chain][counter]
            am21 = am2Arr[chain][counter]

            fittedModel1 = lcmodel(midT1, rad1, am11, am21, myTimes, theAirmasses, plots=False)
            chis1 = np.sum(((myFluxes - fittedModel1) / uncertainty) ** 2.) / (len(myFluxes) - 4)
            chiSquaredList1.append(chis1)
        allchiSquared.append(chiSquaredList1)

    plt.figure()
    plt.xlabel('Chain Length')
    plt.ylabel('Chi^2')
    for chain in np.arange(myTrace.nchains):
        plt.plot(np.arange(len(allchiSquared[chain])), allchiSquared[chain], '-bo')
    plt.rc('grid', linestyle="-", color='black')
    plt.grid(True)
    plt.title(targetname + ' Chi^2 vs. Chain Length ' + date)
    # plt.show()
    plt.savefig(infoDict['saveplot'] + 'temp/ChiSquaredTrace' + date + targetname + '.png')
    plt.close()

    chiMedian = np.nanmedian(allchiSquared)

    burns = []
    for chain in np.arange(myTrace.nchains):
        idxburn, = np.where(allchiSquared[chain] <= chiMedian)
        if len(idxburn) == 0:
            burnno = 0
        else:
            burnno = idxburn[0]
        burns.append(burnno)

    completeBurn = np.max(burns)
    done = True
    print('Chi^2 Burn In Length: ' + str(completeBurn))

    return completeBurn


# make plots of the centroid positions as a function of time
def plotCentroids(xTarg, yTarg, xRef, yRef, times, targetname, date):
    times = np.array(times)
    # X TARGET
    plt.figure()
    plt.plot(times - np.nanmin(times), xTarg, '-bo')
    plt.xlabel('Time (JD-' + str(np.nanmin(times)) + ')')
    plt.ylabel('X Pixel Position')
    plt.title(targetname + ' X Centroid Position ' + date)
    plt.savefig(infoDict['saveplot'] + 'temp/XCentroidPosition' + targetname + date + '.png')
    plt.close()

    # Y TARGET
    plt.figure()
    plt.plot(times - np.nanmin(times), yTarg, '-bo')
    plt.xlabel('Time (JD-' + str(np.nanmin(times)) + ')')
    plt.ylabel('Y Pixel Position')
    plt.title(targetname + ' Y Centroid Position ' + date)
    plt.savefig(infoDict['saveplot'] + 'temp/YCentroidPos' + targetname + date + '.png')
    plt.close()

    # X COMP
    plt.figure()
    plt.plot(times - np.nanmin(times), xRef, '-ro')
    plt.xlabel('Time (JD-' + str(np.nanmin(times)) + ')')
    plt.ylabel('X Pixel Position')
    plt.title('Comp Star X Centroid Position ' + date)
    plt.savefig(infoDict['saveplot'] + 'temp/CompStarXCentroidPos' + date + '.png')
    plt.close()

    # Y COMP
    plt.figure()
    plt.plot(times - np.nanmin(times), yRef, '-ro')
    plt.xlabel('Time (JD-' + str(np.nanmin(times)) + ')')
    plt.ylabel('Y Pixel Position')
    plt.title('Comp Star Y Centroid Position ' + date)
    plt.savefig(infoDict['saveplot'] + 'temp/CompStarYCentroidPos' + date + '.png')
    plt.close()

    # X DISTANCE BETWEEN TARGET AND COMP
    plt.figure()
    plt.xlabel('Time (JD-' + str(np.nanmin(times)) + ')')
    plt.ylabel('X Pixel Distance')
    for e in range(0, len(xTarg)):
        plt.plot(times[e] - np.nanmin(times), abs(int(xTarg[e]) - int(xRef[e])), 'bo')
    plt.title('Distance between Target and Comparison X position')
    plt.savefig(infoDict['saveplot'] + 'temp/XCentroidDistance' + targetname + date + '.png')
    plt.close()

    # Y DISTANCE BETWEEN TARGET AND COMP
    plt.figure()
    plt.xlabel('Time (JD-' + str(np.nanmin(times)) + ')')
    plt.ylabel('Y Pixel Difference')
    d = 0
    for d in range(0, len(yTarg)):
        plt.plot(times[d] - np.nanmin(times), abs(int(yTarg[d]) - int(yRef[d])), 'bo')
    plt.title('Difference between Target and Comparison Y position')
    plt.savefig(infoDict['saveplot'] + 'temp/YCentroidDistance' + targetname + date + '.png')
    plt.close()


# -----CONTEXT FREE GLOBAL VARIABLES-----------------------------
def contextupdt(times=None, airm=None):
    global context

    if times is not None:
        context['times'] = times
    if airm is not None:
        context['airmass'] = airm


# -- LIGHT CURVE MODEL -- ----------------------------------------------------------------
def lcmodel(midTran, radi, am1, am2, theTimes, theAirmasses, plots=False):
    sep, ophase = time2z(theTimes, pDict['inc'], midTran, pDict['aRs'], pDict['pPer'], pDict['ecc'])
    model, junk = occultquad(abs(sep), linearLimb, quadLimb, radi)

    airmassModel = (am1 * (np.exp(am2 * theAirmasses)))
    fittedModel = model * airmassModel
    if plots:
        plt.figure()
        plt.plot(ophase, fittedModel, '-o')
        plt.xlabel('Orbital Phase')
        plt.show()
        pass
    return fittedModel


def realTimeReduce(i):
    targetFluxVals = []
    referenceFluxVals = []
    normalizedFluxVals = []
    fileNameList = []
    timeSortedNames = []
    timeList = []
    timesListed = []

    # -------TIME SORT THE FILES--------------------------------------------------------------------------------
    directoryP = ""
    directToWatch = str(input("Enter the Directory Path where .FITS or .FTS Image Files are located: "))
    # Add / to end of directory if user does not input it
    if directToWatch[-1] != "/":
        directToWatch += "/"
    directoryP = directToWatch

    while len(g.glob(directoryP)) == 0:
        print("Error: .FITS files not found in " + directoryP)
        directToWatch = str(input("Enter the Directory Path where .FITS or .FTS Image Files are located: "))
        # Add / to end of directory if user does not input it
        if directToWatch[-1] != "/":
            directToWatch += "/"
        directoryP = directToWatch

    fileNumber = 1
    for fileName in g.glob(directoryP):  # Loop through all the fits files and time sorts
        fitsHead = fits.open(name=fileName, memmap=False, cache=False, lazy_load_hdus=False)  # opens the file
        # TIME
        timeVal = getJulianTime(fitsHead)  # gets the julian time registered in the fits header
        timeList.append(timeVal)  # adds to time value list
        fileNameList.append(fileName)
        fitsHead.close()  # close stream
        del fitsHead

    # Time sorts the file names based on the fits file header
    timeSortedNames = [x for _, x in sorted(zip(timeList, fileNameList))]

    # sorts the times for later plotting use
    sortedTimeList = sorted(timeList)

    # hdul = fits.open(name=timeSortedNames[0], memmap=False, cache=False, lazy_load_hdus=False)  # opens the fits file
    # Extracts data from the image file and puts it in a 2D numpy array: firstImageData
    firstImageData = fits.getdata(timeSortedNames[0], ext=0)

    # fit first image
    targx, targy, targamplitude, targsigX, targsigY, targrot, targoff = fit_centroid(firstImageData, [UIprevTPX, UIprevTPY], box=10)
    refx, refy, refamplitude, refsigX, refsigY, refrot, refoff = fit_centroid(firstImageData, [UIprevRPX, UIprevRPY], box=10)

    # just use one aperture and annulus
    apertureR = 3 * max(targsigX, targsigY)
    annulusR = 10

    for imageFile in timeSortedNames:

        hdul = fits.open(name=imageFile, memmap=False, cache=False, lazy_load_hdus=False)  # opens the fits file
        # Extracts data from the image file and puts it in a 2D numpy array: imageData
        currTime = getJulianTime(hdul)
        imageData = hdul['ext', 0].data  # fits.getdata(imageFile, ext=0)
        header = hdul[0].header  # fits.getheader(imageFile)

        hdul.close()  # close the stream
        del hdul

        # Find the target star in the image and get its pixel coordinates if it is the first file
        if fileNumber == 1:
            # Initializing the star location guess as the user inputted pixel coordinates
            prevTPX, prevTPY, prevRPX, prevRPY = UIprevTPX, UIprevTPY, UIprevRPX, UIprevRPY
            prevTSigX, prevTSigY, prevRSigX, prevRSigY = targsigX, targsigY, refsigX, refsigY

            prevImageData = imageData  # no shift should be registered

        # ---FLUX CALCULATION WITH BACKGROUND SUBTRACTION---------------------------------

        # corrects for any image shifts that result from a tracking slip
        shift, error, diffphase = phase_cross_correlation(prevImageData, imageData)
        xShift = shift[1]
        yShift = shift[0]

        prevTPX = prevTPX - xShift
        prevTPY = prevTPY - yShift
        prevRPX = prevRPX - xShift
        prevRPY = prevRPY - yShift

        # --------GAUSSIAN FIT AND CENTROIDING----------------------------------------------

        txmin = int(prevTPX) - distFC  # left
        txmax = int(prevTPX) + distFC  # right
        tymin = int(prevTPY) - distFC  # top
        tymax = int(prevTPY) + distFC  # bottom

        targSearchA = imageData[tymin:tymax, txmin:txmax]

        # Set reference search area
        rxmin = int(prevRPX) - distFC  # left
        rxmax = int(prevRPX) + distFC  # right
        rymin = int(prevRPY) - distFC  # top
        rymax = int(prevRPY) + distFC  # bottom

        refSearchA = imageData[rymin:rymax, rxmin:rxmax]

        # Guess at Gaussian Parameters and feed them in to help gaussian fitter

        tGuessAmp = targSearchA.max() - targSearchA.min()

        # Fits Centroid for Target
        myPriors = [tGuessAmp, prevTSigX, prevTSigY, 0, targSearchA.min()]
        tx, ty, tamplitude, tsigX, tsigY, trot, toff = fit_centroid(imageData, [prevTPX, prevTPY], init=myPriors, box=10)
        currTPX = tx
        currTPY = ty

        # Fits Centroid for Reference
        rGuessAmp = refSearchA.max() - refSearchA.min()
        myRefPriors = [rGuessAmp, prevRSigX, prevRSigY, 0, refSearchA.min()]
        rx, ry, ramplitude, rsigX, rsigY, rrot, roff = fit_centroid(imageData, [prevRPX, prevRPY], init=myRefPriors, box=10)
        currRPX = rx
        currRPY = ry

        # gets the flux value of the target star and
        tFluxVal, tTotCts = getFlux(imageData, currTPX, currTPY, apertureR, annulusR)
        targetFluxVals.append(tFluxVal)  # adds tFluxVal to the total list of flux values of target star

        # gets the flux value of the reference star and subracts the background light
        rFluxVal, rTotCts = getFlux(imageData, currRPX, currRPY, apertureR, annulusR)
        referenceFluxVals.append(rFluxVal)  # adds rFluxVal to the total list of flux values of reference star

        normalizedFluxVals.append((tFluxVal / rFluxVal))

        # TIME
        timesListed.append(currTime)

        # UPDATE PIXEL COORDINATES and SIGMAS
        # target
        prevTPX = currTPX
        prevTPY = currTPY
        prevTSigX = tsigX
        prevTSigY = tsigY
        # reference
        prevRPX = currRPX
        prevRPY = currRPY
        prevRSigX = rsigX
        prevTSigY = rsigY

        # UPDATE FILE COUNT
        prevImageData = imageData
        fileNumber = fileNumber + 1

    # EXIT THE FILE LOOP

    ax1.clear()
    ax1.set_title(targetName)
    ax1.set_ylabel('Normalized Flux')
    ax1.set_xlabel('Time (jd)')
    ax1.plot(timesListed, normalizedFluxVals, 'bo')


def parse_args():
    # TODO
    parser = argparse.ArgumentParser()

    help_ = "Choose a target to process"
    parser.add_argument("-t", "--target", help=help_, type=str, default="all")

    return parser.parse_args()


if __name__ == "__main__":
    # TODO use text based interface if no command line arguments

    print('\n')
    print('*************************************************************')
    print('Welcome to the EXOplanet Transit Interpretation Code (EXOTIC)')
    print("Version ", versionid)
    print('*************************************************************\n')

    # ---INITIALIZATION-------------------------------------------------------
    targetFluxVals, referenceFluxVals, normalizedFluxVals, targUncertanties, refUncertanties, timeList, phasesList, airMassList = (
        [] for l in range(8))

    fileNameList, timeSortedNames, xTargCent, yTargCent, xRefCent, yRefCent, finXTargCent, finYTargCent, finXRefCent, finYRefCent = (
        [] for m in range(10))

    timesListed = []  # sorted times of observation
    fileNumber = 1  # initializes file number to one
    minSTD = 100000  # sets the initial minimum standard deviation absurdly high so it can be replaced immediately
    minChi2 = 100000
    distFC = 10  # gaussian search area
    context = {}

    # ---USER INPUTS--------------------------------------------------------------------------

    realTimeAns = user_input('Enter "1" for Real Time Reduction or "2" for for Complete Reduction: ', type_=int, val1=1, val2=2)

    #############################
    # Real Time Reduction Routine
    #############################

    if realTimeAns == 1:
        print('\n**************************************************************')
        print('Real Time Reduction ("Control + C"  or close the plot to quit)')
        print('**************************************************************\n')

        directToWatch = str(input("Enter the Directory Path of imaging files: "))
        directoryP = ""
        directoryP = directToWatch
        directToWatch, inputfiles = check_file_extensions(directToWatch, 'imaging')

        targetName = str(input("Enter the Planet Name: "))

        while True:
            try:
                carryOn = input('Type continue after the first image has been taken and saved: ')
                if carryOn != 'continue':
                    raise ValueError
                break
            except ValueError:
                continue

        UIprevTPX = user_input(targetName + " X Pixel Coordinate: ", type_=int)
        UIprevTPY = user_input(targetName + " Y Pixel Coordinate: ", type_=int)
        UIprevRPX = user_input("Comp Star X Pixel Coordinate: ", type_=int)
        UIprevRPY = user_input("Comp Star Y Pixel Coordinate: ", type_=int)

        print('Real Time Plotting ("Control + C" or close the plot to quit)')
        print('\nPlease be patient. It will take at least 15 seconds for the first image to get plotted.')

        fig = plt.figure()
        ax1 = fig.add_subplot(1, 1, 1)
        ax1.set_title(targetName)
        ax1.set_ylabel('Normalized Flux')
        ax1.set_xlabel('Time (jd)')

        anim = FuncAnimation(fig, realTimeReduce, interval=15000)  # refresh every 15 seconds
        plt.show()

    ###########################
    # Complete Reduction Routine
    ###########################

    # ----USER INPUTS----------------------------------------------------------
    else:
        print('\n**************************')
        print('Complete Reduction Routine')
        print('**************************\n')

        directoryP = ""
        compStarList = []

        infoDict = {'fitsdir': None, 'saveplot': None, 'flatsdir': None, 'darksdir': None, 'biasesdir': None,
                    'aavsonum': None, 'secondobs': None, 'date': None, 'lat': None, 'long': None,'elev': None,
                    'ctype': None, 'pixelbin': None, 'exposure': None, 'filter': None, 'notes': None,
                    'tarcoords': None, 'compstars': None}

        userpDict = {'ra': None, 'dec': None, 'pName': None, 'sName': None, 'pPer': None, 'pPerUnc': None,
                     'midT': None, 'midTUnc': None, 'rprs': None, 'aRs': None, 'inc': None, 'ecc': None, 'teff': None,
                     'teffUncPos': None, 'teffUncNeg': None, 'met': None, 'metUncPos': None, 'metUncNeg': None,
                     'logg': None, 'loggUncPos': None, 'loggUncNeg': None}

        fitsortext = user_input('Enter "1" to perform aperture photometry on fits files or "2" to start '
                                'with pre-reduced data in a .txt format: ', type_=int, val1=1, val2=2)

        fileorcommandline = user_input('How would you like to input your initial parameters? '
                                       'Enter "1" to use the Command Line or "2" to use an input file: ', type_=int, val1=1, val2=2)

        # Read in input file rather than using the command line
        if fileorcommandline == 2:
            print("\nYour current working directory is: ", os.getcwd())
            print("\nPotential initialization files I've found in " + os.getcwd() + " are: ")
            [print(i) for i in g.glob(os.getcwd() + "/*.json")]

            # Parse input file
            while True:
                try:
                    initfilename = str(input("\nPlease enter the Directory and Filename of your Initialization File: "))
                    if initfilename == 'ok':
                        initfilename = "/Users/rzellem/Documents/EXOTIC/inits.json"
                    break
                except FileNotFoundError:
                    print("Error: Initialization file not found. Please try again.")
                except IsADirectoryError:
                    print('Error: Entered a directory. Please try again.')

            # inits = []
            # for line in initf:
            #     if line[0] == "#": continue
            #     inits.append(line)
            # initf.close()

            infoDict, userpDict = inits_file(initfilename, infoDict, userpDict)

            if infoDict['flatsdir'] == "n":
                flats = 'n'
                flatsBool = False
            else:
                flats = 'y'
                flatsBool = True

            if infoDict['darksdir'] == "n":
                darks = 'n'
                darksBool = False
            else:
                darks = 'y'
                darksBool = True

            if infoDict['biasesdir'] == "n":
                biases = 'n'
                biasesBool = False
            else:
                biases = 'y'
                biasesBool = True

            if flatsBool + darksBool + biasesBool:
                cals = 'y'
            else:
                cals = 'n'

            # Initial position of target star
            UIprevTPX = infoDict['tarcoords'][0]
            UIprevTPY = infoDict['tarcoords'][1]

            # Read in locations of comp stars
            for i in infoDict['compstars']:
                compStarList.append((i[0], i[1]))

        if fitsortext == 1:
            # File directory name and initial guess at target and comp star locations on image.
            if fileorcommandline == 1:
                infoDict['fitsdir'] = str(input("\nEnter the Directory of imaging files: "))

            infoDict['fitsdir'], inputfiles = check_file_extensions(infoDict['fitsdir'], 'imaging')
        else:
            datafile = str(input("Enter the path and filename of your data file: "))
            if datafile == 'ok':
                datafile = "/Users/rzellem/Documents/EXOTIC/sample-data/NormalizedFluxHAT-P-32 bDecember 17, 2017.txt"
                # datafile = "/Users/rzellem/Downloads/fluxorama.csv"

            try:
                initf = open(datafile, 'r')
            except FileNotFoundError:
                print("Data file not found. Please try again.")
                sys.exit()

            processeddata = initf.readlines()

        if fileorcommandline == 1:
            infoDict['saveplot'] = str(input("Enter the Directory to Save Plots into or type new to create one: "))

        # Check to see if the save directory exists
        while True:
            try:
                if infoDict['saveplot'] == 'new':
                    infoDict['saveplot'] = create_directory()
                    break
                # In case the user forgets the trailing / for the folder
                if infoDict['saveplot'][-1] != "/":
                    infoDict['saveplot'] += "/"
                if os.path.isdir(infoDict['saveplot']):
                    break
                raise OSError
            except OSError:
                print('Error: the directory entered does not exist. Please try again.')
                infoDict['saveplot'] = input("Enter the Directory to Save Plots into or type new to create one: ")

        # Make a temp directory of helpful files
        try:
            os.makedirs(infoDict['saveplot'] + "temp/")
        except FileExistsError:
            # directory already exists
            pass

        if fileorcommandline == 1:
            userpDict['pName'] = str(input("\nEnter the Planet Name: "))

        print("\nLooking up ", userpDict['pName'], "- please wait.")
        done = False
        t = threading.Thread(target=animate, daemon=True)
        t.start()
        # check to make sure the target can be found in the exoplanet archive right after they enter its name

        # Checks to see if the file exists or is over one week old to scrape/rescrape parameters (units in seconds)
        if not os.path.exists("eaConf.json") or time.time() - os.path.getmtime('eaConf.json') > 604800:
            new_scrape(filename="eaConf.json")
        targetName = userpDict['pName']

        CandidatePlanetBool = False
        with open("eaConf.json", "r") as confirmedFile:
            data = json.load(confirmedFile)
            planets = [data[i]['pl_name'].lower().replace(' ', '').replace('-', '') for i in range(len(data))]
            #stars = [data[i]['hostname'] for i in range(len(data))]
            if targetName.lower().replace(' ', '').replace('-', '') not in planets:
                while targetName.lower().replace(' ', '').replace('-', '') not in planets:
                    done = True
                    print("\nCannot find " + userpDict['pName'] + " in the NASA Exoplanet Archive. Check spelling or file: eaConf.json.")
                    targetName = input("If this is a planet candidate, type candidate or re-enter the planet's name: ")
                    if targetName.replace(' ', '') == 'candidate':
                        CandidatePlanetBool = True
                        break
            if not CandidatePlanetBool:
                idx = planets.index(targetName.lower().replace(' ', '').replace('-', ''))
                pDict = new_getParams(data[idx])
                print('\nSuccessfuly found ' + targetName + ' in the NASA Exoplanet Archive!')

        if targetName.replace(' ','') != 'candidate' and targetName.replace(' ', '') != userpDict['pName']:
            userpDict['pName'] = targetName

        done = True

        # observation date
        if fileorcommandline == 1:
            infoDict['date'] = str(input("\nEnter the Observation Date: "))

        # Using a / in your date can screw up the file paths- this will check user's date
        while "/" in infoDict['date']:
            print("Do not use / in your date. Please try again.")
            infoDict['date'] = str(input("\nEnter the Observation Date: "))

        if fitsortext == 1:
            if fileorcommandline == 1:
                infoDict['lat'] = input("Enter the latitude of where you observed (deg) "
                                        "(Don't forget the sign where North is '+' and South is '-'): ")
            # Latitude
            while True:
                try:
                    infoDict['lat'] = infoDict['lat'].replace(' ', '')
                    if infoDict['lat'][0] != '+' and infoDict['lat'][0] != '-':
                        raise ValueError("You forgot the sign for the latitude! North is '+' and South is '-'. Please try again.")
                    lati = float(infoDict['lat'])
                    if lati <= -90.00 or lati >= 90.00:
                        raise ValueError('Your latitude is out of range. Please enter a latitude between -90 and +90 (deg)')
                    break
                # check to make sure they have a sign
                except ValueError as err:
                    print(err.args)
                    infoDict['lat'] = input("Enter the latitude of where you observed (deg) "
                                            "(Don't forget the sign where North is '+' and South is '-'): ")

            if fileorcommandline == 1:
                infoDict['long'] = input("Enter the longitude of where you observed (deg) "
                                         "(Don't forget the sign where East is '+' and West is '-'): ")
            # Longitude
            while True:
                try:
                    infoDict['long'] = infoDict['long'].replace(' ', '')
                    if infoDict['long'][0] != '+' and infoDict['long'][0] != '-':
                        raise ValueError("You forgot the sign for the longitude! East is '+' and West is '-'. Please try again.")
                    longit = float(infoDict['long'])
                    if longit <= -180.00 or longit >= 180.00:
                        raise ValueError('Your longitude is out of range. Please enter a longitude between -180 and +180 (deg)')
                    break
                # check to make sure they have a sign
                except ValueError as err:
                    print(err.args)
                    infoDict['long'] = input("Enter the longitude of where you observed (deg) "
                                             "(Don't forget the sign where East is '+' and West is '-'): ")

            if fileorcommandline == 1:
                infoDict['elev'] = user_input("Enter the elevation (in meters) of where you observed: ", type_=float)

            # TARGET STAR
            if fileorcommandline == 1:
                UIprevTPX = user_input('\n' + userpDict['pName'] + " X Pixel Coordinate: ", type_=int)
                UIprevTPY = user_input(userpDict['pName'] + " Y Pixel Coordinate: ", type_=int)
                numCompStars = user_input("How many comparison stars would you like to use? (1-10) ", type_=int)

                for num in range(numCompStars):
                    xpix = user_input("Comparison Star %s X Pixel Coordinate: " % str(num+1), type_=int)
                    ypix = user_input("Comparison Star %s Y Pixel Coordinate: " % str(num+1), type_=int)
                    compStarList.append((xpix, ypix))

            # ---HANDLE CALIBRATION IMAGES------------------------------------------------
            if fileorcommandline == 1:
                cals = user_input('\nDo you have any calibration images (flats, darks or biases)? (y/n): ', type_=str, val1='y', val2='n')

            # if they have cals, handle them by calculating the median flat, dark or bias
            if cals == 'y':

                # flats
                # THIS DOES NOT ACCOUNT FOR CALIBRATING THE FLATS, WHICH COULD BE TAKEN AT A DIFFERENT EXPOSURE TIME
                if fileorcommandline == 1:
                    flats = user_input('\nDo you have flats? (y/n): ', type_=str, val1='y', val2='n')
                    if flats == 'y':
                        flatsBool = True
                        infoDict['flatsdir'] = str(input('Enter the directory path to your flats (must be in their own separate folder): '))  # +"/*.FITS"
                    else:
                        flatsBool = False

                    if flatsBool:
                        infoDict['flatsdir'], inputflats = check_file_extensions(infoDict['flatsdir'], 'flats')
                        flatsImgList = []
                        for flatFile in inputflats:
                            flatData = fits.getdata(flatFile, ext=0)
                            flatsImgList.append(flatData)
                        notNormFlat = np.median(flatsImgList, axis=0)

                        # NORMALIZE
                        medi = np.median(notNormFlat)
                        generalFlat = notNormFlat / medi
                else:
                    flatsBool = False

                # darks
                if fileorcommandline == 1:
                    darks = user_input('\nDo you have darks? (y/n): ', type_=str, val1='y', val2='n')
                    if darks == 'y':
                        darksBool = True
                        infoDict['darksdir'] = str(input('Enter the directory path to your darks (must be in their own separate folder): '))  # +"/*.FITS"
                    else:
                        darksBool = False

                # Only do the dark correction if user selects this option
                if darksBool:
                    infoDict['darksdir'], inputdarks = check_file_extensions(infoDict['darksdir'], 'darks')
                    darksImgList = []
                    for darkFile in inputdarks:
                        darkData = fits.getdata(darkFile, ext=0)
                        darksImgList.append(darkData)
                    generalDark = np.median(darksImgList, axis=0)

                # biases
                if fileorcommandline == 1:
                    biases = user_input('\nDo you have biases? (y/n): ', type_=str, val1='y', val2='n')
                    if biases == 'y':
                        biasesBool = True
                        infoDict['biasesdir'] = str(input('Enter the directory path to your biases (must be in their own separate folder): '))  # +"/*.FITS"
                    else:
                        biasesBool = False

                if biasesBool:
                    # Add / to end of directory if user does not input it
                    infoDict['biasesdir'], inputbiases = check_file_extensions(infoDict['biasesdir'], 'biases')
                    biasesImgList = []
                    for biasFile in inputbiases:
                        biasData = fits.getdata(biasFile, ext=0)
                        biasesImgList.append(biasData)
                    generalBias = np.median(biasesImgList, axis=0)
            else:
                flatsBool = False
                darksBool = False
                biasesBool = False

        print("\n***************************************")
        print("Plotting Options")
        binplotBool = True
        # binplot = str(input("Would you like to overplot a binned version of your data for plotting purposes? (y/n; select y if you have a lot of data.) "))
        # if binplot == 'y' or binplot == 'yes' or binplot == 'Y' or binplot == 'Yes':
        #     binplotBool = True
        # else:
        #     binplotBool = False

        # Handle AAVSO Formatting
        if fileorcommandline == 1:
            # userNameEmails = str(input('Please enter your name(s) and email address(es) in the format: Your Name (youremail@example.com), Next Name (nextemail@example.com), etc.  '))
            infoDict['aavsonum'] = str(input('Please enter your AAVSO Observer Account Number (type N/A if you do not currently have an account): '))
            infoDict['secondobs'] = str(input('Please enter your comma-separated secondary observer codes (or type N/A if only 1 observer code): '))
            infoDict['ctype'] = str(input("Please enter your camera type (CCD or DSLR): "))
            infoDict['pixelbin'] = str(input('Please enter your pixel binning: '))
            infoDict['exposure'] = user_input('Please enter your exposure time (seconds): ', type_=int)
            infoDict['filter'] = str(input('Please enter your filter name from the options at '
                                           'http://astroutils.astronomy.ohio-state.edu/exofast/limbdark.shtml: '))
            infoDict['notes'] = str(input('Please enter any observing notes (seeing, weather, etc.): '))

        # Get the planetary parameters non-candidate exoplanets
        if not CandidatePlanetBool:
            pDict = get_planetary_parameters(CandidatePlanetBool, userpDict, pdict=pDict)
        # Candidate planetary parameters for exoplanets
        else:
            pDict = get_planetary_parameters(CandidatePlanetBool, userpDict)

        print('\n***************************')
        print('Limb Darkening Coefficients')
        print('***************************')

        # curl exofast for the limb darkening terms based on effective temperature, metallicity, surface gravity
        URL = 'http://astroutils.astronomy.ohio-state.edu/exofast/limbdark.shtml'
        URLphp = 'http://astroutils.astronomy.ohio-state.edu/exofast/quadld.php'

        with requests.Session() as sesh:
            while True:
                try:
                    form_newData = {"action": URLphp,
                                    "teff": str(pDict['teff']),
                                    "feh": str(pDict['met']),
                                    "logg": str(pDict['logg']),
                                    "bname": infoDict['filter'],
                                    "pname": "Select Planet"
                                    }
                    r = sesh.post(URLphp, data=form_newData)
                    fullcontents = r.text

                    # linear term
                    linearString = ''
                    for indexLinear in range(len(fullcontents)):
                        if fullcontents[indexLinear].isdigit():
                            while fullcontents[indexLinear + 1] != ' ':
                                linearString = linearString + fullcontents[indexLinear]
                                indexLinear = indexLinear + 1
                            # print (linearString)
                            linearLimb = float(linearString)
                            break

                    # quadratic term
                    quadString = ''
                    for indexQuad in range(indexLinear + 1, len(fullcontents)):
                        if fullcontents[indexQuad].isdigit() or fullcontents[indexQuad] == '.':
                            quadString = quadString + fullcontents[indexQuad]
                            indexQuad = indexQuad + 1
                    # print (quadString)
                    quadLimb = float(quadString)
                    break
                except ValueError:
                    infoDict['filter'] = input('\nNot valid filter name. Please enter a valid filter name using '
                                               'http://astroutils.astronomy.ohio-state.edu/exofast/limbdark.shtml: ')

        print('\nBased on the stellar parameters you just entered, the limb darkening coefficients are: ')
        print('Linear Term: ' + linearString)
        print('Quadratic Term: ' + quadString)

        if fitsortext == 1:
            print('\n**************************')
            print('Starting Reduction Process')
            print('**************************')

            #########################################
            # FLUX DATA EXTRACTION AND MANIPULATION
            #########################################

            # Loop placed to check user-entered x and y target coordinates against WCS.
            while True:
                fileNumber = 1
                allImageData, timeList, fileNameList, timesListed, airMassList, fileNameStr = [], [], [], [], [], []

                # ----TIME SORT THE FILES-------------------------------------------------------------
                for fileName in inputfiles:  # Loop through all the fits files in the directory and executes data reduction

                    # fitsHead = fits.open(name=fileName, memmap=False, cache=False, lazy_load_hdus=False)  # opens the file

                    # FOR 61'' DATA ONLY: ONLY REDUCE DATA FROM B FILTER
                    # if fitsHead[0].header ['FILTER']== 'Harris-B':
                    #     #TIME
                    #     timeVal = getJulianTime(fitsHead) #gets the julian time registered in the fits header
                    #     timeList.append(timeVal) #adds to time value list
                    #     fileNameList.append (fileName)
                    # fitsHead.close()  # close stream
                    # del fitsHead

                    # Keeps a list of file names
                    fileNameStr.append(fileName)

                    hdul = fits.open(name=fileName, memmap=False, cache=False, lazy_load_hdus=False)  # opens the fits file
                    imageheader = hdul[0].header
                    # TIME
                    timeVal = getJulianTime(hdul)  # gets the julian time registered in the fits header
                    timeList.append(timeVal)  # adds to time value list
                    fileNameList.append(fileName)

                    # TIME
                    currTime = getJulianTime(hdul)
                    timesListed.append(currTime)

                    # AIRMASS
                    airMass = getAirMass(hdul, pDict['ra'], pDict['dec'], lati, longit, infoDict['elev'])  # gets the airmass at the time the image was taken
                    airMassList.append(airMass)  # adds that airmass value to the list of airmasses

                    # IMAGES
                    allImageData.append(hdul[0].data)

                    hdul.close()  # closes the file to avoid using up all of computer's resources
                    del hdul

                # Recast list as numpy arrays
                allImageData = np.array(allImageData)
                timesListed = np.array(timesListed)
                airMassList = np.array(airMassList)

                # TODO: Is this dead code? The vars pointing and location are undefined.
                # TODO: comment out conditional block?
                # If all of the airmasses == 1, then you need to calculate the airmass for the user
                if set(airMassList) == 1:
                    pointingAltAz = pointing.transform_to(AltAz(obstime=t, location=location))

                # # Time sorts the file names based on the fits file header
                # timeSortedNames = [x for _, x in sorted(zip(timeList, fileNameList))]
                # tsnCopy = timeSortedNames

                # sorts the times for later plotting use
                sortedallImageData = allImageData[np.argsort(timeList)]
                timesListed = timesListed[np.argsort(timeList)]
                airMassList = airMassList[np.argsort(timeList)]
                sortedTimeList = sorted(timeList)

                # print("\nEXOTIC now has the option to filter the raw images for cosmic rays. Typically, images do not need this filter. However, if you run into an error while running EXOTIC, give this a try. As a heads up, this can take a few minutes.")
                # cosmicrayfilter = user_input("\nDo you want to filter the raw images for cosmic rays? (y/n): ")
                # if cosmicrayfilter.lower() == "yes" or cosmicrayfilter.lower() == "y":
                #     cosmicrayfilter_bool = True
                # else:
                #     cosmicrayfilter_bool = False

                # The cosmic ray filter isn't really working for now...so let's just turn it off
                cosmicrayfilter_bool = False
                if cosmicrayfilter_bool:
                    print("\nFiltering your data for cosmic rays.")
                    done = False
                    t = threading.Thread(target=animate, daemon=True)
                    t.start()
                    # # -------COSMIC RAY FILTERING-----------------------------------------------------------------------
                    # For now, this is a simple median filter...in the future, should use something more smart later
                    for xi in np.arange(np.shape(sortedallImageData)[-2]):
                        # print("Filtering for cosmic rays in image row: "+str(xi)+"/"+str(np.shape(sortedallImageData)[-2]))
                        for yi in np.arange(np.shape(sortedallImageData)[-1]):
                            # Simple median filter
                            idx = np.abs(sortedallImageData[:, xi, yi]-np.nanmedian(sortedallImageData[:, xi, yi])) > 5*np.nanstd(sortedallImageData[:, xi, yi])
                            sortedallImageData[idx, xi, yi] = np.nanmedian(sortedallImageData[:, xi, yi])
                            # Filter iteratively until no more 5sigma outliers exist - not currently working, so keep commented out for now
                            # while sum(idx) > 0:
                            #     # sortedallImageData[idx,xi,yi] = np.nanmedian(sortedallImageData[:,xi,yi])
                            #     idx = np.abs(sortedallImageData[:,xi,yi]-np.nanmedian(sortedallImageData[:,xi,yi])) >  5*np.nanstd(sortedallImageData[:,xi,yi])
                    done = True

                # if len(sortedTimeList) == 0:
                #     print("Error: .FITS files not found in " + directoryP)
                #     sys.exit()

                # -------OPTIMAL COMP STAR, APERTURE, AND ANNULUS CALCULATION----------------------------------------

                # Loops through all of the possible aperture and annulus radius
                # guess at optimal aperture by doing a gaussian fit and going out 3 sigma as an estimate

                # hdul = fits.open(name=timeSortedNames[0], memmap=False, cache=False, lazy_load_hdus=False)  # opens the fits file
                # firstImageData = hdul['ext', 0].data  # fits.getdata(timeSortedNames[0], ext=0)
                firstimagecounter = 0
                firstImageData = sortedallImageData[firstimagecounter]

                # Sometimes the first image is a bad one...in that case, we iterate until we do not fail
                while True:
                    # fit Target in the first image and use it to determine aperture and annulus range
                    try:
                        targx, targy, targamplitude, targsigX, targsigY, targrot, targoff = fit_centroid(firstImageData, [UIprevTPX, UIprevTPY],
                                                                                                box=10)
                        break
                    # If the first image is a bad one, then move on to the next image
                    except Exception:
                        firstimagecounter += 1
                        firstImageData = sortedallImageData[firstimagecounter]

                # Filter the other data as well
                sortedallImageData = sortedallImageData[firstimagecounter:]
                timesListed = timesListed[firstimagecounter:]
                airMassList = airMassList[firstimagecounter:]
                sortedTimeList = sortedTimeList[firstimagecounter:]

                # apply cals correction if applicable
                if darksBool:
                    print("Dark subtracting images.")
                    sortedallImageData = sortedallImageData - generalDark
                elif biasesBool:
                    print("Bias-correcting images.")
                    sortedallImageData = sortedallImageData - generalBias
                else:
                    pass

                if flatsBool:
                    print("Flattening images.")
                    sortedallImageData = sortedallImageData / generalFlat

                # Plate Solution
                pathSolve = infoDict['saveplot'] + 'ref_file_%s_%s' % (str(firstimagecounter), fileNameStr[firstimagecounter].split('/')[-1])

                # Removes existing file of first_fits.fits
                try:
                    os.remove(pathSolve)
                except OSError:
                    pass
                convertToFITS = fits.PrimaryHDU(data=sortedallImageData[0])
                convertToFITS.writeto(pathSolve)
                wcsFile = check_wcs(pathSolve, infoDict['saveplot'])

                # Check pixel coordinates by converting to WCS. If not correct, loop over again
                if wcsFile:
                    print('Here is the path to your plate solution: ' + wcsFile)
                    hdulWCS = fits.open(name=wcsFile, memmap=False, cache=False, lazy_load_hdus=False)  # opens the fits file
                    rafile, decfile = get_radec(hdulWCS)

                    # Save previously entered x and y pixel coordinates before checking against plate solution
                    saveUIprevTPX, saveUIprevTPY = UIprevTPX, UIprevTPY
                    UIprevTPX, UIprevTPY = check_targetpixelwcs(UIprevTPX, UIprevTPY, pDict['ra'],
                                                                pDict['dec'], rafile, decfile)
                    # If the coordinates were not changed, do not loop over again
                    if UIprevTPX == saveUIprevTPX and UIprevTPY == saveUIprevTPY:
                        break
                else:
                    break

            # Image Alignment
            print("\nAligning your images from FITS files. Please wait.")
            done = False
            t = threading.Thread(target=animate, daemon=True)
            t.start()
            sortedallImageData, unalignedBoolList, boollist = image_alignment(sortedallImageData)
            done = True
            print('\n\nImages Aligned.')

            minAperture = int(2 * max(targsigX, targsigY))
            maxAperture = int(5 * max(targsigX, targsigY) + 1)
            minAnnulus = 2
            maxAnnulus = 5
            # exit()
            # fit centroids for first image to determine priors to be used later
            for compCounter in range(0, len(compStarList)):
                print('\n***************************************************************')
                print('Determining Optimal Aperture and Annulus Size for Comp Star #' + str(compCounter + 1))
                print('***************************************************************')

                # #just in case comp star drifted off and timeSortedNames had to be altered, reset it for the new comp star
                # timeSortedNames = tsnCopy

                UIprevRPX, UIprevRPY = compStarList[compCounter]

                print('Target X: ' + str(round(targx)) + ' Target Y: ' + str(round(targy)))
                refx, refy, refamplitude, refsigX, refsigY, retrot, refoff = fit_centroid(firstImageData, [UIprevRPX, UIprevRPY],
                                                                                box=10)
                print('Comparison X: ' + str(round(refx)) + ' Comparison Y: ' + str(round(refy)) + '\n')

                # determines the aperture and annulus combinations to iterate through based on the sigmas of the LM fit
                aperture_min = int(3 * np.nanmax([targsigX, targsigY]))
                aperture_max = int(5 * np.nanmax([targsigX, targsigY]))
                annulus_min = int(2 * np.nanmax([targsigX, targsigY]))
                annulus_max = int(4 * np.nanmax([targsigX, targsigY]))

                # Run through only 5 different aperture sizes, all interger pixel values
                aperture_step = np.nanmax([1, (aperture_max + 1 - aperture_min)//5])  # forces step size to be at least 1
                aperture_sizes = np.arange(aperture_min, aperture_max + 1, aperture_step)

                # Run through only 5 different annulus sizes, all interger pixel values
                annulus_step = np.nanmax([1, (annulus_max - annulus_min)//5])  # forces step size to be at least 1
                annulus_sizes = [5] # np.arange(annulus_min, annulus_max, annulus_step) # TODO clean up for issue #40

                target_fits = {}
                ref_fits = {}
                reg_trans = {}

                for apertureR in aperture_sizes:  # aperture loop
                    for annulusR in annulus_sizes:  # annulus loop # no need
                        # fileNumber = 1
                        print('Testing Comparison Star #' + str(compCounter+1) + ' with a '+str(apertureR)+' pixel aperture and a '+str(annulusR)+' pixel annulus.')
                        for fileNumber, imageData in enumerate(sortedallImageData):

                            # hDul = fits.open(name=imageFile, memmap=False, cache=False, lazy_load_hdus=False)  # opens the fits file
                            # imageData = fits.getdata(imageFile, ext=0)  # Extracts data from the image file

                            # header = fits.getheader(imageFile)

                            # Find the target star in the image and get its pixel coordinates if it is the first file
                            if fileNumber == 0:
                                # Initializing the star location guess as the user inputted pixel coordinates
                                prevTPX, prevTPY, prevRPX, prevRPY = UIprevTPX, UIprevTPY, UIprevRPX, UIprevRPY  # 398, 275, 419, 203
                                prevTSigX, prevTSigY, prevRSigX, prevRSigY = targsigX, targsigY, refsigX, refsigY
                                prevImageData = imageData  # no shift should be registered

                            # ------ CENTROID FITTING ----------------------------------------

                            # corrects for any image shifts that result from a tracking slip
                            # shift, error, diffphase = phase_cross_correlation(prevImageData, imageData)
                            if fileNumber in reg_trans.keys():
                                shift, error, diffphase = reg_trans[fileNumber]
                            else:
                                shift, error, diffphase = phase_cross_correlation(prevImageData, imageData)
                                reg_trans[fileNumber] = [shift, error, diffphase]

                            xShift = shift[1]
                            yShift = shift[0]

                            prevTPX = prevTPX - xShift
                            prevTPY = prevTPY - yShift
                            prevRPX = prevRPX - xShift
                            prevRPY = prevRPY - yShift

                            # set target search area
                            txmin = int(prevTPX) - distFC  # left
                            txmax = int(prevTPX) + distFC  # right
                            tymin = int(prevTPY) - distFC  # top
                            tymax = int(prevTPY) + distFC  # bottom

                            # boolean that represents if either the target or comp star gets too close to the detector
                            driftBool = False

                            #check if your target star is too close to the edge of the detector
                            if txmin <= 0 or tymin <= 0 or txmax >= len(imageData) or tymax >= len(imageData[0]):
                                print('*************************************************************************************')
                                print('WARNING: In image '+str(fileNumber)+', your target star has drifted too close to the edge of the detector.')
                                #tooClose = int(input('Enter "1" to pick a new comparison star or enter "2" to continue using the same comp star, with the images with all the remaining images ignored \n'))
                                print('All the remaining images after image #'+str(fileNumber-1)+' will be ignored')
                                driftBool = True

                                # mask off the rest of timeSortedNames and then ignore the rest of the procedure until

                            # Set reference search area
                            rxmin = int(prevRPX) - distFC  # left
                            rxmax = int(prevRPX) + distFC  # right
                            rymin = int(prevRPY) - distFC  # top
                            rymax = int(prevRPY) + distFC  # bottom

                            # check if the reference is too close to the edge of the detector
                            if rxmin <= 0 or rymin <= 0 or rxmax >= len(imageData[0]) or rymax >= len(imageData):
                                print('*************************************************************************************')
                                print('WARNING: In image '+str(fileNumber)+', your reference star has drifted too close to the edge of the detector.')
                                #tooClose = int(input('Enter "1" to pick a new comparison star or enter "2" to continue using the same comp star, with the images with all the remaining images ignored \n'))
                                print('All the remaining images after image #'+str(fileNumber-1)+' will be ignored for this comparison star')
                                print('*************************************************************************************')
                                driftBool = True

                            # if the star isn't too close, then proceed as normal
                            if not driftBool:
                                targSearchA = imageData[tymin:tymax, txmin:txmax]
                                refSearchA = imageData[rymin:rymax, rxmin:rxmax]

                                targPos = [prevTPX, prevTPY]

                                # get minimum background value bigger than 0
                                targImFlat = np.sort(np.array(targSearchA).ravel())

                                # Initialize the variable
                                tGuessBkg = 0
                                for el in targImFlat:
                                    if el > 0:
                                        tGuessBkg = el
                                        break

                                refImFlat = np.sort(np.array(refSearchA).ravel())
                                for rel in refImFlat:
                                    if rel > 0:
                                        rGuessBkg = rel
                                        break

                                # Guess at Gaussian Parameters and feed them in to help gaussian fitter

                                tGuessAmp = targSearchA.max() - tGuessBkg
                                if tGuessAmp < 0:
                                    print('Error: the Darks have a higher pixel counts than the image itself')
                                myPriors = [tGuessAmp, prevTSigX, prevTSigY, 0, tGuessBkg]

                                # tx, ty, tamplitude, tsigX, tsigY, toff = fit_centroid(imageData, targPos,
                                #                                                     init=myPriors, box=distFC)
                                if fileNumber in target_fits.keys():
                                    tx, ty, tamplitude, tsigX, tsigY, toff = target_fits[fileNumber]
                                else:
                                    tx, ty, tamplitude, tsigX, tsigY, trot, toff = fit_centroid(imageData, targPos,
                                                                                          init=myPriors, box=distFC)
                                    target_fits[fileNumber] = [tx, ty, tamplitude, tsigX, tsigY, toff]

                                currTPX = tx
                                currTPY = ty

                                # append to list of target centroid positions for later plotting
                                xTargCent.append(currTPX)
                                yTargCent.append(currTPY)

                                rGuessAmp = refSearchA.max() - rGuessBkg
                                myRefPriors = [rGuessAmp, prevRSigX, prevRSigY, 0, rGuessBkg]
                                # rx, ry, ramplitude, rsigX, rsigY, roff = fit_centroid(imageData, [prevRPX, prevRPY],
                                # init=myRefPriors, box=distFC)
                                if fileNumber in ref_fits.keys():
                                    rx, ry, ramplitude, rsigX, rsigY, roff = ref_fits[fileNumber]
                                else:
                                    rx, ry, ramplitude, rsigX, rsigY, rrot, roff = fit_centroid(imageData, [prevRPX, prevRPY],
                                                                                          init=myRefPriors, box=distFC)
                                    ref_fits[fileNumber] = [rx, ry, ramplitude, rsigX, rsigY, roff]
                                currRPX = rx
                                currRPY = ry

                                # append to list of reference centroid positions for later plotting
                                xRefCent.append(currRPX)
                                yRefCent.append(currRPY)

                                if tamplitude < 0 or tsigX < 0 or tsigY < 0:  # gets rid of negative amplitude values that indicate it couldn't fit gaussian
                                    print('Could not fit 2D gaussian to Target for File Number' + str(fileNumber))

                                elif ramplitude < 0 or rsigX < 0 or rsigY < 0:  # gets rid of negative amplitude values that indicate it couldn't fit gaussian
                                    print('Could not fit 2D gaussian to Comparison Star for File Number' + str(fileNumber))

                                else:
                                    # ------FLUX CALCULATION WITH BACKGROUND SUBTRACTION----------------------------------

                                    # gets the flux value of the target star and subtracts the background light
                                    tFluxVal, tTotCts = getFlux(imageData, currTPX, currTPY, apertureR, annulusR)
                                    # FIXME centroid position is way off from user input for star

                                    targetFluxVals.append(tFluxVal)  # adds tFluxVal to the total list of flux values of target star
                                    targUncertanties.append(np.sqrt(tFluxVal))  # uncertanty on each point is the sqrt of the total counts

                                    # gets the flux value of the reference star and subracts the background light
                                    rFluxVal, rTotCts = getFlux(imageData, currRPX, currRPY, apertureR, annulusR)

                                    referenceFluxVals.append(
                                        rFluxVal)  # adds rFluxVal to the total list of flux values of reference star
                                    refUncertanties.append(np.sqrt(rFluxVal))

                                    # # TIME
                                    # currTime = getJulianTime(hDul)
                                    # timesListed.append(currTime)

                                    # ORBITAL PHASE
                                    currentPhase = getPhase(currTime, pDict['pPer'], pDict['midT'])
                                    phasesList.append(currentPhase)  # adds to list of phases

                                    # # AIRMASS
                                    # airMass = getAirMass(hDul)  # gets the airmass at the time the image was taken
                                    # airMassList.append(airMass)  # adds that airmass value to the list of airmasses

                                    # UPDATE PIXEL COORDINATES and SIGMAS
                                    # target
                                    prevTPX = currTPX
                                    prevTPY = currTPY
                                    prevTSigX = tsigX
                                    prevTSigY = tsigY
                                    # reference
                                    prevRPX = currRPX
                                    prevRPY = currRPY
                                    prevRSigX = rsigX
                                    prevTSigY = rsigY

                                # UPDATE FILE COUNT
                                prevImageData = imageData
                                # fileNumber = fileNumber + 1
                                # hDul.close()  # close the stream

                            # otherwise, mask off the rest of the files from time sorted names including the current one
                            else:
                                print("\nFiltering data to account for drifting target.")
                                # timeSortedNames = timeSortedNames[:fileNumber]

                                # TIME
                                timesListed = timesListed[:fileNumber]

                                # AIRMASS
                                airMassList = airMassList[:fileNumber]

                                # ALL IMAGES
                                sortedallImageData = sortedallImageData[:fileNumber]

                                boollist = boollist[:fileNumber]

                                break

                        # EXIT THE FILE LOOP

                        # NORMALIZE BY REF STAR
                        # Convert the raw flux values to arrays and then divide them to get the normalized flux data
                        rawFinalFluxData = np.array(targetFluxVals) / np.array(referenceFluxVals)

                        # --- 5 Sigma Clip from mean to get rid of ridiculous outliers (based on sigma of entire dataset)-----------------------------------------

                        # Convert Everything to numpy Arrays
                        arrayFinalFlux = np.array(rawFinalFluxData)  # finalFluxData
                        arrayTargets = np.array(targetFluxVals)  # finalFluxData
                        arrayTimes = np.array(timesListed)
                        arrayPhases = np.array(phasesList)
                        arrayTargets = np.array(targetFluxVals)
                        arrayReferences = np.array(referenceFluxVals)
                        arrayAirmass = np.array(airMassList)
                        arrayTUnc = np.array(targUncertanties)
                        arrayRUnc = np.array(refUncertanties)

                        # If unaligned images existed, delete .fits data w/ boollist from airmass and times.
                        if unalignedBoolList.size > 0:
                            arrayTimes = arrayTimes[boollist]
                            arrayAirmass = arrayAirmass[boollist]

                        normUncertainties = (arrayTargets / arrayReferences) * np.sqrt(
                            ((arrayTUnc / arrayTargets) ** 2.) + ((arrayRUnc / arrayReferences) ** 2.))
                        arrayNormUnc = np.array(normUncertainties)

                        # Execute sigma_clip
                        try:
                            filtered_data = sigma_clip(arrayFinalFlux, sigma=5, maxiters=1, cenfunc=np.mean, copy=False)
                        except TypeError:
                            filtered_data = sigma_clip(arrayFinalFlux, sigma=5, cenfunc=np.mean, copy=False)

                        # -----LM LIGHTCURVE FIT--------------------------------------

                        midTranCur = nearestTransitTime(timesListed, pDict['pPer'], pDict['midT'])
                        #midTranCur was in the initval first
                        initvals = [np.median(arrayTimes), pDict['rprs'], np.median(arrayFinalFlux[~filtered_data.mask]), 0]
                        up = [arrayTimes[-1], 1, np.inf, 1.0]
                        low = [arrayTimes[0], 0, -np.inf, -1.0]
                        bound = [low, up]

                        # define residual function to be minimized
                        def lc2min(x):
                            gaelMod = lcmodel(x[0], x[1], x[2], x[3], arrayTimes[~filtered_data.mask],
                                            arrayAirmass[~filtered_data.mask], plots=False)
                            # airMod= ( x[2]*(np.exp(x[3]*arrayAirmass[~filtered_data.mask])))
                            # return arrayFinalFlux[~filtered_data.mask]/airMod - gaelMod/airMod
                            return (arrayFinalFlux[~filtered_data.mask] / gaelMod) - 1.


                        res = least_squares(lc2min, x0=initvals, bounds=bound, method='trf')  # results of least squares fit

                        # Calculate the standard deviation of the residuals
                        residualVals = res.fun
                        standardDev2 = np.std(residualVals, dtype=np.float64)  # calculates standard deviation of data

                        lsFit = lcmodel(res.x[0], res.x[1], res.x[2], res.x[3], arrayTimes[~filtered_data.mask],
                                        arrayAirmass[~filtered_data.mask], plots=False)

                        # compute chi^2 from least squares fit
                        # print('Median Uncertainty Value: '+ str(round(np.median(arrayNormUnc),5)))
                        chi2_init = np.sum(((arrayFinalFlux[~filtered_data.mask] - lsFit) / arrayNormUnc[~filtered_data.mask]) ** 2.) / (
                                len(arrayFinalFlux[~filtered_data.mask]) - len(res.x))
                        # print("Non-Reduced chi2: ",np.sum(((arrayFinalFlux[~filtered_data.mask]-lsFit)/arrayNormUnc)**2.))

                        # chi2 = np.sum(((arrayFinalFlux[~filtered_data.mask]-lsFit)/arrayNormUnc)**2.)/(len(arrayFinalFlux[~filtered_data.mask])-len(res.x)-1)

                        print('The Residual Standard Deviation is: ' + str(round(standardDev2, 6)))
                        print('The Reduced Chi-Squared is: ' + str(round(chi2_init, 6)) + '\n')
                        if minSTD > standardDev2:  # If the standard deviation is less than the previous min
                            bestCompStar = compCounter + 1
                            minSTD = standardDev2  # set the minimum standard deviation to that

                            arrayNormUnc = arrayNormUnc * np.sqrt(chi2_init)  # scale errorbars by sqrt(chi2) so that chi2 == 1
                            minAnnulus = annulusR  # then set min aperature and annulus to those values
                            minAperture = apertureR
                            # gets the centroid trace plots to ensure tracking is working
                            finXTargCentArray = np.array(xTargCent)
                            finYTargCentArray = np.array(yTargCent)
                            finXRefCentArray = np.array(xRefCent)
                            finYRefCentArray = np.array(yRefCent)

                            # APPLY DATA FILTER
                            # apply data filter sets the lists we want to print to correspond to the optimal aperature
                            finXTargCent = finXTargCentArray[~filtered_data.mask]
                            finYTargCent = finYTargCentArray[~filtered_data.mask]
                            finXRefCent = finXRefCentArray[~filtered_data.mask]
                            finYRefCent = finYRefCentArray[~filtered_data.mask]
                            # sets the lists we want to print to correspond to the optimal aperature
                            goodFluxes = arrayFinalFlux[~filtered_data.mask]
                            nonBJDTimes = arrayTimes[~filtered_data.mask]
                            nonBJDPhases = arrayPhases[~filtered_data.mask]
                            goodAirmasses = arrayAirmass[~filtered_data.mask]
                            goodTargets = arrayTargets[~filtered_data.mask]
                            goodReferences = arrayReferences[~filtered_data.mask]
                            goodTUnc = arrayTUnc[~filtered_data.mask]
                            goodRUnc = arrayRUnc[~filtered_data.mask]
                            goodNormUnc = arrayNormUnc[~filtered_data.mask]
                            goodResids = residualVals

                        # Reinitialize the the arrays to be empty
                        # airMassList = []
                        phasesList = []
                        # timesListed = []
                        targetFluxVals = []
                        referenceFluxVals = []
                        targUncertanties = []
                        refUncertanties = []
                        normUncertainties = []
                        xTargCent = []
                        yTargCent = []
                        xRefCent = []
                        yRefCent = []

                    # Exit aperture loop
                # Exit annulus loop
            # Exit the Comp Stars Loop
            print('\n*********************************************')
            print('Best Comparison Star: #' + str(bestCompStar))
            print('Minimum Residual Scatter: ' + str(round(minSTD * 100, 4)) + '%')
            print('Optimal Aperture: ' + str(minAperture))
            print('Optimal Annulus: ' + str(minAnnulus))
            print('********************************************\n')

            # # %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
            # # Save a text file of the RA and DEC of the target and comp
            # # %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
            # outParamsFile = open(saveDirectory + targetName + date + '.radec', 'w+')
            # outParamsFile.write('#RA, Dec, Target = 0 / Ref Star = 1, Centroid [pix]\n')
            # outParamsFile.write(raStr+","+decStr+",0,"+str(minAperture)+"\n")
            # outParamsFile.close()

            # %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
            # Save an image of the FOV
            # (for now, take the first image; later will sum all of the images up)
            # %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
            if wcsFile:
                if hdulWCS[0].header['COMMENT'][135].split(' ')[0] == 'scale:':
                    imscalen = float(hdulWCS[0].header['COMMENT'][135].split(' ')[1])
                    imscaleunits = 'Image scale in arc-secs/pixel'
                    imscale = imscaleunits + ": " + str(round(imscalen, 2))
                else:
                    i = 100
                    while hdulWCS[0].header['COMMENT'][i].split(' ')[0] != 'scale:':
                        i += 1
                    imscalen = float(hdulWCS[0].header['COMMENT'][i].split(' ')[1])
                    imscaleunits = 'Image scale in arc-secs/pixel'
                    imscale = imscaleunits + ": " + str(round(imscalen, 2))
                hdulWCS.close()  # close stream
                del hdulWCS
            elif "IM_SCALE" in imageheader:
                imscalen = imageheader['IM_SCALE']
                imscaleunits = imageheader.comments['IM_SCALE']
                imscale = imscaleunits + ": " + str(imscalen)
            elif "PIXSCALE" in imageheader:
                imscalen = imageheader['PIXSCALE']
                imscaleunits = imageheader.comments['PIXSCALE']
                imscale = imscaleunits + ": " + str(imscalen)
            else:
                print("Cannot find the pixel scale in the image header.")
                # pixscale = input("Do you know the size of your pixels? (y/n) ")
                # if pixscale == 'y' or pixscale == 'Y' or pixscale == 'yes':
                imscalen = input("Please enter the size of your pixel (e.g., 5 arcsec/pixel). ")
                imscale = "Image scale: " + imscalen
            imwidth = np.shape(sortedallImageData[0])[1]
            imheight = np.shape(sortedallImageData[0])[0]
            picframe = 10*(minAperture+minAnnulus)
            pltx = [min([finXTargCent[0], finXRefCent[0]])-picframe, max([finXTargCent[0], finXRefCent[0]])+picframe]
            FORwidth = pltx[1]-pltx[0]
            plty = [min([finYTargCent[0], finYRefCent[0]])-picframe, max([finYTargCent[0], finYRefCent[0]])+picframe]
            FORheight = plty[1]-plty[0]
            fig, ax = plt.subplots()
            target_circle = plt.Circle((finXTargCent[0], finYTargCent[0]), minAperture, color='lime', fill=False, ls='-', label='Target')
            target_circle_sky = plt.Circle((finXTargCent[0], finYTargCent[0]), minAperture+minAnnulus, color='lime', fill=False, ls='--', lw=.5)
            ref_circle = plt.Circle((finXRefCent[0], finYRefCent[0]), minAperture, color='r', fill=False, ls='-.', label='Comp')
            ref_circle_sky = plt.Circle((finXRefCent[0], finYRefCent[0]), minAperture+minAnnulus, color='r', fill=False, ls='--', lw=.5)
            plt.imshow(np.log10(sortedallImageData[0]), origin='lower', cmap='Greys_r', interpolation=None)  #,vmax=np.nanmax([arrayTargets[0],arrayReferences[0]]))
            plt.plot(finXTargCent[0], finYTargCent[0], marker='+', color='lime')
            ax.add_artist(target_circle)
            ax.add_artist(target_circle_sky)
            ax.add_artist(ref_circle)
            ax.add_artist(ref_circle_sky)
            plt.plot(finXRefCent[0], finYRefCent[0], '+r')
            plt.xlabel("x-axis [pixel]")
            plt.ylabel("y-axis [pixel]")
            plt.title("FOV for " + pDict['pName'] + "\n(" + imscale + ")")
            plt.xlim(pltx[0], pltx[1])
            plt.ylim(plty[0], plty[1])
            ax.grid(False)
            plt.plot(0, 0, color='lime', ls='-', label='Target')
            plt.plot(0, 0, color='r', ls='-.', label='Comp')
            l = plt.legend(frameon=None, framealpha=0)
            for text in l.get_texts():
                text.set_color("white")
            plt.savefig(infoDict['saveplot'] + "FOV" + pDict['pName'] + infoDict['date'] + ".pdf", bbox_inches='tight')
            plt.close()

            # Take the BJD times from the image headers
            if "BJD_TDB" in imageheader:
                goodTimes = nonBJDTimes
            # If not in there, then convert all the final times into BJD - using astropy alone
            else:
                print("No BJDs in Image Headers. Converting all JDs to BJD_TDBs.")
                print("Please be patient- this step can take a few minutes.")
                # targetloc = astropy.coordinates.SkyCoord(raStr, decStr, unit=(astropy.units.deg,astropy.units.deg), frame='icrs')
                # obsloc = astropy.coordinates.EarthLocation(lat=lati, lon=longit)
                # timesToConvert = astropy.time.Time(nonBJDTimes, format='jd', scale='utc', location=obsloc)
                # ltt_bary = timesToConvert.light_travel_time(targetloc)
                # time_barycentre = timesToConvert.tdb + ltt_bary
                # resultos = time_barycentre.value
                # goodTimes = resultos
                done = False
                t = threading.Thread(target=animate, daemon=True)
                t.start()
                resultos = utc_tdb.JDUTC_to_BJDTDB(nonBJDTimes, ra=pDict['ra'], dec=pDict['dec'], lat=lati, longi=longit, alt=infoDict['elev'])
                goodTimes = resultos[0]
                done = True

            # Centroid position plots
            plotCentroids(finXTargCent, finYTargCent, finXRefCent, finYRefCent, goodTimes, pDict['pName'], infoDict['date'])

            # TODO: convert the exoplanet archive mid transit time to bjd - need to take into account observatory location listed in Exoplanet Archive
            # tMidtoC = astropy.time.Time(timeMidTransit, format='jd', scale='utc')
            # forPhaseResult = utc_tdb.JDUTC_to_BJDTDB(tMidtoC, ra=raDeg, dec=decDeg, lat=lati, longi=longit, alt=2000)
            # bjdMidTOld = float(forPhaseResult[0])
            bjdMidTOld = pDict['midT']


            goodPhasesList = []
            # convert all the phases based on the updated bjd times
            for convertedTime in goodTimes:
                bjdPhase = getPhase(float(convertedTime), pDict['pPer'], bjdMidTOld)
                goodPhasesList.append(bjdPhase)
            goodPhases = np.array(goodPhasesList)

            # another 3 sigma clip based on residuals of the best LM fit
            try:
                interFilter = sigma_clip(goodResids, sigma=3, maxiters=1, cenfunc=np.median, copy=False)
            except TypeError:
                interFilter = sigma_clip(goodResids, sigma=3, cenfunc=np.median, copy=False)

            goodFluxes = goodFluxes[~interFilter.mask]
            goodTimes = goodTimes[~interFilter.mask]
            goodPhases = goodPhases[~interFilter.mask]
            goodAirmasses = goodAirmasses[~interFilter.mask]
            goodTargets = goodTargets[~interFilter.mask]
            goodReferences = goodReferences[~interFilter.mask]
            goodTUnc = goodTUnc[~interFilter.mask]
            goodRUnc = goodRUnc[~interFilter.mask]
            goodNormUnc = goodNormUnc[~interFilter.mask]

            # Calculate the standard deviation of the normalized flux values
            standardDev1 = np.std(goodFluxes)

            ######################################
            # PLOTS ROUND 1
            ####################################
            # Make plots of raw target and reference values
            plt.figure()
            plt.errorbar(goodTimes, goodTargets, yerr=goodTUnc, linestyle='None', fmt='-o')
            plt.xlabel('Time (BJD)')
            plt.ylabel('Total Flux')
            plt.rc('grid', linestyle="-", color='black')
            plt.grid(True)
            plt.title(pDict['pName'] + ' Raw Flux Values ' + infoDict['date'])
            plt.savefig(infoDict['saveplot'] + 'temp/TargetRawFlux' + pDict['pName'] + infoDict['date'] + '.png')
            plt.close()

            plt.figure()
            plt.errorbar(goodTimes, goodReferences, yerr=goodRUnc, linestyle='None', fmt='-o')
            plt.xlabel('Time (BJD)')
            plt.ylabel('Total Flux')
            plt.rc('grid', linestyle="-", color='black')
            plt.grid(True)
            plt.title('Comparison Star Raw Flux Values ' + infoDict['date'])
            plt.savefig(infoDict['saveplot'] + 'temp/CompRawFlux' + pDict['pName'] + infoDict['date'] + '.png')
            plt.close()

            # Plots final reduced light curve (after the 3 sigma clip)
            plt.figure()
            plt.errorbar(goodPhases, goodFluxes, yerr=goodNormUnc, linestyle='None', fmt='-bo')
            plt.xlabel('Phase')
            plt.ylabel('Normalized Flux')
            plt.rc('grid', linestyle="-", color='black')
            plt.grid(True)
            plt.title(pDict['pName'] + ' Normalized Flux vs. Phase ' + infoDict['date'])
            plt.savefig(infoDict['saveplot'] + 'NormalizedFluxPhase' + pDict['pName'] + infoDict['date'] + '.png')
            plt.close()

            # Save normalized flux to text file prior to MCMC
            outParamsFile = open(infoDict['saveplot'] + 'NormalizedFlux' + pDict['pName'] + infoDict['date'] + '.txt', 'w+')
            outParamsFile.write(str("BJD") + ',' + str("Norm Flux") + ',' + str("Norm Err") + ',' + str("AM") + '\n')
            for ti, fi, erri, ami in zip(goodTimes, goodFluxes, goodNormUnc, goodAirmasses):
                outParamsFile.write(str(round(ti, 8)) + ',' + str(round(fi, 7)) + ',' + str(round(erri, 6)) + ',' + str(round(ami, 2)) + '\n')
            # CODE YIELDED DATA IN PREV LINE FORMAT
            outParamsFile.close()
            print('\nOutput File Saved')
        else:
            goodTimes, goodFluxes, goodNormUnc, goodAirmasses = [], [], [], []
            for i in processeddata:
                try:
                    goodTimes.append(float(i.split(",")[0]))
                    goodFluxes.append(float(i.split(",")[1]))
                    goodNormUnc.append(float(i.split(",")[2]))
                    goodAirmasses.append(float(i.split(",")[3]))
                except ValueError:
                    continue

            goodTimes = np.array(goodTimes)
            goodFluxes = np.array(goodFluxes)
            goodNormUnc = np.array(goodNormUnc)
            goodAirmasses = np.array(goodAirmasses)

            bjdMidTOld = goodTimes[0]
            standardDev1 = np.std(goodFluxes)

        print('\n****************************************')
        print('Fitting a Light Curve Model to Your Data')
        print('****************************************\n')

        # EXOTIC now will automatically bin your data together to limit the MCMC runtime
        if len(goodTimes) > 200:
            print("Whoa! You have a lot of datapoints (" + str(len(goodTimes)) + ")!")
            bin_option = user_input("In order to limit EXOTIC's run time, EXOTIC can automatically bin down your data."
                                    "Would you to perform this action? (y/n): ", type_=str, val1='y', val2='n')
            if bin_option == 'y':
                goodTimes = binner(goodTimes, len(goodTimes) // 200)
                goodFluxes, goodNormUnc = binner(goodFluxes, len(goodFluxes) // 200, goodNormUnc)
                goodAirmasses = binner(goodAirmasses, len(goodAirmasses) // 200)
                print("Onwards and upwards!\n")

        #####################
        # MCMC LIGHTCURVE FIT
        #####################
        # The transit function is based on the analytic expressions of Mandel and Agol et al 2002. and Gael Roudier's transit model

        log = logging.getLogger(__name__)
        pymc3log = logging.getLogger('pymc3')
        pymc3log.setLevel(logging.ERROR)

        # OBSERVATIONS

        bjdMidTranCur = float(nearestTransitTime(goodTimes, pDict['pPer'], bjdMidTOld))

        extractRad = pDict['rprs']
        extractTime = bjdMidTranCur  # expected mid transit time of the transit the user observed (based on previous calculation)
        sigOff = standardDev1
        amC2Guess = 0  # guess b airmass term is 0
        sigC2 = .1  # this is a huge guess so it's always going to be less than this
        sigRad = (np.median(standardDev1)) / (2 * pDict['rprs'])  # uncertainty is the uncertainty in the dataset w/ propogation
        # propMidTUnct = uncTMid(ogPeriodErr, ogMidTErr, goodTimes, planetPeriod,bjdMidTOld)  # use method to calculate propogated midTUncertainty

        contextupdt(times=goodTimes, airm=goodAirmasses)  # update my global constant variable

        # define the light curve model using theano tensors
        @tco.as_op(itypes=[tt.dscalar, tt.dscalar, tt.dscalar, tt.dscalar], otypes=[tt.dvector])
        def gaelModel(*specparams):
            tranTime, pRad, amc1, amc2 = specparams

            # lightcurve model
            sep, ophase = time2z(context['times'], pDict['inc'], float(tranTime), pDict['aRs'], pDict['pPer'], pDict['ecc'])
            gmodel, garb = occultquad(abs(sep), linearLimb, quadLimb, float(pRad))

            # exponential airmass model
            airmassModel = (float(amc1) * (np.exp(float(amc2) * context['airmass'])))
            completeModel = gmodel * airmassModel

            return completeModel


        # initialize pymc3 sampler using gael model
        nodes = []
        lcMod = pm.Model()
        with lcMod:

            # PRIORS
            ### Double check these priors
            # BoundedNormal = pm.Bound(pm.Normal, lower=extractTime - 3 * planetPeriod / 4, upper=extractTime + 3 * planetPeriod / 4)  # ###get the transit duration
            midT = pm.Uniform('Tmid', upper=goodTimes[len(goodTimes) - 1], lower=goodTimes[0])
            BoundedNormal2 = pm.Bound(pm.Normal, lower=0, upper=1)
            radius = BoundedNormal2('RpRs', mu=extractRad, tau=1.0 / (sigRad ** 2))
            airmassCoeff1 = pm.Normal('Am1', mu=np.median(goodFluxes), tau=1.0 / (sigOff ** 2))
            airmassCoeff2 = pm.Normal('Am2', mu=amC2Guess, tau=1.0 / (sigC2 ** 2))

            # append to list of parameters
            nodes.append(midT)
            nodes.append(radius)
            nodes.append(airmassCoeff1)
            nodes.append(airmassCoeff2)

            # OBSERVATION MODEL
            obs = pm.Normal('obs', mu=gaelModel(*nodes), tau=1. / (goodNormUnc ** 2.), observed=goodFluxes)

        # Sample from the model
        final_chain_length = int(100000)

        with lcMod:
            step = pm.Metropolis()  # Metropolis-Hastings Sampling Technique
            if "Windows" in platform.system():
                trace = pm.sample(final_chain_length, step, chains=None, cores=1) # For some reason, Windows machines do not like using multi-cores with pymc3....
            else:
                trace = pm.sample(final_chain_length, step, chains=None, cores=None)

        # ----Plot the Results from the MCMC -------------------------------------------------------------------
        print('\n******************************************')
        print('MCMC Diagnostic Tests and Chi Squared Burn\n')

        # ChiSquared Trace to determine burn in length
        burn = plotChi2Trace(trace, goodFluxes, goodTimes, goodAirmasses, goodNormUnc, pDict['pName'], infoDict['date'])

        # OUTPUTS
        fitMidTArray = trace['Tmid', burn:]
        fitRadiusArray = trace['RpRs', burn:]

        fitMidT = float(np.median(trace['Tmid', burn:]))
        fitRadius = float(np.median(trace['RpRs', burn:]))
        fitAm1 = float(np.median(trace['Am1', burn:]))
        fitAm2 = float(np.median(trace['Am2', burn:]))

        midTranUncert = round(np.std(trace['Tmid', burn:]), 6)
        radUncert = round(np.std(trace['RpRs', burn:]), 6)
        am1Uncert = round(np.std(trace['Am1', burn:]), 6)
        am2Uncert = round(np.std(trace['Am2', burn:]), 6)

        # Plot Traces
        for keyi in trace.varnames:
            if "interval" not in keyi:
                plt.plot(trace[keyi, burn:])
                plt.title(keyi)
                plt.savefig(infoDict['saveplot'] + 'temp/Traces' + pDict['pName'] + infoDict['date'] + "_" + keyi + '.png')
                plt.close()

        # # Gelman Rubin
        # print("Gelman Rubin Convergence Test:")
        # print(pm.gelman_rubin(trace))

        # TODO set the MCMC chain length low, then run a gelman_rubin(trace) to see if <=1.1
        # (RTZ will probably make this 1.01 to be safe)
        # if they are not below this value, then run more chains
        # Hopefully this will keep the code running for less time

        fittedModel = lcmodel(fitMidT, fitRadius, fitAm1, fitAm2, goodTimes, goodAirmasses, plots=False)
        airmassMo = (fitAm1 * (np.exp(fitAm2 * goodAirmasses)))

        # Final 3-sigma Clip
        residuals = (goodFluxes / fittedModel) - 1.0
        try:
            finalFilter = sigma_clip(residuals, sigma=3, maxiters=1, cenfunc=np.median, copy=False)
        except TypeError:
            finalFilter = sigma_clip(residuals, sigma=3, cenfunc=np.median, copy=False)

        finalFluxes = goodFluxes[~finalFilter.mask]
        finalTimes = goodTimes[~finalFilter.mask]
        # finalPhases = goodPhases[~finalFilter.mask]
        finalPhases = (finalTimes - fitMidT) / pDict['pPer'] + 1.
        finalAirmasses = goodAirmasses[~finalFilter.mask]
        # finalTargets = goodTargets[~finalFilter.mask]
        # finalReferences = goodReferences[~finalFilter.mask]
        # finalTUnc = goodTUnc[~finalFilter.mask]
        # finalRUnc = goodRUnc[~finalFilter.mask]
        finalNormUnc = goodNormUnc[~finalFilter.mask]

        finalAirmassModel = (fitAm1 * (np.exp(fitAm2 * finalAirmasses)))

        # Final Light Curve Model
        finalModel = lcmodel(fitMidT, fitRadius, fitAm1, fitAm2, finalTimes, finalAirmasses, plots=False)

        # recaclculate phases based on fitted mid transit time
        adjPhases = []
        for bTime in finalTimes:
            newPhase = ((bTime - fitMidT) / pDict['pPer'])
            adjPhases.append(newPhase)
        adjustedPhases = np.array(adjPhases)

        #########################
        # PLOT FINAL LIGHT CURVE
        #########################

        f = plt.figure(figsize=(12 / 1.5, 9.5 / 1.5))
        f.subplots_adjust(top=0.94, bottom=0.08, left=0.1, right=0.96)
        ax_lc = plt.subplot2grid((4, 5), (0, 0), colspan=5, rowspan=3)
        ax_res = plt.subplot2grid((4, 5), (3, 0), colspan=5, rowspan=1)
        f.suptitle(pDict['pName'])

        x = adjustedPhases
        ax_res.set_xlabel('Phase')

        # # make symmetric about 0 phase
        # maxdist = max(np.abs(adjustedPhases[0]), adjustedPhases[-1])
        # ax_res.set_xlim([-maxdist, maxdist])
        # ax_lc.set_xlim([-maxdist, maxdist])

        # clip plot to get rid of white space
        ax_res.set_xlim([min(adjustedPhases), max(adjustedPhases)])
        ax_lc.set_xlim([min(adjustedPhases), max(adjustedPhases)])

        # making borders and tick labels black
        ax_lc.spines['bottom'].set_color('black')
        ax_lc.spines['top'].set_color('black')
        ax_lc.spines['right'].set_color('black')
        ax_lc.spines['left'].set_color('black')
        ax_lc.tick_params(axis='x', colors='black')
        ax_lc.tick_params(axis='y', colors='black')

        ax_res.spines['bottom'].set_color('black')
        ax_res.spines['top'].set_color('black')
        ax_res.spines['right'].set_color('black')
        ax_res.spines['left'].set_color('black')
        ax_res.tick_params(axis='x', colors='black')
        ax_res.tick_params(axis='y', colors='black')

        # residual histogramfinalAirmassModel
        # bins up to 3 std of Residuals

        # # key cahnge of dividing residuals by the airmass model too
        finalResiduals = finalFluxes / finalModel - 1.0

        maxbs = np.round(3 * np.std(finalResiduals), -2) * 1e6
        bins = np.linspace(-maxbs, maxbs, 7)

        # residual plot
        ax_res.plot(x, finalResiduals, color='gray', marker='o', markersize=5, linestyle='None')
        ax_res.plot(x, np.zeros(len(adjustedPhases)), 'r-', lw=2, alpha=1, zorder=100)
        ax_res.set_ylabel('Residuals')
        # ax_res.set_ylim([-.04, .04])
        ax_res.set_ylim([-2 * np.nanstd(finalResiduals), 2 * np.nanstd(finalResiduals)])

        correctedSTD = np.std(finalResiduals)
        # ax_lc.errorbar( x, self.y/self.data[t]['airmass'], yerr=self.yerr/self.data[t]['airmass'], ls='none', marker='o', color='black')
        ax_lc.errorbar(adjustedPhases, finalFluxes / finalAirmassModel, yerr=finalNormUnc / finalAirmassModel, ls='none',
                       marker='o', color='gray', markersize=4)
        ax_lc.plot(adjustedPhases, finalModel / finalAirmassModel, 'r', zorder=1000, lw=2)

        ax_lc.set_ylabel('Relative Flux')
        ax_lc.get_xaxis().set_visible(False)

        if binplotBool:
            ax_res.errorbar(binner(x, len(finalResiduals) // 10), binner(finalResiduals, len(finalResiduals) // 10),
                            yerr=binner(finalResiduals, len(finalResiduals) // 10, finalNormUnc / finalAirmassModel)[1],
                            fmt='s', mfc='b', mec='b', ecolor='b', zorder=10)
            ax_lc.errorbar(binner(adjustedPhases, len(adjustedPhases) // 10),
                           binner(finalFluxes / finalAirmassModel, len(adjustedPhases) // 10),
                           yerr=binner(finalResiduals, len(finalResiduals) // 10, finalNormUnc / finalAirmassModel)[1],
                           fmt='s', mfc='b', mec='b', ecolor='b', zorder=10)

        # For some reason, saving as a pdf crashed on Rob's laptop...so adding in a try statement to save it as a pdf if it can, otherwise, png
        try:
            f.savefig(infoDict['saveplot'] + 'FinalLightCurve' + pDict['pName'] + infoDict['date'] + ".pdf", bbox_inches="tight")
        except AttributeError:
            f.savefig(infoDict['saveplot'] + 'FinalLightCurve' + pDict['pName'] + infoDict['date'] + ".png", bbox_inches="tight")
        plt.close()

        # write output to text file
        outParamsFile = open(infoDict['saveplot'] + 'FinalLightCurve' + pDict['pName'] + infoDict['date'] + '.csv', 'w+')
        outParamsFile.write('FINAL TIMESERIES OF ' + pDict['pName'] + '\n')
        outParamsFile.write('BJD_TDB,Orbital Phase,Model,Flux,Uncertainty\n')

        for bjdi, phasei, fluxi, fluxerri, modeli, ami in zip(finalTimes, adjustedPhases, finalFluxes/finalAirmassModel,
                                                              finalNormUnc/finalAirmassModel, finalModel/finalAirmassModel, finalAirmassModel):
            outParamsFile.write(str(bjdi)+","+str(phasei)+","+str(modeli)+","+str(fluxi)+","+str(fluxerri)+"\n")

        outParamsFile.close()

        ###################
        # CHI SQUARED ROLL
        ###################

        # Check for how well the light curve fits the data
        chiSum = 0
        chiSquareList = []
        rollList = []

        # ----Chi squared calculation---------------------------------------------------------------
        for k in np.arange(len(finalFluxes) // 10):  # +1
            sushi = np.roll(finalFluxes, k * 10)

            # Performs a chi squared roll
            chiSquareList.append(np.sum(((sushi - finalModel) / finalNormUnc) ** 2.) / (len(sushi) - 4))
            rollList.append(k * 10)

        plt.figure()
        plt.plot(rollList, chiSquareList, "-o")
        plt.xlabel('Bin Number')
        plt.ylabel('Chi Squared')
        plt.savefig(infoDict['saveplot'] + 'temp/ChiSquaredRoll' + pDict['pName'] + '.png')
        plt.close()

        # print final extracted planetary parameters

        print('*********************************************************')
        print('FINAL PLANETARY PARAMETERS')
        print('\nThe fitted Mid-Transit Time is: ' + str(fitMidT) + ' +/- ' + str(midTranUncert) + ' (BJD)')
        print('The fitted Ratio of Planet to Stellar Radius is: ' + str(fitRadius) + ' +/- ' + str(
            radUncert) + ' (Rp/Rs)')
        print('The transit depth uncertainty is: ' + str(
            100 * 2 * fitRadius * round(np.std(trace['RpRs', burn:]), 6)) + ' (%)')
        print('The fitted airmass1 is: ' + str(fitAm1) + ' +/- ' + str(am1Uncert))
        print('The fitted airmass2 is: ' + str(fitAm2) + ' +/- ' + str(am2Uncert))
        print('The scatter in the residuals of the lightcurve fit is: ' + str(round(100 * correctedSTD, 3)) + ' (%)')
        print('\n*********************************************************')

        ##########
        # SAVE DATA
        ##########

        # write output to text file
        outParamsFile = open(infoDict['saveplot'] + 'FinalParams' + pDict['pName'] + infoDict['date'] + '.txt', 'w+')
        outParamsFile.write('FINAL PLANETARY PARAMETERS\n')
        outParamsFile.write('')
        outParamsFile.write('The fitted Mid-Transit Time is: ' + str(fitMidT) + ' +/- ' + str(midTranUncert) + ' (BJD)\n')
        outParamsFile.write('The fitted Ratio of Planet to Stellar Radius is: ' + str(fitRadius) + ' +/- ' + str(
            radUncert) + ' (Rp/Rs)\n')
        outParamsFile.write('The transit depth uncertainty is: ' + str(
            2 * 100 * fitRadius * round(np.std(trace['RpRs', burn:]), 6)) + ' (%)\n')
        outParamsFile.write('The fitted airmass1 is: ' + str(fitAm1) + ' +/- ' + str(am1Uncert) + '\n')
        outParamsFile.write('The fitted airmass2 is: ' + str(fitAm2) + ' +/- ' + str(am2Uncert) + '\n')
        outParamsFile.write(
            'The scatter in the residuals of the lightcurve fit is: ' + str(round(100 * correctedSTD, 3)) + '%\n')
        outParamsFile.close()
        print('\nFinal Planetary Parameters have been saved in ' + infoDict['saveplot'] + ' as '
              + pDict['pName'] + infoDict['date'] + '.txt' + '\n')

        # AAVSO Format
        userCode = infoDict['aavsonum']
        secuserCode = infoDict['secondobs']
        # else:
        outParamsFile = open(infoDict['saveplot'] + 'AAVSO' + pDict['pName'] + infoDict['date'] + '.txt', 'w+')
        outParamsFile.write('#TYPE=EXOPLANET\n')  # fixed
        outParamsFile.write('#OBSCODE=' + infoDict['aavsonum'] + '\n')  # UI
        outParamsFile.write('#SECONDARYOBSCODE=' + infoDict['secondobs'] + '\n')  # UI
        outParamsFile.write('#SOFTWARE=EXOTIC v' + versionid + '\n')  # fixed
        outParamsFile.write('#DELIM=,\n')  # fixed
        outParamsFile.write('#DATE_TYPE=BJD_TDB\n')  # fixed
        outParamsFile.write('#OBSTYPE=' + infoDict['ctype'] + '\n')
        outParamsFile.write('#STAR_NAME=' + pDict['sName'] + '\n')  # code yields
        outParamsFile.write('#EXOPLANET_NAME=' + pDict['pName'] + '\n')  # code yields
        outParamsFile.write('#BINNING=' + infoDict['pixelbin'] + '\n')  # user input
        outParamsFile.write('#EXPOSURE_TIME=' + str(infoDict['exposure']) + '\n')  # UI
        outParamsFile.write('#FILTER=' + infoDict['filter'] + '\n')
        outParamsFile.write('#NOTES=' + infoDict['notes'] + '\n')
        outParamsFile.write('#DETREND_PARAMETERS=AIRMASS, AIRMASS CORRECTION FUNCTION\n')  # fixed
        outParamsFile.write('#MEASUREMENT_TYPE=Rnflux\n')  # fixed
        # outParamsFile.write('#PRIORS=Period=' + str(planetPeriod) + ' +/- ' + str(ogPeriodErr) + ',a/R*=' + str(
        #     semi) + ',Tc=' + str(round(bjdMidTranCur, 8)) + ' +/- ' + str(round(propMidTUnct, 8)) + ',T0=' + str(
        #     round(bjdMidTOld, 8)) + ' +/- ' + str(round(ogMidTErr, 8)) + ',inc=' + str(inc) + ',ecc=' + str(
        #     eccent) + ',u1=' + str(linearLimb) + ',u2=' + str(quadLimb) + '\n')  # code yields
        outParamsFile.write('#PRIORS=Period=' + str(pDict['pPer']) + ' +/- ' + str(pDict['pPerUnc']) + ',a/R*=' + str(
            pDict['aRs']) + ',inc=' + str(pDict['inc']) + ',ecc=' + str(pDict['ecc']) + ',u1=' + str(linearLimb) + ',u2=' + str(quadLimb) + '\n')
        # code yields
        outParamsFile.write(
            '#RESULTS=Tc=' + str(round(fitMidT, 8)) + ' +/- ' + str(round(midTranUncert, 8)) + ',Rp/R*=' + str(
                round(fitRadius, 6)) + ' +/- ' + str(round(radUncert, 6)) + ',Am1=' + str(
                round(fitAm1, 5)) + ' +/- ' + str(round(am1Uncert, 5)) + ',Am2=' + str(
                round(fitAm2, 5)) + ' +/- ' + str(round(am2Uncert, 5)) + '\n')  # code yields
        # outParamsFile.write('#NOTES= ' + userNameEmails + '\n')
        outParamsFile.write('#DATE,NORM_FLUX,MERR,DETREND_1,DETREND_2\n')
        for aavsoC in range(0, len(finalTimes)):
            outParamsFile.write(
                str(round(finalTimes[aavsoC], 8)) + ',' + str(round(finalFluxes[aavsoC], 7)) + ',' + str(
                    round(finalNormUnc[aavsoC], 7)) + ',' + str(round(finalAirmasses[aavsoC], 7)) + ',' + str(
                    round(finalAirmassModel[aavsoC], 7)) + '\n')
        # CODE YIELDED DATA IN PREV LINE FORMAT
        outParamsFile.close()
        print('Output File Saved')
        # pass

        # outParamsFile = open(saveDirectory + 'Residuals' + targetName + date + '.txt', 'w+')
        # outParamsFile.write('#DATE,RESIDUALS\n')
        # for aavsoC in range(0, len(finalTimes)):
        #     outParamsFile.write(
        #         str(round(finalTimes[aavsoC], 8)) + ',' + str(round(finalResiduals[aavsoC], 8)) + '\n')
        # # CODE YIELDED DATA IN PREV LINE FORMAT
        # outParamsFile.close()
        # print('Residuals File Saved')

        print('\n************************')
        print('End of Reduction Process')
        print('************************')

    # end regular reduction script

    pass
