#! /usr/bin/env python
#
#   gtn.py -- Front-end script for running Dockerized tn-seq pipelines.
#   
#   Copyright (C) 2018, 2019 S3IT, University of Zurich
#
#   This program is free software: you can redistribute it and/or
#   modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""
Front-end script for submitting multiple `tn-seq pipeline` jobs fetching
docker images from the `sparkvilla/tnseq` docker hub repository. It uses
Snakemake as workflow manager.

It uses the generic `gc3libs.cmdline.SessionBasedScript` framework.

See the output of ``gtn.py --help`` for program usage
instructions.

Example of docker execution:
docker run -i -v /path/to/tn_data/:/input:ro -v /path/to/tn_output/:/output -v /path/to/tn_setup/Snakefile:/setup/ --entrypoint snakemake sparkvilla/tnseq -s /setup/Snakefile

gtn-seq takes "--- files" as input.
"""

# summary of user-visible changes
__changelog__ = """
  2018-11-06:
  * Initial version
"""
__author__ = 'Diego Villamaina <diego.villamaina@zi.uzh.ch>'
__docformat__ = 'reStructuredText'
__version__ = '1.0'

import os
import shutil
import subprocess
import tempfile
import re

# GC3Pie specific libraries
import gc3libs
import gc3libs.exceptions
from gc3libs import Application
from gc3libs.workflow import RetryableTask
from gc3libs.cmdline import SessionBasedScript, existing_file, existing_directory, positive_int
import gc3libs.utils
from gc3libs.quantity import GB
from gc3libs.utils import write_contents

# Defaults
RUN_DOCKER = "./run_docker.sh"
MAX_MEMORY = 32*GB
DEFAULT_GTN_FOLDER = "data/"
DEFAULT_RESULT_FOLDER_LOCAL = "output"
DEFAULT_RESULT_FOLDER_REMOTE = "output/"
DEFAULT_DOCKER_IMAGE = "sparkvilla/tnseq" 
DEFAULT_SNAKEFILE_TEMPLATE = "./Snakefile" 
DEFAULT_SNAKEFILE_TEMPLATE_LOCALHOST = "./Snakefile_Localhost" 
COPY_COMMAND = "cp {0}/* {1} -Rf"
RUN_DOCKER_SCRIPT="""#!/bin/bash

echo "[`date`]: Start processing for pipeline {dataset}"
group=`id -g -n`
i=1
retry=3
while [ $i -le $retry ];
do
  docker pull {container}
  if [ $? -ne 0 ]
  then
  sleep 20s
  i=$((i+1))
  else
  break
  fi
done
echo "Running the container..."
sudo docker run -i --rm -v {data}:/input -v {output}:/output -v {snakefile}:/setup/Snakefile --entrypoint snakemake {container} -s /setup/Snakefile

RET=$?
echo "fixing local filesystem permission"
sudo chown -R $USER:$group {output}
echo "[`date`]: Done with code $RET"
exit $RET
"""

# Utility methods
class Dataset():
    """
    Class to verify the namimg of gtn group, dataset, and FASTQ files. 
       
    A group folder must be named as:
        g-{'group_name'}
 
    A dataset folder must be named as:
        d{number}-g-{'group_name'}
   
    2 FASTQ files for each dataset are expected, named as:
        d{number}-g-{'group_name'}_R1.fq
        d{number}-g-{'group_name'}_R2.fq

    Attributes 
    ---------
   
    name: dataset name
    location: full path to the dataset 
    name_g: group name
    g_location: full path to the group  

    """
    def __init__(self, name, location):
        self.name = name
        self.location = location
        self.g_location = os.path.split(location)[0]
        self.g_name = os.path.split(self.g_location)[1]
        self._verify_dataset(self.g_name, self.g_location)
        self._verify_filename(self.name, self.location)

    def _verify_dataset(self, g_name, g_location):
        valid_dataset = [ data for data in os.listdir(g_location) if re.search("d\d-{0}".format(g_name),data) ]
        assert len(valid_dataset) > 0, \
        "Marker d-{0} not found. Location {1} not a valid dataset.".format(g_name,
                                                                           g_location)
    def _verify_filename(self, name, location):
        valid_filenames = [ f for f in os.listdir(location) if os.path.isfile(os.path.join(location,f)) and 
                                                            re.search("{0}_R\d.fastq".format(name),f)]
        # 2 FASTQ files expected: R1 and R2
        assert len(valid_filenames) > 1, \
        "Marker {0}. Location: {1} not a valid dataset.".format(name,
                                                                location)


def _make_temp_run_docker_file(location, dataset_name, data, output, snakefile, docker):
    """
    Create execution script to control docker execution and post-process
    """
    try:
        (fd, tmp_filename) = tempfile.mkstemp(prefix="{}_drun_".format(dataset_name),dir=location)
        write_contents(tmp_filename, RUN_DOCKER_SCRIPT.format(dataset=dataset_name,
                                                              data=data,
                                                              output=output,
                                                              snakefile=snakefile,
                                                              container=docker))
        os.chmod(tmp_filename, 0755)
        return tmp_filename
    except Exception, ex:
        gc3libs.log.debug("Error creating execution script."
                          "Error type: %s. Message: %s" % (type(ex), ex.message))
        raise

def _get_groups(gtn_input):
    """
    Build a list of (group_path, group_name) from the gtn root folder.
    A group folder must start with: g-
    """
    dirs = os.listdir(gtn_input)
    return [(os.path.join(gtn_input,d),d) for d in dirs if d.startswith('g-')]
    
def _get_datasets(gtn_input):
    """
    Yield all datasets objects.
    """
    for g_path, g_name in _get_groups(gtn_input): 
        for d_name in os.listdir(g_path):
            d_path = os.path.join(g_path,d_name)
            yield Dataset(d_name, d_path)

def _get_group_name(dataset_name):
    split_name=dataset_name.split('-')[1:]
    return '-'.join(split_name) 

def __in_place_change(filename, new_string, old_string):
    """
    Helper:
    Replace an old_string with a new_strig in a file. If the old_string
    is not found an exeption is raised.
    """
    # Read the input filename 
    with open(filename) as f:
        s = f.read()
        if old_string not in s:
            raise ValueError('%s not found in: %s' % (old_string, filename))
                                                        
   # Safely write the changed content, if file and old_string were found
    with open(filename, 'w') as f:
        # This must change to gc3pie logging
        gc3libs.log.debug("Changing %s to %s" % (old_string, new_string))
        s = s.replace(old_string, new_string)
        f.write(s)

def _make_tmp_snakefile(template_snakefile, location, dataset):
    """
    Create a Snakefile for a specific dataset. 
    
    The template_snakefile is expected to have a line:
        SAMPLES = ['DATASET_NAME']
    with 'DATASET_NAME' string to be replaced by dataset.    

    """
    (fd, tmp_filename) = tempfile.mkstemp(prefix="{}_snakef_".format(dataset),dir=location)
    gc3libs.log.debug("Generate a tmp snakefile %s" % (tmp_filename))
    shutil.copy2(template_snakefile, tmp_filename)
    __in_place_change(tmp_filename, new_string=dataset, old_string='DATASET_NAME')
    return tmp_filename

# Custom application class
class GtnApplication(Application):
    """
    Custom class to wrap the execution of the Snakemake pipeline.
    """
    application_name = 'gtn'

    def __init__(self, docker_run, dataset, dataset_name, data_output_dir, snakefile, **extra_args):

        executables = []
        inputs = dict()
        outputs = []

        self.dataset_path = dataset 
        self.dataset_name = dataset_name
        self.data_output_dir = data_output_dir #  extra_args['data_output_dir']
        self.snakefile = snakefile # extra_args['snakefile']
        self.group_name = _get_group_name(dataset_name)

        # Transfer the Snakefile
        inputs[self.snakefile] = os.path.join(DEFAULT_GTN_FOLDER,
                                              os.path.basename(self.snakefile))

        if 'transfer_data' in extra_args.keys() and extra_args['transfer_data']:
            # Input data need to be transferred to compute node
            # include them in the `inputs` list and adapt
            # container execution command
            inputs[self.dataset_path] = os.path.join(DEFAULT_GTN_FOLDER,
                                           os.path.basename(self.dataset_path))
            outputs.append(DEFAULT_RESULT_FOLDER_REMOTE)

            run_docker_input_data = os.path.join('$PWD', DEFAULT_GTN_FOLDER, self.dataset_name)
            run_docker_output_data = os.path.join('$PWD', DEFAULT_RESULT_FOLDER_REMOTE)
            run_docker_snakefile =  os.path.join('$PWD', 
                                                 DEFAULT_GTN_FOLDER, 
                                                 os.path.basename(self.snakefile))
        else:
            # Use local filesystem as reference
            # Define mount points
            run_docker_input_data = os.path.join(self.dataset_path, self.group_name, self.dataset_name)
            run_docker_output_data = os.path.join('$PWD',DEFAULT_RESULT_FOLDER_REMOTE)
            run_docker_snakefile =  os.path.join('$PWD', 
                                                 DEFAULT_GTN_FOLDER, 
                                                 os.path.basename(self.snakefile))

            outputs.append(DEFAULT_RESULT_FOLDER_REMOTE)

        self.run_script = _make_temp_run_docker_file(extra_args['session'],
                                                dataset_name,
                                                run_docker_input_data,
                                                run_docker_output_data,
                                                run_docker_snakefile,
                                                docker_run)

        inputs[self.run_script] = "./run_docker.sh"
        executables.append(inputs[self.run_script])

        Application.__init__(
            self,
            arguments="./run_docker.sh",
            inputs=inputs,
            outputs=outputs,
            stdout='{0}.log'.format(dataset_name),
            join=True,
            executables=executables,
            **extra_args)

    def terminated(self):
        """
        checks exitcode. If out-of-memory is somehow detected (e.g. exit code 137)
        try re-submit increasing memory allocation
        :return: None
        """
        if self.execution.returncode == 137:
            if self.requested_memory and self.requested_memory < MAX_MEMORY:
                self.requested_memory *= 4*GB
                self.execution.returncode = (0, 99)

class GtnLocalhostApplication(Application):
    """ 
    Custom class for execution of Snakemake pipeline on Localhost.
    """
    application_name = 'gtnlocalhost'

    def __init__(self, dataset, dataset_name, data_output_dir, snakefile, **extra_args):

        self.dataset_path = dataset
        self.dataset_name = dataset_name
        self.data_output_dir = data_output_dir #  extra_args['data_output_dir']
        self.snakefile = snakefile # extra_args['snakefile']
        self.group_name = _get_group_name(dataset_name)

        inp = os.path.basename(snakefile) 
        out = os.path.basename(os.path.join(self.data_output_dir,self.group_name))


        Application.__init__(
            self,
            arguments=[
                "snakemake", "-s", inp ],
            stdout='{0}.log'.format(dataset_name),
            inputs=[snakefile],
            outputs=[out],
            output_dir=("g-"+inp))

class GtnRetriableTask(RetryableTask):
    def __init__(self, docker_run, dataset, dataset_name,**extra_args):
        return GtnApplication(docker_run, dataset, dataset_name,**extra_args)


class GtnScript(SessionBasedScript):
    """
    The ``gtn`` command keeps a record of jobs (submitted, executed
    and pending) in a session file (set name with the ``-s`` option); at
    each invocation of the command, the status of all recorded jobs is
    updated, output from finished jobs is collected, and a summary table
    of all known jobs is printed.

    Options can specify a maximum number of jobs that should be in
    'SUBMITTED' or 'RUNNING' state; ``gbids`` will delay submission of
    newly-created jobs so that this limit is never exceeded.

    Once the processing of all chunked files has been completed, ``gtn``
    aggregates them into a single larger output file located in
    'self.params.output'.
    """

    def __init__(self):
        self.gtn_app_execution = DEFAULT_DOCKER_IMAGE
        SessionBasedScript.__init__(
            self,
            version=__version__,
            application=GtnApplication,
            stats_only_for=GtnApplication,
        )

    # def setup(self):
    #     SessionBasedScript.setup(self)

    #     self.add_param("-C", "--continuous", "--watch",
    #                    type=positive_int, dest="wait",
    #                    default=10, metavar="NUM",
    #                    help="Keep running, monitoring jobs and possibly submitting"
    #                    " new ones every NUM seconds. Default: %(default)s seconds."
    #     )

    #     self.add_param("-c", "--cpu-cores", dest="ncores",
    #                    type=positive_int, default=8,  # 8 core
    #                    metavar="NUM",
    #                    help="Set the number of CPU cores required for each job"
    #                    " (default: %(default)s). NUM must be a whole number."
    #     )

    def setup_args(self):

        self.add_param("gtn_input_folder", type=existing_directory,
                       help="Root location of input data. Note: expects folder in "
                            "gtn format")

        self.add_param("gtn_output_folder", type=str, help="Location of the "
                                                            " results.")

    def setup_options(self):
        self.add_param("-F", "--datatransfer", dest="transfer_data",
                       action="store_true", default=False,
                       help="Transfer input data to compute nodes. "
                            "If False, data will be assumed be already visible on "
                            "compute nodes - e.g. shared filesystem. "
                            "Default: %(default)s.")
        
        self.add_param("-app", dest="gtn_app", type=str,
                       default=False,
                       help="Name docker image to use. "
                       " Default: sparkvilla/gtnseq")

        self.add_param("-sfile", metavar="[PATH]",
                       type=existing_file,       
                       dest="snakefile_template", default=False,
                       help="Location of the Snakefile template") 

    def parse_args(self):
        """
        Declare command line arguments. 
        """
        self.params.gtn_output_folder = os.path.abspath(self.params.gtn_output_folder)
        self.params.gtn_input_folder = os.path.abspath(self.params.gtn_input_folder)

    def new_tasks(self, extra):
        """
           create single gtnApplication with all input data
           for each valid input file create a new GtnApplication
        """
        tasks = []
        local_result_folder = os.path.join(self.session.path,
                                           DEFAULT_RESULT_FOLDER_LOCAL)
             
        snakefile_template = os.path.abspath(DEFAULT_SNAKEFILE_TEMPLATE)

        if self.params.resource_name == "localhost":
            snakefile_template = os.path.abspath(DEFAULT_SNAKEFILE_TEMPLATE_LOCALHOST)
        
        for folder in [self.params.gtn_output_folder]:
            if not os.path.isdir(folder):
                try:
                    os.mkdir(folder)
                except OSError, osx:
                    gc3libs.log.error("Failed to create folder {0}. reason: '{1}'".format(folder,
                                                                                          osx))
        if self.params.transfer_data and not os.path.isdir(local_result_folder):
            os.mkdir(os.path.join(local_result_folder))


        #Creates a tn pipeline for each existing dataset
        for dataset in _get_datasets(self.params.gtn_input_folder):
            
            gc3libs.log.info("Dataset: {} was found. Pipeline starting out..".format(dataset.name))
            
            extra_args = extra.copy()

            if not self.params.transfer_data:
                # Use root BIDS folder and set participant label for each task
                dataset.location = self.params.gtn_input_folder

            if self.params.transfer_data:
                extra_args['local_result_folder'] = local_result_folder

            if self.params.gtn_app:
                self.gtn_app_execution = self.params.gtn_app        

            if self.params.snakefile_template:
                snakefile_template = os.path.abspath(self.params.snakefile) 

            snakefile_tmp_path = _make_tmp_snakefile(snakefile_template,
                                                     self.session.path,
                                                     dataset.name)
            
            extra_args['snakefile'] = snakefile_tmp_path   
            extra_args['session'] = self.session.path
            extra_args['transfer_data'] = self.params.transfer_data
            #extra_args['jobname'] = job_name
            extra_args['output_dir'] = os.path.join(os.path.abspath(self.session.path),
                                                    '.compute',
                                                    dataset.name)
            extra_args['data_output_dir'] = os.path.join(os.path.abspath(self.params.gtn_output_folder),
                                                         dataset.name)

            self.log.debug("Creating Application for dataset: {}".format(dataset.name))

            if self.params.resource_name == "localhost":
                tasks.append(GtnLocalhostApplication(
                     dataset.location,
                     dataset.name,
                     **extra_args))

            else:
                tasks.append(GtnApplication(
                    self.gtn_app_execution,
                    dataset.location,
                    dataset.name,
                    **extra_args))

        return tasks

    def after_main_loop(self):
        """
        Merge all results from all subjects into `results` folder
        """

        for task in self.session:
            if isinstance(task, GtnApplication) and task.execution.returncode == 0 and os.path.exists(task.output_dir):
                gc3libs.log.debug("Moving tasks {0} results from {1} to {2}".format(task.dataset_name,
                                                                                    task.output_dir,
                                                                                    self.params.gtn_output_folder))

                gc3libs.utils.movetree(task.output_dir, os.path.join(self.params.gtn_output_folder,task.dataset_name))
                # Cleanup data_output_dir folder
                gc3libs.log.debug("Removing task data_output_dir '{0}'".format(task.output_dir))
                shutil.rmtree(task.output_dir)

# run script, but allow GC3Pie persistence module to access classes defined here;
# for details, see: http://code.google.com/p/gc3pie/issues/detail?id=95
if __name__ == "__main__":
    import gtn 

    gtn.GtnScript().run()
