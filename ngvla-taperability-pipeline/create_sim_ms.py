## To be run in CASA
import os
import sys

try:
    from simutil import simutil
except:
    from casatasks.private.simutil import simutil


if os.path.isfile(configuration):
    config_prefix = configuration.replace('.cfg','') if configuration.endswith('.cfg') else configuration
else:
    print('a configuration file is requred')

cwd=os.getcwd()

outdir = 'taperability-{0}'.format(config_prefix)

try:
    os.mkdir(outdir)
    print('creating simulation directory: {0}'.format(outdir))
except:
    raise Exception('output directory {0} already exists'.format(outdir))


os.system('cp run_all.py {0}'.format(outdir))
os.system('cp {0} {1}'.format(configuration, outdir))


ms_name = outdir+'/'+outdir+'.ms'



u=simutil()
try:
    x,y,z,d,padnames,telescope,posobs = u.readantenna( outdir+'/'+configuration )
except:
    x,y,z,d,padnames,padnames2,telescope,posobs = u.readantenna( outdir+'/'+configuration )


sm.open( ms_name )

## set the antenna configuration
sm.setconfig(telescopename='ngvla', x=x, y=y, z=z,
             dishdiameter=d, mount='alt-az', antname=list(padnames),padname=list(padnames),
             coordsystem='global', referencelocation=posobs)

##global is earth-centered

## set the spectral windows
sm.setspwindow(spwname='band', freq=frequency,
               deltafreq='1MHz', freqresolution='1MHz',
               nchannels=1, stokes='RR RL LR LL')#resource tool

sm.setfeed('perfect R L')


sm.setfield(sourcename='source', sourcedirection=['J2000','00h0m0.0',source_dec+'.0.0.000'])


## data are flagged either because they are below the limit elevation or the antenna is shadowed
sm.setlimits(shadowlimit=0.001, elevationlimit='8.0deg')

## Weight to assign autocorrelation
sm.setauto(autocorrwt=0.0)


# int time: how often the array writes one visibility
sm.settimes(integrationtime=integration_time, usehourangle=True,
            referencetime=me.epoch('utc', 'today'))

## the observation time 
#writes a scan of that source with that resource
sm.observe('source', 'band', starttime=timerange[0], stoptime=timerange[1])

sm.setnoise(mode='simplenoise', simplenoise='1Jy') ## set the noise level

sm.corrupt() ## adds the noise: calculate random Gaussian numbers and add to visibilities

sm.close()

print('created simulated MS: {0}'.format(ms_name))



#
