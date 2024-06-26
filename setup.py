from setuptools import setup, find_packages

setup(name='deephe3', 
      packages=find_packages(), 
      package_data={'deephe3': ['process_data_tools/periodic_table.json']}, 
      install_requires=[
          'ase', 
          'pymatgen', 
          'tqdm', 
          'numpy', 
          'torch>=1.12',  # to support mace
          'torch-scatter', 
          'torch-sparse', 
          'torch-cluster', 
          'torch-spline-conv', 
          'torch-geometric<=2.3.1', 
          'e3nn==0.4.4',  # to support mace
          'h5py', 
          'tensorboard', 
          'pathos'
      ]
)
