import os
from snakemake.remote.HTTP import RemoteProvider as HTTPRemoteProvider

HTTP = HTTPRemoteProvider()
   
SAMPLES = ['DATASET_NAME']

for smp in SAMPLES:
  print("Sample " + smp + " will be processed")

rule final: 
    input:
#        directory('/tmp/MOUSE_GRCm38.p6'),
        expand('/output/{sample}_R1_fastqc.html', sample=SAMPLES),
        expand('/output/{sample}_R2_fastqc.html', sample=SAMPLES),
        expand('/output/{sample}_trimmed_R1.fastq', sample=SAMPLES),
        expand('/output/{sample}_trimmed_R2.fastq', sample=SAMPLES),
        expand('/output/{sample}_trimmed_R1_fastqc.html', sample=SAMPLES),
        expand('/output/{sample}_trimmed_R2_fastqc.html', sample=SAMPLES),
        expand('/output/{sample}_trimmed.fastq', sample=SAMPLES),

rule get_genome:
    input:
        HTTP.remote("cloud.s3it.uzh.ch:8080/v1/AUTH_576f87a2a18948bdb2da11fdcad29ae2/RNA-genome/GENOME.zip", keep_local=True)
    output:
       directory('/tmp/MOUSE_GRCm38.p6')
    priority:1
    run:
        outputName = os.path.join('/tmp',os.path.basename(input[0]))
        shell("mv {input} {outputName} && unzip {outputName} -d /tmp && rm {outputName}")

rule perform_qc:
    input:
       R1='/input/{sample}_R1.fastq',
       R2='/input/{sample}_R2.fastq',
    params:
        out_dir = '/output/'
    output:
       '/output/{sample}_R1_fastqc.html',
       '/output/{sample}_R1_fastqc.zip',
       '/output/{sample}_R2_fastqc.html',
       '/output/{sample}_R2_fastqc.zip',
    shell:
        r'''
            fastqc -o {params.out_dir} -f fastq {input.R1} {input.R2}
         '''

rule trimmometic_run:
     input:
       R1_read='/input/{sample}_R1.fastq',
       R2_read='/input/{sample}_R1.fastq',
     output:
       R1_trimmed='/output/{sample}_trimmed_R1.fastq',
       R2_trimmed='/output/{sample}_trimmed_R2.fastq',
       R1_unpaired='/output/{sample}_trimmed_upaired_R1.fastq',
       R2_unpaired='/output/{sample}_trimmed_upaired_R2.fastq',

     message: """---TRIMMOMATIC---"""
     shell:
        r'''
            java -jar /usr/share/java/trimmomatic-0.35.jar PE -phred33 {input.R1_read} {input.R2_read} {output.R1_trimmed} {output.R1_unpaired} {output.R2_trimmed} {output.R2_unpaired} LEADING:3 TRAILING:3 SLIDINGWINDOW:4:15 MINLEN:30
         '''

rule perform_qc_trimmed:
    input: 
       R1_trimmed_qc='/output/{sample}_trimmed_R1.fastq',
       R2_trimmed_qc='/output/{sample}_trimmed_R2.fastq',
    params:
       out_dir = '/output/'
    output:
       '/output/{sample}_trimmed_R1_fastqc.html',
       '/output/{sample}_trimmed_R1_fastqc.zip',
       '/output/{sample}_trimmed_R2_fastqc.html',
       '/output/{sample}_trimmed_R2_fastqc.zip',
    
    message: """---QC trimmed Data---"""
    shell:
        r'''
            fastqc -outdir {params.out_dir} -f fastq {input.R1_trimmed_qc} {input.R2_trimmed_qc}
         '''

rule merge_trimmed_R1_and_R2:
    input: 
       R1_trimmed_qc='/output/{sample}_trimmed_R1.fastq',
       R2_trimmed_qc='/output/{sample}_trimmed_R2.fastq',
    output:
       merged='/output/{sample}_trimmed.fastq',
   
    message: """---Merge trimmed R1 and R2---"""
    shell:
        r'''
            cat {input.R1_trimmed_qc} {input.R2_trimmed_qc} > {output.merged} 
         '''
