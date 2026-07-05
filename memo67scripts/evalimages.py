 
import combo_utils as combut

truth_image = 'ngvla_30dor/ngvla_30dor.ngvla-core-revC_loc.skymodel'
joint_vp = 'ngvlaSba_final.tab'
#"ngvla-and-sba-final.tab"

phase_center="J2000 08h37m27.2s 22d39m14.7s"
core_ms = 'ngvla_30dor/ngvla_30dor.ngvla-core-revC_loc'
sd_ms='sd_30dor_new/sd_30dor_new.ngvla-sd_loc.sd'
sba_ms = 'sba_30dor_new/sba_30dor_new.ngvla-sba-revC_loc'
sd_img_fixed = sd_ms+'.sf7.tp.fixed'
newms='joint_30dor.ngvla.revC_new'


INT_imagename = newms+'.autoDev5b'

sd_model = combut.make_clnMod_fromImg(sd_img_fixed,INT_imagename+'.image',pb_map=INT_imagename+'.pb',tag='jointGridTest')

best_images = ['joint_30dor.ngvla.revC_new.autoDev5b.image.pbcor',
               'joint_30dor.ngvla.revC_new.autoDev5b.image.feather.pbcor',
               'joint_30dor.ngvla.revC_new.sdmod.autoDev5b.image.pbcor',
               'joint_30dor.ngvla.revC_new.sdmod.autoDev5b.image.feather.pbcor']

for mm in best_images:
    combut.calc_fidelity(mm,truth_image,INT_imagename+'.pb',outfile=mm+'.fiderr',pb_thresh=0.5)

