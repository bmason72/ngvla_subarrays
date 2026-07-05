ngVLA taperability pipeline
version 1.0

Viviana Rosero
9.10.2020


Introduction:

This pipeline produces a taperability curve for a given ngVLA configuration file.  The taperability curve shows the change in sensitivity versus resolution as parameterized by an inefficiency factor, eta.  The inefficiency factor is defined as the increase in image rms compared with natural weighting. The taperability curve is built by creating a simulated measurement set at a chosen frequency which is then imaged using a range of uv-tapers and robust values. 

Each taperability curve has a native resolution (natural and no taper) which gives the highest sensitivity and therefore the smallest inefficiency (normalized to 1). Points to the right and to the left of the native resolution correspond to natural weighting plus a uv-taper and robust weighting with no taper, respectively. Note that these curves provide information about the inefficiency factor needed to reach the target resolution, and not any additional factors based on PSF quality. See ngVLA memos #55 and #72 for further information and examples of taperability curves for many subarrays and combinations of subarrays of the ngVLA. 

Note: the pipeline computes both image rms and stdev, and will print a warning if this ratio exceeds 5%.  This can usually be addressed by increasing the image field of view (i.e., larger image size, less oversampling, and/or by turning on adaptive cellsize).

Contents:

This pipeline package consists of the following files:

run_all.py : script to sequentially execute all steps of the pipeline. 

create_sim_ms.py : uses CASA's sm tool to create a simulated Measurement Set
create_images.py : uses CASA's tclean task to image the simulated MS
analyze_images.py : creates the taperability curve from the set of images

tclean_wrapper : a wrapper script to setup and call tclean
casa_script_wrapper.py : a wrapper script to run casa on the NRAO-NM postprocessing cluster

** Important: run_all.py is the only file the user is intended to edit **


Usage:

1) Place all of the above pipeline files in your desired working directory
2) Copy your desired array configuration file to the working directory
3) Edit run_all.py and adjust the parameters to your desired values.
4) Execute run_all.py with CASA, i.e., one of:  
   casa -c run_all.py (outside casa) or
   execfile('run_all.py') (inside casa)

Note: cluster submission requires SSH keys, see here for more details: https://info.nrao.edu/computing/guide/network-access/sshPages


Outputs:

A folder is created named taperability-{name of configuration file} to store the pipeline output. If the configuration file ends in .cfg the extension is removed. Inside the output folder the pipeline writes:

- a copy of run_all.py at the time it was run

- a copy of the input configuration file at the time it was run

- the simulated measurement set, having the same name as the output folder plus '.ms'

- residual and psf images from tclean. all other tclean outputs are deleted to save space

- taperability_table.txt, an ASCII table containing the taperability results



- taperability_curve.png, a plot of the taperability curve

- psf_cuts.png, a plot of NS and EW cuts through the naturally weighted PSF

A folder named run_casa and a file named qsub.sh are also created to facilitate running casa on the cluster.
