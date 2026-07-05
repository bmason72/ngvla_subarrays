#!/usr/bin/env python

import os
from time import sleep
import numpy as np
import subprocess



image_base_name = cwd+'/'+outdir+'/simimage_'

ms_name = outdir+'/'+outdir+'.ms'

vis = cwd+'/'+ms_name

if not os.path.isdir('run_casa'):
    os.mkdir('run_casa')

if 0 not in TA_list:
    TA_list = np.array([0]+list(TA_list))

robust_list = np.linspace(-2,1.6,10)

jobs = []

adaptive_cellsize_argument = '--cs_adapt' if adaptive_cellsize else ''

print('submitting imaging jobs')

taper = 0
weighting='briggs'
for i,robust in enumerate(robust_list):
    sys.stdout.write('\rsubmitting jobs for robust: {0:2d} of {1} '.format(i+1,len(robust_list)))
    sys.stdout.flush()

    submit_string =  "{8}/casa_script_wrapper.py tclean_wrapper.py --vis='{0}' --name='{7}' -i {1} -r {2} -t {3} -w {4} -o {5} -s {6}".format(vis, imsize, robust, taper, weighting, oversample, cellsize, image_base_name, cwd)


    with open(os.devnull, 'w') as devnull:
      output = subprocess.check_output( submit_string.split(), stderr=devnull )
    jobid=output.strip().decode()
    jobs.append(jobid)
    sleep(5)


robust=2.
weighting='natural'
for i,taper in enumerate(TA_list):
    sys.stdout.write('\rsubmitting jobs for natural: {0:2d} of {1} '.format(i+1,len(TA_list)))
    sys.stdout.flush()

    submit_string =  "{8}/casa_script_wrapper.py tclean_wrapper.py --vis='{0}' --name='{7}' -i {1} -r {2} -t {3} -w {4} -o {5} -s {6} {9}".format(vis, imsize, robust, taper, weighting, oversample, cellsize, image_base_name, cwd, adaptive_cellsize_argument)

    with open(os.devnull, 'w') as devnull:
      output = subprocess.check_output( submit_string.split(), stderr=devnull )
    jobid=output.strip().decode()
    jobs.append(jobid)
    sleep(5)



print('\rall imaging jobs submitted                      ')

def queue_wait(jobs):
    job_ids = [job.split('.')[0] for job in jobs]
    qstat_str = 'ssh nmpost-master /opt/services/torque/bin/qstat batch'
    with open(os.devnull, 'w') as devnull:
        qstat_jobs = subprocess.check_output(qstat_str.split(), stderr=devnull)
    qstat_job_ids =  [qj.split('.')[0] for qj in qstat_jobs.decode().split('\n')[:-1]]
    return len( set.intersection( set(job_ids), set(qstat_job_ids)))


njobs = len(jobs)

wait = True

while wait:
    njobs_remaining = queue_wait(jobs)

    if njobs_remaining == 0:
        wait=False

    else:
        sys.stdout.write('\rwaiting for job(s) to finish:  {0} '.format(njobs_remaining))
        sys.stdout.flush()
        sleep(20)


print('\rall imaging jobs completed                        ')

sleep(60)





#
