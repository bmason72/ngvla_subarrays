# ngVLA taperability pipeline version 1.0


# name of the array configuration file (antenna locations in global coordinates)
configuration = 'ngvla-plains-revC.cfg'

# simulation frequency (CASA frequency string)
frequency = '30GHz'

# simulation dump time (CASA time string)
integration_time = '60s'

# simulation range of hour angles (CASA time string)
timerange = ['-2h','2h']

# simulation declination in degrees
source_dec = '+24'

# simulated image size in pixels
imsize = 4096   # suitable for most arrays
#imsize = 15000  # suitable for main array
#imsize = 25000   # suitable for main+lba array

# image cell size in arcsec, or -1 to calculate from oversample and im.advise 
cellsize = -1

# image oversampling factor in pixels (only used if cellsize = -1)
oversample = 5

# if True, will adapt the cellsize based on the value of the taper (constant oversampling)
# if False, will hold the cellsize constant (oversampling will increase at lower resolutions)
adaptive_cellsize = False

# image tapers in mas (list or numpy array).  

import numpy as np
#TA_list = np.logspace(3,4,15) # suitable for core array
TA_list = np.logspace(1.5,3,15) # suitable for plains array
#TA_list = np.logspace(0,1.5,15)  # suitable for mid array
#TA_list = np.logspace(-0.8,0.5,15)  # suitable for lba array
#TA_list = np.logspace(0,2.5,15)  # suitable for plains+mid array
#TA_list = np.logspace(1.8,4,15)  # suitable for plains+core array
#TA_list = np.logspace(0,4,15)  # suitable for main array
#TA_list = np.logspace(-0.8,4,15)  # suitable for main+lba array


exec(open("create_sim_ms.py").read())

exec(open("create_images.py").read())

exec(open("analyze_images.py").read())



#
