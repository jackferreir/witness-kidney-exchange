[![INFORMS Journal on Computing Logo](https://INFORMSJoC.github.io/logos/INFORMS_Journal_on_Computing_Header.jpg)](https://pubsonline.informs.org/journal/ijoc)

# A Branch-Price-and-Cut Algorithm for the Kidney Exchange Problem

This archive is distributed in association with the [INFORMS Journal on
Computing](https://pubsonline.informs.org/journal/ijoc) under the [MIT License](LICENSE).

The software and data in this repository are a snapshot of the software and data
that were used in the research reported on in the paper 
[A Branch-Price-and-Cut Algorithm for the Kidney Exchange Problem](https://doi.org/10.1287/ijoc.2024.0664) by Matteo Petris, Claudia Archetti, Diego Cattaruzza, Maxime Ogier, Frédéric Semet. 

## Cite

To cite the contents of this repository, please cite both the paper and this repo, using their respective DOIs.

https://doi.org/10.1287/ijoc.2024.0664

https://doi.org/10.1287/ijoc.2024.0664.cd

Below is the BibTex for citing this snapshot of the repository.

```
@misc{Petris2024,
  author =        {Matteo Petris and Claudia Archetti and Diego Cattaruzza and Maxime Ogier and Frédéric Semet},
  publisher =     {INFORMS Journal on Computing},
  title =         {{A Branch-Price-and-Cut Algorithm for the Kidney Exchange Problem}},
  year =          {2025},
  doi =           {10.1287/ijoc.2024.0664.cd},
  url =           {https://github.com/INFORMSJoC/2024.0664},
  note =          {Available for download at https://github.com/INFORMSJoC/2024.0664},
}  
```

## Description

This software provides the implementation of the exact solution method introduced to solve the Kidney Exchange Problem described in the paper.

## Building

The source code is available in folder `src`.

This project requires the following dependencies:
- [Gurobi](https://www.gurobi.com/downloads/) (version 9.5.2 or later)
- [LEMON - Graph Library](https://lemon.cs.elte.hu/trac/lemon/wiki/Downloads) (version 1.3.1 or later)

The code was compiled on a windows machine under a 64-bit version of MS Visual Studio 2019.
Information about how to run the code are provided in `main.cpp`.

## Data and Results

Due to space limitations, in folder `data`, we provide the set of instances named `Pansart et al. 2022`, only.
However, all the instances are available at the following link [https://doi.org/10.57745/IHQAPY](https://doi.org/10.57745/IHQAPY).

File `KEP_detailed_results.xlsx` contains the detailed results of all the tested approached in the paper.

## Support

The code is not supported.
