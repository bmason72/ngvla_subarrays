
# Qs/optimizations
# -need keys into each that are unique and match (including old eop)
# -does main contain the long cases? why only 60?
#

m=sau.read_csv_to_list('memo121/MainCln.csv',fltConv=['Frequency','Resolution','Nantennas','TA_nat','res_nat','level_nat','eta_nat','TA_rob','robust','level_rob','eta_rob'],strict=True,strip=True)

p=sau.read_csv_to_list('memo121/PerformanceCln.csv',fltConv=['Frequency','Resolution','Nantennas','TA_nat','res_nat','level_nat','eta_nat','TA_rob','robust','level_rob','eta_rob'],strict=True,strip=True)

e=sau.read_csv_to_list('memo121/EfficientCln.csv',fltConv=['Frequency','Resolution','Nantennas','TA_nat','res_nat','level_nat','eta_nat','TA_rob','robust','level_rob','eta_rob'],strict=True,strip=True)

# put in by hand to match the data values in sa_name of v's files
sa_components={'SpMID_CW_28_MOD': ['mid'],
               'core':  ['icore','ocore'],
               'coreInner':['icore'],
               'long':['long'],
               'long_main':['long','mid','spiral','icore','ocore'],
               'long-mid-spiral-outer50core':  ['long','mid','spiral','ocore'],
               'long_mid': ['long','mid'],
               'long_mid_spiral': ['long','mid','spiral'],
               'main': ['mid','spiral','ocore','icore'],
               'mid-spiral-outer50core':['mid','spiral','ocore'],
               'spiral': ['spiral'],
               'spiral-outer50core': ['spiral','ocore'],
               'spiral_core':['spiral','ocore','icore'],
               'spiral_mid': ['mid','spiral']}


# probably read eopRevCforced.txt and use that as the basis for times anyway

# 1 - start with MAIN. calculate obs time. do this by matching with EOP
#   1b - add .1 etc to p and e
#   - tally pressure etc
# 2 - add in beam sculpting - repeat
# 3 - by hand: shift things around. cores to efficient or min matching. select LONG/MID to less over-sub'd

eop_old = sau.read_csv_to_list('eopRevCforcedCln.txt',fltConv=['BmaxKm','BminKm','AntHrs','Hrs','Hrs(RevC_eop)'],strict=True,strip=True)

# MAIN
m_merged = [
    {'old': revCobs, 'new': revEobs}
    for revCobs in eop_old
    for revEobs in m
    if revCobs['UseCase'] == revEobs['CaseName']
]

tratio_msculpt=np.array([])
tantratio_msculpt=np.array([])
for i in range(len(m_merged)):
    nant_old = m_merged[i]['old']['AntHrs']/m_merged[i]['old']['Hrs']
    nant_new = m_merged[i]['new']['Nantennas']
    t_old = m_merged[i]['old']['Hrs']
    t_new = nant_old**2 / nant_new**2 *t_old * m_merged[i]['new']['eta_rob']**2
    print(i,m_merged[i]['new']['CaseName'],t_old,t_new)
    tratio_msculpt=np.append(tratio_msculpt,t_new/t_old)
    tantratio_msculpt=np.append(tantratio_msculpt,t_new*nant_new/(t_old*nant_old))
    m_merged[i]['obs']= {'Tsub_h':t_new,'t_old':t_old,'nant_new':nant_new,'nant_old':nant_old,
                         'antennas': sa_components[m_merged[i]['new']['name_sub']]}
    
# PERFORMANCE    
p_merged = [
    {'old': revCobs, 'new': revEobs}
    for revCobs in eop_old
    for revEobs in p
    if revCobs['UseCase'] == revEobs['CaseName']
]

tratio_perf = np.array([])
tantratio_perf = np.array([])
for i in range(len(p_merged)):
    nant_old = p_merged[i]['old']['AntHrs']/p_merged[i]['old']['Hrs']
    nant_new = p_merged[i]['new']['Nantennas']
    t_old = p_merged[i]['old']['Hrs']
    t_new = nant_old**2 / nant_new**2 *t_old * p_merged[i]['new']['eta_rob']**2
    print(i,p_merged[i]['new']['CaseName'],t_old,t_new)
    tratio_perf=np.append(tratio_perf,t_new/t_old)
    tantratio_perf=np.append(tantratio_perf,t_new*nant_new/(nant_old*t_old))
    p_merged[i]['obs']= {'Tsub_h':t_new,'t_old':t_old,'nant_new':nant_new,'nant_old':nant_old,
                         'antennas': sa_components[p_merged[i]['new']['name_sub']]}

# EFFICIENT    
e_merged = [
    {'old': revCobs, 'new': revEobs}
    for revCobs in eop_old
    for revEobs in e
    if revCobs['UseCase'] == revEobs['CaseName']
]

tratio_eff = np.array([])
tantratio_eff = np.array([])
for i in range(len(e_merged)):
    nant_old = e_merged[i]['old']['AntHrs']/e_merged[i]['old']['Hrs']
    nant_new = e_merged[i]['new']['Nantennas']
    t_old = e_merged[i]['old']['Hrs']
    t_new = nant_old**2 / nant_new**2 *t_old * e_merged[i]['new']['eta_rob']**2
    print(i,e_merged[i]['new']['CaseName'],t_old,t_new)
    tratio_eff=np.append(tratio_eff,t_new/t_old)
    tantratio_eff=np.append(tantratio_eff,t_new*nant_new/(nant_old*t_old))
    e_merged[i]['obs']= {'Tsub_h':t_new,'t_old':t_old,'nant_new':nant_new,'nant_old':nant_old,
                         'antennas': sa_components[e_merged[i]['new']['name_sub']]}

mp_merged = [
    {'old': mainObs, 'new': saObs}
    for mainObs in m
    for saObs in p
    if mainObs['CaseName'] == saObs['CaseName']
]
me_merged = [
    {'old': mainObs, 'new': saObs}
    for mainObs in m
    for saObs in e
    if mainObs['CaseName'] == saObs['CaseName']
]

tratio_me = np.array([])
tantratio_me = np.array([])
for i in range(len(me_merged)):
    nant_old = me_merged[i]['old']['Nantennas']
    nant_new = me_merged[i]['new']['Nantennas']
    new_tratio = nant_old**2 / nant_new**2 * (me_merged[i]['new']['eta_rob']/ me_merged[i]['old']['eta_rob'])**2
    new_tantratio = new_tratio * nant_new / nant_old
    tratio_me=np.append(tratio_me,new_tratio)
    tantratio_me=np.append(tantratio_me,new_tantratio)
    print(i,me_merged[i]['new']['CaseName'],me_merged[i]['new']['name_sub'],new_tratio,new_tantratio)

# median ratio 0.91
#  40% of obs show better than 20% or greater impvt (antHrs 0.8 or less)
#  25% show 40% impvt (0.6 or less)


"""
## -- End pasted text --
0 PF3(KSG1).1 mid-spiral-outer50core 1.0270904809911914 0.7535196519421358
1 PF3(KSG1).2 mid-spiral-outer50core 1.0450829648261593 0.76671974522293
2 PF1.1 mid-spiral-outer50core 1.1317760126718088 0.8303216541564205
3 PF1.2 mid-spiral-outer50core 1.0270904809911914 0.7535196519421358
4 PF5.1 main 1.0 1.0
5 PF5.2 mid-spiral-outer50core 1.0450829648261593 0.76671974522293
6 AC5(KSG2).1 spiral_core 1.2505641771874605 0.9817513166705297
7 AC5(KSG2).2 spiral-outer50core 1.7814757024736232 0.9240364624980008
8 AC5(KSG2).3 mid-spiral-outer50core 1.2743602781196617 0.9349278675924622
9 AC1 spiral-outer50core 2.4849253517990073 1.2889098787368682
10 AC2 spiral_core 1.256534240362812 0.9864380952380954
11 AC3 mid-spiral-outer50core 1.2368062257707038 0.9073765301214977
12 AC4 spiral_core 1.0353879612487134 0.8128279321952516
13 AC6 core 0.9543464115252072 0.5083901444573534
14 SS06 mid-spiral-outer50core 1.0348320903818196 0.7591992438782508
15 SF9.1 SpMID_CW_28_MOD 4.692766680153233 1.0087255480703212
16 SF9.2 long_mid_spiral 21.438583669421487 11.019832727272727
17 HiZ1(KSG3.3.1).1 coreInner 1.108934264128129 0.29537034137992224
18 HiZ1(KSG3.3.1).2 core 1.023605444253356 0.5452851432003859
19 HiZ1(KSG3.3.1).3 core 1.0255536222950339 0.5463229576711863
20 HiZ5(KSG3.3.2).1 spiral_core 1.3007490911002946 1.0211488191815397
21 HiZ5(KSG3.3.2).2 spiral_core 1.1691165300174513 0.9178111076772515
22 HiZ5(KSG3.3.2).3 spiral-outer50core 1.833694744569905 0.9511220404077545
23 HiZ2 coreInner 1.0995757046533563 0.29287764095907154
24 HiZ3 coreInner 1.3834837401314959 0.36849800554904333
25 HiZ6 core 1.0646825453231252 0.5671673372282069
26 HiZ7.1 spiral-outer50core 3.2487953419936844 1.6851228175761634
27 HiZ7.2 mid-spiral-outer50core 1.126153504320522 0.8261967298052427
28 HiZ8 mid-spiral-outer50core 1.443500713240596 1.0590168784054839
29 HiZ10 mid-spiral-outer50core 1.1089445350193932 0.8135714579347884
30 NGA8(KSG3.3.3) spiral_core 1.1267990992693373 0.884589947089947
31 NGA2(KSG3.3.4) spiral-outer50core 1.802746865729491 0.935069635962493
32 NGA2(KSG3.3.5) coreInner 19.96051572791628 5.316585964912281          ???????
33 NGA3.1 core 1.0621688346066678 0.5658282576876641
34 NGA3.2 core 0.9677076404141649 0.5155078084449289
35 NGA3.3 spiral_core 0.9623212664199869 0.7554671624231674
36 NGA3.4 spiral_core 1.2525756156539487 0.9833303898591746
37 NGA3.5 mid-spiral-outer50core 1.6091176098252606 1.1805208632830184
38 NGA6.1 main 1.0 1.0
39 NGA6.2 mid-spiral-outer50core 1.0425872452037463 0.764888773350412
40 NGA6.3 mid-spiral-outer50core 1.0565358433263 0.7751220906646219
41 NGA7 core 1.0450829648261593 0.5567264392064587
42 NGA9 core 0.9650414638244164 0.5140875087662778
43 NGA10 coreInner 1.0956431225257353 0.2918301774951725
44 NGA15 mid-spiral-outer50core 1.263206193660127 0.9267447308628035
45 NGA16 long 59.35161600000001 8.32032
46 NGA17 long_mid 26.84330637119114 9.533136842105264
47 TDCP1 (KSG4) spiral_mid 1.319990866769346 0.6168181620417506
48 TDCP2 (KSG5) spiral 5.741823148389261 1.4488712617430846
49 TDCP8 long 60.45580844444446 8.475113333333336
50 TDCP5 core 0.9677076404141649 0.5155078084449289
51 Prepare spiral_core 1.238219566683414 0.972060220573895
52 TDCP17.1 SpMID_CW_28_MOD 4.848445581124745 1.0421892370641974
53 TDCP17.2 long 105.51398400000001 14.791680000000001
54 NGA12 spiral_core 1.2911685897779397 1.0136276779565134
55 TDCP16.3 core 0.9677076404141649 0.5155078084449289
56 TDCP18 SpMID_CW_28_MOD 4.592151141769201 0.9870979089784264
"""

sau.plot_csv_data('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency')
pl.savefig('etaRobVscaledRes.png')
pl.close()
sau.plot_csv_data('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_nat', 'name_sub' ,'Frequency')
reload(sau)
sau.plot_csv_data('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency')
pl.savefig('etaRobVscaledRes.png')
pl.close()
sau.plot_csv_data('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_nat', 'name_sub' ,'Frequency')
pl.savefig('etaNatVscaledRes.png')
reload(sau)
sau.plot_csv_data('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency', yscale='time',nant_col='Nantennas')
sau.plot_csv_data2('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency', yscale='time',nant_col='Nantennas')
reload(sau)
sau.plot_csv_data2('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency', yscale='time',nant_col='Nantennas')
reload(sau)
sau.plot_csv_data2('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency', yscale='time',nant_col='Nantennas')
reload(sau)
sau.plot_csv_data2('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency', yscale='time',nant_col='Nantennas')
pl.savefig('totalTimeSculptedVsScaledResolution.png')
sau.plot_csv_data2('memo121/MainEfficientPerformanceClean.csv', 'Resolution', 'eta_rob', 'name_sub' ,'Frequency', yscale='antTime',nant_col='Nantennas')
pl.savefig('antHrsSculptedVsScaledResolution.png')

###########################

mtots=sau.tally_station_usage2024(m_merged)
ptots=sau.tally_station_usage2024(p_merged)
etots=sau.tally_station_usage2024(e_merged)


mptots=sau.tally_station_usage2024(p_merged)
metots=sau.tally_station_usage2024(e_merged)

"""
total hours by component

scaled from old EOP assuming that represents natural weight
sensitivity calculations

Note i wasn't sure how MAIN dealt with LONG, it didn't appear to do so in any consistent way?

In [400]: mtots
Out[400]: 
{'mid': 47276.46793750458,
 'spiral': 47276.46793750458,
 'ocore': 47276.46793750458,
 'icore': 47276.46793750458,
 'long': 144.31548606865226}

In [401]: ptots
Out[401]: 
{'mid': 27467.968716542815,
 'spiral': 49358.182670264454,
 'ocore': 49358.182670264454,
 'icore': 21982.852885854594,
 'long': 1159.3749286098434}

In [402]: etots
Out[402]: 
{'mid': 43267.70358754618,
 'spiral': 42593.92651465466,
 'ocore': 40447.20681886295,
 'icore': 19892.0711257248,
 'long': 5149.738118886931}

"""



mp_comp_tratio = [
    {'old': revCobs, 'new': revEobs}
    for revCobs in eop_old
    for revEobs in m
    if revCobs['UseCase'] == revEobs['CaseName']
]


