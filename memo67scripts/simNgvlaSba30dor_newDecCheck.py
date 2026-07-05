
#
# sep2019 bsm 
#  -fix vptable
#  -fix integration time ratio
#     
# check -27, 0ish, 30, 80

my_cfg = "ngvla-sba-revC_loc"
#my_cfg = "sbarot"

# transit
# "x " = xyz AR N-S
#  29.8% flagged
myproj="sba_30dor_transit"
in_map_center="J2000 08h37m27.2s 34d00m44.7s"
phase_center="J2000 08h37m27.2s 34d00m14.7s"

# 23"x13" = 1.79 AR N-S
#  29.8% flagged
#myproj="sba_30dor_newM20"
#in_map_center="J2000 08h37m27.2s -27d38m44.7s"
#phase_center="J2000 08h37m27.2s -27d38m14.7s"

# 23"x13" = 1.79 AR N-S
#  29.8% flagged
#myproj="sba_30dor_newM20"
#in_map_center="J2000 08h37m27.2s -27d38m44.7s"
#phase_center="J2000 08h37m27.2s -27d38m14.7s"

# with rotated config
# 22"x13" = 1.69 AR N-S
# 6.4% of data flagged
#myproj="sba_30dor_newM20"
#in_map_center="J2000 08h37m27.2s -27d38m44.7s"
#phase_center="J2000 08h37m27.2s -27d38m14.7s"

# 12"x13" = 1.08 AR N-S
# none flagged
#myproj="sba_30dor_newEquatorial"
#in_map_center="J2000 08h37m27.2s 0d38m44.7s"
#phase_center="J2000 08h37m27.2s 0d39m14.7s"

# with sbarot
# 13x12 @ 45deg
#myproj="sba_30dor_newEquatorial"
#in_map_center="J2000 08h37m27.2s 0d38m44.7s"
#phase_center="J2000 08h37m27.2s 0d39m14.7s"

# 12"x11" = 1.09 AR E-W
#myproj="sba_30dor_newP44"
#in_map_center="J2000 08h37m27.2s 44d38m44.7s"
#phase_center="J2000 08h37m27.2s 44d39m14.7s"

# with sbarot
# AR = 1.3 E-W
#myproj="sba_30dor_newP44"
#in_map_center="J2000 08h37m27.2s 44d38m44.7s"
#phase_center="J2000 08h37m27.2s 44d39m14.7s"

# 16"x12" = 1.33 AR N-S 
# none flagged
#myproj="sba_30dor_newP80"
#in_map_center="J2000 08h37m27.2s 79d38m44.7s"
#phase_center="J2000 08h37m27.2s 79d39m14.7s"

# with sbarot
# 15"x13" = 1.15 AR N-S
# none flagged
#myproj="sba_30dor_newP80"
#in_map_center="J2000 08h37m27.2s 79d38m44.7s"
#phase_center="J2000 08h37m27.2s 79d39m14.7s"

# original -  phase ctr is 0.5 arcm north of map center
#in_map_center="J2000 08h37m27.2s 22d38m44.7s"
#phase_center="J2000 08h37m27.2s 22d39m14.7s"

skmod="30dor-hires.fits"


# core sim = 1870s
#   *2.2 = 4114sec (SBA total integ goal)
#   23 * 180s = 4140s -- 18x 10sec integs per ea of 23 ptgs
mytotaltime="4140s"
out_vis = myproj+'/'+myproj+'.'+my_cfg
real_cfg=my_cfg+'.cfg'

this_vp = 'sba_final.tab'
rmtables(this_vp)
# use this to set the beam properly
vp.reset()
vp.setpbairy(telescope='NGVLA',dishdiam=6.0,blockagediam=0.0,maxrad='8.5deg',reffreq='1.0GHz',dopb=True)
vp.saveastable(this_vp)
sba_table = vp.getuserdefault('NGVLA')
vp.setuserdefault(sba_table,'NGVLA','sbaNgvla')

# 
# OR load a pre-existing table-
#vp.reset()
# vp.loadtable() - old versions....
#vp.loadfromtable(this_vp)
#

default("simobserve")
project            =  myproj
indirection=in_map_center
direction=phase_center
skymodel         =  skmod
inbright="0.01Jy/pixel"
incenter="93.0GHz"
inwidth="100MHz"
# have simobserve calculate mosaic pointing locations:
setpointings       =  True
mapsize = "4.5arcmin"
hourangle = "transit"
integration        =  "10s"
obsmode            =  "int"
graphics           =  "both"
thermalnoise       = ""
refdate = "2017/12/03"
antennalist        =  real_cfg
totaltime          =  mytotaltime
simobserve() 

