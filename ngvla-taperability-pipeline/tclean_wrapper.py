## run in CASA

import os
import sys
import shutil
import argparse as ap


def make_image_tclean( vis, image_base_name = 'simimage_' , imsize = 1000, cellsize=-1, oversample=4., weighting='briggs', robust=0.5, taper= 0, total_time='8h', adaptive_cellsize=False ):

    if cellsize == -1:
        im.open(vis)
        cellsize_info = im.advise()
        im.close()
        cellsize = cellsize_info[2]['value']*2./oversample
        if adaptive_cellsize:
            cellsize = np.max([cellsize,taper/oversample/1e3])        


    try:
        prec=int('{0:.1e}'.format(cellsize).split('e-')[1]) + 1
    except:
        prec=1
    cell= str('{0:.{prec}f}arcsec'.format(cellsize, prec=prec))

    if taper == 0:
        uvtaper=[]
    else:
        uvtaper=['{0}marcsec'.format(taper),'{0}marcsec'.format(taper),'0deg']


    if '/' in vis:
        imagename = image_base_name+vis.rstrip('/').split('/')[-1].split('.ms')[0]+'_'+str(cell)+'_'+str(imsize)+'_'+total_time+'_'+str(robust)+'_TA'+str(taper)
    else:
        imagename = image_base_name+vis.split('.ms')[0]+'_'+str(cell)+'_'+str(imsize)+'_'+total_time+'_'+str(robust)+'_TA'+str(taper)


    if not os.path.isdir(imagename+'.image'):
        tclean(vis= vis, imagename= imagename, cell=cell, imsize=imsize, datacolumn = 'data', weighting = weighting, robust = robust, uvtaper = uvtaper, savemodel='none', pblimit=-0.02 )

    print(vis, cell, imagename, imsize)

    return vis, cellsize, imagename, imsize




parser = ap.ArgumentParser( formatter_class=ap.RawDescriptionHelpFormatter )
parser.add_argument('-v','--vis',type=str,default='',help="Measurement Set name")
parser.add_argument('-n','--name',type=str,default='simimage_',help="Image base name")
parser.add_argument('-i','--imsize',type=int,default=640,help="Image size in pixels")
parser.add_argument('-s','--cell',type=float,default=-1,help="Image cell size in mas")
parser.add_argument('-r','--robust',type=float,default=0.0,help="Briggs weighting robust parameter")
parser.add_argument('-t','--taper',type=float,default=0,help="UV taper size in mas")
parser.add_argument('-w','--weight',type=str,default='natural',help="Imaging weight type")
parser.add_argument('-o','--oversample',type=int,default=4,help="Oversampling factor")
parser.add_argument('--cs_adapt',action='store_true',help="Use adaptive cellsize")

args, unknown = parser.parse_known_args()


print(args)

vis, cellsize, imagename, imsize = make_image_tclean( args.vis, image_base_name=args.name, imsize=args.imsize, cellsize=args.cell, oversample=args.oversample, weighting=args.weight, robust=args.robust, taper=args.taper, adaptive_cellsize=args.cs_adapt )

ext_to_del = ['.pb','.sumwt','.model','.residual']
for delext in ext_to_del:
    if os.path.isdir( imagename+delext ):
        shutil.rmtree( imagename+delext )

ia.open(imagename+'.image')
x=ia.getchunk()
beam=ia.restoringbeam()['major']['value']
ia.close()
with open(imagename+'.image.rms','w') as out1:
    out1.write( str(np.std(x)) + '  ' + str(np.sqrt(np.mean(np.square(x)))) )



#
