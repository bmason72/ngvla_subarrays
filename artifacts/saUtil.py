import csv
import pylab as pl
import re
import numpy as np
import pickle
import os
import pandas as pd


def execfile(filename, globals=None, locals=None):
    with open(filename, 'r') as f:
        code = compile(f.read(), filename, 'exec')
        exec(code, globals, locals)

def read_so_pickles(files):
    """
    Read pickle files that have summary information extracted from
    simulated CASA snaphot observations for each subarray
    """
    results = {}
    for file in files:
        with open(file,'rb') as f:
            #print(file)
            z=pickle.load(f)
            f.close()
            config = os.path.splitext(file)[0]
            results[config] = {}
            #print(config)
            blens = np.sort(z['q'])
            #print(z['q'])
            results[config]['blens'] = blens
            results[config]['antennas'] = z['antennas']
    return results

def print_antenna_locations(names, locations, selected_antennas, label):
    print(f"{label} AntennaName X Y Z D")
    for index in selected_antennas:
        antenna_name = names[index + 1]
        location = locations[index]
        print(f"{antenna_name} {location[0]} {location[1]} {location[2]}")

def split_by_radius(files):
    results = {}

    for file in files:
        with open(file, "r") as f:
            locations = []
            names = {}
            for line in f:
                if line.strip().startswith("#"):
                    continue

                parts = re.split(r'\s+',line.strip())
                locations.append((float(parts[0]), float(parts[1]), float(parts[2])))
                names[len(locations)] = parts[4]

            center = np.mean(locations, axis=0)
            distances = [np.linalg.norm(np.array(loc) - center) for loc in locations]
            sorted_indices = np.argsort(distances)
            inner_antennas = sorted_indices[:len(sorted_indices) // 2]
            outer_antennas = sorted_indices[len(sorted_indices) // 2:]

            baselines = []
            blens = np.array([])
            for i in inner_antennas:
                for j in inner_antennas:
                    if j > i:
                        dx = locations[i][0] - locations[j][0]
                        dy = locations[i][1] - locations[j][1]
                        dz = locations[i][2] - locations[j][2]
                        baseline_length = np.sqrt(dx*dx + dy*dy + dz*dz)
                        blens = np.append(blens, baseline_length)
                        baseline_vector = (dx, dy, dz)
                        baseline_name = f"{names[i+1]}_{names[j+1]}"
                        baselines.append((baseline_name, baseline_length, baseline_vector))

            results[file] = {}
            results[file]['baselines'] = baselines
            blens.sort()
            results[file]['blens'] = blens

            # Print antenna locations for the inner and outer antennas
            print(f"Selected antennas for file {file}:")
            print_antenna_locations(names, locations, inner_antennas, "Inner")
            print()
            print_antenna_locations(names, locations, outer_antennas, "Outer")
            print()

    return results
    
def compute_baselines(files):
    """
    Read a list of CASA format config files
    return a dictionary (keys are filenames)
     each entry is a dictionary with
      'blens' -  a sorted numpy array of baseline lengths in meters
      'baselines' - a list of actual baselines, entries are
          baselineName, blen[m], (dx,dy,dz)_inMeters 
    May2023 - largely deprecated in favor of using CASA simulations
              to accurately include earth curvature effects for 
              the larger baselines
    """
    results = {}

    for file in files:
        with open(file, "r") as f:
            locations = []
            names = {}
            for line in f:
                # Ignore lines starting with pound sign
                if line.strip().startswith("#"):
                    continue

                parts = re.split(r'\s+',line.strip())
                locations.append((float(parts[0]), float(parts[1]), float(parts[2])))
                # ignore diameter - column 4(index 3)
                names[len(locations)] = parts[4]

            baselines = []
            blens =pl.array([])
            for i in range(len(locations)):
                for j in range(i+1, len(locations)):
                    dx = locations[i][0] - locations[j][0]
                    dy = locations[i][1] - locations[j][1]
                    dz = locations[i][2] - locations[j][2]
                    baseline_length = pl.sqrt(dx*dx + dy*dy + dz*dz)
                    blens = pl.append(blens,baseline_length)
                    baseline_vector = (dx, dy, dz)
                    baseline_name = f"{names[i+1]}_{names[j+1]}"
                    baselines.append((baseline_name, baseline_length, baseline_vector))
            results[file]={}
            results[file]['baselines'] = baselines
            blens.sort()
            results[file]['blens'] = blens
    return results

def getband(freq):
    """
    input freq/GHz - unlike my other getband() which takes Hz : )
    returns [ngvla band as integer, full rx bandwidth in GHz, FOV/arcsec]
    """
    f = freq
    try:
        if ( f < 3.5):
            band = 1
            full_bw = 2.3
        if ( f >= 3.5):
            band = 2
            full_bw = 8.8
        if (f >= 12.3):
            band = 3
            full_bw = 8.2
        if (f >= 20.5):
            band = 4
            full_bw = 13.5
        if (f >= 30.5):
            band = 5
            full_bw = 20.0
        if (f >= 70.0):
            band = 6
            full_bw = 46.0


        # use Band 3 mid band as reference: 3'.56 FWHM at 16 GHz
        full_fov = 3.56 * 60 * (16.0/f)
        return [band,full_bw,full_fov]
    except:
        print("**** Failed to find band for freq [GHz]")
        print(f)
        return -1.0

# directly from "write python code that reads a CSV file into a list, with each row corresponding to a dictionary whose keys are defined by the column headers"
def read_csv_to_list(filename,fltConv=[],strict=False,strip=False):
    with open(filename, newline='',encoding='utf-8-sig') as csvfile:
        lines = [line for line in csvfile if not line.startswith('#')]
        

    fieldnames = [name.strip() for name in lines[0].split(',')]
    like_a_file = '\n'.join(lines[1:]) # don't include 1st line it's the field names
    #reader = csv.DictReader(like_a_file,fieldnames=[name.strip() for name in csvfile.readline().split(',')])
    reader = csv.DictReader(like_a_file.splitlines(), fieldnames=fieldnames)
    
    data = []
    for row in reader:
        readWasOk=True
        for key in fltConv:
            if key in row:
                try:
                    row[key]=float(row[key])
                except:
                    if len(row[key]) == 0:
                        print("ERROR: Empty field ",key)
                        print(row['CaseName'])
                        readWasOk = False
                        continue
                    print("Trying removing comma from field value for row:")
                    print(row['CaseName'])
                    row[key]=float(row[key].replace(",",""))
        if (readWasOk or not(strict)):
            if (strip):
                for key in row:
                    if (isinstance(row[key],str)):
                        row[key] = row[key].strip()
            data.append(row)
    return data

def choose_longest_sa(sg,sa_list,strategy = 'lowestAntHrs',manual_sa=''):
    """
    Return a dictionary with the SG and a list of observations, each of which is a dictionary
    """
    result = {}
    result['sg']=sg

    # beam FWHM in arcsec (comes in in mas)
    AR = float(sg['AR_mas']) * 1e-3
    # freq in hz (comes in GHz)
    freq = float(sg['CenterFreq_GHz'])*1e9
    # lamdda in meters
    lam = 3e8/freq
    # bmax in meters
    bmaxSg = lam / (AR / 206264.8)
    # bmin in meters (comes in in km)
    bminSg = float(sg['Bmin_km'].replace(',','')) * 1e3

    # handle pathological cases
    if (bminSg > bmaxSg):
        print(" *** WARNING: bmin > bmax, setting them equal")
        bminSg = bmaxSg

    # use the passed-in SA
    if strategy == 'manual':
        n_sa = len(sa_list)
        foundSa=False
        for i in range(n_sa):
            if (sa_list[i]['sa_name'] == manual_sa):
                foundSa = True
                best_choice = sa_list[i]
        if not(foundSa):
            print("***** ERROR: failed to find SA ",manual_sa)
            print(sa_list[:]['sa_name'])

    # use the column Subarray_new in the input file
    if strategy == 'sa_new':
        new_sa = sg['Subarray_new']
        n_sa = len(sa_list)
        foundSa=False
        for i in range(n_sa):
            if (sa_list[i]['sa_name'] == new_sa):
                foundSa = True
                best_choice = sa_list[i]
        if not(foundSa):
            print("***** ERROR: failed to find SA ",manual_sa)
            print(sa_list[:]['sa_name'])
        
    # this requires SGbmax >= bmax_SA and gets the closest
    #   match to BMIN as it can
    if strategy == 'minMatching':
        n_sa = len(sa_list)
        bminDiff = np.array([])
        saNames = np.array([])
        # make a list of bminDiff. order corresponds to sa_list entries:
        for i in range(n_sa):
            print(sa_list[i]['sa_name'],sa_list[i]['bmin'],bminSg)
            bminDiff = np.append(bminDiff, bminSg - sa_list[i]['bmin'])
            saNames = np.append(saNames,sa_list[i]['sa_name'])
        # if there are some SA's with bmin_sa < bmin_sg (ie bminDiff > 0)
        #   then choose the closest match. AntHrs is the tiebreaker.
        # if not, then go with the closest match; again antHrs is tiebreaker.
        if np.any( bminDiff > 0):
            smallest = np.min(bminDiff[bminDiff>0])
            good_ind = np.argwhere(bminDiff==smallest)
        else:
            smallest = np.min(np.abs(bminDiff))
            good_ind = np.argwhere(np.abs(bminDiff)==smallest)
        good_ind = good_ind.flatten()
        if (len(good_ind) == 1):
            best_choice = sa_list[good_ind[0]]
        else:
            lowest_antHrs = float('inf')
            for i in good_ind:
                print(i,good_ind)
                option = sa_list[i]
                if option['antHrsProxy'] < lowest_antHrs:
                    best_choice = option
                    lowest_antHrs = option['antHrsProxy']
                    
    if strategy == 'lowestAntHrs':    
        lowest_antHrs = -1
        for option in sa_list:
            if lowest_antHrs < 0:
                lowest_antHrs = option['antHrsProxy']
                best_choice = option
            else:
                if option['antHrsProxy'] < lowest_antHrs:
                    best_choice = option
                    lowest_antHrs = option['antHrsProxy']

    result['obsList']=[best_choice]

    return result

def tally_station_usage(eop):
    """
    """

    station_totals = {}
    for entry in eop:
        for obs in entry['obsList']:
            if ('Tsub_h' in obs.keys()):
                tsub = obs['Tsub_h']
            else:
                print("*** ERROR: missing Tsub_h entry ",obs['sg']['UseCase'])
                continue
            this_station_list = obs['antennas']
            for station in this_station_list:
                #station_totals[station] = station_totals.get(station,0.) + obs['antHrsProxy']/obs['nant']
                station_totals[station] = station_totals.get(station,0.) + tsub

    return station_totals

def tally_station_usage2024(eop,usecaselist=None):
    """
    To do similar with viviana's memo121 result file
    """

    station_totals = {}
    for entry in eop:
        obs=entry['obs']
        useCase=entry['new']['CaseName']
        #if (usecaselist != None and )
        #for obs in entry['obs']:
        if ('Tsub_h' in obs.keys()):
            tsub = obs['Tsub_h']
        else:
            print("*** ERROR: missing Tsub_h entry ",useCase)
            continue
        this_station_list = obs['antennas']
        print(entry['new']['CaseName'],tsub,this_station_list)
        for station in this_station_list:
            station_totals[station] = station_totals.get(station,0.) + tsub

                
    return station_totals

def plot_station_usage(station_totals,sort_stations=False):
    stations = list(station_totals.keys())
    totals = list(station_totals.values())
    if (sort_stations):
        # the crazy pythonic way to co-sort two lists in python
        stations, totals = zip(*sorted(zip(stations,totals), key=lambda pair: pair[0].lower()))
        
    pl.barh(stations,totals)
    pl.xlabel("Hrs")
    pl.ylabel("Atnenna")
    pl.title("Observing time per antenna")
    yticks_positions = range(0,len(stations),7)
    yticks_labels = [stations[i] for i in yticks_positions]
    pl.yticks(yticks_positions,yticks_labels)
    pl.ion()
    pl.show()
    
def show_eop(eop):
    """
    """
    nobs = len(eop)
    print("*** UseCase  , BmaxKm , BminKm, subarray , AntHrs , Hrs , Hrs(RevC_eop), LASOk ")
    # bmax really should be in the SG but for now it's not...
    for row in eop:
        firstObs = row['obsList'][0]
        # 16:-3
        #print(row['sg']['UseCase'],' , ',"{:.1f}".format(firstObs['bmaxSg']/1e3),' , ',"{:.2f}".format(firstObs['bminSg']/1e3),' , ', firstObs['sa_name'][10:-3],' , ',"{:.3f}".format(firstObs['antHrsProxy']),' , ',"{:.4f}".format(100.*firstObs['antHrsProxy']/firstObs['nant']),' , ',firstObs['lasOk'])
        print(row['sg']['UseCase'],' , ',"{:.1f}".format(firstObs['bmaxSg']/1e3),' , ',"{:.2f}".format(firstObs['bminSg']/1e3),' , ', firstObs['sa_name'][10:-3],' , ',"{:.1f}".format(firstObs['Tsub_h']*firstObs['nant']),' , ',"{:.1f}".format(firstObs['Tsub_h']),' , ',"{:.1f}".format(row['sg']['Tsub_h']),' , ',firstObs['lasOk'])
              
def identify_longest_sa(sg,sa_list,fudge_factor=3.0,force=''):
    """
    takes EOP google sheet inputs and maps to a subarray in the list
     -selects ones that have a bmax > the needed bmax (but with the smallest delta)
     -tries to also satisfy LAS
    """
    
    # beam FWHM in arcsec (comes in in mas)
    AR = float(sg['AR_mas']) * 1e-3
    # freq in hz (comes in GHz)
    freq = float(sg['CenterFreq_GHz'])*1e9
    # lamdda in meters
    lam = 3e8/freq
    # bmax in meters
    bmaxSg = lam / (AR / 206264.8)
    # bmin in meters (comes in in km)
    bminSg = float(sg['Bmin_km'].replace(',','')) * 1e3

    # handle pathological cases
    if (bminSg > bmaxSg):
        print(" *** WARNING: bmin > bmax, setting them equal")
        bminSg = bmaxSg
    
    print("****************")
    print(sg['UseCase'])
    print(f" Freq[GHz]: '{freq/1e9}'  Bmin[km]: '{bminSg/1e3}'  Bmax[km]: '{bmaxSg/1e3}'")

    valid_sa_list = []
    # first scan for the closest
    min_ratio = float('inf')
    for this_sa in sa_list.keys():
        this_ratio = (sa_list[this_sa]['blens'].max() / bmaxSg)
        if 1 <= this_ratio < min_ratio:
            min_ratio = this_ratio

    print("Nant BL_10 AntHrs  Hrs  SA UseCase")
    for this_sa in sa_list.keys():
        sa_bmax = sa_list[this_sa]['blens'].max()
        sa_bmin = sa_list[this_sa]['blens'].min()        
        #print(this_sa,bmax,sa_bmax,sa_bmin)
        these_baselines = sa_list[this_sa]['blens']
        bl_count = np.count_nonzero( (these_baselines > bmaxSg/10.0) & (these_baselines <= bmaxSg))
        #        if (sa_bmax >= bmax):
        #        if ( (bl_count > 6) & (sa_bmax >= bmax)):
        if ( (len(force) > 0) & (force == this_sa) ):
            forceThisOne = True
            print(" Forceing ",force,this_sa)
        else:
            forceThisOne = False
        if  ( ((sa_bmax >= bmaxSg) & (sa_bmax < bmaxSg*min_ratio*fudge_factor)) or forceThisOne ):
            #nant = np.sqrt(2.0*len(these_baselines))
            nant = len(sa_list[this_sa]['antennas'])
            print("** ",nant,bl_count,"{:.4f}".format(nant/bl_count),"{:.2f}".format(1000.0/bl_count),this_sa,sg['UseCase'])
            # ant hours proxy is very crude-
            sa_descriptor = {'sa_name':this_sa, 'bmax': sa_bmax, 'bmaxRatio': sa_bmax / bmaxSg, 'bmin': sa_bmin, 'bmaxSg': bmaxSg,
                             'bminSg': bminSg, 'Nbl10': bl_count,'nant':nant,
                             'antHrsProxy': nant/bl_count ,'lasOk': bminSg >= sa_bmin,'blens':these_baselines,'antennas':sa_list[this_sa]['antennas']}
            valid_sa_list.append(sa_descriptor)

    # sort it in increasing order of bmax
    valid_sa_list = sorted(valid_sa_list, key=lambda x: x['lasOk'], reverse=True)
    #valid_sa_list = sorted(valid_sa_list, key=lambda x: x['deltaBmax'])
    valid_sa_list = sorted(valid_sa_list, key=lambda x: x['antHrsProxy'])
    return valid_sa_list


def scale_eop_time(this_obs,sa_list,sa_list_c,eop_sa_xlate):
    # pass in
    #  this_obs['sg','obsList'] - just one obs though
    #  sa_list - current rev subarrays
    #  sa_list_c - read-in pickles characterizing revC SA's. names must correspond
    #     to the keys in the revC EOP via the mapping in eop_sa_xlate
    #
    ########
    # working out the time estimate here - 
    sg = this_obs['sg']
    bmaxSg = float(sg['Bmax_km'])*1e3
    bminSg = float(sg['Bmin_km'].replace(',',''))*1e3

    #obs_options = sau.identify_longest_sa(sg,sa_list)
    #this_obs = sau.choose_longest_sa(sg,obs_options)
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
    this_obs['obsList'][0]['Tsub_h'] = new_time

    return this_obs

def filter_spurious_shorts(sa_list,sa_filt_list,bfilt=150.0):
    """
    """

    for sa_to_filt in sa_filt_list:
        if (sa_to_filt in sa_list):
            z=sa_list[sa_to_filt]['blens']
            z=z[np.where( z > bfilt)]
            sa_list[sa_to_filt]['blens'] = z
        else:
            print("**** WARNING: could not find SA ",sa_to_filt)

    return sa_list

        
import pandas as pd
import matplotlib.pyplot as plt

def plot_csv_data(file_path, x_col, y_col, group_col, freq_col):
    """
    Reads a CSV file and creates a plot with multiple lines.

    Parameters:
    file_path (str): Path to the CSV file.
    x_col (str): Name of the column to use for the x-axis.
    y_col (str): Name of the column to use for the y-axis.
    group_col (str): Name of the column to group by for multiple lines.
    freq_col (str): Name of the column containing the frequency for scaling x-values.
    """
    # Read the CSV file
    df = pd.read_csv(file_path)

    # Check if the specified columns exist in the dataframe
    if x_col not in df.columns or y_col not in df.columns or group_col not in df.columns or freq_col not in df.columns:
        raise ValueError(f"One or more specified columns do not exist in the CSV file: {x_col}, {y_col}, {group_col}, {freq_col}")

    # Scale the x-values
    df[x_col] = df[x_col] * df[freq_col]/30.0

    # Create a plot for each unique value in the group_col
    unique_groups = df[group_col].unique()

    pl.figure(figsize=(10, 6))

    for group in unique_groups:
        group_data = df[df[group_col] == group]
        # Sort the group data by the scaled x-values
        group_data = group_data.sort_values(by=x_col)
        pl.plot(group_data[x_col], group_data[y_col], label=str(group),marker='x')

    pl.xscale('log')
    # Add title and labels
    pl.title(f'{y_col} vs {x_col} (scaled) grouped by {group_col}')
    pl.xlabel(f'Scaled {x_col}')
    pl.ylabel(y_col)
    pl.legend(title=group_col)

    # Show the plot
    pl.show()

import pandas as pd
import matplotlib.pyplot as plt

def plot_csv_data2(file_path, x_col, y_col, group_col, freq_col, yscale='default', nant_col=None):
    """
    Reads a CSV file and creates a plot with multiple lines and markers.

    Parameters:
    file_path (str): Path to the CSV file.
    x_col (str): Name of the column to use for the x-axis.
    y_col (str): Name of the column to use for the y-axis.
    group_col (str): Name of the column to group by for multiple lines.
    freq_col (str): Name of the column containing the frequency for scaling x-values.
    yscale (str): Scaling option for the y-axis. Options are 'default', 'time', 'antTime'.
    nant_col (str): Name of the column containing the number of antennas (required for 'time' and 'antTime' yscale options).
    """
    # Read the CSV file
    df = pd.read_csv(file_path)

    # Check if the specified columns exist in the dataframe
    required_cols = [x_col, y_col, group_col, freq_col]
    if yscale in ['time', 'antTime']:
        required_cols.append(nant_col)
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Column {col} does not exist in the CSV file")

    # Scale the x-values
    df[x_col] = df[x_col] * df[freq_col] / 30.0

    # Scale the y-values based on the yscale option
    if yscale == 'time':
        df[y_col] = (214 / df[nant_col] * df[y_col]) ** 2
    elif yscale == 'antTime':
        df[y_col] = (214 * df[y_col]) ** 2 / df[nant_col]

    # Create a plot for each unique value in the group_col
    unique_groups = df[group_col].unique()

    plt.figure(figsize=(10, 6))

    for group in unique_groups:
        group_data = df[df[group_col] == group]
        # Sort the group data by the scaled x-values
        group_data = group_data.sort_values(by=x_col)
        # Plot with markers
        plt.plot(group_data[x_col], group_data[y_col], marker='o', linestyle='-', markersize=6, label=str(group))

    # Set x-axis to log scale
    plt.xscale('log')
    plt.yscale('log')
    
    # Add title and labels
    y_label = y_col
    if yscale == 'time':
        y_label = f'(214 / {nant_col} x {y_col})^2'
    elif yscale == 'antTime':
        y_label = f'(214 x {y_col})^2 / {nant_col}'
    
    plt.title(f'{y_label} vs {x_col} (scaled) grouped by {group_col}')
    plt.xlabel(f'Scaled {x_col}')
    plt.ylabel(y_label)
    plt.legend(title=group_col)

    # Show the plot
    plt.show()

