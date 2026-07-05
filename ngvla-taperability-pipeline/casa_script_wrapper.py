#!/usr/bin/env python

import os
import sys
import subprocess


cwd = os.getcwd()
casa_script_and_args = str(' '.join(sys.argv[1:]))


casa_path = "/home/casa/packages/RHEL7/release/casa-pipeline-release-5.6.2-2.el7/bin/casa"

qsub_file='''#!/bin/sh
#PBS -l mem=85gb,vmem=85gb,nodes=1:ppn=1
#PBS -o run_casa/${{PBS_JOBID}}/${{PBS_JOBNAME}}.out
#PBS -e run_casa/${{PBS_JOBID}}/${{PBS_JOBNAME}}.err


cd {1}/run_casa
mkdir ${{PBS_JOBID}}
cd ${{PBS_JOBID}}

xvfb-run -d {0} --nogui --nologger -c {1}/{2}

'''.format( casa_path, cwd, casa_script_and_args )

with open('qsub.sh','w') as out1:
    out1.writelines(qsub_file)

os.chmod('qsub.sh',0755)

subprocess_command = ["ssh","nmpost-master",'cd {0};/opt/services/torque/bin/qsub'.format(cwd),'qsub.sh']
with open(os.devnull, 'w') as devnull:
    subprocess.call( subprocess_command, stderr=devnull)


#
