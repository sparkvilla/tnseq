#FROM ubuntu:16.04
FROM khturner/tn-seq
	
MAINTAINER Diego Villamaina version: 0.1

## Update repo list and install required packages ####
RUN apt-get update -y && apt-get install -y \
    software-properties-common \
    time \
    libffi-dev \
    libssl-dev \
    git-core \
    apt-transport-https \
    wget \
    unzip \
    build-essential \
    python-dev \
    python3-pip \  
    python2.7-dev \ 
    python-pip \
    python-numpy \
    python-matplotlib \
    python-pysam \
    trimmomatic  

## Install snakemake (Require python >= 3.5)
RUN pip3 install snakemake

## Gtnseq app 
COPY Snakefile Snakefile_Localhost gtn.py /gtn/

## Cannot run pip install <package> gives: ImportError: cannot import name main  
RUN pip install --upgrade pip && \
    python -m pip install virtualenv 

###########################    
### Install gc3pie ########
###########################
#RUN wget https://raw.githubusercontent.com/uzh/gc3pie/master/install.py && \
COPY install.py /root/ 
RUN  python /root/install.py --develop -y

## Install packages within gc3pie virtualenv
RUN . /root/gc3pie/bin/activate && \
    pip install os-client-config \ 
    python-novaclient \
    python-neutronclient \
    python-openstackclient

# Add gc3pie.conf file (my own conf for demo)
COPY gc3pie.conf /root/.gc3/

# Add SC auth file
COPY enhancer.ch-openrc.sh run_gtn.sh /

########################

## Install FASTQC ###
WORKDIR /opt
RUN wget http://www.bioinformatics.babraham.ac.uk/projects/fastqc/fastqc_v0.11.8.zip && \
    unzip fastqc_v0.11.8.zip && \
    chmod 755 /opt/FastQC/fastqc && \
    rm /opt/fastqc_v0.11.8.zip 

###### Add tools PATHS to $PATH #########
ENV PATH="/opt/FastQC/:${PATH}"

ENTRYPOINT ["/run_gtn.sh"]
