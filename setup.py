from setuptools import setup, find_packages

setup(name='deephe3', 
      packages=find_packages(), 
      install_requires=[
          'ase', 
          'pymatgen', 
          'tqdm', 
          'numpy', 
          'torch==1.13.1',  # to support mace
          'torch-scatter', 
          'torch-sparse', 
          'torch-cluster', 
          'torch-spline-conv', 
          'torch-geometric', 
          'e3nn==0.4.4',  # to support mace
          'h5py', 
          'tensorboard', 
          'pathos'
      ]
)
