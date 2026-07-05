import csv
import pylab as pl
import saUtil as sau
from importlib import reload
from saUtil import execfile
import pickle

#
# To Do
# -assess N_10 times vs beam sculpting times vs N_bl times vs N_bl_inRange times
#   -run sims of mid+plains+10core
#   -update rop_custom.csv
#   -i can include ones that didn't change SA since beam sculpting is still a thing
#   -rerun assessment
# -write an overall flowchart of how it will probably actually work
# -write down the metrics and what will be tracked
# -compute ant hrs and bl_effic for a range of cases and look at them
# -think about how the other scheduling dimensions will play out
# -think of how the "viable options" will be carried forward
# -consider scientific priority
#

#
# to do (31may23 discussion)
# -add inner half core and (outer half core + X)
# -add (LONG+5MID / MID-5)
# -clarify scope of this task in a paranoid way
# -some how capture commensal / commensal multi-band...?
# -add "uv-coverage" flag? or more likely, allow user to override
#   selection

# use transform_eop.py to get the EOP into a useful data structure
# read EOP in if needed
fh=open('eop.pkl','rb')
data=pickle.load(fh)
fh.close()

# split core - prints to screen...
#sau.split_by_radius("cfgs/ngvla-revE.core.loc.cfg")

# The order here may have an impact on the final order.
config_files=['cfgs/core_inner.loc.cfg',
  'cfgs/core_outer.loc.cfg',
  'cfgs/ngVLA-revE.spiral.loc.cfg',
  'cfgs/ngVLA-revE.spiralOuterCore.loc.cfg',
  'cfgs/ngvla-revD.core-LOC.cfg',
  'cfgs/ngvla-revDE-plains.loc.cfg']

config_files_rev_c=['sims/RevC_core_ms.pkl',
                    'sims/RevC_lba_ms.pkl',
                    'sims/RevC_main_lba_ms.pkl',
                    'sims/RevC_main_ms.pkl',
                    'sims/RevC_mid_lba_ms.pkl',
                    'sims/RevC_mid_ms.pkl',
                    'sims/RevC_plains_core_ms.pkl',
                    'sims/RevC_plains_mid_ms.pkl',
                    'sims/RevC_plains_ms.pkl']

# translate between EOP labels and the above files
eop_sa_xlate={'Core': 'sims/RevC_core_ms.pkl',
              'LBA': 'sims/RevC_lba_ms.pkl',
              'Main+LBA': 'sims/RevC_main_lba_ms.pkl',
              'Main': 'sims/RevC_main_ms.pkl',
              'LBA+Mid': 'sims/RevC_mid_lba_ms.pkl',
              'Mid': 'sims/RevC_mid_ms.pkl',
              'Plains+Core': 'sims/RevC_plains_core_ms.pkl',
              'Plains+Mid': 'sims/RevC_plains_mid_ms.pkl',
              'Plains': 'sims/RevC_plains_ms.pkl'}

config_files_rev_d=['sims/RevD_ngvla-revD.core_ms.pkl',
                    'sims/RevD_ngvla-revD.lba_main_ms.pkl',
                    'sims/RevD_ngvla-revD.lba_ms.pkl',
                    'sims/RevD_ngvla-revD.main_ms.pkl',
                    'sims/RevD_ngvla-revD.mid_lba_ms.pkl',
                    'sims/RevD_ngvla-revD.mid_ms.pkl',
                    'sims/RevD_ngvla-revD.spiral_core_ms.pkl',
                    'sims/RevD_ngvla-revD.spiral_mid_ms.pkl',
                    'sims/RevD_ngvla-revD.spiral_ms.pkl']

# probably want to add main no ends; and permutations thereof
config_files_rev_e=['sims/RevE_ngvla-revE.spiral_mid_ms.pkl',
                    'sims/RevE_ngvla-revE.spiral_mid_5core_ms.pkl',
                    'sims/RevE_ngvla-revD.spiral_ms.pkl',
                    'sims/RevE_ngvla-revE.long_mid_ms.pkl',
                    'sims/RevE_ngvla-revE.core_ms.pkl',
                    'sims/RevE_SpMID_CW_28_MOD_ms.pkl',
                    'sims/RevE_ngvla-revE.long_mid_spiral_ms.pkl',
                    'sims/RevE_ngvla-revE.long_main_ms.pkl',
                    'sims/RevE_ngvla-revE.long_mid_spiral_5core_ms.pkl',
                    'sims/RevE_ngvla-revE.spiralPlus5core_ms.pkl',
                    'sims/RevE_ngvla-revE.main_ms.pkl',
                    'sims/RevE_ngvla-revE.long_ms.pkl',
                    'sims/RevE_ngvla-revE.spiral_core_ms.pkl',
                    'sims/RevE_ngvla-revE.coreInner_ms.pkl',
                    'sims/RevE_ngvla-revE.spiral_outerCore_ms.pkl',
                    'sims/RevE_ngvla-revE.mid_spiral_outerCore_ms.pkl',
                    'sims/RevE_ngvla-revE.long_mid_spiral_outerCore_ms.pkl'
                    ]

# old style
sa_list = sau.compute_baselines(config_files)
sau.identify_longest_sa(data[0],sa_list)

# instead read sa's from pickle files (simobserve summaries)
sa_list_e = sau.read_so_pickles(config_files_rev_e)
sa_list_d = sau.read_so_pickles(config_files_rev_d)
sa_list_c = sau.read_so_pickles(config_files_rev_c)

# filter useless short baselines out of LONG and LONG+MID only
filt_list=['sims/RevE_ngvla-revE.long_mid_ms',
           'sims/RevE_ngvla-revE.long_ms',
           'sims/RevE_ngvla-revE.long_ms']
sa_list_e = sau.filter_spurious_shorts(sa_list_e,filt_list)

# longest options
# choose one
#  -4km, 38km, 1200km, 8500km
# more compact arrays
strategy_list = ['lowestAntHrs','minMatching']

# EOP is a list of dictionaries
#  each dictionary has the SG and a list of required observations

fh = open('failedSgs.txt','w')
this_eop = []
sum_e = 0.
my_strategy=1
for sg in data:
  try:
    obs_options = sau.identify_longest_sa(sg,sa_list_e)
    this_obs = sau.choose_longest_sa(sg,obs_options,strategy=strategy_list[my_strategy])
    # add estimated observing time. takes one SG and one observation
    this_obs = sau.scale_eop_time(this_obs,sa_list_e,sa_list_c,eop_sa_xlate)
    this_eop.append(this_obs)
  except:
    print("*** ERROR \n",file=fh)
    print(sg,file=fh)
    print("\n",file=fh)
    continue
  sum_e += this_obs['obsList'][0]['antHrsProxy']
fh.close()
eop_e = this_eop
sau.show_eop(eop_e)
ant_totals = sau.tally_station_usage(this_eop)
sau.plot_station_usage(ant_totals,sort_stations=True)

sg=data[56]
obs_options = sau.identify_longest_sa(sg,sa_list_e)
this_obs = sau.choose_longest_sa(sg,obs_options,strategy=strategy_list[my_strategy])
this_obs = sau.scale_eop_time(this_obs,sa_list_e,sa_list_c,eop_sa_xlate)

this_eop = []
sum_c = 0.
for sg in data:
  try:
    rev_c_eop_sa =  (eop_sa_xlate[sg['Subarry']].split('.pkl'))[0]
    obs_options = sau.identify_longest_sa(sg,sa_list_c,force=rev_c_eop_sa)
    #this_obs = sau.choose_longest_sa(sg,obs_options,strategy = 'minMatching')
    this_obs = sau.choose_longest_sa(sg,obs_options,strategy = 'manual',manual_sa = rev_c_eop_sa)    
    this_obs = sau.scale_eop_time(this_obs,sa_list_c,sa_list_c,eop_sa_xlate)
    this_eop.append(this_obs)
  except:
    print("*** ERROR ")
    print(sg['UseCase'],sg['Subarry'],rev_c_eop_sa)
    for i in range(len(obs_options)):
      print(obs_options[i]['sa_name'])
    continue
  sum_c += this_obs['obsList'][0]['antHrsProxy']
  #sum_c += this_obs['obsList'][0]['Tsub_h']  
eop_c = this_eop
sau.show_eop(this_eop)
ant_totals = sau.tally_station_usage(this_eop)
sau.plot_station_usage(ant_totals)


########
# working out the time estimate here - 
sg = data[nn]
bmaxSg = float(sg['Bmax_km'])*1e3
bminSg = float(sg['Bmin_km'])*1e3
obs_options = sau.identify_longest_sa(sg,sa_list_e)
this_obs = sau.choose_longest_sa(sg,obs_options)
#this_obs = estimate_time(this_obs,eop_c)
rev_c_sa_name = (eop_sa_xlate[this_obs['sg']['Subarry']].split('.pkl'))[0]
rev_c_sa = sa_list_c[rev_c_sa_name]
sa_bmax_c = rev_c_sa['blens'].max()
sa_bmin_c = rev_c_sa['blens'].min()        
rev_c_baselines = rev_c_sa['blens']
these_baselines = this_obs['obsList'][0]['blens']
bl_count_these = np.count_nonzero( (these_baselines > bmaxSg/10.0) & (these_baselines <= bmaxSg))
bl_count_c = np.count_nonzero( (rev_c_baselines > bmaxSg/10.0) & (rev_c_baselines <= bmaxSg))
new_time = sg['Tsub_h'] * bl_count_c / bl_count_these
print(new_time,sg['Tsub_h'],bl_count_these,bl_count_c)
# i think it works : )
#####


This_eop = []
sum_d = 0.
for sg in data:
  try:
    obs_options = sau.identify_longest_sa(sg,sa_list_d)
    this_obs = sau.choose_longest_sa(sg,obs_options)
    this_eop.append(this_obs)
  except:
    print("*** ERROR ")
    print(sg)
    continue
  sum_d += this_obs['obsList'][0]['antHrsProxy']
eop_d = this_eop
sau.show_eop(this_eop)
ant_totals = sau.tally_station_usage(this_eop)
sau.plot_station_usage(ant_totals)


#
# done steps 1may23
#  -tabulate and plot per station
#  -tweak "identify_longest" to get fewer dumbly long ones
#  -paradigm: do min antHrs assignment initially. then look at optimizing.
#
# Next up:
#  -some of the little puzzles from 28apr
#  -make an inner 2km core. run relevant subarrays
#  -go ahead and make outer half core+spiral.
#     -outer half spiral is not that well motivated. it's just a factor of 2.
#  -back up code. gather it all together. summarize. communicate
#  -refactor and optimize code a little
#  -override LONG stupid short baselines
#  -do a first pass at the "splitting things up": ID least and most subscribed.
#     
#
# why does pretty print say "prepare" for UseCase in one row
#
# Next steps28apr23
# -why am i getting both core and core_noTpa? other than that's what i put in
#
# -why did the lba_mod sim crash?
# -why is this one SG crashing?
# -refine heuristic/flowchart for choosing. put in separate scripts
# -actually tabulate
# -add tabulation by station
# -is my antHrsProxy normalized appropriately to compare across schemes?
#    i think it is. --> understand why RevD is worse than C?
# -tabulate multiple observations per SG
# -add SG to tabulation. pretty print it all.
# -compare and understand basic results.
#

#
# next steps 18apr23
#
# -check my code in as a backup. document stuff.
# -loop over SGs
# -translate each into an observation -> obsList
# -implement time tallying for observations (per component-ant-hr)
#    --> add this to identify_longest_sa
#    --> the per component part is tricky with general cfg files
#    --> it also doesn't quite fully measure what you need in general, which is per antenna utilization
# -implement approximate integration time rescaling
# -check approx integ time rescaling with V's memo
# -check for which observations need supplementary shorter spacing obs
#    implement a thing to provide them
#    -requires time ratios...
# -implement one or two basic strategies for how to do the assignment
#    -consider options for how to do this
# -strategies of interest: a) existing EOP
#   b) coarse but new mapping (LONG, MID, MID+SP, MAIN, PLAINS=CORE+SP, ALL, CORE, SBA, TPA)
#   c) more subarrays - no group split - add SP+OUTER_CORE, INNER_CORE, SP+10CORE
#   d) same but group split
#

