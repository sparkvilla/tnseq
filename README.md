# Welcome to Gtn: a containerized gc3pie app to run Tnseq (Transposon Sequencing) pipeline

## Requirements

* Docker

* Root folder data structure:

The root folder that contains the data to be analyzed is expected: 

 * To have the following structure:

```root folder
   |-- group folders
       |--dataset folders
          |--fastq files```

 * To adhere to the following naming convention:

A group/sample folder must be named as:

```g-{'group_name'}```
 
A dataset folder must be named as:

```d{number}-g-{'group_name'}```
       
2 FASTQ files for each dataset are expected to be named as:

```d{number}-g-{'group_name'}_R1.fastq
   d{number}-g-{'group_name'}_R2.fastq```

Example:

This is a valid root folder (example_data) structure:

```example_data/
	├── g-control
	│   └── d1-g-control
	│       ├── d1-g-control_R1.fastq
	│       └── d1-g-control_R2.fastq
	└── g-treated
	     └── d1-g-treated
		├── d1-g-treated_R1.fastq
		└── d1-g-treated_R2.fastq```
	
## Run gtn

###  Cloud infrastructure (UZH only)
 
```$ docker run -it -v /path/to/input/:/input -v /path/to/output/:/output -v /path/to/.ssh:/root/.ssh sparkvilla/tnseq```

### Localhost
```$ docker run -it -v /path/to/input/:/input -v /path/to/output/:/output sparkvilla/tnseq localhost```
