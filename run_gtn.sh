#!/bin/bash

# Run pipeline
source /root/gc3pie/bin/activate 

if [[ $1 == "localhost" ]];
then	
  cd /gtn && python gtn.py /input /output -r localhost -C 20 -N 
else
  source /enhancer.ch-openrc.sh && cd /gtn && python gtn.py /input /output -r sciencecloud -C 20 -N -F -c 8 
fi
