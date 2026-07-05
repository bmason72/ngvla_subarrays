
import combo_utils as combut

truth_image = 'ngvla_30dor/ngvla_30dor.ngvla-core-revC_loc.skymodel'
joint_vp = 'ngvlaSba_final.tab'
#"ngvla-and-sba-final.tab"

phase_center="J2000 08h37m27.2s 22d39m14.7s"
core_ms = 'ngvla_30dor/ngvla_30dor.ngvla-core-revC_loc'
sd_ms='sd_30dor_new/sd_30dor_new.ngvla-sd_loc.sd'
sba_ms = 'sba_30dor_new/sba_30dor_new.ngvla-sba-revC_loc'
sd_img_fixed = sd_ms+'.sf7.tp.fixed'

##############

# dec2020 new & correct VP table prescription for non-alma heterogeneous arrays-
rmtables(joint_vp)
vp.reset()
vp.setpbairy(telescope='NGVLA1',dishdiam=6.0,blockagediam=0.0,maxrad='8.5deg',reffreq='1.0GHz',dopb=True)
vp.setpbairy(telescope='NGVLA1',dishdiam=18.0,blockagediam=0.0,maxrad='8.5deg',reffreq='1.0GHz',dopb=True)
vp.saveastable(joint_vp)

# Empty list in which we'll build up a list of the image products
#  created along the way
#
# all images must have the same number of pixels
#  since they use one PB image in the fidelity calculation
#  the created_images will lack the TP maps so it's not a complete
#  manifest.

created_images = []
 
# core only imaging -- 

# make an SD image in Jy/pix on that grid-
sd_model = combut.make_clnMod_fromImg(sd_img_fixed,INT_imagename+'.image',pb_map=INT_imagename+'.pb',tag='coreGrid')

INT_imagename = core_ms + '.autoDev2.final.sdmod'
rmtables(INT_imagename+"*")
#delmod(vis=core_ms+'.ms')
tclean(vis=core_ms+'.ms',imagename=INT_imagename,niter=10000,cycleniter=1000,pblimit=0.3,phasecenter=phase_center,deconvolver='multiscale',
       interactive=False,pbcor=True,cell='0.25arcsec',imsize=[1960,1960],gridder='mosaic',uvtaper='2arcsec',weighting='natural',threshold='0.05Jy',usemask='auto-multithresh',vptable=joint_vp,
       scales=[0,7,35],smallscalebias=0.55,sidelobethreshold=3.5,noisethreshold=5.0,minbeamfrac=0.3,lownoisethreshold=2.5,negativethreshold=0.0,growiterations=50,smoothfactor=0.75,cyclefactor=0.65,verbose=True,startmodel=sd_model)
for mm in ['.image','.residual','.pb','.image.pbcor']:
    created_images.append(INT_imagename+mm)


INT_imagename = core_ms + '.simple.final'
rmtables(INT_imagename+"*")
#delmod(vis=core_ms+'.ms')
tclean(vis=core_ms+'.ms',imagename=INT_imagename,niter=20000,cycleniter=1000,pblimit=0.3,phasecenter=phase_center,
       interactive=False,pbcor=True,cell='0.25arcsec',imsize=[1960,1960],gridder='mosaic',uvtaper='2arcsec',weighting='natural',threshold='0.05Jy',usemask='auto-multithresh',vptable=joint_vp,
       sidelobethreshold=3.5,noisethreshold=5.0,minbeamfrac=0.3,lownoisethreshold=2.5,negativethreshold=0.0,growiterations=50,smoothfactor=0.75,cyclefactor=0.65,verbose=True,startmodel='')
for mm in ['.image','.residual','.pb','.image.pbcor']:
    created_images.append(INT_imagename+mm)

