
# Observes a FITS file (Run this once)

in_map_center="J2000 08h37m27.2s 22d38m44.7s"
phase_center="J2000 08h37m27.2s 22d39m14.7s"

myproj="ngvla_30dor"

skmod="30dor-hires.fits"

# this one case automatically gets the VP right. 
#  18m antenna is built into CASA as the 
#  default for observatory=NGVLA

# 187 ptgs....
#  10sec each = 1870sec

mytotaltime="1870s" # core
my_cfg = "ngvla-core-revC_loc"
out_vis = myproj+'/'+myproj+'.'+my_cfg
real_cfg=my_cfg+'.cfg'

default("simobserve")
project            =  myproj
indirection=in_map_center
direction=phase_center
skymodel         =  skmod
inbright="0.01Jy/pixel"
incenter="93.0GHz"
inwidth="100MHz"
setpointings       =  True
mapsize  = "4.5arcmin"
hourangle = "transit"
integration        =  "10s"
obsmode            =  "int"
graphics           =  "both"
refdate = "2017/12/01"
antennalist        =  real_cfg
totaltime          =  mytotaltime
thermalnoise       = ""
simobserve() 

# now tweak the telescope name-
print("If this hangs its probably because of a table lock in the parent or OBSERVATION table:")
tb.open(out_vis+'.ms/OBSERVATION',nomodify=False)
telcol=tb.getcol("TELESCOPE_NAME")
new_telcol = np.array(["NGVLA1" for i in range(len(telcol))],dtype=telcol.dtype)
tb.putcol("TELESCOPE_NAME",new_telcol)
tb.flush()
tb.done()


