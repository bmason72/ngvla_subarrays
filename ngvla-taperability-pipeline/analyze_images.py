import pylab as pl
import numpy as np
import re
from glob import glob
import os
#import warnings
#warnings.filterwarnings("ignore", category=VisibleDeprecationWarning)



print('analyzing images')

all_psf = glob(image_base_name+'*.psf')

psf_pattern = '([\d\.]+)arcsec_([\d]+)_([\d]+)h_([\d\.-]+)_TA([\d\.]+).psf'


dat = np.zeros( (len(all_psf),5) )
for i,this_psf in enumerate(all_psf):
    
    m = re.search(psf_pattern,this_psf)
    if m:
        dat[i,0] = np.float(m.groups()[3])
        dat[i,1] = np.float(m.groups()[4])

        ia.open(this_psf)
        beam = ia.restoringbeam()
        ia.close()

        dat[i,2] = qa.convert(beam['major'],'mas')['value']
        dat[i,3] = qa.convert(beam['minor'],'mas')['value']

        with open(this_psf.replace('.psf','.image.rms'),'r') as in1:
           this_std, this_rms = in1.read().strip().split()
        
        ratio = float(this_rms)/float(this_std)

        
        if ratio > 1.05:
	   print('Warning: the ratio of rms to std is {0:.2f} for image {1}'.format(ratio,this_psf.replace('.psf','.image')))
           

        dat[i,4] = float(this_rms)


    else:
        print(this_psf)




# compute taperability curve

na_psf = np.where((dat[:,0] == 2) & (dat[:,1] == 0))[0][0]

sigma_na = dat[na_psf,4]

b_effective = (dat[:,2]*dat[:,3])**.5

eta_w = dat[:,4]/sigma_na

sort_by_b = np.argsort(b_effective)

b_sorted = b_effective[sort_by_b]

e_sorted = eta_w[sort_by_b]

log_b_sorted = np.log10(b_sorted)

hits = np.where(e_sorted < 3)[0]

robust_points = dat[sort_by_b,0][hits] != 2



# save output table
output_table = outdir+'/taperability_table.txt'
output_dat = np.zeros( (len(dat), 5) )
output_dat[:,0] = dat[sort_by_b,0] # robust
output_dat[:,1] = dat[sort_by_b,1] # taper
output_dat[:,2] = dat[sort_by_b,2] # bmaj (mas)
output_dat[:,3] = dat[sort_by_b,3] # bmin (mas)
output_dat[:,4] = eta_w[sort_by_b] # eta_w

with open(output_table,'w') as out1:
  out1.write('#robust taper(mas) bmaj(mas) bmin(mas) eta_w\n')
  for line in output_dat:
    out1.write(' '.join(['{0:.2f}'.format(f) for f in line])+'\n')
    


# plot taperability curve
pl.plot( b_sorted[hits],e_sorted[hits],'k--',alpha=0.5)
pl.plot( b_sorted[hits][~robust_points],e_sorted[hits][~robust_points],'ro', label='Natural, TA=changes')
pl.plot( b_sorted[hits][robust_points],e_sorted[hits][robust_points],'bo', label='Robust, TA=0')
pl.legend(loc='lower right', prop={'size': 12}, numpoints=1)

pl.ylim(.8,3)
ax=pl.gca()
ax.set_xscale('log')
pl.xlabel('Resolution (mas)')
pl.ylabel('eta_w')

pl.savefig(outdir+'/taperability_curve.png')
pl.close()



# plot the native psf
def get_psf_cuts(image_name):
    ia.open(image_name)
    pixels = ia.getregion(dropdeg=True)
    pixels_arcsec = qa.convert(qa.quantity(ia.summary()['incr'][1],'rad'),'arcsec')['value']
    ia.close()
    npixels = pixels.shape[0]
    peak_px = np.where(pixels==1)[0][0]
    x = np.linspace(-npixels/2, npixels/2, npixels) * pixels_arcsec
    cut1 = pixels[peak_px,:].squeeze() # north-south cut
    cut2 = pixels[:,peak_px].squeeze() # east-west cut
    return (x,cut1, cut2)



x_lim = 5*b_effective[na_psf] / 1e3

this_psf = all_psf[na_psf]
xcut,cut_NS,cut_EW = get_psf_cuts(this_psf)
pl.plot(xcut,cut_NS,'-',lw=2, alpha=0.5, label='North-South')
pl.plot(xcut,cut_EW,'-',lw=2, alpha=0.5, label='East-West')
pl.ylim(-.05,1.05)
pl.xlim( -x_lim,x_lim )
pl.xlabel('arcsec')
pl.title('Native PSF Cuts')
pl.legend(loc='upper right', prop={'size': 12})
pl.savefig(outdir+'/psf_cuts.png')
pl.close()







#
