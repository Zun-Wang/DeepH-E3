import collections
import itertools
import os
import json
import warnings

import torch
from torch_geometric.data import Data, Batch
import numpy as np
import h5py

from .from_pymatgen.lattice import find_neighbors, _one_to_three, _compute_cube_index, _three_to_one


class Collater:
    def __init__(self, edge_Aij):
        self.edge_Aij = edge_Aij

    def __call__(self, graph_list):
        if self.edge_Aij:
            return Batch.from_data_list(graph_list)
        else:
            return Batch.from_data_list(graph_list)

def load_orbital_types(path, return_orbital_types=False):
    orbital_types = []
    with open(path) as f:
        line = f.readline()
        while line:
            orbital_types.append(list(map(int, line.split())))
            line = f.readline()
    atom_num_orbital = [sum(map(lambda x: 2 * x + 1,atom_orbital_types)) for atom_orbital_types in orbital_types]
    if return_orbital_types:
        return atom_num_orbital, orbital_types
    else:
        return atom_num_orbital

"""
The function get_graph below is extended from "https://github.com/materialsproject/pymatgen", which has the MIT License below

---------------------------------------------------------------------------
The MIT License (MIT)
Copyright (c) 2011-2012 MIT & The Regents of the University of California, through Lawrence Berkeley National Laboratory

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
def get_graph(cart_coords, frac_coords, numbers, stru_id, r, max_num_nbr, edge_Aij, lattice,
              default_dtype_torch, data_folder,
              target_file_name='hamiltonian', inference=False,
              huge_structure=False, only_get_R_list=False, numerical_tol=1e-8, **kwargs):
    assert target_file_name in ['hamiltonians.h5', 'density_matrixs.h5']
    cart_coords_np = cart_coords.detach().numpy()
    frac_coords_np = frac_coords.detach().numpy()
    lattice_np = lattice.detach().numpy()
    num_atom = cart_coords.shape[0]

    center_coords_min = np.min(cart_coords_np, axis=0)
    center_coords_max = np.max(cart_coords_np, axis=0)
    # The lower bound of all considered atom coords
    global_min = center_coords_min - r - numerical_tol
    global_max = center_coords_max + r + numerical_tol
    global_min_torch = torch.tensor(global_min)
    global_max_torch = torch.tensor(global_max)

    reciprocal_lattice = np.linalg.inv(lattice_np).T * 2 * np.pi
    recp_len = np.sqrt(np.sum(reciprocal_lattice ** 2, axis=1))
    maxr = np.ceil((r + 0.15) * recp_len / (2 * np.pi))
    nmin = np.floor(np.min(frac_coords_np, axis=0)) - maxr
    nmax = np.ceil(np.max(frac_coords_np, axis=0)) + maxr
    all_ranges = [np.arange(x, y, dtype='int64') for x, y in zip(nmin, nmax)]
    images = torch.tensor(list(itertools.product(*all_ranges))).type_as(lattice)

    if only_get_R_list:
        return images

    # Filter out those beyond max range
    # coords = (images @ lattice).unsqueeze(1).expand(-1, num_atom, 3) + cart_coords.unsqueeze(0).expand(images.shape[0], num_atom, 3)
    coords = (images @ lattice)[:, None, :] + cart_coords[None, :, :]
    indices = torch.arange(num_atom).unsqueeze(0).expand(images.shape[0], num_atom)
    valid_index_bool = coords.gt(global_min_torch) * coords.lt(global_max_torch)
    valid_index_bool = valid_index_bool.all(dim=-1)
    valid_coords = coords[valid_index_bool]
    valid_indices = indices[valid_index_bool]


    # Divide the valid 3D space into cubes and compute the cube ids
    valid_coords_np = valid_coords.detach().numpy()
    all_cube_index = _compute_cube_index(valid_coords_np, global_min, r)
    nx, ny, nz = _compute_cube_index(global_max, global_min, r) + 1
    all_cube_index = _three_to_one(all_cube_index, ny, nz)
    site_cube_index = _three_to_one(_compute_cube_index(cart_coords_np, global_min, r), ny, nz)
    # create cube index to coordinates, images, and indices map
    cube_to_coords_index = collections.defaultdict(list)  # type: Dict[int, List]

    # for cart_coord, j, k, l in zip(all_cube_index.ravel(), valid_coords_np, valid_images, valid_indices):
    for index, cart_coord in enumerate(all_cube_index.ravel()):
        cube_to_coords_index[cart_coord].append(index)

    # find all neighboring cubes for each atom in the lattice cell
    site_neighbors = find_neighbors(site_cube_index, nx, ny, nz)


    if data_folder is not None:
        atom_num_orbital = load_orbital_types(os.path.join(data_folder, 'orbital_types.dat'))

        with open(os.path.join(data_folder, 'info.json'), 'r') as info_f:
            info_dict = json.load(info_f)
            spinful = info_dict["isspinful"]

        if inference == False:
            Aij_dict = {}
            fid = h5py.File(os.path.join(data_folder, target_file_name), 'r')
            for k, v in fid.items():
                key = json.loads(k)
                key = (key[0], key[1], key[2], key[3] - 1, key[4] - 1)
                if spinful:
                    num_orbital_row = atom_num_orbital[key[3]]
                    num_orbital_column = atom_num_orbital[key[4]]
                    # soc block order:
                    # 1 3
                    # 4 2
                    Aij_value = torch.stack([
                        torch.tensor(v[:num_orbital_row, :num_orbital_column].real, dtype=default_dtype_torch),
                        torch.tensor(v[:num_orbital_row, :num_orbital_column].imag, dtype=default_dtype_torch),
                        torch.tensor(v[num_orbital_row:, num_orbital_column:].real, dtype=default_dtype_torch),
                        torch.tensor(v[num_orbital_row:, num_orbital_column:].imag, dtype=default_dtype_torch),
                        torch.tensor(v[:num_orbital_row, num_orbital_column:].real, dtype=default_dtype_torch),
                        torch.tensor(v[:num_orbital_row, num_orbital_column:].imag, dtype=default_dtype_torch),
                        torch.tensor(v[num_orbital_row:, :num_orbital_column].real, dtype=default_dtype_torch),
                        torch.tensor(v[num_orbital_row:, :num_orbital_column].imag, dtype=default_dtype_torch)
                    ], dim=-1)

                    Aij_dict[key] = Aij_value
                else:
                    Aij_dict[key] = torch.tensor(v, dtype=default_dtype_torch)
            fid.close()
        max_num_orbital = max(atom_num_orbital)


    edge_idx, edge_fea, edge_idx_first = [], [], []
    for index_first, (cart_coord, j) in enumerate(zip(cart_coords, site_neighbors)):
        l1 = np.array(_three_to_one(j, ny, nz), dtype=int).ravel()
        # use the cube index map to find the all the neighboring
        # coords, images, and indices
        ks = [k for k in l1 if k in cube_to_coords_index]
        nn_coords_index = np.concatenate([cube_to_coords_index[k] for k in ks], axis=0)
        nn_coords = valid_coords[nn_coords_index]
        nn_indices = valid_indices[nn_coords_index]
        dist = torch.norm(nn_coords - cart_coord[None, :], dim=1)

        # allow edge with distance = 0
        if True:
            nn_coords = nn_coords.squeeze()
            nn_indices = nn_indices.squeeze()
            dist = dist.squeeze()
        else:
            nonzero_index = dist.nonzero(as_tuple=False)
            nn_coords = nn_coords[nonzero_index]
            nn_coords = nn_coords.squeeze(1)
            nn_indices = nn_indices[nonzero_index].view(-1)
            dist = dist[nonzero_index].view(-1)

        if max_num_nbr > 0:
            if len(dist) >= max_num_nbr:
                dist_top, index_top = dist.topk(max_num_nbr, largest=False, sorted=True)
                edge_idx.extend(nn_indices[index_top])
                edge_idx_first.extend([index_first] * len(index_top))
                edge_fea_single = torch.cat([dist_top.view(-1, 1), nn_coords[index_top] - cart_coord], dim=-1)
                edge_fea.append(edge_fea_single)
            else:
                warnings.warn("Can not find a number of max_num_nbr atoms within the radius")
                edge_idx.extend(nn_indices)
                edge_idx_first.extend([index_first] * len(nn_indices))
                edge_fea_single = torch.cat([dist.view(-1, 1), nn_coords - cart_coord], dim=-1)
                edge_fea.append(edge_fea_single)
        else:
            index_top = dist.lt(r + numerical_tol)
            edge_idx.extend(nn_indices[index_top])
            edge_idx_first.extend([index_first] * len(nn_indices[index_top]))
            edge_fea_single = torch.cat([dist[index_top].view(-1, 1), nn_coords[index_top] - cart_coord], dim=-1)
            edge_fea.append(edge_fea_single)

    edge_fea = torch.cat(edge_fea).type(default_dtype_torch)
    edge_idx_first = torch.LongTensor(edge_idx_first)
    # edge_idx_first = torch.arange(num_atom).unsqueeze(1).expand(-1, max_num_nbr).reshape(-1)
    edge_idx = torch.stack([edge_idx_first, torch.LongTensor(edge_idx)])

    if data_folder is not None:
        if inference:
            data = Data(x=numbers, edge_index=edge_idx, edge_attr=edge_fea, stru_id=stru_id,
                        Aij=None,
                        Aij_mask=None,
                        atom_num_orbital=torch.tensor(atom_num_orbital),
                        **kwargs)
        else:
            if edge_Aij:
                if edge_fea.shape[0] < 0.9 * len(Aij_dict):
                    warnings.warn("Too many Aijs are not included within the radius")
                Aij_mask = torch.zeros(edge_fea.shape[0], dtype=torch.bool)  # Aij_mask[i]代表第 i 个边是否计算了hopping等
                # TODO 没有处理数据集包括不同元素组成的情况
                if spinful:
                    Aij = torch.full([edge_fea.shape[0], max_num_orbital, max_num_orbital, 8], np.nan,
                                     dtype=default_dtype_torch)
                else:
                    Aij = torch.full([edge_fea.shape[0], max_num_orbital, max_num_orbital], np.nan,
                                     dtype=default_dtype_torch)

                inv_lattice = torch.inverse(lattice).type(default_dtype_torch)
                for index in range(edge_fea.shape[0]):
                    # h_{i0, jR} i and j is 0-based index
                    i, j = edge_idx[:, index]
                    cart_coords_i = cart_coords[i]
                    cart_coords_j = cart_coords_i + edge_fea[index, 1:4]
                    cart_coords_j_unit_cell = cart_coords[j]
                    R = torch.round((cart_coords_j - cart_coords_j_unit_cell) @ inv_lattice).int().tolist()

                    key = (*R, i.item(), j.item())
                    if key in Aij_dict:
                        Aij_mask[index] = True
                        if spinful:
                            Aij[index, :atom_num_orbital[i], :atom_num_orbital[j], :] = Aij_dict[key]
                        else:
                            Aij[index, :atom_num_orbital[i], :atom_num_orbital[j]] = Aij_dict[key]
                    else:
                        raise NotImplementedError(
                            "Not yet have support for graph radius including hopping without calculation")

                data = Data(x=numbers, edge_index=edge_idx, edge_attr=edge_fea, stru_id=stru_id,
                            pos=cart_coords.type(default_dtype_torch), lattice=lattice.unsqueeze(0),
                            Aij=Aij, Aij_mask=Aij_mask,
                            atom_num_orbital=torch.tensor(atom_num_orbital),
                            spinful=spinful,
                            **kwargs)
            else:
                if spinful:
                    Aij = torch.full([len(Aij_dict), max_num_orbital, max_num_orbital, 8], np.nan,
                                     dtype=default_dtype_torch)
                else:
                    Aij = torch.full([len(Aij_dict), max_num_orbital, max_num_orbital], np.nan,
                                     dtype=default_dtype_torch)
                Aij_edge_index = torch.full([2, len(Aij_dict)], -1, dtype=torch.int64)
                # Aij_edge_fea = torch.full([len(Aij_dict), 10], np.nan, dtype=default_dtype_torch)
                Aij_edge_fea = torch.full([len(Aij_dict), 4], np.nan, dtype=default_dtype_torch)

                for index_Aij, (key, Aij_value) in enumerate(Aij_dict.items()):
                    i, j = key[3], key[4]
                    Aij_edge_index[0, index_Aij], Aij_edge_index[1, index_Aij] = i, j
                    R = torch.tensor([key[0], key[1], key[2]], dtype=default_dtype_torch)
                    cart_coords_i = cart_coords[i]
                    # cart_coords_j_unit_cell = cart_coords[key[4]]
                    cart_coords_j = cart_coords[j] + R @ lattice.type(default_dtype_torch)
                    edge_fea_single = torch.cat([
                        torch.norm(cart_coords_j - cart_coords_i, dim=-1, keepdim=True),
                        # cart_coords_i,
                        # cart_coords_j,
                        # cart_coords_j_unit_cell
                        cart_coords_j - cart_coords_i,
                    ]).type(default_dtype_torch)
                    Aij_edge_fea[index_Aij] = edge_fea_single

                    if spinful:
                        Aij[index_Aij, :atom_num_orbital[i], :atom_num_orbital[j], :] = Aij_value
                    else:
                        Aij[index_Aij, :atom_num_orbital[i], :atom_num_orbital[j]] = Aij_value

                data = Data(x=numbers, edge_index=edge_idx, edge_attr=edge_fea, stru_id=stru_id,
                            pos=cart_coords.type(default_dtype_torch), lattice=lattice.unsqueeze(0),
                            Aij=Aij, Aij_edge_index=Aij_edge_index, Aij_edge_attr=Aij_edge_fea,
                            atom_num_orbital=torch.tensor(atom_num_orbital),
                            spinful=spinful,
                            **kwargs)
    else:
        data = Data(x=numbers, edge_index=edge_idx, edge_attr=edge_fea, stru_id=stru_id,
                    pos=cart_coords.type(default_dtype_torch), lattice=lattice.unsqueeze(0), **kwargs)
    return data